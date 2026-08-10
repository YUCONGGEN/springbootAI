package com.springpy.seatabridge;

import org.apache.seata.rm.tcc.api.BusinessActionContext;
import org.apache.seata.rm.tcc.api.BusinessActionContextParameter;
import org.apache.seata.rm.tcc.api.TwoPhaseBusinessAction;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
public class TccBranchActionImpl implements TccBranchAction {

    private final CallbackClient callbackClient;

    public TccBranchActionImpl(CallbackClient callbackClient) {
        this.callbackClient = callbackClient;
    }

    @Override
    @Transactional
    @TwoPhaseBusinessAction(
            name = "springpyTccBranch",
            commitMethod = "commit",
            rollbackMethod = "rollback",
            useTCCFence = true)
    public boolean prepare(
            BusinessActionContext context,
            @BusinessActionContextParameter(paramName = "callbackBranchId") String callbackBranchId,
            @BusinessActionContextParameter(paramName = "resourceId") String resourceId,
            @BusinessActionContextParameter(paramName = "callbackUrl") String callbackUrl,
            @BusinessActionContextParameter(paramName = "serviceName") String serviceName,
            @BusinessActionContextParameter(paramName = "metadataJson") String metadataJson) {
        return callbackClient.invoke(
                "prepare",
                context,
                callbackBranchId,
                resourceId,
                callbackUrl,
                serviceName,
                metadataJson);
    }

    @Override
    @Transactional
    public boolean commit(BusinessActionContext context) {
        return invokeSecondPhase("commit", context);
    }

    @Override
    @Transactional
    public boolean rollback(BusinessActionContext context) {
        return invokeSecondPhase("rollback", context);
    }

    private boolean invokeSecondPhase(String action, BusinessActionContext context) {
        return callbackClient.invoke(
                action,
                context,
                String.valueOf(context.getActionContext("callbackBranchId")),
                String.valueOf(context.getActionContext("resourceId")),
                String.valueOf(context.getActionContext("callbackUrl")),
                String.valueOf(context.getActionContext("serviceName")),
                String.valueOf(context.getActionContext("metadataJson")));
    }
}
