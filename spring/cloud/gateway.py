"""
轻量 API 网关 (Embedded API Gateway)

无需 Spring Cloud Gateway / WebFlux 的内嵌API网关，基于 ASGI/WSGI 反向代理：
- 路由转发（service-id -> instance URL via discovery）
- 负载均衡（支持轮询/随机/权重）
- 全局过滤器（认证、日志、追踪头注入、限流）
- 路径重写（StripPrefix、PrefixPath）
- 熔断集成（依赖 Sentinel）

Usage (Starlette/FastAPI-based):
    from spring.cloud.gateway import GatewayRouter

    gateway = GatewayRouter(discovery_client=discovery_client)
    gateway.route("/users/**", service_id="user-service", strip_prefix=True)
    gateway.route("/orders/**", service_id="order-service")
    app.mount("/api", gateway)
"""

import time
import logging
import threading
import re
import random
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field

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
        token = ctx.request_headers.get(self.token_header, "")
        if not token:
            ctx.response_status = 401
            ctx.response_headers["X-Gateway-Error"] = "Missing Authorization"
            return False
        return True


class TracingFilter(GatewayFilter):
    """追踪头注入过滤器"""
    def pre_filter(self, ctx: FilterContext) -> bool:
        try:
            from spring.cloud.tracer import get_tracer
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
            from spring.cloud.sentinel import sentinel_engine
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

    支持WSGI/ASGI双模式，可直接挂载到 Starlette/FastAPI/Werkzeug 应用上。

    Usage:
        gateway = GatewayRouter(discovery_client=nacos_discovery)
        gateway.route("/api/users/**", "user-service", strip_prefix=True)
        app.add_route("/api/{path:path}", gateway.handle_asgi, methods=["GET","POST","PUT","DELETE"])
    """

    def __init__(self, discovery_client=None, default_filters: List[GatewayFilter] = None):
        self.discovery = discovery_client
        self.routes: List[Route] = []
        self.filters: List[GatewayFilter] = default_filters or [
            LoggingFilter(),
            TracingFilter(),
        ]
        self._rr_counters: Dict[str, int] = {}
        self._rr_lock = threading.Lock()
        self._path_pattern_cache: Dict[str, re.Pattern] = {}

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

    def handle_asgi(self, scope, receive, send):
        """ASGI 处理器（适配 Starlette/FastAPI）"""
        import json
        if scope['type'] != 'http':
            return

        path = scope['path']
        method = scope['method']
        route = self.match_route(path)
        if route is None:
            self._asgi_response(send, 404, {"content-type": "application/json"},
                                json.dumps({"error": "No route matched", "path": path}).encode())
            return

        headers = {k.decode(): v.decode() for k, v in scope.get('headers', [])}
        query = scope.get('query_string', b'').decode()
        query_dict = {}
        if query:
            for pair in query.split('&'):
                if '=' in pair:
                    k, v = pair.split('=', 1)
                    query_dict[k] = v

        ctx = FilterContext(
            route=route,
            request_path=path,
            request_headers=headers,
            request_method=method,
            request_query=query_dict,
        )

        # 执行前置过滤器
        for flt in self.filters:
            if not flt.pre_filter(ctx):
                self._asgi_response(send, ctx.response_status or 403,
                                    {**ctx.response_headers, "content-type": "application/json"},
                                    json.dumps({"error": "Gateway filter blocked",
                                                "details": ctx.response_headers}).encode())
                return

        target_uri = self._resolve_uri(route)
        if not target_uri:
            self._asgi_response(send, 503, {"content-type": "application/json"},
                                json.dumps({"error": "Service unavailable",
                                            "service": route.service_id}).encode())
            return

        forward_path = self.rewrite_path(route, path)
        ctx.attributes['forward_uri'] = target_uri + forward_path

        # 简单HTTP转发（使用urllib，避免引入额外依赖）
        try:
            target_url = target_uri + forward_path
            if query_dict:
                target_url += '?' + '&'.join(f"{k}={v}" for k, v in query_dict.items())

            import urllib.request
            import urllib.error
            req = urllib.request.Request(target_url, method=method)
            for k, v in ctx.request_headers.items():
                if k.lower() not in ('host', 'content-length'):
                    req.add_header(k, v)

            # 读取body
            body = b''
            async def read_body():
                nonlocal body
                while True:
                    msg = await receive()
                    if msg['type'] == 'http.request':
                        body += msg.get('body', b'')
                        if not msg.get('more_body', False):
                            break
                return body

            # 同步获取body（简化实现）
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 简单fallback: 使用空body处理GET/DELETE
                    if method in ('POST', 'PUT', 'PATCH'):
                        body = self._read_body_sync(receive)
                else:
                    body = loop.run_until_complete(read_body())
            except Exception:
                pass

            if body:
                req.data = body

            try:
                resp = urllib.request.urlopen(req, timeout=10)
                resp_body = resp.read()
                resp_status = resp.status
                resp_headers = dict(resp.headers)
            except urllib.error.HTTPError as e:
                resp_status = e.code
                resp_body = e.read()
                resp_headers = dict(e.headers)
            except Exception as e:
                resp_status = 502
                resp_body = json.dumps({"error": "Bad gateway", "detail": str(e)}).encode()
                resp_headers = {"content-type": "application/json"}

            ctx.response_status = resp_status
            ctx.response_headers.update({k: str(v) for k, v in resp_headers.items() if k.lower() not in ('transfer-encoding',)})

            # 执行后置过滤器
            for flt in self.filters:
                try:
                    flt.post_filter(ctx)
                except Exception:
                    pass

            self._asgi_response(send, resp_status, ctx.response_headers, resp_body)
        except Exception as e:
            logger.error(f"[Gateway] Proxy error: {e}")
            self._asgi_response(send, 500, {"content-type": "application/json"},
                                json.dumps({"error": "Gateway internal error", "detail": str(e)}).encode())

    def _read_body_sync(self, receive):
        """同步读取body（简化实现）"""
        body = b''
        try:
            while True:
                msg = receive()
                if hasattr(msg, '__await__'):
                    # can't easily do this in sync mode; return empty
                    break
                if msg.get('type') == 'http.request':
                    body += msg.get('body', b'')
                    if not msg.get('more_body', False):
                        break
        except Exception:
            pass
        return body

    def _asgi_response(self, send, status: int, headers: Dict[str, str], body: bytes):
        """发送ASGI响应"""
        import asyncio
        async def _respond():
            await send({
                'type': 'http.response.start',
                'status': status,
                'headers': [(k.encode(), v.encode() if isinstance(v, str) else v) for k, v in headers.items()],
            })
            await send({
                'type': 'http.response.body',
                'body': body,
            })
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(_respond())
        except RuntimeError:
            # No running loop; create one
            asyncio.run(_respond())

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
