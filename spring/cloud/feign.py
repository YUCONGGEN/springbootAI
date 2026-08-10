"""
Feign远程调用模块
提供声明式HTTP客户端功能
"""
import requests
import logging
import json
import inspect
from dataclasses import asdict, is_dataclass
from typing import Dict, Any, Optional, Type, Callable
from starlette.concurrency import run_in_threadpool
from spring.cloud.load_balancer import LoadBalancer

logger = logging.getLogger("Spring.Cloud.Feign")


class FeignClientProxy:
    """Feign客户端代理"""
    
    def __init__(
        self,
        service_name: str,
        path: str = "",
        url: str = "",
        fallback: Type = None,
        fallback_factory: Type = None,
        timeout: float = 30,
        pool_connections: int = 20,
        pool_maxsize: int = 100,
    ):
        self.service_name = service_name
        self.path = path
        self.url = url
        self.fallback = fallback
        self.fallback_factory = fallback_factory
        self.timeout = timeout
        self._load_balancer = LoadBalancer()
        self._session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=max(1, int(pool_connections)),
            pool_maxsize=max(1, int(pool_maxsize)),
            max_retries=0,
            pool_block=True,
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "FeignClientProxy":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
    
    def _get_base_url(self) -> str:
        """获取基础URL"""
        if self.url:
            return self.url
        
        # 使用负载均衡获取服务实例
        instances = self._load_balancer.get_instances(self.service_name)
        if not instances:
            raise Exception(f"No instances available for service: {self.service_name}")
        
        instance = self._load_balancer.select_instance(instances)
        return f"http://{instance['ip']}:{instance['port']}"
    
    def _build_url(self, endpoint: str) -> str:
        """构建完整URL"""
        base_url = self._get_base_url()
        full_path = self.path.rstrip('/') + '/' + endpoint.lstrip('/')
        return f"{base_url.rstrip('/')}/{full_path.lstrip('/')}"

    @staticmethod
    def _jsonable(value: Any) -> Any:
        if is_dataclass(value) and not isinstance(value, type):
            return asdict(value)
        if hasattr(value, 'model_dump') and callable(value.model_dump):
            return value.model_dump()
        if hasattr(value, 'dict') and callable(value.dict):
            return value.dict()
        return value

    def _call_fallback(self, fallback_method: Optional[str], error: Exception, args, kwargs):
        if not self.fallback:
            raise error
        try:
            if self.fallback_factory:
                factory = self.fallback_factory()
                fallback_instance = factory.create(error) if hasattr(factory, 'create') else factory(error)
            else:
                fallback_instance = self.fallback()
        except TypeError:
            fallback_instance = self.fallback()
        method = getattr(fallback_instance, fallback_method or '', None)
        if not callable(method):
            raise error
        return method(*args, **kwargs)

    def request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_data: Any = None,
        data: Any = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        fallback_method: Optional[str] = None,
        call_args: tuple = (),
        call_kwargs: Optional[dict] = None,
    ) -> Any:
        """Execute a declared Feign request and invoke its fallback if needed."""
        url = self._build_url(endpoint)
        call_kwargs = call_kwargs or {}

        # 自动注入分布式事务XID头
        req_headers = dict(headers) if headers else {}
        try:
            from spring.cloud.seata import seata_manager
            xid = seata_manager.get_current_tx_id()
            if xid:
                seata_manager.inject_xid_headers(req_headers, xid)
        except Exception:
            pass

        # 自动注入追踪头（W3C traceparent）
        try:
            from spring.cloud.tracer import get_tracer
            tracer = get_tracer()
            if tracer.enabled:
                tracer.inject_headers(req_headers)
        except Exception:
            pass

        try:
            response = self._session.request(
                method.upper(),
                url,
                params=params,
                json=self._jsonable(json_data) if json_data is not None else None,
                data=data,
                headers=req_headers,
                timeout=self.timeout if timeout is None else timeout,
            )
            response.raise_for_status()
            if not response.content:
                return None
            try:
                return response.json()
            except (ValueError, json.JSONDecodeError):
                return response.text
        except Exception as error:
            logger.error("Feign %s request failed: %s, error: %s", method, url, error)
            return self._call_fallback(fallback_method, error, call_args, call_kwargs)

    async def arequest(self, method: str, endpoint: str, **kwargs) -> Any:
        """Execute the synchronous requests client without blocking the ASGI loop."""
        return await run_in_threadpool(self.request, method, endpoint, **kwargs)
    
    def get(self, endpoint: str, params: Dict[str, Any] = None, headers: Dict[str, str] = None) -> Any:
        """
        发送GET请求
        
        Args:
            endpoint: 端点路径
            params: 查询参数
            headers: 请求头
        
        Returns:
            响应数据
        """
        url = self._build_url(endpoint)
        
        try:
            response = self._session.get(
                url, params=params, headers=headers, timeout=self.timeout
            )
            response.raise_for_status()
            
            try:
                return response.json()
            except json.JSONDecodeError:
                return response.text
        except Exception as e:
            logger.error(f"Feign GET request failed: {url}, error: {e}")
            
            # 尝试降级处理
            if self.fallback:
                fallback_instance = self.fallback()
                method = getattr(fallback_instance, endpoint.replace('/', '_'), None)
                if method and callable(method):
                    return method(params=params, headers=headers)
            
            raise
    
    def post(self, endpoint: str, data: Dict[str, Any] = None, json_data: Dict[str, Any] = None, 
             headers: Dict[str, str] = None) -> Any:
        """
        发送POST请求
        
        Args:
            endpoint: 端点路径
            data: 表单数据
            json_data: JSON数据
            headers: 请求头
        
        Returns:
            响应数据
        """
        url = self._build_url(endpoint)
        
        try:
            response = self._session.post(
                url, data=data, json=json_data, headers=headers, timeout=self.timeout
            )
            response.raise_for_status()
            
            try:
                return response.json()
            except json.JSONDecodeError:
                return response.text
        except Exception as e:
            logger.error(f"Feign POST request failed: {url}, error: {e}")
            
            if self.fallback:
                fallback_instance = self.fallback()
                method = getattr(fallback_instance, endpoint.replace('/', '_'), None)
                if method and callable(method):
                    return method(data=data, json_data=json_data, headers=headers)
            
            raise
    
    def put(self, endpoint: str, data: Dict[str, Any] = None, json_data: Dict[str, Any] = None,
            headers: Dict[str, str] = None) -> Any:
        """
        发送PUT请求
        
        Args:
            endpoint: 端点路径
            data: 表单数据
            json_data: JSON数据
            headers: 请求头
        
        Returns:
            响应数据
        """
        url = self._build_url(endpoint)
        
        try:
            response = self._session.put(
                url, data=data, json=json_data, headers=headers, timeout=self.timeout
            )
            response.raise_for_status()
            
            try:
                return response.json()
            except json.JSONDecodeError:
                return response.text
        except Exception as e:
            logger.error(f"Feign PUT request failed: {url}, error: {e}")
            
            if self.fallback:
                fallback_instance = self.fallback()
                method = getattr(fallback_instance, endpoint.replace('/', '_'), None)
                if method and callable(method):
                    return method(data=data, json_data=json_data, headers=headers)
            
            raise
    
    def delete(self, endpoint: str, params: Dict[str, Any] = None, headers: Dict[str, str] = None) -> Any:
        """
        发送DELETE请求
        
        Args:
            endpoint: 端点路径
            params: 查询参数
            headers: 请求头
        
        Returns:
            响应数据
        """
        url = self._build_url(endpoint)
        
        try:
            response = self._session.delete(
                url, params=params, headers=headers, timeout=self.timeout
            )
            response.raise_for_status()
            
            try:
                return response.json()
            except json.JSONDecodeError:
                return response.text
        except Exception as e:
            logger.error(f"Feign DELETE request failed: {url}, error: {e}")
            
            if self.fallback:
                fallback_instance = self.fallback()
                method = getattr(fallback_instance, endpoint.replace('/', '_'), None)
                if method and callable(method):
                    return method(params=params, headers=headers)
            
            raise


