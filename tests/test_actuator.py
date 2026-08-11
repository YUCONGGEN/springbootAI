"""P0-2 Actuator 运维端点测试。

覆盖 ``spring.web.actuator`` 的纯函数逻辑与 HTTP 薄端点：
- ``/actuator`` 端点目录
- ``/env`` 环境配置（脱敏）
- ``/loggers`` 日志级别查询与动态修改
- ``/metrics`` 指标列表
- ``/beans`` Bean 列表
- ``/configprops`` 配置属性绑定
- ``/mappings`` 路由映射
- ``/threaddump`` 线程转储

设计为纯函数 + 薄端点，因此测试以纯函数为主，辅以 FastAPI TestClient 验证 HTTP 包装。
"""
import logging
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spring.web.actuator import (
    actuator_router,
    configure_actuator,
    get_endpoint_directory,
    get_env_info,
    _sanitize,
    get_loggers,
    get_logger_level,
    set_logger_level,
    get_metrics,
    get_beans,
    get_configprops,
    get_mappings,
    get_threaddump,
)


# ==================== 测试桩上下文 ====================

class _FakeBeanDefinition:
    """模拟 BeanDefinition，仅暴露 actuator 需要的属性。"""

    def __init__(self, bean_class=None, scope="singleton", is_singleton=True,
                 annotations=None):
        self.bean_class = bean_class
        self.scope = scope
        self.is_singleton = is_singleton
        self.annotations = annotations or {}


class _FakeBeanFactory:
    def __init__(self, definitions):
        self._definitions = definitions

    def get_bean_names(self):
        return list(self._definitions.keys())

    def get_bean_definition(self, name):
        return self._definitions.get(name)


class _FakeConfigLoader:
    def __init__(self, config, profile="default"):
        self._config = config
        self._profile = profile

    def get_active_profile(self):
        return self._profile

    def get_prefix_config(self, prefix):
        return self._config.get(prefix, {})


class _FakeContext:
    """模拟 ApplicationContext，仅暴露 actuator 需要的接口。"""

    def __init__(self, config=None, definitions=None, profile="default"):
        self._config = config or {}
        self.config_loader = _FakeConfigLoader(self._config, profile)
        self.bean_factory = _FakeBeanFactory(definitions or {})
        # 用于 /mappings 端点取 FastAPI app
        self.web_context = None

    def get_config(self):
        return self._config


@pytest.fixture
def app_with_actuator():
    """构造一个挂载 actuator_router 的 FastAPI 应用 + 桩上下文。

    功能测试禁用 Actuator 鉴权（``management.endpoints.web.security.enabled=false``），
    专注于端点逻辑（脱敏、日志级别、beans 等）；鉴权行为由专门的安全测试覆盖。
    """
    ctx = _FakeContext(
        config={
            "server": {"port": 8080, "host": "0.0.0.0"},
            "database": {"password": "super-secret", "enabled": False, "url": "sqlite:///x.db"},
            # 功能测试禁用鉴权；生产环境默认 enabled=true
            "management": {"endpoints": {"web": {"security": {"enabled": False}}}},
        },
        definitions={
            "user_service": _FakeBeanDefinition(
                bean_class=type("UserService", (), {}),
                scope="singleton",
            ),
        },
    )
    app = FastAPI()
    app.include_router(actuator_router, prefix="/actuator")
    configure_actuator(ctx)
    ctx.web_context = SimpleNamespace(get_app=lambda: app)
    client = TestClient(app)
    yield client, ctx
    # 复位全局上下文，避免影响后续测试
    configure_actuator(None)


# ==================== 端点目录 ====================

class TestEndpointDirectory:
    def test_directory_lists_standard_endpoints(self):
        directory = get_endpoint_directory()
        links = directory["_links"]
        for name in ("health", "env", "loggers", "metrics", "beans",
                     "configprops", "mappings", "threaddump", "info", "prometheus"):
            assert name in links, f"端点目录缺少 {name}"
        assert links["env"]["href"] == "/actuator/env"
        assert "GET" in links["health"]["methods"]

    def test_directory_http(self, app_with_actuator):
        client, _ = app_with_actuator
        # 两种根路径都应返回目录
        for url in ("/actuator", "/actuator/"):
            resp = client.get(url)
            assert resp.status_code == 200
            assert "env" in resp.json()["_links"]


# ==================== /env 脱敏 ====================

