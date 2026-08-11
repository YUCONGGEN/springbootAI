"""
连接池故障注入测试
测试连接池在各种故障场景下的弹性表现：池满超时、连接有效性检测、泄漏检测、优雅关闭、坏连接恢复
"""

import sys
import time
import threading
from pathlib import Path
from unittest.mock import patch
from typing import Any, Dict

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import tests._test_helpers  # noqa: F401  安装模块mock

from spring.orm.pymybatis.pool.connection_pool import (
    ConnectionPool,
    PooledConnection,
)


class MockConnection:
    """模拟数据库连接"""

    def __init__(self, valid: bool = True, on_ping_error: Exception = None):
        self.valid = valid
        self.on_ping_error = on_ping_error
        self.closed = False
        self.rollback_called = False
        self.ping_count = 0

    def ping(self):
        self.ping_count += 1
        if not self.valid:
            raise Exception("Connection is invalid")
        if self.on_ping_error:
            raise self.on_ping_error

    def close(self):
        self.closed = True

    def rollback(self):
        self.rollback_called = True

    def isclosed(self):
        return self.closed


class ResilientTestPool(ConnectionPool):
    """用于故障注入测试的连接池实现"""

    def __init__(self, config: Dict[str, Any] = None,
                 create_connection_error: Exception = None,
                 new_connections_valid: bool = True):
        self._create_called = 0
        self._close_called = 0
        self._create_connection_error = create_connection_error
        self._new_connections_valid = new_connections_valid
        self._created_connections = []

        default_config = {
            'min_size': 0,
            'max_size': 3,
            'max_idle': 60,
            'wait_timeout': 1.0,
            'validation_interval': 300,
            'leak_detection_enabled': False,
            'leak_timeout': 10,
            'circuit_breaker_enabled': False,
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)

    def _create_connection(self) -> Any:
        self._create_called += 1
        if self._create_connection_error:
            raise self._create_connection_error
        conn = MockConnection(valid=self._new_connections_valid)
        self._created_connections.append(conn)
        return conn

    def _close_connection(self, connection: Any) -> None:
        self._close_called += 1
        if hasattr(connection, 'close'):
            connection.close()

    def set_new_connections_valid(self, valid: bool):
        """设置后续新创建连接是否有效"""
        self._new_connections_valid = valid

    def set_create_error(self, error: Exception = None):
        """设置创建连接时抛出的异常"""
        self._create_connection_error = error


