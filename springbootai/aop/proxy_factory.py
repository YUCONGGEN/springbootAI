from typing import Type, Any, Dict, Callable, List
from springbootai.aop.method_interceptor import MethodInterceptor, MethodInvocation
import functools
import inspect


class ProxyFactory:
    def __init__(self):
        self._interceptors: Dict[str, List[MethodInterceptor]] = {}
        self._cache_storage: Dict[str, Any] = {}

    def add_interceptor(self, method_name: str, interceptor: MethodInterceptor) -> None:
        if method_name not in self._interceptors:
            self._interceptors[method_name] = []
        self._interceptors[method_name].append(interceptor)

    def create_proxy(self, target: Any, target_class: Type) -> Any:
        for name, method in inspect.getmembers(target_class):
            if not name.startswith('_') and inspect.isfunction(method):
                interceptors = self._interceptors.get(name, [])
                if interceptors:
                    wrapped_method = self._wrap_method(target, method, interceptors)
                    setattr(target, name, wrapped_method)
        return target

    def _wrap_method(self, target: Any, method: Callable, interceptors: List[MethodInterceptor]) -> Callable:
        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            invocation = MethodInvocation(target, method, args, kwargs)
            
            def proceed():
                return invocation.proceed()
            
            invocation.proceed = proceed
            
            result = invocation.proceed()
            
            for interceptor in reversed(interceptors):
                result = interceptor.invoke(invocation)
            
            return result

        return wrapper

    def get_cache(self, key: str) -> Any:
        return self._cache_storage.get(key)

    def set_cache(self, key: str, value: Any) -> None:
        self._cache_storage[key] = value

    def clear_cache(self, key: str = None) -> None:
        if key:
            self._cache_storage.pop(key, None)
        else:
            self._cache_storage.clear()
