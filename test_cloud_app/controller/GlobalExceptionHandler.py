from spring.annotations.core import ControllerAdvice, ExceptionHandler
from spring.web.result import Result


@ControllerAdvice
class GlobalExceptionHandler:
    """全局异常处理器 - 测试 @ControllerAdvice 和 @ExceptionHandler"""
    
    @ExceptionHandler(ValueError)
    def handle_value_error(self, ex: ValueError):
        """处理 ValueError"""
        return Result.bad_request(message=str(ex))
    
    @ExceptionHandler(TypeError)
    def handle_type_error(self, ex: TypeError):
        """处理 TypeError"""
        return Result.bad_request(message=str(ex))
    
    @ExceptionHandler(RuntimeError)
    def handle_runtime_error(self, ex: RuntimeError):
        """处理 RuntimeError"""
        return Result.error(message=str(ex), code=500)
    
    @ExceptionHandler(Exception)
    def handle_all(self, ex: Exception):
        """处理所有其他异常"""
        return Result.error(message="Internal server error", code=500)
