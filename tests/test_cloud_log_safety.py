"""Regression tests for source-level cloud component log safety.

These tests replace each module logger instead of relying on ``caplog``.  That
keeps the assertions meaningful even when the application's global logging
filter would otherwise hide an unsafe message after it left the component.
"""

from __future__ import annotations

from typing import Any

from springbootai.cloud import bus as bus_module
from springbootai.cloud import discovery as discovery_module
from springbootai.cloud import seata as seata_module


class _CapturingLogger:
    def __init__(self) -> None:
        self.records: list[str] = []

    def _capture(self, level: str, message: Any, *args: Any, **_kwargs: Any) -> None:
        try:
            rendered = str(message) % args if args else str(message)
        except Exception:
            rendered = f"{message!s} {args!r}"
        self.records.append(f"{level}:{rendered}")

    def debug(self, message: Any, *args: Any, **kwargs: Any) -> None:
        self._capture("DEBUG", message, *args, **kwargs)

    def info(self, message: Any, *args: Any, **kwargs: Any) -> None:
        self._capture("INFO", message, *args, **kwargs)

    def warning(self, message: Any, *args: Any, **kwargs: Any) -> None:
        self._capture("WARNING", message, *args, **kwargs)

    def error(self, message: Any, *args: Any, **kwargs: Any) -> None:
        self._capture("ERROR", message, *args, **kwargs)

    def exception(self, message: Any, *args: Any, **kwargs: Any) -> None:
        self._capture("EXCEPTION", message, *args, **kwargs)

    @property
    def text(self) -> str:
        return "\n".join(self.records)


def _assert_log_safe(log_text: str, *secrets: str) -> None:
    for secret in secrets:
        assert secret not in log_text
    # User-controlled CR/LF must be escaped, not emitted as a forged record.
    assert "\nFORGED" not in log_text
    assert "\rFORGED" not in log_text
    assert "\u0085FORGED" not in log_text
    assert "\u2028FORGED" not in log_text
    assert "\u2029FORGED" not in log_text


def test_bus_omits_event_payload_and_exception_details(monkeypatch) -> None:
    logger = _CapturingLogger()
    monkeypatch.setattr(bus_module, "logger", logger)
    event_bus = object.__new__(bus_module.EventBus)
    bus_module.EventBus.__init__(event_bus)
    event_bus.configure(
        {
            "spring": {
                "application": {
                    "name": "password=BUS_SERVICE_SECRET\nFORGED",
                },
                "cloud": {
                    "bus": {
                        "enabled": True,
                        "backend": "local",
                        "destination": "token=BUS_DESTINATION_SECRET\rFORGED",
                    }
                },
            }
        }
    )

    def fail_with_secret(_event: bus_module.BusEvent) -> None:
        raise RuntimeError(
            "password=BUS_EXCEPTION_SECRET\ntoken=BUS_EXCEPTION_TOKEN"
        )

    event_bus.subscribe("*", fail_with_secret)
    event = bus_module.BusEvent(
        type="refreshConfig\nFORGED\u2028FORGED",
        data={
            "password": "BUS_PAYLOAD_PASSWORD",
            "token": "BUS_PAYLOAD_TOKEN",
        },
    )

    assert event_bus.publish(event) == event.id
    assert "error_type=RuntimeError" in logger.text
    assert f"event_id={event.id}" in logger.text
    _assert_log_safe(
        logger.text,
        "BUS_SERVICE_SECRET",
        "BUS_DESTINATION_SECRET",
        "BUS_EXCEPTION_SECRET",
        "BUS_EXCEPTION_TOKEN",
        "BUS_PAYLOAD_PASSWORD",
        "BUS_PAYLOAD_TOKEN",
    )


