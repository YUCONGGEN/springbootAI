from typing import Type, Optional, Any, Dict, Callable, List, Tuple, get_args, get_origin, Union
from springbootai.context.bean_definition import BeanDefinition
from springbootai.context.lifecycle import (
    BeanPostProcessor, BeanFactoryPostProcessor, InitializingBean, DisposableBean,
    ApplicationContextAware, BeanFactoryAware, EnvironmentAware, SmartLifecycle,
    LifecycleProcessor,
)
from springbootai.annotations.core import Autowired, Qualifier, Slf4j, PostConstruct, PreDestroy, Primary, Transactional, Cacheable, Retryable, Async, Value
from springbootai.annotations.cache import CachePut, CacheEvict, CacheConfig, Caching
from springbootai.aop.proxy_factory import ProxyFactory
import inspect
import time
import asyncio
import functools
import threading
import hashlib
import copy
import concurrent.futures
import types
import logging


logger = logging.getLogger("Spring.Context.BeanFactory")


class BeanDependencyError(ValueError):
    """Raised when a Bean cannot be built because an injected dependency is unavailable.

    It remains a ``ValueError`` for backwards compatibility with callers that
    already handle the container's resolution errors, while giving lifecycle
    startup a precise signal for optional-dependency degradation.
    """


class MissingBeanDependencyError(BeanDependencyError):
    """A required Bean is absent because an optional integration is unavailable."""


def _cleanup_unregistered_instance(definition: BeanDefinition, instance: Any) -> None:
    """Release an instance whose creation failed before registration.

    ``BeanFactory.get_bean`` only stores a singleton after ``_create_bean``
    returns.  A factory method or post-construct hook can therefore create a
    resource and fail before the normal ``destroy_bean`` path can see it.
    Cleanup is deliberately best effort and never replaces the original error.
    """
    try:
        for name, method in inspect.getmembers(instance.__class__):
            if not name.startswith('_') and inspect.isfunction(method):
                annotations = getattr(method, '__spring_annotations__', [])
                for annotation in annotations:
                    if isinstance(annotation, PreDestroy):
                        try:
                            method(instance)
                        except Exception:
                            pass

        if definition.destroy_method and hasattr(instance, definition.destroy_method):
            destroy_method = getattr(instance, definition.destroy_method)
            if callable(destroy_method):
                try:
                    destroy_method()
                except Exception:
                    pass

        destroy = getattr(instance, 'destroy', None)
        if callable(destroy):
            try:
                destroy()
            except Exception:
                pass
    except Exception:
        # Introspection itself can fail for proxy objects; the original bean
        # creation exception remains the useful diagnostic in that case.
        pass


# 全局线程池，用于@Async注解的异步执行
_ASYNC_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=8,
    thread_name_prefix="SpringAsync-"
)


