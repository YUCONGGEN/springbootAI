import os
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.seata_integration]

if os.getenv("RUN_SEATA_INTEGRATION_TESTS") != "1":
    pytest.skip(
        "set RUN_SEATA_INTEGRATION_TESTS=1 with the Docker Seata stack running",
        allow_module_level=True,
    )


@pytest.fixture
def tcc_callback_server():
    events = []
    lock = threading.Lock()
    expected_token = os.getenv("SEATA_BRIDGE_TOKEN", "springpy-integration-secret")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.headers.get("X-Seata-Bridge-Token") != expected_token:
                self.send_error(401)
                return
            content_length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(content_length) or b"{}")
            parts = self.path.strip("/").split("/")
            if len(parts) != 4 or parts[:2] != ["seata", "branch"]:
                self.send_error(404)
                return
            with lock:
                events.append({"branch_id": parts[2], "action": parts[3], **payload})
            response = b'{"success":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, events, lock
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _wait_for_action(events, lock, branch_id, action):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with lock:
            matches = [
                event for event in events
                if event["branch_id"] == branch_id and event["action"] == action
            ]
        if matches:
            return matches[-1]
        time.sleep(0.05)
    pytest.fail(f"Seata TCC callback not received: branch={branch_id}, action={action}")


def test_real_seata_tcc_commit_and_rollback_contract(tcc_callback_server):
    from spring.cloud.seata import SeataTransactionManager

    callback_port, events, lock = tcc_callback_server
    manager = SeataTransactionManager()
    manager.configure(
        server_addr=os.getenv("SEATA_SERVER", "127.0.0.1:8091"),
        application_id=os.getenv("SEATA_APP_ID", "springpy-integration"),
        transaction_group=os.getenv("SEATA_TX_GROUP", "springpy_tx_group"),
        mode="distributed",
        bridge_url=os.getenv("SEATA_BRIDGE_URL", "http://127.0.0.1:18091"),
        bridge_token=os.getenv("SEATA_BRIDGE_TOKEN", "springpy-integration-secret"),
    )
    callback_host = os.getenv("SEATA_CALLBACK_HOST", "host.docker.internal")
    callback_url = f"http://{callback_host}:{callback_port}/seata/branch"

    try:
        committed_xid = manager.begin_transaction(name="springpy-contract-commit")
        assert committed_xid.count(":") >= 2
        assert manager.get_current_tx_id() == committed_xid
        commit_branch = manager.register_branch(
            committed_xid,
            branch_id="contract-commit",
            resource_id="inventory:SKU-1",
            callback_url=callback_url,
            service_name="inventory-test",
            metadata={"sku": "SKU-1", "quantity": 1},
        )
        prepared = _wait_for_action(events, lock, commit_branch, "prepare")
        assert prepared["xid"] == committed_xid
        assert prepared["metadata"] == {"sku": "SKU-1", "quantity": 1}
        assert manager.commit_transaction(committed_xid) is True
        committed = _wait_for_action(events, lock, commit_branch, "commit")
        assert committed["seataBranchId"] > 0
        assert manager.is_in_transaction() is False

        rolled_back_xid = manager.begin_transaction(name="springpy-contract-rollback")
        rollback_branch = manager.register_branch(
            rolled_back_xid,
            branch_id="contract-rollback",
            resource_id="account:user-1",
            callback_url=callback_url,
            service_name="account-test",
            metadata={"amount": "10.00"},
        )
        _wait_for_action(events, lock, rollback_branch, "prepare")
        assert manager.rollback_transaction(rolled_back_xid) is True
        rolled_back = _wait_for_action(events, lock, rollback_branch, "rollback")
        assert rolled_back["xid"] == rolled_back_xid
        assert manager.is_in_transaction() is False
    finally:
        if manager.is_in_transaction():
            manager.rollback_transaction(manager.get_current_tx_id())
        manager.set_mode("local")
