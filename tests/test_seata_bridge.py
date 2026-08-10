import io
import json
from urllib.error import HTTPError

import pytest

from spring.cloud import seata as seata_module
from spring.cloud.seata import SeataTransactionManager
from spring.cloud.seata_bridge import (
    SeataBridgeClient,
    SeataBridgeError,
)


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, _size):
        return self.payload


def test_bridge_client_sends_token_and_parses_json(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response({"xid": "127.0.0.1:8091:1", "status": "Begin"})

    monkeypatch.setattr("spring.cloud.seata_bridge.urlrequest.urlopen", fake_urlopen)
    client = SeataBridgeClient("http://127.0.0.1:18091/", "0123456789abcdef", 2.5)

    result = client.begin(
        timeout_ms=5000,
        name="order",
        application_id="orders",
        transaction_group="springpy_tx_group",
    )

    assert result["xid"] == "127.0.0.1:8091:1"
    assert captured["timeout"] == 2.5
    assert captured["request"].get_header("X-seata-bridge-token") == "0123456789abcdef"
    assert json.loads(captured["request"].data)["name"] == "order"


def test_bridge_client_reports_http_error_body(monkeypatch):
    def fake_urlopen(_request, timeout):
        assert timeout == 5.0
        raise HTTPError(
            "http://127.0.0.1:18091/api/v1/transactions",
            409,
            "Conflict",
            {},
            io.BytesIO(b'{"message":"coordinator down"}'),
        )

    monkeypatch.setattr("spring.cloud.seata_bridge.urlrequest.urlopen", fake_urlopen)
    client = SeataBridgeClient("http://127.0.0.1:18091", "0123456789abcdef")

    with pytest.raises(SeataBridgeError, match="coordinator down"):
        client.begin(
            timeout_ms=5000,
            name="order",
            application_id="orders",
            transaction_group="springpy_tx_group",
        )


@pytest.mark.parametrize("url", ["", "localhost:18091", "ftp://localhost/service"])
def test_bridge_client_rejects_invalid_urls(url):
    with pytest.raises(ValueError, match="absolute HTTP"):
        SeataBridgeClient(url, "0123456789abcdef")


def test_distributed_manager_uses_bridge_and_fails_closed(monkeypatch):
    calls = []

    class FakeBridge:
        def __init__(self, base_url, token, timeout_s):
            calls.append(("init", base_url, token, timeout_s))

        def health(self):
            return {
                "status": "UP",
                "transactionGroup": "springpy_tx_group",
                "serverAddr": "seata-server:8091",
            }

        def begin(self, **payload):
            calls.append(("begin", payload))
            return {"xid": "seata-server:8091:100", "status": "Begin"}

        def register_branch(self, xid, **payload):
            calls.append(("branch", xid, payload))
            return {"xid": xid, "branchId": payload["branch_id"]}

        def commit(self, xid):
            calls.append(("commit", xid))
            return {"success": True, "status": "Committed"}

        def rollback(self, xid):
            calls.append(("rollback", xid))
            return {"success": True, "status": "Rollbacked"}

    monkeypatch.setattr(seata_module, "SeataBridgeClient", FakeBridge)
    manager = SeataTransactionManager()
    manager.configure(
        application_id="orders",
        transaction_group="springpy_tx_group",
        mode="distributed",
        bridge_url="http://127.0.0.1:18091",
        bridge_token="0123456789abcdef",
    )
    try:
        xid = manager.begin_transaction(timeout=5000, name="create-order")
        branch_id = manager.register_branch(
            xid,
            resource_id="inventory",
            callback_url="http://inventory/seata/branch",
            service_name="inventory-service",
            metadata={"sku": "SKU-1"},
        )
        assert branch_id
        assert manager.commit_transaction(xid) is True
        assert ("commit", xid) in calls

        xid = manager.begin_transaction(timeout=5000, name="cancel-order")
        assert manager.rollback_transaction(xid) is True
        assert ("rollback", xid) in calls
    finally:
        manager.set_mode("local")


def test_distributed_manager_rejects_process_local_branch_callbacks(monkeypatch):
    class FakeBridge:
        def __init__(self, *_args, **_kwargs):
            pass

        def health(self):
            return {"status": "UP", "transactionGroup": "springpy_tx_group"}

        def begin(self, **_payload):
            return {"xid": "seata-server:8091:101", "status": "Begin"}

        def rollback(self, _xid):
            return {"success": True, "status": "Rollbacked"}

    monkeypatch.setattr(seata_module, "SeataBridgeClient", FakeBridge)
    manager = SeataTransactionManager()
    manager.configure(
        application_id="orders",
        transaction_group="springpy_tx_group",
        mode="distributed",
        bridge_url="http://127.0.0.1:18092",
        bridge_token="0123456789abcdef",
    )
    xid = manager.begin_transaction(name="unsafe-callback")
    try:
        with pytest.raises(ValueError, match="process-local callbacks"):
            manager.register_branch(
                xid,
                resource_id="inventory",
                commit_cb=lambda *_: None,
                rollback_cb=lambda *_: None,
            )
    finally:
        manager.rollback_transaction(xid)
        manager.set_mode("local")
