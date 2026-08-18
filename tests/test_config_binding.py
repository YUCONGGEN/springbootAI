"""P1-5 配置松散绑定与校验测试。

覆盖 ``springbootai.config.binding`` 模块：
- 松散绑定（kebab-case / camelCase / snake_case / SCREAMING_SNAKE 等价匹配）
- 嵌套绑定（``@NestedConfigurationProperties`` 递归绑定子字典）
- 类型强转（int/float/bool/str）
- ``@Validated`` + BeanValidator 校验（违反约束抛 ``ValidationError``）
- ApplicationContext 集成（``@ConfigurationProperties`` + ``@Validated`` 端到端）

复用既有范式：``@NestedConfigurationProperties`` 继承 ``SpringAnnotation``，
校验复用 ``springbootai.validation.BeanValidator``，不重复造轮子。
"""
import os
import tempfile

import pytest

from springbootai.annotations.core import (
    Component, ConfigurationProperties, Validated,
)
from springbootai.config.binding import (
    NestedConfigurationProperties,
    ConfigurationPropertiesBinder,
    validate_configuration_properties,
    _normalize,
)
from springbootai.validation import (
    BeanValidator, NotBlank, Min, Max, ValidationError,
)


# ==================== 松散绑定 ====================

class TestLooseBinding:
    def test_normalize_equivalence(self):
        assert _normalize("max-connections") == _normalize("maxConnections")
        assert _normalize("max_connections") == _normalize("maxConnections")
        assert _normalize("MAX_CONNECTIONS") == _normalize("max-connections")
        assert _normalize("serverPort") == "serverport"

    def test_kebab_case_binds_to_snake_attr(self):
        class ServerProps:
            def __init__(self):
                self.max_connections = 0
                self.server_port = 0

        props = ServerProps()
        ConfigurationPropertiesBinder.bind(props, {
            "max-connections": 100,
            "server-port": 8080,
        })
        assert props.max_connections == 100
        assert props.server_port == 8080

    def test_camel_case_binds_to_snake_attr(self):
        class Props:
            def __init__(self):
                self.max_connections = 0

        props = Props()
        ConfigurationPropertiesBinder.bind(props, {"maxConnections": 50})
        assert props.max_connections == 50

    def test_snake_case_binds_to_camel_attr(self):
        class Props:
            def __init__(self):
                self.maxConnections = 0

        props = Props()
        ConfigurationPropertiesBinder.bind(props, {"max_connections": 30})
        assert props.maxConnections == 30

    def test_screaming_snake_binds(self):
        class Props:
            def __init__(self):
                self.pool_size = 0

        props = Props()
        ConfigurationPropertiesBinder.bind(props, {"POOL_SIZE": 8})
        assert props.pool_size == 8

    def test_unmatched_key_skipped(self):
        class Props:
            def __init__(self):
                self.known = 0

        props = Props()
        ConfigurationPropertiesBinder.bind(props, {"known": 1, "unknown-key": 99})
        assert props.known == 1
        assert not hasattr(props, "unknown_key")

    def test_non_dict_config_returns_unchanged(self):
        class Props:
            def __init__(self):
                self.x = 0
        props = Props()
        # 非字典配置直接返回，不报错
        ConfigurationPropertiesBinder.bind(props, "not-a-dict")
        assert props.x == 0


# ==================== 类型强转 ====================

class TestTypeCoercion:
    def test_int_coercion(self):
        class Props:
            port: int = 0

        props = Props()
        ConfigurationPropertiesBinder.bind(props, {"port": "9090"})
        assert props.port == 9090 and isinstance(props.port, int)

    def test_float_coercion(self):
        class Props:
            threshold: float = 0.0

        props = Props()
        ConfigurationPropertiesBinder.bind(props, {"threshold": "0.75"})
        assert props.threshold == 0.75 and isinstance(props.threshold, float)

    def test_bool_coercion_from_string(self):
        class Props:
            enabled: bool = False

        props = Props()
        ConfigurationPropertiesBinder.bind(props, {"enabled": "true"})
        assert props.enabled is True

    def test_bool_already_bool_unchanged(self):
        class Props:
            enabled: bool = False

        props = Props()
        ConfigurationPropertiesBinder.bind(props, {"enabled": False})
        assert props.enabled is False

    def test_coercion_failure_keeps_original(self):
        class Props:
            port: int = 0

        props = Props()
        ConfigurationPropertiesBinder.bind(props, {"port": "not-a-number"})
        # 强转失败保留原值
        assert props.port == "not-a-number"

    def test_list_value_preserved(self):
        class Props:
            hosts: list = []

        props = Props()
        ConfigurationPropertiesBinder.bind(props, {"hosts": ["a", "b", "c"]})
        assert props.hosts == ["a", "b", "c"]


# ==================== 嵌套绑定 ====================

