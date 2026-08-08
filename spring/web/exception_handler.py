from typing import Type, Callable, Dict, Any, Optional
from fastapi import Request
from spring.web.result import Result
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

        for registered_type, handler in self._handlers.items():
            if issubclass(exception_type, registered_type):
                return handler

        return None

    def handle(self, exception: Exception) -> Result:
        handler = self.get_handler(type(exception))
        if handler:
            try:
                result = handler(exception)
                if isinstance(result, Result):
                    return result
                return Result.error(message=str(result))
            except Exception as e:
                self._logger.error(f"Exception handler failed: {str(e)}")
                return Result.error(message="Internal server error")

        return self._default_handler(exception)

    def _default_handler(self, exception: Exception) -> Result:
        import traceback
        self._logger.error(f"Unexpected error: {str(exception)}")
        self._logger.error(traceback.format_exc())
        
        if self._show_details:
            return Result.error(message=f"Unexpected error: {str(exception)}")
        return Result.error(message="Internal server error")

    def register_default_handlers(self) -> None:
        self.add_exception_handler(ValueError, self._handle_value_error)
        self.add_exception_handler(TypeError, self._handle_type_error)
        self.add_exception_handler(Exception, self._default_handler)

    def _handle_value_error(self, exception: ValueError) -> Result:
        return Result.bad_request(message=str(exception))

    def _handle_type_error(self, exception: TypeError) -> Result:
        return Result.bad_request(message=str(exception))

    def set_show_details(self, show_details: bool) -> None:
        self._show_details = show_details
