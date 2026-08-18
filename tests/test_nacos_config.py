"""Nacos Config 启动引导与动态刷新测试。"""
from __future__ import annotations

import time

from springbootai.cloud import nacos_config
from springbootai.config.config_loader import ConfigLoader


class _FakeNacosClient:
    def __init__(self, content: str):
        self.content = content

    def get_config(self, data_id, group, timeout=None):
        assert data_id == "welding-dev.yml"
        assert group == "DEFAULT_GROUP"
        return self.content


class _FailingNacosClient:
    def get_config(self, data_id, group, timeout=None):
        raise RuntimeError("authentication required")

def test_nacos_yaml_is_loaded_and_change_listener_is_registered(monkeypatch):
    properties = nacos_config.NacosConfigProperties(
        enabled=True,
        server_addr="127.0.0.1:8848",
        data_id="welding-dev.yml",
        refresh_interval_seconds=1,
    )
    fake = _FakeNacosClient("server:\n  port: 9191\njwt:\n  expires_in: 28800\n")
    client = nacos_config.NacosConfigClient(properties)
    monkeypatch.setattr(client, "_new_client", lambda authenticated=False: fake)

    assert client.fetch() == {"server": {"port": 9191}, "jwt": {"expires_in": 28800}}
    calls = []
    client.start_listener(lambda: calls.append("changed"))
    fake.content = "server:\n  port: 9292\n"
    deadline = time.time() + 2
    while not calls and time.time() < deadline:
        time.sleep(0.05)
    assert calls == ["changed"]
    client.close()


def test_nacos_client_reuses_authenticated_sdk_client(monkeypatch):
    """认证读取成功后，轮询不能重复创建 SDK 客户端或登录会话。"""
    properties = nacos_config.NacosConfigProperties(
        enabled=True,
        server_addr="127.0.0.1:8848",
        data_id="welding-dev.yml",
        username="nacos",
        password="nacos",
    )
    anonymous = _FailingNacosClient()
    authenticated = _FakeNacosClient("app:\n  version: 1\n")
    created = []
    client = nacos_config.NacosConfigClient(properties)

    def new_client(is_authenticated=False):
        created.append(is_authenticated)
        return authenticated if is_authenticated else anonymous

    monkeypatch.setattr(client, "_new_client", new_client)
    assert client.fetch() == {"app": {"version": 1}}
    assert client.fetch() == {"app": {"version": 1}}
    assert created == [False, True]
    client.close()


def test_config_loader_merges_nacos_before_environment_overrides(monkeypatch, tmp_path):
    remote = {
        "server": {"port": 9191},
        "jwt": {"expires_in": 28800},
        "spring": {"application": {"name": "welding-remote"}},
        "management": {
            "admin": {
                "request-metrics": {
                    "enabled": True,
                    "include-paths": ["/api/**"],
                }
            }
        },
    }

    class FakeBootstrapClient:
        def start_listener(self, callback):
            self.callback = callback

        def close(self):
            pass

    fake_client = FakeBootstrapClient()
    monkeypatch.setenv("NACOS_CONFIG_ENABLED", "true")
    monkeypatch.setenv("SERVER_PORT", "9292")
    monkeypatch.setenv("MANAGEMENT_ADMIN_REQUEST_METRICS_INCLUDE_PATHS", "/v1/**, /api/**")
    monkeypatch.setattr(
        nacos_config,
        "bootstrap_nacos_config",
        lambda local_config, existing_client=None: (fake_client, remote),
    )

    loader = ConfigLoader(base_path=str(tmp_path), log_events=False)
    assert loader.get_value("spring.application.name") == "welding-remote"
    assert loader.get_value("jwt.expires_in") == 28800
    # 环境变量仍是最高优先级，覆盖 Nacos 的 server.port。
    assert loader.get_value("server.port") == 9292
    # 管理面板读取的是 Nacos 合并后的最终配置；环境变量只覆盖指定字段。
    assert loader.get_value("management.admin.request-metrics.enabled") is True
    assert loader.get_value("management.admin.request-metrics.include-paths") == ["/v1/**", "/api/**"]
