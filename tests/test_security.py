"""
安全测试
测试SQL注入检测、JWT工具、密码编码、审计日志、HTTP头重放防护等安全功能
"""

import os
import sys
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import tests._test_helpers  # noqa: F401  安装模块mock


class AuditLogRecorder:
    """测试用审计日志记录器（内存实现）"""

    def __init__(self):
        self.records = []
        self._lock = threading.Lock()

    def log(self, action: str, target: str = None, result: str = 'success',
            duration_ms: float = 0.0, **kwargs):
        """记录审计日志"""
        with self._lock:
            record = {
                'action': action,
                'target': target,
                'result': result,
                'duration_ms': duration_ms,
                'timestamp': time.time(),
                'extra': kwargs,
            }
            self.records.append(record)
        return record

    def get_records(self, action=None):
        """获取记录"""
        with self._lock:
            if action:
                return [r for r in self.records if r['action'] == action]
            return list(self.records)

    def clear(self):
        """清空记录"""
        with self._lock:
            self.records.clear()


class TestSQLInjectionDetector:
    """测试SQL注入检测器"""

    def setup_method(self):
        """初始化检测器，使用宽松配置便于测试各检测点"""
        from spring.orm.pymybatis.security.sql_injection_detector import (
            SQLInjectionDetector, SQLInjectionLevel
        )
        self.detector = SQLInjectionDetector(
            enabled=True,
            max_risk_level=SQLInjectionLevel.LOW,
            block_ddl=True,
        )

    def test_union_injection_detected(self):
        """测试UNION注入检测"""
        from spring.orm.pymybatis.security.sql_injection_detector import SQLInjectionLevel

        payloads = [
            "' UNION SELECT username, password FROM users--",
            "1 UNION SELECT * FROM secrets",
            "admin' UNION SELECT 1,version()--",
        ]
        for payload in payloads:
            level = self.detector.detect(payload)
            assert level.value >= SQLInjectionLevel.HIGH.value, f"UNION注入应被HIGH级别检测: {payload}"

    def test_boolean_blind_injection_detected(self):
        """测试布尔盲注检测"""
        from spring.orm.pymybatis.security.sql_injection_detector import SQLInjectionLevel

        payloads = [
            "' AND 1=1--",
            "' OR 1=1#",
            "' OR 2=2",
            "1' OR '1'='1",
            "' AND 5=5",
        ]
        for payload in payloads:
            level = self.detector.detect(payload)
            assert level.value >= SQLInjectionLevel.HIGH.value, f"布尔盲注应被HIGH级别检测: {payload} (level={level})"

    def test_time_based_blind_injection_detected(self):
        """测试时间盲注检测"""
        from spring.orm.pymybatis.security.sql_injection_detector import SQLInjectionLevel

        payloads = [
            "'; WAITFOR DELAY '0:0:5'--",
            "' AND SLEEP(5)--",
            "1' AND BENCHMARK(1000000,MD5('test'))--",
        ]
        for payload in payloads:
            level = self.detector.detect(payload)
            assert level.value >= SQLInjectionLevel.HIGH.value, f"时间盲注应被HIGH级别检测: {payload}"

    def test_comment_injection_detected(self):
        """测试注释注入检测"""
        from spring.orm.pymybatis.security.sql_injection_detector import SQLInjectionLevel

        payloads = [
            "admin'--",
            "test' # ",
            "root'/*comment*/",
        ]
        for payload in payloads:
            level = self.detector.detect(payload)
            assert level.value >= SQLInjectionLevel.HIGH.value, f"注释注入应被检测: {payload}"

    def test_stacked_queries_detected(self):
        """测试堆叠查询检测"""
        from spring.orm.pymybatis.security.sql_injection_detector import SQLInjectionLevel

        payloads = [
            "1'; DROP TABLE users;--",
            "1'; DELETE FROM logs; SELECT '1",
        ]
        for payload in payloads:
            level = self.detector.detect(payload)
            assert level.value >= SQLInjectionLevel.HIGH.value, f"堆叠查询应被HIGH级别检测: {payload}"

    def test_ddl_statements_blocked(self):
        """测试DDL语句检测"""
        ddl_statements = [
            "DROP TABLE users",
            "ALTER TABLE users ADD COLUMN hack TEXT",
            "TRUNCATE TABLE audit_log",
            "CREATE TABLE backdoor (id INT)",
        ]
        for sql in ddl_statements:
            assert self.detector.detect_ddl(sql) is True, f"DDL语句应被阻止: {sql}"

    def test_normal_parameters_pass(self):
        """测试正常参数不被误判"""
        from spring.orm.pymybatis.security.sql_injection_detector import SQLInjectionLevel

        normal_values = [
            "john.doe@example.com",
            "张三",
            "Product Name 123",
            "+86-13800138000",
            "order-2024-001",
            "hello world",
            "100",
            "3.14159",
            "",
            None,
        ]
        for value in normal_values:
            level = self.detector.detect(value)
            assert level == SQLInjectionLevel.NONE or level == SQLInjectionLevel.LOW, \
                f"正常参数不应被判定为注入: {value} (level={level})"

    def test_safe_select_not_blocked(self):
        """测试正常SELECT语句不被DDL检测阻止"""
        safe_sqls = [
            "SELECT * FROM users WHERE id = ?",
            "SELECT username FROM users WHERE email = ?",
            "INSERT INTO logs (msg) VALUES (?)",
        ]
        for sql in safe_sqls:
            assert self.detector.detect_ddl(sql) is False, f"正常查询不是DDL: {sql}"

    def test_is_blocked_and_is_safe(self):
        """测试is_blocked和is_safe便捷方法"""
        malicious = "' OR 1=1--"
        safe = "john_doe"

        assert self.detector.is_blocked(malicious) is True
        assert self.detector.is_safe(malicious) is False

        assert self.detector.is_blocked(safe) is False
        assert self.detector.is_safe(safe) is True

    def test_batch_detection(self):
        """测试批量检测"""
        params = {
            'username': 'admin',
            'password': "' OR 1=1--",
            'email': 'user@example.com',
            'sort': 'id; DROP TABLE x',
        }
        results = self.detector.detect_batch(params)

        assert results['username'].value <= 1
        assert results['password'].value >= 3
        assert results['email'].value <= 1
        assert results['sort'].value >= 3

    def test_detection_details(self):
        """测试获取检测详情"""
        details = self.detector.get_detection_details("' UNION SELECT * FROM passwords--")

        assert details['level'] in ('HIGH', 'MEDIUM', 'LOW')
        assert 'patterns' in details
        assert len(details['patterns']) > 0
        assert details['is_blocked'] is True

    def test_sanitize_removes_comments(self):
        """测试sanitize清理注释"""
        dirty = "admin'-- "
        cleaned = self.detector.sanitize(dirty)

        assert '--' not in cleaned
        assert 'DROP TABLE' not in cleaned

    def test_disabled_detector_passes_everything(self):
        """测试禁用检测器时所有内容都通过"""
        from spring.orm.pymybatis.security.sql_injection_detector import (
            SQLInjectionDetector, SQLInjectionLevel
        )
        detector = SQLInjectionDetector(enabled=False)

        assert detector.detect("' OR 1=1--") == SQLInjectionLevel.NONE
        assert detector.is_blocked("'; DROP TABLE x;--") is False


