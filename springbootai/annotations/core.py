from typing import Optional, Union, Any, Type, List, Callable, Tuple
import inspect

# Public annotation API for direct imports and IDE static analysis. Keep this
# list aligned with the symbols re-exported by ``springbootai.annotations``.
__all__ = [
    "SpringAnnotation", "get_spring_annotations", "ApplicationEvent", "EventListener",
    "SpringBootApplication", "ComponentScan", "RestController", "Controller",
    "RequestMapping", "GetMapping", "PostMapping", "PutMapping", "PatchMapping",
    "DeleteMapping", "Service", "Component", "Aspect", "Pointcut", "Order", "Before",
    "After", "Around", "AfterReturning", "AfterThrowing", "Repository", "Autowired",
    "Qualifier", "Configuration", "Scope", "Bean", "Value", "ConfigurationProperties",
    "RequestParam", "PathVariable", "RequestBody", "RequestPart", "FileUpload",
    "Valid", "Validated", "CrossOrigin",
    "ControllerAdvice", "ExceptionHandler", "Slf4j", "LogExecutionTime", "PostConstruct",
    "PreDestroy", "Primary", "Profile", "Lazy", "RequestHeader", "CookieValue",
    "ResponseStatus", "Transactional", "Cacheable", "Retryable", "Recover", "Async",
    "Scheduled", "AsyncResult", "RateLimit", "CircuitBreaker", "Idempotent", "AuditLog",
    "FeatureToggle", "Lock", "Metrics", "Synchronized", "Validate", "Trace",
    "PreAuthorize", "PostAuthorize", "Secured", "Authenticate",
]

class SpringAnnotation:
    _annotation_type: str = "base"

    def __new__(cls, *args, **kwargs):
        # 如果第一个参数是类或函数，且不是内置类型，说明是@Annotation形式（不带括号）
        if args and (isinstance(args[0], type) or callable(args[0])):
            target = args[0]
            # 排除内置类型（如ValueError, Exception等），它们是注解的参数，不是目标
            if isinstance(target, type) and target.__module__ in ('builtins', '__builtin__'):
                # 这是内置类型，作为注解参数处理
                return super().__new__(cls)
            # 创建注解实例
            instance = super().__new__(cls)
            # 应用注解
            instance.__init__(*args[1:], **kwargs)
            # ``hasattr`` also sees annotations inherited from a base class.
            # Each decorated target needs its own list, otherwise decorating a
            # subclass silently mutates the parent's Spring metadata.
            if '__spring_annotations__' not in target.__dict__:
                target.__spring_annotations__ = []
            target.__spring_annotations__.append(instance)
            instance._original_class = target
            # 返回原始类，而不是注解实例
            return target
        # 否则是@Annotation()形式，返回注解实例
        return super().__new__(cls)

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self._original_class = None

    def __call__(self, target: Union[Type, Callable]) -> Union[Type, Callable]:
        if '__spring_annotations__' not in target.__dict__:
            target.__spring_annotations__ = []
        target.__spring_annotations__.append(self)
        self._original_class = target
        return target


def get_spring_annotations(target: Any) -> List["SpringAnnotation"]:
    """Return annotations declared directly on *target* in declaration order.

    Spring's metadata is intentionally not merged from base classes.  This
    helper gives scanners and integrations one consistent read path and keeps
    inherited annotations from being mistaken for declarations on a subclass.
    """
    return list(getattr(target, "__dict__", {}).get("__spring_annotations__", []))


class ApplicationEvent:
    """Base class for events published through the application context."""

    def __init__(self, source: Any = None):
        self.source = source


class EventListener(SpringAnnotation):
    """Mark a bean method as an application event listener."""

    _annotation_type = "event_listener"

    def __new__(cls, *args, **kwargs):
        # ``@EventListener(MyEvent)`` is a common shorthand.  The base
        # annotation treats a positional class as a decorator target, so
        # event classes need to be recognized before delegating to it.
        if args and isinstance(args[0], type):
            try:
                if issubclass(args[0], ApplicationEvent):
                    return object.__new__(cls)
            except TypeError:
                pass
        return super().__new__(cls, *args, **kwargs)

    def __init__(
        self,
        event_type: Optional[Type[ApplicationEvent]] = None,
        order: int = 0,
    ):
        super().__init__(event_type=event_type, order=order)


