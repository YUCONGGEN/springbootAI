"""DI/配置/事件完整测试 - 覆盖 ConfigLoader、BeanRegistry、ApplicationEventPublisher、retry。"""

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import tests._test_helpers  # noqa: F401  安装模块mock

from springbootai.config.config_loader import ConfigLoader, ConfigurationError
from springbootai.context.registry import BeanRegistry
from springbootai.event.publisher import ApplicationEventPublisher
from springbootai.annotations.core import ApplicationEvent, EventListener, get_spring_annotations
from springbootai.retry.retry_decorator import retry
from springbootai.retry.retry_annotations import Backoff


# ==================== ConfigLoader 测试 ====================

class TestConfigLoader:
    def test_loads_application_yml(self):
        loader = ConfigLoader(config_path="application.yml")
        # yaml.safe_load is mocked to return {}, but _override_with_env sets defaults
        config = loader.get_config()
        assert isinstance(config, dict)

    def test_get_server_port(self):
        loader = ConfigLoader(config_path="application.yml")
        # Default port from _override_with_env
        port = loader.get("server.port")
        assert port == 8080

    def test_get_server_host(self):
        loader = ConfigLoader(config_path="application.yml")
        assert loader.get("server.host") == "0.0.0.0"

    def test_get_nonexistent_with_default(self):
        loader = ConfigLoader(config_path="application.yml")
        assert loader.get("nonexistent.key", default="x") == "x"

    def test_get_nonexistent_without_default(self):
        loader = ConfigLoader(config_path="application.yml")
        assert loader.get("nonexistent.key") is None

    def test_get_active_profile(self):
        loader = ConfigLoader(config_path="application.yml")
        profile = loader.get_active_profile()
        # Profile comes from SPRING_PROFILES_ACTIVE env or defaults to "default"
        assert isinstance(profile, str)

    def test_get_value_alias(self):
        loader = ConfigLoader(config_path="application.yml")
        assert loader.get_value("server.port") == 8080

    def test_get_config_returns_dict(self):
        loader = ConfigLoader(config_path="application.yml")
        config = loader.get_config()
        assert isinstance(config, dict)
        assert "server" in config

    def test_get_prefix_config(self):
        loader = ConfigLoader(config_path="application.yml")
        server_config = loader.get_prefix_config("server")
        assert isinstance(server_config, dict)
        assert "port" in server_config

    def test_resolve_value_expression_simple(self):
        loader = ConfigLoader(config_path="application.yml")
        # server.port exists in config → should return it
        assert loader.resolve_value_expression("server.port") == 8080

    def test_resolve_value_expression_spring_style(self):
        loader = ConfigLoader(config_path="application.yml")
        # ${server.port:9090} → key exists, returns config value
        assert loader.resolve_value_expression("${server.port:9090}") == 8080

    def test_resolve_value_expression_with_default(self):
        loader = ConfigLoader(config_path="application.yml")
        # ${nonexistent.key:default_val} → key missing, returns expression default
        result = loader.resolve_value_expression("${nonexistent.key:default_val}")
        assert result == "default_val"

    def test_resolve_value_expression_non_string(self):
        loader = ConfigLoader(config_path="application.yml")
        assert loader.resolve_value_expression(42) == 42

    def test_resolve_value_expression_fallback(self):
        loader = ConfigLoader(config_path="application.yml")
        # Nonexistent key without expression default → returns caller default
        assert loader.resolve_value_expression("nonexistent.key", default="fb") == "fb"

    def test_nonexistent_config_path(self):
        # ConfigLoader with nonexistent path should not raise; uses defaults
        loader = ConfigLoader(config_path="/nonexistent/path.yml")
        assert loader.get("server.port") == 8080


