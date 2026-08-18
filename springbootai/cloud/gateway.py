"""
轻量异步 API 网关 (Embedded API Gateway)

无需 Spring Cloud Gateway / WebFlux 的内嵌 API 网关，基于异步 ASGI 反向代理：
- 路由转发（service-id -> instance URL via discovery）
- 负载均衡（支持轮询/随机/权重）
- 全局过滤器（认证、日志、追踪头注入、限流）
- 路径重写（StripPrefix、PrefixPath）
- 熔断集成（依赖 Sentinel）

Usage (Starlette/FastAPI-based):
    from springbootai.cloud.gateway import GatewayRouter

    gateway = GatewayRouter(discovery_client=discovery_client)
    gateway.route("/users/**", service_id="user-service", strip_prefix=True)
    gateway.route("/orders/**", service_id="order-service")
    app.add_route("/api/{path:path}", gateway.handle_asgi,
                  methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
"""

import time
import logging
import threading
import re
import random
import inspect
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("Spring.Cloud.Gateway")


@dataclass
class Route:
    """网关路由定义"""
    id: str
    path: str                    # 路径匹配模式，支持 ** 通配符
    service_id: str = ""         # 目标服务ID（通过发现获取）
    uri: str = ""                # 直接目标URI（优先级高于service_id）
    strip_prefix: bool = False   # 是否去除前缀
    prefix: str = ""             # 添加前缀
    filters: List[str] = field(default_factory=list)
    predicates: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class FilterContext:
    """过滤器上下文"""
    route: Route
    request_path: str
    request_headers: Dict[str, str]
    request_method: str
    request_query: Dict[str, str]
    response_status: int = 0
    response_headers: Dict[str, str] = field(default_factory=dict)
    attributes: Dict[str, Any] = field(default_factory=dict)
    start_time: float = 0.0


class GatewayFilter:
    """网关过滤器基类"""
    def pre_filter(self, ctx: FilterContext) -> bool:
        """前置过滤，返回False则终止请求"""
        return True

    def post_filter(self, ctx: FilterContext):
        """后置过滤"""
        pass


class AuthenticationFilter(GatewayFilter):
    """认证过滤器：检查JWT/Token"""
    def __init__(self, token_header: str = "Authorization", exclude_paths: List[str] = None):
        self.token_header = token_header
        self.exclude_paths = exclude_paths or ["/login", "/health", "/actuator"]

    def pre_filter(self, ctx: FilterContext) -> bool:
        for ep in self.exclude_paths:
            if ctx.request_path.startswith(ep):
                return True
        token = next(
            (value for key, value in ctx.request_headers.items()
             if key.lower() == self.token_header.lower()),
            "",
        )
        if not token:
            ctx.response_status = 401
            ctx.response_headers["X-Gateway-Error"] = "Missing Authorization"
            return False
        return True


class TracingFilter(GatewayFilter):
    """追踪头注入过滤器"""
    def pre_filter(self, ctx: FilterContext) -> bool:
        try:
            from springbootai.cloud.tracer import get_tracer
            tracer = get_tracer()
            tp = tracer.get_traceparent_header()
            if tp:
                ctx.request_headers['traceparent'] = tp
                cur = tracer.get_current_span()
                if cur:
                    ctx.request_headers['X-B3-TraceId'] = cur.trace_id
                    ctx.request_headers['X-B3-SpanId'] = cur.span_id
        except Exception:
            pass
        return True


class RateLimitFilter(GatewayFilter):
    """网关限流过滤器（使用Sentinel引擎）"""
    def __init__(self, default_qps: float = 500.0):
        self.default_qps = default_qps

    def pre_filter(self, ctx: FilterContext) -> bool:
        try:
            from springbootai.cloud.sentinel import sentinel_engine
            resource = f"gateway:{ctx.route.id}:{ctx.request_method}"
            try:
                sentinel_engine.entry(resource, args=(), kwargs={})
                # 简化：不维持entry对象，仅做QPS检查
            except Exception:
                ctx.response_status = 429
                ctx.response_headers["X-Gateway-Error"] = "Rate Limited"
                return False
        except ImportError:
            pass
        return True


class LoggingFilter(GatewayFilter):
    """访问日志过滤器"""
    def pre_filter(self, ctx: FilterContext) -> bool:
        ctx.start_time = time.monotonic()
        logger.info(f"[Gateway] {ctx.request_method} {ctx.request_path} -> {ctx.route.service_id or ctx.route.uri}")
        return True

    def post_filter(self, ctx: FilterContext):
        duration = (time.monotonic() - ctx.start_time) * 1000
        logger.info(f"[Gateway] {ctx.request_method} {ctx.request_path} "
                     f"status={ctx.response_status} duration={duration:.2f}ms")


