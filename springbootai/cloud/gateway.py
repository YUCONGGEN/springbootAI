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
import math
import threading
import re
import random
import inspect
import asyncio
import tempfile
from collections import deque
from collections.abc import Mapping
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool
from springbootai.logging.context import (
    get_request_id, outbound_request_id, request_context, safe_log_field,
    sanitize_url,
)

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
    filters: List['GatewayFilter'] = field(default_factory=list)
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
    def pre_filter(self, ctx: FilterContext) -> Any:
        """前置过滤，返回False则终止请求"""
        return True

    def post_filter(self, ctx: FilterContext):
        """后置过滤"""
        pass


class AuthenticationFilter(GatewayFilter):
    """Validate a bearer access token before forwarding a request.

    ``validator`` may be supplied for an external identity provider.  It must
    either return a claims mapping/truthy value or raise for an invalid token.
    Without an override the configured OAuth2 resource server is preferred,
    then the framework JWT utility is used.
    """

    def __init__(self, token_header: str = "Authorization",
                 exclude_paths: Optional[List[str]] = None, validator=None):
        self.token_header = token_header
        self.validator = validator
        self.exclude_paths = (
            ["/login", "/health", "/actuator"]
            if exclude_paths is None else list(exclude_paths)
        )

    async def _validate(self, token: str):
        if self.validator is not None:
            if inspect.iscoroutinefunction(self.validator):
                result = await self.validator(token)
            else:
                result = await run_in_threadpool(self.validator, token)
            if inspect.isawaitable(result):
                result = await result
            if not result:
                raise ValueError("token validator rejected the token")
            return result
        from springbootai.security.oauth2 import oauth2_resource_server
        if oauth2_resource_server.is_configured:
            return await run_in_threadpool(
                oauth2_resource_server.validate_token, token)
        from springbootai.security.jwt_utils import jwt_utils
        return await run_in_threadpool(jwt_utils.decode_token, token)

    async def pre_filter(self, ctx: FilterContext) -> bool:
        for ep in self.exclude_paths:
            normalized = str(ep).rstrip('/') or '/'
            if (ctx.request_path == normalized
                    or normalized != '/'
                    and ctx.request_path.startswith(normalized + '/')):
                return True
        token = next(
            (value for key, value in ctx.request_headers.items()
             if key.lower() == self.token_header.lower()),
            "",
        )
        if not token:
            ctx.response_status = 401
            ctx.response_headers["WWW-Authenticate"] = "Bearer"
            return False
        scheme, separator, credential = str(token).partition(" ")
        if not separator or scheme.lower() != "bearer" or not credential.strip():
            ctx.response_status = 401
            ctx.response_headers["WWW-Authenticate"] = (
                'Bearer error="invalid_token"')
            return False
        try:
            claims = await self._validate(credential.strip())
        except Exception as exc:
            logger.info(
                "[Gateway] Bearer token rejected error_type=%s request_id=%s",
                type(exc).__name__, get_request_id(),
            )
            ctx.response_status = 401
            ctx.response_headers["WWW-Authenticate"] = (
                'Bearer error="invalid_token"')
            return False
        ctx.attributes["principal"] = claims
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
        self.default_qps = float(default_qps)
        if self.default_qps <= 0:
            raise ValueError("Gateway default_qps must be greater than zero")
        self._lock = threading.Lock()
        self._requests: Dict[str, deque] = {}

    def _allow_local(self, resource: str) -> bool:
        """Apply the advertised default QPS even without Sentinel rules."""
        now = time.monotonic()
        cutoff = now - 1.0
        with self._lock:
            window = self._requests.setdefault(resource, deque())
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= self.default_qps:
                return False
            window.append(now)
        return True

    def pre_filter(self, ctx: FilterContext) -> bool:
        resource = f"gateway:{ctx.route.id}:{ctx.request_method}"
        if not self._allow_local(resource):
            ctx.response_status = 429
            ctx.response_headers["X-Gateway-Error"] = "Rate Limited"
            return False
        try:
            from springbootai.cloud.sentinel import BlockException, sentinel_engine
            try:
                entry = sentinel_engine.entry(resource, args=(), kwargs={})
                ctx.attributes[f"sentinel:{id(self)}"] = entry
            except BlockException:
                ctx.response_status = 429
                ctx.response_headers["X-Gateway-Error"] = "Rate Limited"
                return False
        except ImportError:
            pass
        except Exception as exc:
            # Sentinel instrumentation failure must not masquerade as a client
            # rate-limit violation.  The local limiter still protects the route.
            logger.warning(
                "[Gateway] Sentinel check failed error_type=%s request_id=%s",
                type(exc).__name__, get_request_id(),
            )
        return True

    def post_filter(self, ctx: FilterContext):
        entry = ctx.attributes.pop(f"sentinel:{id(self)}", None)
        if entry is None:
            return
        if ctx.response_status >= 500:
            entry.error()
        else:
            entry.success()