class TestEnvEndpoint:
    def test_sanitize_masks_password_secret_token(self):
        data = {
            "database": {"password": "abc", "url": "sqlite:///x.db"},
            "api_key": "12345",
            "normal": "visible",
            "token": "t",
            "auth": {"passwd": "p", "role": "admin"},
            "list_key": [{"secret": "s"}, {"ok": 1}],
        }
        masked = _sanitize(data)
        assert masked["database"]["password"] == "******"
        assert masked["database"]["url"] == "sqlite:///x.db"
        assert masked["api_key"] == "******"
        assert masked["normal"] == "visible"
        assert masked["token"] == "******"
        # 父键 "auth" 不命中敏感词，递归进入子字典；子键 "passwd" 命中则脱敏
        assert masked["auth"]["passwd"] == "******"
        assert masked["auth"]["role"] == "admin"
        assert masked["list_key"][0]["secret"] == "******"
        assert masked["list_key"][1]["ok"] == 1

    def test_sanitize_preserves_non_dict(self):
        assert _sanitize("plain") == "plain"
        assert _sanitize(123) == 123
        assert _sanitize(None) is None
        assert _sanitize([1, 2]) == [1, 2]

    def test_env_info_with_context(self):
        ctx = _FakeContext(
            config={"server": {"password": "p", "port": 8080}},
            profile="prod",
        )
        info = get_env_info(ctx)
        assert info["activeProfiles"] == ["prod"]
        assert len(info["propertySources"]) == 1
        props = info["propertySources"][0]["properties"]
        assert props["server"]["password"] == "******"
        assert props["server"]["port"] == 8080

    def test_env_info_without_context(self):
        info = get_env_info(None)
        assert info == {"activeProfiles": [], "propertySources": []}

    def test_env_http_masks_sensitive(self, app_with_actuator):
        client, _ = app_with_actuator
        resp = client.get("/actuator/env")
        assert resp.status_code == 200
        body = resp.json()
        props = body["propertySources"][0]["properties"]
        assert props["database"]["password"] == "******"
        assert props["database"]["url"] == "sqlite:///x.db"


# ==================== /loggers ====================

class TestLoggersEndpoint:
    def test_get_loggers_includes_root(self):
        result = get_loggers()
        assert "ROOT" in result["loggers"]
        assert "INFO" in result["levels"]

    def test_get_loggers_lists_registered_logger(self):
        logging.getLogger("spring.test.actuator")
        result = get_loggers()
        assert "spring.test.actuator" in result["loggers"]

    def test_get_logger_level(self):
        logger = logging.getLogger("spring.test.levelprobe")
        logger.setLevel(logging.DEBUG)
        info = get_logger_level("spring.test.levelprobe")
        assert info["configuredLevel"] == "DEBUG"

    def test_set_logger_level_changes_effective_level(self):
        name = "spring.test.dynamic"
        set_logger_level(name, "ERROR")
        assert logging.getLogger(name).getEffectiveLevel() == logging.ERROR
        set_logger_level(name, "INFO")
        assert logging.getLogger(name).level == logging.INFO

    def test_set_logger_level_root_alias(self):
        original = logging.getLogger().level
        try:
            set_logger_level("root", "WARNING")
            assert logging.getLogger().level == logging.WARNING
        finally:
            logging.getLogger().setLevel(original)

    def test_set_logger_level_off_disables(self):
        name = "spring.test.offprobe"
        set_logger_level(name, "OFF")
        assert logging.getLogger(name).getEffectiveLevel() > logging.CRITICAL

    def test_set_logger_level_invalid_raises(self):
        with pytest.raises(ValueError):
            set_logger_level("spring.test.bad", "NOPE")

    def test_loggers_http_get_and_post(self, app_with_actuator):
        client, _ = app_with_actuator
        # GET 列表
        resp = client.get("/actuator/loggers")
        assert resp.status_code == 200
        assert "ROOT" in resp.json()["loggers"]
        # POST 动态修改
        name = "spring.test.httpprobe"
        resp = client.post(f"/actuator/loggers/{name}", json={"configuredLevel": "DEBUG"})
        assert resp.status_code == 200
        assert resp.json()["configuredLevel"] == "DEBUG"
        assert logging.getLogger(name).level == logging.DEBUG
        # GET 单个
        resp = client.get(f"/actuator/loggers/{name}")
        assert resp.status_code == 200

    def test_loggers_http_invalid_level_returns_400(self, app_with_actuator):
        client, _ = app_with_actuator
        resp = client.post("/actuator/loggers/spring.test.bad", json={"configuredLevel": "NOPE"})
        assert resp.status_code == 400
        assert "error" in resp.json()


