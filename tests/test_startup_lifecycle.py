"""Regression coverage for startup resource ownership without a config file."""

import pytest

_STARTUP_ENV_NAMES = (
    "SPRING_PROFILES_ACTIVE",
    "APP_ENV",
    "STARTUP_FAIL_FAST",
    "DB_ENABLED",
    "DB_URL",
    "DB_DRIVER",
    "DB_NAME",
    "DB_HOST",
    "DB_PORT",
    "DB_USERNAME",
    "DB_PASSWORD",
    "REDIS_ENABLED",
    "RABBITMQ_ENABLED",
    "DISCOVERY_ENABLED",
    "SEATA_ENABLED",
    "PROMETHEUS_ENABLED",
    "SERVER_PORT",
    "SERVER_HOST",
)


@pytest.fixture(autouse=True)
def _restore_global_config_loader():
    """Keep context-local test configuration from leaking into later tests."""
    from spring.config.config_loader import ConfigLoader, config_loader

    original_state = dict(config_loader.__dict__)
    original_base_path = ConfigLoader._default_base_path
    try:
        yield
    finally:
        config_loader.__dict__.clear()
        config_loader.__dict__.update(original_state)
        ConfigLoader._default_base_path = original_base_path


def _no_config_main_class():
    # An unresolved module makes ApplicationContext exercise its source-file
    # fallback instead of accidentally loading the repository application.yml.
    return type("NoConfigApplication", (), {"__module__": "__no_config_application__"})


def _clear_startup_environment(monkeypatch):
    for name in _STARTUP_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_application_context_destroy_releases_default_sqlite(tmp_path, monkeypatch):
    """The default no-config MyBatis pool must be closed by context destroy."""
    _clear_startup_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)

    from spring.main import SpringApplication

    application = SpringApplication(_no_config_main_class())
    application._prepare_context()
    database_path = tmp_path / "test"
    assert database_path.exists()

    application.application_context.destroy()
    database_path.unlink()


def test_web_startup_failure_releases_context_resources(tmp_path, monkeypatch):
    """A failure after context creation must not keep the SQLite file locked."""
    _clear_startup_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)

    from spring.main import create_app
    from spring.web.web_context import WebApplicationContext

    def fail_init(self):
        raise RuntimeError("synthetic web startup failure")

    monkeypatch.setattr(WebApplicationContext, "init", fail_init)
    with pytest.raises(RuntimeError, match="synthetic web startup failure"):
        create_app(_no_config_main_class())

    database_path = tmp_path / "test"
    assert database_path.exists()
    database_path.unlink()


def test_destroy_all_continues_and_blocks_lazy_beans():
    """Teardown must not recreate a lazy resource or stop at one bad destructor."""
    from spring.context.bean_definition import BeanDefinition
    from spring.context.bean_factory import BeanFactory

    state = []

    class Broken:
        def destroy(self):
            state.append("broken")
            raise RuntimeError("destructor failed")

    class Healthy:
        def destroy(self):
            state.append("healthy")

    class Lazy:
        def __init__(self):
            state.append("lazy-created")

    factory = BeanFactory()
    for name, bean_class in (
        ("broken", Broken),
        ("healthy", Healthy),
        ("lazy", Lazy),
    ):
        factory.register_bean_definition(name, BeanDefinition(bean_class, name))

    factory.get_bean("broken")
    factory.get_bean("healthy")
    factory.destroy_all()

    assert state == ["broken", "healthy"]
    with pytest.raises(RuntimeError, match="has been destroyed"):
        factory.get_bean("lazy")


def test_asgi_shutdown_releases_default_sqlite(tmp_path, monkeypatch):
    """The ASGI lifespan shutdown must release all context-owned resources."""
    _clear_startup_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)

    from spring.main import create_app
    from spring.core.graceful_shutdown import shutdown_handler
    from starlette.testclient import TestClient

    asgi_app = create_app(_no_config_main_class())
    application_context = asgi_app.state.spring_application.application_context

    class RecordingScheduler:
        def __init__(self):
            self.stopped = False

        def stop_all(self):
            self.stopped = True

    scheduler = RecordingScheduler()
    application_context._scheduler = scheduler
    database_path = tmp_path / "test"
    assert database_path.exists()

    # Keep the process-global shutdown singleton isolated from other tests;
    # WebApplicationContext's own close_resources hook still runs normally.
    monkeypatch.setattr(shutdown_handler, "initiate_shutdown", lambda: False)
    with TestClient(asgi_app):
        pass

    from spring.context.application_context import ApplicationContext

    assert scheduler.stopped is True
    assert application_context._scheduler is None
    assert ApplicationContext.get_instance() is None
    database_path.unlink()


