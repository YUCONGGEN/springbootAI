package com.springpy.seatabridge;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.util.Map;
import java.util.regex.Pattern;
import org.apache.seata.core.context.RootContext;
import org.apache.seata.core.model.GlobalStatus;
import org.apache.seata.tm.api.GlobalTransaction;
import org.apache.seata.tm.api.GlobalTransactionContext;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class BridgeController {

    private static final Pattern BRANCH_ID = Pattern.compile("[A-Za-z0-9._-]{1,64}");

    private final TccBranchAction tccBranchAction;
    private final ObjectMapper objectMapper;
    private final String applicationId;
    private final String transactionGroup;
    private final String serverAddr;

    public BridgeController(
            TccBranchAction tccBranchAction,
            ObjectMapper objectMapper,
            @Value("${seata.application-id}") String applicationId,
            @Value("${seata.tx-service-group}") String transactionGroup,
            @Value("${bridge.seata-server-addr}") String serverAddr) {
        this.tccBranchAction = tccBranchAction;
        this.objectMapper = objectMapper;
        this.applicationId = applicationId;
        this.transactionGroup = transactionGroup;
        this.serverAddr = serverAddr;
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, Object>> health() {
        boolean reachable = isCoordinatorReachable();
        Map<String, Object> body = Map.of(
                "status", reachable ? "UP" : "DOWN",
                "mode", "SEATA_TCC",
                "applicationId", applicationId,
                "transactionGroup", transactionGroup,
                "serverAddr", serverAddr);
        return ResponseEntity.status(reachable ? HttpStatus.OK : HttpStatus.SERVICE_UNAVAILABLE).body(body);
    }

    @PostMapping("/api/v1/transactions")
    public Map<String, Object> begin(@RequestBody BeginRequest request) throws Exception {
        require(request.timeoutMs() >= 1000 && request.timeoutMs() <= 600_000,
                "timeoutMs must be between 1000 and 600000");
        require(request.name() != null && !request.name().isBlank() && request.name().length() <= 128,
                "name must contain 1 to 128 characters");
        require(request.applicationId() != null && !request.applicationId().isBlank(),
                "applicationId is required");
        require(transactionGroup.equals(request.transactionGroup()),
                "transactionGroup does not match bridge configuration");

        GlobalTransaction transaction = GlobalTransactionContext.createNew();
        try {
            transaction.begin(request.timeoutMs(), request.name());
            String xid = transaction.getXid();
            require(xid != null && !xid.isBlank(), "Seata returned an empty XID");
            return Map.of("xid", xid, "status", transaction.getLocalStatus().name());
        } catch (Exception exception) {
            if (transaction.getXid() != null) {
                try {
                    transaction.rollback();
                } catch (Exception ignored) {
                    exception.addSuppressed(ignored);
                }
            }
            throw exception;
        } finally {
            RootContext.unbind();
        }
    }

    @PostMapping("/api/v1/transactions/{xid}/branches")
    public Map<String, Object> registerBranch(
            @PathVariable String xid,
            @RequestBody BranchRequest request) throws Exception {
        require(BRANCH_ID.matcher(value(request.branchId())).matches(),
                "branchId must match [A-Za-z0-9._-]{1,64}");
        require(!value(request.resourceId()).isBlank() && request.resourceId().length() <= 256,
                "resourceId must contain 1 to 256 characters");
        require(!value(request.callbackUrl()).isBlank() && request.callbackUrl().length() <= 2048,
                "callbackUrl is required and must not exceed 2048 characters");
        String metadataJson = metadataJson(request.metadata());
        require(metadataJson.length() <= 16_384, "metadata must not exceed 16384 characters");
        require(GlobalTransactionContext.reload(xid).getStatus() == GlobalStatus.Begin,
                "global transaction is not in Begin status");
        require(RootContext.getXID() == null, "bridge thread already contains an XID");

        RootContext.bind(xid);
        try {
            boolean prepared = tccBranchAction.prepare(
                    null,
                    request.branchId(),
                    request.resourceId(),
                    request.callbackUrl(),
                    value(request.serviceName()),
                    metadataJson);
            require(prepared, "TCC prepare callback failed");
            return Map.of(
                    "xid", xid,
                    "branchId", request.branchId(),
                    "status", "REGISTERED");
        } finally {
            RootContext.unbind();
        }
    }

    @PostMapping("/api/v1/transactions/{xid}/commit")
    public Map<String, Object> commit(@PathVariable String xid) throws Exception {
        GlobalTransaction transaction = GlobalTransactionContext.reload(xid);
        transaction.commit();
        GlobalStatus status = transaction.getLocalStatus();
        require(status == GlobalStatus.Committed || status == GlobalStatus.AsyncCommitting,
                "global commit did not complete successfully: " + status);
        return Map.of("xid", xid, "status", status.name(), "success", true);
    }

    @PostMapping("/api/v1/transactions/{xid}/rollback")
    public Map<String, Object> rollback(@PathVariable String xid) throws Exception {
        GlobalTransaction transaction = GlobalTransactionContext.reload(xid);
        transaction.rollback();
        GlobalStatus status = transaction.getLocalStatus();
        require(status == GlobalStatus.Rollbacked || status == GlobalStatus.TimeoutRollbacked,
                "global rollback did not complete successfully: " + status);
        return Map.of("xid", xid, "status", status.name(), "success", true);
    }

    @GetMapping("/api/v1/transactions/{xid}")
    public Map<String, Object> status(@PathVariable String xid) throws Exception {
        GlobalStatus status = GlobalTransactionContext.reload(xid).getStatus();
        return Map.of("xid", xid, "status", status.name());
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> handleException(Exception exception) {
        HttpStatus status = exception instanceof IllegalArgumentException
                ? HttpStatus.BAD_REQUEST
                : HttpStatus.CONFLICT;
        return ResponseEntity.status(status).body(Map.of(
                "error", exception.getClass().getSimpleName(),
                "message", value(exception.getMessage())));
    }

    private String metadataJson(Map<String, Object> metadata) throws JsonProcessingException {
        return objectMapper.writeValueAsString(metadata == null ? Map.of() : metadata);
    }

    private boolean isCoordinatorReachable() {
        String firstAddress = serverAddr.split(",", 2)[0].trim();
        int separator = firstAddress.lastIndexOf(':');
        if (separator <= 0 || separator == firstAddress.length() - 1) {
            return false;
        }
        String host = firstAddress.substring(0, separator);
        int port;
        try {
            port = Integer.parseInt(firstAddress.substring(separator + 1));
        } catch (NumberFormatException exception) {
            return false;
        }
        try (Socket socket = new Socket()) {
            socket.connect(new InetSocketAddress(host, port), 1000);
            return true;
        } catch (Exception exception) {
            return false;
        }
    }

    private static String value(String input) {
        return input == null ? "" : input;
    }

    private static void require(boolean condition, String message) {
        if (!condition) {
            throw new IllegalArgumentException(message);
        }
    }

    public record BeginRequest(
            int timeoutMs,
            String name,
            String applicationId,
            String transactionGroup) {}

    public record BranchRequest(
            String branchId,
            String resourceId,
            String callbackUrl,
            String serviceName,
            Map<String, Object> metadata) {}
}