# ==================== /metrics ====================

class TestMetricsEndpoint:
    def test_get_metrics_returns_names_list(self):
        result = get_metrics()
        assert "names" in result
        assert isinstance(result["names"], list)

    def test_metrics_http(self, app_with_actuator):
        client, _ = app_with_actuator
        resp = client.get("/actuator/metrics")
        assert resp.status_code == 200
        assert "names" in resp.json()


# ==================== /beans ====================

class TestBeansEndpoint:
    def test_get_beans_with_context(self):
        cls = type("UserService", (), {})
        ctx = _FakeContext(definitions={
            "user_service": _FakeBeanDefinition(bean_class=cls, scope="singleton"),
        })
        result = get_beans(ctx)
        beans = result["contexts"]["application"]["beans"]
        assert "user_service" in beans
        assert beans["user_service"]["type"] == "UserService"
        assert beans["user_service"]["scope"] == "singleton"

    def test_get_beans_without_context(self):
        assert get_beans(None) == {"contexts": {"application": {"beans": {}}}}

    def test_beans_http(self, app_with_actuator):
        client, _ = app_with_actuator
        resp = client.get("/actuator/beans")
        assert resp.status_code == 200
        beans = resp.json()["contexts"]["application"]["beans"]
        assert "user_service" in beans


# ==================== /configprops ====================

class TestConfigpropsEndpoint:
    def test_get_configprops_with_properties_annotation(self):
        props_ann = SimpleNamespace(prefix="server")
        ctx = _FakeContext(
            config={"server": {"port": 9090, "password": "secret"}},
            definitions={
                "server_props": _FakeBeanDefinition(
                    annotations={"properties": [props_ann]},
                ),
            },
        )
        result = get_configprops(ctx)
        # configprops 以配置前缀为键（对齐 Spring Boot），而非 bean 名
        bean = result["contexts"]["application"]["beans"]["server"]
        assert bean["prefix"] == "server"
        # 脱敏生效
        assert bean["properties"]["password"] == "******"
        assert bean["properties"]["port"] == 9090

    def test_get_configprops_skips_beans_without_properties(self):
        ctx = _FakeContext(definitions={
            "plain": _FakeBeanDefinition(annotations={}),
        })
        result = get_configprops(ctx)
        assert result["contexts"]["application"]["beans"] == {}

    def test_configprops_http(self, app_with_actuator):
        client, _ = app_with_actuator
        resp = client.get("/actuator/configprops")
        assert resp.status_code == 200


# ==================== /mappings ====================

class TestMappingsEndpoint:
    def test_get_mappings_with_app(self):
        app = FastAPI()

        @app.get("/hello")
        def hello():
            return {"ok": True}

        result = get_mappings(app)
        mappings = result["contexts"]["application"]["mappings"]["dispatcherServlets"]["dispatcherServlet"]
        paths = [m["path"] for m in mappings]
        assert "/hello" in paths

    def test_get_mappings_without_app(self):
        result = get_mappings(None)
        mappings = result["contexts"]["application"]["mappings"]["dispatcherServlets"]["dispatcherServlet"]
        assert mappings == []

    def test_mappings_http(self, app_with_actuator):
        client, _ = app_with_actuator
        resp = client.get("/actuator/mappings")
        assert resp.status_code == 200
        body = resp.json()
        assert "dispatcherServlets" in body["contexts"]["application"]["mappings"]


# ==================== /threaddump ====================

class TestThreaddumpEndpoint:
    def test_get_threaddump_returns_threads(self):
        result = get_threaddump()
        assert "threads" in result
        names = [t["threadName"] for t in result["threads"]]
        # 主线程必然存在
        assert any("MainThread" in n for n in names)
        # 每个线程结构完整
        for t in result["threads"]:
            assert "threadId" in t
            assert "threadState" in t
            assert "daemon" in t
            assert "stack" in t

    def test_threaddump_http(self, app_with_actuator):
        client, _ = app_with_actuator
        resp = client.get("/actuator/threaddump")
        assert resp.status_code == 200
        assert "threads" in resp.json()