class TestJWTUtils:
    """测试JWT生成与验证"""

    def setup_method(self):
        """初始化JWT工具"""
        from spring.security.jwt_utils import JwtUtils
        self.secret = 'test-jwt-secret-key-for-unit-tests-12345'
        self.jwt = JwtUtils(secret_key=self.secret, algorithm='HS256')

    def test_generate_and_validate_token(self):
        """测试正常token生成和验证"""
        payload = {'user_id': 'u123', 'username': 'testuser', 'roles': ['user']}
        token = self.jwt.generate_token(payload, expires_in=3600)

        assert token is not None
        assert isinstance(token, str)
        assert self.jwt.validate_token(token) is True

    def test_decode_token_returns_payload(self):
        """测试解码token返回正确载荷"""
        payload = {'user_id': 'u456', 'roles': ['admin', 'user']}
        token = self.jwt.generate_token(payload, expires_in=3600)

        decoded = self.jwt.decode_token(token)

        assert decoded['user_id'] == 'u456'
        assert 'admin' in decoded['roles']
        assert 'exp' in decoded
        assert 'iat' in decoded
        assert 'jti' in decoded

    def test_expired_token_rejected(self):
        """测试过期token被拒绝"""
        import jwt as pyjwt

        payload = {'user_id': 'expired_user'}
        token = self.jwt.generate_token(payload, expires_in=1)

        time.sleep(2)

        assert self.jwt.validate_token(token) is False
        with pytest.raises(pyjwt.ExpiredSignatureError):
            self.jwt.decode_token(token)

    def test_tampered_token_rejected(self):
        """测试篡改的token被拒绝"""
        import jwt as pyjwt

        payload = {'user_id': 'victim', 'role': 'user'}
        token = self.jwt.generate_token(payload, expires_in=3600)

        parts = token.split('.')
        tampered = parts[0] + '.' + parts[1] + 'aaaa.' + parts[2]

        assert self.jwt.validate_token(tampered) is False
        with pytest.raises(pyjwt.InvalidTokenError):
            self.jwt.decode_token(tampered)

    def test_invalid_token_string_rejected(self):
        """测试无效token字符串被拒绝"""
        assert self.jwt.validate_token('') is False
        assert self.jwt.validate_token('not.a.token') is False
        assert self.jwt.validate_token('abc.def') is False

    def test_extract_user_id(self):
        """测试从token提取用户ID"""
        token = self.jwt.generate_token({'user_id': 'u789'}, expires_in=3600)
        assert self.jwt.extract_user_id(token) == 'u789'

    def test_extract_roles(self):
        """测试从token提取角色列表"""
        token = self.jwt.generate_token({'roles': ['admin', 'editor']}, expires_in=3600)
        roles = self.jwt.extract_roles(token)

        assert 'admin' in roles
        assert 'editor' in roles

    def test_extract_permissions(self):
        """测试从token提取权限列表"""
        token = self.jwt.generate_token({'permissions': ['read', 'write', 'delete']}, expires_in=3600)
        perms = self.jwt.extract_permissions(token)

        assert 'write' in perms
        assert len(perms) == 3

    def test_extract_from_invalid_token_returns_empty(self):
        """测试从无效token提取角色/权限返回空"""
        assert self.jwt.extract_roles('invalid') == []
        assert self.jwt.extract_permissions('invalid') == []
        assert self.jwt.extract_user_id('invalid') is None

    def test_is_expired(self):
        """测试is_expired方法"""
        token = self.jwt.generate_token({'user_id': 'tmp'}, expires_in=1)
        assert self.jwt.is_expired(token) is False

        time.sleep(2)
        assert self.jwt.is_expired(token) is True

    def test_refresh_token_flow(self):
        """测试刷新token流程"""
        access = self.jwt.generate_token({'user_id': 'refresh_user'}, expires_in=1)
        refresh = self.jwt.generate_refresh_token({'user_id': 'refresh_user'}, expires_in=86400)

        # refresh token 必须显式按 refresh 类型验证（默认只接受 access token）
        assert self.jwt.validate_token(refresh, expected_token_type='refresh') is True
        # refresh token 不能作为 access token 通过验证（安全加固）
        assert self.jwt.validate_token(refresh) is False

        new_access = self.jwt.refresh_token(refresh, expires_in=3600)
        assert self.jwt.validate_token(new_access) is True
        assert self.jwt.extract_user_id(new_access) == 'refresh_user'

    def test_invalid_algorithm_rejected(self):
        """测试不允许的算法抛出异常"""
        from spring.security.jwt_utils import JwtUtils

        with pytest.raises(ValueError, match="不允许的 JWT 算法"):
            JwtUtils(secret_key=self.secret, algorithm='none')


