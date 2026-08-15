"""
异常处理控制器 — 测试 @ControllerAdvice, @ExceptionHandler, @ResponseStatus
"""
from spring.annotations.core import (
    ControllerAdvice, ExceptionHandler, ResponseStatus,
    RestController, GetMapping, Slf4j,
)
from spring.web.result import Result


# ==================== @ControllerAdvice 全局异常处理 ====================

@ControllerAdvice
@Slf4j
class GlobalExceptionHandler:
    """全局异常处理器 — @ControllerAdvice + @ExceptionHandler"""

    @ExceptionHandler(ValueError)
    @ResponseStatus(400)
    def handle_value_error(self, ex: ValueError):
        self.logger.warning(f"ValueError: {ex}")
        return Result.bad_request(message=str(ex))

    @ExceptionHandler(TypeError)
    @ResponseStatus(400)
    def handle_type_error(self, ex: TypeError):
        self.logger.warning(f"TypeError: {ex}")
        return Result.bad_request(message=f"Type error: {ex}")

    @ExceptionHandler(KeyError)
    @ResponseStatus(400)
    def handle_key_error(self, ex: KeyError):
        self.logger.warning(f"KeyError: {ex}")
        return Result.bad_request(message=f"Missing key: {ex}")

    @ExceptionHandler(PermissionError)
    @ResponseStatus(403)
    def handle_permission_error(self, ex: PermissionError):
        self.logger.warning(f"PermissionError: {ex}")
        return Result.forbidden(message=str(ex))

    @ExceptionHandler(RuntimeError)
    @ResponseStatus(500)
    def handle_runtime_error(self, ex: RuntimeError):
        self.logger.error(f"RuntimeError: {ex}")
        return Result.error(message=str(ex), code=500)

    @ExceptionHandler(Exception)
    @ResponseStatus(500)
    def handle_all_exceptions(self, ex: Exception):
        self.logger.error(f"Unhandled exception: {type(ex).__name__}: {ex}")
        return Result.internal_error(message="Internal server error")


# ==================== 异常触发端点 ====================

@RestController
@Slf4j
class ErrorTriggerController:
    """用于触发各类异常的测试端点"""

    @GetMapping("/api/errors/value")
    def trigger_value_error(self):
        raise ValueError("This is a test ValueError")

    @GetMapping("/api/errors/type")
    def trigger_type_error(self):
        raise TypeError("This is a test TypeError")

    @GetMapping("/api/errors/runtime")
    def trigger_runtime_error(self):
        raise RuntimeError("This is a test RuntimeError")

    @GetMapping("/api/errors/custom")
    def trigger_custom(self, error_type: str = "value"):
        if error_type == "value":
            raise ValueError("Triggered ValueError")
        elif error_type == "permission":
            raise PermissionError("Triggered PermissionError")
        elif error_type == "key":
            raise KeyError("Triggered KeyError")
        else:
            raise RuntimeError("Triggered RuntimeError")
