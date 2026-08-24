from types import SimpleNamespace

from springbootai.cloud.nacos_config import NacosConfigClient, NacosConfigProperties
from springbootai.config.config_loader import ConfigLoader
from springbootai.web.request_metrics import RequestMetricsStore, resolve_request_metrics_config


def test_request_metrics_table_name_must_be_a_valid_identifier(tmp_path):
    store = RequestMetricsStore(
        {"database": {"driver": "sqlite", "database": str(tmp_path / "m.db")}},
        "123; DROP TABLE users",
    )
    assert store.table == "springbootai_request_metrics"


def test_sqlite_database_path_is_used_when_url_is_not_configured(monkeypatch, tmp_path):
    monkeypatch.delenv("DB_URL", raising=False)
    config_file = tmp_path / "application.yml"
    config_file.write_text(
        "database:\n  driver: sqlite\n  database: ./runtime/business.db\n",
        encoding="utf-8",
    )
    loaded = ConfigLoader(config_path=str(config_file), log_events=False).get_config()
    assert loaded["database"]["url"].endswith("./runtime/business.db")


def test_nacos_refresh_retries_when_refresh_callback_fails(monkeypatch):
    properties = NacosConfigProperties(
        enabled=True, server_addr="unused", data_id="app.yml", refresh_interval_seconds=1
    )
    client = NacosConfigClient(properties)
    client._client = object()
    client._last_content = "old: true"
    client._get_content = lambda: "new: true"
    calls = []

    def fail_once():
        calls.append(True)
        # 模拟 ApplicationContext.reload() 在回调中重新 fetch，验证失败时
        # 不会把待处理版本提前提交。
        client.fetch()
        if len(calls) == 1:
            raise RuntimeError("temporary rebind failure")

    client.start_listener(fail_once)
    import time
    time.sleep(2.2)
    client.close()
    assert len(calls) >= 2
    assert client._last_content == "new: true"


def test_request_metrics_runtime_config_accepts_alias_and_string_boolean():
    config = {"management": {"admin": {
        "request_metrics": {"enabled": "true", "include_paths": "/api/**"}
    }}}
    resolved = resolve_request_metrics_config(config)
    assert resolved["enabled"] is True
    assert resolved["include_paths"] == ["/api/**"]


def test_reload_clears_in_progress_flag_when_success_hook_fails(monkeypatch, tmp_path):
    """刷新完成后的日志/清理钩子异常不能让 loader 永久卡在刷新状态。"""
    config_file = tmp_path / "application.yml"
    config_file.write_text("server:\n  port: 8080\n", encoding="utf-8")
    loader = ConfigLoader(config_path=str(config_file), log_events=False)
    original_log = loader._log

    def fail_success_log(level, message, *args):
        if message == "Config reloaded":
            raise RuntimeError("logging hook failed")
        return original_log(level, message, *args)

    monkeypatch.setattr(loader, "_log", fail_success_log)
    try:
        loader.reload()
    except RuntimeError as exc:
        assert str(exc) == "logging hook failed"
    else:
        raise AssertionError("reload should surface a failing success hook")
    assert loader._reload_in_progress is False
