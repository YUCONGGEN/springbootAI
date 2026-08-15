"""CSRF 防护模块测试 —— 覆盖 CSRFTokenManager / CSRFMiddleware / init_csrf /
get_csrf_token_manager。

基于 Double Submit Cookie 模式：
- GET 请求响应中注入 XSRF-TOKEN Cookie
- POST/PUT/PATCH/DELETE 请求校验 Cookie 与 Header 中的 Token 是否一致

中间件测试使用 FastAPI TestClient 进行集成验证。
"""
import sys
import time as _real_time
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import tests._test_helpers  # noqa: F401  安装模块mock

from spring.web.csrf import (
    CSRFTokenManager,
    CSRFMiddleware,
    init_csrf,
    get_csrf_token_manager,
)


# ==================== CSRFTokenManager ====================

class TestCSRFTokenManager:
    """Token 生成与验证测试。"""

    def test_generate_token_returns_string(self):
        # 生成的 Token 应为非空字符串
        manager = CSRFTokenManager()
        token = manager.generate_token()
        assert isinstance(token, str)
        assert len(token) > 0

    def test_generate_token_unique(self):
        # 两次生成的 Token 不应相同（CSPRNG 保证随机性）
        manager = CSRFTokenManager()
        t1 = manager.generate_token()
        t2 = manager.generate_token()
        assert t1 != t2

    def test_generate_token_custom_length(self):
        # 实际实现使用 secrets.token_urlsafe(32) 生成固定 32 字节随机部分，
        # 此处验证 Token 三段式结构及各部分长度符合预期。
        manager = CSRFTokenManager()
        token = manager.generate_token()
        parts = token.split(".")
        assert len(parts) == 3  # {timestamp}.{random}.{hmac}
        timestamp_str, random_part, signature = parts
        # 时间戳部分应为数字
        assert timestamp_str.isdigit()
        # secrets.token_urlsafe(32) 输出 43 个字符（32 字节 → base64url 无填充）
        assert len(random_part) == 43
        # 多次生成的随机部分长度一致（固定长度）
        for _ in range(5):
            assert len(manager.generate_token().split(".")[1]) == 43
        # HMAC-SHA256 十六进制签名（64 字符）
        assert len(signature) == 64

    def test_validate_valid_token(self):
        # 刚生成的 Token 应校验通过
        manager = CSRFTokenManager()
        token = manager.generate_token()
        assert manager.validate_token(token) is True

    def test_validate_invalid_token(self):
        # 非法格式 / 篡改签名的 Token 应校验失败
        manager = CSRFTokenManager()
        # 格式非法
        assert manager.validate_token("garbage") is False
        # 两段式（缺少签名）
        assert manager.validate_token("12345.abcde") is False
        # 三段式但时间戳非数字
        assert manager.validate_token("not.a.valid") is False
        # 篡改签名（最后 4 位替换）
        token = manager.generate_token()
        tampered = token[:-4] + "0000"
        assert manager.validate_token(tampered) is False
        # 使用不同 secret 的 manager 生成的 Token 不应通过
        other = CSRFTokenManager(secret_key="another-secret")
        assert manager.validate_token(other.generate_token()) is False

    def test_validate_expired_token(self):
        # 通过 mock 时间模拟 Token 过期
        manager = CSRFTokenManager(expire_seconds=3600)
        token = manager.generate_token()  # 使用真实时间生成（timestamp = T0）
        # 将 time.time 推进至过期之后（T0 + 3601）
        future = _real_time.time() + 3601
        with patch("spring.web.csrf.time.time", return_value=future):
            assert manager.validate_token(token) is False
        # 恢复真实时间后应再次有效
        assert manager.validate_token(token) is True

    def test_validate_empty_token(self):
        # 空值 / None 应校验失败
        manager = CSRFTokenManager()
        assert manager.validate_token("") is False
        assert manager.validate_token(None) is False


# ==================== CSRFMiddleware ====================

