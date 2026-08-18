"""
生产就绪功能测试
测试数据库迁移、密钥管理、重放防护、优雅退出、Nonce缓存等生产级功能
"""

import os
import sys
import time
import tempfile
import shutil
import sqlite3
import threading
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import tests._test_helpers  # noqa: F401  安装模块mock


class MockPooledConnection:
    """模拟池化连接包装类"""
    def __init__(self, conn):
        self.connection = conn


class SQLitePoolForMigration:
    """为迁移测试提供的SQLite连接池适配器"""
    def __init__(self, db_path=':memory:'):
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row

    def get_connection(self):
        return MockPooledConnection(self._conn)

    def return_connection(self, pooled):
        pass


class TestMigrationManager:
    """测试数据库迁移管理器"""

    def setup_method(self):
        """每个测试前创建临时目录和SQLite内存数据库"""
        self.temp_dir = tempfile.mkdtemp()
        self.migrations_dir = Path(self.temp_dir) / 'migrations'
        self.migrations_dir.mkdir()
        self.pool = SQLitePoolForMigration(':memory:')

    def teardown_method(self):
        """清理临时目录"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_migrate_creates_version_table(self):
        """测试迁移时自动创建schema_version表"""
        from springbootai.orm.migration import MigrationManager

        manager = MigrationManager(self.pool, str(self.migrations_dir), dialect='sqlite')
        cursor = self.pool._conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
        result = cursor.fetchone()
        assert result is not None, "schema_version表应被自动创建"

    def test_migrate_applies_pending_migrations(self):
        """测试执行待执行的迁移文件"""
        from springbootai.orm.migration import MigrationManager

        migration_file = self.migrations_dir / 'V1__create_test_table.sql'
        migration_file.write_text("""
            CREATE TABLE test_table (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
        """, encoding='utf-8')

        manager = MigrationManager(self.pool, str(self.migrations_dir), dialect='sqlite')
        executed = manager.migrate()

        assert len(executed) == 1, "应执行1条迁移"
        assert executed[0].version == '1'

        cursor = self.pool._conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='test_table'")
        assert cursor.fetchone() is not None, "test_table应被创建"

    def test_migrate_multiple_versions_in_order(self):
        """测试按版本号顺序执行多个迁移"""
        from springbootai.orm.migration import MigrationManager

        (self.migrations_dir / 'V2__add_column.sql').write_text(
            "ALTER TABLE test_table ADD COLUMN email TEXT;", encoding='utf-8'
        )
        (self.migrations_dir / 'V1__create_table.sql').write_text(
            "CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT);", encoding='utf-8'
        )

        manager = MigrationManager(self.pool, str(self.migrations_dir), dialect='sqlite')
        executed = manager.migrate()

        assert len(executed) == 2
        versions = [r.version for r in executed]
        assert versions == ['1', '2'], "迁移应按版本号顺序执行"

    def test_migrate_skips_already_applied(self):
        """测试已执行的迁移不会重复执行"""
        from springbootai.orm.migration import MigrationManager

        (self.migrations_dir / 'V1__create_table.sql').write_text(
            "CREATE TABLE test_table (id INTEGER PRIMARY KEY);", encoding='utf-8'
        )

        manager = MigrationManager(self.pool, str(self.migrations_dir), dialect='sqlite')
        first_run = manager.migrate()
        assert len(first_run) == 1

        second_run = manager.migrate()
        assert len(second_run) == 0, "已执行的迁移不应重复执行"

    def test_status_reports_pending_and_applied(self):
        """测试status()方法正确报告迁移状态"""
        from springbootai.orm.migration import MigrationManager, MigrationState

        (self.migrations_dir / 'V1__first.sql').write_text(
            "CREATE TABLE t1 (id INTEGER);", encoding='utf-8'
        )
        (self.migrations_dir / 'V2__second.sql').write_text(
            "CREATE TABLE t2 (id INTEGER);", encoding='utf-8'
        )

        manager = MigrationManager(self.pool, str(self.migrations_dir), dialect='sqlite')
        manager.migrate()

        (self.migrations_dir / 'V3__third.sql').write_text(
            "CREATE TABLE t3 (id INTEGER);", encoding='utf-8'
        )

        status = manager.status()
        assert status['total'] == 3
        assert status['applied'] == 2
        assert status['pending'] == 1

        states = {m['version']: m['state'] for m in status['migrations']}
        assert states['1'] == MigrationState.SUCCESS
        assert states['2'] == MigrationState.SUCCESS
        assert states['3'] == MigrationState.PENDING

    def test_checksum_mismatch_raises_error(self):
        """测试已应用迁移文件被篡改时抛出checksum不匹配异常"""
        from springbootai.orm.migration import MigrationManager, MigrationError

        v1_file = self.migrations_dir / 'V1__test.sql'
        v1_file.write_text("CREATE TABLE t1 (id INTEGER);", encoding='utf-8')

        manager = MigrationManager(self.pool, str(self.migrations_dir), dialect='sqlite')
        manager.migrate()

        v1_file.write_text("CREATE TABLE t1 (id INTEGER, name TEXT);", encoding='utf-8')

        with pytest.raises(MigrationError, match="Checksum mismatch"):
            manager.migrate()

    def test_repair_removes_failed_records(self):
        """测试repair()方法删除失败的迁移记录"""
        from springbootai.orm.migration import MigrationManager

        manager = MigrationManager(self.pool, str(self.migrations_dir), dialect='sqlite')

        cursor = self.pool._conn.cursor()
        cursor.execute(
            'INSERT INTO "schema_version" (version, description, script, checksum, installed_on, execution_time, success) VALUES (?, ?, ?, ?, ?, ?, ?)',
            ('99', 'failed_migration', 'V99__fail.sql', 'abc123', int(time.time()), 0, 0)
        )
        self.pool._conn.commit()

        repaired = manager.repair()
        assert repaired == 1, "应修复1条失败记录"

        cursor.execute('SELECT COUNT(*) FROM "schema_version" WHERE success = 0')
        assert cursor.fetchone()[0] == 0, "失败记录应被删除"


class TestSecretManager:
    """测试密钥管理器"""

    def setup_method(self):
        """每个测试前重置SecretManager单例"""
        from springbootai.security.secret_manager import SecretManager
        SecretManager.reset()
        self._orig_env = os.environ.copy()

    def teardown_method(self):
        """恢复环境变量并重置单例"""
        os.environ.clear()
        os.environ.update(self._orig_env)
        from springbootai.security.secret_manager import SecretManager
        SecretManager.reset()

    def test_loads_from_spring_secrets_prefix(self):
        """测试从SPRING_SECRETS_前缀环境变量加载密钥"""
        from springbootai.security.secret_manager import SecretManager

        os.environ['SPRING_SECRETS_DB_PASSWORD'] = 'my_secret_pass_123'
        mgr = SecretManager()

        assert mgr.get_secret('db_password') == 'my_secret_pass_123'

    def test_get_secret_case_insensitive(self):
        """测试密钥名称大小写不敏感"""
        from springbootai.security.secret_manager import SecretManager

        os.environ['SPRING_SECRETS_REDIS_PASSWORD'] = 'redis_secret'
        mgr = SecretManager()

        assert mgr.get_secret('Redis-Password') == 'redis_secret'
        assert mgr.get_secret('REDIS_PASSWORD') == 'redis_secret'

    def test_get_secret_from_direct_env_var(self):
        """测试从直接命名的环境变量获取密钥"""
        from springbootai.security.secret_manager import SecretManager

        os.environ['JWT_SECRET_KEY'] = 'direct_jwt_secret'
        mgr = SecretManager()

        assert mgr.get_secret('jwt_secret_key') == 'direct_jwt_secret'

    def test_get_secret_returns_default_when_missing(self):
        """测试密钥不存在时返回默认值"""
        from springbootai.security.secret_manager import SecretManager

        mgr = SecretManager()
        result = mgr.get_secret('nonexistent_key', default='default_value')

        assert result == 'default_value'

    def test_require_secret_raises_when_missing(self):
        """测试require_secret在密钥不存在时抛出异常"""
        from springbootai.security.secret_manager import SecretManager

        mgr = SecretManager()

        with pytest.raises(ValueError, match="Required secret"):
            mgr.require_secret('definitely_missing_secret')

    def test_require_secret_returns_value_when_present(self):
        """测试require_secret在密钥存在时返回值"""
        from springbootai.security.secret_manager import SecretManager

        os.environ['SPRING_SECRETS_API_KEY'] = 'test_api_key_value'
        mgr = SecretManager()

        assert mgr.require_secret('api_key') == 'test_api_key_value'

    def test_base64_decode(self):
        """测试base64编码密钥解码"""
        import base64
        from springbootai.security.secret_manager import SecretManager

        original = 'my_plain_secret'
        encoded = base64.b64encode(original.encode('utf-8')).decode('utf-8')
        os.environ['SPRING_SECRETS_ENCODED_SECRET'] = encoded
        mgr = SecretManager()

        result = mgr.get_secret('encoded_secret', decode_base64=True)
        assert result == original

    def test_base64_decode_invalid_returns_raw(self):
        """测试无效base64时返回原始值"""
        from springbootai.security.secret_manager import SecretManager

        os.environ['SPRING_SECRETS_BAD_B64'] = 'not_valid_base64!!!'
        mgr = SecretManager()

        result = mgr.get_secret('bad_b64', decode_base64=True)
        assert result == 'not_valid_base64!!!'

    def test_mask_secret_function(self):
        """测试密钥脱敏函数"""
        from springbootai.security.secret_manager import mask_secret

        secret = 'abcdefghijklmnop'
        masked = mask_secret(secret, show_chars=4)
        assert masked == 'abcd***mnop'
        assert 'efghijkl' not in masked

    def test_mask_secret_short_value(self):
        """测试短密钥脱敏返回***"""
        from springbootai.security.secret_manager import mask_secret

        assert mask_secret('ab') == '***'
        assert mask_secret('') == '***'
        assert mask_secret(None) == '***'

    def test_set_secret_for_rotation(self):
        """测试运行时设置密钥（密钥轮换）"""
        from springbootai.security.secret_manager import SecretManager

        mgr = SecretManager()
        mgr.set_secret('rotated_key', 'new_value_456')

        assert mgr.get_secret('rotated_key') == 'new_value_456'

    def test_is_sensitive_key(self):
        """测试敏感键名判断"""
        from springbootai.security.secret_manager import is_sensitive_key

        assert is_sensitive_key('db_password') is True
        assert is_sensitive_key('api_key') is True
        assert is_sensitive_key('secret_token') is True
        assert is_sensitive_key('username') is False
        assert is_sensitive_key('host') is False


class TestReplayProtection:
    """测试重放攻击防护"""

    def setup_method(self):
        """初始化重放保护器"""
        from springbootai.security.replay_protection import ReplayProtection
        self.secret = 'test-secret-key-for-replay-protection'
        self.protector = ReplayProtection(secret_key=self.secret, timestamp_window=10)

    def _generate_valid_request(self, body='', method='POST', path='/api/test'):
        """生成一个有效的请求参数"""
        timestamp = str(int(time.time()))
        nonce = os.urandom(16).hex()
        signature = self.protector.generate_signature(timestamp, nonce, body, method, path)
        return timestamp, nonce, signature

    def test_valid_request_passes(self):
        """测试有效请求通过验证"""

        timestamp, nonce, signature = self._generate_valid_request()
        valid, reason = self.protector.validate_request(
            timestamp=timestamp, nonce=nonce, signature=signature,
            body='', method='POST', path='/api/test'
        )

        assert valid is True
        assert reason == 'OK'

    def test_duplicate_nonce_rejected(self):
        """测试重复nonce被拒绝"""
        timestamp = str(int(time.time()))
        nonce = 'unique_nonce_value_12345678'
        signature = self.protector.generate_signature(timestamp, nonce)

        valid1, _ = self.protector.validate_request(timestamp, nonce, signature)
        assert valid1 is True

        valid2, reason = self.protector.validate_request(timestamp, nonce, signature)
        assert valid2 is False
        assert 'Duplicate nonce' in reason

    def test_expired_timestamp_rejected(self):
        """测试过期时间戳被拒绝"""
        old_timestamp = str(int(time.time()) - 600)
        nonce = os.urandom(16).hex()
        signature = self.protector.generate_signature(old_timestamp, nonce)

        valid, reason = self.protector.validate_request(old_timestamp, nonce, signature)
        assert valid is False
        assert 'Timestamp expired' in reason

    def test_future_timestamp_rejected(self):
        """测试未来太久的时间戳被拒绝"""
        future_timestamp = str(int(time.time()) + 600)
        nonce = os.urandom(16).hex()
        signature = self.protector.generate_signature(future_timestamp, nonce)

        valid, reason = self.protector.validate_request(future_timestamp, nonce, signature)
        assert valid is False
        assert 'Timestamp expired' in reason

    def test_invalid_signature_rejected(self):
        """测试无效签名被拒绝"""
        timestamp = str(int(time.time()))
        nonce = os.urandom(16).hex()
        wrong_signature = '0000000000000000000000000000000000000000000000000000000000000000'

        valid, reason = self.protector.validate_request(timestamp, nonce, wrong_signature)
        assert valid is False
        assert 'Invalid signature' in reason

    def test_invalid_timestamp_format_rejected(self):
        """测试无效时间戳格式被拒绝"""
        nonce = os.urandom(16).hex()

        valid, reason = self.protector.validate_request('not_a_timestamp', nonce, '')
        assert valid is False
        assert 'Invalid timestamp' in reason

    def test_short_nonce_rejected(self):
        """测试过短的nonce被拒绝"""
        timestamp = str(int(time.time()))

        valid, reason = self.protector.validate_request(timestamp, 'short', '')
        assert valid is False
        assert 'nonce' in reason.lower() or '8 character' in reason.lower()

    def test_millisecond_timestamp_supported(self):
        """测试毫秒级时间戳自动识别（不验证签名，因签名需与原始timestamp一致）"""
        now = int(time.time())
        timestamp_ms = str(now * 1000)
        nonce = os.urandom(16).hex()

        valid, reason = self.protector.validate_request(
            timestamp_ms, nonce, ''
        )
        assert valid is True, f"毫秒时间戳应被正确识别（无签名模式）: {reason}"

    def test_validate_headers_method(self):
        """测试从HTTP头验证请求"""
        timestamp, nonce, signature = self._generate_valid_request(body='{"data":1}')
        headers = {
            'X-Timestamp': timestamp,
            'X-Nonce': nonce,
            'X-Signature': signature,
        }

        valid, _ = self.protector.validate_headers(headers, body='{"data":1}', method='POST', path='/api/test')
        assert valid is True

    def test_body_tampering_detected(self):
        """测试请求体篡改导致签名验证失败"""
        timestamp, nonce, signature = self._generate_valid_request(body='original_body')

        valid, reason = self.protector.validate_request(
            timestamp, nonce, signature, body='tampered_body'
        )
        assert valid is False
        assert 'Invalid signature' in reason


class TestGracefulShutdown:
    """测试优雅退出管理器"""

    def test_register_and_execute_hooks(self):
        """测试注册关闭钩子并执行"""
        from springbootai.core.graceful_shutdown import GracefulShutdown

        shutdown = GracefulShutdown(drain_timeout=1, shutdown_timeout=1)
        hook_called = []

        def my_hook():
            hook_called.append('called')

        shutdown.register_hook('test_hook', my_hook)

        shutdown.initiate_shutdown()
        shutdown.wait_for_shutdown(timeout=5)

        assert 'called' in hook_called

    def test_hooks_execute_in_order(self):
        """测试钩子按order顺序执行"""
        from springbootai.core.graceful_shutdown import GracefulShutdown

        shutdown = GracefulShutdown(drain_timeout=1, shutdown_timeout=1)
        execution_order = []

        shutdown.register_hook('third', lambda: execution_order.append(3), order=30)
        shutdown.register_hook('first', lambda: execution_order.append(1), order=10)
        shutdown.register_hook('second', lambda: execution_order.append(2), order=20)

        shutdown.initiate_shutdown()
        shutdown.wait_for_shutdown(timeout=5)

        assert execution_order == [1, 2, 3]

    def test_drain_waits_for_inflight_requests(self):
        """测试排空阶段等待在途请求完成"""
        from springbootai.core.graceful_shutdown import GracefulShutdown

        shutdown = GracefulShutdown(drain_timeout=3, shutdown_timeout=1)
        finished = threading.Event()

        shutdown.request_started()
        shutdown.request_started()

        def finish_requests():
            time.sleep(0.5)
            shutdown.request_finished()
            shutdown.request_finished()
            finished.set()

        t = threading.Thread(target=finish_requests, daemon=True)
        t.start()

        start = time.monotonic()
        shutdown.initiate_shutdown()
        shutdown.wait_for_shutdown(timeout=5)
        elapsed = time.monotonic() - start

        assert finished.is_set()
        assert elapsed < 2, "应在请求完成后快速关闭，不应等满drain_timeout"

    def test_drain_timeout_proceeds(self):
        """测试排空超时后继续关闭流程"""
        from springbootai.core.graceful_shutdown import GracefulShutdown

        shutdown = GracefulShutdown(drain_timeout=0.3, shutdown_timeout=1)
        hook_called = threading.Event()

        shutdown.register_hook('late_hook', hook_called.set)

        shutdown.request_started()

        shutdown.initiate_shutdown()
        shutdown.wait_for_shutdown(timeout=5)

        assert hook_called.is_set(), "排空超时后钩子仍应执行"

    def test_is_draining_flag(self):
        """测试is_draining状态标志"""
        from springbootai.core.graceful_shutdown import GracefulShutdown, ShutdownPhase

        shutdown = GracefulShutdown(drain_timeout=1, shutdown_timeout=1)

        assert shutdown.is_draining is False
        assert shutdown.phase == ShutdownPhase.RUNNING

        shutdown.initiate_shutdown()
        shutdown.wait_for_shutdown(timeout=5)

        assert shutdown.is_draining is True
        assert shutdown.phase == ShutdownPhase.STOPPED

    def test_hook_exception_does_not_stop_others(self):
        """测试单个钩子异常不影响其他钩子执行"""
        from springbootai.core.graceful_shutdown import GracefulShutdown

        shutdown = GracefulShutdown(drain_timeout=0.1, shutdown_timeout=1)
        second_called = []

        def bad_hook():
            raise RuntimeError("hook failed!")

        shutdown.register_hook('bad', bad_hook, order=1)
        shutdown.register_hook('good', lambda: second_called.append(True), order=2)

        shutdown.initiate_shutdown()
        shutdown.wait_for_shutdown(timeout=5)

        assert len(second_called) == 1, "异常钩子后的钩子仍应执行"

    def test_request_counting(self):
        """测试在途请求计数"""
        from springbootai.core.graceful_shutdown import GracefulShutdown

        shutdown = GracefulShutdown()

        assert shutdown.inflight_count == 0

        shutdown.request_started()
        shutdown.request_started()
        assert shutdown.inflight_count == 2

        shutdown.request_finished()
        assert shutdown.inflight_count == 1

        shutdown.request_finished()
        assert shutdown.inflight_count == 0


class TestNonceCache:
    """测试LRU Nonce缓存"""

    def test_check_and_add_new_nonce(self):
        """测试新nonce检查并添加成功"""
        from springbootai.security.replay_protection import NonceCache

        cache = NonceCache(max_size=100, ttl=300)
        result = cache.check_and_add('new_nonce_value_123')

        assert result is True

    def test_duplicate_nonce_detected(self):
        """测试重复nonce被检测到"""
        from springbootai.security.replay_protection import NonceCache

        cache = NonceCache(max_size=100, ttl=300)

        first = cache.check_and_add('duplicate_nonce')
        second = cache.check_and_add('duplicate_nonce')

        assert first is True
        assert second is False

    def test_capacity_limit_lru_eviction(self):
        """测试容量限制触发LRU淘汰"""
        from springbootai.security.replay_protection import NonceCache

        cache = NonceCache(max_size=5, ttl=300)

        for i in range(5):
            cache.check_and_add(f'nonce_{i}')

        assert len(cache._cache) == 5

        cache.check_and_add('nonce_new')

        assert len(cache._cache) == 5
        assert 'nonce_0' not in cache._cache, "最早插入的nonce应被LRU淘汰"
        assert 'nonce_new' in cache._cache

    def test_expired_nonce_cleanup(self):
        """测试过期nonce清理"""
        from springbootai.security.replay_protection import NonceCache

        cache = NonceCache(max_size=100, ttl=1)

        cache.check_and_add('expired_nonce')
        cache._cache['expired_nonce'] = time.time() - 10

        cache.check_and_add('fresh_nonce')

        assert 'expired_nonce' not in cache._cache, "过期nonce应被清理"

    def test_thread_safety(self):
        """测试多线程并发访问缓存的线程安全性"""
        from springbootai.security.replay_protection import NonceCache
        import random

        cache = NonceCache(max_size=1000, ttl=300)
        errors = []
        results = set()
        lock = threading.Lock()

        def worker(thread_id):
            try:
                for i in range(50):
                    nonce = f't{thread_id}_n{i}_{random.randint(0, 100000)}'
                    res = cache.check_and_add(nonce)
                    with lock:
                        results.add((nonce, res))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"线程安全测试失败: {errors}"

    def test_multiple_unique_nonces(self):
        """测试多个不同nonce都能通过"""
        from springbootai.security.replay_protection import NonceCache

        cache = NonceCache(max_size=1000, ttl=300)

        for i in range(100):
            assert cache.check_and_add(f'unique_nonce_{i}') is True

        for i in range(100):
            assert cache.check_and_add(f'unique_nonce_{i}') is False