class FeignClientFactory:
    """Feign客户端工厂"""
    
    _clients: Dict[str, FeignClientProxy] = {}
    
    @classmethod
    def get_client(cls, service_name: str) -> FeignClientProxy:
        """
        获取Feign客户端
        
        Args:
            service_name: 服务名称
        
        Returns:
            Feign客户端代理
        """
        if service_name not in cls._clients:
            cls._clients[service_name] = FeignClientProxy(service_name)
        
        return cls._clients[service_name]
    
    @classmethod
    def register_client(cls, service_name: str, client: FeignClientProxy):
        """
        注册Feign客户端
        
        Args:
            service_name: 服务名称
            client: Feign客户端代理
        """
        cls._clients[service_name] = client

    @classmethod
    def close_all(cls) -> None:
        for client in cls._clients.values():
            client.close()
        cls._clients.clear()


def create_feign_client(service_name: str, path: str = "", url: str = "", 
                        fallback: Type = None,
                        fallback_factory: Type = None,
                        timeout: float = 30) -> FeignClientProxy:
    """
    创建Feign客户端
    
    Args:
        service_name: 服务名称
        path: 路径前缀
        url: 直接URL（调试用）
        fallback: 降级实现类
    
    Returns:
        Feign客户端代理
    """
    return FeignClientProxy(service_name, path, url, fallback, fallback_factory, timeout)