class TestConfigurationError:
    def test_invalid_jwt_algorithm_raises(self):
        loader = ConfigLoader(config_path="application.yml")
        loader._config["jwt"]["algorithm"] = "RS256"
        with pytest.raises(ConfigurationError):
            loader._validate_config()

    def test_cors_credentials_with_wildcard_raises(self):
        loader = ConfigLoader(config_path="application.yml")
        loader._config["server"]["cors"]["allow_credentials"] = True
        loader._config["server"]["cors"]["allow_origins"] = ["*"]
        with pytest.raises(ConfigurationError):
            loader._validate_config()

    def test_configuration_error_is_value_error(self):
        assert issubclass(ConfigurationError, ValueError)

    # ===== 生产环境 AI api-key 强制校验（safe-by-default）=====

    @staticmethod
    def _make_prod_loader(monkeypatch, ai_config):
        """构造一个生产 profile 下的 ConfigLoader（绕过 init 时的 prod 校验）。

        1. 先在非 prod profile 下创建实例（init 通过校验）；
        2. 再切换 SPRING_PROFILES_ACTIVE=prod 并替换 _config；
        3. 调用方负责调用 _validate_config()。
        """
        monkeypatch.delenv("SPRING_PROFILES_ACTIVE", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        loader = ConfigLoader(config_path="application.yml")
        monkeypatch.setenv("SPRING_PROFILES_ACTIVE", "prod")
        loader._config = {
            "spring": {"profiles": {"active": "prod"}, "ai": ai_config},
            "jwt": {"secret_key": "x" * 48, "algorithm": "HS256"},
        }
        return loader

    def test_prod_profile_missing_ai_api_key_raises(self, monkeypatch):
        """生产 profile + AI 启用 + 缺 api-key → ConfigurationError"""
        loader = self._make_prod_loader(monkeypatch, {
            "default-provider": "openai",
            "openai": {"api-key": ""},
        })
        with pytest.raises(ConfigurationError, match="api-key"):
            loader._validate_config()

    def test_prod_profile_ai_with_api_key_passes(self, monkeypatch):
        """生产 profile + AI 启用 + 配置 api-key → 通过"""
        monkeypatch.delenv("AI_ALLOW_FAKE", raising=False)
        loader = self._make_prod_loader(monkeypatch, {
            "default-provider": "openai",
            "openai": {"api-key": "unit-test-placeholder"},
        })
        loader._validate_config()
        # 生产 profile 必须强制 AI_ALLOW_FAKE=false（防止后续 autoconfig 静默降级）
        assert os.environ.get("AI_ALLOW_FAKE") == "false"

    def test_prod_profile_ollama_without_api_key_passes(self, monkeypatch):
        """生产 profile + ollama provider（本地部署无需 api-key）→ 通过"""
        loader = self._make_prod_loader(monkeypatch, {
            "default-provider": "ollama",
            "ollama": {"base-url": "http://ollama:11434"},
        })
        # ollama 无需 api-key，不应抛异常
        loader._validate_config()

    def test_prod_profile_ai_disabled_passes(self, monkeypatch):
        """生产 profile + AI 显式禁用 → 不校验 api-key"""
        loader = self._make_prod_loader(monkeypatch, {
            "enabled": False,
            "default-provider": "openai",
            "openai": {"api-key": ""},
        })
        loader._validate_config()

    def test_non_prod_profile_skips_ai_validation(self, monkeypatch):
        """非生产 profile + 缺 api-key → 不抛异常（开发环境允许 Fake 降级）"""
        monkeypatch.delenv("SPRING_PROFILES_ACTIVE", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        loader = ConfigLoader(config_path="application.yml")
        loader._config = {
            "spring": {"profiles": {"active": "dev"}, "ai": {
                "default-provider": "openai",
                "openai": {"api-key": ""},
            }},
            "jwt": {"secret_key": "x" * 48, "algorithm": "HS256"},
        }
        # 开发环境不强制 AI 校验
        loader._validate_config()

    def test_prod_profile_deepseek_missing_key_raises(self, monkeypatch):
        """生产 profile + DeepSeek provider + 缺 api-key → ConfigurationError（含环境变量提示）"""
        loader = self._make_prod_loader(monkeypatch, {
            "default-provider": "deepseek",
            "deepseek": {"api-key": ""},
        })
        with pytest.raises(ConfigurationError, match="DEEPSEEK_API_KEY"):
            loader._validate_config()


# ==================== BeanRegistry 测试 ====================

class TestBeanRegistry:
    def setup_method(self):
        # Reset singleton before each test
        BeanRegistry._instance = None
        BeanRegistry._initialized = False
        self.registry = BeanRegistry()

    def teardown_method(self):
        self.registry.clear()
        BeanRegistry._instance = None
        BeanRegistry._initialized = False

    def test_singleton(self):
        r1 = BeanRegistry()
        r2 = BeanRegistry()
        assert r1 is r2

    def test_register_and_get(self):
        bean = {"name": "test"}
        self.registry.register("mybean", bean)
        assert self.registry.get("mybean") is bean

    def test_contains(self):
        self.registry.register("x", 42)
        assert self.registry.contains("x") is True
        assert self.registry.contains("y") is False

    def test_get_nonexistent_returns_none(self):
        assert self.registry.get("nonexistent") is None

    def test_get_by_type(self):
        class MyService:
            pass

        svc = MyService()
        self.registry.register("svc", svc)
        assert self.registry.get_by_type(MyService) is svc

    def test_contains_type(self):
        class Svc:
            pass

        svc = Svc()
        self.registry.register("s", svc)
        assert self.registry.contains_type(Svc) is True

    def test_contains_type_false(self):
        class Svc:
            pass

        assert self.registry.contains_type(Svc) is False

    def test_unregister(self):
        self.registry.register("x", 42)
        self.registry.unregister("x")
        assert self.registry.contains("x") is False

    def test_clear(self):
        self.registry.register("a", 1)
        self.registry.register("b", 2)
        self.registry.clear()
        assert self.registry.get_count() == 0

    def test_get_all(self):
        self.registry.register("a", 1)
        self.registry.register("b", 2)
        all_beans = self.registry.get_all()
        assert all_beans == {"a": 1, "b": 2}

    def test_get_names(self):
        self.registry.register("a", 1)
        self.registry.register("b", 2)
        names = self.registry.get_names()
        assert set(names) == {"a", "b"}

    def test_get_count(self):
        self.registry.register("a", 1)
        self.registry.register("b", 2)
        assert self.registry.get_count() == 2

    def test_get_by_type_isinstance_fallback(self):
        class Base:
            pass

        class Derived(Base):
            pass

        d = Derived()
        self.registry.register("d", d)
        # contains_type checks exact type, so Base is not registered
        assert self.registry.contains_type(Base) is False
        # But get_by_type falls back to isinstance check
        assert self.registry.get_by_type(Base) is d


# ==================== ApplicationEventPublisher 测试 ====================

class TestApplicationEventPublisher:
    def test_create_publisher(self):
        publisher = ApplicationEventPublisher()
        assert publisher.listener_count() == 0

    def test_add_listener(self):
        publisher = ApplicationEventPublisher()
        publisher.add_listener(lambda event: None)
        assert publisher.listener_count() == 1

    def test_publish_event_wraps_non_application_event(self):
        publisher = ApplicationEventPublisher()
        received = []

        def listener(event):
            received.append(event)

        publisher.add_listener(listener)
        event = publisher.publish_event("hello")
        assert isinstance(event, ApplicationEvent)
        assert event.source == "hello"
        assert len(received) == 1
        assert received[0].source == "hello"

    def test_publish_application_event(self):
        publisher = ApplicationEventPublisher()
        received = []

        def listener(event):
            received.append(event)

        publisher.add_listener(listener)
        evt = ApplicationEvent("source1")
        result = publisher.publish_event(evt)
        assert result is evt
        assert len(received) == 1

    def test_remove_listener(self):
        publisher = ApplicationEventPublisher()

        def listener(event):
            pass

        publisher.add_listener(listener)
        assert publisher.listener_count() == 1
        publisher.remove_listener(listener)
        assert publisher.listener_count() == 0

    def test_clear(self):
        publisher = ApplicationEventPublisher()
        publisher.add_listener(lambda e: None)
        publisher.add_listener(lambda e: None)
        publisher.clear()
        assert publisher.listener_count() == 0

    def test_listener_count(self):
        publisher = ApplicationEventPublisher()
        assert publisher.listener_count() == 0
        publisher.add_listener(lambda e: None)
        assert publisher.listener_count() == 1
        publisher.add_listener(lambda e: None)
        assert publisher.listener_count() == 2

    def test_event_type_filter(self):
        class MyEvent(ApplicationEvent):
            pass

        class OtherEvent(ApplicationEvent):
            pass

        publisher = ApplicationEventPublisher()
        received = []

        def listener(event):
            received.append(event)

        publisher.add_listener(listener, event_type=MyEvent)
        publisher.publish_event(OtherEvent("other"))
        assert len(received) == 0  # OtherEvent doesn't match MyEvent
        publisher.publish_event(MyEvent("mine"))
        assert len(received) == 1

    def test_order_respected(self):
        publisher = ApplicationEventPublisher()
        order = []

        def first(event):
            order.append("first")

        def second(event):
            order.append("second")

        publisher.add_listener(first, order=2)
        publisher.add_listener(second, order=1)
        publisher.publish_event("test")
        # order=1 (second) runs before order=2 (first)
        assert order == ["second", "first"]

    def test_no_listeners(self):
        publisher = ApplicationEventPublisher()
        event = publisher.publish_event("test")
        assert event.source == "test"


class TestEventListenerAnnotation:
    def test_with_event_type_and_order(self):
        class MyEvent(ApplicationEvent):
            pass

        ann = EventListener(MyEvent, order=2)
        assert ann.event_type is MyEvent
        assert ann.order == 2

    def test_default_order(self):
        class MyEvent(ApplicationEvent):
            pass

        ann = EventListener(MyEvent)
        assert ann.order == 0

    def test_decorates(self):
        class MyEvent(ApplicationEvent):
            pass

        @EventListener(MyEvent, order=1)
        def listener(event):
            pass

        anns = get_spring_annotations(listener)
        assert len(anns) == 1
        assert isinstance(anns[0], EventListener)
        assert anns[0].event_type is MyEvent


# ==================== Retry 装饰器测试 ====================

class TestRetryDecorator:
    def test_success_no_retry(self):
        call_count = 0

        @retry(max_retries=3, delay=0, exceptions=(ValueError,))
        def fn():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert fn() == "ok"
        assert call_count == 1

    def test_fail_then_succeed(self):
        call_count = 0

        @retry(max_retries=3, delay=0, exceptions=(ValueError,))
        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("fail")
            return "recovered"

        assert fn() == "recovered"
        assert call_count == 2

    def test_exhausted_raises_last_exception(self):
        call_count = 0

        @retry(max_retries=3, delay=0, exceptions=(ValueError,))
        def fn():
            nonlocal call_count
            call_count += 1
            raise ValueError(f"attempt {call_count}")

        with pytest.raises(ValueError) as exc_info:
            fn()
        assert "attempt 3" in str(exc_info.value)
        assert call_count == 3

    def test_non_matching_exception_not_retried(self):
        call_count = 0

        @retry(max_retries=3, delay=0, exceptions=(ValueError,))
        def fn():
            nonlocal call_count
            call_count += 1
            raise KeyError("not retried")

        with pytest.raises(KeyError):
            fn()
        assert call_count == 1

    def test_preserves_function_name(self):
        @retry(max_retries=2, delay=0)
        def my_function():
            return "ok"

        assert my_function.__name__ == "my_function"

    def test_default_exceptions_all_exceptions(self):
        call_count = 0

        @retry(max_retries=2, delay=0)
        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("retry me")
            return "ok"

        assert fn() == "ok"
        assert call_count == 2


class TestBackoff:
    def test_defaults(self):
        b = Backoff()
        assert b.delay == 1000
        assert b.max_delay == 10000
        assert b.multiplier == 2.0
        assert b.random_factor == 0.1

    def test_custom(self):
        b = Backoff(delay=100, max_delay=5000, multiplier=2.0, random_factor=0.1)
        assert b.delay == 100
        assert b.max_delay == 5000
        assert b.multiplier == 2.0
        assert b.random_factor == 0.1

    def test_zero_random_factor(self):
        b = Backoff(delay=100, max_delay=5000, multiplier=2.0, random_factor=0.0)
        assert b.random_factor == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