class TestPasswordEncoder:
    """测试密码编码与验证"""

    def setup_method(self):
        """初始化密码编码器（bcrypt）"""
        try:
            from spring.orm.pymybatis.security.password_encoder import PasswordEncoder
            self.encoder = PasswordEncoder(algorithm='bcrypt')
            self._bcrypt_available = True
        except ImportError:
            self._bcrypt_available = False
            pytest.skip("bcrypt未安装，跳过bcrypt测试")

    def test_bcrypt_hash_format(self):
        """测试bcrypt哈希格式正确"""
        hashed = self.encoder.encode('mypassword123')

        assert hashed is not None
        assert isinstance(hashed, str)
        assert hashed.startswith('$2b$') or hashed.startswith('$2a$')
        assert len(hashed) > 50

    def test_bcrypt_verify_correct_password(self):
        """测试bcrypt验证正确密码"""
        raw = 'correct_horse_battery_staple'
        hashed = self.encoder.encode(raw)

        assert self.encoder.matches(raw, hashed) is True

    def test_bcrypt_verify_wrong_password(self):
        """测试bcrypt验证错误密码"""
        hashed = self.encoder.encode('real_password')

        assert self.encoder.matches('wrong_password', hashed) is False

    def test_bcrypt_unique_hashes(self):
        """测试同一密码每次哈希结果不同（随机盐）"""
        password = 'same_password'
        hash1 = self.encoder.encode(password)
        hash2 = self.encoder.encode(password)

        assert hash1 != hash2, "bcrypt每次应使用不同的盐值"
        assert self.encoder.matches(password, hash1) is True
        assert self.encoder.matches(password, hash2) is True

    def test_bcrypt_none_password_raises(self):
        """测试None密码抛出异常"""
        with pytest.raises(ValueError):
            self.encoder.encode(None)

    def test_bcrypt_matches_none_returns_false(self):
        """测试None参数匹配返回False"""
        hashed = self.encoder.encode('test')
        assert self.encoder.matches(None, hashed) is False
        assert self.encoder.matches('test', None) is False

    def test_sha256_encoder(self):
        """测试SHA-256编码器"""
        from spring.orm.pymybatis.security.password_encoder import PasswordEncoder

        sha_encoder = PasswordEncoder(algorithm='sha256')
        raw = 'sha_password_test'
        hashed = sha_encoder.encode(raw)

        assert '$' in hashed
        assert sha_encoder.matches(raw, hashed) is True
        assert sha_encoder.matches('wrong', hashed) is False

    def test_md5_encoder(self):
        """测试MD5编码器（仅兼容用）"""
        from spring.orm.pymybatis.security.password_encoder import PasswordEncoder

        md5_encoder = PasswordEncoder(algorithm='md5')
        raw = 'md5_password'
        hashed = md5_encoder.encode(raw)

        assert '$' in hashed
        assert md5_encoder.matches(raw, hashed) is True
        assert md5_encoder.matches('wrong', hashed) is False


