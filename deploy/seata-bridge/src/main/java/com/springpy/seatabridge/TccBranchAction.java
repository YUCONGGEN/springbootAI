package com.springpy.seatabridge;

import org.apache.seata.rm.tcc.api.BusinessActionContext;
import org.apache.seata.rm.tcc.api.LocalTCC;

@LocalTCC
public interface TccBranchAction {

    boolean prepare(
            BusinessActionContext context,
            String callbackBranchId,
            String resourceId,
            String callbackUrl,
            String serviceName,
            String metadataJson);

    boolean commit(BusinessActionContext context);

    boolean rollback(BusinessActionContext context);
}