class LoadBalancerStrategy:
    """负载均衡策略"""
    @staticmethod
    def round_robin(instances: List[dict]) -> Optional[dict]:
        if not instances:
            return None
        idx = int(time.time() * 1000) % len(instances)
        return instances[idx]

    @staticmethod
    def random_choice(instances: List[dict]) -> Optional[dict]:
        if not instances:
            return None
        return random.choice(instances)

    @staticmethod
    def weighted(instances: List[dict]) -> Optional[dict]:
        if not instances:
            return None
        weights = [inst.get('weight', 1) for inst in instances]
        total = sum(weights)
        r = random.uniform(0, total)
        upto = 0
        for inst, w in zip(instances, weights):
            if upto + w >= r:
                return inst
            upto += w
        return instances[0]


class GatewayRouter:
    """
    API 网关路由

    作为异步 Starlette/FastAPI endpoint 使用。上游 I/O 不会阻塞事件循环。

    Usage:
        gateway = GatewayRouter(timeout=5)
        gateway.route("/api/users/**", uri="http://127.0.0.1:8081",
                      strip_prefix=True)
        gateway.install(app, "/api/{path:path}")
    """

    _HOP_BY_HOP_HEADERS = {
        'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
        'te', 'trailer', 'transfer-encoding', 'upgrade',
    }

    def __init__(self, discovery_client=None, default_filters: List[GatewayFilter] = None,
                 timeout: float = 10.0, max_body_size: int = 10 * 1024 * 1024,
                 max_response_size: int = 50 * 1024 * 1024,
                 transport: Optional[httpx.AsyncBaseTransport] = None):
        self.discovery = discovery_client
        self.routes: List[Route] = []
        self.filters: List[GatewayFilter] = (
            list(default_filters) if default_filters is not None
            else [LoggingFilter(), TracingFilter()]
        )
        self._rr_counters: Dict[str, int] = {}
        self._rr_lock = threading.Lock()
        self._path_pattern_cache: Dict[str, re.Pattern] = {}
        self.timeout = float(timeout)
        self.max_body_size = int(max_body_size)
        # 上游响应大小上限（字节）：防止大文件下载/并发请求整体载入内存耗尽 worker。
        # 旧版本直接 upstream.content 整体载入，无大小限制。0 表示禁用限制（不推荐）。
        self.max_response_size = int(max_response_size)
        self._transport = transport
        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = threading.Lock()

    def install(self, app, path: str = "/{path:path}",
                methods: Optional[List[str]] = None) -> "GatewayRouter":
        """Register the gateway route and its HTTP-client shutdown hook."""
        route_methods = methods or ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
        path_id = re.sub(r"[^a-zA-Z0-9]+", "_", path).strip("_") or "root"
        existing_operation_ids = {
            getattr(route, "operation_id", None) for route in app.routes
        }
        for method in route_methods:
            normalized_method = method.upper()
            base_operation_id = f"gateway_{normalized_method.lower()}_{path_id}"
            operation_id = base_operation_id
            suffix = 2
            while operation_id in existing_operation_ids:
                operation_id = f"{base_operation_id}_{suffix}"
                suffix += 1
            existing_operation_ids.add(operation_id)
            app.add_api_route(
                path,
                self.handle_asgi,
                methods=[normalized_method],
                name=operation_id,
                operation_id=operation_id,
            )
        app.router.add_event_handler("shutdown", self.aclose)
        return self

    def _get_client(self) -> httpx.AsyncClient:
        # Construction has no await points.  A short process-local lock avoids
        # leaking duplicate connection pools during the first concurrent hit.
        with self._client_lock:
            if self._client is None:
                self._client = httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout),
                    follow_redirects=False,
                    transport=self._transport,
                )
            return self._client

    async def aclose(self) -> None:
        with self._client_lock:
            client = self._client
            self._client = None
        if client is not None:
            await client.aclose()

    def add_filter(self, flt: GatewayFilter):
        self.filters.append(flt)

    def route(self, path: str, service_id: str = "", uri: str = "",
              strip_prefix: bool = False, prefix: str = "",
              route_id: str = "", filters: List[str] = None,
              **predicates) -> Route:
        """添加路由"""
        rid = route_id or f"route_{len(self.routes) + 1}"
        r = Route(
            id=rid,
            path=path,
            service_id=service_id,
            uri=uri,
            strip_prefix=strip_prefix,
            prefix=prefix,
            filters=filters or [],
            predicates=predicates,
        )
        self.routes.append(r)
        self._path_pattern_cache[path] = self._compile_pattern(path)
        logger.info(f"[Gateway] Route added: {path} -> {service_id or uri}")
        return r

    def _compile_pattern(self, pattern: str) -> re.Pattern:
        """编译路径通配符为正则表达式"""
        regex = re.escape(pattern).replace(r'\*\*', '.*').replace(r'\*', '[^/]*')
        return re.compile(f'^{regex}$')

    def match_route(self, request_path: str) -> Optional[Route]:
        """匹配路由"""
        for r in self.routes:
            if not r.enabled:
                continue
            pat = self._path_pattern_cache.get(r.path)
            if pat is None:
                pat = self._compile_pattern(r.path)
                self._path_pattern_cache[r.path] = pat
            if pat.match(request_path):
                return r
        return None

    def _resolve_uri(self, route: Route) -> Optional[str]:
        """解析目标服务URI"""
        if route.uri:
            return route.uri.rstrip('/')
        if route.service_id and self.discovery:
            instances = self._get_instances(route.service_id)
            if instances:
                inst = LoadBalancerStrategy.round_robin(instances)
                host = inst.get('ip') or inst.get('host', '127.0.0.1')
                port = inst.get('port', 80)
                scheme = inst.get('scheme', 'http')
                return f"{scheme}://{host}:{port}"
        return None

    def _get_instances(self, service_id: str) -> List[dict]:
        """获取服务实例列表"""
        try:
            instances = self.discovery.get_instances(service_id)
            if instances:
                return instances if isinstance(instances, list) else [instances]
        except Exception as e:
            logger.warning(f"[Gateway] Failed to discover {service_id}: {e}")
        return []

    def rewrite_path(self, route: Route, request_path: str) -> str:
        """路径重写"""
        path = request_path
        if route.strip_prefix:
            # 去除匹配的前缀部分
            parts = route.path.split('/**')[0].rstrip('*').rstrip('/')
            if path.startswith(parts):
                path = path[len(parts):] or '/'
        if route.prefix:
            path = route.prefix.rstrip('/') + '/' + path.lstrip('/')
        return path

    async def _run_filter(self, flt: GatewayFilter, method: str,
                          ctx: FilterContext) -> Any:
        result = getattr(flt, method)(ctx)
        if inspect.isawaitable(result):
            return await result
        return result

    async def handle_asgi(self, request: Request) -> Response:
        """转发一个 Starlette/FastAPI 请求。"""
        path = request.url.path
        method = request.method
        route = self.match_route(path)
        if route is None:
            return JSONResponse({"error": "No route matched", "path": path}, status_code=404)

        headers = dict(request.headers)
        query_items = list(request.query_params.multi_items())
        query_dict = dict(query_items)

        ctx = FilterContext(
            route=route,
            request_path=path,
            request_headers=headers,
            request_method=method,
            request_query=query_dict,
        )

        # 执行前置过滤器
        for flt in self.filters:
            if not await self._run_filter(flt, 'pre_filter', ctx):
                return JSONResponse(
                    {"error": "Gateway filter blocked", "details": ctx.response_headers},
                    status_code=ctx.response_status or 403,
                    headers=ctx.response_headers,
                )

        target_uri = self._resolve_uri(route)
        if not target_uri:
            return JSONResponse(
                {"error": "Service unavailable", "service": route.service_id},
                status_code=503,
            )

        forward_path = self.rewrite_path(route, path)
        ctx.attributes['forward_uri'] = target_uri + forward_path

        content_length = request.headers.get('content-length')
        if self.max_body_size > 0 and content_length:
            try:
                if int(content_length) > self.max_body_size:
                    return JSONResponse({"error": "Request body too large"}, status_code=413)
            except ValueError:
                pass

        if self.max_body_size > 0:
            chunks = []
            body_size = 0
            async for chunk in request.stream():
                body_size += len(chunk)
                if body_size > self.max_body_size:
                    return JSONResponse({"error": "Request body too large"}, status_code=413)
                chunks.append(chunk)
            body = b''.join(chunks)
        else:
            body = await request.body()

        request_headers = {
            key: value for key, value in ctx.request_headers.items()
            if key.lower() not in self._HOP_BY_HOP_HEADERS | {'host', 'content-length'}
        }
        try:
            target_url = target_uri + forward_path
            # 使用 stream=True 避免上游响应整体载入内存：
            # 旧版本 upstream.content 一次性载入全部响应体，大文件下载或并发请求
            # 可能耗尽 worker 内存。流式读取配合 max_response_size 可在超限时提前中止。
            req = self._get_client().build_request(
                method,
                target_url,
                params=query_items,
                headers=request_headers,
                content=body,
            )
            upstream = await self._get_client().send(req, stream=True)

            try:
                ctx.response_status = upstream.status_code
                response_headers = {
                    key: value for key, value in upstream.headers.items()
                    if key.lower() not in self._HOP_BY_HOP_HEADERS | {'content-length'}
                }
                ctx.response_headers.update(response_headers)

                # 执行后置过滤器
                for flt in self.filters:
                    try:
                        await self._run_filter(flt, 'post_filter', ctx)
                    except Exception:
                        logger.exception("[Gateway] post filter failed")

                # 响应大小限制：
                # (1) 先检查 Content-Length 头（快速路径，无需读取响应体即可拒绝）
                # (2) 流式读取时累计字节数，超限立即中止并返回 502
                if self.max_response_size > 0:
                    content_length = upstream.headers.get('content-length')
                    if content_length:
                        try:
                            if int(content_length) > self.max_response_size:
                                logger.warning(
                                    "[Gateway] Upstream response Content-Length %s exceeds limit %d",
                                    content_length, self.max_response_size,
                                )
                                return JSONResponse(
                                    {"error": "Upstream response too large",
                                     "limit_bytes": self.max_response_size},
                                    status_code=502,
                                )
                        except ValueError:
                            pass

                    # is_stream_consumed=True 表示响应体已预载（如 MockTransport 或
                    # 非 stream 模式）；此时 aiter_raw() 会抛 StreamConsumed，
                    # 直接用 .content 检查大小即可。
                    if upstream.is_stream_consumed:
                        response_body = upstream.content
                        if len(response_body) > self.max_response_size:
                            logger.warning(
                                "[Gateway] Upstream response %d bytes exceeds limit %d",
                                len(response_body), self.max_response_size,
                            )
                            return JSONResponse(
                                {"error": "Upstream response too large",
                                 "limit_bytes": self.max_response_size},
                                status_code=502,
                            )
                    else:
                        chunks = []
                        response_size = 0
                        too_large = False
                        async for chunk in upstream.aiter_raw():
                            response_size += len(chunk)
                            if response_size > self.max_response_size:
                                logger.warning(
                                    "[Gateway] Upstream response exceeded %d bytes (got %d+), aborting",
                                    self.max_response_size, response_size,
                                )
                                too_large = True
                                break
                            chunks.append(chunk)

                        if too_large:
                            return JSONResponse(
                                {"error": "Upstream response too large",
                                 "limit_bytes": self.max_response_size},
                                status_code=502,
                            )
                        response_body = b''.join(chunks)
                else:
                    # 无限制：直接读取完整响应（向后兼容，不推荐在生产使用）
                    response_body = await upstream.aread()

                return Response(
                    content=response_body,
                    status_code=upstream.status_code,
                    headers=ctx.response_headers,
                )
            finally:
                # stream=True 模式下必须显式关闭响应，否则连接不会归还连接池
                await upstream.aclose()
        except httpx.TimeoutException as exc:
            logger.warning(f"[Gateway] Upstream timeout: {exc}")
            return JSONResponse({"error": "Gateway timeout"}, status_code=504)
        except httpx.HTTPError as exc:
            logger.warning(f"[Gateway] Upstream request failed: {exc}")
            return JSONResponse({"error": "Bad gateway"}, status_code=502)
        except Exception:
            logger.exception("[Gateway] Proxy error")
            return JSONResponse({"error": "Gateway internal error"}, status_code=500)

    def get_routes(self) -> List[Dict]:
        """获取所有路由信息"""
        return [{
            'id': r.id,
            'path': r.path,
            'service_id': r.service_id,
            'uri': r.uri,
            'enabled': r.enabled,
        } for r in self.routes]


# 全局网关实例
_gateway_instance: Optional[GatewayRouter] = None


def get_gateway(discovery_client=None) -> GatewayRouter:
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = GatewayRouter(discovery_client=discovery_client)
    return _gateway_instance
