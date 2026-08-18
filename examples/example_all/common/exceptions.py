"""具有稳定 HTTP 语义的应用异常。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .constants import ApiCode


class ApiError(Exception):
    """Base error used by application code that needs a predictable response.

    框架异常仍由 ``@ControllerAdvice`` 处理。应用服务需要返回明确状态码时，
    可以使用这个异常层次，避免在 Controller 中重复编写映射分支。
    """

    code = ApiCode.BAD_REQUEST
    default_message = "Request failed"

    def __init__(self, message: str | None = None, *, details: Any = None):
        self.details = details
        super().__init__(message or self.default_message)


class BusinessError(ApiError):
    """请求格式正确，但违反了业务规则。"""

    code = 400
    default_message = "Business rule rejected the request"


class NotFoundError(ApiError):
    """请求的领域数据不存在。"""

    code = 404
    default_message = "Resource not found"


class ForbiddenError(ApiError):
    """已认证的调用方无权执行该操作。"""

    code = ApiCode.FORBIDDEN
    default_message = "Forbidden"


class UnauthorizedError(ApiError):
    """调用方必须先完成认证才能访问资源。"""

    code = ApiCode.UNAUTHORIZED
    default_message = "Authentication is required"


class ConflictError(ApiError):
    """请求与资源当前状态冲突。"""

    code = ApiCode.CONFLICT
    default_message = "Resource state conflict"


class ValidationError(ApiError):
    """输入校验失败，可选地携带字段级错误信息。"""

    code = ApiCode.BAD_REQUEST
    default_message = "Validation failed"

    def __init__(
        self,
        message: str | None = None,
        *,
        field_errors: Mapping[str, str] | None = None,
    ):
        self.field_errors = dict(field_errors or {})
        super().__init__(message, details={"fields": self.field_errors} if self.field_errors else None)


__all__ = [
    "ApiError",
    "BusinessError",
    "ConflictError",
    "ForbiddenError",
    "NotFoundError",
    "UnauthorizedError",
    "ValidationError",
]
