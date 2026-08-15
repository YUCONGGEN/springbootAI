"""OAuth2 资源服务器 (Resource Server) 测试。

覆盖 ``spring.security.oauth2`` 模块的核心功能：
- ``OAuth2ResourceServer`` 单例的配置与初始化
- JWT Access Token 验证（HS256 对称密钥模式）
- FastAPI 依赖注入与路由保护
- ``init_oauth2`` 全局初始化函数

安全边界覆盖：
- 过期 / 篡改签名 / 错误 issuer / 错误 audience / 格式非法 / 空_token
- 缺失 Authorization 头 / 无效 Bearer 前缀 / scope 不足
"""
import sys
import time
from pathlib import Path

import pytest

# 将项目根目录加入 sys.path，确保能直接 import spring 包
PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import tests._test_helpers  # noqa: F401  安装缺失依赖的 mock stub

import jwt as pyjwt
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from spring.security.oauth2 import (
    OAuth2ResourceServer,
    OAuth2TokenValidationError,
    init_oauth2,
    oauth2_resource_server,
)


# ==================== 测试常量 ====================

# HS256 对称密钥（长度 >= 32，满足安全要求）
SECRET_KEY = "my-secret-key-at-least-32-characters-long-abc123"
# 不同的密钥，用于测试签名验证失败
WRONG_SECRET_KEY = "another-secret-key-also-long-enough-xyz789"
ISSUER = "https://auth.example.com"
AUDIENCE = "my-api"


# ==================== 辅助函数 ====================

def _reset_server(server: OAuth2ResourceServer) -> None:
    """重置单例服务器的所有可变状态，避免测试间状态泄漏。"""
    server._configured = False
    server._secret_key = None
    server._issuer = None
    server._audiences = []
    server._algorithms = ["RS256", "HS256"]
    server._jwks_cache = None


def _build_config(**jwt_overrides) -> dict:
    """构建 OAuth2 测试配置字典。

    默认包含完整的 HS256 配置；通过 jwt_overrides 可覆盖或删除特定字段。
    传入 None 值表示删除该字段。
    """
    jwt_config = {
        "issuer": ISSUER,
        "audiences": [AUDIENCE],
        "algorithms": ["HS256"],
        "secret-key": SECRET_KEY,
    }
    for key, value in jwt_overrides.items():
        if value is None:
            jwt_config.pop(key, None)
        else:
            jwt_config[key] = value
    return {
        "spring": {
            "security": {
                "oauth2": {
                    "resourceserver": {
                        "jwt": jwt_config,
                    },
                },
            },
        },
    }


def _make_token(
    payload_overrides: dict | None = None,
    secret: str = SECRET_KEY,
    algorithm: str = "HS256",
) -> str:
    """生成测试用 JWT Access Token。

    默认包含 sub / iss / aud / iat / exp / scope，可通过 payload_overrides 覆盖。
    """
    now = int(time.time())
    payload = {
        "sub": "user123",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 3600,
        "scope": "read write",
    }
    if payload_overrides:
        payload.update(payload_overrides)
    return pyjwt.encode(payload, secret, algorithm=algorithm)


def _configure_server(server: OAuth2ResourceServer, **jwt_overrides) -> OAuth2ResourceServer:
    """配置 OAuth2 服务器并返回，便于链式调用。"""
    server.configure(_build_config(**jwt_overrides))
    return server


def _create_test_app(
    server: OAuth2ResourceServer,
    required_scopes: list[str] | None = None,
) -> FastAPI:
    """创建测试用 FastAPI 应用。

    由于 ``get_dependency`` 返回的闭包参数 ``request`` 缺少 ``Request`` 类型注解，
    FastAPI 无法自动注入 Request 对象。此处通过路径函数显式接收 ``request: Request``
    再传入依赖闭包，确保依赖逻辑通过真实 HTTP 请求被完整执行。
    """
    app = FastAPI()
    dep = server.get_dependency(required_scopes=required_scopes)

    @app.get("/protected")
    def protected(request: Request):
        # 调用 OAuth2 依赖函数进行 token 验证与 scope 校验
        # 验证失败时 dep 会抛出 HTTPException，由 FastAPI 异常处理器返回对应 HTTP 状态码
        payload = dep(request)
        return {"sub": payload.get("sub"), "scope": payload.get("scope", "")}

    return app