class SpringBootApplication(SpringAnnotation):
    _annotation_type = "boot"

    def __init__(self, scan_base_packages: Optional[List[str]] = None):
        super().__init__(scan_base_packages=scan_base_packages)


class ComponentScan(SpringAnnotation):
    _annotation_type = "scan"

    def __init__(self, base_packages: Optional[List[str]] = None):
        super().__init__(base_packages=base_packages)


class RestController(SpringAnnotation):
    _annotation_type = "controller"

    def __init__(self, value: str = ""):
        super().__init__(value=value)


class Controller(SpringAnnotation):
    _annotation_type = "controller"

    def __init__(self, value: str = ""):
        super().__init__(value=value)


class RequestMapping(SpringAnnotation):
    _annotation_type = "mapping"

    def __init__(
        self,
        path: Union[str, List[str]] = "",
        method: Optional[Union[str, List[str]]] = None,
        consumes: Optional[str] = None,
        produces: Optional[str] = None,
        value: Optional[Union[str, List[str]]] = None,
    ):
        if value is not None:
            if path:
                raise TypeError("RequestMapping 的 path 和 value 只能设置一个")
            path = value
        if isinstance(method, str):
            method = [method]
        super().__init__(path=path, method=[m.upper() for m in (method or [])], consumes=consumes, produces=produces)


class GetMapping(SpringAnnotation):
    _annotation_type = "mapping"

    def __init__(
        self,
        path: Union[str, List[str]] = "",
        consumes: Optional[str] = None,
        produces: Optional[str] = None,
        value: Optional[Union[str, List[str]]] = None,
    ):
        if value is not None:
            if path:
                raise TypeError("GetMapping 的 path 和 value 只能设置一个")
            path = value
        super().__init__(path=path, method=["GET"], consumes=consumes, produces=produces)


class PostMapping(SpringAnnotation):
    _annotation_type = "mapping"

    def __init__(
        self,
        path: Union[str, List[str]] = "",
        consumes: Optional[str] = None,
        produces: Optional[str] = None,
        value: Optional[Union[str, List[str]]] = None,
    ):
        if value is not None:
            if path:
                raise TypeError("PostMapping 的 path 和 value 只能设置一个")
            path = value
        super().__init__(path=path, method=["POST"], consumes=consumes, produces=produces)


class PutMapping(SpringAnnotation):
    _annotation_type = "mapping"

    def __init__(
        self,
        path: Union[str, List[str]] = "",
        consumes: Optional[str] = None,
        produces: Optional[str] = None,
        value: Optional[Union[str, List[str]]] = None,
    ):
        if value is not None:
            if path:
                raise TypeError("PutMapping 的 path 和 value 只能设置一个")
            path = value
        super().__init__(path=path, method=["PUT"], consumes=consumes, produces=produces)


class PatchMapping(SpringAnnotation):
    _annotation_type = "mapping"

    def __init__(
        self,
        path: Union[str, List[str]] = "",
        consumes: Optional[str] = None,
        produces: Optional[str] = None,
        value: Optional[Union[str, List[str]]] = None,
    ):
        if value is not None:
            if path:
                raise TypeError("PatchMapping 的 path 和 value 只能设置一个")
            path = value
        super().__init__(path=path, method=["PATCH"], consumes=consumes, produces=produces)


class DeleteMapping(SpringAnnotation):
    _annotation_type = "mapping"

    def __init__(
        self,
        path: Union[str, List[str]] = "",
        consumes: Optional[str] = None,
        produces: Optional[str] = None,
        value: Optional[Union[str, List[str]]] = None,
    ):
        if value is not None:
            if path:
                raise TypeError("DeleteMapping 的 path 和 value 只能设置一个")
            path = value
        super().__init__(path=path, method=["DELETE"], consumes=consumes, produces=produces)


class Service(SpringAnnotation):
    _annotation_type = "component"

    def __init__(self, value: str = ""):
        super().__init__(value=value)