class TestNestedBinding:
    def test_nested_configuration_properties_recursive_bind(self):
        @NestedConfigurationProperties
        class DatabaseProps:
            url: str = ""
            max_pool_size: int = 0

        @ConfigurationProperties("app")
        class AppProps:
            name: str = ""
            database: DatabaseProps = None

        props = AppProps()
        ConfigurationPropertiesBinder.bind(props, {
            "name": "demo",
            "database": {
                "url": "sqlite:///x.db",
                "max-pool-size": 20,
            },
        })
        assert props.name == "demo"
        assert isinstance(props.database, DatabaseProps)
        assert props.database.url == "sqlite:///x.db"
        assert props.database.max_pool_size == 20

    def test_nested_dict_without_annotation_assigns_plain_dict(self):
        class Props:
            section: dict = None

        props = Props()
        # 属性类型为 dict，非 @NestedConfigurationProperties → 直接赋值字典
        ConfigurationPropertiesBinder.bind(props, {"section": {"a": 1}})
        assert props.section == {"a": 1}

    def test_deeply_nested_binding(self):
        @NestedConfigurationProperties
        class Level3:
            flag: bool = False

        @NestedConfigurationProperties
        class Level2:
            name: str = ""
            child: Level3 = None

        class Level1:
            l2: Level2 = None

        props = Level1()
        ConfigurationPropertiesBinder.bind(props, {
            "l2": {
                "name": "mid",
                "child": {"flag": "true"},
            },
        })
        assert isinstance(props.l2, Level2)
        assert props.l2.name == "mid"
        assert isinstance(props.l2.child, Level3)
        assert props.l2.child.flag is True


# ==================== @Validated 校验 ====================

class TestValidatedConfiguration:
    def test_validate_passes_when_constraints_satisfied(self):
        @Validated
        class Props:
            name = NotBlank()
            port = Min(1)
            port_max = Max(65535)

            def __init__(self):
                self.name = "ok"
                self.port = 8080
                self.port_max = 8080

        props = Props()
        # 不抛错即通过
        validate_configuration_properties(props)

    def test_validate_raises_on_violation(self):
        @Validated
        class Props:
            name = NotBlank(message="名称不能为空")
            port = Min(1, message="端口必须>=1")

            def __init__(self):
                self.name = ""
                self.port = 0

        props = Props()
        with pytest.raises(ValidationError):
            validate_configuration_properties(props)

    def test_validate_skipped_without_validated_annotation(self):
        class Props:
            name = NotBlank()

            def __init__(self):
                self.name = ""  # 违反但不标注 @Validated → 不校验

        props = Props()
        # 不抛错
        validate_configuration_properties(props)

    def test_bean_validator_directly_on_config(self):
        @Validated
        class Props:
            host = NotBlank()
            port = Min(1)

            def __init__(self):
                self.host = "localhost"
                self.port = 8080

        violations = BeanValidator.validate(Props())
        assert violations == []


# ==================== ApplicationContext 端到端集成 ====================

class _App:
    pass


class TestApplicationContextIntegration:
    def _write_config(self, content):
        fd, path = tempfile.mkstemp(suffix=".yml", prefix="app_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_configuration_properties_loose_and_nested_binding_via_context(self, monkeypatch):
        from springbootai.context.application_context import ApplicationContext
        from springbootai.annotations.core import SpringBootApplication

        config_path = self._write_config(
            "my-app:\n"
            "  app-name: demo-app\n"
            "  max-connections: 32\n"
            "  database:\n"
            "    url: sqlite:///mem.db\n"
            "    pool-size: 10\n"
        )

        @NestedConfigurationProperties
        class DbProps:
            url: str = ""
            pool_size: int = 0

        @SpringBootApplication
        class App:
            pass

        @ConfigurationProperties("my-app")
        @Component
        class MyAppProps:
            app_name: str = ""
            max_connections: int = 0
            database: DbProps = None

        # 指向临时配置文件构造 ConfigLoader
        from springbootai.config.config_loader import ConfigLoader
        loader = ConfigLoader(config_path=config_path)
        ctx = ApplicationContext(App, config_loader=loader)
        # 手动注册配置属性 Bean 并触发绑定
        from springbootai.context.bean_definition import BeanDefinition
        definition = BeanDefinition(bean_class=MyAppProps, bean_name="my_app_props")
        definition.add_annotation(ConfigurationProperties("my-app"))
        ctx.bean_factory.register_bean_definition("my_app_props", definition)
        ctx._apply_configuration_properties(ctx.bean_factory.get_bean("my_app_props"), definition)

        bean = ctx.bean_factory.get_bean("my_app_props")
        assert bean.app_name == "demo-app"
        assert bean.max_connections == 32
        assert isinstance(bean.database, DbProps)
        assert bean.database.url == "sqlite:///mem.db"
        assert bean.database.pool_size == 10
        ctx.destroy()
        os.unlink(config_path)

    def test_validated_configuration_raises_on_invalid_via_context(self, monkeypatch):
        from springbootai.context.application_context import ApplicationContext
        from springbootai.annotations.core import SpringBootApplication

        config_path = self._write_config(
            "bad-app:\n"
            "  name: ''\n"   # 违反 NotBlank
            "  port: 0\n"    # 违反 Min(1)
        )

        @SpringBootApplication
        class App:
            pass

        @Validated
        @ConfigurationProperties("bad-app")
        @Component
        class BadAppProps:
            name = NotBlank(message="名称不能为空")
            port = Min(1, message="端口必须>=1")

            def __init__(self):
                self.name = ""
                self.port = 0

        from springbootai.config.config_loader import ConfigLoader
        loader = ConfigLoader(config_path=config_path)
        ctx = ApplicationContext(App, config_loader=loader)
        from springbootai.context.bean_definition import BeanDefinition
        definition = BeanDefinition(bean_class=BadAppProps, bean_name="bad_app_props")
        definition.add_annotation(ConfigurationProperties("bad-app"))
        definition.add_annotation(Validated())
        ctx.bean_factory.register_bean_definition("bad_app_props", definition)

        with pytest.raises(ValidationError):
            instance = ctx.bean_factory.get_bean("bad_app_props")
            ctx._apply_configuration_properties(instance, definition)
        ctx.destroy()
        os.unlink(config_path)