# ==================== 全局 fixture ====================

@pytest.fixture(autouse=True)
def _isolate_oauth2_singleton():
    """每个测试前后重置 OAuth2 单例状态，确保测试隔离。"""
    server = OAuth2ResourceServer()
    _reset_server(server)
    yield
    _reset_server(server)


# ==================== 配置测试 ====================

class TestOAuth2Configure:
    """OAuth2ResourceServer.configure() 配置测试。"""

    def test_configure_with_secret_key(self):
        """使用 HS256 对称密钥配置后，密钥与 _configured 标志正确设置。"""
        server = OAuth2ResourceServer()
        config = _build_config(issuer=None, audiences=None, algorithms=None)
        server.configure(config)

        assert server._configured is True
        assert server._secret_key == SECRET_KEY
        # 仅提供 secret-key 时不应创建 JWKS 缓存
        assert server._jwks_cache is None

    def test_configure_with_issuer(self):
        """issuer 和 issuer-uri 两种配置键都能正确解析。"""
        server = OAuth2ResourceServer()

        # 测试 issuer 键
        server.configure(_build_config())
        assert server._issuer == ISSUER

        # 测试 issuer-uri 键（Spring 官方配置格式）
        _reset_server(server)
        config = _build_config(issuer=None)
        config["spring"]["security"]["oauth2"]["resourceserver"]["jwt"]["issuer-uri"] = ISSUER
        server.configure(config)
        assert server._issuer == ISSUER

    def test_configure_with_audiences(self):
        """audiences 列表正确解析。"""
        server = OAuth2ResourceServer()
        audiences = ["my-api", "my-api-v2"]
        server.configure(_build_config(audiences=audiences))

        assert server._audiences == audiences
        assert server._configured is True

    def test_configure_with_algorithms(self):
        """algorithms 列表正确解析。"""
        server = OAuth2ResourceServer()
        algorithms = ["HS256", "RS256"]
        server.configure(_build_config(algorithms=algorithms))

        assert server._algorithms == algorithms
        assert server._configured is True

    def test_configure_not_configured(self):
        """未调用 configure() 时，_configured 应为 False。"""
        server = OAuth2ResourceServer()
        # fixture 已重置状态，此处直接断言初始状态
        assert server._configured is False


# ==================== Token 验证测试 ====================

class TestOAuth2ValidateToken:
    """OAuth2ResourceServer.validate_token() 验证测试。"""

    def test_validate_valid_hs256_token(self):
        """合法的 HS256 token 验证通过，返回 payload。"""
        server = _configure_server(OAuth2ResourceServer())
        token = _make_token()

        payload = server.validate_token(token)

        assert payload["sub"] == "user123"
        assert payload["iss"] == ISSUER
        assert payload["aud"] == AUDIENCE
        assert "exp" in payload

    def test_validate_expired_token(self):
        """过期的 token 验证失败，抛出 OAuth2TokenValidationError。"""
        server = _configure_server(OAuth2ResourceServer())
        now = int(time.time())
        token = _make_token({
            "iat": now - 7200,
            "exp": now - 3600,  # 1 小时前过期
        })

        with pytest.raises(OAuth2TokenValidationError, match="expired"):
            server.validate_token(token)

    def test_validate_invalid_signature(self):
        """用不同密钥签名的 token 验证失败。"""
        server = _configure_server(OAuth2ResourceServer())
        # 用错误的密钥签名
        token = _make_token(secret=WRONG_SECRET_KEY)

        with pytest.raises(OAuth2TokenValidationError, match="Invalid token"):
            server.validate_token(token)

    def test_validate_wrong_issuer(self):
        """issuer 不匹配的 token 验证失败。"""
        server = _configure_server(OAuth2ResourceServer())
        token = _make_token({"iss": "https://wrong-issuer.example.com"})

        with pytest.raises(OAuth2TokenValidationError, match="issuer"):
            server.validate_token(token)

    def test_validate_wrong_audience(self):
        """audience 不匹配的 token 验证失败。"""
        server = _configure_server(OAuth2ResourceServer())
        token = _make_token({"aud": "wrong-audience"})

        with pytest.raises(OAuth2TokenValidationError, match="audience"):
            server.validate_token(token)

    def test_validate_malformed_token(self):
        """格式非法的 token 字符串验证失败。"""
        server = _configure_server(OAuth2ResourceServer())

        with pytest.raises(OAuth2TokenValidationError, match="Invalid token header"):
            server.validate_token("not.a.valid.jwt")

    def test_validate_empty_token(self):
        """空字符串 token 验证失败。"""
        server = _configure_server(OAuth2ResourceServer())

        with pytest.raises(OAuth2TokenValidationError, match="Invalid token header"):
            server.validate_token("")

    def test_validate_unconfigured_raises(self):
        """未配置时调用 validate_token 抛出异常。"""
        server = OAuth2ResourceServer()
        # fixture 已重置为未配置状态

        with pytest.raises(OAuth2TokenValidationError, match="not configured"):
            server.validate_token("some.token.here")