class Component(SpringAnnotation):
    _annotation_type = "component"

    def __init__(self, value: str = ""):
        super().__init__(value=value)


class Aspect(Component):
    """Declare a component whose methods contain AOP advice."""

    _annotation_type = "aspect"


class Pointcut(SpringAnnotation):
    """Declare a reusable pointcut expression on an aspect method."""

    _annotation_type = "pointcut"

    def __init__(self, value: str):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Pointcut value must be a non-empty string")
        super().__init__(value=value.strip())


class Order(SpringAnnotation):
    """声明组件/通知的执行优先级（对齐 Spring ``@Order``）。

    数值越小优先级越高：
    - 切面通知：优先级高的 @Before 先执行、@After 后执行（对齐 Spring 语义）
    - BeanPostProcessor / 拦截器：数值小的先执行

    使用示例：
        @Aspect
        @Order(1)  # 比 @Order(2) 的通知先执行
        class LoggingAspect:
            ...
    """

    _annotation_type = "order"

    def __init__(self, value: int = 0):
        super().__init__(value=int(value))

    def get_order(self) -> int:
        return int(self.value)


class _AdviceAnnotation:
    def _init_advice(self, value: str = "", *, pointcut: Optional[str] = None):
        expression = pointcut if pointcut is not None else value
        if not isinstance(expression, str) or not expression.strip():
            raise ValueError("Advice pointcut must be a non-empty string")
        SpringAnnotation.__init__(self, value=expression.strip())


class Before(_AdviceAnnotation, SpringAnnotation):
    """Run advice before a matched method."""

    _annotation_type = "advice"

    def __init__(self, value: str = "", *, pointcut: Optional[str] = None):
        self._init_advice(value, pointcut=pointcut)


class After(Before):
    """Run advice after a matched method, including exceptional completion."""


class Around(Before):
    """Wrap a matched method with a ``ProceedingJoinPoint``."""


class AfterReturning(Before):
    """Run advice after a matched method returns successfully."""

    def __init__(
        self,
        value: str = "",
        *,
        pointcut: Optional[str] = None,
        returning: str = "result",
    ):
        self._init_advice(value, pointcut=pointcut)
        self.returning = returning


class AfterThrowing(Before):
    """Run advice after a matched method raises an exception."""

    def __init__(
        self,
        value: str = "",
        *,
        pointcut: Optional[str] = None,
        throwing: str = "exception",
    ):
        self._init_advice(value, pointcut=pointcut)
        self.throwing = throwing


class Repository(SpringAnnotation):
    _annotation_type = "component"

    def __init__(self, value: str = ""):
        super().__init__(value=value)


class Autowired(SpringAnnotation):
    _annotation_type = "inject"

    def __init__(self, required: bool = True):
        super().__init__(required=required)


class Qualifier(SpringAnnotation):
    _annotation_type = "qualifier"

    def __init__(self, value: str):
        super().__init__(value=value)


class Configuration(SpringAnnotation):
    _annotation_type = "configuration"

    def __init__(self, proxyBeanMethods: bool = True, proxy_bean_methods: Optional[bool] = None):
        if proxy_bean_methods is not None:
            proxyBeanMethods = proxy_bean_methods
        super().__init__(proxyBeanMethods=proxyBeanMethods)


class Scope(SpringAnnotation):
    """Declare a Bean scope (``singleton`` or ``prototype``)."""

    _annotation_type = "scope"

    def __init__(self, value: str = "singleton"):
        normalized = str(value).lower()
        if normalized not in {"singleton", "prototype"}:
            raise ValueError("Scope 仅支持 singleton 或 prototype")
        super().__init__(value=normalized)


class Bean(SpringAnnotation):
    _annotation_type = "bean"

    def __init__(
        self,
        name: Optional[str] = None,
        scope: str = "singleton",
        init_method: Optional[str] = None,
        destroy_method: Optional[str] = None,
    ):
        super().__init__(name=name, scope=scope, init_method=init_method, destroy_method=destroy_method)


class Value(SpringAnnotation):
    _annotation_type = "value"

    def __init__(self, value: str, default: Any = None):
        super().__init__(value=value, default=default)


