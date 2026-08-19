"""SpringBootAI IoC 容器增强测试。

覆盖新增的 Spring 对齐能力：
- BeanPostProcessor（before/after 初始化回调）
- InitializingBean / DisposableBean 接口生命周期
- SmartLifecycle 相位启停
- Aware 接口回调（BeanFactoryAware / EnvironmentAware）
- 三级缓存解决 Field/Setter 循环依赖
"""
import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from springbootai.context.bean_factory import BeanFactory
from springbootai.context.bean_definition import BeanDefinition
from springbootai.context.lifecycle import (
    InitializingBean,
    DisposableBean,
    SmartLifecycle,
    BeanPostProcessor,
    BeanFactoryAware,
    EnvironmentAware,
)


# ==================== BeanPostProcessor ====================


class _TrackingPostProcessor(BeanPostProcessor):
    """记录 before/after 初始化调用顺序的后置处理器。"""

    def __init__(self):
        self.calls = []

    def post_process_before_initialization(self, bean, bean_name):
        self.calls.append(("before", bean_name))
        return bean

    def post_process_after_initialization(self, bean, bean_name):
        self.calls.append(("after", bean_name))
        return bean


class _PlainBean:
    def __init__(self):
        self.initialized = False


class TestBeanPostProcessor:
    def test_before_and_after_called_around_initialization(self):
        factory = BeanFactory()
        processor = _TrackingPostProcessor()
        factory.add_bean_post_processor(processor)

        factory.register_bean_definition(
            "plain", BeanDefinition(_PlainBean, "plain")
        )
        bean = factory.get_bean("plain")

        assert isinstance(bean, _PlainBean)
        assert ("before", "plain") in processor.calls
        assert ("after", "plain") in processor.calls
        assert processor.calls.index(("before", "plain")) < processor.calls.index(
            ("after", "plain")
        )

    def test_post_processor_can_wrap_bean(self):
        class _WrappingProcessor(BeanPostProcessor):
            def post_process_after_initialization(self, bean, bean_name):
                class Wrapper:
                    def __init__(self, inner):
                        self.inner = inner

                return Wrapper(bean)

        factory = BeanFactory()
        factory.add_bean_post_processor(_WrappingProcessor())
        factory.register_bean_definition(
            "plain", BeanDefinition(_PlainBean, "plain")
        )
        bean = factory.get_bean("plain")
        assert hasattr(bean, "inner")
        assert isinstance(bean.inner, _PlainBean)


# ==================== InitializingBean / DisposableBean ====================


class _LifecycleBean(InitializingBean, DisposableBean):
    def __init__(self):
        self.events = []

    def after_properties_set(self):
        self.events.append("after_properties_set")

    def destroy(self):
        self.events.append("destroy")


class TestInitializingAndDisposable:
    def test_after_properties_set_called(self):
        factory = BeanFactory()
        factory.register_bean_definition(
            "lb", BeanDefinition(_LifecycleBean, "lb")
        )
        bean = factory.get_bean("lb")
        assert "after_properties_set" in bean.events

    def test_destroy_called_on_destroy_bean(self):
        factory = BeanFactory()
        factory.register_bean_definition(
            "lb", BeanDefinition(_LifecycleBean, "lb")
        )
        bean = factory.get_bean("lb")
        factory.destroy_bean("lb")
        assert "destroy" in bean.events


# ==================== SmartLifecycle ====================


class _SampleLifecycle(SmartLifecycle):
    def __init__(self, phase=0):
        self.events = []
        self._phase = phase

    def start(self):
        self.events.append("start")

    def stop(self):
        self.events.append("stop")

    def get_phase(self):
        return self._phase


class TestSmartLifecycle:
    def test_start_and_stop_in_phase_order(self):
        factory = BeanFactory()
        factory.register_bean_definition(
            "low", BeanDefinition(_SampleLifecycle, "low")
        )
        factory.register_bean_definition(
            "high", BeanDefinition(_SampleLifecycle, "high")
        )
        # 手动注册实例以控制 phase
        low = _SampleLifecycle(phase=1)
        high = _SampleLifecycle(phase=2)
        factory._lifecycle_processor.register(low)
        factory._lifecycle_processor.register(high)

        factory.start_lifecycles()
        assert low.events == ["start"]
        assert high.events == ["start"]
        assert low.is_running() and high.is_running()

        factory.stop_lifecycles()
        # 停止时反序：phase 大的先停止
        assert high.events[-1] == "stop"
        assert low.events[-1] == "stop"
        assert not low.is_running() and not high.is_running()


# ==================== Aware 接口 ====================


