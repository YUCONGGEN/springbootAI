"""组件初始化统一异常处理测试。

验证 main.py 的 ``_handle_init_error`` / ``_format_component_error`` / ``ComponentInitError``
统一异常捕获机制：所有 init_* 的异常（ImportError / ValueError / ConnectionError 等）都被
捕获并输出明确信息（组件名/配置内容/错误原因/修复建议），不再静默吞掉或输出框架 traceback。

回归场景：
1. init_jwt 原先只捕获 ImportError，配置错误（如 algorithm=RS256）的 ValueError 未被捕获。
2. 其他 init_* 的 except Exception 只输出简短 warning，不含配置项名/值/建议。
3. 非 fail_fast 模式下配置错误被静默吞掉，用户不知道组件初始化失败。
"""
import sys
import io
import pytest

from spring.main import SpringApplication, ComponentInitError


class TestFormatComponentError:
    """测试 _format_component_error 格式化输出。"""

    def test_error_contains_component_name(self):
        msg = SpringApplication._format_component_error(
            'Redis', {'host': 'localhost'}, ConnectionError('refused'))
        assert 'Redis' in msg

    def test_error_contains_config_values(self):
        msg = SpringApplication._format_component_error(
            'Database', {'url': 'mysql://localhost', 'port': 3306}, RuntimeError('boom'))
        assert 'mysql://localhost' in msg
        assert '3306' in msg

    def test_sensitive_fields_masked(self):
        """密码/密钥等敏感字段应脱敏为 ***。"""
        msg = SpringApplication._format_component_error(
            'Database',
            {'url': 'mysql://localhost', 'password': 'mypassword', 'username': 'root'},
            ConnectionError('refused'))
        assert '***' in msg
        assert 'mypassword' not in msg
        assert 'root' in msg  # 非敏感字段不脱敏

    def test_secret_key_masked(self):
        """JWT secret_key 应脱敏。"""
        msg = SpringApplication._format_component_error(
            'JWT', {'secret_key': 'my-secret', 'algorithm': 'RS256'},
            ValueError('不允许的 JWT 算法: RS256'))
        assert '***' in msg
        assert 'my-secret' not in msg
        assert 'RS256' in msg  # 非敏感字段不脱敏

    def test_empty_password_shows_placeholder(self):
        """空密码应显示 (空) 而非 ***。"""
        msg = SpringApplication._format_component_error(
            'Database', {'password': ''}, ConnectionError('refused'))
        assert '(空)' in msg

    def test_error_contains_exception_type(self):
        msg = SpringApplication._format_component_error(
            'Redis', {}, ValueError('bad value'))
        assert 'ValueError' in msg
        assert 'bad value' in msg

    def test_import_error_has_install_suggestion(self):
        """ImportError 应提示安装依赖，而非检查配置。"""
        msg = SpringApplication._format_component_error(
            'Redis', {'enabled': True}, ImportError('No module named redis'))
        assert '依赖未安装' in msg
        assert '安装' in msg
        assert 'redis.enabled=false' in msg

    def test_non_import_error_has_config_suggestion(self):
        """非 ImportError 应提示检查配置。"""
        msg = SpringApplication._format_component_error(
            'Redis', {'host': 'localhost'}, ConnectionError('refused'))
        assert '检查' in msg
        assert '配置项' in msg

    def test_empty_config_shows_placeholder(self):
        msg = SpringApplication._format_component_error(
            'Test', {}, RuntimeError('boom'))
        assert '(无配置)' in msg

    def test_none_config_shows_placeholder(self):
        msg = SpringApplication._format_component_error(
            'Test', None, RuntimeError('boom'))
        assert '(无配置)' in msg


class TestHandleInitError:
    """测试 _handle_init_error 的 fail_fast 行为。"""

    def test_fail_fast_raises_component_init_error(self):
        """fail_fast=True 时应抛出 ComponentInitError（携带格式化信息）。"""
        app = SpringApplication.__new__(SpringApplication)
        with pytest.raises(ComponentInitError) as exc_info:
            app._handle_init_error(
                'JWT', {'algorithm': 'RS256'},
                ValueError('不允许的 JWT 算法: RS256'),
                fail_fast=True)
        msg = str(exc_info.value)
        assert 'JWT' in msg
        assert 'RS256' in msg
        assert 'ValueError' in msg

    def test_non_fail_fast_does_not_raise(self, capsys):
        """fail_fast=False 时不应抛异常，但应输出警告到 stderr。"""
        app = SpringApplication.__new__(SpringApplication)
        # 不应抛异常
        app._handle_init_error(
            'Redis', {'host': 'localhost'},
            ConnectionError('refused'),
            fail_fast=False)
        captured = capsys.readouterr()
        assert 'Redis' in captured.err
        assert '组件初始化失败' in captured.err
        assert 'fail_fast=false' in captured.err

    def test_non_fail_fast_warning_contains_config(self, capsys):
        """非 fail_fast 警告应包含配置内容，让用户知道什么配置导致了失败。"""
        app = SpringApplication.__new__(SpringApplication)
        app._handle_init_error(
            'Database', {'url': 'mysql://localhost', 'port': 3306},
            ConnectionError('refused'),
            fail_fast=False)
        captured = capsys.readouterr()
        assert 'mysql://localhost' in captured.err
        assert '3306' in captured.err

    def test_fail_fast_preserves_original_exception(self):
        """ComponentInitError 应通过 __cause__ 保留原始异常。"""
        app = SpringApplication.__new__(SpringApplication)
        original = ValueError('original error')
        with pytest.raises(ComponentInitError) as exc_info:
            app._handle_init_error('Test', {}, original, fail_fast=True)
        assert exc_info.value.__cause__ is original


class TestSensitiveMasking:
    """测试敏感字段脱敏。"""

    def test_mask_password(self):
        masked = SpringApplication._mask_sensitive({'password': 'secret123'})
        assert masked['password'] == '***'

    def test_mask_secret_key(self):
        masked = SpringApplication._mask_sensitive({'secret_key': 'jwt-secret'})
        assert masked['secret_key'] == '***'

    def test_mask_token(self):
        masked = SpringApplication._mask_sensitive({'token': 'abc123'})
        assert masked['token'] == '***'

    def test_mask_api_key(self):
        masked = SpringApplication._mask_sensitive({'api_key': 'key123'})
        assert masked['api_key'] == '***'

    def test_case_insensitive_masking(self):
        """敏感字段名大小写不敏感。"""
        masked = SpringApplication._mask_sensitive({'Password': 'secret', 'API_KEY': 'key'})
        assert masked['Password'] == '***'
        assert masked['API_KEY'] == '***'

    def test_non_sensitive_not_masked(self):
        masked = SpringApplication._mask_sensitive({'host': 'localhost', 'port': 3306})
        assert masked['host'] == 'localhost'
        assert masked['port'] == 3306

    def test_empty_config_returns_empty(self):
        assert SpringApplication._mask_sensitive({}) == {}
        assert SpringApplication._mask_sensitive(None) == {}
