from typing import Optional, Type, Any, List, Dict, get_type_hints
import os
import sys
from spring.context.bean_factory import BeanFactory
from spring.context.bean_definition import BeanDefinition
from spring.context.scanner import ComponentScanner
from spring.annotations.core import (
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
from spring.annotations.cloud import EnableFeignClients, FeignClient
from spring.config.config_loader import ConfigLoader, set_global_config_loader
from spring.event import ApplicationEventPublisher
import inspect


class ApplicationContext:
    _current_context: Optional['ApplicationContext'] = None

    def __init__(self, main_class: Type, config_loader: Optional[ConfigLoader] = None):
        self.main_class = main_class
        ApplicationContext._current_context = self
        
        # 确保main_class是一个类
        if not inspect.isclass(main_class):
            # 如果不是类，尝试从__spring_annotations__中获取原始类
            if hasattr(main_class, '__spring_annotations__'):
                for annotation in main_class.__spring_annotations__:
                    if hasattr(annotation, '_original_class'):
                        main_class = annotation._original_class
                        break
        
        main_class_file = inspect.getfile(main_class)
        main_class_dir = os.path.dirname(os.path.abspath(main_class_file))
        context_config_loader = config_loader or ConfigLoader(base_path=main_class_dir)
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
        self.scanner = ComponentScanner(self)
        self._scheduler = None
        self._started = False
        from spring.utils.logger import SpringLogger
        self.logger = SpringLogger()

    @classmethod
    def get_instance(cls) -> Optional['ApplicationContext']:
        """Return the currently active application context, if any."""
        return cls._current_context

    def refresh(self) -> None:
        if self._started:
            return

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
            import traceback
            self.logger.error(f"Failed to refresh application context: {str(e)}")
            self.logger.error(traceback.format_exc())
            raise

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
        from spring.cloud.feign import create_declared_feign_client
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
                config_instance = self.bean_factory.get_bean(bean_name)
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
                            from spring.aop.cloud_aop import apply_cloud_annotations
                            wrapped_method = apply_cloud_annotations(config_instance, method)
                        except ImportError:
                            pass
                        
                        # 对工厂方法应用 comprehensive AOP 注解
                        try:
                            from spring.aop.comprehensive_aop import apply_annotations
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
                instance = self.bean_factory.get_bean(bean_name)
                self._apply_configuration_properties(instance, definition)

    def _apply_configuration_properties(self, instance: Any, definition: BeanDefinition) -> None:
        properties_annotations = definition.annotations.get(ConfigurationProperties._annotation_type)
        if not properties_annotations:
            return

        properties_annotation = properties_annotations[0]
        prefix = properties_annotation.prefix
        config = self.config_loader.get_prefix_config(prefix)

        for key, value in config.items():
            # 同时支持 kebab-case（yml 惯例，如 silver-threshold）与
            # snake_case（Python 惯例，如 silver_threshold）
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
                instance = self.bean_factory.get_bean(bean_name)
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
                                    from spring.annotations.cloud import NacosValue
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
            except Exception:
                # 跳过无法实例化的bean（如配置类等）
                continue

    def _register_scheduled_tasks(self) -> None:
        from spring.scheduling.scheduler import Scheduler
        from spring.annotations.core import Scheduled
        
        self._scheduler = Scheduler()
        
        for bean_name in self.bean_factory.get_bean_names():
            definition = self.bean_factory.get_bean_definition(bean_name)
            if not definition:
                continue
            
            instance = self.bean_factory.get_bean(bean_name)
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
        for bean_name in self.bean_factory.get_bean_names():
            instance = self.bean_factory.get_bean(bean_name)
            for name, method in inspect.getmembers(instance.__class__):
                if name.startswith('_') or not inspect.isfunction(method):
                    continue
                for annotation in getattr(method, '__spring_annotations__', []):
                    if not isinstance(annotation, EventListener):
                        continue
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

    def publish_event(self, event: Any):
        return self.event_publisher.publish_event(event)

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
        """Reload ``application.yml`` and rebind refreshable Beans."""
        self.config_loader.reload()
        refreshed = self.bean_factory.refresh_configuration()
        try:
            from spring.aop.cloud_aop import trigger_config_refresh
            trigger_config_refresh()
        except ImportError:
            pass
        return refreshed

    def destroy(self) -> None:
        self.bean_factory.destroy_all()
        self.event_publisher.clear()
        if ApplicationContext._current_context is self:
            ApplicationContext._current_context = None
