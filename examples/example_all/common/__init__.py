"""全局安装并自动执行的应用基础设施。

本包只暴露横切关注点。框架扫描 ``common`` 时会发现
``GlobalExceptionHandler`` 和 ``RequestMonitoringInterceptor`` 并注册为 Bean；
接口代码无需手动调用它们。
"""

from .context import get_request_id, request_scope, reset_request_id, set_request_id
from .constants import ApiCode, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, REQUEST_ID_HEADER
from .advice import GlobalExceptionHandler
from .monitoring import (
    MonitoringController,
    RequestMetric,
    RequestMetricMapper,
    RequestMonitoringInterceptor,
)
from .exceptions import (
    ApiError,
    BusinessError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from .utils import mask_sensitive, new_request_id

__all__ = [
    "ApiError",
    "ApiCode",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "REQUEST_ID_HEADER",
    "GlobalExceptionHandler",
    "BusinessError",
    "ConflictError",
    "ForbiddenError",
    "NotFoundError",
    "UnauthorizedError",
    "ValidationError",
    "RequestMonitoringInterceptor",
    "MonitoringController",
    "RequestMetric",
    "RequestMetricMapper",
    "new_request_id",
    "mask_sensitive",
    "get_request_id",
    "set_request_id",
    "reset_request_id",
    "request_scope",
]
