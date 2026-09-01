from typing import Optional, Type, Any, List, Dict, get_type_hints
import os
import sys
from springbootai.context.bean_factory import BeanFactory, MissingBeanDependencyError
from springbootai.context.bean_definition import BeanDefinition
from springbootai.context.scanner import ComponentScanner
from springbootai.annotations.core import (
    SpringBootApplication,
    ComponentScan,
    Component,
    Service,
    Repository,
    Controller,
    RestController,
    Configuration,
    Bean,
    Autowired,
    Qualifier,
    Value,
    ConfigurationProperties,
    Scope,
    Profile,
    Lazy,
    EventListener,
)
from springbootai.annotations.cloud import EnableFeignClients, FeignClient
from springbootai.annotations.conditional import all_conditions_match as _all_conditions_match
from springbootai.config.config_loader import ConfigLoader, set_global_config_loader
from springbootai.event import ApplicationEventPublisher
from springbootai.core.typing_utils import unwrap_optional_type
import inspect


class ApplicationContext:
    _current_context: Optional['ApplicationContext'] = None

    # These integrations expose connection failures through their own exception
    # hierarchies instead of the built-in ``ConnectionError``/``TimeoutError``.
    # Keep this deliberately narrow: a lifecycle fallback must not hide generic
    # driver, validation, or application errors merely because they originate
    # in an optional third-party package.
    _EXTERNAL_CONNECTIVITY_ERROR_TYPES = frozenset({
        ('redis.exceptions', 'ConnectionError'),
        ('redis.exceptions', 'TimeoutError'),
        ('pika.exceptions', 'AMQPConnectionError'),
        ('pika.exceptions', 'AMQPHeartbeatTimeout'),
        ('pika.exceptions', 'ConnectionClosedByBroker'),
        ('kafka.errors', 'NoBrokersAvailable'),
        ('kafka.errors', 'KafkaConnectionError'),
        ('kafka.errors', 'KafkaTimeoutError'),
        ('pymysql.err', 'InterfaceError'),
        ('pymysql.err', 'OperationalError'),
        ('psycopg2', 'InterfaceError'),
        ('psycopg2', 'OperationalError'),
        ('psycopg', 'InterfaceError'),
        ('psycopg', 'OperationalError'),
        ('sqlalchemy.exc', 'DisconnectionError'),
        ('sqlalchemy.exc', 'InvalidatePoolError'),
        ('sqlalchemy.exc', 'OperationalError'),
        ('sqlalchemy.exc', 'TimeoutError'),
        ('requests.exceptions', 'ConnectionError'),
        ('requests.exceptions', 'ConnectTimeout'),
        ('requests.exceptions', 'ReadTimeout'),
        ('httpx', 'ConnectError'),
        ('httpx', 'ConnectTimeout'),
        ('httpx', 'ReadTimeout'),
        ('httpx', 'PoolTimeout'),
    })

    def __init__(self, main_class: Type, config_loader: Optional[ConfigLoader] = None):
        ApplicationContext._current_context = self
        
        # 确保main_class是一个类
        if not inspect.isclass(main_class):
            # 如果不是类，尝试从__spring_annotations__中获取原始类
            if hasattr(main_class, '__spring_annotations__'):
                for annotation in main_class.__spring_annotations__:
                    if hasattr(annotation, '_original_class'):
                        main_class = annotation._original_class
                        break

        # Keep the normalized class on the context.  Decorators may expose a
        # callable wrapper carrying ``_original_class``; retaining the wrapper
        # here makes package scanning and annotation lookup inconsistent.
        self.main_class = main_class

        if config_loader is not None:
            context_config_loader = config_loader
        else:
            # ``inspect.getfile`` raises for built-in/dynamically-created
            # classes.  Such classes are valid in tests and in embedding
            # scenarios; fall back to the process working directory so the
            # context can still start with the normal ConfigLoader defaults.
            try:
                main_class_file = inspect.getfile(main_class)
            except (TypeError, OSError):
                main_class_file = os.path.join(os.getcwd(), "__main__.py")
            main_class_dir = os.path.dirname(os.path.abspath(main_class_file))
            context_config_loader = ConfigLoader(base_path=main_class_dir)
        self.config_loader = set_global_config_loader(context_config_loader)
        self.bean_factory = BeanFactory(self.config_loader)
        self.event_publisher = ApplicationEventPublisher()
        publisher_definition = BeanDefinition(
            bean_class=ApplicationEventPublisher,
            bean_name='application_event_publisher',
        )
        self.bean_factory.register_bean_definition(
            'application_event_publisher', publisher_definition
        )
        self.bean_factory.register_instance(
            'application_event_publisher', self.event_publisher
        )
        # 事务事件发布器（@TransactionalEventListener）；springbootai.tx 缺失时为 None，降级为普通事件
        self.tx_event_publisher = None
        try:
            from springbootai.tx import TransactionalEventPublisher
            self.tx_event_publisher = TransactionalEventPublisher()
            tx_publisher_definition = BeanDefinition(
                bean_class=TransactionalEventPublisher,
                bean_name='transactional_event_publisher',
            )
            self.bean_factory.register_bean_definition(
                'transactional_event_publisher', tx_publisher_definition
            )
            self.bean_factory.register_instance(
                'transactional_event_publisher', self.tx_event_publisher
            )
        except ImportError:  # pragma: no cover
            pass
        self.scanner = ComponentScanner(self)
        self._scheduler = None
        self._started = False
        # Beans whose optional dependencies could not be created while the
        # application is running in non-fail-fast mode.  Lifecycle scanners
        # consult this set so one unavailable integration does not prevent
        # unrelated web endpoints from starting.
        self._unavailable_beans: Dict[str, Exception] = {}
        from springbootai.utils.logger import SpringLogger
        self.logger = SpringLogger()

    @classmethod
    def get_instance(cls) -> Optional['ApplicationContext']:
        """Return the currently active application context, if any."""
        return cls._current_context

    def _startup_fail_fast(self) -> bool:
        """Return whether lifecycle bean failures should abort startup."""
        try:
            config = self.config_loader.get_config()
        except Exception:
            config = {}
        if not isinstance(config, dict):
            return False

        startup = config.get('startup')
        if isinstance(startup, dict) and 'fail_fast' in startup:
            value = startup.get('fail_fast')
            if isinstance(value, str):
                return value.strip().lower() in {'true', '1', 'yes', 'on'}
            return bool(value)

        spring = config.get('spring')
        profiles = spring.get('profiles') if isinstance(spring, dict) else {}
        active = profiles.get('active', 'default') if isinstance(profiles, dict) else 'default'
        return str(active).strip().lower() in {'prod', 'production'}

    def _get_lifecycle_bean(self, bean_name: str, phase: str):
        """Resolve a bean for startup bookkeeping, honoring ``fail_fast``.

        Enterprise integrations are often optional (for example a MySQL
        mapper when the local developer has no MySQL server).  In tolerant
        mode, remember only dependency/import/connection failures and let
        other lifecycle phases proceed; application logic errors still
        propagate.  In production/fail-fast mode every failure propagates.
        """
        unavailable_beans = getattr(self, '_unavailable_beans', None)
        if unavailable_beans is None:
            unavailable_beans = self._unavailable_beans = {}
        if bean_name in unavailable_beans:
            return None
        try:
            return self.bean_factory.get_bean(bean_name)
        except Exception as exc:
            if self._startup_fail_fast():
                raise
            if not self._is_tolerable_lifecycle_error(exc):
                # ``fail_fast=false`` is intended for unavailable optional
                # integrations, not for hiding arbitrary application bugs in
                # constructors, post-construct hooks, or validation.
                raise
            unavailable_beans[bean_name] = exc
            logger = getattr(self, 'logger', None)
            if logger is not None:
                logger.warning(
                    f"Skipping bean '{bean_name}' during {phase} "
                    f"error_type={type(exc).__name__}")
            return None

    @classmethod
    def _is_tolerable_lifecycle_error(cls, exc: Exception) -> bool:
        """Return whether a lifecycle failure is an optional dependency outage.

        Client libraries often wrap the actual network exception in a generic
        ``RuntimeError`` or a framework-specific outer exception.  Walk the
        explicit exception chain, but classify only built-in connection errors
        and a small, module-and-type whitelist for supported integrations.
        """
        seen = set()
        current = exc
        while isinstance(current, Exception) and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, (
                MissingBeanDependencyError,
                ImportError,
                ConnectionError,
                TimeoutError,
            )):
                return True

            for error_type in type(current).__mro__:
                if (
                    error_type.__module__, error_type.__name__
                ) in cls._EXTERNAL_CONNECTIVITY_ERROR_TYPES:
                    return True

            next_error = current.__cause__
            if next_error is None and not current.__suppress_context__:
                next_error = current.__context__
            current = next_error
        return False

    def is_bean_unavailable(self, bean_name: str) -> bool:
        """Return whether tolerant startup skipped ``bean_name``."""
        return bean_name in self._unavailable_beans

    def refresh(self) -> None:
        if self._started:
            return

        # 记录刷新前的 Bean 名快照，失败时回滚到该状态，避免部分 Bean 已注册导致不一致
        snapshot = set(self.bean_factory.get_bean_names()) if hasattr(self.bean_factory, 'get_bean_names') else set()
        self._unavailable_beans.clear()
        try:
            self._load_config()
            self._scan_components()
            self._register_feign_clients()
            self._register_configuration_beans()
            self._autowire_configuration_properties()
            self._autowire_value_annotations()
            self._register_event_listeners()
            self._register_scheduled_tasks()
            self._started = True
        except Exception as e:
            self.logger.error(
                "Failed to refresh application context: "
                f"error_type={type(e).__name__}")
            # 回滚：移除本次 refresh 新注册的 Bean，清理已创建的资源，确保状态一致
            self._rollback_refresh(snapshot)
            raise

    def _rollback_refresh(self, snapshot: set) -> None:
        """refresh() 失败时回滚到刷新前的状态。

        - 移除本次新增的 Bean 定义和实例
        - 停止已启动的定时任务
        - 关闭已初始化的连接池等资源
        """
        try:
            # 停止定时任务（若已启动）。Spring's local scheduler exposes
            # ``stop_all``; retain the ``shutdown`` fallback for custom
            # schedulers supplied by integrations.
            self._stop_scheduler()

            # 移除本次新增的 Bean
            current_names = set(self.bean_factory.get_bean_names()) if hasattr(self.bean_factory, 'get_bean_names') else set()
            for name in current_names - snapshot:
                try:
                    # Destroy before removing the definition; BeanFactory's
                    # normal destroy path needs the definition to locate
                    # custom close methods and @PreDestroy hooks.
                    self.bean_factory.destroy_bean(name)
                except Exception:
                    # A broken destructor must not prevent the remaining
                    # newly-created beans from being cleaned up.
                    pass
                try:
                    if hasattr(self.bean_factory, 'remove_bean_definition'):
                        self.bean_factory.remove_bean_definition(name)
                    elif hasattr(self.bean_factory, '_bean_definitions'):
                        self.bean_factory._bean_definitions.pop(name, None)
                        if hasattr(self.bean_factory, '_bean_instances'):
                            self.bean_factory._bean_instances.pop(name, None)
                        if hasattr(self.bean_factory, '_type_to_name'):
                            for bean_type, mapped_name in list(self.bean_factory._type_to_name.items()):
                                if mapped_name == name:
                                    self.bean_factory._type_to_name.pop(bean_type, None)
                except Exception:
                    pass
        except Exception:
            pass  # 回滚失败不应掩盖原始异常

    def _stop_scheduler(self) -> None:
        """Stop scheduled work without letting teardown mask the root error."""
        scheduler = self._scheduler
        self._scheduler = None
        if scheduler is None:
            return

        try:
            stop_all = getattr(scheduler, 'stop_all', None)
            if callable(stop_all):
                stop_all()
                return

            shutdown = getattr(scheduler, 'shutdown', None)
            if callable(shutdown):
                try:
                    shutdown(wait=False)
                except TypeError:
                    shutdown()
        except Exception as exc:
            self.logger.warning(
                "Failed to stop scheduled tasks: "
                f"error_type={type(exc).__name__}")

    def _load_config(self) -> None:
        self.config_loader.load_config()

    def _scan_components(self) -> None:
        base_packages = self._get_base_packages()
        components = self.scanner.scan(base_packages)
        for component in components:
            self._register_component(component)

    def _register_feign_clients(self) -> None:
        """Scan and register typed ``@FeignClient`` proxies when enabled."""
        annotations = getattr(self.main_class, '__spring_annotations__', [])
        enable = next((item for item in annotations if isinstance(item, EnableFeignClients)), None)
        if enable is None:
            return
        base_packages = enable.base_packages or self._get_base_packages()
        from springbootai.cloud.feign import create_declared_feign_client
        seen = set(self.bean_factory.get_bean_names())
        for client_class in self.scanner.scan_classes(base_packages):
            client_annotations = getattr(client_class, '__spring_annotations__', [])
            client_annotation = next(
                (item for item in client_annotations if isinstance(item, FeignClient)),
                None,
            )
            if client_annotation is None:
                continue
            bean_name = client_annotation.value or self._generate_bean_name(client_class)
            if bean_name in seen:
                continue
            definition = BeanDefinition(bean_class=client_class, bean_name=bean_name)
            definition.add_annotation(client_annotation)
            self.bean_factory.register_bean_definition(bean_name, definition)
            self.bean_factory.register_instance(
                bean_name,
                create_declared_feign_client(client_class, client_annotation),
            )
            seen.add(bean_name)

    def _get_base_packages(self) -> List[str]:
        annotations = getattr(self.main_class, '__spring_annotations__', [])
        for annotation in annotations:
            if isinstance(annotation, SpringBootApplication):
                if annotation.scan_base_packages:
                    return annotation.scan_base_packages
                return [self._extract_package_name(self.main_class)]
            elif isinstance(annotation, ComponentScan):
                if annotation.base_packages:
                    return annotation.base_packages
        return [self._extract_package_name(self.main_class)]

    def _extract_package_name(self, main_class: Type) -> str:
        module_name = main_class.__module__
        # 处理__main__模块的情况（python -m xxx运行时）
        if module_name == '__main__':
            # 从__file__属性推断实际的模块名
            if hasattr(main_class, '__module__'):
                module_obj = sys.modules.get(main_class.__module__)
                if module_obj and hasattr(module_obj, '__file__'):
                    import os
                    file_path = module_obj.__file__
                    # 去掉.py后缀和路径，获取模块名
                    module_name = os.path.basename(file_path)[:-3]
                    # 如果是Application.py，返回当前目录名作为包名
                    if module_name == 'Application':
                        return os.path.basename(os.path.dirname(file_path))
        if '.' in module_name:
            return module_name.rsplit('.', 1)[0]
        return module_name

    def _register_component(self, component_class: Type) -> None:
        if not self._matches_active_profile(component_class):
            return
        if not self._matches_conditions(component_class):
            return

        annotations = getattr(component_class, '__spring_annotations__', [])
        explicit_name = next(
            (
                getattr(annotation, 'value', '')
                for annotation in annotations
                if isinstance(annotation, (Component, Service, Repository, Controller, RestController))
                and getattr(annotation, 'value', '')
            ),
            '',
        )
        bean_name = explicit_name or self._generate_bean_name(component_class)
        scope = next(
            (
                annotation.value for annotation in annotations if isinstance(annotation, Scope)
            ),
            'singleton',
        )
        definition = BeanDefinition(bean_class=component_class, bean_name=bean_name, scope=scope)

        for annotation in annotations:
            definition.add_annotation(annotation)

        self._extract_dependencies(component_class, definition)
        self.bean_factory.register_bean_definition(bean_name, definition)

    def _matches_active_profile(self, component_class: Type) -> bool:
        annotations = getattr(component_class, '__spring_annotations__', [])
        for annotation in annotations:
            if isinstance(annotation, Profile):
                active_profile = self.config_loader.get_active_profile()
                return active_profile in annotation.value
        return True

    def _matches_conditions(self, component_class: Type) -> bool:
        """求类上条件装配注解（@Conditional / @ConditionalOnProperty / ...）的合取。

        与 ``_matches_active_profile`` 并列，在 ``_register_component`` 阶段执行：
        任一条件为假则跳过该 Bean 的注册。条件注解的 ``matches(ctx)`` 接收本上下文，
        可访问 ``self.config_loader`` 与 ``self.bean_factory``。
        """
        return _all_conditions_match(component_class, self)

    def _generate_bean_name(self, cls: Type) -> str:
        name = cls.__name__
        if name.endswith('Controller'):
            base_name = name[:-10]
        elif name.endswith('Service'):
            base_name = name[:-7]
        elif name.endswith('Repository'):
            base_name = name[:-10]
        elif name.endswith('Config'):
            base_name = name[:-6]
        else:
            base_name = name
        
        # 将驼峰式转换为下划线式
        result = []
        for i, char in enumerate(base_name):
            if i > 0 and char.isupper():
                result.append('_')
            result.append(char.lower())
        
        suffix = ''
        if name.endswith('Controller'):
            suffix = '_controller'
        elif name.endswith('Service'):
            suffix = '_service'
        elif name.endswith('Repository'):
            suffix = '_repository'
        elif name.endswith('Config'):
            suffix = '_config'
        
        return ''.join(result) + suffix

    def _extract_dependencies(self, cls: Type, definition: BeanDefinition) -> None:
        if hasattr(cls, '__init__'):
            init_annotations = getattr(cls.__init__, '__spring_annotations__', [])
            if any(isinstance(a, Autowired) for a in init_annotations):
                sig = inspect.signature(cls.__init__)
                try:
                    type_hints = get_type_hints(cls.__init__, include_extras=True)
                except (NameError, TypeError):
                    type_hints = {}
                autowired = next(a for a in init_annotations if isinstance(a, Autowired))
                for param_name, param in sig.parameters.items():
                    if param_name == 'self':
                        continue
                    parameter_type = type_hints.get(param_name, param.annotation)
                    # 解包 Optional[X]：Python 3.10 的 get_type_hints 会把带 None 默认值的
                    # 构造参数注解自动包装为 Optional[X]（3.11+ 不再包装）。此处统一解包为承载类型，
                    # 否则按类型匹配 Bean 时 Optional[SomeService] 无法命中已注册的 SomeService。
                    # 在 Annotated 解包之前先解 Optional，可正确处理 Optional[Annotated[X, Q]]。
                    parameter_type = unwrap_optional_type(parameter_type)
                    if parameter_type is not inspect.Parameter.empty:
                        qualifier = None
                        for ann in init_annotations:
                            if isinstance(ann, Qualifier):
                                qualifier = ann.value
                                break
                        inline_qualifier = None
                        try:
                            from typing import Annotated, get_args, get_origin
                            if get_origin(parameter_type) is Annotated:
                                base, *metadata = get_args(parameter_type)
                                parameter_type = base
                                inline_qualifier = next(
                                    (item.value for item in metadata if isinstance(item, Qualifier)),
                                    None,
                                )
                        except (TypeError, AttributeError):
                            pass
                        definition.add_dependency(
                            param_name,
                            parameter_type,
                            inline_qualifier or qualifier,
                            required=autowired.required,
                        )

    def _register_configuration_beans(self) -> None:
        for bean_name in self.bean_factory.get_bean_names():
            definition = self.bean_factory.get_bean_definition(bean_name)
            if definition and Configuration._annotation_type in definition.annotations:
                config_instance = self._get_lifecycle_bean(bean_name, 'configuration')
                if config_instance is None:
                    continue
                self._register_beans_from_configuration(config_instance, definition)

    def _register_beans_from_configuration(self, config_instance: Any, config_definition: BeanDefinition) -> None:
        for name, method in inspect.getmembers(config_instance.__class__):
            if not name.startswith('_') and inspect.isfunction(method):
                annotations = getattr(method, '__spring_annotations__', [])
                for annotation in annotations:
                    if isinstance(annotation, Bean):
                        bean_name = annotation.name or name
                        scope = annotation.scope
                        init_method = annotation.init_method
                        destroy_method = annotation.destroy_method

                        # 对工厂方法应用 Cloud AOP 注解（如 @LoadBalanced）
                        wrapped_method = method
                        try:
                            from springbootai.aop.cloud_aop import apply_cloud_annotations
                            wrapped_method = apply_cloud_annotations(config_instance, method)
                        except ImportError:
                            pass
                        
                        # 对工厂方法应用 comprehensive AOP 注解
                        try:
                            from springbootai.aop.comprehensive_aop import apply_annotations
                            wrapped_method = apply_annotations(config_instance, wrapped_method)
                        except ImportError:
                            pass

                        bean_def = BeanDefinition(
                            bean_class=method,
                            bean_name=bean_name,
                            scope=scope,
                            init_method=init_method,
                            destroy_method=destroy_method,
                            factory_method=wrapped_method,  # 使用包装后的方法
                            factory_class=config_instance.__class__,
                        )

                        for method_annotation in annotations:
                            bean_def.add_annotation(method_annotation)

                        return_type = inspect.signature(method).return_annotation
                        if return_type is not inspect.Signature.empty:
                            bean_def.bean_class = return_type

                        self.bean_factory.register_bean_definition(bean_name, bean_def)

    def _autowire_configuration_properties(self) -> None:
        for bean_name in self.bean_factory.get_bean_names():
            definition = self.bean_factory.get_bean_definition(bean_name)
            if definition and ConfigurationProperties._annotation_type in definition.annotations:
                lazy_annotations = definition.annotations.get(Lazy._annotation_type, [])
                if any(annotation.value for annotation in lazy_annotations):
                    continue
                instance = self._get_lifecycle_bean(bean_name, 'configuration-properties')
                if instance is None:
                    continue
                self._apply_configuration_properties(instance, definition)

    def _apply_configuration_properties(self, instance: Any, definition: BeanDefinition) -> None:
        properties_annotations = definition.annotations.get(ConfigurationProperties._annotation_type)
        if not properties_annotations:
            return

        properties_annotation = properties_annotations[0]
        prefix = properties_annotation.prefix
        config = self.config_loader.get_prefix_config(prefix)

        # 松散绑定（kebab/camel/snake 等价匹配）+ 嵌套绑定 + 类型强转
        try:
            from springbootai.config.binding import (
                ConfigurationPropertiesBinder, validate_configuration_properties,
            )
            ConfigurationPropertiesBinder.bind(instance, config)
            # @Validated 触发 Bean Validation；违反约束抛 ValidationError
            validate_configuration_properties(instance)
        except ImportError:  # pragma: no cover - binding 为内置模块
            # 回退到原扁平绑定（兼容 springbootai.config.binding 缺失场景）
            for key, value in config.items():
                attr_name = key.replace('-', '_')
                if hasattr(instance, attr_name):
                    setattr(instance, attr_name, value)
                elif hasattr(instance, key):
                    setattr(instance, key, value)

    def _autowire_value_annotations(self) -> None:
        for bean_name in self.bean_factory.get_bean_names():
            try:
                # 获取bean实例（如果尚未实例化，会触发创建）
                definition = self.bean_factory.get_bean_definition(bean_name)
                if definition:
                    lazy_annotations = definition.annotations.get(Lazy._annotation_type, [])
                    if any(annotation.value for annotation in lazy_annotations):
                        continue
                resolver = getattr(self, '_get_lifecycle_bean', None)
                if callable(resolver):
                    instance = resolver(bean_name, 'value-injection')
                else:
                    # Keep lightweight test/embedding stubs compatible when
                    # they provide only a BeanFactory-like object.
                    instance = self.bean_factory.get_bean(bean_name)
                if instance is None:
                    continue
                bean_class = instance.__class__

                # 处理构造函数参数中的@Value注解
                if hasattr(bean_class, '__init__'):
                    sig = inspect.signature(bean_class.__init__)
                    for param_name, param in sig.parameters.items():
                        if param_name == 'self':
                            continue
                        if isinstance(param.default, Value):
                            value_annotation = param.default
                            config_value = self.config_loader.resolve_value_expression(
                                value_annotation.value,
                                getattr(value_annotation, 'default', None),
                            )
                            setattr(instance, param_name, config_value)
                
                # 处理字段上的@Value注解
                for name, field in inspect.getmembers(bean_class):
                    if not name.startswith('_'):
                        # @Value/@NacosValue can be attached to a function as
                        # metadata alongside route/AOP annotations.  Replacing
                        # that function on the instance makes the handler
                        # non-callable and breaks controller registration.
                        # Constructor/default and class-field injection are
                        # handled separately by BeanFactory.
                        if callable(field):
                            continue
                        annotations = getattr(field, '__spring_annotations__', [])
                        for annotation in annotations:
                            if isinstance(annotation, Value):
                                setattr(
                                    instance,
                                    name,
                                    self.config_loader.resolve_value_expression(
                                        annotation.value,
                                        getattr(annotation, 'default', None),
                                    ),
                                )
                            else:
                                try:
                                    from springbootai.annotations.cloud import NacosValue
                                except ImportError:
                                    NacosValue = ()
                                if NacosValue and isinstance(annotation, NacosValue):
                                    setattr(
                                        instance,
                                        name,
                                        self.config_loader.resolve_value_expression(
                                            annotation.value,
                                            None,
                                        ),
                                    )
            except Exception as exc:
                # Configuration expression errors and application lifecycle
                # bugs must remain visible.  Only dependency/import/connection
                # failures are degradable in tolerant startup mode.
                tolerable = getattr(self, '_is_tolerable_lifecycle_error', None)
                if (
                    callable(tolerable)
                    and not self._startup_fail_fast()
                    and tolerable(exc)
                ):
                    unavailable = getattr(self, '_unavailable_beans', None)
                    if unavailable is not None:
                        unavailable[bean_name] = exc
                    continue
                # Preserve the historical best-effort behavior for minimal
                # BeanFactory stubs that do not expose lifecycle helpers.
                if not callable(tolerable):
                    continue
                raise

    def _register_scheduled_tasks(self) -> None:
        from springbootai.scheduling.scheduler import Scheduler
        from springbootai.annotations.core import Scheduled
        
        self._scheduler = Scheduler()
        
        for bean_name in self.bean_factory.get_bean_names():
            definition = self.bean_factory.get_bean_definition(bean_name)
            if not definition:
                continue
            
            instance = self._get_lifecycle_bean(bean_name, 'scheduled-task')
            if instance is None:
                continue
            bean_class = instance.__class__
            
            for name, method in inspect.getmembers(bean_class):
                if not name.startswith('_') and inspect.isfunction(method):
                    annotations = getattr(method, '__spring_annotations__', [])
                    for annotation in annotations:
                        if isinstance(annotation, Scheduled):
                            task_id = f"{bean_name}.{name}"
                            self._scheduler.schedule(
                                task_id=task_id,
                                func=method.__get__(instance),
                                fixed_rate=annotation.fixed_rate,
                                fixed_delay=annotation.fixed_delay,
                                cron=annotation.cron,
                                initial_delay=annotation.initial_delay,
                            )

    def _register_event_listeners(self) -> None:
        self.event_publisher.clear()
        if self.tx_event_publisher is not None:
            self.tx_event_publisher.clear()
        # 事务事件监听器注解类型（springbootai.tx 缺失时为 None）
        try:
            from springbootai.tx import TransactionalEventListener as _TxEventListener
        except ImportError:  # pragma: no cover
            _TxEventListener = None

        for bean_name in self.bean_factory.get_bean_names():
            instance = self._get_lifecycle_bean(bean_name, 'event-listener')
            if instance is None:
                continue
            for name, method in inspect.getmembers(instance.__class__):
                if name.startswith('_') or not inspect.isfunction(method):
                    continue
                for annotation in getattr(method, '__spring_annotations__', []):
                    if isinstance(annotation, EventListener):
                        event_type = annotation.event_type
                        if event_type is None:
                            parameters = [
                                (parameter_name, parameter)
                                for parameter_name, parameter in inspect.signature(method).parameters.items()
                                if parameter_name != 'self'
                            ]
                            if parameters:
                                parameter_name, parameter = parameters[0]
                                try:
                                    event_type = get_type_hints(method).get(parameter_name)
                                except (NameError, TypeError):
                                    event_type = parameter.annotation
                                if not isinstance(event_type, type):
                                    event_type = None
                        self.event_publisher.add_listener(
                            getattr(instance, name),
                            event_type=event_type,
                            order=annotation.order,
                        )
                    elif _TxEventListener is not None and isinstance(annotation, _TxEventListener):
                        # 事务事件监听器：注册到 TransactionalEventPublisher，按阶段触发
                        event_type = annotation.event_type
                        if event_type is None:
                            parameters = [
                                (parameter_name, parameter)
                                for parameter_name, parameter in inspect.signature(method).parameters.items()
                                if parameter_name != 'self'
                            ]
                            if parameters:
                                parameter_name, parameter = parameters[0]
                                try:
                                    event_type = get_type_hints(method).get(parameter_name)
                                except (NameError, TypeError):
                                    event_type = parameter.annotation
                                if not isinstance(event_type, type):
                                    event_type = None
                        self.tx_event_publisher.add_listener(
                            getattr(instance, name),
                            event_type=event_type,
                            phase=annotation.phase,
                            fallback_execution=annotation.fallback_execution,
                            order=annotation.order,
                        )

    def publish_event(self, event: Any):
        # 普通监听器立即触发；事务监听器按事务阶段触发（无事务时按 fallback_execution 决定）
        self.event_publisher.publish_event(event)
        if self.tx_event_publisher is not None:
            return self.tx_event_publisher.publish_event(event)
        return event

    async def publish_event_async(self, event: Any):
        """Await ordinary event listeners without creating detached tasks.

        Transactional listeners are still registered synchronously because
        their actual execution belongs to the later transaction phase.
        """
        published = await self.event_publisher.publish_event_async(event)
        if self.tx_event_publisher is not None:
            return await self.tx_event_publisher.publish_event_async(published)
        return published

    def get_event_publisher(self) -> ApplicationEventPublisher:
        return self.event_publisher

    def get_bean(self, bean_name: str) -> Any:
        return self.bean_factory.get_bean(bean_name)

    def get_bean_by_type(self, bean_type: Type) -> Any:
        return self.bean_factory.get_bean_by_type(bean_type)

    def contains_bean(self, bean_name: str) -> bool:
        return self.bean_factory.contains_bean(bean_name)

    def get_bean_names(self) -> List[str]:
        return self.bean_factory.get_bean_names()

    def get_config(self) -> Dict[str, Any]:
        return self.config_loader.get_config()

    def get_value(self, key: str, default: Any = None) -> Any:
        return self.config_loader.get_value(key, default)

    def refresh_configuration(self) -> List[str]:
        """重新加载配置并刷新 Web/Actuator 与可刷新 Bean。"""
        self.config_loader.reload()
        refreshed = self.bean_factory.refresh_configuration()
        # Web 运行时配置不属于 Bean 绑定范围；Nacos 热更新后显式重读最终配置，
        # 使 Admin 参数、Actuator 鉴权和请求监控规则即时生效。
        web_context = getattr(self, "web_context", None)
        if web_context is not None:
            refresh_web = getattr(web_context, "refresh_runtime_configuration", None)
            if callable(refresh_web):
                refresh_web()
        try:
            from springbootai.aop.cloud_aop import trigger_config_refresh
            trigger_config_refresh()
        except ImportError:
            pass
        return refreshed

    def destroy(self) -> None:
        self._stop_scheduler()
        try:
            self.bean_factory.destroy_all()
        finally:
            try:
                self.config_loader.close_nacos_config()
            except AttributeError:
                pass
            self.event_publisher.clear()
            if self.tx_event_publisher is not None:
                self.tx_event_publisher.clear()
            if ApplicationContext._current_context is self:
                ApplicationContext._current_context = None
