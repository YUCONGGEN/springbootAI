"""
Feign远程调用模块
提供声明式HTTP客户端功能
"""
import requests
import logging
import json
import inspect
import threading
from dataclasses import asdict, is_dataclass
from typing import Dict, Any, Optional, Type
from urllib.parse import quote, urlsplit
from urllib3.util.retry import Retry
from starlette.concurrency import run_in_threadpool
from springbootai.cloud.load_balancer import LoadBalancer
from springbootai.logging.context import outbound_request_id, sanitize_url

logger = logging.getLogger("Spring.Cloud.Feign")


class FeignRequestError(RuntimeError):
    """Stable, credential-safe error raised by declared HTTP clients."""

    def __init__(self, method: str, url: str, reason: str,
                 status_code: Optional[int] = None):
        self.method = method
        self.url = sanitize_url(url)
        self.reason = reason
        self.status_code = status_code
        status = f" status={status_code}" if status_code is not None else ""
        super().__init__(
            f"Feign request failed: {method} {self.url}{status} ({reason})")


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
        max_retries: int = 2,
        retry_backoff: float = 0.2,
        connect_timeout: Optional[float] = None,
        read_timeout: Optional[float] = None,
        max_response_size: int = 10 * 1024 * 1024,
    ):
        self.service_name = service_name
        self.path = path
        self.url = url
        self.fallback = fallback
        self.fallback_factory = fallback_factory
        self.timeout = self._positive_timeout(timeout, "timeout")
        self.connect_timeout = (
            self._positive_timeout(connect_timeout, "connect_timeout")
            if connect_timeout is not None else None)
        self.read_timeout = (
            self._positive_timeout(read_timeout, "read_timeout")
            if read_timeout is not None else None)
        self.max_response_size = max(0, int(max_response_size))
        self.max_retries = max(0, min(int(max_retries), 10))
        self._closed = False
        self._load_balancer = LoadBalancer()
        self._session = requests.Session()
        retry_policy = Retry(
            total=self.max_retries,
            connect=self.max_retries,
            read=self.max_retries,
            status=self.max_retries,
            backoff_factor=max(0.0, float(retry_backoff)),
            status_forcelist=(429, 502, 503, 504),
            allowed_methods=frozenset(
                {"HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=max(1, int(pool_connections)),
            pool_maxsize=max(1, int(pool_maxsize)),
            max_retries=retry_policy,
            pool_block=True,
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def close(self) -> None:
        if not self._closed:
            self._session.close()
            self._closed = True

    def __enter__(self) -> "FeignClientProxy":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    @staticmethod
    def _positive_timeout(value: Any, name: str) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Feign {name} must be a positive number") from exc
        if parsed <= 0:
            raise ValueError(f"Feign {name} must be greater than zero")
        return parsed

    def _effective_timeout(self, override: Optional[float] = None):
        if override is not None:
            return self._positive_timeout(override, "timeout")
        if self.connect_timeout is None and self.read_timeout is None:
            return self.timeout
        return (
            self.connect_timeout or self.timeout,
            self.read_timeout or self.timeout,
        )

    @staticmethod
    def _validate_base_url(value: str) -> str:
        try:
            parsed = urlsplit(str(value))
            parsed.port
        except ValueError as exc:
            raise ValueError("Feign base URL is invalid") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Feign base URL must use http or https and include a host")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Feign base URL must not contain embedded credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("Feign base URL must not contain a query or fragment")
        return str(value).rstrip("/")
    
    def _get_base_url(self) -> str:
        """获取基础URL"""
        if self.url:
            return self._validate_base_url(self.url)
        
        # 使用负载均衡获取服务实例
        instances = self._load_balancer.get_instances(self.service_name)
        if not instances:
            raise Exception(f"No instances available for service: {self.service_name}")
        
        instance = self._load_balancer.select_instance(instances)
        return self._validate_base_url(
            f"http://{instance['ip']}:{instance['port']}")
    
    def _build_url(self, endpoint: str) -> str:
        """构建完整URL"""
        base_url = self._get_base_url()
        full_path = self.path.rstrip('/') + '/' + endpoint.lstrip('/')
        return f"{base_url.rstrip('/')}/{full_path.lstrip('/')}"

    def _decode_response(self, response, method: str, url: str) -> Any:
        headers = getattr(response, "headers", {}) or {}
        declared_size = headers.get("Content-Length", headers.get("content-length"))
        if self.max_response_size > 0 and declared_size:
            try:
                if int(declared_size) > self.max_response_size:
                    raise FeignRequestError(
                        method, url, "response_too_large")
            except ValueError:
                pass
        iterator = getattr(response, "iter_content", None)
        if callable(iterator):
            chunks = []
            byte_size = 0
            for chunk in iterator(chunk_size=64 * 1024):
                if not chunk:
                    continue
                byte_size += len(chunk)
                if (self.max_response_size > 0
                        and byte_size > self.max_response_size):
                    raise FeignRequestError(
                        method, url, "response_too_large")
                chunks.append(chunk)
            content = b"".join(chunks)
        else:
            content = getattr(response, "content", b"")
            if isinstance(content, str):
                content = content.encode("utf-8")
            if (self.max_response_size > 0
                    and len(content) > self.max_response_size):
                raise FeignRequestError(
                    method, url, "response_too_large")
        if not content:
            return None
        try:
            return json.loads(content)
        except (TypeError, ValueError, json.JSONDecodeError):
            encoding = getattr(response, "encoding", None) or "utf-8"
            return content.decode(encoding, errors="replace")

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
        if not self.fallback and not self.fallback_factory:
            raise error
        if self.fallback_factory:
            factory = (
                self.fallback_factory()
                if isinstance(self.fallback_factory, type)
                else self.fallback_factory
            )
            if hasattr(factory, 'create') and callable(factory.create):
                fallback_instance = factory.create(error)
            elif callable(factory):
                fallback_instance = factory(error)
            else:
                raise TypeError("Feign fallback_factory must be callable or define create()")
        else:
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
        if self._closed:
            raise RuntimeError("Feign client is closed")
        method = str(method).upper()
        if method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
            raise ValueError(f"Unsupported Feign HTTP method: {method}")
        url = self._build_url(endpoint)
        call_kwargs = call_kwargs or {}

        # 自动注入分布式事务XID头
        req_headers = dict(headers) if headers else {}
        supplied_request_id = next((
            value for key, value in req_headers.items()
            if key.lower() == "x-request-id"
        ), None)
        request_id = outbound_request_id(supplied_request_id)
        req_headers = {
            key: value for key, value in req_headers.items()
            if key.lower() != "x-request-id"
        }
        req_headers["X-Request-ID"] = request_id
        try:
            from springbootai.cloud.seata import seata_manager
            xid = seata_manager.get_current_tx_id()
            if xid:
                seata_manager.inject_xid_headers(req_headers, xid)
        except Exception:
            pass

        # 自动注入追踪头（W3C traceparent）
        try:
            from springbootai.cloud.tracer import get_tracer
            tracer = get_tracer()
            if tracer.enabled:
                tracer.inject_headers(req_headers)
        except Exception:
            pass

        response = None
        try:
            response = self._session.request(
                method,
                url,
                params=params,
                json=self._jsonable(json_data) if json_data is not None else None,
                data=data,
                headers=req_headers,
                timeout=self._effective_timeout(timeout),
                stream=True,
                allow_redirects=False,
            )
            status_code = getattr(response, "status_code", 200)
            if isinstance(status_code, int) and 300 <= status_code < 400:
                raise FeignRequestError(
                    method, url, "redirect_not_allowed",
                    status_code=status_code,
                )
            response.raise_for_status()
            return self._decode_response(response, method, url)
        except Exception as error:
            if isinstance(error, FeignRequestError):
                public_error = error
            else:
                status_code = getattr(
                    getattr(error, "response", None), "status_code", None)
                public_error = FeignRequestError(
                    method, url, type(error).__name__, status_code=status_code)
            logger.warning(
                "Feign request failed method=%s target=%s error_type=%s "
                "status=%s request_id=%s",
                method, sanitize_url(url), type(error).__name__,
                public_error.status_code, request_id,
            )
            closer = getattr(response, "close", None)
            if callable(closer):
                closer()
                response = None
            return self._call_fallback(
                fallback_method, public_error, call_args, call_kwargs)
        finally:
            closer = getattr(response, "close", None)
            if callable(closer):
                closer()

    async def arequest(self, method: str, endpoint: str, **kwargs) -> Any:
        """Execute the synchronous requests client without blocking the ASGI loop."""
        return await run_in_threadpool(self.request, method, endpoint, **kwargs)
    
    def get(self, endpoint: str, params: Dict[str, Any] = None,
            headers: Dict[str, str] = None) -> Any:
        """
        发送GET请求
        
        Args:
            endpoint: 端点路径
            params: 查询参数
            headers: 请求头
        
        Returns:
            响应数据
        """
        return self.request(
            "GET", endpoint, params=params, headers=headers,
            fallback_method=endpoint.replace('/', '_'),
            call_kwargs={"params": params, "headers": headers},
        )
    
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
        return self.request(
            "POST", endpoint, data=data, json_data=json_data, headers=headers,
            fallback_method=endpoint.replace('/', '_'),
            call_kwargs={
                "data": data, "json_data": json_data, "headers": headers,
            },
        )
    
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
        return self.request(
            "PUT", endpoint, data=data, json_data=json_data, headers=headers,
            fallback_method=endpoint.replace('/', '_'),
            call_kwargs={
                "data": data, "json_data": json_data, "headers": headers,
            },
        )
    
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
        return self.request(
            "DELETE", endpoint, params=params, headers=headers,
            fallback_method=endpoint.replace('/', '_'),
            call_kwargs={"params": params, "headers": headers},
        )


class FeignClientFactory:
    """Feign客户端工厂"""
    
    _clients: Dict[str, FeignClientProxy] = {}
    _lock = threading.RLock()
    
    @classmethod
    def get_client(cls, service_name: str) -> FeignClientProxy:
        """
        获取Feign客户端
        
        Args:
            service_name: 服务名称
        
        Returns:
            Feign客户端代理
        """
        with cls._lock:
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
        with cls._lock:
            previous = cls._clients.get(service_name)
            cls._clients[service_name] = client
        if previous is not None and previous is not client:
            previous.close()

    @classmethod
    def close_all(cls) -> None:
        with cls._lock:
            clients = list(cls._clients.values())
            cls._clients.clear()
        for client in clients:
            client.close()


def create_feign_client(service_name: str, path: str = "", url: str = "", 
                        fallback: Type = None,
                        fallback_factory: Type = None,
                        timeout: float = 30, **client_options) -> FeignClientProxy:
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
    return FeignClientProxy(
        service_name, path, url, fallback, fallback_factory, timeout,
        **client_options,
    )


def create_declared_feign_client(client_class: Type, annotation: Any) -> Any:
    """Create a typed proxy from a ``@FeignClient`` class declaration.

    Method mappings use the same SpringBootAI ``@RequestMapping`` family as web
    controllers.  The generated object subclasses the declaration class, so
    normal type-based IoC injection and ``isinstance`` checks continue to work.
    """
    from springbootai.annotations.core import (
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
                bound = inspect.signature(original).bind(None, *args, **kwargs)
                explicitly_bound = set(bound.arguments)
                values = dict(bound.arguments)
                values.pop('self', None)
                path_values = {}
                query = {}
                body = None
                headers = {}
                for parameter in params:
                    marker = parameter.default
                    supplied = parameter.name in explicitly_bound
                    value = values.get(parameter.name)
                    if not supplied and isinstance(marker, (RequestParam, RequestHeader)):
                        if marker.required and marker.default is None:
                            raise TypeError(
                                f"Missing required Feign argument: {parameter.name}")
                        value = marker.default
                    elif not supplied and isinstance(marker, RequestBody):
                        if marker.required:
                            raise TypeError(
                                f"Missing required Feign argument: {parameter.name}")
                        value = None
                    elif not supplied and isinstance(marker, PathVariable):
                        raise TypeError(
                            f"Missing required Feign path argument: {parameter.name}")
                    elif not supplied and marker is not inspect.Parameter.empty:
                        value = marker
                    if isinstance(marker, PathVariable) or '{' + parameter.name + '}' in endpoint:
                        path_name = (
                            marker.name if isinstance(marker, PathVariable) and marker.name
                            else parameter.name
                        )
                        if value is None:
                            raise ValueError(f"Feign 路径参数不能为空: {path_name}")
                        path_values[path_name] = quote(str(value), safe="")
                    elif isinstance(marker, RequestHeader):
                        if value is not None:
                            headers[marker.name or parameter.name.replace('_', '-')] = str(value)
                    elif isinstance(marker, RequestBody):
                        body = value
                    elif isinstance(marker, RequestParam):
                        if value is not None:
                            query[marker.name or parameter.name] = value
                    elif verb in {'GET', 'DELETE'}:
                        if value is not None:
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