class ConfigurationProperties(SpringAnnotation):
    _annotation_type = "properties"

    def __init__(self, prefix: str):
        super().__init__(prefix=prefix)


class RequestParam:
    _annotation_type = "param"

    def __init__(
        self,
        name: Optional[str] = None,
        required: bool = True,
        default: Any = None,
        value: Optional[str] = None,
    ):
        self.name = value if value is not None else name
        self.required = required
        self.default = default


class PathVariable:
    _annotation_type = "param"

    def __init__(self, name: Optional[str] = None, required: bool = True, value: Optional[str] = None):
        self.name = value if value is not None else name
        self.required = required


class RequestBody:
    _annotation_type = "param"

    def __init__(self, required: bool = True, value: Optional[bool] = None):
        if value is not None:
            required = value
        self.required = required


class RequestPart:
    """绑定 ``multipart/form-data`` 中的文件字段。

    这是 Spring ``@RequestPart`` 的 Python 版本。参数类型建议标注为
    ``UploadFile`` 或 ``list[UploadFile]``，框架会自动生成 FastAPI 的
    ``File(...)`` 参数并把上传对象传入 Controller。``allowed_extensions``
    和 ``max_size`` 是框架侧的轻量安全校验，避免每个项目重复写文件名和大小检查。
    """

    _annotation_type = "param"

    def __init__(
        self,
        name: Optional[str] = None,
        required: bool = True,
        value: Optional[str] = None,
        description: str = "",
        media_type: Optional[str] = None,
        max_size: Optional[int] = None,
        allowed_extensions: Optional[List[str] | Tuple[str, ...] | str] = None,
    ):
        self.name = value if value is not None else name
        self.required = bool(required)
        self.description = description or ""
        self.media_type = media_type
        try:
            self.max_size = int(max_size) if max_size is not None else None
        except (TypeError, ValueError):
            raise TypeError("max_size must be a positive integer or None")
        if self.max_size is not None and self.max_size <= 0:
            raise ValueError("max_size must be greater than zero")
        if isinstance(allowed_extensions, str):
            allowed_extensions = allowed_extensions.split(",")
        self.allowed_extensions = tuple(
            str(item).strip().lower().lstrip(".")
            for item in (allowed_extensions or ())
            if str(item).strip()
        )


# 文件上传在业务代码里更直观的别名；保留 RequestPart 作为 Spring 风格主名称。
FileUpload = RequestPart


class Valid(SpringAnnotation):
    """Mark a request-body parameter for FastAPI/Pydantic validation.

    Validation groups are retained as migration metadata. Field validation is
    performed by the annotated Pydantic model at request time.
    """

    _annotation_type = "param"

    def __init__(self, groups: Optional[List[Type]] = None):
        super().__init__(groups=groups or [])


class Validated(SpringAnnotation):
    """Request-body validation marker that keeps optional group metadata."""

    _annotation_type = "param"

    def __init__(self, groups: Optional[List[Type]] = None):
        super().__init__(groups=groups or [])


class CrossOrigin(SpringAnnotation):
    _annotation_type = "cors"

    def __init__(
        self,
        origins: Optional[List[str]] = None,
        methods: Optional[List[str]] = None,
        allowedHeaders: Optional[List[str]] = None,
        allowCredentials: bool = False,
        maxAge: int = 3600,
        allowed_headers: Optional[List[str]] = None,
        allow_credentials: Optional[bool] = None,
        max_age: Optional[int] = None,
    ):
        if allowed_headers is not None:
            allowedHeaders = allowed_headers
        if allow_credentials is not None:
            allowCredentials = allow_credentials
        if max_age is not None:
            maxAge = max_age
        super().__init__(
            origins=origins or ["*"],
            methods=methods or ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allowedHeaders=allowedHeaders or ["*"],
            allowCredentials=allowCredentials,
            maxAge=maxAge,
        )


class ControllerAdvice(SpringAnnotation):
    """声明一个由框架自动发现的全局 Web 异常处理类。

    被该注解标记的类会在 WebApplicationContext 初始化时扫描其
    ``@ExceptionHandler`` 方法，并按照异常类型注册到全局异常处理链。
    Controller 不需要手动创建或调用这个类。
    """

    _annotation_type = "advice"

    def __init__(self):
        """创建无状态的全局 Advice 注解实例。"""
        super().__init__()


