"""核心注解完整测试 - 覆盖 SpringAnnotation 基础设施及核心组件注解。"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import tests._test_helpers  # noqa: F401  安装模块mock

from spring.annotations.core import (
    SpringBootApplication, ComponentScan, Service, Component, Repository,
    Autowired, Qualifier, Configuration, Scope, Bean, Value,
    ConfigurationProperties, Primary, Profile, Lazy, PostConstruct, PreDestroy,
    get_spring_annotations,
)


class TestSpringBootApplication:
    def test_with_packages(self):
        ann = SpringBootApplication(["com.app"])
        assert ann.scan_base_packages == ["com.app"]

    def test_default_none(self):
        ann = SpringBootApplication()
        assert ann.scan_base_packages is None

    def test_decorates_class(self):
        @SpringBootApplication(["com.demo"])
        class App:
            pass

        attached = get_spring_annotations(App)
        assert len(attached) == 1
        assert isinstance(attached[0], SpringBootApplication)
        assert attached[0].scan_base_packages == ["com.demo"]


class TestComponentScan:
    def test_with_packages(self):
        ann = ComponentScan(["com.demo.service"])
        assert ann.base_packages == ["com.demo.service"]

    def test_default_none(self):
        ann = ComponentScan()
        assert ann.base_packages is None


class TestComponentAnnotations:
    def test_service_value(self):
        ann = Service("userService")
        assert ann.value == "userService"

    def test_service_default_empty(self):
        ann = Service()
        assert ann.value == ""

    def test_component_value(self):
        ann = Component("repo")
        assert ann.value == "repo"

    def test_repository_value(self):
        ann = Repository("userRepo")
        assert ann.value == "userRepo"

    def test_component_attaches_annotation(self):
        @Component("bean1")
        class Bean1:
            pass

        attached = get_spring_annotations(Bean1)
        assert len(attached) == 1
        assert isinstance(attached[0], Component)
        assert attached[0].value == "bean1"


class TestAutowired:
    def test_default_required(self):
        ann = Autowired()
        assert ann.required is True

    def test_required_false(self):
        ann = Autowired(required=False)
        assert ann.required is False


class TestQualifier:
    def test_value(self):
        ann = Qualifier("primary")
        assert ann.value == "primary"


class TestConfiguration:
    def test_default_proxy_bean_methods(self):
        ann = Configuration()
        assert ann.proxyBeanMethods is True

    def test_proxy_bean_methods_false_snake(self):
        ann = Configuration(proxy_bean_methods=False)
        assert ann.proxyBeanMethods is False

    def test_proxy_bean_methods_camel_param(self):
        ann = Configuration(proxyBeanMethods=False)
        assert ann.proxyBeanMethods is False


class TestScope:
    def test_singleton_default(self):
        ann = Scope()
        assert ann.value == "singleton"

    def test_prototype(self):
        ann = Scope("prototype")
        assert ann.value == "prototype"

    def test_case_insensitive(self):
        ann = Scope("PROTOTYPE")
        assert ann.value == "prototype"

    def test_invalid_scope_raises(self):
        with pytest.raises(ValueError):
            Scope("request")

    def test_invalid_scope_request_raises(self):
        with pytest.raises(ValueError):
            Scope("session")


class TestBean:
    def test_with_all_params(self):
        ann = Bean(
            name="itemBean",
            scope="prototype",
            init_method="init",
            destroy_method="close",
        )
        assert ann.name == "itemBean"
        assert ann.scope == "prototype"
        assert ann.init_method == "init"
        assert ann.destroy_method == "close"

    def test_defaults(self):
        ann = Bean()
        assert ann.name is None
        assert ann.scope == "singleton"
        assert ann.init_method is None
        assert ann.destroy_method is None


class TestValue:
    def test_with_default(self):
        ann = Value("app.timeout", default=30)
        assert ann.value == "app.timeout"
        assert ann.default == 30

    def test_default_none(self):
        ann = Value("app.name")
        assert ann.value == "app.name"
        assert ann.default is None


class TestConfigurationProperties:
    def test_prefix(self):
        ann = ConfigurationProperties("app")
        assert ann.prefix == "app"


class TestLifecycleAnnotations:
    def test_primary(self):
        @Primary()
        class B:
            pass

        anns = get_spring_annotations(B)
        assert len(anns) == 1
        assert isinstance(anns[0], Primary)

    def test_post_construct(self):
        @PostConstruct()
        class B:
            pass

        assert any(isinstance(a, PostConstruct) for a in get_spring_annotations(B))

    def test_pre_destroy(self):
        @PreDestroy()
        class B:
            pass

        assert any(isinstance(a, PreDestroy) for a in get_spring_annotations(B))


class TestProfile:
    def test_list_value(self):
        ann = Profile(["dev", "test"])
        assert ann.value == ["dev", "test"]

    def test_string_converts_to_list(self):
        ann = Profile("prod")
        assert ann.value == ["prod"]

    def test_attribute_name_is_value(self):
        ann = Profile(["dev"])
        assert hasattr(ann, "value")
        assert not hasattr(ann, "profiles")


class TestLazy:
    def test_default_true(self):
        ann = Lazy()
        assert ann.value is True

    def test_false(self):
        ann = Lazy(False)
        assert ann.value is False


class TestGetSpringAnnotations:
    def test_returns_list(self):
        @Service("svc")
        class S:
            pass

        result = get_spring_annotations(S)
        assert isinstance(result, list)
        assert len(result) == 1

    def test_does_not_inherit_from_base(self):
        @Component("parent")
        class Parent:
            pass

        @Service("child")
        class Child(Parent):
            pass

        # Only Child's own annotations are returned, not Parent's.
        child_anns = get_spring_annotations(Child)
        assert len(child_anns) == 1
        assert isinstance(child_anns[0], Service)

    def test_multiple_annotations_in_order(self):
        @Primary()
        @Service("multi")
        class Multi:
            pass

        anns = get_spring_annotations(Multi)
        # Decorators apply bottom-up: Service is applied first (innermost),
        # then Primary is applied (outermost). So Service is appended first.
        assert len(anns) == 2
        assert isinstance(anns[0], Service)
        assert isinstance(anns[1], Primary)

    def test_empty_for_undecorated(self):
        class Plain:
            pass

        assert get_spring_annotations(Plain) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
