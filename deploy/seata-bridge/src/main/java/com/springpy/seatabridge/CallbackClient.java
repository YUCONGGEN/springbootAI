package com.springpy.seatabridge;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Arrays;
import java.util.Locale;
import java.util.Set;
import java.util.stream.Collectors;
import org.apache.seata.rm.tcc.api.BusinessActionContext;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class CallbackClient {

    private static final Logger LOGGER = LoggerFactory.getLogger(CallbackClient.class);

    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;
    private final Set<String> allowedHosts;
    private final String callbackToken;
    private final Duration requestTimeout;

    public CallbackClient(
            ObjectMapper objectMapper,
            @Value("${bridge.callback-allowed-hosts:}") String allowedHosts,
            @Value("${bridge.token:}") String callbackToken,
            @Value("${bridge.callback-timeout-ms:5000}") long callbackTimeoutMs) {
        this.objectMapper = objectMapper;
        this.allowedHosts = Arrays.stream(allowedHosts.split(","))
                .map(String::trim)
                .map(value -> value.toLowerCase(Locale.ROOT))
                .filter(value -> !value.isEmpty())
                .collect(Collectors.toUnmodifiableSet());
        this.callbackToken = callbackToken;
        this.requestTimeout = Duration.ofMillis(Math.max(100, callbackTimeoutMs));
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(3))
                .followRedirects(HttpClient.Redirect.NEVER)
                .build();
    }

    public boolean invoke(
            String action,
            BusinessActionContext context,
            String callbackBranchId,
            String resourceId,
            String callbackUrl,
            String serviceName,
            String metadataJson) {
        try {
            URI baseUri = validateCallbackUri(callbackUrl);
            String encodedBranchId = URLEncoder.encode(callbackBranchId, StandardCharsets.UTF_8);
            URI callbackUri = URI.create(
                    baseUri.toString().replaceAll("/+$", "")
                            + "/" + encodedBranchId + "/" + action);

            ObjectNode payload = objectMapper.createObjectNode();
            payload.put("xid", context.getXid());
            payload.put("branchId", callbackBranchId);
            payload.put("seataBranchId", context.getBranchId());
            payload.put("resourceId", resourceId);
            payload.put("serviceName", serviceName);
            payload.set("metadata", parseMetadata(metadataJson));

            HttpRequest request = HttpRequest.newBuilder(callbackUri)
                    .timeout(requestTimeout)
                    .header("Content-Type", "application/json")
                    .header("Accept", "application/json")
                    .header("X-Seata-Bridge-Token", callbackToken)
                    .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(payload)))
                    .build();
            HttpResponse<String> response = httpClient.send(
                    request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            boolean success = response.statusCode() >= 200 && response.statusCode() < 300;
            if (!success) {
                LOGGER.error(
                        "TCC {} callback rejected: xid={}, branch={}, status={}",
                        action,
                        context.getXid(),
                        callbackBranchId,
                        response.statusCode());
            }
            return success;
        } catch (Exception exception) {
            LOGGER.error(
                    "TCC {} callback failed: xid={}, branch={}",
                    action,
                    context.getXid(),
                    callbackBranchId,
                    exception);
            return false;
        }
    }

    private URI validateCallbackUri(String callbackUrl) {
        URI uri = URI.create(callbackUrl);
        String scheme = uri.getScheme();
        String host = uri.getHost();
        if (host == null || !("http".equalsIgnoreCase(scheme) || "https".equalsIgnoreCase(scheme))) {
            throw new IllegalArgumentException("callbackUrl must be an absolute HTTP(S) URL");
        }
        String normalizedHost = host.toLowerCase(Locale.ROOT);
        if (!allowedHosts.contains("*") && !allowedHosts.contains(normalizedHost)) {
            throw new IllegalArgumentException("callback host is not allow-listed: " + host);
        }
        if (uri.getUserInfo() != null || uri.getFragment() != null) {
            throw new IllegalArgumentException("callbackUrl must not contain user info or a fragment");
        }
        return uri;
    }

    private JsonNode parseMetadata(String metadataJson) throws JsonProcessingException {
        if (metadataJson == null || metadataJson.isBlank()) {
            return objectMapper.createObjectNode();
        }
        return objectMapper.readTree(metadataJson);
    }
}
