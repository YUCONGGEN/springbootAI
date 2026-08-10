import time
import threading

import pytest

from spring.cloud.seata import BranchStatus, SeataTransactionManager


@pytest.fixture
def http_manager(tmp_path):
    manager = SeataTransactionManager()
    manager.stop_recovery_worker()
    manager._cleanup_context()
    manager._global_transactions.clear()
    manager._branches.clear()
    manager._branch_callbacks.clear()
    manager.configure(
        mode="http",
        store_path=str(tmp_path / "seata-http.sqlite3"),
        recovery_grace_ms=0,
        recovery_interval_s=0,
    )
    yield manager
    manager.stop_recovery_worker()
    manager._cleanup_context()
    manager._global_transactions.clear()
    manager._branches.clear()
    manager._branch_callbacks.clear()
    manager.set_mode("local")
    manager._transaction_store = None
    manager._transaction_store_path = ""


def _simulate_worker_restart(manager):
    manager._cleanup_context()
    manager._global_transactions.clear()
    manager._branches.clear()
    manager._branch_callbacks.clear()


def test_http_transaction_metadata_survives_callback_cache_loss(http_manager):
    xid = http_manager.begin_transaction(name="durable")
    branch_id = http_manager.register_branch(
        xid,
        resource_id="orders-db",
        callback_url="http://orders.internal/seata/branch",
    )

    _simulate_worker_restart(http_manager)
    stored = http_manager.get_stored_transaction(xid)

    assert stored["status"] == "BEGIN"
    assert stored["name"] == "durable"
    assert stored["branches"][0]["branch_id"] == branch_id
    assert stored["branches"][0]["callback_url"].startswith("http://orders.internal")


def test_http_commit_is_idempotent_after_timeout_and_restart(http_manager):
    calls = []
    xid = http_manager.begin_transaction(name="idempotent", timeout=50)
    http_manager.register_branch(
        xid,
        resource_id="orders-db",
        commit_cb=lambda current_xid, branch_id: calls.append(branch_id),
        rollback_cb=lambda *_: None,
    )
    assert http_manager.commit_transaction(xid) is True
    time.sleep(0.08)

    _simulate_worker_restart(http_manager)
    assert http_manager.commit_transaction(xid) is True
    assert len(calls) == 1
    assert http_manager.get_stored_transaction(xid)["status"] == "COMMITTED"


def test_http_startup_recovery_rolls_back_expired_remote_branch(http_manager, monkeypatch):
    xid = http_manager.begin_transaction(name="recover", timeout=1)
    http_manager.register_branch(
        xid,
        resource_id="inventory-db",
        callback_url="http://inventory.internal/seata/branch",
    )
    time.sleep(0.02)
    _simulate_worker_restart(http_manager)

    actions = []
    monkeypatch.setattr(
        http_manager,
        "_notify_branch",
        lambda branch, action: actions.append((branch["branch_id"], action)) or True,
    )
    result = http_manager.recover_pending_transactions()

    assert xid in result["rolled_back"]
    assert actions == [(http_manager.get_stored_transaction(xid)["branches"][0]["branch_id"], "rollback")]
    assert http_manager.get_stored_transaction(xid)["status"] == "ROLLED_BACK"


def test_http_local_callback_loss_fails_closed_and_persists_partial_status(http_manager):
    xid = http_manager.begin_transaction(name="fail-closed")
    branch_id = http_manager.register_branch(
        xid,
        resource_id="payment-db",
        commit_cb=lambda *_: None,
        rollback_cb=lambda *_: None,
    )
    _simulate_worker_restart(http_manager)

    assert http_manager.commit_transaction(xid) is False
    stored = http_manager.get_stored_transaction(xid)
    branch = next(item for item in stored["branches"] if item["branch_id"] == branch_id)
    assert stored["status"] == "PARTIAL_COMMIT"
    assert branch["status"] == BranchStatus.FAILED
    assert "callback failed" in branch["last_error"]


def test_http_branch_registration_is_rejected_after_completion_started(http_manager):
    xid = http_manager.begin_transaction(name="sealed")
    http_manager._transaction_store.update_transaction(xid, "COMMITTING")

    with pytest.raises(ValueError, match="not accepting branches"):
        http_manager.register_branch(xid, resource_id="late-branch")


def test_http_recovery_worker_has_worker_owned_lifecycle(http_manager):
    http_manager._recovery_interval_s = 0.01
    http_manager.start_recovery_worker()
    assert http_manager._recovery_thread is not None
    assert http_manager._recovery_thread.is_alive()
    http_manager.stop_recovery_worker()
    assert http_manager._recovery_thread is None


def test_concurrent_http_commit_claims_transaction_once(http_manager):
    calls = []
    calls_lock = threading.Lock()
    start = threading.Barrier(3)
    xid = http_manager.begin_transaction(name="concurrent")

    def commit_callback(*_):
        with calls_lock:
            calls.append("commit")
        time.sleep(0.03)

    http_manager.register_branch(
        xid,
        resource_id="orders-db",
        commit_cb=commit_callback,
        rollback_cb=lambda *_: None,
    )
    http_manager._cleanup_context()
    results = []

    def commit():
        start.wait()
        results.append(http_manager.commit_transaction(xid))

    workers = [threading.Thread(target=commit) for _ in range(2)]
    for worker in workers:
        worker.start()
    start.wait()
    for worker in workers:
        worker.join(timeout=2)

    assert all(not worker.is_alive() for worker in workers)
    assert calls == ["commit"]
    assert any(results)
    assert http_manager.get_stored_transaction(xid)["status"] == "COMMITTED"