def create_declared_feign_client(client_class: Type, annotation: Any) -> Any:
    """Create a typed proxy from a ``@FeignClient`` class declaration.

    Method mappings use the same SpringBootAI ``@RequestMapping`` family as web
    controllers.  The generated object subclasses the declaration class, so
    normal type-based IoC injection and ``isinstance`` checks continue to work.
    """
    from spring.annotations.core import (
        RequestMapping, GetMapping, PostMapping, PutMapping,
        PatchMapping, DeleteMapping, RequestParam, PathVariable,
        RequestBody, RequestHeader,
    )

    proxy = FeignClientProxy(
        annotation.value,
        path=annotation.path,
        url=annotation.url,
        fallback=annotation.fallback,
        fallback_factory=annotation.fallback_factory,
    )

    mappings = (RequestMapping, GetMapping, PostMapping, PutMapping, PatchMapping, DeleteMapping)
    generated = {}
    for method_name, method in inspect.getmembers(client_class, inspect.isfunction):
        mapping = next((item for item in getattr(method, '__spring_annotations__', []) if isinstance(item, mappings)), None)
        if mapping is None:
            continue
        raw_path = mapping.path
        endpoint_path = raw_path[0] if isinstance(raw_path, list) else raw_path
        endpoint_path = endpoint_path or method_name
        http_method = (mapping.method or ['GET'])[0].upper()
        signature = inspect.signature(method)
        parameters = [p for p in signature.parameters.values() if p.name != 'self']

        def make_call(name, endpoint, verb, original, params):
            def call(self, *args, **kwargs):
                bound = inspect.signature(original).bind_partial(None, *args, **kwargs)
                bound.apply_defaults()
                values = dict(bound.arguments)
                values.pop('self', None)
                path_values = {}
                query = {}
                body = None
                headers = {}
                for parameter in params:
                    value = values.get(parameter.name)
                    marker = parameter.default
                    if isinstance(marker, PathVariable) or '{' + parameter.name + '}' in endpoint:
                        path_values[marker.name if isinstance(marker, PathVariable) and marker.name else parameter.name] = value
                    elif isinstance(marker, RequestHeader):
                        headers[marker.name or parameter.name.replace('_', '-')] = value
                    elif isinstance(marker, RequestBody):
                        body = value
                    elif isinstance(marker, RequestParam):
                        query[marker.name or parameter.name] = value
                    elif verb in {'GET', 'DELETE'}:
                        query[parameter.name] = value
                    elif body is None:
                        body = value
                    else:
                        query[parameter.name] = value
                try:
                    endpoint_rendered = endpoint.format(**path_values)
                except KeyError as exc:
                    raise ValueError(f"Feign 路径缺少参数: {exc.args[0]}") from exc
                return proxy.request(
                    verb,
                    endpoint_rendered,
                    params=query or None,
                    json_data=body if verb not in {'GET', 'DELETE'} else None,
                    headers=headers or None,
                    timeout=proxy.timeout,
                    fallback_method=name,
                    call_args=args,
                    call_kwargs=kwargs,
                )
            call.__name__ = name
            call.__doc__ = getattr(original, '__doc__', None)
            if inspect.iscoroutinefunction(original):
                async def async_call(self, *args, **kwargs):
                    return await run_in_threadpool(call, self, *args, **kwargs)
                async_call.__name__ = name
                async_call.__doc__ = call.__doc__
                return async_call
            return call

        generated[method_name] = make_call(method_name, endpoint_path, http_method, method, parameters)

    original_destroy = getattr(client_class, 'destroy', None)

    def destroy(self):
        try:
            if callable(original_destroy):
                original_destroy(self)
        finally:
            proxy.close()

    generated['destroy'] = destroy
    implementation = type(f"{client_class.__name__}FeignProxy", (client_class,), generated)
    instance = implementation()
    instance.__feign_proxy__ = proxy
    return instance