class TestAuditLog:
    """测试审计日志功能"""

    def setup_method(self):
        """初始化审计日志记录器"""
        self.audit = AuditLogRecorder()

    def test_log_action(self):
        """测试记录操作动作"""
        self.audit.log('user_login', target='user:u123', result='success')

        records = self.audit.get_records()
        assert len(records) == 1
        assert records[0]['action'] == 'user_login'
        assert records[0]['target'] == 'user:u123'
        assert records[0]['result'] == 'success'

    def test_log_target_tracking(self):
        """测试目标对象记录"""
        self.audit.log('data_access', target='table:users', result='success')
        self.audit.log('data_access', target='table:passwords', result='denied')

        records = self.audit.get_records('data_access')
        assert len(records) == 2
        targets = {r['target'] for r in records}
        assert 'table:users' in targets
        assert 'table:passwords' in targets

    def test_log_result_outcomes(self):
        """测试操作结果记录（成功/失败/拒绝）"""
        self.audit.log('config_change', result='success')
        self.audit.log('config_change', result='failure')
        self.audit.log('config_change', result='denied')

        records = self.audit.get_records('config_change')
        results = [r['result'] for r in records]
        assert 'success' in results
        assert 'failure' in results
        assert 'denied' in results

    def test_log_duration_tracking(self):
        """测试操作耗时记录"""
        start = time.monotonic()
        time.sleep(0.05)
        elapsed_ms = (time.monotonic() - start) * 1000

        self.audit.log('slow_query', target='report_query', duration_ms=elapsed_ms)

        record = self.audit.get_records('slow_query')[0]
        assert record['duration_ms'] >= 40
        assert 'timestamp' in record

    def test_log_extra_fields(self):
        """测试额外字段记录"""
        self.audit.log(
            'api_call',
            target='/api/users',
            result='success',
            duration_ms=25.5,
            ip='192.168.1.1',
            method='GET',
            status_code=200,
        )

        record = self.audit.get_records('api_call')[0]
        assert record['extra']['ip'] == '192.168.1.1'
        assert record['extra']['method'] == 'GET'
        assert record['extra']['status_code'] == 200

    def test_filter_by_action(self):
        """测试按动作类型过滤日志"""
        self.audit.log('login', target='u1')
        self.audit.log('logout', target='u1')
        self.audit.log('login', target='u2')
        self.audit.log('query', target='db1')

        logins = self.audit.get_records('login')
        assert len(logins) == 2
        assert all(r['action'] == 'login' for r in logins)

    def test_concurrent_logging(self):
        """测试多线程并发记录审计日志的线程安全性"""
        errors = []

        def worker(thread_id):
            try:
                for i in range(50):
                    self.audit.log(
                        f'action_{thread_id}',
                        target=f'target_{i}',
                        result='success' if i % 2 == 0 else 'failure',
                        duration_ms=float(i),
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"并发记录日志出错: {errors}"
        assert len(self.audit.get_records()) == 200


class TestReplayHeaders:
    """测试HTTP头重放防护验证"""

    def setup_method(self):
        """初始化重放保护器"""
        from spring.security.replay_protection import ReplayProtection
        self.secret = 'replay-header-test-secret-key-2024'
        self.protector = ReplayProtection(secret_key=self.secret, timestamp_window=30)

    def _build_signed_headers(self, body='', method='POST', path='/api/secure',
                              timestamp=None, nonce=None):
        """构建带签名的HTTP头"""
        import os
        if timestamp is None:
            timestamp = str(int(time.time()))
        if nonce is None:
            nonce = os.urandom(16).hex()

        signature = self.protector.generate_signature(timestamp, nonce, body, method, path)
        return {
            'X-Timestamp': timestamp,
            'X-Nonce': nonce,
            'X-Signature': signature,
            'Content-Type': 'application/json',
        }

    def test_valid_headers_pass(self):
        """测试有效的重放防护头通过验证"""
        body = '{"action":"transfer","amount":100}'
        headers = self._build_signed_headers(body=body, method='POST', path='/api/transfer')

        valid, reason = self.protector.validate_headers(
            headers, body=body, method='POST', path='/api/transfer'
        )
        assert valid is True, f"有效头应通过验证: {reason}"

    def test_missing_timestamp_header_rejected(self):
        """测试缺少时间戳头被拒绝"""
        headers = {
            'X-Nonce': 'abcdef1234567890',
            'X-Signature': '0' * 64,
        }

        valid, reason = self.protector.validate_headers(headers)
        assert valid is False
        assert 'timestamp' in reason.lower() or 'Invalid' in reason

    def test_missing_nonce_header_rejected(self):
        """测试缺少nonce头被拒绝"""
        headers = {
            'X-Timestamp': str(int(time.time())),
            'X-Signature': '0' * 64,
        }

        valid, reason = self.protector.validate_headers(headers)
        assert valid is False
        assert 'nonce' in reason.lower()

    def test_lowercase_headers_supported(self):
        """测试小写HTTP头被正确读取"""
        body = 'test'
        ts = str(int(time.time()))
        nonce = os.urandom(16).hex()
        sig = self.protector.generate_signature(ts, nonce, body, 'GET', '/test')

        headers = {
            'x-timestamp': ts,
            'x-nonce': nonce,
            'x-signature': sig,
        }

        valid, _ = self.protector.validate_headers(headers, body=body, method='GET', path='/test')
        assert valid is True

    def test_replay_with_same_headers_blocked(self):
        """测试使用相同头重放请求被阻止"""
        body = '{"cmd":"delete"}'
        headers = self._build_signed_headers(body=body, method='POST', path='/api/delete')

        valid1, _ = self.protector.validate_headers(headers, body=body, method='POST', path='/api/delete')
        assert valid1 is True

        valid2, reason = self.protector.validate_headers(headers, body=body, method='POST', path='/api/delete')
        assert valid2 is False
        assert 'Duplicate nonce' in reason or 'replay' in reason.lower()

    def test_wrong_path_signature_fails(self):
        """测试路径不匹配导致签名验证失败"""
        body = ''
        headers = self._build_signed_headers(body=body, method='GET', path='/api/legitimate')

        valid, reason = self.protector.validate_headers(headers, body=body, method='GET', path='/api/malicious')
        assert valid is False
        assert 'signature' in reason.lower()

    def test_wrong_method_signature_fails(self):
        """测试HTTP方法不匹配导致签名验证失败"""
        body = 'data'
        headers = self._build_signed_headers(body=body, method='GET', path='/api/data')

        valid, reason = self.protector.validate_headers(headers, body=body, method='DELETE', path='/api/data')
        assert valid is False
        assert 'signature' in reason.lower()

    def test_unsigned_request_without_signature_header(self):
        """测试不带签名头的请求（签名可选时）仅做nonce和timestamp校验"""
        headers = {
            'X-Timestamp': str(int(time.time())),
            'X-Nonce': os.urandom(16).hex(),
        }

        valid, reason = self.protector.validate_headers(headers, body='any')
        assert valid is True, "不提供签名时仅做nonce+timestamp校验应通过"

    def test_old_timestamp_headers_rejected(self):
        """测试带有过期时间戳的头被拒绝"""
        old_ts = str(int(time.time()) - 600)
        headers = {
            'X-Timestamp': old_ts,
            'X-Nonce': os.urandom(16).hex(),
            'X-Signature': '0' * 64,
        }

        valid, reason = self.protector.validate_headers(headers)
        assert valid is False
        assert 'expired' in reason.lower()