def test_failed_context_refresh_releases_default_sqlite(tmp_path, monkeypatch):
    """A refresh error after MyBatis setup must not leave the DB handle open."""
    _clear_startup_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)

    from spring.context.application_context import ApplicationContext
    from spring.main import SpringApplication

    def fail_refresh(self):
        raise RuntimeError("synthetic refresh failure")

    monkeypatch.setattr(ApplicationContext, "refresh", fail_refresh)
    application = SpringApplication(_no_config_main_class())

    try:
        application._prepare_context()
    except RuntimeError as exc:
        assert str(exc) == "synthetic refresh failure"
    else:
        raise AssertionError("_prepare_context() should propagate refresh failures")

    database_path = tmp_path / "test"
    assert database_path.exists()
    database_path.unlink()


def _lifecycle_context_with_missing_dependency(tmp_path, fail_fast):
    """Build a context containing optional lifecycle beans with one missing DI target."""
    from spring.annotations.core import (
        Autowired,
        Configuration,
        EventListener,
        GetMapping,
        RestController,
        Service,
        SpringBootApplication,
    )
    from spring.config.config_loader import ConfigLoader
    from spring.context.application_context import ApplicationContext
    from spring.context.bean_definition import BeanDefinition

    config_path = tmp_path / "application.yml"
    config_path.write_text(
        f"startup:\n  fail_fast: {str(fail_fast).lower()}\n",
        encoding="utf-8",
    )

    @SpringBootApplication(scan_base_packages=["__startup_lifecycle_no_components__"])
    class Application:
        pass

    class MissingDependency:
        pass

    @Configuration
    class OptionalConfiguration:
        @Autowired
        def __init__(self, missing: MissingDependency):
            self.missing = missing

    @Service
    class OptionalListener:
        @Autowired
        def __init__(self, missing: MissingDependency):
            self.missing = missing

        @EventListener()
        def receive(self, event):
            return event

    @RestController
    class OptionalController:
        @Autowired
        def __init__(self, missing: MissingDependency):
            self.missing = missing

        @GetMapping("/optional-feature")
        def get_optional_feature(self):
            return {"available": True}

    context = ApplicationContext(
        Application,
        config_loader=ConfigLoader(config_path=str(config_path)),
    )
    names = {
        "configuration": "optional_configuration",
        "listener": "optional_listener_service",
        "controller": "optional_controller",
    }
    for kind, bean_class in {
        "configuration": OptionalConfiguration,
        "listener": OptionalListener,
        "controller": OptionalController,
    }.items():
        definition = BeanDefinition(bean_class, names[kind])
        for annotation in getattr(bean_class, "__spring_annotations__", []):
            definition.add_annotation(annotation)
        context.bean_factory.register_bean_definition(names[kind], definition)

    return context, names


def test_tolerant_startup_skips_unavailable_lifecycle_beans(tmp_path, monkeypatch):
    """Optional config, listeners, and controllers must not prevent startup."""
    _clear_startup_environment(monkeypatch)
    context, names = _lifecycle_context_with_missing_dependency(tmp_path, False)

    context.refresh()

    assert context._started is True
    assert all(context.is_bean_unavailable(bean_name) for bean_name in names.values())
    assert context.get_event_publisher().listener_count() == 0

    from spring.web.web_context import WebApplicationContext

    web_context = WebApplicationContext(context)
    web_context.init()
    assert "/optional-feature" not in {
        route_path
        for route in web_context.fastapi_app.router.routes
        if (route_path := getattr(route, "path", None)) is not None
    }
    context.destroy()


def test_fail_fast_startup_keeps_lifecycle_dependency_errors(tmp_path, monkeypatch):
    """Strict startup must still reject a lifecycle bean with a missing dependency."""
    _clear_startup_environment(monkeypatch)
    context, _ = _lifecycle_context_with_missing_dependency(tmp_path, True)

    with pytest.raises(ValueError, match="Cannot resolve parameter 'missing'"):
        context.refresh()

    assert context._started is False
    context.destroy()


def test_context_destroy_stops_scheduled_tasks(tmp_path, monkeypatch):
    """Context teardown must stop scheduling work before releasing Beans."""
    _clear_startup_environment(monkeypatch)
    context, _ = _lifecycle_context_with_missing_dependency(tmp_path, False)

    class RecordingScheduler:
        def __init__(self):
            self.stopped = False

        def stop_all(self):
            self.stopped = True

    scheduler = RecordingScheduler()
    context._scheduler = scheduler

    context.destroy()

    assert scheduler.stopped is True
    assert context._scheduler is None


