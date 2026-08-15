"""
OAuth2 资源服务器 (Resource Server)

验证来自 Authorization Server 的 JWT Access Token，保护 API 端点。

核心功能：
- 支持 HS256（对称密钥）和 RS256（JWKS 非对称密钥）
- 验证 issuer / audience / scope / expiry
- JWKS 公钥自动获取与缓存（定期刷新）
- 提供 FastAPI 依赖注入，保护路由

与 Java Spring Security OAuth2 的差异：
- Java 使用 SecurityFilterChain + @EnableResourceServer
- Python 使用 FastAPI Depends + @EnableResourceServer 注解

配置（application.yml）：
    spring:
      security:
        oauth2:
          resourceserver:
            jwt:
              issuer-uri: https://auth.example.com
              jwk-set-uri: https://auth.example.com/.well-known/jwks.json
              secret-key: ${OAUTH2_SECRET}  # HS256 模式使用
              algorithms: [RS256, HS256]
              audiences: [my-api]
"""
import json
import logging
import time
import threading
import functools
from typing import Any, Callable, Dict, List, Optional, Set
from urllib.request import urlopen, Request
from urllib.error import URLError

logger = logging.getLogger("Spring.Security.OAuth2")


class OAuth2TokenValidationError(Exception):
    """OAuth2 token 验证失败"""
    pass


class JwksCache:
    """JWKS（JSON Web Key Set）缓存管理器。

    从 Authorization Server 获取公钥集合并缓存，定期刷新。
    """

    def __init__(self, jwk_set_uri: str, refresh_interval: int = 3600):
        self.jwk_set_uri = jwk_set_uri
        self.refresh_interval = refresh_interval  # 默认 1 小时刷新一次
        self._keys: Dict[str, dict] = {}  # kid -> key dict
        self._last_fetch: float = 0
        self._lock = threading.Lock()

    def _fetch_jwks(self) -> None:
        """从 Authorization Server 获取 JWKS。"""
        try:
            req = Request(self.jwk_set_uri, headers={"Accept": "application/json"})
            with urlopen(req, timeout=10) as resp:  # nosec B310 - URL from config
                data = json.loads(resp.read().decode('utf-8'))
            keys = data.get('keys', [])
            new_keys = {}
            for key in keys:
                kid = key.get('kid')
                if kid:
                    new_keys[kid] = key
            self._keys = new_keys
            self._last_fetch = time.time()
            logger.info(f"JWKS fetched: {len(new_keys)} keys from {self.jwk_set_uri}")
        except URLError as e:
            logger.error(f"Failed to fetch JWKS from {self.jwk_set_uri}: {e}")
            # 保留旧密钥，不清空
        except Exception as e:
            logger.error(f"JWKS fetch error: {e}")

    def get_key(self, kid: str) -> Optional[dict]:
        """根据 key ID 获取公钥。

        如果缓存过期或为空，先刷新。
        """
        with self._lock:
            now = time.time()
            if not self._keys or (now - self._last_fetch) > self.refresh_interval:
                self._fetch_jwks()
            return self._keys.get(kid)

    def force_refresh(self) -> None:
        """强制刷新 JWKS 缓存。"""
        with self._lock:
            self._fetch_jwks()