def _build_app(manager):
    """构建带 CSRF 中间件的 FastAPI 应用与 TestClient。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/")
    async def get_endpoint():
        return {"ok": True}

    @app.post("/")
    async def post_endpoint():
        return {"ok": True}

    app.add_middleware(CSRFMiddleware, token_manager=manager)
    return app, TestClient


class TestCSRFMiddleware:
    """CSRF 中间件集成测试（Double Submit Cookie 模式）。"""

    def test_get_request_injects_cookie(self):
        # GET 请求响应中应注入 XSRF-TOKEN Cookie
        manager = CSRFTokenManager()
        app, TestClient = _build_app(manager)
        with TestClient(app) as client:
            resp = client.get("/")
        assert resp.status_code == 200
        set_cookie = resp.headers.get("set-cookie", "")
        assert "XSRF-TOKEN=" in set_cookie
        assert "Path=/" in set_cookie
        assert "SameSite=lax" in set_cookie

    def test_post_without_token_rejected(self):
        # POST 请求未携带任何 Token 应被拒绝（403）
        manager = CSRFTokenManager()
        app, TestClient = _build_app(manager)
        with TestClient(app) as client:
            resp = client.post("/")
        assert resp.status_code == 403
        assert "CSRF" in resp.text

    def test_post_with_valid_token_passes(self):
        # POST 请求携带一致的有效 Token 应通过（Cookie == Header）
        manager = CSRFTokenManager()
        token = manager.generate_token()
        app, TestClient = _build_app(manager)
        with TestClient(app) as client:
            client.cookies.set("XSRF-TOKEN", token)
            resp = client.post("/", headers={"X-XSRF-TOKEN": token})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_post_with_mismatched_tokens_rejected(self):
        # Cookie 与 Header 中的 Token 不一致应被拒绝（Double Submit 校验）
        manager = CSRFTokenManager()
        token_a = manager.generate_token()
        token_b = manager.generate_token()
        app, TestClient = _build_app(manager)
        with TestClient(app) as client:
            client.cookies.set("XSRF-TOKEN", token_a)
            resp = client.post("/", headers={"X-XSRF-TOKEN": token_b})
        assert resp.status_code == 403

    def test_post_with_only_cookie_rejected(self):
        # 仅携带 Cookie Token（缺少 Header）应被拒绝
        manager = CSRFTokenManager()
        token = manager.generate_token()
        app, TestClient = _build_app(manager)
        with TestClient(app) as client:
            client.cookies.set("XSRF-TOKEN", token)
            resp = client.post("/")
        assert resp.status_code == 403

    def test_post_with_only_header_rejected(self):
        # 仅携带 Header Token（缺少 Cookie）应被拒绝
        manager = CSRFTokenManager()
        token = manager.generate_token()
        app, TestClient = _build_app(manager)
        with TestClient(app) as client:
            resp = client.post("/", headers={"X-XSRF-TOKEN": token})
        assert resp.status_code == 403


# ==================== init_csrf ====================

@pytest.fixture
def reset_csrf_global():
    """保存并复位全局 CSRF Token 管理器状态，测试后恢复。"""
    from spring.web import csrf as csrf_module
    saved = csrf_module._csrf_token_manager
    csrf_module._csrf_token_manager = None
    yield
    csrf_module._csrf_token_manager = saved


class TestInitCSRF:
    """init_csrf 配置初始化测试。"""

    def test_init_csrf_disabled_returns_none(self, reset_csrf_global):
        # enabled=False（或缺失）应返回 None，且不设置全局管理器
        config = {"server": {"csrf": {"enabled": False}}}
        assert init_csrf(config) is None
        assert get_csrf_token_manager() is None

    def test_init_csrf_enabled_returns_manager(self, reset_csrf_global):
        # enabled=True 应返回 CSRFTokenManager 实例，并设置为全局管理器
        config = {"server": {"csrf": {"enabled": True}}}
        manager = init_csrf(config)
        assert isinstance(manager, CSRFTokenManager)
        assert get_csrf_token_manager() is manager

    def test_init_csrf_with_custom_params(self, reset_csrf_global):
        # 自定义参数应正确传递给管理器（kebab-case 配置键）
        config = {
            "server": {
                "csrf": {
                    "enabled": True,
                    "cookie-name": "MY-CSRF",
                    "header-name": "X-MY-CSRF",
                    "secure": True,
                    "samesite": "strict",
                    "expire-seconds": 7200,
                    "secret-key": "my-secret",
                }
            }
        }
        manager = init_csrf(config)
        assert manager is not None
        assert manager.cookie_name == "MY-CSRF"
        assert manager.header_name == "X-MY-CSRF"
        assert manager.secure is True
        assert manager.samesite == "strict"
        assert manager.expire_seconds == 7200
        assert manager.secret_key == "my-secret"


# ==================== get_csrf_token_manager ====================

class TestGetCSRFTokenManager:
    """全局获取 CSRF Token 管理器测试。"""

    def test_get_manager_returns_none_before_init(self, reset_csrf_global):
        # 初始化前应返回 None
        assert get_csrf_token_manager() is None

    def test_get_manager_returns_instance_after_init(self, reset_csrf_global):
        # 初始化后应返回同一个管理器实例
        config = {"server": {"csrf": {"enabled": True}}}
        manager = init_csrf(config)
        assert manager is not None
        assert get_csrf_token_manager() is manager

    def test_get_manager_returns_none_when_disabled(self, reset_csrf_global):
        # 禁用时初始化后全局管理器仍为 None
        config = {"server": {"csrf": {"enabled": False}}}
        init_csrf(config)
        assert get_csrf_token_manager() is None
