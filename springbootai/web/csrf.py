"""
CSRF（Cross-Site Request Forgery）防护中间件

提供基于 Double Submit Cookie 模式的 CSRF 防护。

适用场景：
- 使用 Cookie 认证的 Web 应用（Session ID 在 Cookie 中）
- 表单提交场景

不适用场景（无需开启 CSRF）：
- 纯 REST API + Bearer Token 认证（Token 在 Header 中，不受 CSRF 影响）
- 无状态 API 服务

与 Java Spring Security CSRF 的差异：
- Java 使用 CsrfFilter + CsrfTokenRepository
- Python 使用 FastAPI Middleware + CSRFTokenManager

配置（application.yml）：
    server:
      csrf:
        enabled: false  # 默认关闭（Bearer Token 不需要 CSRF）
        cookie-name: XSRF-TOKEN
        header-name: X-XSRF-TOKEN
        secure: false   # 生产环境设为 true（仅 HTTPS 传输）
        samesite: lax   # strict | lax | none
        expire-seconds: 3600
"""
import hashlib
import hmac
import logging
import secrets
import time
from typing import Optional

logger = logging.getLogger("Spring.Web.CSRF")


class CSRFTokenManager:
    """CSRF Token 管理器（Double Submit Cookie 模式）

    工作原理：
    1. GET 请求响应中设置 Cookie（XSRF-TOKEN），包含随机 token
    2. 前端 JS 读取 Cookie，在后续 POST/PUT/DELETE 请求的 Header 中附带 token
    3. 服务端校验 Cookie 中的 token 与 Header 中的 token 是否一致

    安全性：
    - Token 使用 secrets.token_urlsafe（CSPRNG 生成）
    - Token 带 HMAC 签名（防篡改）
    - Token 有过期时间（默认 1 小时）
    - Cookie 设置 HttpOnly=False（JS 需读取）、Secure、SameSite
    """

    def __init__(self, secret_key: Optional[str] = None,
                 cookie_name: str = "XSRF-TOKEN",
                 header_name: str = "X-XSRF-TOKEN",
                 secure: bool = False,
                 samesite: str = "lax",
                 expire_seconds: int = 3600,
                 token_length: int = 32):
        try:
            expire_seconds = int(expire_seconds)
            token_length = int(token_length)
        except (TypeError, ValueError) as exc:
            raise ValueError("CSRF expire_seconds and token_length must be integers") from exc
        normalized_samesite = str(samesite).lower()
        if expire_seconds <= 0:
            raise ValueError("CSRF expire_seconds must be positive")
        if token_length < 16:
            raise ValueError("CSRF token_length must be at least 16 bytes")
        if normalized_samesite not in {"strict", "lax", "none"}:
            raise ValueError("CSRF samesite must be strict, lax, or none")
        if normalized_samesite == "none" and not secure:
            raise ValueError("CSRF SameSite=None requires a Secure cookie")
        self.secret_key = secret_key or secrets.token_hex(32)
        self.cookie_name = cookie_name
        self.header_name = header_name
        self.secure = bool(secure)
        self.samesite = normalized_samesite
        self.expire_seconds = expire_seconds
        self.token_length = token_length

    def generate_token(self) -> str:
        """生成 CSRF Token（带时间戳和 HMAC 签名）。

        格式：{timestamp}.{random}.{hmac}
        """
        timestamp = int(time.time())
        random_part = secrets.token_urlsafe(self.token_length)
        # HMAC 签名：timestamp + random_part
        payload = f"{timestamp}.{random_part}"
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        return f"{payload}.{signature}"

    def validate_token(self, token: str) -> bool:
        """验证 CSRF Token。

        Returns:
            True 如果 token 有效且未过期
        """
        if not token:
            return False
        parts = token.split('.')
        if len(parts) != 3:
            return False
        try:
            timestamp_str, random_part, signature = parts
            timestamp = int(timestamp_str)
        except (ValueError, TypeError):
            return False

        # 检查过期
        age = time.time() - timestamp
        if age < -60 or age > self.expire_seconds:
            return False

        # 验证 HMAC 签名
        payload = f"{timestamp_str}.{random_part}"
        expected_signature = hmac.new(
            self.secret_key.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()

        # 使用 compare_digest 防止时序攻击
        return hmac.compare_digest(signature, expected_signature)

    def get_cookie_params(self, token: str) -> dict:
        """获取 Set-Cookie 参数。"""
        params = {
            "key": self.cookie_name,
            "value": token,
            "httponly": False,  # JS 需要读取
            "secure": self.secure,
            "samesite": self.samesite,
            "max_age": self.expire_seconds,
            "path": "/",
        }
        return params


# 需要 CSRF 校验的 HTTP 方法
_CSRF_PROTECTED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class CSRFMiddleware:
    """FastAPI CSRF 中间件

    Usage:
        from springbootai.web.csrf import CSRFMiddleware
        app.add_middleware(CSRFMiddleware, token_manager=manager)

    或通过配置自动注册：
        server:
          csrf:
            enabled: true
    """

    def __init__(self, app, token_manager: CSRFTokenManager):
        self.app = app
        self.token_manager = token_manager

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")

        # 非 CSRF 保护方法：直接放行，GET 响应中注入 Cookie
        if method not in _CSRF_PROTECTED_METHODS:
            await self._inject_csrf_cookie(scope, receive, send)
            return

        # POST/PUT/PATCH/DELETE：校验 CSRF Token
        cookie_token = self._get_cookie_token(scope)
        header_token = self._get_header_token(scope)

        if not cookie_token or not header_token:
            await self._reject(scope, receive, send,
                               "Missing CSRF token in cookie or header")
            return

        if not self.token_manager.validate_token(cookie_token):
            await self._reject(scope, receive, send, "Invalid CSRF token in cookie")
            return

        # Double Submit：Cookie 中的 token 与 Header 中的 token 必须一致
        if cookie_token != header_token:
            await self._reject(scope, receive, send,
                               "CSRF token mismatch between cookie and header")
            return

        await self.app(scope, receive, send)

    def _get_cookie_token(self, scope) -> str:
        """从请求 Cookie 中提取 CSRF token。"""
        headers = dict(scope.get("headers", []))
        cookie_header = headers.get(b"cookie", b"").decode("utf-8")
        if not cookie_header:
            return ""
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith(f"{self.token_manager.cookie_name}="):
                return part[len(self.token_manager.cookie_name) + 1:]
        return ""

    def _get_header_token(self, scope) -> str:
        """从请求 Header 中提取 CSRF token。"""
        headers = dict(scope.get("headers", []))
        header_name = self.token_manager.header_name.lower().encode("utf-8")
        return headers.get(header_name, b"").decode("utf-8")

    async def _inject_csrf_cookie(self, scope, receive, send):
        """在 GET 响应中注入 CSRF Cookie。"""
        token = self.token_manager.generate_token()
        cookie_value = (
            f"{self.token_manager.cookie_name}={token}; "
            f"Path=/; "
            f"SameSite={self.token_manager.samesite}; "
            f"Max-Age={self.token_manager.expire_seconds}"
        )
        if self.token_manager.secure:
            cookie_value += "; Secure"

        # 包装 send 函数，在响应头中添加 Set-Cookie
        async def send_with_csrf(message):
            if message["type"] == "http.response.start":
                headers = message.get("headers", [])
                headers.append((b"set-cookie", cookie_value.encode("utf-8")))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_csrf)

    async def _reject(self, scope, receive, send, reason: str):
        """拒绝请求（403 Forbidden）。"""
        logger.warning(f"CSRF rejection: {reason}")
        response_body = b'{"detail":"CSRF validation failed","reason":"' + reason.encode("utf-8") + b'"}'
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(response_body)).encode("utf-8")),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": response_body,
        })