def test_tolerant_startup_does_not_hide_application_init_errors(tmp_path, monkeypatch):
    """Only dependency/outage failures are degradable in tolerant mode."""
    _clear_startup_environment(monkeypatch)

    from spring.annotations.core import EventListener, Service, SpringBootApplication
    from spring.config.config_loader import ConfigLoader
    from spring.context.application_context import ApplicationContext
    from spring.context.bean_definition import BeanDefinition

    config_path = tmp_path / "application.yml"
    config_path.write_text("startup:\n  fail_fast: false\n", encoding="utf-8")

    @SpringBootApplication(scan_base_packages=["__startup_lifecycle_no_components__"])
    class Application:
        pass

    @Service
    class BrokenListener:
        def __init__(self):
            raise RuntimeError("application bug")

        @EventListener()
        def receive(self, event):
            return event

    context = ApplicationContext(
        Application,
        config_loader=ConfigLoader(config_path=str(config_path)),
    )
    definition = BeanDefinition(BrokenListener, "broken_listener_service")
    for annotation in getattr(BrokenListener, "__spring_annotations__", []):
        definition.add_annotation(annotation)
    context.bean_factory.register_bean_definition("broken_listener_service", definition)

    import pytest

    with pytest.raises(RuntimeError, match="application bug"):
        context.refresh()
    context.destroy()


def test_failed_bean_creation_runs_instance_cleanup(tmp_path, monkeypatch):
    """A resource returned before init failure must still receive destroy()."""
    _clear_startup_environment(monkeypatch)

    from spring.annotations.core import EventListener, Service, SpringBootApplication
    from spring.config.config_loader import ConfigLoader
    from spring.context.application_context import ApplicationContext
    from spring.context.bean_definition import BeanDefinition

    config_path = tmp_path / "application.yml"
    config_path.write_text("startup:\n  fail_fast: false\n", encoding="utf-8")
    state = {}

    @SpringBootApplication(scan_base_packages=["__startup_lifecycle_no_components__"])
    class Application:
        pass

    @Service
    class ResourceBean:
        def __init__(self):
            state["instance"] = self

        def init(self):
            raise ConnectionError("backend unavailable")

        def destroy(self):
            state["destroyed"] = True

        @EventListener()
        def receive(self, event):
            return event

    context = ApplicationContext(
        Application,
        config_loader=ConfigLoader(config_path=str(config_path)),
    )
    definition = BeanDefinition(ResourceBean, "resource_listener_service")
    for annotation in getattr(ResourceBean, "__spring_annotations__", []):
        definition.add_annotation(annotation)
    context.bean_factory.register_bean_definition("resource_listener_service", definition)

    # The connection error is degradable, but the partially-created resource
    # must not survive the skipped Bean.
    context.refresh()

    assert state["instance"] is not None
    assert state["destroyed"] is True
    assert context.is_bean_unavailable("resource_listener_service")
    context.destroy()


def test_failed_refresh_destroys_previously_created_new_beans(tmp_path, monkeypatch):
    """Refresh rollback must destroy registered instances before removing definitions."""
    _clear_startup_environment(monkeypatch)

    from spring.annotations.core import Service, SpringBootApplication
    from spring.config.config_loader import ConfigLoader
    from spring.context.application_context import ApplicationContext
    from spring.context.bean_definition import BeanDefinition

    config_path = tmp_path / "application.yml"
    config_path.write_text("startup:\n  fail_fast: false\n", encoding="utf-8")
    state = {}

    @SpringBootApplication(scan_base_packages=["__startup_lifecycle_no_components__"])
    class Application:
        pass

    @Service
    class HealthyBean:
        def destroy(self):
            state["healthy_destroyed"] = True

    @Service
    class BrokenBean:
        def __init__(self):
            raise RuntimeError("rollback trigger")

    context = ApplicationContext(
        Application,
        config_loader=ConfigLoader(config_path=str(config_path)),
    )

    def register_components():
        for bean_name, bean_class in (
            ("healthy_bean_service", HealthyBean),
            ("broken_bean_service", BrokenBean),
        ):
            definition = BeanDefinition(bean_class, bean_name)
            for annotation in getattr(bean_class, "__spring_annotations__", []):
                definition.add_annotation(annotation)
            context.bean_factory.register_bean_definition(bean_name, definition)

    monkeypatch.setattr(context, "_scan_components", register_components)

    import pytest

    with pytest.raises(RuntimeError, match="rollback trigger"):
        context.refresh()

    assert state["healthy_destroyed"] is True
    assert context.bean_factory.get_bean_definition("healthy_bean_service") is None
    assert context.bean_factory.get_bean_definition("broken_bean_service") is None
    context.destroy()