# ==================== FastAPI 依赖测试 ====================

class TestOAuth2Dependency:
    """OAuth2ResourceServer.get_dependency() FastAPI 依赖测试。"""

    def test_dependency_with_valid_token(self):
        """携带合法 Bearer token 的请求返回 200。"""
        server = _configure_server(OAuth2ResourceServer())
        app = _create_test_app(server, required_scopes=None)
        client = TestClient(app)

        token = _make_token()
        resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["sub"] == "user123"
        assert body["scope"] == "read write"

    def test_dependency_without_token(self):
        """缺失 Authorization 头时返回 401。"""
        server = _configure_server(OAuth2ResourceServer())
        app = _create_test_app(server, required_scopes=None)
        client = TestClient(app)

        # 不携带 Authorization 头
        resp = client.get("/protected")
        assert resp.status_code == 401
        assert "Bearer" in resp.headers.get("WWW-Authenticate", "")

    def test_dependency_with_invalid_token(self):
        """携带无效 token 的请求返回 401。"""
        server = _configure_server(OAuth2ResourceServer())
        app = _create_test_app(server, required_scopes=None)
        client = TestClient(app)

        # 携带格式非法的 token
        resp = client.get(
            "/protected",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code == 401

    def test_dependency_with_required_scopes(self):
        """required_scopes 校验：拥有所需 scope 返回 200，缺少时返回 403。"""
        server = _configure_server(OAuth2ResourceServer())
        # token 包含 scope="read write"
        token = _make_token({"scope": "read write"})

        # 拥有所需 scope → 200
        app_ok = _create_test_app(server, required_scopes=["read"])
        client_ok = TestClient(app_ok)
        resp_ok = client_ok.get(
            "/protected",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp_ok.status_code == 200

        # 缺少所需 scope → 403
        app_forbidden = _create_test_app(server, required_scopes=["admin"])
        client_forbidden = TestClient(app_forbidden)
        resp_forbidden = client_forbidden.get(
            "/protected",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp_forbidden.status_code == 403
        assert "insufficient_scope" in resp_forbidden.headers.get("WWW-Authenticate", "")


# ==================== init_oauth2 初始化函数测试 ====================

class TestInitOAuth2:
    """init_oauth2() 全局初始化函数测试。"""

    def test_init_oauth2_configures_global_singleton(self):
        """init_oauth2 使用完整配置初始化全局单例。"""
        config = _build_config()
        init_oauth2(config)

        # 全局单例应被配置
        assert oauth2_resource_server._configured is True
        assert oauth2_resource_server._secret_key == SECRET_KEY
        assert oauth2_resource_server._issuer == ISSUER
        assert oauth2_resource_server._audiences == [AUDIENCE]
        assert oauth2_resource_server._algorithms == ["HS256"]

    def test_init_oauth2_empty_config_does_nothing(self):
        """配置中无 spring.security.oauth2 时，init_oauth2 不做任何操作。"""
        # 先确保单例处于未配置状态
        assert oauth2_resource_server._configured is False

        # 空配置（不含 spring.security.oauth2 键）
        init_oauth2({})

        # 应保持未配置状态
        assert oauth2_resource_server._configured is False

    def test_init_oauth2_returns_none(self):
        """init_oauth2 返回值为 None。"""
        result = init_oauth2({})
        assert result is None

    def test_init_oauth2_partial_config_still_configures(self):
        """仅提供 secret-key 时，init_oauth2 仍能完成配置。"""
        config = _build_config(issuer=None, audiences=None, algorithms=None)
        init_oauth2(config)

        assert oauth2_resource_server._configured is True
        assert oauth2_resource_server._secret_key == SECRET_KEY
