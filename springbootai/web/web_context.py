from typing import Type, Any, Dict, Callable, List, Optional, get_args, get_origin, Union
import asyncio
import json
import logging
from datetime import datetime, date
from decimal import Decimal
from fastapi import FastAPI, Request, Response, UploadFile
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from springbootai.context.application_context import ApplicationContext
from springbootai.annotations.core import (
    RestController,
    Controller,
    RequestMapping,
    GetMapping,
    PostMapping,
    PutMapping,
    PatchMapping,
    DeleteMapping,
    RequestParam,
    PathVariable,
    RequestBody,
    RequestPart,
    Valid,
    Validated,
    RequestHeader,
    CookieValue,
    CrossOrigin,
    ControllerAdvice,
    ExceptionHandler,
    ResponseStatus,
)
from springbootai.web.result import Result
from springbootai.logging.context import (
    get_request_id, normalize_request_id, reset_request_id, set_request_id,
    sanitize_exception_value,
)
import os
import inspect
import re


class _JsonEncoder(json.JSONEncoder):
    """扩展 JSON 编码器，支持 datetime、date、Decimal、bytes 等非原生类型"""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, bytes):
            return obj.decode('utf-8', errors='replace')
        return super().default(obj)


class _SyncHandlerOverloaded(RuntimeError):
    """Raised when the bounded synchronous-handler queue cannot accept work."""


class _RequestBodyTooLarge(RuntimeError):
    """Internal signal raised before an oversized body reaches a controller."""


class RequestBodyLimitMiddleware:
    """ASGI request-body limiter that also covers chunked uploads."""

    def __init__(self, app, max_body_size: int):
        self.app = app
        self.max_body_size = max(0, int(max_body_size))

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or self.max_body_size <= 0:
            await self.app(scope, receive, send)
            return

        headers = {
            key.lower(): value for key, value in scope.get("headers", [])
        }
        declared = headers.get(b"content-length")
        if declared:
            try:
                if int(declared) > self.max_body_size:
                    await self._reject(send)
                    return
            except (TypeError, ValueError):
                pass

        consumed = 0
        response_started = False

        async def limited_receive():
            nonlocal consumed
            message = await receive()
            if message.get("type") == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.max_body_size:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
            await self._reject(send)

    @staticmethod
    async def _reject(send) -> None:
        body = b'{"detail":"Request body too large"}'
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})