class ExceptionHandler(SpringAnnotation):
    _annotation_type = "exception_handler"

    def __new__(cls, *exceptions: Type[Exception], value: Optional[List[Type[Exception]]] = None):
        """Keep exception classes as annotation arguments.

        ``SpringAnnotation.__new__`` treats a callable first argument as the
        target of a decorator.  Exception classes are callable too, so a
        custom ``@ExceptionHandler(MyError)`` used to replace the decorated
        method with ``MyError``.  ExceptionHandler has an unambiguous contract:
        its positional arguments are always exception types.
        """
        return object.__new__(cls)

    def __init__(self, *exceptions: Type[Exception], value: Optional[List[Type[Exception]]] = None):
        if value:
            exceptions = tuple(value)
        super().__init__(
            value=list(exceptions) if exceptions else [],
            exceptions=exceptions
        )


class Slf4j(SpringAnnotation):
    _annotation_type = "logging"

    def __init__(self, logger_name: Optional[str] = None):
        super().__init__(logger_name=logger_name)


class LogExecutionTime(SpringAnnotation):
    _annotation_type = "logging"

    def __init__(self, log_level: str = "info"):
        super().__init__(log_level=log_level)

    def __call__(self, func: Callable) -> Callable:
        super().__call__(func)
        
        import time
        import functools

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.time()
                try:
                    return await func(*args, **kwargs)
                finally:
                    execution_time = time.time() - start_time
                    logger = self._get_logger(func)
                    log_method = getattr(logger, self.log_level.lower(), logger.info)
                    log_method(
                        f"Execution time for {func.__name__}: {execution_time:.4f}s"
                    )

            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                return func(*args, **kwargs)
            finally:
                execution_time = time.time() - start_time
                logger = self._get_logger(func)
                log_method = getattr(logger, self.log_level.lower(), logger.info)
                log_method(f"Execution time for {func.__name__}: {execution_time:.4f}s")

        return wrapper

    def _get_logger(self, func: Callable) -> Any:
        from springbootai.utils.logger import get_logger
        return get_logger(func.__module__)


class PostConstruct(SpringAnnotation):
    _annotation_type = "lifecycle"

    def __init__(self):
        super().__init__()


class PreDestroy(SpringAnnotation):
    _annotation_type = "lifecycle"

    def __init__(self):
        super().__init__()


class Primary(SpringAnnotation):
    _annotation_type = "primary"

    def __init__(self):
        super().__init__()


class Profile(SpringAnnotation):
    _annotation_type = "profile"

    def __init__(self, value: Union[str, List[str]]):
        if isinstance(value, str):
            value = [value]
        super().__init__(value=value)


class Lazy(SpringAnnotation):
    _annotation_type = "lazy"

    def __init__(self, value: bool = True):
        super().__init__(value=value)


class RequestHeader:
    _annotation_type = "param"

    def __init__(
        self,
        name: Optional[str] = None,
        required: bool = True,
        default: Any = None,
        value: Optional[str] = None,
    ):
        self.name = value if value is not None else name
        self.required = required
        self.default = default


class CookieValue:
    _annotation_type = "param"

    def __init__(
        self,
        name: Optional[str] = None,
        required: bool = True,
        default: Any = None,
        value: Optional[str] = None,
    ):
        self.name = value if value is not None else name
        self.required = required
        self.default = default


class ResponseStatus(SpringAnnotation):
    _annotation_type = "response"

    def __init__(self, code: int, reason: str = ""):
        super().__init__(code=code, reason=reason)


class Transactional(SpringAnnotation):
    _annotation_type = "aop"

    def __init__(
        self,
        propagation: str = "REQUIRED",
        rollback_for: Optional[List[Type[Exception]]] = None,
        no_rollback_for: Optional[List[Type[Exception]]] = None,
    ):
        super().__init__(
            propagation=propagation,
            rollback_for=rollback_for or [],
            no_rollback_for=no_rollback_for or [],
        )


