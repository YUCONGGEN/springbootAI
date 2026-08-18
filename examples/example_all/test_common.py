"""全局监控基础设施测试：验证框架注解、Mapper 持久化契约和拦截器生命周期。"""

from types import SimpleNamespace

from example_all.common import (
    ApiError,
    GlobalExceptionHandler,
    RequestMetric,
    RequestMetricMapper,
    RequestMonitoringInterceptor,
    get_request_id,
)


class _FakeLogger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None


class _FakeMetricMapper:
    def __init__(self):
        self.rows = {}

    def find_by_path(self, path):
        return self.rows.get(path)

    def insert(self, path, request_count, error_count, total_ms, last_status):
        self.rows[path] = {
            "path": path,
            "request_count": request_count,
            "error_count": error_count,
            "total_ms": total_ms,
            "last_status": last_status,
        }

    def increment(self, path, error_count, total_ms, last_status):
        row = self.rows[path]
        row["request_count"] += 1
        row["error_count"] += error_count
        row["total_ms"] += total_ms
        row["last_status"] = last_status

    def find_all(self):
        return list(self.rows.values())


def _request(path: str = "/api/test", request_id: str = "test-request"):
    return SimpleNamespace(
        url=SimpleNamespace(path=path),
        method="GET",
        headers={"X-Request-ID": request_id},
        state=SimpleNamespace(),
    )


def test_monitoring_interceptor_persists_counter_through_mapper():
    mapper = _FakeMetricMapper()
    interceptor = RequestMonitoringInterceptor(mapper)
    interceptor.logger = _FakeLogger()

    first = _request()
    interceptor.pre_handle(first, None)
    assert get_request_id() == "test-request"
    interceptor.post_handle(first, SimpleNamespace(status_code=200), None)
    interceptor.after_completion(first, SimpleNamespace(status_code=200), None)

    second = _request()
    interceptor.pre_handle(second, None)
    interceptor.after_completion(second, SimpleNamespace(status_code=500), None, RuntimeError("failed"))

    row = mapper.rows["/api/test"]
    assert row["request_count"] == 2
    assert row["error_count"] == 1
    assert get_request_id() is None


def test_monitoring_entity_and_mapper_keep_framework_metadata():
    assert RequestMetric.__entity__ is True
    assert RequestMetric.__table__.name == "request_metrics"
    assert getattr(RequestMetricMapper.find_by_path, "select", None) is not None
    assert getattr(RequestMetricMapper.insert, "insert", None) is not None
    assert getattr(RequestMetricMapper.increment, "update", None) is not None


def test_global_advice_maps_custom_application_error():
    advice = GlobalExceptionHandler()
    advice.logger = _FakeLogger()
    response = advice.handle_api_error(ApiError("invalid"))
    assert response.code == 400
    assert response.message == "invalid"