class WebApplicationContext:
    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        """安全转换整数，兼容 dict 格式的配置值。"""
        if isinstance(value, dict):
            value = value.get('value') or value.get('size') or default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        """安全转换浮点数，兼容 dict 格式的配置值。"""
        if isinstance(value, dict):
            value = value.get('value') or value.get('timeout') or default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    def __init__(self, application_context: ApplicationContext, static_dir: str = None,
                 interceptor_registry: Any = None):
        self.application_context = application_context
        # ---- Swagger/OpenAPI 配置 ----
        from springbootai.web.swagger import SwaggerConfig
        try:
            config = application_context.get_config()
        except (AttributeError, TypeError):
            config = {}
        self.swagger_config = SwaggerConfig.from_config(config)
        self.fastapi_app = FastAPI(**self.swagger_config.to_fastapi_kwargs())
        # 收集所有 Controller 类（用于 @Tag/@SecurityScheme 全局元数据）
        self._controller_classes: List[Type] = []
        # 收集方法级 @Parameter 元数据：{operation_id 或 path:method: [Parameter]}
        self._method_param_meta: Dict[str, list] = {}
        self._routes: List[APIRoute] = []
        self._exception_handlers: Dict[Type[Exception], Callable] = {}
        self._static_dir = static_dir
        self._logger = logging.getLogger("Spring.Web")
        self._interceptor_registry = interceptor_registry
        self._runtime_interceptor_registry = None
        self._interceptors_registered = False
        # ApplicationContext.refresh_configuration() uses this back-reference
        # to refresh framework-owned Web configuration after Nacos changes.
        # 测试/嵌入式调用可能传入不可变的占位对象；反向引用只是运行期优化，
        # 设置失败不能阻止 Web 上下文创建。
        try:
            setattr(application_context, "web_context", self)
        except (AttributeError, TypeError):
            self._logger.debug("Application context does not allow web_context back-reference")
        thread_pool = self._get_thread_pool_config()
        self._sync_max_workers = max(1, self._safe_int(thread_pool.get('max_workers', 40)))
        self._sync_max_queue = max(0, self._safe_int(thread_pool.get('max_queue', 100)))
        self._sync_queue_timeout = max(
            0.001, self._safe_float(thread_pool.get('queue_timeout', 0.1))
        )
        self._sync_capacity = asyncio.Semaphore(
            self._sync_max_workers + self._sync_max_queue
        )

    def init(self) -> None:
        self.fastapi_app.router.add_event_handler(
            'startup', self._configure_sync_thread_pool
        )
        self._register_controllers()
        self._register_interceptors()
        self._register_exception_handlers()
        self._register_cors_middleware()
        self._register_request_body_limit()
        # Starlette 后添加的 middleware 位于外层；请求上下文必须包住 CORS，
        # 才能让预检/拒绝响应同样获得关联 ID。
        self._register_request_context_middleware()
        self._register_static_files()
        self._register_health_endpoints()
        self._register_shutdown_handlers()
        self._configure_swagger()
        # 静态文件通配路由 /{full_path:path} 先于 actuator/health 路由注册，
        # FastAPI 0.141+ 的 include_router 以 _IncludedRouter 懒加载对象追加，
        # 通配路由会先匹配 /actuator/* 等路径并返回 404。
        # 将通配路由移到路由表末尾，确保 API 与 Actuator 端点优先匹配。
        self._move_wildcard_static_route_to_end()

    def _register_request_context_middleware(self) -> None:
        """Attach a validated correlation ID to logs and every HTTP response."""
        if getattr(self, '_request_context_registered', False):
            return
        try:
            config = self.application_context.get_config()
        except (AttributeError, TypeError):
            config = {}
        server = config.get("server", {}) if isinstance(config, dict) else {}
        request_id_config = (
            server.get("request-id", server.get("request_id", {}))
            if isinstance(server, dict) else {}
        )
        if not isinstance(request_id_config, dict):
            request_id_config = {}
        header_name = str(request_id_config.get("header", "X-Request-ID")).strip()
        if not header_name or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", header_name):
            self._logger.warning(
                "Invalid server.request-id.header; using X-Request-ID")
            header_name = "X-Request-ID"
        self.request_id_header = header_name

        @self.fastapi_app.middleware("http")
        async def request_context_middleware(request: Request, call_next):
            supplied = request.headers.get(header_name)
            request_id = normalize_request_id(supplied)
            token = set_request_id(request_id)
            request.state.request_id = request_id
            try:
                response = await call_next(request)
                response.headers[header_name] = request_id
                return response
            finally:
                reset_request_id(token)
        self._request_context_registered = True

    def _register_request_body_limit(self) -> None:
        try:
            config = self.application_context.get_config()
        except (AttributeError, TypeError):
            config = {}
        server = config.get("server", {}) if isinstance(config, dict) else {}
        if not isinstance(server, dict):
            server = {}
        raw = server.get(
            "max-request-body-size",
            server.get("max_request_body_size", 10 * 1024 * 1024),
        )
        limit = self._safe_int(raw, 10 * 1024 * 1024)
        if limit < 0:
            raise ValueError("server.max-request-body-size must not be negative")
        self.fastapi_app.add_middleware(
            RequestBodyLimitMiddleware, max_body_size=limit)

    def _move_wildcard_static_route_to_end(self) -> None:
        """将 ``/{full_path:path}`` 通配路由移到路由表末尾。

        静态文件通配路由若在 actuator/API 路由之前注册，会拦截所有未匹配路径，
        导致后注册的 ``/actuator/*`` 等端点返回 404。此方法在所有路由注册
        完成后统一调整顺序，保证通配路由仅作为兜底匹配。
        """
        routes = self.fastapi_app.router.routes
        wildcard_idx = next(
            (
                i for i, r in enumerate(routes)
                if hasattr(r, "path") and r.path == "/{full_path:path}"
            ),
            None,
        )
        if wildcard_idx is not None and wildcard_idx != len(routes) - 1:
            wildcard_route = routes.pop(wildcard_idx)
            routes.append(wildcard_route)

    def _configure_swagger(self) -> None:
        """在路由注册完成后，自定义 ``app.openapi()`` 注入全局 securitySchemes、
        ``@Schema`` 模型描述与 ``@Parameter`` 参数描述。"""
        from springbootai.web.swagger import (
            configure_swagger, collect_openapi_tags, collect_security_schemes,
            register_schema, Schema,
        )
        # 收集全局 @SecurityScheme
        security_schemes = collect_security_schemes(self._controller_classes)
        tag_definitions = collect_openapi_tags(self._controller_classes)
        # 注册 @Schema 标注的模型类
        for cls in self._controller_classes:
            for ann in (getattr(cls, '__spring_annotations__', []) or []):
                if isinstance(ann, Schema) and getattr(ann, '_original_class', None):
                    register_schema(ann._original_class, ann)
        configure_swagger(
            self.fastapi_app,
            self.swagger_config,
            security_schemes=security_schemes,
            method_param_meta=self._method_param_meta,
            tag_definitions=tag_definitions,
        )

    def _get_thread_pool_config(self) -> Dict[str, Any]:
        try:
            config = self.application_context.get_config()
        except (AttributeError, TypeError):
            return {}
        server = config.get('server', {}) if isinstance(config, dict) else {}
        value = server.get('thread_pool', server.get('thread-pool', {}))
        return value if isinstance(value, dict) else {}

    async def _configure_sync_thread_pool(self) -> None:
        """Set AnyIO's per-worker thread limit after the ASGI loop starts."""
        from anyio.to_thread import current_default_thread_limiter

        current_default_thread_limiter().total_tokens = self._sync_max_workers

    async def _run_sync_handler(self, handler: Callable, call_params: Dict[str, Any]) -> Any:
        try:
            await asyncio.wait_for(
                self._sync_capacity.acquire(), timeout=self._sync_queue_timeout
            )
        except asyncio.TimeoutError as exc:
            raise _SyncHandlerOverloaded(
                "Synchronous request capacity exhausted"
            ) from exc
        try:
            return await run_in_threadpool(handler, **call_params)
        finally:
            self._sync_capacity.release()

    def _register_interceptors(self) -> None:
        """Attach managed ``HandlerInterceptor`` beans to the HTTP lifecycle."""
        if self._interceptors_registered:
            return
        from springbootai.web.interceptor import HandlerInterceptor, InterceptorManager, InterceptorRegistry

        registry = self._interceptor_registry or InterceptorRegistry()
        self._runtime_interceptor_registry = registry
        # 请求持久化监控是框架能力，默认关闭；开启后自动加入拦截器，
        # 项目无需再定义实体、Mapper、Controller 或手工注册 Bean。
        try:
            from springbootai.web.request_metrics import configure_request_metrics
            metrics_interceptor = configure_request_metrics(self.application_context.get_config())
            if metrics_interceptor is not None:
                registry.add_interceptor(metrics_interceptor)
                self._logger.info("Built-in request metrics enabled")
        except Exception as exc:
            self._logger.warning(
                "Built-in request metrics unavailable error_type=%s",
                type(exc).__name__)
        if self._interceptor_registry is None:
            for bean_name in self.application_context.get_bean_names():
                try:
                    bean = self.application_context.get_bean(bean_name)
                except Exception:
                    continue
                if isinstance(bean, HandlerInterceptor):
                    registry.add_interceptor(bean)
        manager = InterceptorManager(registry)

        @self.fastapi_app.middleware("http")
        async def interceptor_middleware(request: Request, call_next):
            handler, route_template = self._resolve_request_handler(request.scope)
            request.state.springbootai_route_template = route_template
            response = Response(status_code=500)
            error = None
            try:
                if not await manager.apply_pre_handle(request, handler):
                    return Response(status_code=403, content="Request rejected by interceptor")
                response = await call_next(request)
                await manager.apply_post_handle(request, response, handler)
                return response
            except Exception as exc:
                error = exc
                raise
            finally:
                try:
                    await manager.apply_after_completion(
                        request, response, handler, error
                    )
                except Exception:
                    self._logger.exception("Interceptor after_completion failed")

        self._interceptors_registered = True

    def _resolve_request_handler(self, scope: Dict[str, Any]):
        """Resolve the endpoint before Starlette's router mutates the scope."""
        from starlette.routing import Match
        for route in self.fastapi_app.router.routes:
            matcher = getattr(route, "matches", None)
            if not callable(matcher):
                continue
            try:
                match, child_scope = matcher(scope)
            except Exception:
                continue
            if match == Match.FULL:
                handler = (
                    child_scope.get("endpoint")
                    or getattr(route, "endpoint", None)
                    or (lambda: None)
                )
                return handler, getattr(route, "path", scope.get("path", ""))
        return (lambda: None), "<unmatched>"

    def refresh_runtime_configuration(self) -> None:
        """应用 Nacos/环境热更新后的 Web 配置，不重复注册 FastAPI 路由或中间件。"""
        config = self.application_context.get_config()
        try:
            from springbootai.web.actuator import configure_actuator
            configure_actuator(self.application_context)
        except Exception as exc:
            self._logger.warning(
                "Actuator runtime configuration refresh skipped error_type=%s",
                type(exc).__name__)

        try:
            from springbootai.web.request_metrics import configure_request_metrics
            from springbootai.web.request_metrics import resolve_request_metrics_config
            replacement = configure_request_metrics(config)
            registry = self._runtime_interceptor_registry
            if registry is not None:
                # 统一复用监控配置解析器，兼容 request-metrics/request_metrics、
                # 布尔值和环境变量合并后的字符串值。不能仅凭 replacement 判断，
                # 因为启用配置存储失败时 replacement 也会是 None，此时应保留旧实例。
                options = resolve_request_metrics_config(config)
                # replacement is None for both disabled and failed reconfiguration.
                # Only remove the old interceptor when the new config explicitly disables it;
                # failed hot updates keep the last known-good monitor running.
                if replacement is not None or not options["enabled"]:
                    registry.remove_interceptors(
                        lambda interceptor: getattr(
                            interceptor, "_springbootai_request_metrics", False
                        )
                    )
                if replacement is not None:
                    registry.add_interceptor(replacement)
        except Exception as exc:
            self._logger.warning(
                "Request metrics runtime configuration refresh skipped "
                "error_type=%s", type(exc).__name__)

    def _register_controllers(self) -> None:
        self._logger.info(f"Registering controllers, found {len(self.application_context.get_bean_names())} beans")
        for bean_name in self.application_context.get_bean_names():
            definition = self.application_context.bean_factory.get_bean_definition(bean_name)
            if not definition:
                continue

            annotations = definition.annotations
            if RestController._annotation_type not in annotations and \
               Controller._annotation_type not in annotations:
                continue

            self._logger.info(f"Found controller: {bean_name}")
            resolver = getattr(self.application_context, '_get_lifecycle_bean', None)
            if callable(resolver):
                controller_instance = resolver(bean_name, 'controller')
            else:
                try:
                    controller_instance = self.application_context.get_bean(bean_name)
                except Exception:
                    self._logger.warning(
                        "Skipping unavailable controller bean '%s'", bean_name,
                        exc_info=True,
                    )
                    continue
            if controller_instance is None:
                continue
            controller_class = controller_instance.__class__
            self._controller_classes.append(controller_class)

            class_mapping = self._get_class_mapping(controller_class)
            class_path = class_mapping.get('path', '')
            self._logger.info(f"Controller path: {class_path}")

            # 按方法定义顺序注册路由（遍历 MRO 的 __dict__，Python 3.7+ 保留定义顺序）。
            # 对齐 Spring MVC 静态路径优先的体验：开发者可将静态路径（如 /list）声明在
            # 动态路径（如 /{user_id}）之前，避免被动态路径拦截。
            # 注意：不能用 inspect.getmembers（按字母序），否则 /{user_id} 会拦截 /list。
            for method_name in self._iter_handler_names(controller_class):
                method = getattr(controller_instance, method_name)
                self._logger.info(f"Registering method: {method_name}")
                # Bound instance methods expose ``__func__``; static methods are
                # plain callables and do not.  Keep the underlying function when
                # available, otherwise pass the callable directly so controller
                # registration cannot fail on a valid ``@staticmethod`` handler.
                handler = getattr(method, "__func__", method)
                self._register_handler(controller_instance, handler, class_path)

    @staticmethod
    def _iter_handler_names(controller_class: Type):
        """按定义顺序遍历 Controller 及其 MRO 上的 handler 方法名（跳过 `_` 开头）。

        遍历 ``__mro__`` 的 ``__dict__`` 以保留源码定义顺序（Python 3.7+ 类命名空间有序），
        同时覆盖继承的 handler；子类同名方法覆盖父类。
        """
        seen = set()
        for klass in controller_class.__mro__:
            for name, member in vars(klass).items():
                if name.startswith('_') or name in seen:
                    continue
                # ``vars(cls)`` exposes ``staticmethod``/``classmethod`` as
                # descriptor objects rather than plain functions.  Unwrap the
                # descriptor before checking it so valid annotated handlers
                # are not silently omitted during route registration.
                if isinstance(member, (staticmethod, classmethod)):
                    member = member.__func__
                if inspect.isfunction(member) or inspect.ismethod(member):
                    seen.add(name)
                    yield name

    def _get_class_mapping(self, controller_class: Type) -> Dict[str, Any]:
        annotations = getattr(controller_class, '__spring_annotations__', [])
        for annotation in annotations:
            if isinstance(annotation, RequestMapping):
                return {
                    'path': annotation.path,
                    'method': annotation.method,
                    'consumes': annotation.consumes,
                    'produces': annotation.produces,
                }
        return {'path': '', 'method': [], 'consumes': None, 'produces': None}

    def _register_handler(self, controller_instance: Any, method: Callable, class_path: str) -> None:
        annotations = getattr(method, '__spring_annotations__', [])
        if not annotations:
            return

        # 收集 Swagger/OpenAPI 注解元数据（@Operation/@ApiResponse/@SecurityRequirement）
        from springbootai.web.swagger import collect_openapi_metadata, Parameter
        controller_class = controller_instance.__class__
        openapi_meta = collect_openapi_metadata(method, controller_class)
        # 收集方法级 @Parameter 元数据，供 configure_swagger 后处理注入
        method_params = [a for a in (getattr(method, '__spring_annotations__', []) or []) if isinstance(a, Parameter)]

        for annotation in annotations:
            if isinstance(annotation, (RequestMapping, GetMapping, PostMapping, PutMapping, PatchMapping, DeleteMapping)):
                paths = annotation.path if isinstance(annotation.path, list) else [annotation.path]
                class_paths = class_path if isinstance(class_path, list) else [class_path]
                methods = annotation.method or ['GET']
                for raw_path in paths or ['']:
                    path = raw_path or ''
                    prefix = class_paths[0] if class_paths else ''
                    if prefix:
                        path = prefix.rstrip('/')
                        if raw_path:
                            path += '/' + str(raw_path).lstrip('/')
                    elif not path:
                        path = '/'
                    endpoint = self._create_endpoint(controller_instance, method, path)
                    for http_method in methods:
                        self._add_route(http_method.lower(), path, endpoint, openapi_meta)
                        # 记录 @Parameter 元数据（key = path:method，与后处理一致）
                        if method_params:
                            key = f"{path}:{http_method.lower()}"
                            self._method_param_meta[key] = method_params

    def _create_endpoint(self, controller_instance: Any, method: Callable, path: str) -> Callable:
        from fastapi import Path as FastPath, Query as FastQuery, Body as FastBody, File as FastFile

        sig = inspect.signature(method)
        param_infos = []

        for param_name, param in sig.parameters.items():
            if param_name == 'self':
                continue
            
            # 检查是否在路径中
            path_param_match = re.search(r'\{' + param_name + r'\}', path)
            
            if isinstance(param.default, PathVariable):
                ann = param.default
                actual_name = ann.name or param_name
                param_infos.append({
                    'name': param_name, 'kind': 'path', 'http_name': actual_name,
                    'annotation': param.annotation if param.annotation is not inspect.Parameter.empty else str,
                    'default': None, 'required': True,
                })
            elif isinstance(param.default, RequestParam):
                ann = param.default
                actual_name = ann.name or param_name
                param_infos.append({
                    'name': param_name, 'kind': 'query', 'http_name': actual_name,
                    'annotation': param.annotation if param.annotation is not inspect.Parameter.empty else str,
                    'default': ann.default, 'required': ann.required,
                })
            elif isinstance(param.default, (RequestBody, Valid, Validated)):
                body_annotation = (
                    param.annotation
                    if param.annotation is not inspect.Parameter.empty
                    else dict
                )
                param_infos.append({
                    'name': param_name, 'kind': 'body', 'http_name': param_name,
                    'annotation': body_annotation, 'default': None,
                    'required': getattr(param.default, 'required', True),
                })
            elif isinstance(param.default, RequestPart):
                file_annotation = (
                    param.annotation
                    if param.annotation is not inspect.Parameter.empty
                    else UploadFile
                )
                ann = param.default
                actual_name = ann.name or param_name
                param_infos.append({
                    'name': param_name, 'kind': 'file', 'http_name': actual_name,
                    'annotation': file_annotation, 'default': None,
                    'required': ann.required, 'upload': ann,
                })
            elif isinstance(param.default, RequestHeader):
                ann = param.default
                header_name = ann.name or param_name.replace('_', '-')
                param_infos.append({
                    'name': param_name, 'kind': 'header', 'http_name': header_name,
                    'annotation': param.annotation if param.annotation is not inspect.Parameter.empty else str,
                    'default': ann.default, 'required': ann.required,
                })
            elif isinstance(param.default, CookieValue):
                ann = param.default
                cookie_name = ann.name or param_name
                param_infos.append({
                    'name': param_name, 'kind': 'cookie', 'http_name': cookie_name,
                    'annotation': param.annotation if param.annotation is not inspect.Parameter.empty else str,
                    'default': ann.default, 'required': ann.required,
                })
            elif path_param_match:
                # 路径中包含该参数名，视为路径参数
                param_infos.append({
                    'name': param_name, 'kind': 'path', 'http_name': param_name,
                    'annotation': param.annotation if param.annotation is not inspect.Parameter.empty else str,
                    'default': None, 'required': True,
                })
            elif param.annotation == dict:
                # dict 类型的参数，视为请求体参数
                param_infos.append({
                    'name': param_name, 'kind': 'body', 'http_name': param_name,
                    'annotation': dict, 'default': None, 'required': param.default is inspect.Parameter.empty,
                })
            elif param.default is not inspect.Parameter.empty:
                # 有默认值的参数，视为查询参数
                param_infos.append({
                    'name': param_name, 'kind': 'query', 'http_name': param_name,
                    'annotation': param.annotation if param.annotation is not inspect.Parameter.empty else str,
                    'default': param.default, 'required': False,
                })
            else:
                # 无默认值且不在路径中的参数，视为必需查询参数
                param_infos.append({
                    'name': param_name, 'kind': 'query', 'http_name': param_name,
                    'annotation': param.annotation if param.annotation is not inspect.Parameter.empty else str,
                    'default': None, 'required': True,
                })

        # 为动态 endpoint 构建参数签名
        endpoint_params = [
            inspect.Parameter('request', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Request),
        ]
        for info in param_infos:
            if info['kind'] == 'path':
                endpoint_params.append(inspect.Parameter(
                    info['name'], inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=FastPath(...), annotation=info['annotation'],
                ))
            elif info['kind'] == 'query':
                alias = info['http_name'] if info['http_name'] != info['name'] else None
                query_annotation = Optional.__getitem__(info['annotation'])
                if info['required'] and info['default'] is None:
                    endpoint_params.append(inspect.Parameter(
                        info['name'], inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        default=FastQuery(..., alias=alias), annotation=query_annotation,
                    ))
                else:
                    endpoint_params.append(inspect.Parameter(
                        info['name'], inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        default=FastQuery(info['default'], alias=alias), annotation=query_annotation,
                    ))
            elif info['kind'] == 'body':
                endpoint_params.append(inspect.Parameter(
                    info['name'], inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=FastBody(... if info['required'] else None), annotation=info['annotation'],
                ))
            elif info['kind'] == 'file':
                upload = info['upload']
                endpoint_params.append(inspect.Parameter(
                    info['name'], inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=FastFile(
                        ... if info['required'] else None,
                        alias=info['http_name'],
                        description=upload.description or None,
                        media_type=upload.media_type,
                    ),
                    annotation=info['annotation'],
                ))

        def make_endpoint(controller_instance, method, param_infos):
            method_annotations = getattr(method, '__spring_annotations__', [])
            controller_annotations = getattr(
                controller_instance.__class__, '__spring_annotations__', []
            )
            response_status = next(
                (item for item in method_annotations if isinstance(item, ResponseStatus)),
                next(
                    (
                        item for item in controller_annotations
                        if isinstance(item, ResponseStatus)
                    ),
                    None,
                ),
            )
            requires_authentication = any(
                type(item).__name__ == 'Authenticate' for item in method_annotations
            )

            async def endpoint(request: Request, **kwargs):
                try:
                    call_params = {}
                    for info in param_infos:
                        name = info['name']
                        if name in kwargs:
                            if kwargs[name] is None and info['required'] and info['kind'] in {'query', 'path', 'body', 'file'}:
                                raise ValueError(f"请求参数 '{info['http_name']}' 不能为空")
                            if info['kind'] == 'file':
                                self._validate_upload(kwargs[name], info['upload'])
                                call_params[name] = kwargs[name]
                            else:
                                call_params[name] = self._convert_type(kwargs[name], info['annotation'])
                        elif info['kind'] == 'body':
                            try:
                                body = await request.json()
                            except Exception:
                                if info['required']:
                                    raise ValueError(f"Request body '{name}' is required")
                                body = None
                            call_params[name] = self._convert_type(body, info['annotation'])
                        elif info['kind'] == 'header':
                            value = request.headers.get(info['http_name'])
                            if value is None:
                                if info['required']:
                                    raise ValueError(f"Header '{info['http_name']}' is required")
                                value = info['default']
                            call_params[name] = self._convert_type(value, info['annotation'])
                        elif info['kind'] == 'query':
                            if info['required']:
                                raise ValueError(f"Query parameter '{info['http_name']}' is required")
                            call_params[name] = info['default']
                        elif info['kind'] == 'cookie':
                            value = request.cookies.get(info['http_name'])
                            if value is None:
                                if info['required']:
                                    raise ValueError(f"Cookie '{info['http_name']}' is required")
                                value = info['default']
                            call_params[name] = self._convert_type(value, info['annotation'])

                    if requires_authentication:
                        call_params['_spring_request'] = request
                    handler = getattr(controller_instance, method.__name__)
                    if inspect.iscoroutinefunction(handler):
                        result = await handler(**call_params)
                    else:
                        # FastAPI normally offloads sync endpoints automatically.  SpringBootAI
                        # wraps every controller in an async adapter, so it must preserve
                        # that behavior explicitly for blocking DB/HTTP/AI workloads.
                        result = await self._run_sync_handler(handler, call_params)
                        if inspect.isawaitable(result):
                            result = await result

                    if not isinstance(result, Result):
                        result = Result.success(data=result)
                    if response_status is not None:
                        result = Result(
                            code=response_status.code,
                            message=response_status.reason or result.message,
                            data=result.data,
                        )
                    return self._result_response(result)

                except _SyncHandlerOverloaded as e:
                    return JSONResponse(
                        status_code=503,
                        headers={'Retry-After': '1'},
                        content={
                            'code': 503,
                            'message': str(e),
                            'data': None,
                        },
                    )
                except Exception as e:
                    # 认证/授权失败是可预期的客户端状态，必须优先于项目的
                    # @ExceptionHandler(Exception)。否则宽泛兜底会把过期 Token
                    # 错误包装为 500，客户端无法触发重新登录或刷新令牌。
                    security_response = self._security_failure_response(e)
                    if security_response is not None:
                        self._logger.warning(
                            "Request rejected method=%s path=%s status=%s "
                            "error_type=%s request_id=%s",
                            request.method,
                            request.url.path,
                            security_response.status_code,
                            type(e).__name__,
                            get_request_id(),
                        )
                        return security_response

                    handler = self._find_exception_handler(e)
                    if isinstance(e, (ValueError, TypeError)):
                        self._logger.warning(
                            "Bad request method=%s path=%s error_type=%s request_id=%s",
                            request.method, request.url.path,
                            type(e).__name__, get_request_id(),
                        )
                    else:
                        safe_error = sanitize_exception_value(e)
                        self._logger.error(
                            "Request processing failed method=%s path=%s "
                            "error_type=%s request_id=%s",
                            request.method, request.url.path,
                            type(e).__name__, get_request_id(),
                            exc_info=(
                                type(safe_error), safe_error,
                                safe_error.__traceback__,
                            ),
                        )
                    if handler is not None:
                        try:
                            handler_result = handler(e)
                            if inspect.isawaitable(handler_result):
                                handler_result = await handler_result
                            if isinstance(handler_result, Result):
                                return self._result_response(handler_result)
                            return self._result_response(
                                Result.error(message="Internal server error", code=500)
                            )
                        except Exception as handler_exc:
                            # An exception handler is application code; a bug in
                            # it must not escape the endpoint and take down the
                            # request task.  Preserve the original failure in logs
                            # while returning the same generic response policy.
                            safe_handler_error = sanitize_exception_value(
                                handler_exc)
                            self._logger.error(
                                "Exception handler failed for %s error_type=%s",
                                type(e).__name__, type(handler_exc).__name__,
                                exc_info=(
                                    type(safe_handler_error), safe_handler_error,
                                    safe_handler_error.__traceback__,
                                ),
                            )
                            return self._result_response(
                                Result.error(message="Internal server error", code=500)
                            )
                    if isinstance(e, (ValueError, TypeError)):
                        return self._result_response(Result.bad_request(message=str(e)))
                    # 生产环境隐藏详细错误信息
                    return self._result_response(
                        Result.error(message="Internal server error", code=500)
                    )

            # 替换签名，让 FastAPI 正确识别路径/查询/body参数
            original_sig = inspect.signature(endpoint)
            new_sig = original_sig.replace(parameters=endpoint_params)
            endpoint.__signature__ = new_sig
            endpoint.__name__ = method.__name__
            return endpoint

        return make_endpoint(controller_instance, method, param_infos)

    @staticmethod
    def _validate_upload(value: Any, annotation: RequestPart) -> None:
        """执行上传文件的可选扩展名和大小校验，不读取/消耗文件流。"""
        values = value if isinstance(value, (list, tuple)) else [value]
        for upload in values:
            if upload is None:
                continue
            filename = str(getattr(upload, "filename", "") or "")
            if annotation.allowed_extensions:
                suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
                if suffix not in annotation.allowed_extensions:
                    allowed = ", ".join(f".{item}" for item in annotation.allowed_extensions)
                    raise ValueError(
                        f"文件 '{filename or '未命名文件'}' 类型不允许，仅支持: {allowed}"
                    )
            if annotation.max_size is not None:
                size = getattr(upload, "size", None)
                if size is not None:
                    try:
                        numeric_size = int(size)
                    except (TypeError, ValueError):
                        numeric_size = None
                    if numeric_size is not None and numeric_size > annotation.max_size:
                        raise ValueError(
                            f"文件 '{filename or '未命名文件'}' 超过大小限制 "
                            f"({annotation.max_size} bytes)"
                        )

    @staticmethod
    def _security_failure_response(error: Exception) -> Optional[JSONResponse]:
        """将框架认证/授权异常转换为稳定的 HTTP 响应。

        Security AOP 使用带 ``status_code`` 的异常表达认证状态。此处只接管 401、403，
        不干预项目自定义的普通异常处理。响应不暴露 JWT 库的签名、过期时间等细节，
        具体原因仅保留在 WARNING 日志中。
        """
        status_code = getattr(error, "status_code", None)
        if status_code == 401:
            return WebApplicationContext._result_response(
                Result.unauthorized(message="Authentication required"),
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
            )
        if status_code == 403:
            return WebApplicationContext._result_response(
                Result.forbidden(message="Access denied")
            )
        return None

    @staticmethod
    def _result_response(
        result: Result,
        headers: Optional[Dict[str, str]] = None,
    ) -> JSONResponse:
        status_code = result.code if 100 <= result.code <= 599 else 500
        return JSONResponse(
            status_code=status_code,
            headers=headers,
            content=json.loads(json.dumps({
                'code': result.code,
                'message': result.message,
                'data': result.data,
            }, cls=_JsonEncoder)),
        )

    def _extract_path_param_names(self, path: str) -> List[str]:
        return re.findall(r'\{([^}]+)\}', path)

    def _find_exception_handler(self, error: Exception) -> Optional[Callable]:
        """Match handlers using normal Python subclass semantics."""
        candidates = [
            (exception_type, handler)
            for exception_type, handler in self._exception_handlers.items()
            if isinstance(error, exception_type)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: len(getattr(item[0], '__mro__', ())), reverse=True)
        return candidates[0][1]

    def _convert_type(self, value: Any, target_type: Type) -> Any:
        if value is None:
            return None

        origin = get_origin(target_type)
        if origin is Union:
            candidates = [item for item in get_args(target_type) if item is not type(None)]
            if len(candidates) == 1:
                return self._convert_type(value, candidates[0])

        if target_type is int:
            return int(value)
        elif target_type is float:
            return float(value)
        elif target_type is bool:
            return str(value).lower() == 'true'
        elif target_type is str:
            return str(value)
        return value

    def _add_route(self, http_method: str, path: str, endpoint: Callable,
                   openapi_meta: Optional[Dict[str, Any]] = None) -> None:
        # 将 Swagger 注解元数据传给 FastAPI 路由装饰器（tags/summary/description/
        # operation_id/deprecated/responses/security）
        kwargs = dict(openapi_meta) if openapi_meta else {}
        if http_method == 'get':
            self.fastapi_app.get(path, **kwargs)(endpoint)
        elif http_method == 'post':
            self.fastapi_app.post(path, **kwargs)(endpoint)
        elif http_method == 'put':
            self.fastapi_app.put(path, **kwargs)(endpoint)
        elif http_method == 'patch':
            self.fastapi_app.patch(path, **kwargs)(endpoint)
        elif http_method == 'delete':
            self.fastapi_app.delete(path, **kwargs)(endpoint)

    def _register_exception_handlers(self) -> None:
        for bean_name in self.application_context.get_bean_names():
            definition = self.application_context.bean_factory.get_bean_definition(bean_name)
            if not definition:
                continue

            if ControllerAdvice._annotation_type in definition.annotations:
                resolver = getattr(self.application_context, '_get_lifecycle_bean', None)
                if callable(resolver):
                    advice_instance = resolver(bean_name, 'exception-handler')
                else:
                    try:
                        advice_instance = self.application_context.get_bean(bean_name)
                    except Exception:
                        self._logger.warning(
                            "Skipping unavailable exception handler bean '%s'",
                            bean_name,
                            exc_info=True,
                        )
                        continue
                if advice_instance is None:
                    continue
                advice_class = advice_instance.__class__

                for method_name, method in inspect.getmembers(advice_class):
                    if not method_name.startswith('_') and inspect.isfunction(method):
                        annotations = getattr(method, '__spring_annotations__', [])
                        for annotation in annotations:
                            if isinstance(annotation, ExceptionHandler):
                                for exception_type in annotation.exceptions:
                                    self._exception_handlers[exception_type] = method.__get__(advice_instance)

    def _register_cors_middleware(self) -> None:
        from fastapi.middleware.cors import CORSMiddleware

        configured_cors = self.application_context.get_value('server.cors', {}) or {}
        # Invalid/null CORS sections should not prevent the application from
        # starting.  Treat non-mapping values as an empty configuration and let
        # the framework defaults apply.
        if not isinstance(configured_cors, dict):
            self._logger.warning(
                "Ignoring invalid server.cors configuration (expected an object)"
            )
            configured_cors = {}
        cors_config = {
            "allow_origins": configured_cors.get('allow_origins', []),
            "allow_credentials": configured_cors.get('allow_credentials', False),
            "allow_methods": configured_cors.get(
                'allow_methods', ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
            ),
            "allow_headers": configured_cors.get(
                'allow_headers', ["Content-Type", "Authorization"]
            ),
            "max_age": configured_cors.get('max_age', 600),
        }

        for bean_name in self.application_context.get_bean_names():
            definition = self.application_context.bean_factory.get_bean_definition(bean_name)
            if not definition:
                continue

            if CrossOrigin._annotation_type in definition.annotations:
                cors_annotations = definition.annotations[CrossOrigin._annotation_type]
                if cors_annotations:
                    try:
                        cors_annotation = cors_annotations[0]
                        credentials = cors_annotation.allowCredentials
                        origins = cors_annotation.origins
                        
                        if credentials and "*" in origins:
                            raise ValueError("CORS开启凭证时不能允许通配来源")
                        
                        cors_config.update({
                            "allow_origins": origins,
                            "allow_methods": cors_annotation.methods,
                            "allow_headers": cors_annotation.allowedHeaders,
                            "allow_credentials": credentials,
                            "max_age": cors_annotation.maxAge,
                        })
                    except Exception as e:
                        self._logger.error(
                            "Failed to parse CORS configuration: "
                            f"error_type={type(e).__name__}")
                
                break

        self.fastapi_app.add_middleware(CORSMiddleware, **cors_config)

    def _register_static_files(self) -> None:
        """注册静态文件服务"""
        if self._static_dir and os.path.isdir(self._static_dir):
            from fastapi.staticfiles import StaticFiles
            from fastapi.responses import FileResponse
            
            # 获取静态目录的绝对路径，用于路径安全验证
            self._static_dir_abs = os.path.realpath(self._static_dir)
            
            # 挂载静态文件目录
            self.fastapi_app.mount("/static", StaticFiles(directory=self._static_dir), name="static")
            
            # 添加首页路由
            @self.fastapi_app.get("/")
            async def serve_index():
                index_path = os.path.join(self._static_dir_abs, "index.html")
                if os.path.exists(index_path) and os.path.isfile(index_path):
                    return FileResponse(index_path)
                return {"error": "index.html not found"}
            
            # 添加其他静态文件路由（处理 js、css、images 等）
            @self.fastapi_app.get("/{full_path:path}")
            async def serve_static(full_path: str):
                # 安全验证：防止路径遍历攻击
                if '..' in full_path:
                    from fastapi import HTTPException
                    raise HTTPException(status_code=403, detail="Forbidden")
                
                file_path = os.path.join(self._static_dir_abs, full_path)
                # 使用 realpath 验证路径是否在静态目录内
                real_file_path = os.path.realpath(file_path)
                
                # 确保请求的文件在静态目录内
                if not real_file_path.startswith(self._static_dir_abs + os.sep) and real_file_path != self._static_dir_abs:
                    from fastapi import HTTPException
                    raise HTTPException(status_code=403, detail="Forbidden")
                
                if os.path.exists(real_file_path) and os.path.isfile(real_file_path):
                    return FileResponse(real_file_path)
                # 如果是 API 请求，返回 404 让 API 路由处理
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Not Found")
            
            self._logger.info("Static file service registered: %s", self._static_dir_abs)
        else:
            if self._static_dir:
                self._logger.warning(
                    "Static file directory does not exist: %s", self._static_dir)

    def get_app(self) -> FastAPI:
        return self.fastapi_app

    def _register_health_endpoints(self) -> None:
        """注册健康检查端点 + Actuator 运维端点。"""
        try:
            from springbootai.web.health import configure_health_checks, health_router
            configure_health_checks(self.application_context)
            self.fastapi_app.include_router(health_router, prefix="/actuator")
            self._logger.info("Health check endpoints registered")
        except Exception as e:
            self._logger.warning(f"Failed to register health check endpoints: {e}")
        # Actuator 标准运维端点（/env /loggers /metrics /beans /configprops /mappings /threaddump）
        try:
            from springbootai.web.actuator import actuator_router, configure_actuator
            configure_actuator(self.application_context)
            self.fastapi_app.include_router(actuator_router, prefix="/actuator")
            self._logger.info("Actuator endpoints registered")
        except Exception as e:
            self._logger.warning(f"Failed to register actuator endpoints: {e}")

    def _register_shutdown_handlers(self) -> None:
        def close_resources() -> None:
            try:
                from springbootai.messaging.rabbitmq import rabbitmq_client
                rabbitmq_client.close()
            except ImportError:
                pass
            except Exception as exc:
                self._logger.warning(
                    "RabbitMQ cleanup failed during shutdown error_type=%s",
                    type(exc).__name__)

            try:
                from springbootai.cloud.feign import FeignClientFactory
                FeignClientFactory.close_all()
            except ImportError:
                pass
            except Exception as exc:
                self._logger.warning(
                    "Feign cleanup failed during shutdown error_type=%s",
                    type(exc).__name__)

            # ApplicationContext owns more than BeanFactory instances: it also
            # owns scheduled tasks, event listeners, and the active-context
            # reference.  Calling destroy_all() directly leaves those resources
            # alive after an ASGI lifespan shutdown.
            destroy_context = getattr(self.application_context, 'destroy', None)
            if callable(destroy_context):
                destroy_context()
            else:
                # Preserve compatibility with lightweight test/embedding
                # contexts that only provide a BeanFactory-like object.
                self.application_context.bean_factory.destroy_all()

        self.fastapi_app.router.add_event_handler('shutdown', close_resources)

    def run(self, host: str = "0.0.0.0", port: int = 8080, **kwargs) -> None:  # nosec B104 - explicit server API
        # 优先使用 uvicorn，fallback 到其他方案
        try:
            import uvicorn
            # log_config=None 禁用 Uvicorn 默认 LOGGING_CONFIG，
            # 避免其为 uvicorn/uvicorn.access logger 添加 StreamHandler（propagate=False）
            # 覆盖 SpringLogger._intercept_third_party_loggers 的 LoguruHandler 拦截。
            # 拦截由 init_logging → _setup_loguru → _intercept_third_party_loggers 完成，
            # 使访问日志（GET /api/xxx 200 OK）和启动日志也写入配置的日志文件。
            run_options = dict(kwargs)
            run_options.pop("host", None)
            run_options.pop("port", None)
            run_options.setdefault("log_config", None)
            uvicorn.run(
                self.fastapi_app, host=host, port=port, **run_options)
        except ImportError:
            try:
                from a2wsgi import ASGIMiddleware, WSGIServer
                wsgi_app = ASGIMiddleware(self.fastapi_app)
                server = WSGIServer(wsgi_app, host=host, port=port)
                server.run()
            except ImportError:
                raise RuntimeError("Neither uvicorn nor a2wsgi is installed. Please install one of them.")
