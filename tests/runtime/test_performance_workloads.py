import asyncio

import httpx


def test_feature_workloads_execute_real_framework_paths():
    from spring.context.application_context import ApplicationContext

    previous_context = ApplicationContext.get_instance()
    from tests.performance import benchmark_app

    async def scenario():
        transport = httpx.ASGITransport(app=benchmark_app.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://benchmark") as client:
            return {
                "validation": await client.post(
                    "/benchmark/validation",
                    json={
                        "name": "load-user",
                        "age": 30,
                        "email": "load@example.test",
                        "password": "benchmark-password",
                    },
                ),
                "cache": await client.post(
                    "/benchmark/cache", json={"id": 101, "value": "cached"}
                ),
                "csv": await client.get("/benchmark/csv?rows=12"),
                "jpa": await client.get("/benchmark/jpa"),
                "conditional": await client.get(
                    "/benchmark/conditional?evaluations=12"
                ),
                "data": await client.get("/benchmark/data?rows=40"),
                "datasource": await client.get("/benchmark/datasource"),
                "txevent": await client.get("/benchmark/tx-event"),
                "config": await client.get(
                    "/benchmark/config-binding?bindings=3"
                ),
                "i18n": await client.get("/benchmark/i18n?messages=6"),
                "actuator": await client.get("/actuator/beans"),
                "swagger": await client.get("/openapi.json"),
                "swagger_docs": await client.get("/docs"),
                "swagger_redoc": await client.get("/redoc"),
            }

    try:
        responses = asyncio.run(scenario())
        feature_service = (
            ApplicationContext.get_instance().bean_factory.get_bean_by_type(
                benchmark_app.BenchmarkFeatureService
            )
        )
        retained_cache_fixture_state = (
            len(feature_service._source),
            len(feature_service._loads_by_item),
        )
    finally:
        ApplicationContext._current_context = previous_context

    assert all(response.status_code == 200 for response in responses.values())
    validation = responses["validation"].json()["data"]
    cache = responses["cache"].json()["data"]
    csv = responses["csv"].json()["data"]
    jpa = responses["jpa"].json()["data"]
    conditional = responses["conditional"].json()["data"]
    data = responses["data"].json()["data"]
    datasource = responses["datasource"].json()["data"]
    txevent = responses["txevent"].json()["data"]
    config = responses["config"].json()["data"]
    i18n = responses["i18n"].json()["data"]
    actuator = responses["actuator"].json()
    openapi = responses["swagger"].json()
    assert validation["valid"] is True
    assert cache["consistent"] is True and cache["cache_hit"] is True
    assert retained_cache_fixture_state == (0, 0)
    assert csv["kind"] == "csv" and csv["rows"] == 12
    assert csv["bytes"] > 0 and csv["round_trip"] is True
    assert jpa["updated"] is True and jpa["conflict_detected"] is True
    assert jpa["version"] == 1 and jpa["transient_mapped"] is False
    assert conditional["matched"] == conditional["evaluations"] == 12
    assert data["total"] == data["expected_total"] == 10
    assert data["sorted"] is True and data["transient_mapped"] is False
    assert datasource["selected"][0] == "master"
    assert datasource["selected"][3] == "report"
    assert datasource["routed_to_slaves"] is True
    assert datasource["returned"] is True and datasource["context_cleared"] is True
    assert txevent["commit_phases"] == [
        "before_commit", "after_commit", "after_completion"
    ]
    assert txevent["rollback_phases"] == ["after_rollback", "after_completion"]
    assert txevent["context_cleared"] is True
    assert config["valid"] is True and config["bindings"] == 3
    assert i18n["messages"] == i18n["resolved"] == 6
    assert i18n["fallback"] is True
    assert actuator["contexts"]["application"]["beans"]
    assert openapi["info"]["title"]
    assert openapi["paths"]["/benchmark/data"]["get"]["operationId"] == "benchmarkData"
    assert "SpringBootAI Benchmark" in openapi["paths"]["/benchmark/data"]["get"]["tags"]
    assert openapi["components"]["securitySchemes"]["BenchmarkBearer"]["scheme"] == "bearer"
    assert responses["swagger_docs"].headers["content-type"].startswith("text/html")
    assert responses["swagger_redoc"].headers["content-type"].startswith("text/html")


def test_websocket_workloads_execute_real_asgi_routes():
    from fastapi.testclient import TestClient
    from tests.performance import benchmark_app

    with TestClient(benchmark_app.app) as client:
        with client.websocket_connect("/ws/benchmark-echo") as socket:
            assert socket.receive_text() == "ready"
            socket.send_text("ping")
            assert socket.receive_text() == "echo:ping"

        with client.websocket_connect("/ws/benchmark-app") as socket:
            socket.send_json({
                "action": "subscribe",
                "destination": "/topic/bootstrap",
            })
            assert socket.receive_json()["payload"] == {"ready": True}

            socket.send_json({
                "action": "message",
                "destination": "/app/echo",
                "payload": "ping",
            })
            assert socket.receive_json()["payload"] == {"echo": "ping"}

            socket.send_json({
                "action": "subscribe",
                "destination": "/topic/benchmark",
            })
            socket.send_json({
                "action": "message",
                "destination": "/app/broadcast",
                "payload": "ping",
            })
            broadcast = socket.receive_json()
            assert broadcast["destination"] == "/topic/benchmark"
            assert broadcast["payload"] == {"broadcast": "ping"}


def test_conditional_assembly_benchmark_registers_expected_components():
    from tests.performance.conditional_assembly import run_benchmark

    report = run_benchmark(iterations=3, component_count=25, warmup=1)
    assert report["failures"] == []
    assert report["registered_per_iteration"] == 20
    assert report["result"]["p95_ms"] is not None


def test_test_slice_assembly_benchmark_covers_all_slices():
    from tests.performance.test_slice_assembly import run_benchmark

    report = run_benchmark(iterations=1, warmup=0)
    assert report["failures"] == []
    assert set(report["result"]) == {
        "spring_boot_test", "web_mvc_test", "data_jpa_test"
    }
    assert all(values["p95_ms"] is not None for values in report["result"].values())
