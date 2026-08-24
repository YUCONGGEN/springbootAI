"""配置来源/热刷新监控的最小安全回归测试。"""

from springbootai.config.config_loader import ConfigLoader
from springbootai.config.config_monitor import ConfigMonitor


def test_config_monitor_is_disabled_and_keeps_no_history_by_default():
    monitor = ConfigMonitor()

    monitor.record("load", current={"server": {"port": 8080}}, source="yaml")

    snapshot = monitor.snapshot()
    assert snapshot["enabled"] is False
    assert snapshot["events"] == []


def test_config_monitor_masks_sensitive_values_and_limits_history():
    monitor = ConfigMonitor({
        "enabled": True,
        "include_values": True,
        "history_size": 2,
    })
    previous = {"jwt": {"secret-key": "old"}, "server": {"port": 8080}}
    current = {"jwt": {"secret-key": "new"}, "server": {"port": 8090}}

    monitor.record("load", current=previous, source="yaml")
    monitor.record_refresh(
        previous=previous,
        current=current,
        source="nacos",
        success=True,
        duration_ms=2.5,
    )
    monitor.record("manual", current=current, source="cli")

    snapshot = monitor.snapshot()
    assert len(snapshot["events"]) == 2
    refresh = snapshot["events"][0]
    assert refresh["changed_keys"] == ["jwt.secret-key", "server.port"]
    assert refresh["values"]["jwt.secret-key"] == "******"
    assert refresh["values"]["server.port"] == 8090


def test_config_monitor_can_be_enabled_by_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("MANAGEMENT_CONFIG_MONITOR_ENABLED", "true")
    config_file = tmp_path / "application.yml"
    config_file.write_text("server:\n  port: 8080\n", encoding="utf-8")

    loader = ConfigLoader(config_path=str(config_file), log_events=False)

    assert loader.get_config_monitor().enabled is True
    assert loader.get_config_monitor().snapshot()["events"]