def test_discovery_sanitizes_endpoint_fields_and_exception_details(monkeypatch) -> None:
    logger = _CapturingLogger()
    monkeypatch.setattr(discovery_module, "logger", logger)

    class FailingNacosClient:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError(
                "password=NACOS_CONNECT_SECRET\ntoken=NACOS_CONNECT_TOKEN"
            )

    monkeypatch.setattr(discovery_module, "NacosClient", FailingNacosClient)
    client = object.__new__(discovery_module.NacosDiscoveryClient)
    discovery_module.NacosDiscoveryClient.__init__(
        client,
        server_addr=(
            "https://nacos-user:NACOS_URL_PASSWORD@nacos.test:8848/nacos"
            "?token=NACOS_URL_TOKEN"
        ),
        username="nacos-user",
        password="NACOS_CONFIG_PASSWORD",
    )

    client.connect()
    assert client._client is None
    assert "endpoint=https://nacos.test:8848/nacos" in logger.text
    assert "error_type=RuntimeError" in logger.text

    class FailingRegistrationClient:
        def add_naming_instance(self, **_kwargs: Any) -> None:
            raise RuntimeError(
                "password=NACOS_REGISTER_SECRET\ntoken=NACOS_REGISTER_TOKEN"
            )

    client._client = FailingRegistrationClient()
    assert not client.register_service(
        "password=NACOS_SERVICE_SECRET\nFORGED",
        "127.0.0.1",
        8080,
        metadata={"token": "NACOS_METADATA_TOKEN"},
    )
    _assert_log_safe(
        logger.text,
        "NACOS_URL_PASSWORD",
        "NACOS_URL_TOKEN",
        "NACOS_CONFIG_PASSWORD",
        "NACOS_CONNECT_SECRET",
        "NACOS_CONNECT_TOKEN",
        "NACOS_SERVICE_SECRET",
        "NACOS_METADATA_TOKEN",
        "NACOS_REGISTER_SECRET",
        "NACOS_REGISTER_TOKEN",
    )


def test_seata_logs_only_safe_branch_identifiers_and_error_type(monkeypatch) -> None:
    logger = _CapturingLogger()
    monkeypatch.setattr(seata_module, "logger", logger)
    manager = object.__new__(seata_module.SeataTransactionManager)
    seata_module.SeataTransactionManager.__init__(manager)
    manager.callback_allowed_hosts = ("callback.test",)

    xid = "xid\nFORGED"
    branch_id = "token=SEATA_BRANCH_TOKEN\rFORGED"
    callback_url = (
        "https://callback.test/seata/branch?token=SEATA_CALLBACK_TOKEN"
    )

    def fail_with_secret(_xid: str, _branch_id: str) -> None:
        raise RuntimeError(
            "password=SEATA_EXCEPTION_SECRET\ntoken=SEATA_EXCEPTION_TOKEN"
        )

    returned_branch_id = manager.register_branch(
        xid,
        branch_id=branch_id,
        callback_url=callback_url,
        commit_cb=fail_with_secret,
        service_name="password=SEATA_SERVICE_SECRET\nFORGED",
        metadata={"password": "SEATA_METADATA_PASSWORD"},
    )
    assert returned_branch_id == branch_id
    assert not manager._notify_branch(
        {
            "xid": xid,
            "branch_id": branch_id,
            "callback_url": callback_url,
        },
        "commit",
    )

    assert "error_type=RuntimeError" in logger.text
    assert "callback=https://callback.test/seata/branch" in logger.text
    _assert_log_safe(
        logger.text,
        "SEATA_BRANCH_TOKEN",
        "SEATA_CALLBACK_TOKEN",
        "SEATA_SERVICE_SECRET",
        "SEATA_METADATA_PASSWORD",
        "SEATA_EXCEPTION_SECRET",
        "SEATA_EXCEPTION_TOKEN",
    )


def test_seata_startup_recovery_logs_counts_not_transaction_payload(monkeypatch) -> None:
    logger = _CapturingLogger()
    monkeypatch.setattr(seata_module, "logger", logger)

    class RecoveryManager:
        def configure(self, **_kwargs: Any) -> None:
            return None

        def recover_pending_transactions(self) -> dict[str, list[str]]:
            return {
                "committed": ["password=RECOVERY_COMMITTED_SECRET\nFORGED"],
                "rolled_back": ["token=RECOVERY_ROLLBACK_TOKEN\rFORGED"],
                "pending": ["password=RECOVERY_PENDING_SECRET"],
            }

    monkeypatch.setattr(seata_module, "seata_manager", RecoveryManager())
    seata_module.init_seata(
        {
            "mode": "http",
            "http_compensation_enabled": True,
            "recover_on_startup": True,
        }
    )

    assert "committed=1 rolled_back=1 pending=1" in logger.text
    _assert_log_safe(
        logger.text,
        "RECOVERY_COMMITTED_SECRET",
        "RECOVERY_ROLLBACK_TOKEN",
        "RECOVERY_PENDING_SECRET",
    )


def test_seata_health_does_not_return_bridge_exception_details() -> None:
    class Bridge:
        def health(self):
            raise seata_module.SeataBridgeError(
                "password=HEALTH_SECRET\ntoken=HEALTH_TOKEN")

    manager = object.__new__(seata_module.SeataTransactionManager)
    seata_module.SeataTransactionManager.__init__(manager)
    manager.mode = "distributed"
    manager._bridge_client = Bridge()

    health = manager.check_health()
    assert health == {
        "status": "DOWN",
        "reason": "bridge health failed: error_type=SeataBridgeError",
    }
