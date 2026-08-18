from typing import Callable, Any
from abc import ABC, abstractmethod


class MethodInterceptor(ABC):
    @abstractmethod
    def invoke(self, invocation: 'MethodInvocation') -> Any:
        pass


class MethodInvocation:
    def __init__(self, target: Any, method: Callable, args: tuple, kwargs: dict):
        self.target = target
        self.method = method
        self.args = args
        self.kwargs = kwargs

    def proceed(self) -> Any:
        return self.method(*self.args, **self.kwargs)
