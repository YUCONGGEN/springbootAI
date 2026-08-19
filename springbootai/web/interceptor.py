from typing import Callable, List, Optional
from abc import ABC
import fnmatch
import inspect
from fastapi import Request, Response


class HandlerInterceptor(ABC):
    def pre_handle(self, request: Request, handler: Callable) -> bool:
        return True

    def post_handle(self, request: Request, response: Response, handler: Callable) -> None:
        pass

    def after_completion(self, request: Request, response: Response, handler: Callable, exception: Optional[Exception] = None) -> None:
        pass


class InterceptorRegistry:
    def __init__(self):
        self._interceptors: List[HandlerInterceptor] = []
        self._exclude_paths: List[str] = []
        self._include_paths: List[str] = []

    def add_interceptor(self, interceptor: HandlerInterceptor) -> 'InterceptorRegistry':
        self._interceptors.append(interceptor)
        return self

    def exclude_path_patterns(self, *patterns: str) -> 'InterceptorRegistry':
        self._exclude_paths.extend(patterns)
        return self

    def include_path_patterns(self, *patterns: str) -> 'InterceptorRegistry':
        self._include_paths.extend(patterns)
        return self

    def get_interceptors(self) -> List[HandlerInterceptor]:
        return list(self._interceptors)

    def remove_interceptors(self, predicate: Callable[[HandlerInterceptor], bool]) -> None:
        """Remove managed interceptors without exposing the internal list."""
        self._interceptors[:] = [item for item in self._interceptors if not predicate(item)]

    def should_intercept(self, path: str) -> bool:
        if self._include_paths:
            if not any(self._matches(path, p) for p in self._include_paths):
                return False

        if self._exclude_paths:
            if any(self._matches(path, p) for p in self._exclude_paths):
                return False

        return True

    @staticmethod
    def _matches(path: str, pattern: str) -> bool:
        """Match Spring-style ``/**`` patterns and ordinary glob patterns."""
        if pattern in {'/**', '**', '*'}:
            return True
        if pattern.endswith('/**'):
            prefix = pattern[:-3].rstrip('/')
            return path == prefix or path.startswith(prefix + '/')
        return fnmatch.fnmatchcase(path, pattern) or path.startswith(pattern.rstrip('/') + '/')


class InterceptorManager:
    def __init__(self, registry: InterceptorRegistry):
        self.registry = registry

    async def apply_pre_handle(self, request: Request, handler: Callable) -> bool:
        for interceptor in self.registry.get_interceptors():
            if not self.registry.should_intercept(request.url.path):
                continue
            result = interceptor.pre_handle(request, handler)
            if inspect.isawaitable(result):
                result = await result
            if not result:
                return False
        return True

    async def apply_post_handle(self, request: Request, response: Response, handler: Callable) -> None:
        for interceptor in self.registry.get_interceptors():
            if not self.registry.should_intercept(request.url.path):
                continue
            result = interceptor.post_handle(request, response, handler)
            if inspect.isawaitable(result):
                await result

    async def apply_after_completion(self, request: Request, response: Response, handler: Callable, exception: Optional[Exception] = None) -> None:
        for interceptor in self.registry.get_interceptors():
            if not self.registry.should_intercept(request.url.path):
                continue
            result = interceptor.after_completion(request, response, handler, exception)
            if inspect.isawaitable(result):
                await result
