"""示例应用共享常量。

这里只放应用约定。SpringBootAI 已提供的值应直接从框架导入，避免重复定义。
"""

from enum import IntEnum

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100
REQUEST_ID_HEADER = "X-Request-ID"


class ApiCode(IntEnum):
    """应用异常使用的兼容 HTTP 的结果码。

    统一集中命名后，服务代码更清晰，同时 ``Result`` 仍可使用普通 HTTP 状态码。
    """

    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    CONFLICT = 409
    TOO_MANY_REQUESTS = 429
    INTERNAL_ERROR = 500
    SERVICE_UNAVAILABLE = 503

__all__ = ["ApiCode", "DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "REQUEST_ID_HEADER"]