class Cacheable(SpringAnnotation):
    _annotation_type = "aop"

    def __init__(
        self,
        value: str,
        key: Optional[str] = None,
        condition: Optional[str] = None,
    ):
        super().__init__(value=value, key=key, condition=condition)


class Retryable(SpringAnnotation):
    _annotation_type = "aop"

    def __init__(
        self,
        value: Optional[Tuple[Type[Exception], ...]] = None,
        max_retries: int = 3,
        backoff: Optional[Union['Backoff', int, float]] = None,
        exclude: Optional[Tuple[Type[Exception], ...]] = None,
        recover: str = "",
        max_attempts: Optional[int] = None,
    ):
        from springbootai.retry.retry_annotations import Backoff as RetryBackoff

        if max_attempts is not None:
            if max_retries != 3 and max_retries != max_attempts:
                raise ValueError("max_retries 与 max_attempts 不能设置为不同值")
            max_retries = max_attempts
        if max_retries <= 0:
            raise ValueError("max_retries 必须大于0")
        if isinstance(backoff, (int, float)):
            if backoff < 0:
                raise ValueError("backoff 延迟不能小于0")
            backoff = RetryBackoff(
                delay=int(backoff),
                max_delay=int(backoff),
                multiplier=1.0,
                random_factor=0.0,
            )

        super().__init__(
            value=value or (Exception,),
            max_retries=max_retries,
            backoff=backoff or RetryBackoff(),
            exclude=exclude or (),
            recover=recover,
        )


class Recover(SpringAnnotation):
    """Mark a method as a fallback for an exhausted ``@Retryable`` call."""

    _annotation_type = "recover"

    def __new__(cls, *args, **kwargs):
        # ``@Recover(SomeError)`` uses an exception class as configuration,
        # not as the decorator target understood by SpringAnnotation.__new__.
        if args and isinstance(args[0], type) and issubclass(args[0], Exception):
            return object.__new__(cls)
        return super().__new__(cls, *args, **kwargs)

    def __init__(
        self,
        value: Optional[Union[Type[Exception], Tuple[Type[Exception], ...]]] = None,
    ):
        if value is None:
            exception_types = None
        elif isinstance(value, type) and issubclass(value, Exception):
            exception_types = (value,)
        elif isinstance(value, tuple) and value and all(
            isinstance(item, type) and issubclass(item, Exception) for item in value
        ):
            exception_types = value
        else:
            raise TypeError("Recover value must be an exception type or non-empty tuple")
        super().__init__(value=exception_types)


class Async(SpringAnnotation):
    _annotation_type = "aop"

    def __init__(self):
        super().__init__()


class Scheduled(SpringAnnotation):
    _annotation_type = "scheduling"

    def __init__(
        self,
        fixed_rate: Optional[int] = None,
        fixed_delay: Optional[int] = None,
        cron: Optional[str] = None,
        initial_delay: int = 0,
    ):
        configured = [fixed_rate is not None, fixed_delay is not None, cron is not None]
        if sum(configured) != 1:
            raise ValueError("Scheduled 必须且只能设置 fixed_rate、fixed_delay 或 cron 之一")
        if fixed_rate is not None and fixed_rate <= 0:
            raise ValueError("fixed_rate 必须大于0")
        if fixed_delay is not None and fixed_delay <= 0:
            raise ValueError("fixed_delay 必须大于0")
        if initial_delay < 0:
            raise ValueError("initial_delay 不能小于0")
        super().__init__(
            fixed_rate=fixed_rate,
            fixed_delay=fixed_delay,
            cron=cron,
            initial_delay=initial_delay,
        )


class AsyncResult(SpringAnnotation):
    _annotation_type = "async"

    def __init__(self, value: Any = None):
        super().__init__(value=value)


# ==================== 进阶骚操作注解 ====================

class RateLimit(SpringAnnotation):
    """接口限流注解"""
    _annotation_type = "aop"

    def __init__(
        self,
        max_requests: int = 100,
        time_window: int = 60,
        key: str = None,
    ):
        super().__init__(
            max_requests=max_requests,
            time_window=time_window,
            key=key,
        )


