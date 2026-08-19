"""
Spring风格Bean生命周期接口与BeanPostProcessor扩展点。

对齐 Spring 框架:
- InitializingBean: afterPropertiesSet() 在属性注入完成后调用
- DisposableBean: destroy() 在容器关闭时调用
- BeanPostProcessor: postProcessBeforeInitialization/postProcessAfterInitialization
- BeanFactoryPostProcessor: postProcessBeanFactory 在Bean定义加载后、实例化前调用
- SmartLifecycle: 可启停的生命周期组件（含相位控制）
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List
import threading


# ==================== 生命周期接口 ====================


class InitializingBean(ABC):
    """Bean属性注入完成后调用，对齐 Spring InitializingBean。

    与 @PostConstruct 的区别:
    - @PostConstruct 是注解驱动，在 afterPropertiesSet() 之前执行
    - InitializingBean 是接口驱动，类型安全，适合框架内部组件
    """

    @abstractmethod
    def after_properties_set(self) -> None:
        """属性注入完成后、初始化完成前调用。"""


class DisposableBean(ABC):
    """容器关闭时调用，对齐 Spring DisposableBean。

    与 @PreDestroy 的区别:
    - @PreDestroy 是注解驱动，在 destroy() 之前执行
    - DisposableBean 是接口驱动，类型安全
    """

    @abstractmethod
    def destroy(self) -> None:
        """容器销毁Bean时调用。"""


class SmartLifecycle(ABC):
    """可启停的生命周期组件，支持相位控制，对齐 Spring SmartLifecycle。

    用于需要在应用启动后自动启动、关闭前优雅停止的组件，如：
    - 消息监听器容器
    - 定时任务调度器
    - MCP Server
    - WebSocket Broker
    """

    _lifecycle_lock = threading.Lock()
    _running = False

    def is_running(self) -> bool:
        """组件是否正在运行。"""
        return self._running

    @abstractmethod
    def start(self) -> None:
        """启动组件。"""

    @abstractmethod
    def stop(self) -> None:
        """停止组件。"""

    def is_auto_startup(self) -> bool:
        """是否在容器刷新后自动启动。默认True。"""
        return True

    def get_phase(self) -> int:
        """启动/停止相位。相位小的先启动，停止时反序。默认0。"""
        return 0

    def stop_with_callback(self, callback) -> None:
        """异步停止，完成后调用callback。默认同步调用stop()。"""
        try:
            self.stop()
        finally:
            callback()


# ==================== BeanPostProcessor ====================


class BeanPostProcessor(ABC):
    """Bean后置处理器，对齐 Spring BeanPostProcessor。

    在Bean初始化前后对新创建的Bean实例进行自定义修改。
    典型用途：
    - 检查标记接口（如ApplicationContextAware）
    - 代理包装（AOP已内置，此为扩展点）
    - 字段注入自定义逻辑
    - 自定义初始化日志

    执行顺序：postProcessBeforeInitialization -> @PostConstruct ->
              InitializingBean.afterPropertiesSet -> initMethod ->
              postProcessAfterInitialization -> Bean就绪
    """

    def post_process_before_initialization(self, bean: Any, bean_name: str) -> Any:
        """在 @PostConstruct / InitializingBean / initMethod 之前应用。

        Returns:
            原始Bean或包装后的Bean。返回None表示不修改。
        """
        return bean

    def post_process_after_initialization(self, bean: Any, bean_name: str) -> Any:
        """在初始化完成后应用（可返回代理对象）。

        Returns:
            原始Bean或代理。返回None表示不修改。
        """
        return bean


# ==================== BeanFactoryPostProcessor ====================


class BeanFactoryPostProcessor(ABC):
    """BeanFactory后置处理器，对齐 Spring BeanFactoryPostProcessor。

    在所有Bean定义加载完成后、任何Bean实例化之前调用。
    典型用途：
    - 修改Bean定义（如修改属性值、替换实现类）
    - 注册额外的Bean定义
    - 配置属性覆盖
    """

    @abstractmethod
    def post_process_bean_factory(self, bean_factory) -> None:
        """在Bean实例化前修改BeanFactory中的Bean定义。

        Args:
            bean_factory: BeanFactory实例，可调用 register_bean_definition() 修改
        """


# ==================== Aware接口 ====================


class Aware:
    """标记接口：实现此接口的Bean会在初始化时收到容器回调。"""


class ApplicationContextAware(Aware):
    """注入ApplicationContext，对齐 Spring ApplicationContextAware。"""

    @abstractmethod
    def set_application_context(self, application_context) -> None:
        pass


class BeanFactoryAware(Aware):
    """注入BeanFactory，对齐 Spring BeanFactoryAware。"""

    @abstractmethod
    def set_bean_factory(self, bean_factory) -> None:
        pass


class EnvironmentAware(Aware):
    """注入配置/环境，对齐 Spring EnvironmentAware。"""

    @abstractmethod
    def set_environment(self, config_loader) -> None:
        pass


# ==================== 生命周期管理器 ====================


class LifecycleProcessor:
    """管理SmartLifecycle组件的启停相位顺序。"""

    def __init__(self):
        self._lifecycles: List[SmartLifecycle] = []
        self._lock = threading.Lock()

    def register(self, lifecycle: SmartLifecycle) -> None:
        with self._lock:
            if lifecycle not in self._lifecycles:
                self._lifecycles.append(lifecycle)

    def start(self) -> None:
        """按phase升序启动所有autoStartup组件。"""
        with self._lock:
            sorted_lifecycles = sorted(
                [l for l in self._lifecycles if l.is_auto_startup() and not l.is_running()],
                key=lambda x: x.get_phase(),
            )
        for lifecycle in sorted_lifecycles:
            try:
                lifecycle.start()
                lifecycle._running = True
            except Exception:
                import logging
                logging.getLogger("Spring.Lifecycle").exception(
                    "Failed to start lifecycle %s", type(lifecycle).__name__
                )

    def stop(self) -> None:
        """按phase降序停止所有运行中的组件。"""
        with self._lock:
            sorted_lifecycles = sorted(
                [l for l in self._lifecycles if l.is_running()],
                key=lambda x: x.get_phase(),
                reverse=True,
            )
        for lifecycle in sorted_lifecycles:
            try:
                lifecycle.stop()
                lifecycle._running = False
            except Exception:
                import logging
                logging.getLogger("Spring.Lifecycle").exception(
                    "Failed to stop lifecycle %s", type(lifecycle).__name__
                )

    def is_running(self) -> bool:
        return any(l.is_running() for l in self._lifecycles)


__all__ = [
    "InitializingBean",
    "DisposableBean",
    "SmartLifecycle",
    "BeanPostProcessor",
    "BeanFactoryPostProcessor",
    "Aware",
    "ApplicationContextAware",
    "BeanFactoryAware",
    "EnvironmentAware",
    "LifecycleProcessor",
]