def test_nested_dependency_value_error_is_not_relabelled_as_missing_dependency():
    """A dependency's configuration error must remain non-degradable."""
    from spring.context.bean_definition import BeanDefinition
    from spring.context.bean_factory import BeanDependencyError, BeanFactory

    class BrokenDependency:
        def __init__(self):
            raise ValueError("invalid dependency configuration")

    class Consumer:
        pass

    factory = BeanFactory()
    factory.register_bean_definition(
        "broken_dependency", BeanDefinition(BrokenDependency, "broken_dependency")
    )
    consumer_definition = BeanDefinition(Consumer, "consumer")
    consumer_definition.add_dependency("broken", BrokenDependency)
    factory.register_bean_definition("consumer", consumer_definition)

    try:
        factory.get_bean("consumer")
    except ValueError as exc:
        assert str(exc) == "invalid dependency configuration"
        assert not isinstance(exc, BeanDependencyError)
    else:
        raise AssertionError("nested dependency error should propagate")


def _lifecycle_context_for_bean_failure(tmp_path, fail_fast, bean_class, bean_name):
    """Create a context that reaches ``bean_class`` through a lifecycle scan."""
    from spring.annotations.core import SpringBootApplication
    from spring.config.config_loader import ConfigLoader
    from spring.context.application_context import ApplicationContext
    from spring.context.bean_definition import BeanDefinition

    config_path = tmp_path / "application.yml"
    config_path.write_text(
        f"startup:\n  fail_fast: {str(fail_fast).lower()}\n",
        encoding="utf-8",
    )

    @SpringBootApplication(scan_base_packages=["__startup_lifecycle_no_components__"])
    class Application:
        pass

    context = ApplicationContext(
        Application,
        config_loader=ConfigLoader(config_path=str(config_path)),
    )
    definition = BeanDefinition(bean_class, bean_name)
    for annotation in getattr(bean_class, "__spring_annotations__", []):
        definition.add_annotation(annotation)
    context.bean_factory.register_bean_definition(bean_name, definition)
    return context


@pytest.mark.parametrize(
    ("module_name", "error_name", "chain_kind"),
    [
        ("redis.exceptions", "ConnectionError", "cause"),
        ("pymysql.err", "OperationalError", "context"),
        ("pika.exceptions", "AMQPConnectionError", "cause"),
        ("kafka.errors", "NoBrokersAvailable", "cause"),
        ("sqlalchemy.exc", "OperationalError", "cause"),
    ],
)
def test_tolerant_startup_skips_chained_third_party_connectivity_errors(
    tmp_path, module_name, error_name, chain_kind
):
    """Known client connection errors remain degradable when wrapped by a Bean."""
    from spring.annotations.core import EventListener, Service

    external_error = type(
        error_name,
        (Exception,),
        {"__module__": module_name},
    )

    @Service
    class OptionalExternalListener:
        def __init__(self):
            try:
                raise external_error("service unavailable")
            except external_error as exc:
                if chain_kind == "cause":
                    raise RuntimeError("external client setup failed") from exc
                raise RuntimeError("external client setup failed")

        @EventListener()
        def receive(self, event):
            return event

    bean_name = "optional_external_listener_service"
    context = _lifecycle_context_for_bean_failure(
        tmp_path, False, OptionalExternalListener, bean_name
    )
    try:
        context.refresh()
        assert context.is_bean_unavailable(bean_name)
    finally:
        context.destroy()


def test_fail_fast_keeps_chained_third_party_connectivity_errors(tmp_path):
    """Explicit strict startup must still expose a wrapped client failure."""
    from spring.annotations.core import EventListener, Service

    redis_connection_error = type(
        "ConnectionError",
        (Exception,),
        {"__module__": "redis.exceptions"},
    )

    @Service
    class StrictExternalListener:
        def __init__(self):
            try:
                raise redis_connection_error("service unavailable")
            except redis_connection_error as exc:
                raise RuntimeError("external client setup failed") from exc

        @EventListener()
        def receive(self, event):
            return event

    context = _lifecycle_context_for_bean_failure(
        tmp_path, True, StrictExternalListener, "strict_external_listener_service"
    )
    try:
        with pytest.raises(RuntimeError, match="external client setup failed"):
            context.refresh()
        assert context._started is False
    finally:
        context.destroy()


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError])
def test_tolerant_startup_keeps_regular_lifecycle_errors(tmp_path, error_type):
    """The external-client whitelist must not hide ordinary application errors."""
    from spring.annotations.core import EventListener, Service

    @Service
    class BrokenListener:
        def __init__(self):
            raise error_type("application initialization failure")

        @EventListener()
        def receive(self, event):
            return event

    context = _lifecycle_context_for_bean_failure(
        tmp_path, False, BrokenListener, "broken_regular_listener_service"
    )
    try:
        with pytest.raises(error_type, match="application initialization failure"):
            context.refresh()
        assert context._started is False
    finally:
        context.destroy()