class LoggingFilter(GatewayFilter):
    """访问日志过滤器"""
    def pre_filter(self, ctx: FilterContext) -> bool:
        ctx.start_time = time.monotonic()
        target = (
            safe_log_field(ctx.route.service_id)
            if ctx.route.service_id else sanitize_url(ctx.route.uri)
        )
        logger.info(
            "[Gateway] %s %s -> %s",
            safe_log_field(ctx.request_method),
            safe_log_field(ctx.request_path),
            target,
        )
        return True

    def post_filter(self, ctx: FilterContext):
        duration = (time.monotonic() - ctx.start_time) * 1000
        logger.info(
            "[Gateway] %s %s status=%s duration=%.2fms",
            safe_log_field(ctx.request_method),
            safe_log_field(ctx.request_path),
            ctx.response_status,
            duration,
        )


class LoadBalancerStrategy:
    """负载均衡策略"""
    _round_robin_lock = threading.Lock()
    _round_robin_counters: Dict[tuple, int] = {}

    @staticmethod
    def round_robin(instances: List[dict]) -> Optional[dict]:
        if not instances:
            return None
        pool_key = tuple(
            (str(item.get('ip', '')), str(item.get('host', '')),
             str(item.get('port', '')))
            for item in instances
        )
        with LoadBalancerStrategy._round_robin_lock:
            idx = (LoadBalancerStrategy._round_robin_counters.get(pool_key, 0)
                   % len(instances))
            LoadBalancerStrategy._round_robin_counters[pool_key] = (
                idx + 1) % len(instances)
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
        weights = []
        for instance in instances:
            try:
                weight = float(instance.get('weight', 1))
            except (TypeError, ValueError, OverflowError):
                weight = 0.0
            weights.append(weight if math.isfinite(weight) and weight > 0 else 0.0)
        total = sum(weights)
        if total <= 0:
            return LoadBalancerStrategy.round_robin(instances)
        r = random.uniform(0, total)
        upto = 0.0
        for inst, w in zip(instances, weights, strict=True):
            # ``r == 0`` 时也不能命中零权重实例。
            if w > 0 and r < upto + w:
                return inst
            upto += w
        # 防御浮点舍入导致 r 落在累计区间之外；返回最后一个正权重实例。
        for inst, w in zip(
                reversed(instances), reversed(weights), strict=True):
            if w > 0:
                return inst
        return LoadBalancerStrategy.round_robin(instances)


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
        'proxy-connection', 'te', 'trailer', 'transfer-encoding', 'upgrade',
    }

    @staticmethod
    def _connection_header_tokens(headers) -> set[str]:
        """Return additional hop-by-hop names nominated by Connection."""
        try:
            value = headers.get('connection', '')
        except (AttributeError, TypeError):
            return set()
        return {
            token.strip().lower() for token in str(value).split(',')
            if token.strip()
        }

    def __init__(self, discovery_client=None,
                 default_filters: Optional[List[GatewayFilter]] = None,
                 timeout: float = 10.0, max_body_size: int = 10 * 1024 * 1024,
                 max_response_size: int = 50 * 1024 * 1024,
                 max_connections: int = 100,
                 max_keepalive_connections: int = 20,
                 transport: Optional[httpx.AsyncBaseTransport] = None):
        self.discovery = discovery_client
        self.routes: List[Route] = []
        self.filters: List[GatewayFilter] = (
            list(default_filters) if default_filters is not None
            else [AuthenticationFilter(), LoggingFilter(), TracingFilter()]
        )
        self._rr_counters: Dict[str, int] = {}
        self._rr_lock = threading.Lock()
        self._path_pattern_cache: Dict[str, re.Pattern] = {}
        self.timeout = self._positive_number(timeout, "timeout")
        self.max_body_size = self._non_negative_size(
            max_body_size, "max_body_size")
        # 上游响应大小上限（字节）：防止大文件下载/并发请求整体载入内存耗尽 worker。
        # 旧版本直接 upstream.content 整体载入，无大小限制。0 表示禁用限制（不推荐）。
        self.max_response_size = self._non_negative_size(
            max_response_size, "max_response_size")
        self.max_connections = max(1, int(max_connections))
        self.max_keepalive_connections = min(
            self.max_connections, max(0, int(max_keepalive_connections)))
        self._transport = transport
        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = threading.Lock()

    @staticmethod
    def _positive_number(value: Any, name: str) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Gateway {name} must be a positive number") from exc
        if parsed <= 0:
            raise ValueError(f"Gateway {name} must be greater than zero")
        return parsed

    @staticmethod
    def _non_negative_size(value: Any, name: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Gateway {name} must be a non-negative integer") from exc
        if parsed < 0:
            raise ValueError(f"Gateway {name} must not be negative")
        return parsed

    @staticmethod
    def _validate_uri(value: str) -> str:
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except (TypeError, ValueError) as exc:
            raise ValueError("Gateway upstream URI is invalid") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(
                "Gateway upstream URI must use http or https and include a host")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError(
                "Gateway upstream URI must not contain embedded credentials")
        if parsed.query or parsed.fragment:
            raise ValueError(
                "Gateway upstream URI must not contain a query or fragment")
        if any(character.isspace() or ord(character) < 32
               for character in parsed.hostname):
            raise ValueError("Gateway upstream URI host is invalid")
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("Gateway upstream URI port is invalid")
        return value.rstrip('/')

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
                    limits=httpx.Limits(
                        max_connections=self.max_connections,
                        max_keepalive_connections=self.max_keepalive_connections,
                    ),
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
              route_id: str = "",
              filters: Optional[List[GatewayFilter]] = None,
              **predicates) -> Route:
        """添加路由"""
        if not path or not str(path).startswith('/'):
            raise ValueError("Gateway route path must start with '/'")
        if not service_id and not uri:
            raise ValueError("Gateway route requires service_id or uri")
        route_filters = list(filters or [])
        invalid_filters = [
            item for item in route_filters
            if not isinstance(item, GatewayFilter)
        ]
        if invalid_filters:
            raise TypeError(
                "Gateway route filters must be GatewayFilter instances")
        normalized_predicates = self._normalize_predicates(predicates)
        uri = self._validate_uri(uri) if uri else ""
        rid = route_id or f"route_{len(self.routes) + 1}"
        r = Route(
            id=rid,
            path=path,
            service_id=service_id,
            uri=uri,
            strip_prefix=strip_prefix,
            prefix=prefix,
            filters=route_filters,
            predicates=normalized_predicates,
        )
        self.routes.append(r)
        self._path_pattern_cache[path] = self._compile_pattern(path)
        target = service_id or sanitize_url(uri)
        logger.info("[Gateway] Route added: %s -> %s", path, target)
        return r

    @staticmethod
    def _normalize_predicates(predicates: Dict[str, Any]) -> Dict[str, Any]:
        """Validate the small, explicit route-predicate surface.

        Silently storing unknown predicates made deployments appear protected
        while every request still matched.  Supported keys intentionally map
        to request data without executing user expressions.
        """
        normalized: Dict[str, Any] = {}
        for raw_key, raw_value in predicates.items():
            key = str(raw_key).strip().lower().replace('-', '_')
            if key in {"method", "methods"}:
                values = ([raw_value] if isinstance(raw_value, str)
                          else list(raw_value or []))
                methods = {
                    str(value).strip().upper() for value in values if str(value).strip()
                }
                if not methods:
                    raise ValueError("Gateway method predicate must not be empty")
                normalized["methods"] = methods
            elif key in {"header", "headers"}:
                if not isinstance(raw_value, Mapping):
                    raise TypeError("Gateway headers predicate must be a mapping")
                normalized["headers"] = {
                    str(name).lower(): str(value)
                    for name, value in raw_value.items()
                }
            elif key in {"query", "queries", "query_params"}:
                if not isinstance(raw_value, Mapping):
                    raise TypeError("Gateway query predicate must be a mapping")
                normalized["query"] = {
                    str(name): str(value) for name, value in raw_value.items()
                }
            else:
                raise ValueError(f"Unsupported Gateway route predicate: {raw_key}")
        return normalized

    def _compile_pattern(self, pattern: str) -> re.Pattern:
        """编译路径通配符为正则表达式"""
        regex = re.escape(pattern).replace(r'\*\*', '.*').replace(r'\*', '[^/]*')
        return re.compile(f'^{regex}$')

    @staticmethod
    def _predicates_match(route: Route, method: Optional[str],
                          headers: Optional[Mapping[str, str]],
                          query: Optional[Mapping[str, str]]) -> bool:
        predicates = route.predicates
        if not predicates:
            return True
        if method is not None and "methods" in predicates:
            if method.upper() not in predicates["methods"]:
                return False
        if headers is not None and "headers" in predicates:
            lowered = {str(key).lower(): str(value)
                       for key, value in headers.items()}
            if any(lowered.get(key) != value
                   for key, value in predicates["headers"].items()):
                return False
        if query is not None and "query" in predicates:
            if any(str(query.get(key, "")) != value
                   for key, value in predicates["query"].items()):
                return False
        return True

    def match_route(self, request_path: str, method: Optional[str] = None,
                    headers: Optional[Mapping[str, str]] = None,
                    query: Optional[Mapping[str, str]] = None) -> Optional[Route]:
        """匹配路由"""
        for r in self.routes:
            if not r.enabled:
                continue
            pat = self._path_pattern_cache.get(r.path)
            if pat is None:
                pat = self._compile_pattern(r.path)
                self._path_pattern_cache[r.path] = pat
            if pat.match(request_path) and self._predicates_match(
                    r, method, headers, query):
                return r
        return None

    def _resolve_uri(self, route: Route) -> Optional[str]:
        """解析目标服务URI"""
        if route.uri:
            return self._validate_uri(route.uri)
        if route.service_id and self.discovery:
            instances = self._get_instances(route.service_id)
            if instances:
                valid_instances = []
                for inst in instances:
                    host = inst.get('ip') or inst.get('host', '127.0.0.1')
                    port = inst.get('port', 80)
                    scheme = inst.get('scheme', 'http')
                    try:
                        uri = self._validate_uri(f"{scheme}://{host}:{port}")
                    except ValueError:
                        logger.warning(
                            "[Gateway] Ignoring invalid discovery instance service=%s",
                            route.service_id,
                        )
                        continue
                    valid_instances.append(uri)
                if not valid_instances:
                    return None
                with self._rr_lock:
                    index = self._rr_counters.get(route.service_id, 0)
                    self._rr_counters[route.service_id] = (
                        index + 1) % len(valid_instances)
                return valid_instances[index % len(valid_instances)]
        return None

    def _get_instances(self, service_id: str) -> List[dict]:
        """获取服务实例列表"""
        try:
            instances = self.discovery.get_instances(service_id)
            if instances:
                candidates = instances if isinstance(instances, list) else [instances]
                return [
                    dict(instance) for instance in candidates
                    if isinstance(instance, Mapping)
                    and self._instance_flag(instance.get('healthy', True))
                    and self._instance_flag(instance.get('enabled', True))
                ]
        except Exception as exc:
            logger.warning(
                "[Gateway] Discovery failed service=%s error_type=%s request_id=%s",
                service_id, type(exc).__name__, get_request_id(),
            )
        return []

    @staticmethod
    def _instance_flag(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return value != 0
        return str(value).strip().lower() not in {
            "", "0", "false", "no", "off", "disabled", "down",
        }

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
        callback = getattr(flt, method)
        if inspect.iscoroutinefunction(callback):
            return await callback(ctx)
        result = await run_in_threadpool(callback, ctx)
        if inspect.isawaitable(result):
            return await result
        return result

    async def handle_asgi(self, request: Request) -> Response:
        """Bind a correlation ID around standalone as well as installed use."""
        request_id = outbound_request_id(request.headers.get('x-request-id'))
        with request_context(request_id):
            response = await self._handle_asgi(request)
        response.headers.setdefault('X-Request-ID', request_id)
        return response

    async def _run_post_filters(self, filters: List[GatewayFilter],
                                ctx: FilterContext, status_code: int) -> None:
        if ctx.attributes.get("gateway.post_filters_completed"):
            return
        ctx.attributes["gateway.post_filters_completed"] = True
        ctx.response_status = status_code
        for flt in filters:
            try:
                await self._run_filter(flt, 'post_filter', ctx)
            except Exception as exc:
                logger.warning(
                    "[Gateway] Post filter failed filter=%s error_type=%s "
                    "request_id=%s",
                    type(flt).__name__, type(exc).__name__, get_request_id(),
                )

    async def _error_response(self, ctx: FilterContext,
                              filters: List[GatewayFilter], payload: Dict[str, Any],
                              status_code: int,
                              headers: Optional[Dict[str, str]] = None) -> Response:
        if headers:
            ctx.response_headers.update(headers)
        await self._run_post_filters(filters, ctx, status_code)
        return JSONResponse(
            payload, status_code=status_code, headers=ctx.response_headers)

    async def _handle_asgi(self, request: Request) -> Response:
        """转发一个 Starlette/FastAPI 请求。"""
        path = request.url.path
        method = request.method
        headers = dict(request.headers)
        query_items = list(request.query_params.multi_items())
        query_dict = dict(query_items)
        route = self.match_route(
            path, method=method, headers=headers, query=query_dict)
        if route is None:
            return JSONResponse({"error": "No route matched", "path": path}, status_code=404)

        ctx = FilterContext(
            route=route,
            request_path=path,
            request_headers=headers,
            request_method=method,
            request_query=query_dict,
        )
        ctx.attributes["gateway.request_id"] = get_request_id()

        active_filters = [*self.filters, *route.filters]
        executed_filters: List[GatewayFilter] = []
        try:
            # A filter that acquired a limiter/tracing resource must always be
            # included in the matching post-filter cleanup, even if its own
            # pre-filter raises.
            for flt in active_filters:
                executed_filters.append(flt)
                if not await self._run_filter(flt, 'pre_filter', ctx):
                    return await self._error_response(
                        ctx, executed_filters,
                        {"error": "Gateway filter blocked"},
                        ctx.response_status or 403,
                    )
            target_uri = await run_in_threadpool(self._resolve_uri, route)
        except Exception as exc:
            logger.warning(
                "[Gateway] Pre-forward processing failed route=%s "
                "error_type=%s request_id=%s",
                route.id, type(exc).__name__, get_request_id(),
            )
            return await self._error_response(
                ctx, executed_filters,
                {"error": "Gateway pre-forward processing failed"}, 500,
            )
        if not target_uri:
            return await self._error_response(
                ctx, executed_filters,
                {"error": "Service unavailable", "service": route.service_id},
                503,
            )

        forward_path = self.rewrite_path(route, path)
        ctx.attributes['forward_uri'] = target_uri + forward_path

        content_length = request.headers.get('content-length')
        declared_body_size = None
        if self.max_body_size > 0 and content_length:
            try:
                declared_body_size = int(content_length)
                if declared_body_size < 0:
                    raise ValueError
                if declared_body_size > self.max_body_size:
                    return await self._error_response(
                        ctx, executed_filters,
                        {"error": "Request body too large"}, 413)
            except ValueError:
                declared_body_size = None
        elif content_length:
            try:
                declared_body_size = int(content_length)
                if declared_body_size < 0:
                    declared_body_size = None
            except ValueError:
                declared_body_size = None

        actual_body_size = None
        try:
            if self.max_body_size > 0:
                # Content-Length is an untrusted hint.  Always count the actual
                # stream and reject it before a potentially mutating upstream
                # sees any bytes.
                chunks = []
                body_size = 0
                async for chunk in request.stream():
                    body_size += len(chunk)
                    if body_size > self.max_body_size:
                        return await self._error_response(
                            ctx, executed_filters,
                            {"error": "Request body too large"}, 413)
                    chunks.append(chunk)
                body = b''.join(chunks)
                actual_body_size = body_size
            else:
                # Limits were explicitly disabled; leave framing to httpx
                # instead of forwarding an untrusted Content-Length value.
                body = request.stream()
        except ClientDisconnect:
            logger.info(
                "[Gateway] Client disconnected route=%s request_id=%s",
                route.id, get_request_id(),
            )
            return await self._error_response(
                ctx, executed_filters, {"error": "Client disconnected"}, 400)

        request_hop_headers = (
            self._HOP_BY_HOP_HEADERS
            | self._connection_header_tokens(ctx.request_headers)
            | {'host', 'content-length'}
        )
        request_headers = {
            key: value for key, value in ctx.request_headers.items()
            if key.lower() not in request_hop_headers
        }
        supplied_request_id = next((
            value for key, value in request_headers.items()
            if key.lower() == 'x-request-id'
        ), None)
        request_id = outbound_request_id(supplied_request_id)
        request_headers = {
            key: value for key, value in request_headers.items()
            if key.lower() != 'x-request-id'
        }
        request_headers['X-Request-ID'] = request_id
        # A bounded response must be measured in bytes delivered to the
        # downstream application, not in the (potentially tiny) compressed
        # representation. Ask well-behaved upstreams for identity encoding;
        # responses that ignore this request are decoded and counted below.
        if self.max_response_size > 0:
            request_headers = {
                key: value for key, value in request_headers.items()
                if key.lower() != 'accept-encoding'
            }
            request_headers['Accept-Encoding'] = 'identity'
        if actual_body_size is not None:
            request_headers['Content-Length'] = str(actual_body_size)
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
            response_hop_headers = (
                self._HOP_BY_HOP_HEADERS
                | self._connection_header_tokens(upstream.headers)
                | {'content-length', 'set-cookie'}
            )
            response_headers = {
                key: value for key, value in upstream.headers.items()
                if key.lower() not in response_hop_headers
            }

            content_encoding = upstream.headers.get(
                'content-encoding', 'identity').strip().lower()
            decode_response = (
                self.max_response_size > 0
                and content_encoding not in {'', 'identity'}
            )
            if decode_response:
                # httpx ``aiter_bytes`` removes the content coding. Headers
                # describing the encoded representation would then be false
                # and can also corrupt a JSON gateway error if copied early.
                for header_name in (
                    'content-encoding', 'content-md5', 'digest', 'etag',
                    'accept-ranges', 'content-range',
                ):
                    response_headers = {
                        key: value for key, value in response_headers.items()
                        if key.lower() != header_name
                    }

            content_length = upstream.headers.get('content-length')
            declared_size = None
            if content_length:
                try:
                    declared_size = int(content_length)
                    if declared_size < 0:
                        raise ValueError
                except ValueError:
                    content_length = None
            # Content-Length describes the encoded representation. It is only
            # a trustworthy fast-path bound when no decoding is required.
            if (self.max_response_size > 0 and not decode_response
                    and declared_size is not None
                    and declared_size > self.max_response_size):
                logger.warning(
                    "[Gateway] Upstream response Content-Length %s exceeds limit %d",
                    content_length, self.max_response_size,
                )
                await upstream.aclose()
                return await self._error_response(
                    ctx, executed_filters,
                    {"error": "Upstream response too large",
                     "limit_bytes": self.max_response_size},
                    502,
                )

            # MockTransport/自定义 transport 可能已经预载响应；此路径仍可在发送
            # headers 前返回明确的 502，并避免为小响应增加流式调度开销。
            if upstream.is_stream_consumed:
                response_body = upstream.content
                await upstream.aclose()
                if (self.max_response_size > 0
                        and len(response_body) > self.max_response_size):
                    logger.warning(
                        "[Gateway] Upstream response %d bytes exceeds limit %d",
                        len(response_body), self.max_response_size,
                    )
                    return await self._error_response(
                        ctx, executed_filters,
                        {"error": "Upstream response too large",
                         "limit_bytes": self.max_response_size},
                        502,
                    )
                ctx.response_headers.update(response_headers)
                await self._run_post_filters(
                    executed_filters, ctx, upstream.status_code)
                response = Response(
                    content=response_body,
                    status_code=upstream.status_code,
                    headers=ctx.response_headers,
                )
            elif self.max_response_size > 0:
                # Consume into a bounded spooled file before returning the
                # response. ASGI response headers are irreversible, so this is
                # the only way to guarantee an oversized chunked response is a
                # real 502 instead of a truncated upstream status.
                spool = tempfile.SpooledTemporaryFile(
                    max_size=min(self.max_response_size, 1024 * 1024),
                    mode="w+b",
                )
                response_size = 0
                try:
                    response_iterator = (
                        upstream.aiter_bytes()
                        if decode_response else upstream.aiter_raw()
                    )
                    async for chunk in response_iterator:
                        response_size += len(chunk)
                        if response_size > self.max_response_size:
                            logger.warning(
                                "[Gateway] Streaming response exceeded %d "
                                "bytes; rejecting before response headers",
                                self.max_response_size,
                            )
                            spool.close()
                            await upstream.aclose()
                            return await self._error_response(
                                ctx, executed_filters,
                                {"error": "Upstream response too large",
                                 "limit_bytes": self.max_response_size},
                                502,
                            )
                        spool.write(chunk)
                    await upstream.aclose()
                    spool.seek(0)
                except BaseException:
                    spool.close()
                    await upstream.aclose()
                    raise

                async def stream_spooled():
                    final_status = upstream.status_code
                    try:
                        while True:
                            chunk = await asyncio.to_thread(
                                spool.read, 64 * 1024)
                            if not chunk:
                                break
                            yield chunk
                    except (asyncio.CancelledError, GeneratorExit):
                        final_status = 499
                        raise
                    finally:
                        spool.close()
                        with request_context(
                                ctx.attributes["gateway.request_id"]):
                            await self._run_post_filters(
                                executed_filters, ctx, final_status)

                ctx.response_headers.update(response_headers)
                response = StreamingResponse(
                    stream_spooled(),
                    status_code=upstream.status_code,
                    headers=ctx.response_headers,
                )
            else:
                ctx.response_headers.update(response_headers)
                async def stream_upstream():
                    response_size = 0
                    final_status = upstream.status_code
                    try:
                        with request_context(
                                ctx.attributes["gateway.request_id"]):
                            async for chunk in upstream.aiter_raw():
                                response_size += len(chunk)
                                if (self.max_response_size > 0
                                        and response_size > self.max_response_size):
                                    logger.warning(
                                        "[Gateway] Streaming response exceeded %d bytes; closing upstream",
                                        self.max_response_size,
                                    )
                                    final_status = 502
                                    # Headers may already be sent, so abort the
                                    # stream without forwarding excess bytes.
                                    raise RuntimeError(
                                        "Gateway upstream response exceeded size limit")
                                yield chunk
                    except asyncio.CancelledError:
                        final_status = 499
                        raise
                    except GeneratorExit:
                        final_status = 499
                        raise
                    except BaseException:
                        final_status = 502
                        raise
                    finally:
                        await upstream.aclose()
                        with request_context(
                                ctx.attributes["gateway.request_id"]):
                            await self._run_post_filters(
                                executed_filters, ctx, final_status)

                response = StreamingResponse(
                    stream_upstream(),
                    status_code=upstream.status_code,
                    headers=ctx.response_headers,
                )

            for cookie in upstream.headers.get_list('set-cookie'):
                response.headers.append('set-cookie', cookie)
            return response
        except ClientDisconnect:
            logger.info(
                "[Gateway] Client disconnected route=%s request_id=%s",
                route.id, get_request_id(),
            )
            return await self._error_response(
                ctx, executed_filters, {"error": "Client disconnected"}, 400)
        except httpx.TimeoutException as exc:
            logger.warning(
                "[Gateway] Upstream timeout route=%s error_type=%s request_id=%s",
                route.id, type(exc).__name__, get_request_id(),
            )
            return await self._error_response(
                ctx, executed_filters, {"error": "Gateway timeout"}, 504)
        except httpx.HTTPError as exc:
            logger.warning(
                "[Gateway] Upstream request failed route=%s error_type=%s "
                "request_id=%s",
                route.id, type(exc).__name__, get_request_id(),
            )
            return await self._error_response(
                ctx, executed_filters, {"error": "Bad gateway"}, 502)
        except Exception as exc:
            logger.error(
                "[Gateway] Proxy error route=%s error_type=%s request_id=%s",
                safe_log_field(route.id), type(exc).__name__, get_request_id(),
            )
            return await self._error_response(
                ctx, executed_filters, {"error": "Gateway internal error"}, 500)

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
