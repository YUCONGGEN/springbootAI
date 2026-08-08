from typing import Generic, TypeVar, Optional, Any
from pydantic import BaseModel

T = TypeVar('T')


class Result(BaseModel, Generic[T]):
    code: int
    message: str
    data: Optional[T] = None

    @classmethod
    def success(cls, data: Optional[T] = None, message: str = "success") -> "Result[T]":
        return cls(code=200, message=message, data=data)

    @classmethod
    def error(cls, code: int = 500, message: str = "error") -> "Result[T]":
        return cls(code=code, message=message, data=None)

    @classmethod
    def bad_request(cls, message: str = "Bad Request") -> "Result[T]":
        return cls(code=400, message=message, data=None)

    @classmethod
    def unauthorized(cls, message: str = "Unauthorized") -> "Result[T]":
        return cls(code=401, message=message, data=None)

    @classmethod
    def forbidden(cls, message: str = "Forbidden") -> "Result[T]":
        return cls(code=403, message=message, data=None)

    @classmethod
    def not_found(cls, message: str = "Not Found") -> "Result[T]":
        return cls(code=404, message=message, data=None)

    @classmethod
    def internal_error(cls, message: str = "Internal Server Error") -> "Result[T]":
        return cls(code=500, message=message, data=None)

    def is_success(self) -> bool:
        return self.code == 200

    def is_error(self) -> bool:
        return self.code != 200
