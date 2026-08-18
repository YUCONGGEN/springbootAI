"""框架内置请求持久化监控测试。"""
from types import SimpleNamespace

from springbootai.web.request_metrics import (
    configure_request_metrics,
    get_request_metrics,
    resolve_request_metrics_config,
)


def test_request_metrics_is_disabled_by_default():
    assert resolve_request_metrics_config({})["enabled"] is False
    assert configure_request_metrics({}) is None
    assert get_request_metrics() == {"enabled": False, "items": []}


def test_request_metrics_persists_business_request_data(tmp_path):
    config = {
        "database": {"driver": "sqlite", "database": str(tmp_path / "metrics.db")},
        "management": {"admin": {"request-metrics": {"enabled": True}}},
    }
    interceptor = configure_request_metrics(config)
    request = SimpleNamespace(
        state=SimpleNamespace(), url=SimpleNamespace(path="/api/welders")
    )
    interceptor.pre_handle(request, None)
    interceptor.post_handle(request, SimpleNamespace(status_code=503), None)

    metrics = get_request_metrics()
    assert metrics["enabled"] is True
    assert metrics["persistent"] is True
    assert len(metrics["items"]) == 1
    row = metrics["items"][0]
    assert row["path"] == "/api/welders"
    assert row["request_count"] == 1
    assert row["error_count"] == 1
    assert row["total_ms"] >= 0
    assert row["last_status"] == 503
    configure_request_metrics({})


def test_request_metrics_excludes_actuator_and_honours_business_whitelist(tmp_path):
    config = {
        "database": {"driver": "sqlite", "database": str(tmp_path / "metrics.db")},
        "management": {
            "admin": {
                "request-metrics": {"enabled": True, "include-paths": ["/api/**"]}
            }
        },
    }
    interceptor = configure_request_metrics(config)
    for path in ("/actuator/health", "/docs/index.html", "/other", "/api/welders"):
        request = SimpleNamespace(state=SimpleNamespace(), url=SimpleNamespace(path=path))
        interceptor.pre_handle(request, None)
        interceptor.post_handle(request, SimpleNamespace(status_code=200), None)

    assert [row["path"] for row in get_request_metrics()["items"]] == ["/api/welders"]
    configure_request_metrics({})


def test_request_metrics_removes_old_non_business_history_on_startup(tmp_path):
    database = str(tmp_path / "metrics.db")
    config = {
        "database": {"driver": "sqlite", "database": database},
        "management": {"admin": {"request-metrics": {"enabled": True}}},
    }
    first = configure_request_metrics(config)
    for path in ("/actuator/health", "/api/welders"):
        request = SimpleNamespace(state=SimpleNamespace(), url=SimpleNamespace(path=path))
        first.store.record(path, 200, 1)

    configure_request_metrics(config)
    assert [row["path"] for row in get_request_metrics()["items"]] == ["/api/welders"]
    configure_request_metrics({})


def test_request_metrics_uses_merged_config_shape_and_does_not_fail_on_bad_storage():
    """配置可来自 Nacos/环境合并结果；不可用存储不能阻止应用继续启动。"""
    config = {
        "management": {
            "admin": {
                "request_metrics": {
                    "enabled": "true",
                    "include_paths": "/api/**, /rpc/**",
                }
            }
        },
        "database": {"url": "not-a-valid-sqlalchemy-url"},
    }
    options = resolve_request_metrics_config(config)
    assert options["enabled"] is True
    assert options["include_paths"] == ["/api/**", "/rpc/**"]
    assert configure_request_metrics(config) is None
    assert get_request_metrics() == {
        "enabled": True,
        "persistent": False,
        "items": [],
        "error": "监控存储不可用",
    }
    configure_request_metrics({})
