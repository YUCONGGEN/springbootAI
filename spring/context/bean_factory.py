from typing import Type, Optional, Any, Dict, Callable, List, get_args, get_origin, Union
from spring.context.bean_definition import BeanDefinition
from spring.annotations.core import Autowired, Qualifier, Slf4j, PostConstruct, PreDestroy, Primary, Transactional, Cacheable, Retryable, Async, Value
from spring.aop.proxy_factory import ProxyFactory
import inspect
import time
import asyncio
import functools
import threading
import hashlib
import pickle
import concurrent.futures
import types


# 全局线程池，用于@Async注解的异步执行
_ASYNC_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=8,
    thread_name_prefix="SpringAsync-"
)


class BeanFactory:
    def __init__(self, config_loader=None):
        self._bean_definitions: Dict[str, BeanDefinition] = {}
        self._bean_instances: Dict[str, Any] = {}
        self._type_to_name: Dict[Type, str] = {}
        # 使用线程本地存储，确保每个线程有独立的状态
        self._thread_local = threading.local()
        self._proxy_factory = ProxyFactory()
        # 缓存支持大小限制和TTL
        self._cache: Dict[str, Any] = {}
        self._cache_metadata: Dict[str, dict] = {}  # 存储缓存项的元数据（创建时间、过期时间）
        self._cache_max_size = 1000  # 默认最大缓存数
        self._cache_default_ttl = 300  # 默认TTL（秒）
        self._lock = threading.RLock()
        self._config_loader = config_loader
    
    def _get_initializing(self) -> set:
        """获取当前线程的 initializing 集合"""
        if not hasattr(self._thread_local, 'initializing'):
            self._thread_local.initializing = set()
        return self._thread_local.initializing
    
    def _get_transaction_stack(self) -> List[Dict[str, Any]]:
        """获取当前线程的 transaction_stack"""
        if not hasattr(self._thread_local, 'transaction_stack'):
            self._thread_local.transaction_stack = []
        return self._thread_local.transaction_stack
    
    def set_config_loader(self, config_loader):
        self._config_loader = config_loader

    def register_bean_definition(self, bean_name: str, definition: BeanDefinition) -> None:
        self._bean_definitions[bean_name] = definition
        if definition.bean_class not in self._type_to_name:
            self._type_to_name[definition.bean_class] = bean_name
    
    def register_instance(self, bean_name: str, instance: Any) -> None:
        """
        直接注册一个已实例化的Bean
        
        Args:
            bean_name: Bean名称
            instance: Bean实例
        """
        self._bean_instances[bean_name] = instance
        bean_class = instance.__class__
        if bean_class not in self._type_to_name:
            self._type_to_name[bean_class] = bean_name

    def get_bean_definition(self, bean_name: str) -> Optional[BeanDefinition]:
        return self._bean_definitions.get(bean_name)

    def get_bean(self, bean_name: str) -> Any:
        definition = self.get_bean_definition(bean_name)
        if not definition:
            raise ValueError(f"No bean named '{bean_name}' found")

        if definition.is_singleton:
            if bean_name not in self._bean_instances:
                with self._lock:
                    if bean_name not in self._bean_instances:
                        self._bean_instances[bean_name] = self._create_bean(definition)
            return self._bean_instances[bean_name]
        else:
            return self._create_bean(definition)

    def get_bean_by_type(self, bean_type: Type) -> Any:
        if not isinstance(bean_type, type):
            # ``Optional[T]`` and ``Annotated[T, ...]`` are typing objects,
            # not valid arguments to issubclass().
            bean_type, _, _ = self._unwrap_dependency_annotation(bean_type)
        if not isinstance(bean_type, type):
            raise ValueError(f"Bean 类型不可解析: {bean_type!r}")
        if bean_type in self._type_to_name:
            return self.get_bean(self._type_to_name[bean_type])

        matching_definitions = []
        for name, definition in self._bean_definitions.items():
            if isinstance(definition.bean_class, type) and issubclass(definition.bean_class, bean_type):
                matching_definitions.append((name, definition))

        if not matching_definitions:
            raise ValueError(f"No bean of type '{bean_type.__name__}' found")

        if len(matching_definitions) == 1:
            return self.get_bean(matching_definitions[0][0])

        primary_definitions = [md for md in matching_definitions 
                              if Primary._annotation_type in md[1].annotations]
        
        if primary_definitions:
            return self.get_bean(primary_definitions[0][0])

        raise ValueError(f"Multiple beans of type '{bean_type.__name__}' found, use @Qualifier to specify")

    def _create_bean(self, definition: BeanDefinition) -> Any:
        initializing = self._get_initializing()
        if definition.bean_name in initializing:
            raise RuntimeError(f"Circular dependency detected for bean: {definition.bean_name}")

        initializing.add(definition.bean_name)

        try:
            if definition.factory_method:
                factory_instance = None
                if definition.factory_class:
                    factory_instance = self.get_bean_by_type(definition.factory_class)
                # 如果有factory_class，传递factory_instance；否则直接调用
                if definition.factory_class:
                    instance = definition.factory_method(factory_instance)
                else:
                    instance = definition.factory_method()
            else:
                instance = self._instantiate_bean(definition)

            self._apply_aop_proxy(instance, definition)
            self._populate_bean(definition, instance)
            self._populate_config_values(definition, instance)
            self._process_slf4j(instance, definition)
            self._initialize_bean(definition, instance)

            return instance
        finally:
            initializing.discard(definition.bean_name)

    def _populate_config_values(self, definition: BeanDefinition, instance: Any) -> None:
        if self._config_loader is None:
            return

        for name, value in vars(instance.__class__).items():
            if isinstance(value, Value):
                setattr(instance, name, self._resolve_value(value))

            # Keep NacosValue optional: the framework can bind a local
            # configuration snapshot even when the Nacos SDK is not installed.
            try:
                from spring.annotations.cloud import NacosValue
            except ImportError:
                NacosValue = ()
            if NacosValue and isinstance(value, NacosValue):
                setattr(instance, name, self._resolve_value(value))

        property_annotations = definition.annotations.get('properties', [])
        if property_annotations:
            config = self._config_loader.get_prefix_config(
                property_annotations[0].prefix
            )
            for key, value in config.items():
                attribute = key.replace('-', '_')
                if hasattr(instance, attribute):
                    setattr(instance, attribute, value)

    def _resolve_value(self, annotation: Value) -> Any:
        return self._config_loader.resolve_value_expression(
            annotation.value,
            getattr(annotation, 'default', None),
        )

    def _instantiate_bean(self, definition: BeanDefinition) -> Any:
        constructor = self._find_constructor_with_autowire(definition.bean_class)
        if constructor:
            args = self._resolve_constructor_args(constructor, definition)
            return definition.bean_class(*args)
        return definition.bean_class()

    def _find_constructor_with_autowire(self, bean_class: Type) -> Optional[Callable]:
        for name, method in inspect.getmembers(bean_class):
            if name == "__init__":
                annotations = getattr(method, '__spring_annotations__', [])
                for annotation in annotations:
                    if isinstance(annotation, Autowired):
                        return method
        return None

    def _resolve_constructor_args(self, constructor: Callable, definition: BeanDefinition) -> list:
        sig = inspect.signature(constructor)
        args = []
        autowired = next(
            (
                annotation for annotation in getattr(constructor, '__spring_annotations__', [])
                if isinstance(annotation, Autowired)
            ),
            Autowired(),
        )
        for param_name, param in sig.parameters.items():
            if param_name == 'self':
                continue
            
            # 检查参数默认值是否是@Value注解
            if isinstance(param.default, Value):
                args.append(self._resolve_value(param.default))
                continue

            try:
                from spring.annotations.cloud import NacosValue
            except ImportError:
                NacosValue = ()
            if NacosValue and isinstance(param.default, NacosValue):
                args.append(self._resolve_value(param.default))
                continue

            param_type, inline_qualifier, optional_type = self._unwrap_dependency_annotation(param.annotation)
            if param_type is inspect.Parameter.empty:
                if param.default is not inspect.Parameter.empty:
                    args.append(param.default)
                    continue
                # 尝试通过参数名查找 Bean
                try:
                    args.append(self.get_bean(param_name))
                    continue
                except (KeyError, ValueError):
                    pass
                if not autowired.required:
                    args.append(None)
                    continue
                raise ValueError(f"Cannot resolve parameter '{param_name}' without type annotation")

            qualifier = inline_qualifier or definition.qualifiers.get(param_name)
            if qualifier:
                try:
                    args.append(self.get_bean(qualifier))
                except ValueError:
                    if not autowired.required or optional_type:
                        args.append(None)
                    else:
                        raise ValueError(f"Cannot resolve parameter '{param_name}'")
            else:
                try:
                    args.append(self.get_bean_by_type(param_type))
                except ValueError:
                    # 如果通过类型找不到，尝试通过参数名查找
                    try:
                        args.append(self.get_bean(param_name))
                    except (KeyError, ValueError):
                        if not autowired.required or optional_type:
                            args.append(None)
                            continue
                        raise ValueError(f"Cannot resolve parameter '{param_name}'")
        return args

    @staticmethod
    def _unwrap_dependency_annotation(annotation: Any):
        """Extract ``Annotated[T, Qualifier(...)]`` and ``Optional[T]`` metadata."""
        qualifier = None
        optional_type = False
        if get_origin(annotation) is not None and str(get_origin(annotation)).endswith('Annotated'):
            args = get_args(annotation)
            annotation = args[0]
            for metadata in args[1:]:
                if isinstance(metadata, Qualifier):
                    qualifier = metadata.value
        origin = get_origin(annotation)
        if origin is Union or str(origin) == 'types.UnionType':
            candidates = [candidate for candidate in get_args(annotation) if candidate is not type(None)]
            optional_type = len(candidates) != len(get_args(annotation))
            if len(candidates) == 1:
                annotation = candidates[0]
        return annotation, qualifier, optional_type

    def _populate_bean(self, definition: BeanDefinition, instance: Any) -> None:
        for field_name, field_type in definition.dependencies.items():
            qualifier = definition.qualifiers.get(field_name)
            if qualifier:
                dependency = self.get_bean(qualifier)
            else:
                try:
                    dependency = self.get_bean_by_type(field_type)
                except ValueError:
                    # 如果通过类型找不到，尝试通过字段名查找
                    try:
                        dependency = self.get_bean(field_name)
                    except (KeyError, ValueError):
                        if not definition.dependency_required.get(field_name, True):
                            setattr(instance, field_name, None)
                            continue
                        raise ValueError(f"Cannot resolve field '{field_name}'")
            setattr(instance, field_name, dependency)

        for name, field in inspect.getmembers(instance.__class__):
            if not name.startswith('_') and hasattr(field, '__spring_annotations__'):
                annotations = field.__spring_annotations__
                for annotation in annotations:
                    if isinstance(annotation, Autowired):
                        field_type = inspect.get_annotations(instance.__class__).get(name)
                        if field_type:
                            qualifier_annotation = None
                            for ann in annotations:
                                if isinstance(ann, Qualifier):
                                    qualifier_annotation = ann
                                    break
                            if qualifier_annotation:
                                dependency = self.get_bean(qualifier_annotation.value)
                            else:
                                dependency = self.get_bean_by_type(field_type)
                            setattr(instance, name, dependency)

    def _process_slf4j(self, instance: Any, definition: BeanDefinition) -> None:
        if Slf4j._annotation_type in definition.annotations:
            from spring.utils.logger import get_logger
            annotations = definition.annotations[Slf4j._annotation_type]
            if annotations:
                annotation = annotations[0]
                logger_name = annotation.logger_name or instance.__class__.__name__
                logger = get_logger(logger_name)
                setattr(instance, 'logger', logger)

    def _initialize_bean(self, definition: BeanDefinition, instance: Any) -> None:
        if definition.init_method and hasattr(instance, definition.init_method):
            init_method = getattr(instance, definition.init_method)
            if callable(init_method):
                init_method()

        if hasattr(instance, 'init') and callable(instance.init):
            instance.init()

        self._register_rabbit_listeners(instance)
        self._invoke_post_construct(instance)

        definition.mark_initialized()

    def _register_rabbit_listeners(self, instance: Any) -> None:
        """Register annotated bound methods after all AOP wrappers are installed."""
        if getattr(instance, '__rabbit_listeners_registered__', False):
            return
        if self._config_loader is not None:
            if not self._config_loader.get_value('rabbitmq.enabled', False):
                return
            try:
                from spring.messaging.rabbitmq import rabbitmq_client
            except ImportError:
                return
            connection = rabbitmq_client._connection
            if connection is None or getattr(connection, 'is_closed', False):
                return
        try:
            from spring.annotations.messaging import RabbitListener, register_rabbit_listener
        except ImportError:
            return

        registered = False
        for name, method in inspect.getmembers(instance.__class__):
            if name.startswith('_') or not inspect.isfunction(method):
                continue
            for annotation in getattr(method, '__spring_annotations__', []):
                if isinstance(annotation, RabbitListener):
                    register_rabbit_listener(annotation, getattr(instance, name))
                    registered = True
        if registered:
            setattr(instance, '__rabbit_listeners_registered__', True)

    def _invoke_post_construct(self, instance: Any) -> None:
        for name, method in inspect.getmembers(instance.__class__):
            if not name.startswith('_') and inspect.isfunction(method):
                annotations = getattr(method, '__spring_annotations__', [])
                for annotation in annotations:
                    if isinstance(annotation, PostConstruct):
                        method(instance)

    def destroy_bean(self, bean_name: str) -> None:
        definition = self.get_bean_definition(bean_name)
        if not definition or definition._destroyed:
            return

        if bean_name in self._bean_instances:
            instance = self._bean_instances[bean_name]

            self._invoke_pre_destroy(instance)

            if definition.destroy_method and hasattr(instance, definition.destroy_method):
                destroy_method = getattr(instance, definition.destroy_method)
                if callable(destroy_method):
                    destroy_method()

            if hasattr(instance, 'destroy') and callable(instance.destroy):
                instance.destroy()

            definition.mark_destroyed()
            del self._bean_instances[bean_name]

    def _invoke_pre_destroy(self, instance: Any) -> None:
        for name, method in inspect.getmembers(instance.__class__):
            if not name.startswith('_') and inspect.isfunction(method):
                annotations = getattr(method, '__spring_annotations__', [])
                for annotation in annotations:
                    if isinstance(annotation, PreDestroy):
                        method(instance)

    def destroy_all(self) -> None:
        for bean_name in list(self._bean_instances.keys()):
            self.destroy_bean(bean_name)

    def contains_bean(self, bean_name: str) -> bool:
        return bean_name in self._bean_definitions

    def get_bean_names(self) -> list:
        return list(self._bean_definitions.keys())

    def get_bean_count(self) -> int:
        return len(self._bean_definitions)

    def _apply_aop_proxy(self, instance: Any, definition: BeanDefinition) -> None:
        bean_class = instance.__class__
        from spring.utils.logger import SpringLogger
        logger = SpringLogger()
        
        logger.info(f"Applying AOP proxy to bean: {definition.bean_name}, instance: {id(instance)}")
        
        for name, method in inspect.getmembers(bean_class):
            if not name.startswith('_') and inspect.isfunction(method):
                annotations = getattr(method, '__spring_annotations__', [])
                
                if annotations:
                    logger.info(f"  Found method {name} with annotations: {[type(a).__name__ for a in annotations]}")
                
                # 处理新注解（使用 comprehensive_aop）
                try:
                    from spring.aop.comprehensive_aop import apply_annotations
                    wrapped_method = apply_annotations(instance, method)
                    if wrapped_method is not method:
                        logger.info(f"  Method {name} wrapped successfully")
                    method = wrapped_method
                except ImportError as e:
                    logger.error(f"  Failed to import comprehensive_aop: {e}")
                
                # 处理 Cloud 注解（使用 cloud_aop）
                try:
                    from spring.aop.cloud_aop import apply_cloud_annotations
                    wrapped_method = apply_cloud_annotations(instance, method)
                    if wrapped_method is not method:
                        logger.info(f"  Method {name} wrapped with Cloud AOP successfully")
                    method = wrapped_method
                except ImportError as e:
                    logger.error(f"  Failed to import cloud_aop: {e}")
                
                # 固定包装顺序：事务在计算内部，缓存命中可跳过事务，异步最外层调度。
                for annotation in annotations:
                    if isinstance(annotation, Transactional):
                        method = self._wrap_transactional(instance, method, annotation)
                for annotation in annotations:
                    if isinstance(annotation, Cacheable):
                        method = self._wrap_cacheable(instance, method, annotation)
                for annotation in annotations:
                    if isinstance(annotation, Async):
                        method = self._wrap_async(instance, method, annotation)

                # Security stays outermost: it consumes the internal request
                # argument and authenticates before transaction/business logic.
                try:
                    from spring.security.security_aop import apply_security_annotations
                    method = apply_security_annotations(instance, method)
                except ImportError as e:
                    logger.error(f"  Failed to import security_aop: {e}")
                
                # 创建绑定方法并设置到实例
                bound_method = types.MethodType(method, instance)
                setattr(instance, name, bound_method)
                logger.info(f"  Method {name} bound to instance: {id(instance)}")

    def _wrap_transactional(self, instance: Any, method: Callable, annotation: Transactional) -> Callable:
        def get_session_factory():
            try:
                return self.get_bean('sqlSessionFactory')
            except Exception as exc:
                raise RuntimeError(
                    "@Transactional需要已启用的MyBatis SqlSessionFactory"
                ) from exc

        def should_rollback(exc: Exception) -> bool:
            if annotation.no_rollback_for and any(
                isinstance(exc, exc_type) for exc_type in annotation.no_rollback_for
            ):
                return False
            if annotation.rollback_for and not any(
                isinstance(exc, exc_type) for exc_type in annotation.rollback_for
            ):
                return False
            return True

        if asyncio.iscoroutinefunction(method):
            @functools.wraps(method)
            async def async_wrapper(*args, **kwargs):
                from spring.orm.mybatis_integration import mybatis_transaction

                deferred_exception = None
                deferred_traceback = None
                with mybatis_transaction(
                    get_session_factory(), str(annotation.propagation).upper()
                ):
                    try:
                        return await method(*args, **kwargs)
                    except Exception as exc:
                        if should_rollback(exc):
                            raise
                        deferred_exception = exc
                        deferred_traceback = exc.__traceback__

                if deferred_exception is not None:
                    raise deferred_exception.with_traceback(deferred_traceback)

            return async_wrapper

        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            from spring.orm.mybatis_integration import mybatis_transaction

            deferred_exception = None
            deferred_traceback = None
            with mybatis_transaction(
                get_session_factory(), str(annotation.propagation).upper()
            ):
                try:
                    return method(*args, **kwargs)
                except Exception as exc:
                    if should_rollback(exc):
                        raise
                    deferred_exception = exc
                    deferred_traceback = exc.__traceback__

            if deferred_exception is not None:
                raise deferred_exception.with_traceback(deferred_traceback)

        return wrapper

    def _wrap_cacheable(self, instance: Any, method: Callable, annotation: Cacheable) -> Callable:
        signature = inspect.signature(method)

        def serialize_arg(arg: Any) -> str:
            if isinstance(arg, (int, float, str, bool, type(None))):
                return str(arg)
            if isinstance(arg, (list, tuple)):
                return '[' + ','.join(serialize_arg(item) for item in arg) + ']'
            if isinstance(arg, dict):
                items = sorted(
                    ((serialize_arg(key), serialize_arg(value)) for key, value in arg.items()),
                    key=lambda item: item[0],
                )
                return '{' + ','.join(f"{key}:{value}" for key, value in items) + '}'
            return f"obj_{id(arg)}"

        def resolve_call(args, kwargs):
            bound = signature.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            cache_arguments = dict(bound.arguments)
            cache_arguments.pop('self', None)

            condition = annotation.condition
            if condition:
                if callable(condition):
                    enabled = bool(condition(**cache_arguments))
                else:
                    condition_name = str(condition).strip()
                    negate = condition_name.startswith('!')
                    if negate:
                        condition_name = condition_name[1:]
                    if condition_name not in cache_arguments:
                        raise ValueError(
                            f"@Cacheable condition只支持参数名，未找到: {condition_name}"
                        )
                    enabled = bool(cache_arguments[condition_name])
                    if negate:
                        enabled = not enabled
                if not enabled:
                    return False, None

            if annotation.key:
                if '{' in annotation.key:
                    try:
                        resolved_key = annotation.key.format(**cache_arguments)
                    except KeyError as exc:
                        raise ValueError(
                            f"@Cacheable key引用了不存在的参数: {exc.args[0]}"
                        ) from exc
                elif annotation.key in cache_arguments:
                    resolved_key = serialize_arg(cache_arguments[annotation.key])
                else:
                    resolved_key = annotation.key
                key_data = f"{annotation.value}:{method.__qualname__}:{resolved_key}"
            else:
                arguments = ','.join(
                    f"{name}:{serialize_arg(value)}"
                    for name, value in sorted(cache_arguments.items())
                )
                key_data = f"{annotation.value}:{method.__qualname__}:{arguments}"
            return True, hashlib.md5(key_data.encode('utf-8')).hexdigest()

        def get_cached(cache_key):
            with self._lock:
                current_time = time.time()
                metadata = self._cache_metadata.get(cache_key)
                if metadata is None or cache_key not in self._cache:
                    return False, None
                if current_time > metadata.get('expire_time', current_time):
                    self._cache.pop(cache_key, None)
                    self._cache_metadata.pop(cache_key, None)
                    return False, None
                return True, self._cache[cache_key]

        def store(cache_key, result):
            current_time = time.time()
            with self._lock:
                if len(self._cache) >= self._cache_max_size:
                    oldest_key = min(
                        self._cache_metadata,
                        key=lambda key: self._cache_metadata[key].get('create_time', 0),
                    )
                    self._cache.pop(oldest_key, None)
                    self._cache_metadata.pop(oldest_key, None)
                self._cache[cache_key] = result
                self._cache_metadata[cache_key] = {
                    'create_time': current_time,
                    'expire_time': current_time + self._cache_default_ttl
                }

        if asyncio.iscoroutinefunction(method):
            @functools.wraps(method)
            async def async_wrapper(*args, **kwargs):
                enabled, cache_key = resolve_call(args, kwargs)
                if not enabled:
                    return await method(*args, **kwargs)
                with self._lock:
                    exists = cache_key in self._cache_metadata
                if exists:
                    hit, cached = get_cached(cache_key)
                    if hit:
                        return cached
                result = await method(*args, **kwargs)
                store(cache_key, result)
                return result

            return async_wrapper

        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            enabled, cache_key = resolve_call(args, kwargs)
            if not enabled:
                return method(*args, **kwargs)
            with self._lock:
                exists = cache_key in self._cache_metadata
            if exists:
                hit, cached = get_cached(cache_key)
                if hit:
                    return cached
            result = method(*args, **kwargs)
            store(cache_key, result)
            return result

        return wrapper

    def _wrap_retryable(self, instance: Any, method: Callable, annotation: Retryable) -> Callable:
        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(annotation.max_attempts):
                try:
                    return method(instance, *args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if annotation.value and not any(isinstance(e, exc_type) for exc_type in annotation.value):
                        raise
                    
                    if attempt < annotation.max_attempts - 1:
                        time.sleep(annotation.backoff / 1000)
            
            raise last_exception

        return wrapper

    def _wrap_async(self, instance: Any, method: Callable, annotation: Async) -> Callable:
        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            if asyncio.iscoroutinefunction(method):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    return _ASYNC_EXECUTOR.submit(
                        asyncio.run, method(*args, **kwargs)
                    )
                return loop.create_task(method(*args, **kwargs))

            future = _ASYNC_EXECUTOR.submit(method, *args, **kwargs)
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return future
            return asyncio.wrap_future(future)

        return wrapper

    def get_transaction_stack(self) -> List[Dict[str, Any]]:
        return self._get_transaction_stack()

    def get_cache(self) -> Dict[str, Any]:
        return self._cache

    def clear_cache(self) -> None:
        self._cache.clear()
        self._cache_metadata.clear()

    def refresh_configuration(self) -> List[str]:
        """Rebind refresh-scoped and auto-refreshed Nacos values in live Beans.

        Python keeps object identity stable during refresh so collaborators that
        already hold a Bean reference see the new values immediately.  This is
        intentionally different from Spring Cloud's target-swapping proxy and
        avoids exposing stale Python references.
        """
        refreshed = []
        try:
            from spring.annotations.cloud import NacosValue
        except ImportError:
            NacosValue = ()

        for bean_name, instance in list(self._bean_instances.items()):
            definition = self._bean_definitions.get(bean_name)
            if definition is None:
                continue
            is_refresh_scope = bool(definition.annotations.get('refresh_scope'))
            dynamic_values = [
                value for value in vars(instance.__class__).values()
                if NacosValue and isinstance(value, NacosValue) and value.auto_refreshed
            ]
            if not is_refresh_scope and not dynamic_values:
                continue
            self._populate_config_values(definition, instance)
            refreshed.append(bean_name)
        return refreshed
    
    def set_cache_config(self, max_size: int = 1000, default_ttl: int = 300) -> None:
        """设置缓存配置"""
        self._cache_max_size = max_size
        self._cache_default_ttl = default_ttl