class OAuth2ResourceServer:
    """OAuth2 资源服务器

    验证 JWT Access Token，支持 HS256 和 RS256。

    Usage:
        server = OAuth2ResourceServer()
        server.configure(config)
        # FastAPI 路由中使用
        @app.get("/api/protected", dependencies=[Depends(server.get_dependency())])
        def protected():
            return {"message": "protected"}
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self._jwks_cache: Optional[JwksCache] = None
        self._secret_key: Optional[str] = None
        self._issuer: Optional[str] = None
        self._audiences: List[str] = []
        self._algorithms: List[str] = ["RS256", "HS256"]
        self._configured = False

    def configure(self, config: dict) -> None:
        """从配置初始化 OAuth2 资源服务器。

        Args:
            config: 应用配置字典
        """
        oauth2_config = config.get('spring', {}).get('security', {}).get('oauth2', {})
        jwt_config = oauth2_config.get('resourceserver', {}).get('jwt', {})

        self._issuer = jwt_config.get('issuer-uri') or jwt_config.get('issuer')
        self._audiences = jwt_config.get('audiences', [])
        self._algorithms = jwt_config.get('algorithms', ["RS256", "HS256"])
        self._secret_key = jwt_config.get('secret-key')

        jwk_set_uri = jwt_config.get('jwk-set-uri')
        if jwk_set_uri:
            self._jwks_cache = JwksCache(jwk_set_uri)
            logger.info(f"OAuth2 Resource Server configured with JWKS: {jwk_set_uri}")
        elif self._secret_key:
            logger.info("OAuth2 Resource Server configured with HS256 secret key")
        else:
            # 尝试复用全局 JWT 配置
            from spring.security.jwt_utils import jwt_utils
            if hasattr(jwt_utils, 'secret_key') and jwt_utils.secret_key:
                self._secret_key = jwt_utils.secret_key
                self._algorithms = ["HS256"]
                logger.info("OAuth2 Resource Server using global JWT secret key (HS256)")
            else:
                logger.warning(
                    "OAuth2 Resource Server not fully configured. "
                    "Set spring.security.oauth2.resourceserver.jwt.jwk-set-uri or secret-key."
                )

        self._configured = True

    def validate_token(self, token: str) -> Dict[str, Any]:
        """验证 OAuth2 JWT Access Token。

        Args:
            token: JWT token 字符串（不含 "Bearer " 前缀）

        Returns:
            token 的 payload（claims）

        Raises:
            OAuth2TokenValidationError: 验证失败
        """
        if not self._configured:
            raise OAuth2TokenValidationError("OAuth2 Resource Server not configured")

        import jwt as pyjwt

        # 解析 header 获取 kid 和 alg
        try:
            unverified_header = pyjwt.get_unverified_header(token)
        except Exception as e:
            raise OAuth2TokenValidationError(f"Invalid token header: {e}") from e

        alg = unverified_header.get('alg', '')
        if alg not in self._algorithms:
            raise OAuth2TokenValidationError(
                f"Algorithm '{alg}' not allowed. Allowed: {self._algorithms}"
            )

        # 构建验证参数
        verify_options = {
            "verify_exp": True,
            "verify_iat": True,
            "verify_aud": bool(self._audiences),
            "verify_iss": bool(self._issuer),
        }

        decode_kwargs = {
            "algorithms": [alg],
            "options": verify_options,
        }
        if self._issuer:
            decode_kwargs["issuer"] = self._issuer
        if self._audiences:
            decode_kwargs["audience"] = self._audiences

        try:
            if alg.startswith('RS') or alg.startswith('ES'):
                # 非对称加密：使用 JWKS 公钥
                kid = unverified_header.get('kid')
                if not kid:
                    raise OAuth2TokenValidationError("Token missing 'kid' header for asymmetric algorithm")
                if self._jwks_cache is None:
                    raise OAuth2TokenValidationError("JWKS cache not configured for asymmetric algorithm")

                jwk = self._jwks_cache.get_key(kid)
                if jwk is None:
                    # 强制刷新一次 JWKS，可能是新加的密钥
                    self._jwks_cache.force_refresh()
                    jwk = self._jwks_cache.get_key(kid)
                if jwk is None:
                    raise OAuth2TokenValidationError(f"Key ID '{kid}' not found in JWKS")

                # 从 JWK 构造 PEM 公钥
                from jwt.algorithms import RSAAlgorithm
                public_key = RSAAlgorithm.from_jwk(json.dumps(jwk))
                decode_kwargs["key"] = public_key
            else:
                # 对称加密：使用 secret key
                if not self._secret_key:
                    raise OAuth2TokenValidationError("Secret key not configured for symmetric algorithm")
                decode_kwargs["key"] = self._secret_key

            payload = pyjwt.decode(token, **decode_kwargs)
            return payload

        except pyjwt.ExpiredSignatureError:
            raise OAuth2TokenValidationError("Token has expired")
        except pyjwt.InvalidAudienceError:
            raise OAuth2TokenValidationError("Invalid audience")
        except pyjwt.InvalidIssuerError:
            raise OAuth2TokenValidationError("Invalid issuer")
        except pyjwt.InvalidTokenError as e:
            raise OAuth2TokenValidationError(f"Invalid token: {e}") from e

    def get_dependency(self, required_scopes: Optional[List[str]] = None):
        """创建 FastAPI 依赖函数，用于保护路由。

        Args:
            required_scopes: 需要的 scope 列表（可选）

        Usage:
            @app.get("/api/protected", dependencies=[Depends(server.get_dependency())])
            def protected():
                return {"message": "ok"}

            # 需要 scope 校验
            @app.get("/api/admin", dependencies=[Depends(server.get_dependency(["admin"]))])
            def admin():
                return {"message": "admin"}
        """
        def _dependency(request) -> Dict[str, Any]:
            # 从 request 头获取 Authorization
            auth_header = ""
            try:
                # FastAPI Request 对象
                auth_header = request.headers.get('Authorization', '')
            except AttributeError:
                # 兼容其他框架
                auth_header = getattr(request, 'authorization', '') or ''

            if not auth_header.lower().startswith('bearer '):
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=401,
                    detail="Bearer token required",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            token = auth_header[7:].strip()
            try:
                payload = self.validate_token(token)
            except OAuth2TokenValidationError as e:
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=401,
                    detail=str(e),
                    headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
                ) from e

            # Scope 校验
            if required_scopes:
                token_scopes = set()
                scope_claim = payload.get('scope', '')
                if isinstance(scope_claim, str):
                    token_scopes = set(scope_claim.split())
                elif isinstance(scope_claim, list):
                    token_scopes = set(scope_claim)

                # 也检查 scp claim（OAuth2 标准）
                scp_claim = payload.get('scp', [])
                if isinstance(scp_claim, list):
                    token_scopes.update(scp_claim)
                elif isinstance(scp_claim, str):
                    token_scopes.add(scp_claim)

                missing = set(required_scopes) - token_scopes
                if missing:
                    from fastapi import HTTPException
                    raise HTTPException(
                        status_code=403,
                        detail=f"Insufficient scope. Required: {list(missing)}",
                        headers={"WWW-Authenticate": "Bearer error=\"insufficient_scope\""},
                    )

            return payload

        return _dependency

    def has_scope(self, payload: Dict[str, Any], scope: str) -> bool:
        """检查 token payload 是否包含指定 scope。"""
        scope_claim = payload.get('scope', '')
        if isinstance(scope_claim, str):
            return scope in set(scope_claim.split())
        elif isinstance(scope_claim, list):
            return scope in scope_claim

        scp_claim = payload.get('scp', [])
        if isinstance(scp_claim, list):
            return scope in scp_claim
        elif isinstance(scp_claim, str):
            return scope == scp_claim
        return False


# 全局单例
oauth2_resource_server = OAuth2ResourceServer()


def init_oauth2(config: dict) -> None:
    """从配置初始化 OAuth2 资源服务器。

    Args:
        config: 应用配置字典
    """
    oauth2_config = config.get('spring', {}).get('security', {}).get('oauth2', {})
    if not oauth2_config:
        return
    oauth2_resource_server.configure(config)
