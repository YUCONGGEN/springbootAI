"""应用级全局 Web 异常处理 Advice。

异常转换属于应用基础设施职责。Controller 只负责暴露接口，并在示例中触发异常。
"""

from springbootai.annotations import ControllerAdvice, ExceptionHandler, ResponseStatus, Slf4j
from springbootai.web import Result
from .exceptions import ApiError


@ControllerAdvice()
@Slf4j()
class GlobalExceptionHandler:
    """将应用异常和基础请求错误统一转换为 ``Result``。"""

    @ExceptionHandler(ApiError)
    @ResponseStatus(400)
    def handle_api_error(self, ex: ApiError):
        self.logger.warning("ApiError: %s", ex)
        return Result.error(code=int(ex.code), message=str(ex))

    @ExceptionHandler(ValueError)
    @ResponseStatus(400)
    def handle_value_error(self, ex: ValueError):
        self.logger.warning("ValueError: %s", ex)
        return Result.bad_request(message=str(ex))

    @ExceptionHandler(TypeError)
    @ResponseStatus(400)
    def handle_type_error(self, ex: TypeError):
        self.logger.warning("TypeError: %s", ex)
        return Result.bad_request(message=f"Type error: {ex}")

    @ExceptionHandler(KeyError)
    @ResponseStatus(400)
    def handle_key_error(self, ex: KeyError):
        self.logger.warning("KeyError: %s", ex)
        return Result.bad_request(message=f"Missing key: {ex}")

    @ExceptionHandler(PermissionError)
    @ResponseStatus(403)
    def handle_permission_error(self, ex: PermissionError):
        self.logger.warning("PermissionError: %s", ex)
        return Result.forbidden(message=str(ex))

    @ExceptionHandler(RuntimeError)
    @ResponseStatus(500)
    def handle_runtime_error(self, ex: RuntimeError):
        self.logger.error("RuntimeError: %s", ex)
        return Result.error(message=str(ex), code=500)

    @ExceptionHandler(Exception)
    @ResponseStatus(500)
    def handle_all_exceptions(self, ex: Exception):
        self.logger.error("Unhandled exception: %s: %s", type(ex).__name__, ex)
        return Result.internal_error(message="Internal server error")


__all__ = ["GlobalExceptionHandler"]
