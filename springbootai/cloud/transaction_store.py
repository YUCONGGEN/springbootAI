"""Durable transaction metadata storage for the HTTP compensation coordinator.

The store deliberately contains coordination metadata only.  Business data and
undo logs remain the responsibility of each resource manager.  SQLite WAL is a
good default for one host with multiple workers; deployments spanning hosts
must point all workers at a shared transactional database or use real Seata.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Any, Dict, Iterable, List, Optional


class SQLiteTransactionStore:
    """Small DB-API store with atomic status transitions and restart recovery."""

    _TERMINAL_STATUSES = {"COMMITTED", "ROLLED_BACK"}

    def __init__(self, path: str):
        if not path:
            raise ValueError("transaction store path is required")
        self.path = os.path.abspath(os.path.expanduser(path))
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._schema_lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=30,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._schema_lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS springpy_global_transactions (
                    xid TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    start_time REAL NOT NULL,
                    timeout_ms INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS springpy_transaction_branches (
                    branch_id TEXT PRIMARY KEY,
                    xid TEXT NOT NULL,
                    resource_id TEXT NOT NULL DEFAULT '',
                    callback_url TEXT NOT NULL DEFAULT '',
                    service_name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    registered_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (xid)
                        REFERENCES springpy_global_transactions (xid)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_springpy_tx_branches_xid
                    ON springpy_transaction_branches (xid);
                """
            )

    @staticmethod
    def _as_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        return dict(row) if row is not None else None

    def create_transaction(
        self,
        xid: str,
        name: str,
        status: str,
        start_time: float,
        timeout_ms: int,
    ) -> None:
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO springpy_global_transactions
                    (xid, name, status, start_time, timeout_ms, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (xid, name, status, start_time, int(timeout_ms), now, now),
            )

    def get_transaction(self, xid: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM springpy_global_transactions WHERE xid = ?", (xid,)
            ).fetchone()
        return self._as_dict(row)

    def list_transactions(self, statuses: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            if statuses:
                values = list(statuses)
                placeholders = ",".join("?" for _ in values)
                rows = connection.execute(
                    f"SELECT * FROM springpy_global_transactions "  # nosec B608 - generated placeholders only
                    f"WHERE status IN ({placeholders}) ORDER BY created_at",
                    values,
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM springpy_global_transactions ORDER BY created_at"
                ).fetchall()
        return [dict(row) for row in rows]

    def transition_transaction(
        self,
        xid: str,
        target_status: str,
        allowed_statuses: Iterable[str],
    ) -> bool:
        allowed = list(allowed_statuses)
        if not allowed:
            raise ValueError("allowed_statuses must not be empty")
        placeholders = ",".join("?" for _ in allowed)
        now = time.time()
        with self._connect() as connection:
            transition_sql = """
                UPDATE springpy_global_transactions
                SET status = ?, updated_at = ?
                WHERE xid = ? AND status IN (__STATUS_PLACEHOLDERS__)
            """.replace("__STATUS_PLACEHOLDERS__", placeholders)  # nosec B608
            cursor = connection.execute(
                transition_sql,
                [target_status, now, xid, *allowed],
            )
        return cursor.rowcount == 1

    def update_transaction(self, xid: str, status: str) -> bool:
        now = time.time()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE springpy_global_transactions
                SET status = ?, updated_at = ?
                WHERE xid = ?
                """,
                (status, now, xid),
            )
        return cursor.rowcount == 1

    def touch_transaction(self, xid: str, status: str) -> bool:
        """Refresh a completion lease without changing its state."""
        now = time.time()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE springpy_global_transactions
                SET updated_at = ?
                WHERE xid = ? AND status = ?
                """,
                (now, xid, status),
            )
        return cursor.rowcount == 1

    def reclaim_stale_transaction(
        self,
        xid: str,
        current_status: str,
        target_status: str,
        updated_before: float,
    ) -> bool:
        """Atomically reclaim a completion lease after it has gone stale."""
        now = time.time()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE springpy_global_transactions
                SET status = ?, updated_at = ?
                WHERE xid = ? AND status = ? AND updated_at <= ?
                """,
                (target_status, now, xid, current_status, updated_before),
            )
        return cursor.rowcount == 1

    def register_branch(self, branch: Dict[str, Any]) -> Dict[str, Any]:
        now = time.time()
        with self._connect() as connection:
            # Hold the transaction state lock until the branch is stored so a
            # concurrent commit cannot miss a newly registered branch.
            connection.execute("BEGIN IMMEDIATE")
            transaction = connection.execute(
                "SELECT xid, status FROM springpy_global_transactions WHERE xid = ?",
                (branch["xid"],),
            ).fetchone()
            if transaction is None:
                raise ValueError(f"Unknown transaction: {branch['xid']}")
            if transaction["status"] != "BEGIN":
                raise ValueError(
                    f"Transaction is not accepting branches: {branch['xid']} "
                    f"({transaction['status']})"
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO springpy_transaction_branches
                    (branch_id, xid, resource_id, callback_url, service_name,
                     status, registered_at, updated_at, last_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, '')
                """,
                (
                    branch["branch_id"],
                    branch["xid"],
                    branch.get("resource_id", ""),
                    branch.get("callback_url", ""),
                    branch.get("service_name", ""),
                    branch["status"],
                    branch.get("registered_at", now),
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM springpy_transaction_branches WHERE branch_id = ?",
                (branch["branch_id"],),
            ).fetchone()
            connection.commit()
        stored = self._as_dict(row)
        if stored is None or stored["xid"] != branch["xid"]:
            raise ValueError(f"Branch ID already belongs to another transaction: {branch['branch_id']}")
        return stored

    def list_branches(self, xid: str) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM springpy_transaction_branches WHERE xid = ? ORDER BY registered_at",
                (xid,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_branch(self, branch_id: str, status: str, last_error: str = "") -> bool:
        now = time.time()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE springpy_transaction_branches
                SET status = ?, last_error = ?, updated_at = ?
                WHERE branch_id = ?
                """,
                (status, last_error, now, branch_id),
            )
        return cursor.rowcount == 1

    def active_counts(self) -> Dict[str, int]:
        active = ("BEGIN", "COMMITTING", "ROLLING_BACK", "PARTIAL_COMMIT", "PARTIAL_ROLLBACK")
        placeholders = ",".join("?" for _ in active)
        with self._connect() as connection:
            transaction_count = connection.execute(
                f"SELECT COUNT(*) FROM springpy_global_transactions WHERE status IN ({placeholders})",  # nosec B608
                active,
            ).fetchone()[0]
            branch_count = connection.execute(
                """
                SELECT COUNT(*) FROM springpy_transaction_branches b
                JOIN springpy_global_transactions t ON t.xid = b.xid
                WHERE t.status IN (?, ?, ?, ?, ?)
                """,
                active,
            ).fetchone()[0]
        return {"active_global_tx": transaction_count, "active_branches": branch_count}