def _get_tx_sync_manager():
    """最佳努力获取事务同步管理器；``springbootai.tx`` 不可用时返回 ``None``。

    ``@Transactional`` 切面在事务边界触发 ``@TransactionalEventListener`` 回调；
    若 ``springbootai.tx`` 未安装则回退到原始事务行为，保持向后兼容。
    """
    try:
        from springbootai.tx.synchronization import TransactionSynchronizationManager
        return TransactionSynchronizationManager
    except ImportError:  # pragma: no cover - springbootai.tx 为内置模块，仅在异常拆分时缺失
        return None


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
        # One process-wide Future per cache key coordinates sync threads and
        # async event loops without binding locks to a particular loop.
        self._cache_inflight: Dict[str, concurrent.futures.Future] = {}
        self._config_loader = config_loader

        # ========== IoC增强：三级缓存解决循环依赖 ==========
        self._singleton_factories: Dict[str, Callable] = {}  # 三级缓存：单例工厂
        self._early_singleton_objects: Dict[str, Any] = {}   # 二级缓存：提前暴露的对象
        self._singletons_currently_in_creation: set = set()  # 正在创建的单例

        # ========== IoC增强：BeanPostProcessor注册 ==========
        self._bean_post_processors: List[BeanPostProcessor] = []
        self._bean_factory_post_processors: List[BeanFactoryPostProcessor] = []
        self._has_invoked_factory_post_processors = False

        # ========== IoC增强：生命周期管理器 ==========
        self._lifecycle_processor = LifecycleProcessor()

        # ========== IoC增强：ApplicationContext引用（供Aware注入） ==========
        self._application_context = None
    
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

    def set_application_context(self, application_context) -> None:
        """设置ApplicationContext引用，供Aware接口注入。"""
        self._application_context = application_context

    def add_bean_post_processor(self, processor: BeanPostProcessor) -> None:
        """注册BeanPostProcessor。"""
        if processor not in self._bean_post_processors:
            self._bean_post_processors.append(processor)
            # 按优先级排序：Ordered接口/Order属性
            self._bean_post_processors.sort(key=lambda p: getattr(p, 'get_order', lambda: 0)())

    def add_bean_factory_post_processor(self, processor: BeanFactoryPostProcessor) -> None:
        """注册BeanFactoryPostProcessor。"""
        if processor not in self._bean_factory_post_processors:
            self._bean_factory_post_processors.append(processor)

    def invoke_bean_factory_post_processors(self) -> None:
        """执行所有BeanFactoryPostProcessor（在Bean实例化前调用）。"""
        if self._has_invoked_factory_post_processors:
            return
        self._has_invoked_factory_post_processors = True
        for processor in self._bean_factory_post_processors:
            try:
                processor.post_process_bean_factory(self)
            except Exception:
                logger.exception("BeanFactoryPostProcessor %s failed", type(processor).__name__)

    def register_bean_definition(self, bean_name: str, definition: BeanDefinition) -> None:
        # A definition may have been marked destroyed during a previous
        # container teardown.  Registering it again is an explicit lifecycle
        # boundary, so make the definition usable for the new context.
        if getattr(definition, '_destroyed', False):
            definition._destroyed = False
            definition._initialized = False
        self._bean_definitions[bean_name] = definition
        mapped_name = self._type_to_name.get(definition.bean_class)
        mapped_definition = self._bean_definitions.get(mapped_name) if mapped_name else None
        if (
            mapped_name is None
            or mapped_name == bean_name
            or mapped_definition is None
            or getattr(mapped_definition, '_destroyed', False)
        ):
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
        mapped_name = self._type_to_name.get(bean_class)
        mapped_definition = self._bean_definitions.get(mapped_name) if mapped_name else None
        if (
            mapped_name is None
            or mapped_name == bean_name
            or mapped_definition is None
            or getattr(mapped_definition, '_destroyed', False)
        ):
            self._type_to_name[bean_class] = bean_name

    def get_bean_definition(self, bean_name: str) -> Optional[BeanDefinition]:
        return self._bean_definitions.get(bean_name)

    def get_bean(self, bean_name: str) -> Any:
        definition = self.get_bean_definition(bean_name)
        if not definition:
            raise MissingBeanDependencyError(f"No bean named '{bean_name}' found")
        if getattr(definition, '_destroyed', False):
            # Teardown must be terminal for a definition.  Without this guard
            # a lazy singleton could recreate a database/Redis connection
            # after ``ApplicationContext.destroy()`` had already run.
            raise RuntimeError(f"Bean '{bean_name}' has been destroyed")

        if definition.is_singleton:
            # 一级缓存：已完全初始化的单例
            if bean_name in self._bean_instances:
                return self._bean_instances[bean_name]
            # 二级缓存：提前暴露的早期对象（已实例化但未初始化完成）
            if bean_name in self._early_singleton_objects:
                return self._early_singleton_objects[bean_name]
            with self._lock:
                # Double-check after lock
                if bean_name in self._bean_instances:
                    return self._bean_instances[bean_name]
                if bean_name in self._early_singleton_objects:
                    return self._early_singleton_objects[bean_name]

                # 标记正在创建
                before_creation = bean_name not in self._singletons_currently_in_creation
                self._singletons_currently_in_creation.add(bean_name)
                try:
                    # 三级缓存：单例工厂（用于AOP代理提前暴露）
                    singleton_object = self._create_bean(definition)
                finally:
                    if before_creation:
                        self._singletons_currently_in_creation.discard(bean_name)
                        # 创建完成，清理二三级缓存
                        self._singleton_factories.pop(bean_name, None)
                        self._early_singleton_objects.pop(bean_name, None)

                # 只有"最外层"创建者才把完整实例写入一级缓存；重入调用
                # （循环依赖）拿到的是提前暴露的引用，不能污染一级缓存，
                # 否则会跳过该 Bean 后续的字段注入与初始化。
                if before_creation:
                    self._bean_instances[bean_name] = singleton_object
                return singleton_object
        else:
            return self._create_bean(definition)

    def get_bean_by_type(self, bean_type: Type) -> Any:
        if not isinstance(bean_type, type):
            # ``Optional[T]`` and ``Annotated[T, ...]`` are typing objects,
            # not valid arguments to issubclass().
            bean_type, _, _ = self._unwrap_dependency_annotation(bean_type)
        # ``typing.Any`` can pass an ``isinstance(..., type)`` check on some
        # Python versions but is still invalid as the second argument to
        # ``issubclass``.  Treat it as an unresolved dependency so optional
        # injection can follow its normal fallback path instead of crashing
        # context refresh with a TypeError.
        if bean_type is Any or not isinstance(bean_type, type):
            raise BeanDependencyError(f"Bean 类型不可解析: {bean_type!r}")
        if bean_type in self._type_to_name:
            return self.get_bean(self._type_to_name[bean_type])

        matching_definitions = []
        for name, definition in self._bean_definitions.items():
            if not isinstance(definition.bean_class, type):
                continue
            try:
                matches = issubclass(definition.bean_class, bean_type)
            except TypeError:
                # Some typing constructs (Protocols, unresolved forward refs)
                # reject ``issubclass`` even after the outer type check.
                matches = False
            if matches:
                matching_definitions.append((name, definition))

        if not matching_definitions:
            raise MissingBeanDependencyError(f"No bean of type '{bean_type.__name__}' found")

        if len(matching_definitions) == 1:
            return self.get_bean(matching_definitions[0][0])

        primary_definitions = [md for md in matching_definitions 
                              if Primary._annotation_type in md[1].annotations]
        
        if primary_definitions:
            return self.get_bean(primary_definitions[0][0])

        raise BeanDependencyError(f"Multiple beans of type '{bean_type.__name__}' found, use @Qualifier to specify")

    def _create_bean(self, definition: BeanDefinition) -> Any:
        initializing = self._get_initializing()
        if definition.bean_name in initializing:
            # 允许通过三级缓存解决Setter/Field循环依赖；构造器循环依赖仍报错
            if definition.bean_name in self._early_singleton_objects:
                return self._early_singleton_objects[definition.bean_name]
            if definition.bean_name in self._singleton_factories:
                early = self._singleton_factories[definition.bean_name]()
                self._early_singleton_objects[definition.bean_name] = early
                return early
            raise RuntimeError(f"Circular dependency detected for bean: {definition.bean_name}")

        initializing.add(definition.bean_name)
        instance = None

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

            # ========== IoC增强：实例化后立即放入三级缓存（提前暴露），解决循环依赖 ==========
            if definition.is_singleton:
                def _get_early_singleton_reference():
                    return self._apply_aop_proxy_early(instance, definition)
                self._singleton_factories[definition.bean_name] = _get_early_singleton_reference

            # ========== IoC增强：Aware接口回调 ==========
            self._invoke_aware_methods(instance)

            # ========== IoC增强：BeanPostProcessor postProcessBeforeInitialization ==========
            instance = self._apply_post_processors_before_init(instance, definition.bean_name)

            self._apply_aop_proxy(instance, definition)
            self._populate_bean(definition, instance)
            self._populate_config_values(definition, instance)
            self._process_slf4j(instance, definition)
            self._initialize_bean(definition, instance)

            # ========== IoC增强：BeanPostProcessor postProcessAfterInitialization ==========
            instance = self._apply_post_processors_after_init(instance, definition.bean_name)

            # ========== IoC增强：注册SmartLifecycle ==========
            if isinstance(instance, SmartLifecycle):
                self._lifecycle_processor.register(instance)

            return instance
        except Exception:
            if instance is not None:
                _cleanup_unregistered_instance(definition, instance)
            raise
        finally:
            initializing.discard(definition.bean_name)

    def _apply_aop_proxy_early(self, instance: Any, definition: BeanDefinition) -> Any:
        """三级缓存提前引用：创建AOP代理但不执行字段注入/初始化。"""
        # 对于提前暴露的引用，只做必要的代理包装（主要解决AOP+循环依赖）
        # 简化处理：先返回原始实例，完整AOP在populate后执行
        return instance

    def _invoke_aware_methods(self, instance: Any) -> None:
        """调用Aware接口回调，注入容器资源。"""
        try:
            if isinstance(instance, BeanFactoryAware):
                instance.set_bean_factory(self)
            if isinstance(instance, ApplicationContextAware) and self._application_context is not None:
                instance.set_application_context(self._application_context)
            if isinstance(instance, EnvironmentAware) and self._config_loader is not None:
                instance.set_environment(self._config_loader)
        except Exception:
            logger.exception("Aware callback failed for %s", type(instance).__name__)

    def _apply_post_processors_before_init(self, instance: Any, bean_name: str) -> Any:
        """执行所有BeanPostProcessor.postProcessBeforeInitialization。"""
        result = instance
        for processor in self._bean_post_processors:
            try:
                processed = processor.post_process_before_initialization(result, bean_name)
                if processed is not None:
                    result = processed
            except Exception:
                logger.exception("BeanPostProcessor BeforeInit failed for %s", bean_name)
        return result

    def _apply_post_processors_after_init(self, instance: Any, bean_name: str) -> Any:
        """执行所有BeanPostProcessor.postProcessAfterInitialization。"""
        result = instance
        for processor in self._bean_post_processors:
            try:
                processed = processor.post_process_after_initialization(result, bean_name)
                if processed is not None:
                    result = processed
            except Exception:
                logger.exception("BeanPostProcessor AfterInit failed for %s", bean_name)
        return result

    def _populate_config_values(self, definition: BeanDefinition, instance: Any) -> None:
        if self._config_loader is None:
            return

        for name, value in vars(instance.__class__).items():
            if isinstance(value, Value):
                setattr(instance, name, self._resolve_value(value))

            # Keep NacosValue optional: the framework can bind a local
            # configuration snapshot even when the Nacos SDK is not installed.
            try:
                from springbootai.annotations.cloud import NacosValue
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
                from springbootai.annotations.cloud import NacosValue
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
                except (KeyError, BeanDependencyError):
                    pass
                if not autowired.required:
                    args.append(None)
                    continue
                raise MissingBeanDependencyError(f"Cannot resolve parameter '{param_name}' without type annotation")

            qualifier = inline_qualifier or definition.qualifiers.get(param_name)
            if qualifier:
                try:
                    args.append(self.get_bean(qualifier))
                except BeanDependencyError:
                    if not autowired.required or optional_type:
                        args.append(None)
                    else:
                        raise MissingBeanDependencyError(f"Cannot resolve parameter '{param_name}'")
            else:
                try:
                    args.append(self.get_bean_by_type(param_type))
                except BeanDependencyError:
                    # 如果通过类型找不到，尝试通过参数名查找
                    try:
                        args.append(self.get_bean(param_name))
                    except (KeyError, BeanDependencyError):
                        if not autowired.required or optional_type:
                            args.append(None)
                            continue
                        raise MissingBeanDependencyError(f"Cannot resolve parameter '{param_name}'")
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
        # AI 注入标记（Embedding()/VectorStore()）采用懒解析，缺少可选
        # AI Bean 时保留原标记，不阻断普通 Bean 启动。
        try:
            from springbootai.ai.annotation_runtime import inject_ai_marker
            inject_ai_marker(self, instance)
        except Exception as exc:
            logger.debug("AI 字段注入跳过 error_type=%s", type(exc).__name__)
        for field_name, field_type in definition.dependencies.items():
            qualifier = definition.qualifiers.get(field_name)
            if qualifier:
                dependency = self.get_bean(qualifier)
            else:
                try:
                    dependency = self.get_bean_by_type(field_type)
                except BeanDependencyError:
                    # 如果通过类型找不到，尝试通过字段名查找
                    try:
                        dependency = self.get_bean(field_name)
                    except (KeyError, BeanDependencyError):
                        if not definition.dependency_required.get(field_name, True):
                            setattr(instance, field_name, None)
                            continue
                        raise MissingBeanDependencyError(f"Cannot resolve field '{field_name}'")
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
            from springbootai.utils.logger import get_logger
            annotations = definition.annotations[Slf4j._annotation_type]
            if annotations:
                annotation = annotations[0]
                logger_name = annotation.logger_name or instance.__class__.__name__
                logger = get_logger(logger_name)
                setattr(instance, 'logger', logger)

    def _initialize_bean(self, definition: BeanDefinition, instance: Any) -> None:
        # 执行顺序：@PostConstruct -> InitializingBean.afterPropertiesSet -> initMethod
        # 对齐Spring标准生命周期顺序

        # 1. @PostConstruct 注解方法
        self._invoke_post_construct(instance)

        # 2. InitializingBean.afterPropertiesSet()
        if isinstance(instance, InitializingBean):
            try:
                instance.after_properties_set()
            except Exception as exc:
                raise RuntimeError(
                    f"InitializingBean.afterPropertiesSet failed for {definition.bean_name}"
                ) from exc

        # 3. 自定义init-method
        if definition.init_method and hasattr(instance, definition.init_method):
            init_method = getattr(instance, definition.init_method)
            if callable(init_method):
                init_method()

        if hasattr(instance, 'init') and callable(instance.init):
            instance.init()

        self._register_rabbit_listeners(instance)

        definition.mark_initialized()

    def _register_rabbit_listeners(self, instance: Any) -> None:
        """Register annotated bound methods after all AOP wrappers are installed."""
        if getattr(instance, '__rabbit_listeners_registered__', False):
            return
        if self._config_loader is not None:
            if not self._config_loader.get_value('rabbitmq.enabled', False):
                return
            try:
                from springbootai.messaging.rabbitmq import rabbitmq_client
            except ImportError:
                return
            connection = rabbitmq_client._connection
            if connection is None or getattr(connection, 'is_closed', False):
                return
        try:
            from springbootai.annotations.messaging import RabbitListener, register_rabbit_listener
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

        first_error = None
        if bean_name in self._bean_instances:
            instance = self._bean_instances[bean_name]

            # 销毁顺序（对齐Spring）：
            # @PreDestroy -> DisposableBean.destroy() -> 自定义destroy-method
            callbacks = []
            callbacks.append(lambda: self._invoke_pre_destroy(instance))
            if isinstance(instance, DisposableBean):
                callbacks.append(instance.destroy)
            if isinstance(instance, SmartLifecycle) and instance.is_running():
                callbacks.append(instance.stop)
            if definition.destroy_method and hasattr(instance, definition.destroy_method):
                destroy_method = getattr(instance, definition.destroy_method)
                if callable(destroy_method):
                    callbacks.append(destroy_method)
            destroy = getattr(instance, 'destroy', None)
            # DisposableBean已经处理过destroy方法，避免重复调用
            if callable(destroy) and not isinstance(instance, DisposableBean):
                callbacks.append(destroy)

            for callback in callbacks:
                try:
                    callback()
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
                    logger.exception(
                        "Bean '%s' destruction callback failed: %s",
                        bean_name,
                        exc,
                    )

        # Remove the instance even when a callback failed.  Keeping it in the
        # singleton map would permit a later teardown to invoke arbitrary user
        # code a second time.
        self._bean_instances.pop(bean_name, None)
        # 清理二三级缓存
        self._singleton_factories.pop(bean_name, None)
        self._early_singleton_objects.pop(bean_name, None)
        definition.mark_destroyed()

        if first_error is not None:
            raise first_error

    def start_lifecycles(self) -> None:
        """启动所有SmartLifecycle组件（在ApplicationContext refresh完成后调用）。"""
        self._lifecycle_processor.start()

    def stop_lifecycles(self) -> None:
        """停止所有SmartLifecycle组件（在ApplicationContext close前调用）。"""
        self._lifecycle_processor.stop()

    def _invoke_pre_destroy(self, instance: Any) -> None:
        first_error = None
        for name, method in inspect.getmembers(instance.__class__):
            if not name.startswith('_') and inspect.isfunction(method):
                annotations = getattr(method, '__spring_annotations__', [])
                for annotation in annotations:
                    if isinstance(annotation, PreDestroy):
                        try:
                            method(instance)
                        except Exception as exc:
                            if first_error is None:
                                first_error = exc
                            logger.exception(
                                "@PreDestroy callback '%s' failed: %s",
                                name,
                                exc,
                            )
        if first_error is not None:
            raise first_error

    def destroy_all(self) -> None:
        for bean_name in list(self._bean_instances.keys()):
            try:
                self.destroy_bean(bean_name)
            except Exception as exc:
                # Teardown is best effort: one faulty user destructor must not
                # leave every later connection pool alive.
                logger.error(
                    "Failed to destroy bean '%s' error_type=%s",
                    bean_name, type(exc).__name__)

        # Mark lazy/prototype definitions as destroyed as well.  They have no
        # instance to visit, but allowing them to be resolved after shutdown
        # would recreate external resources from a dead context.
        for definition in self._bean_definitions.values():
            if not definition._destroyed:
                definition.mark_destroyed()

        self._cache.clear()
        self._cache_metadata.clear()

        # Individual errors are already logged above.  Keep ``destroy_all``
        # non-throwing so ApplicationContext/ASGI shutdown always reaches its
        # remaining cleanup steps.

    def contains_bean(self, bean_name: str) -> bool:
        return bean_name in self._bean_definitions

    def get_bean_names(self) -> list:
        return list(self._bean_definitions.keys())

    def get_bean_count(self) -> int:
        return len(self._bean_definitions)

    def _apply_aop_proxy(self, instance: Any, definition: BeanDefinition) -> None:
        bean_class = instance.__class__
        from springbootai.utils.logger import SpringLogger
        logger = SpringLogger()
        
        logger.info(f"Applying AOP proxy to bean: {definition.bean_name}, instance: {id(instance)}")
        
        for name, method in inspect.getmembers(bean_class):
            if not name.startswith('_') and inspect.isfunction(method):
                # 跳过 @staticmethod：getmembers 会把静态方法拆成底层函数，
                # 若用 types.MethodType 绑定到实例，会把实例当作首个位置参数，
                # 导致 MemoryFactory.create("buffer") 之类调用失败
                # （memory_type 收到的是实例而非 "buffer"）。静态方法无需绑定。
                raw_descriptor = inspect.getattr_static(bean_class, name, None)
                if isinstance(raw_descriptor, staticmethod):
                    continue
                annotations = getattr(method, '__spring_annotations__', [])
                
                if annotations:
                    logger.info(f"  Found method {name} with annotations: {[type(a).__name__ for a in annotations]}")
                
                # 处理新注解（使用 comprehensive_aop）
                try:
                    from springbootai.aop.comprehensive_aop import apply_annotations
                    wrapped_method = apply_annotations(instance, method)
                    if wrapped_method is not method:
                        logger.info(f"  Method {name} wrapped successfully")
                    method = wrapped_method
                except ImportError as e:
                    logger.error(f"  Failed to import comprehensive_aop: {e}")
                
                # 处理 Cloud 注解（使用 cloud_aop）
                try:
                    from springbootai.aop.cloud_aop import apply_cloud_annotations
                    wrapped_method = apply_cloud_annotations(instance, method)
                    if wrapped_method is not method:
                        logger.info(f"  Method {name} wrapped with Cloud AOP successfully")
                    method = wrapped_method
                except ImportError as e:
                    logger.error(f"  Failed to import cloud_aop: {e}")

                # AI 注解层：使用已注册 ChatClient/VectorStore/Agent Bean，
                # 依赖在方法首次调用时解析，兼容 Nacos/环境动态装配。
                try:
                    from springbootai.ai.annotation_runtime import apply_ai_annotations
                    method = apply_ai_annotations(self, instance, method)
                except Exception as e:
                    logger.error(f"  Failed to apply AI annotations: {e}")
                
                # 固定包装顺序：事务在计算内部，缓存命中可跳过事务，异步最外层调度。
                for annotation in annotations:
                    if isinstance(annotation, Transactional):
                        method = self._wrap_transactional(instance, method, annotation)
                for annotation in annotations:
                    if isinstance(annotation, Cacheable):
                        method = self._wrap_cacheable(instance, method, annotation)
                # 缓存增强：@CachePut / @CacheEvict / @Caching（复用 @Cacheable 同一存储）
                for annotation in annotations:
                    if isinstance(annotation, CachePut):
                        method = self._wrap_cache_put(instance, method, annotation)
                for annotation in annotations:
                    if isinstance(annotation, CacheEvict):
                        method = self._wrap_cache_evict(instance, method, annotation)
                for annotation in annotations:
                    if isinstance(annotation, Caching):
                        method = self._wrap_caching(instance, method, annotation)
                for annotation in annotations:
                    if isinstance(annotation, Async):
                        method = self._wrap_async(instance, method, annotation)

                # Security stays outermost: it consumes the internal request
                # argument and authenticates before transaction/business logic.
                try:
                    from springbootai.security.security_aop import apply_security_annotations
                    method = apply_security_annotations(instance, method)
                except ImportError as e:
                    logger.error(f"  Failed to import security_aop: {e}")

                # Declarative aspect advice is the outermost managed-Bean
                # layer and sees the final result of built-in AOP/security.
                try:
                    from springbootai.aop.aspect import apply_aspects
                    method = apply_aspects(
                        self,
                        instance,
                        getattr(bean_class, name),
                        method,
                        definition.bean_name,
                    )
                except ImportError as e:
                    logger.error(f"  Failed to import declarative AOP: {e}")
                
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

        def should_rollback(exc: BaseException) -> bool:
            if annotation.no_rollback_for and any(
                isinstance(exc, exc_type) for exc_type in annotation.no_rollback_for
            ):
                return False
            if annotation.rollback_for and not any(
                isinstance(exc, exc_type) for exc_type in annotation.rollback_for
            ):
                return False
            return True

        propagation = str(annotation.propagation or 'REQUIRED').upper()

        def begin_synchronization(tx_sync):
            """Return ``(owns_boundary, context_token)`` for propagation."""
            if tx_sync is None:
                return False, None
            active = tx_sync.is_synchronization_active()
            if propagation == 'REQUIRES_NEW' or (
                not active and propagation in {'REQUIRED', 'NESTED'}
            ):
                return True, tx_sync.init_synchronization()
            if active and propagation in {'NOT_SUPPORTED', 'NEVER'}:
                return False, tx_sync.suspend_synchronization()
            return False, None

        if asyncio.iscoroutinefunction(method):
            @functools.wraps(method)
            async def async_wrapper(*args, **kwargs):
                from springbootai.orm.mybatis_integration import mybatis_transaction
                tx_sync = _get_tx_sync_manager()

                owns_sync, sync_token = begin_synchronization(tx_sync)

                deferred_exception = None
                deferred_traceback = None
                committed = False
                try:
                    with mybatis_transaction(
                        get_session_factory(), propagation
                    ):
                        try:
                            result = await method(*args, **kwargs)
                        except BaseException as exc:
                            if should_rollback(exc):
                                raise
                            deferred_exception = exc
                            deferred_traceback = exc.__traceback__
                            result = None
                        if owns_sync:
                            tx_sync.trigger_before_commit()
                    committed = True
                    if owns_sync:
                        tx_sync.trigger_after_commit()
                    if deferred_exception is not None:
                        raise deferred_exception.with_traceback(deferred_traceback)
                    return result
                except BaseException:
                    if owns_sync and not committed:
                        tx_sync.trigger_after_rollback()
                    raise
                finally:
                    if owns_sync:
                        tx_sync.trigger_after_completion(
                            'commit' if committed else 'rollback'
                        )
                    if sync_token is not None:
                        tx_sync.restore_synchronization(sync_token)

            return async_wrapper

        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            from springbootai.orm.mybatis_integration import mybatis_transaction
            tx_sync = _get_tx_sync_manager()

            owns_sync, sync_token = begin_synchronization(tx_sync)

            deferred_exception = None
            deferred_traceback = None
            committed = False
            try:
                with mybatis_transaction(
                    get_session_factory(), propagation
                ):
                    try:
                        result = method(*args, **kwargs)
                    except BaseException as exc:
                        if should_rollback(exc):
                            raise
                        deferred_exception = exc
                        deferred_traceback = exc.__traceback__
                        result = None
                    # 成功路径（含 no-rollback 异常）：提交前触发 BEFORE_COMMIT
                    if owns_sync:
                        tx_sync.trigger_before_commit()
                committed = True
                if owns_sync:
                    tx_sync.trigger_after_commit()
                if deferred_exception is not None:
                    raise deferred_exception.with_traceback(deferred_traceback)
                return result
            except BaseException:
                if owns_sync and not committed:
                    tx_sync.trigger_after_rollback()
                raise
            finally:
                if owns_sync:
                    tx_sync.trigger_after_completion(
                        'commit' if committed else 'rollback'
                    )
                if sync_token is not None:
                    tx_sync.restore_synchronization(sync_token)

        return wrapper

    def _wrap_cacheable(self, instance: Any, method: Callable, annotation: Cacheable) -> Callable:
        def resolve_call(args, kwargs):
            return self._cache_resolve_call(
                method, annotation, instance, args, kwargs)

        if asyncio.iscoroutinefunction(method):
            @functools.wraps(method)
            async def async_wrapper(*args, **kwargs):
                enabled, cache_key, namespace = resolve_call(args, kwargs)
                if not enabled:
                    return await method(*args, **kwargs)
                while True:
                    hit, cached = self._cache_get(cache_key)
                    if hit:
                        return cached
                    owner, flight = self._cache_begin_flight(cache_key)
                    if owner:
                        break
                    # Shield the shared concurrent Future: cancelling one
                    # waiter must not cancel the computation for everyone.
                    await asyncio.shield(asyncio.wrap_future(flight))
                try:
                    result = await method(*args, **kwargs)
                    self._cache_store(cache_key, result, namespace)
                except BaseException as exc:
                    self._cache_finish_flight(cache_key, flight, error=exc)
                    raise
                self._cache_finish_flight(cache_key, flight)
                return result

            return async_wrapper

        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            enabled, cache_key, namespace = resolve_call(args, kwargs)
            if not enabled:
                return method(*args, **kwargs)
            while True:
                hit, cached = self._cache_get(cache_key)
                if hit:
                    return cached
                owner, flight = self._cache_begin_flight(cache_key)
                if owner:
                    break
                flight.result()
            try:
                result = method(*args, **kwargs)
                self._cache_store(cache_key, result, namespace)
            except BaseException as exc:
                self._cache_finish_flight(cache_key, flight, error=exc)
                raise
            self._cache_finish_flight(cache_key, flight)
            return result

        return wrapper

    # ==================== 缓存增强：@CachePut / @CacheEvict / @Caching ====================
    # 复用 @Cacheable 同一存储（self._cache / self._cache_metadata / self._lock / TTL）。
    # key 解析逻辑与 _wrap_cacheable 一致（参数名/{param}模板/全参数聚合 + condition），
    # 为保证既有 @Cacheable 行为零回归，本组方法独立实现解析，未改动 _wrap_cacheable。

    def _resolve_cache_value(self, instance: Any, annotation_value: str) -> str:
        """解析缓存命名空间：注解 value 为空时回退到类级 ``@CacheConfig`` 默认。"""
        if annotation_value:
            return annotation_value
        # 读类级 @CacheConfig
        from springbootai.annotations.core import get_spring_annotations
        try:
            for ann in get_spring_annotations(instance.__class__):
                if isinstance(ann, CacheConfig) and ann.cache_names:
                    return ann.cache_names[0]
        except Exception:
            pass
        return annotation_value

    def _resolve_cache_config(self, instance: Any) -> Optional[CacheConfig]:
        from springbootai.annotations.core import get_spring_annotations
        try:
            return next(
                (ann for ann in get_spring_annotations(instance.__class__)
                 if isinstance(ann, CacheConfig)),
                None,
            )
        except Exception:
            return None

    def _cache_serialize_arg(self, arg: Any) -> str:
        """Serialize a cache argument without cross-type/delimiter collisions."""
        def packed(tag: str, payload: str = '') -> str:
            return f"{tag}:{len(payload)}:{payload}"

        if arg is None:
            return packed('none')
        # bool is an int subclass, so it must be handled first.
        if isinstance(arg, bool):
            return packed('bool', '1' if arg else '0')
        if isinstance(arg, int):
            return packed('int', str(arg))
        if isinstance(arg, float):
            return packed('float', repr(arg))
        if isinstance(arg, str):
            return packed('str', arg)
        if isinstance(arg, bytes):
            return packed('bytes', arg.hex())
        if isinstance(arg, list):
            payload = ''.join(packed(
                'item', self._cache_serialize_arg(item)) for item in arg)
            return packed('list', payload)
        if isinstance(arg, tuple):
            payload = ''.join(packed(
                'item', self._cache_serialize_arg(item)) for item in arg)
            return packed('tuple', payload)
        if isinstance(arg, (set, frozenset)):
            items = sorted(self._cache_serialize_arg(item) for item in arg)
            payload = ''.join(packed('item', item) for item in items)
            return packed(
                'frozenset' if isinstance(arg, frozenset) else 'set', payload)
        if isinstance(arg, dict):
            items = sorted(
                ((self._cache_serialize_arg(k), self._cache_serialize_arg(v)) for k, v in arg.items()),
                key=lambda item: item[0],
            )
            payload = ''.join(
                packed('key', key) + packed('value', value)
                for key, value in items
            )
            return packed('dict', payload)
        type_name = f"{type(arg).__module__}.{type(arg).__qualname__}"
        return packed('object', f"{type_name}:{id(arg)}")

    def _cache_resolve_call(self, method: Callable, annotation: Any, instance: Any, args, kwargs):
        """解析一次缓存操作的 (enabled, cache_key, namespace)。返回 (False, None, None) 表示跳过。

        与 _wrap_cacheable.resolve_call 语义一致：condition 支持 参数名 / ``!参数名`` / callable。
        额外返回 namespace（解析后的 value），供 _cache_store 登记，便于 @CacheEvict(all_entries) 清空。
        """
        signature = inspect.signature(method)
        bound = signature.bind_partial(*args, **kwargs)
        bound.apply_defaults()
        cache_arguments = dict(bound.arguments)
        cache_arguments.pop('self', None)

        condition = getattr(annotation, 'condition', None)
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
                        f"缓存 condition 只支持参数名，未找到: {condition_name}"
                    )
                enabled = bool(cache_arguments[condition_name])
                if negate:
                    enabled = not enabled
            if not enabled:
                return False, None, None

        value = self._resolve_cache_value(instance, getattr(annotation, 'value', '') or '')
        key_expr = getattr(annotation, 'key', None)
        if key_expr:
            if '{' in key_expr:
                try:
                    resolved_key = key_expr.format(**cache_arguments)
                except KeyError as exc:
                    raise ValueError(
                        f"缓存 key 引用了不存在的参数: {exc.args[0]}"
                    ) from exc
            elif key_expr in cache_arguments:
                resolved_key = self._cache_serialize_arg(cache_arguments[key_expr])
            else:
                resolved_key = key_expr
            # key = namespace + resolvedKey（与 _wrap_cacheable 一致，不含方法名，
            # 使 @CachePut / @CacheEvict 与 @Cacheable 跨方法共享同一缓存条目）。
            key_data = f"{value}:{resolved_key}"
        else:
            cache_config = self._resolve_cache_config(instance)
            generator_name = (
                cache_config.key_generator if cache_config else None)
            if generator_name:
                generator = self.get_bean(generator_name)
                parameters = tuple(cache_arguments.values())
                generate = getattr(generator, 'generate', None)
                if callable(generate):
                    generated = generate(instance, method, parameters)
                elif callable(generator):
                    generated = generator(instance, method, parameters)
                else:
                    raise TypeError(
                        f"Cache key generator '{generator_name}' is not callable")
                if generated is None:
                    raise ValueError(
                        f"Cache key generator '{generator_name}' returned None")
                key_data = f"{value}:{self._cache_serialize_arg(generated)}"
                return (True,
                        hashlib.sha256(key_data.encode('utf-8')).hexdigest(),
                        value)
            arguments = ','.join(
                f"{name}:{self._cache_serialize_arg(val)}"
                for name, val in sorted(cache_arguments.items())
            )
            key_data = f"{value}:{arguments}"
        return True, hashlib.sha256(key_data.encode('utf-8')).hexdigest(), value

    def _cache_get(self, cache_key: str):
        """读取缓存条目（过期则视为未命中并清理）。返回 (hit, value)。"""
        with self._lock:
            current_time = time.monotonic()
            metadata = self._cache_metadata.get(cache_key)
            if metadata is None or cache_key not in self._cache:
                return False, None
            if current_time > metadata.get('expire_time', current_time):
                self._cache.pop(cache_key, None)
                self._cache_metadata.pop(cache_key, None)
                return False, None
            try:
                # Never expose the canonical cached object. A request-local
                # mutation must not poison later callers or other principals.
                return True, copy.deepcopy(self._cache[cache_key])
            except Exception as exc:
                self._cache.pop(cache_key, None)
                self._cache_metadata.pop(cache_key, None)
                raise TypeError(
                    "Cache values must be safely deep-copyable") from exc

    def _cache_store(self, cache_key: str, result: Any, namespace: str = "") -> None:
        """写入缓存条目（复用 @Cacheable 的容量淘汰与 TTL）。

        ``namespace`` 登记到 metadata，供 ``@CacheEvict(all_entries=True)`` 按命名空间清空。
        """
        try:
            stored_result = copy.deepcopy(result)
        except Exception as exc:
            raise TypeError(
                "Cache values must be safely deep-copyable") from exc
        current_time = time.monotonic()
        with self._lock:
            if len(self._cache) >= self._cache_max_size:
                oldest_key = min(
                    self._cache_metadata,
                    key=lambda k: self._cache_metadata[k].get('create_time', 0),
                )
                self._cache.pop(oldest_key, None)
                self._cache_metadata.pop(oldest_key, None)
            self._cache[cache_key] = stored_result
            self._cache_metadata[cache_key] = {
                'create_time': current_time,
                'expire_time': current_time + self._cache_default_ttl,
                'namespace': namespace,
            }

    def _cache_begin_flight(
        self, cache_key: str,
    ) -> Tuple[bool, concurrent.futures.Future]:
        """Join or create the one in-flight computation for ``cache_key``."""
        with self._lock:
            flight = self._cache_inflight.get(cache_key)
            if flight is not None:
                return False, flight
            flight = concurrent.futures.Future()
            self._cache_inflight[cache_key] = flight
            return True, flight

    def _cache_finish_flight(
        self,
        cache_key: str,
        flight: concurrent.futures.Future,
        *,
        error: Optional[BaseException] = None,
    ) -> None:
        """Wake all waiters and remove exactly the completed generation."""
        with self._lock:
            if self._cache_inflight.get(cache_key) is flight:
                self._cache_inflight.pop(cache_key, None)
        if flight.done():
            return
        if error is None:
            flight.set_result(True)
        else:
            flight.set_exception(error)

    def _cache_evict_key(self, cache_key: str) -> None:
        with self._lock:
            self._cache.pop(cache_key, None)
            self._cache_metadata.pop(cache_key, None)

    def _cache_evict_prefix(self, namespace: str) -> int:
        """清空整个缓存命名空间。

        ``cache_key`` 由 ``sha256(...)`` 生成，无法按前缀匹配；因此在 ``_cache_store`` 时把
        ``namespace`` 登记到 metadata，这里扫描 metadata 按 namespace 清空（含 @Cacheable 条目）。
        """
        removed = 0
        with self._lock:
            victims = [k for k, meta in self._cache_metadata.items()
                        if meta.get('namespace') == namespace]
            for k in victims:
                self._cache.pop(k, None)
                self._cache_metadata.pop(k, None)
                removed += 1
        return removed

    def _wrap_cache_put(self, instance: Any, method: Callable, annotation: CachePut) -> Callable:
        """``@CachePut``：方法总是执行，把返回值写入缓存。"""
        if asyncio.iscoroutinefunction(method):
            @functools.wraps(method)
            async def async_wrapper(*args, **kwargs):
                enabled, cache_key, ns = self._cache_resolve_call(method, annotation, instance, args, kwargs)
                result = await method(*args, **kwargs)
                if enabled:
                    self._cache_store(cache_key, result, ns)
                return result
            return async_wrapper

        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            enabled, cache_key, ns = self._cache_resolve_call(method, annotation, instance, args, kwargs)
            result = method(*args, **kwargs)
            if enabled:
                self._cache_store(cache_key, result, ns)
            return result
        return wrapper

    def _wrap_cache_evict(self, instance: Any, method: Callable, annotation: CacheEvict) -> Callable:
        """``@CacheEvict``：失效缓存。

        - ``before_invocation=True``：方法调用前失效（无论成功与否）。
        - ``before_invocation=False``（默认）：方法成功后失效（异常时不失效）。
        - ``all_entries=True``：清空整个命名空间；否则按 key 失效。
        """
        def _do_evict(args, kwargs):
            if annotation.all_entries:
                self._cache_evict_prefix(
                    self._resolve_cache_value(instance, annotation.value or ''))
                return
            enabled, cache_key, _ns = self._cache_resolve_call(method, annotation, instance, args, kwargs)
            if enabled:
                self._cache_evict_key(cache_key)

        if asyncio.iscoroutinefunction(method):
            @functools.wraps(method)
            async def async_wrapper(*args, **kwargs):
                if annotation.before_invocation:
                    _do_evict(args, kwargs)
                result = await method(*args, **kwargs)
                if not annotation.before_invocation:
                    _do_evict(args, kwargs)
                return result
            return async_wrapper

        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            if annotation.before_invocation:
                _do_evict(args, kwargs)
            result = method(*args, **kwargs)
            if not annotation.before_invocation:
                _do_evict(args, kwargs)
            return result
        return wrapper

    def _wrap_caching(self, instance: Any, method: Callable, annotation: Caching) -> Callable:
        """``@Caching``：组合多个缓存操作，按 cacheable -> put -> evict 顺序叠加包装。

        每个子操作调用对应的 wrap，逐层包装（与 Spring ``@Caching`` 应用多操作语义一致）。
        """
        wrapped = method
        for op in (annotation.cacheable or []):
            wrapped = self._wrap_cacheable(instance, wrapped, op)
        for op in (annotation.put or []):
            wrapped = self._wrap_cache_put(instance, wrapped, op)
        for op in (annotation.evict or []):
            wrapped = self._wrap_cache_evict(instance, wrapped, op)
        return wrapped

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
            from springbootai.annotations.cloud import NacosValue
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
