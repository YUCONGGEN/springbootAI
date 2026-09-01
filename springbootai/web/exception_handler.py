from typing import Type, Callable, Dict, Optional
from springbootai.web.result import Result
from springbootai.logging.context import safe_log_field, sanitize_exception_value
import asyncio
import inspect
import logging


class GlobalExceptionHandler:
    def __init__(self, show_details: bool = False):
        self._handlers: Dict[Type[Exception], Callable] = {}
        self._show_details = show_details
        self._logger = logging.getLogger("Spring.ExceptionHandler")

    def add_exception_handler(self, exception_type: Type[Exception], handler: Callable) -> None:
        self._handlers[exception_type] = handler

    def get_handler(self, exception_type: Type[Exception]) -> Optional[Callable]:
        if exception_type in self._handlers:
            return self._handlers[exception_type]

        # Follow MRO order so a broad Exception handler cannot shadow a more
        # specific handler merely because it was registered first.
        for candidate in exception_type.__mro__:
            if candidate in self._handlers:
                return self._handlers[candidate]

        return None

    def handle(self, exception: Exception) -> Result:
        handler = self.get_handler(type(exception))
        if handler:
            try:
                result = handler(exception)
                if inspect.isawaitable(result):
                    try:
                        asyncio.get_running_loop()
                    except RuntimeError:
                        result = asyncio.run(result)
                    else:
                        if inspect.iscoroutine(result):
                            result.close()
                        raise RuntimeError(
                            "async exception handlers must use handle_async() "
                            "inside an event loop")
                if isinstance(result, Result):
                    return result
                return Result.error(message=str(result))
            except Exception as e:
                self._logger.error(
                    "Exception handler failed error_type=%s message=%s",
                    type(e).__name__, safe_log_field(e),
                )
                return Result.error(message="Internal server error")

        return self._default_handler(exception)

    async def handle_async(self, exception: Exception) -> Result:
        handler = self.get_handler(type(exception))
        if handler:
            try:
                result = handler(exception)
                if inspect.isawaitable(result):
                    result = await result
                if isinstance(result, Result):
                    return result
                return Result.error(message=str(result))
            except Exception as exc:
                self._logger.error(
                    "Exception handler failed error_type=%s message=%s",
                    type(exc).__name__, safe_log_field(exc),
                )
                return Result.error(message="Internal server error")
        return self._default_handler(exception)

    def _default_handler(self, exception: Exception) -> Result:
        sanitized = sanitize_exception_value(exception)
        self._logger.error(
            "Unexpected error error_type=%s message=%s",
            type(exception).__name__, safe_log_field(sanitized),
            exc_info=(type(sanitized), sanitized, sanitized.__traceback__),
        )
        
        if self._show_details:
            return Result.error(
                message=f"Unexpected error: {safe_log_field(sanitized, 1000)}")
        return Result.error(message="Internal server error")

    def register_default_handlers(self) -> None:
        self.add_exception_handler(ValueError, self._handle_value_error)
        self.add_exception_handler(TypeError, self._handle_type_error)
        self.add_exception_handler(Exception, self._default_handler)

    def _handle_value_error(self, exception: ValueError) -> Result:
        return Result.bad_request(message=safe_log_field(exception, 1000))

    def _handle_type_error(self, exception: TypeError) -> Result:
        return Result.bad_request(message=safe_log_field(exception, 1000))

    def set_show_details(self, show_details: bool) -> None:
        self._show_details = show_details
