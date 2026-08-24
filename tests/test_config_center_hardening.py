"""配置中心坏配置与 IO 边界回归测试。"""

import math

import pytest

from springbootai.cloud.config_center import ConfigCenterClient, config_client


@pytest.fixture(autouse=True)
def reset_config_center_state():
    """隔离全局配置中心单例，避免测试之间互相污染。"""
    config_client._configured = False
    config_client._cached_config = {}
    config_client._cached_hash = ""
    config_client._refresh_callbacks = []
    config_client._change_listeners = []
    yield
    config_client._configured = False
    config_client._cached_config = {}
    config_client._cached_hash = ""
    config_client._refresh_callbacks = []
    config_client._change_listeners = []


@pytest.mark.parametrize(
    "config",
    [None, {}, {"spring": None}, {"spring": {"cloud": None}},
     {"spring": {"cloud": {"config": None}}}],
)
def test_malformed_optional_config_center_section_is_disabled(config):
    """可选配置中心的空/错误节点不应阻断应用启动。"""
    config_client.configure(config)
    assert config_client.configured is False


def test_invalid_io_values_are_bounded_and_retry_is_never_zero():
    """非法超时/重试值回退到安全范围，至少执行一次请求。"""
    config_client.configure({
        "spring": {"cloud": {"config": {
            "enabled": True,
            "timeout": None,
            "retry": {
                "max-attempts": -100,
                "initial-interval": math.inf,
                "multiplier": math.nan,
            },
        }}},
    })

    assert config_client._timeout == ConfigCenterClient._DEFAULT_TIMEOUT_MS
    assert config_client._retry_max == 1
    assert config_client._retry_initial == 1000
    assert config_client._retry_multiplier == 1.1


def test_retry_interval_is_capped(monkeypatch):
    """指数退避不能因错误 multiplier 形成超长 sleep。"""
    config_client.configure({
        "spring": {"cloud": {"config": {
            "enabled": True,
            "uri": "http://config.invalid",
            "retry": {
                "max-attempts": 3,
                "initial-interval": ConfigCenterClient._MAX_RETRY_INTERVAL_MS,
                "multiplier": 10,
            },
        }}},
    })
    sleeps = []

    class FailedResponse:
        status_code = 503

        def raise_for_status(self):
            raise RuntimeError("unavailable")

    monkeypatch.setattr(
        "requests.get", lambda *args, **kwargs: FailedResponse(),
    )
    monkeypatch.setattr("springbootai.cloud.config_center.time.sleep", sleeps.append)

    assert config_client.fetch() == {}
    assert sleeps == [60.0, 60.0]