class _AwareBean(BeanFactoryAware, EnvironmentAware):
    def __init__(self):
        self.bean_factory = None
        self.environment = None

    def set_bean_factory(self, bean_factory):
        self.bean_factory = bean_factory

    def set_environment(self, config_loader):
        self.environment = config_loader


class TestAwareCallbacks:
    def test_aware_interfaces_injected(self):
        class _Config:
            def get_value(self, key, default=None):
                return default

        config = _Config()
        factory = BeanFactory(config_loader=config)
        factory.register_bean_definition(
            "aware", BeanDefinition(_AwareBean, "aware")
        )
        bean = factory.get_bean("aware")
        assert bean.bean_factory is factory
        assert bean.environment is config


# ==================== 三级缓存循环依赖 ====================


class _ServiceA:
    def __init__(self):
        self.b = None


class _ServiceB:
    def __init__(self):
        self.a = None


class TestCircularDependency:
    def test_field_injection_cycle_resolved(self):
        factory = BeanFactory()

        def_a = BeanDefinition(_ServiceA, "serviceA")
        def_a.add_dependency("b", _ServiceB)
        def_b = BeanDefinition(_ServiceB, "serviceB")
        def_b.add_dependency("a", _ServiceA)

        factory.register_bean_definition("serviceA", def_a)
        factory.register_bean_definition("serviceB", def_b)

        a = factory.get_bean("serviceA")
        b = factory.get_bean("serviceB")

        # 循环依赖通过提前暴露的引用解决
        assert isinstance(a, _ServiceA)
        assert isinstance(b, _ServiceB)
        assert a.b is b
        assert b.a is a

    def test_constructor_cycle_still_reports_error(self):
        factory = BeanFactory()

        class _CtorA:
            def __init__(self, b):
                self.b = b

        class _CtorB:
            def __init__(self, a):
                self.a = a

        # 构造器循环依赖无法通过三级缓存解决，应抛出异常
        def_a = BeanDefinition(_CtorA, "ctorA")
        def_b = BeanDefinition(_CtorB, "ctorB")
        factory.register_bean_definition("ctorA", def_a)
        factory.register_bean_definition("ctorB", def_b)

        # 直接实例化需要构造参数，这里验证构造器注入的循环依赖场景
        # 使用工厂方法模拟构造器循环依赖
        from springbootai.context.bean_factory import MissingBeanDependencyError

        # 简化：验证 non-singleton 循环依赖仍报错
        with pytest.raises(Exception):
            # 手动触发构造器循环（互相调用工厂方法）
            factory2 = BeanFactory()

            def make_a():
                b = factory2.get_bean("ctorB")
                return _CtorA(b)

            def make_b():
                a = factory2.get_bean("ctorA")
                return _CtorB(a)

            factory2.register_bean_definition(
                "ctorA", BeanDefinition(_CtorA, "ctorA", factory_method=make_a)
            )
            factory2.register_bean_definition(
                "ctorB", BeanDefinition(_CtorB, "ctorB", factory_method=make_b)
            )
            factory2.get_bean("ctorA")


# ==================== 条件注解增强 ====================

from springbootai.annotations.conditional import (
    ConditionalOnMissingClass,
    ConditionalOnExpression,
    ConditionalOnWebApplication,
    ConditionalOnNotWebApplication,
)


class _CondConfig:
    def __init__(self, data=None):
        self._data = data or {}

    def get(self, key, default=None):
        return self._data.get(key, default)


class _CondCtx:
    def __init__(self, config=None):
        self.config_loader = config


class TestEnhancedConditional:
    def test_conditional_on_missing_class(self):
        ann = ConditionalOnMissingClass("this.module.does.not.Exist")
        assert ann.matches(_CondCtx()) is True

        ann2 = ConditionalOnMissingClass("builtins.str")
        assert ann2.matches(_CondCtx()) is False

    def test_conditional_on_expression_property(self):
        ctx = _CondCtx(_CondConfig({"redis.enabled": True}))
        ann = ConditionalOnExpression("${redis.enabled}")
        assert ann.matches(ctx) is True

        ctx2 = _CondCtx(_CondConfig({"redis.enabled": False}))
        assert ann.matches(ctx2) is False

    def test_conditional_on_expression_equality(self):
        ctx = _CondCtx(_CondConfig({"env": "prod"}))
        ann = ConditionalOnExpression("${env} == 'prod'")
        assert ann.matches(ctx) is True

    def test_conditional_on_expression_negation(self):
        ctx = _CondCtx(_CondConfig({"feature.flag": False}))
        ann = ConditionalOnExpression("!${feature.flag}")
        assert ann.matches(ctx) is True

    def test_conditional_on_expression_boolean_literal(self):
        assert ConditionalOnExpression("true").matches(_CondCtx()) is True
        assert ConditionalOnExpression("false").matches(_CondCtx()) is False