class TestConnectionPoolResilience:
    """连接池弹性与故障注入测试"""

    def test_pool_exhaustion_raises_timeout(self):
        """测试池满时等待超时抛出明确异常"""
        pool = ResilientTestPool({
            'min_size': 0,
            'max_size': 2,
            'wait_timeout': 0.5,
            'leak_detection_enabled': False,
        })

        conns = []
        try:
            c1 = pool.get_connection()
            conns.append(c1)
            c2 = pool.get_connection()
            conns.append(c2)

            assert pool.get_pool_stats()['active_connections'] == 2
            assert pool.get_pool_stats()['total_connections'] == 2

            start = time.monotonic()
            with pytest.raises(ConnectionError, match="获取连接超时|超时|max_size"):
                pool.get_connection()
            elapsed = time.monotonic() - start

            assert elapsed >= 0.4, f"应等待约wait_timeout时间，实际等待{elapsed}s"
            assert elapsed < 2.0, "超时等待不应过长"
        finally:
            for c in conns:
                try:
                    pool.return_connection(c)
                except Exception:
                    pass
            pool.close()

    def test_connection_validation(self):
        """测试连接有效性检测：无效连接在获取时被自动丢弃重连"""
        pool = ResilientTestPool({
            'min_size': 0,
            'max_size': 3,
            'wait_timeout': 1.0,
            'validation_interval': 300,
            'leak_detection_enabled': False,
        })
        pool._stop_event.set()

        try:
            bad_conn = MockConnection(valid=False)
            bad_pooled = PooledConnection(bad_conn, pool, time.monotonic())
            pool._pool.put(bad_pooled)
            with pool._lock:
                pool._total_connections = 1

            valid_conn_before = pool._create_called
            good_conn = pool.get_connection()

            assert bad_conn.closed is True, "无效连接应被关闭"
            assert pool._create_called > valid_conn_before, "应创建新连接替代无效连接"
            assert good_conn.is_valid() is True, "返回的连接应是有效的"

            pool.return_connection(good_conn)
        finally:
            pool.close()

    def test_leak_detection(self):
        """测试泄漏检测：长时间未归还的连接触发警告日志"""

        pool = ResilientTestPool({
            'min_size': 0,
            'max_size': 2,
            'wait_timeout': 1.0,
            'leak_detection_enabled': True,
            'leak_timeout': 0.1,
        })
        pool._stop_event.set()

        try:
            leaked_conn = pool.get_connection()
            non_leaked = pool.get_connection()

            non_leaked._checkout_time = time.monotonic() - 0.01
            leaked_conn._checkout_time = time.monotonic() - 1.0

            with patch('spring.orm.pymybatis.pool.connection_pool.logger') as mock_logger:
                pool._detect_leaks()

                warning_calls = [
                    call for call in mock_logger.warning.call_args_list
                    if '泄漏' in str(call) or 'leak' in str(call).lower() or '借出' in str(call)
                ]
                assert len(warning_calls) >= 1, f"应记录连接泄漏警告，实际警告调用: {mock_logger.warning.call_args_list}"

            pool.return_connection(non_leaked)
        finally:
            pool._stop_event.set()
            pool.close()

    def test_graceful_close(self):
        """测试优雅关闭：等待活动连接归还后再关闭"""
        pool = ResilientTestPool({
            'min_size': 0,
            'max_size': 3,
            'wait_timeout': 1.0,
            'leak_detection_enabled': False,
        })
        pool._stop_event.set()

        c1 = pool.get_connection()
        c2 = pool.get_connection()
        c3 = pool.get_connection()

        assert pool.get_pool_stats()['active_connections'] == 3
        assert pool.get_pool_stats()['closed'] is False

        returned_during_close = threading.Event()

        def return_later():
            time.sleep(0.2)
            pool.return_connection(c1)
            pool.return_connection(c2)
            pool.return_connection(c3)
            returned_during_close.set()

        returner = threading.Thread(target=return_later, daemon=True)
        returner.start()

        close_started = threading.Event()

        def close_after_start():
            close_started.set()
            pool.close()

        closer = threading.Thread(target=close_after_start, daemon=True)
        closer.start()

        close_started.wait(timeout=2)
        returned_during_close.wait(timeout=3)
        closer.join(timeout=3)

        assert returned_during_close.is_set(), "所有连接应被归还"
        assert pool.get_pool_stats()['closed'] is True, "连接池最终应关闭"
        assert pool._close_called >= 3, "所有连接应被关闭"

    def test_bad_connection_recovery(self):
        """测试坏连接自动回收重连：获取到坏连接时自动创建新连接"""

        class FlakyConnection:
            def __init__(self, valid=True):
                self.closed = False
                self._valid = valid

            def ping(self):
                if not self._valid:
                    raise Exception("Connection is stale")

            def close(self):
                self.closed = True

            def rollback(self):
                pass

        class RecoveryPool(ConnectionPool):
            def __init__(self):
                self._create_count = 0
                self._close_count = 0
                super().__init__({
                    'min_size': 0,
                    'max_size': 5,
                    'max_idle': 60,
                    'wait_timeout': 2.0,
                    'validation_interval': 300,
                    'leak_detection_enabled': False,
                    'circuit_breaker_enabled': False,
                })

            def _create_connection(self):
                self._create_count += 1
                return FlakyConnection(valid=True)

            def _close_connection(self, conn):
                self._close_count += 1
                conn.close()

        pool = RecoveryPool()
        pool._stop_event.set()

        try:
            invalid_conn = FlakyConnection(valid=False)
            invalid_pooled = PooledConnection(invalid_conn, pool, time.monotonic())
            invalid_pooled.last_used_at = time.monotonic()
            pool._pool.put(invalid_pooled)
            with pool._lock:
                pool._total_connections = 1

            before_create = pool._create_count
            conn = pool.get_connection()

            assert invalid_conn.closed is True, "初始无效连接应被关闭"
            assert pool._create_count > before_create, "应创建新连接替代无效连接"
            assert conn is not None
            assert conn.is_valid() is True

            pool.return_connection(conn)
        finally:
            pool.close()

    def test_return_after_close_disposes(self):
        """测试连接池关闭后归还的连接被正确处置"""
        pool = ResilientTestPool({
            'min_size': 0,
            'max_size': 2,
            'wait_timeout': 1.0,
            'leak_detection_enabled': False,
        })
        pool._stop_event.set()

        conn = pool.get_connection()
        raw_conn = conn.connection

        pool.close()
        assert pool.get_pool_stats()['closed'] is True

        pool.return_connection(conn)
        assert raw_conn.closed is True, "关闭后归还的连接应被关闭"

    def test_double_return_raises_error(self):
        """测试重复归还连接抛出异常"""
        pool = ResilientTestPool({
            'min_size': 0,
            'max_size': 2,
            'wait_timeout': 1.0,
            'leak_detection_enabled': False,
        })
        pool._stop_event.set()

        try:
            conn = pool.get_connection()
            pool.return_connection(conn)

            with pytest.raises(ValueError, match="已归还|already|重复"):
                pool.return_connection(conn)
        finally:
            pool.close()

    def test_pool_stats_consistency(self):
        """测试连接池统计信息一致性"""
        pool = ResilientTestPool({
            'min_size': 0,
            'max_size': 3,
            'wait_timeout': 1.0,
            'leak_detection_enabled': False,
        })
        pool._stop_event.set()

        try:
            stats = pool.get_pool_stats()
            assert stats['active_connections'] == 0
            assert stats['idle_connections'] == 0
            assert stats['total_connections'] == 0
            assert stats['closed'] is False

            c1 = pool.get_connection()
            c2 = pool.get_connection()

            stats = pool.get_pool_stats()
            assert stats['active_connections'] == 2
            assert stats['total_connections'] == 2

            pool.return_connection(c1)
            stats = pool.get_pool_stats()
            assert stats['active_connections'] == 1
            assert stats['idle_connections'] >= 1

            pool.return_connection(c2)
            stats = pool.get_pool_stats()
            assert stats['active_connections'] == 0
        finally:
            pool.close()

    def test_context_manager_connection(self):
        """测试池化连接上下文管理器自动归还"""
        pool = ResilientTestPool({
            'min_size': 0,
            'max_size': 2,
            'wait_timeout': 1.0,
            'leak_detection_enabled': False,
        })
        pool._stop_event.set()

        try:
            with pool.get_connection() as conn:
                assert conn.in_use is True
                raw = conn.connection
                cursor_like = raw

            assert conn.in_use is False, "上下文管理器退出后连接应标记为空闲"
            stats = pool.get_pool_stats()
            assert stats['active_connections'] == 0, "连接应被自动归还"
        finally:
            pool.close()

    def test_connection_from_wrong_pool_rejected(self):
        """测试不属于当前池的连接归还被拒绝"""
        pool1 = ResilientTestPool({
            'min_size': 0, 'max_size': 1, 'wait_timeout': 1.0,
            'leak_detection_enabled': False,
        })
        pool2 = ResilientTestPool({
            'min_size': 0, 'max_size': 1, 'wait_timeout': 1.0,
            'leak_detection_enabled': False,
        })
        pool1._stop_event.set()
        pool2._stop_event.set()

        try:
            c1 = pool1.get_connection()

            with pytest.raises(ValueError, match="不属于|belong"):
                pool2.return_connection(c1)

            pool1.return_connection(c1)
        finally:
            pool1.close()
            pool2.close()

    def test_rollback_on_return(self):
        """测试归还连接时自动回滚未提交事务"""
        pool = ResilientTestPool({
            'min_size': 0,
            'max_size': 1,
            'wait_timeout': 1.0,
            'leak_detection_enabled': False,
        })
        pool._stop_event.set()

        try:
            conn = pool.get_connection()
            raw = conn.connection

            assert raw.rollback_called is False
            pool.return_connection(conn)
            assert raw.rollback_called is True, "归还时应自动回滚"
        finally:
            pool.close()
