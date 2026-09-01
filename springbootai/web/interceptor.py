from typing import Callable, List, Optional
from abc import ABC
import fnmatch
import inspect
from fastapi import Request, Response
from starlette.concurrency import run_in_threadpool


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

    @staticmethod
    async def _invoke(callback: Callable, *args):
        if inspect.iscoroutinefunction(callback):
            return await callback(*args)
        result = await run_in_threadpool(callback, *args)
        if inspect.isawaitable(result):
            return await result
        return result

    async def apply_pre_handle(self, request: Request, handler: Callable) -> bool:
        applied: List[HandlerInterceptor] = []
        setattr(request.state, "springbootai_applied_interceptors", applied)
        for interceptor in self.registry.get_interceptors():
            if not self.registry.should_intercept(request.url.path):
                continue
            result = await self._invoke(interceptor.pre_handle, request, handler)
            if not result:
                return False
            applied.append(interceptor)
        return True

    async def apply_post_handle(self, request: Request, response: Response, handler: Callable) -> None:
        applied = getattr(
            request.state, "springbootai_applied_interceptors", None)
        interceptors = (list(reversed(applied)) if applied is not None
                        else list(reversed(self.registry.get_interceptors())))
        for interceptor in interceptors:
            await self._invoke(interceptor.post_handle, request, response, handler)

    async def apply_after_completion(self, request: Request, response: Response, handler: Callable, exception: Optional[Exception] = None) -> None:
        applied = getattr(
            request.state, "springbootai_applied_interceptors", None)
        interceptors = (list(reversed(applied)) if applied is not None
                        else list(reversed(self.registry.get_interceptors())))
        try:
            for interceptor in interceptors:
                await self._invoke(
                    interceptor.after_completion,
                    request, response, handler, exception,
                )
        finally:
            if applied is not None:
                applied.clear()