# 全局 CSRF Token 管理器
_csrf_token_manager: Optional[CSRFTokenManager] = None


def init_csrf(config: dict) -> Optional[CSRFTokenManager]:
    """从配置初始化 CSRF 防护。

    Args:
        config: 应用配置字典

    Returns:
        CSRFTokenManager 实例（如果启用），否则 None
    """
    global _csrf_token_manager

    csrf_config = config.get('server', {}).get('csrf', {})
    if not csrf_config.get('enabled', False):
        _csrf_token_manager = None
        return None

    def option(*names, default=None):
        for name in names:
            if name in csrf_config:
                return csrf_config[name]
        return default

    secure_value = option('secure', 'secure-cookie', 'secure_cookie', default=False)
    if isinstance(secure_value, str):
        secure_value = secure_value.strip().lower() in {'1', 'true', 'yes', 'on'}

    _csrf_token_manager = CSRFTokenManager(
        secret_key=option('secret-key', 'secret_key'),
        cookie_name=option('cookie-name', 'cookie_name', default='XSRF-TOKEN'),
        header_name=option('header-name', 'header_name', default='X-XSRF-TOKEN'),
        secure=secure_value,
        samesite=option('samesite', 'same-site', 'same_site', default='lax'),
        expire_seconds=option('expire-seconds', 'token-ttl', 'token_ttl', default=3600),
        token_length=option('token-length', 'token_length', default=32),
    )
    logger.info(f"CSRF protection enabled (cookie={_csrf_token_manager.cookie_name})")
    return _csrf_token_manager


def get_csrf_token_manager() -> Optional[CSRFTokenManager]:
    """获取全局 CSRF Token 管理器。"""
    return _csrf_token_manager