class CircuitBreaker(SpringAnnotation):
    """熔断器注解"""
    _annotation_type = "aop"

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        fallback_method: str = None,
    ):
        super().__init__(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            fallback_method=fallback_method,
        )


class Idempotent(SpringAnnotation):
    """幂等性注解"""
    _annotation_type = "aop"

    def __init__(
        self,
        key: str = None,
        expire: int = 300,
        prefix: str = "idempotent",
    ):
        super().__init__(
            key=key,
            expire=expire,
            prefix=prefix,
        )


class AuditLog(SpringAnnotation):
    """审计日志注解"""
    _annotation_type = "aop"

    def __init__(
        self,
        action: str = "",
        target: str = "",
        detail: str = "",
        level: str = "INFO",
    ):
        super().__init__(
            action=action,
            target=target,
            detail=detail,
            level=level,
        )


class FeatureToggle(SpringAnnotation):
    """功能开关注解"""
    _annotation_type = "aop"

    def __init__(
        self,
        name: str,
        default: bool = False,
    ):
        super().__init__(
            name=name,
            default=default,
        )


class Lock(SpringAnnotation):
    """分布式锁注解"""
    _annotation_type = "aop"

    def __init__(
        self,
        key: str = None,
        expire: int = 10,
        wait_timeout: int = 5,
        prefix: str = "lock",
    ):
        super().__init__(
            key=key,
            expire=expire,
            wait_timeout=wait_timeout,
            prefix=prefix,
        )


class Metrics(SpringAnnotation):
    """指标监控注解"""
    _annotation_type = "aop"

    def __init__(
        self,
        name: str = None,
        tags: List[str] = None,
    ):
        super().__init__(
            name=name,
            tags=tags or [],
        )


class Synchronized(SpringAnnotation):
    """方法同步注解"""
    _annotation_type = "aop"

    def __init__(
        self,
        lock_name: str = None,
    ):
        super().__init__(
            lock_name=lock_name,
        )


class Validate(SpringAnnotation):
    """参数校验注解"""
    _annotation_type = "param"

    def __init__(
        self,
        field: str = None,
        min_length: int = None,
        max_length: int = None,
        min: float = None,
        max: float = None,
        regex: str = None,
        message: str = None,
    ):
        super().__init__(
            field=field,
            min_length=min_length,
            max_length=max_length,
            min=min,
            max=max,
            regex=regex,
            message=message,
        )


class Trace(SpringAnnotation):
    """分布式追踪注解"""
    _annotation_type = "aop"

    def __init__(
        self,
        trace_id_key: str = "X-Trace-ID",
        span_name: str = None,
    ):
        super().__init__(
            trace_id_key=trace_id_key,
            span_name=span_name,
        )


# ==================== 安全注解 ====================

class PreAuthorize(SpringAnnotation):
    """
    方法级权限控制注解
    支持表达式：
    - hasRole('ROLE_ADMIN')
    - hasAnyRole('ROLE_ADMIN', 'ROLE_USER')
    - hasPermission('user:read')
    - hasAnyPermission('user:read', 'user:write')
    
    使用示例：
    @PreAuthorize("hasRole('ROLE_ADMIN')")
    def delete_user(self, user_id: int):
        pass
    """
    _annotation_type = "security"

    def __init__(self, value: str):
        super().__init__(value=value)


class PostAuthorize(SpringAnnotation):
    """Authorize a method after evaluating its return value."""

    _annotation_type = "security"

    def __init__(self, value: str):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("PostAuthorize value must be a non-empty expression")
        super().__init__(value=value.strip())


class Secured(SpringAnnotation):
    """
    角色权限控制注解
    检查当前用户是否拥有指定角色中的任一角色
    
    使用示例：
    @Secured(["ROLE_ADMIN", "ROLE_USER"])
    def update_user(self, user_id: int):
        pass
    """
    _annotation_type = "security"

    def __init__(self, value: List[str]):
        super().__init__(value=value)


class Authenticate(SpringAnnotation):
    """
    认证注解
    从请求头中获取 JWT Token 并验证，设置安全上下文
    
    使用示例：
    @Authenticate
    def get_user_profile(self):
        pass
    """
    _annotation_type = "security"

    def __init__(self):
        super().__init__()
