"""
安全服务 — 测试 @PreAuthorize, @Secured, @Authenticate 注解支持
"""
import json
import base64
import hashlib
from spring.annotations.core import Service, Slf4j
from spring.security import SecurityContextHolder


@Slf4j
@Service
class SecurityService:
    """安全认证辅助服务"""

    def __init__(self):
        self._secret = "example_all_secret_key_for_jwt_hmac"

    def generate_token(self, username: str, role: str) -> str:
        """
        生成简单的 JWT Token
        格式: header.payload.signature
        """
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "sub": username,
            "roles": [role],
            "permissions": self._get_permissions(role),
        }

        header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b'=').decode()
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b'=').decode()

        signature = hashlib.sha256(
            f"{header_b64}.{payload_b64}.{self._secret}".encode()
        ).hexdigest()

        return f"{header_b64}.{payload_b64}.{signature}"

    def _get_permissions(self, role: str) -> list:
        permissions = {
            "ROLE_ADMIN": ["resource:read", "resource:write", "user:delete", "admin:all"],
            "ROLE_MODERATOR": ["resource:read", "resource:write"],
            "ROLE_USER": ["resource:read"],
        }
        return permissions.get(role, ["resource:read"])

    def get_current_user(self) -> dict:
        """获取当前安全上下文中的用户信息"""
        ctx = SecurityContextHolder.get_context()
        if ctx and ctx.authentication:
            return {
                "username": ctx.authentication.get("principal", "unknown"),
                "roles": ctx.authentication.get("authorities", []),
                "authenticated": ctx.is_authenticated(),
            }
        return {"username": "anonymous", "roles": [], "authenticated": False}
