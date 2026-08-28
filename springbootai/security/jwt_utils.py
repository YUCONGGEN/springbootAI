"""
JWT 工具类
提供 Token 生成、验证、解析等功能

安全说明：
- ``configure()`` / ``init_jwt()`` 未显式提供 ``secret_key`` 时，不再使用硬编码默认值，
  而是生成进程级随机密钥（每次重启变化），并打印醒目警告。
  这样即使开发环境误暴露到公网，攻击者也无法用已知密钥伪造 token。
  生产环境应通过配置文件顶层 ``jwt.secret_key`` 显式注入稳定密钥。
"""
import jwt
import logging
import os
import secrets
import time
import uuid
import functools
from typing import Optional, Dict, Any

_logger = logging.getLogger("Spring.Security.Jwt")

# 已知的旧版硬编码默认密钥，仅用于检测：若用户仍配置为此值则拒绝并要求更换
_KNOWN_INSECURE_DEFAULT = 'spring-python-secret-key-change-in-production'
_DEFAULT_ACCESS_TOKEN_EXPIRES_IN = 3600


def _resolve_access_token_expires_in(value: Any) -> int:
    """解析 Access Token 有效期，非法配置回退到框架默认的一小时。"""
    if isinstance(value, bool):
        return _DEFAULT_ACCESS_TOKEN_EXPIRES_IN
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return _DEFAULT_ACCESS_TOKEN_EXPIRES_IN
    return seconds if seconds > 0 else _DEFAULT_ACCESS_TOKEN_EXPIRES_IN


def _generate_random_secret_key() -> str:
    """生成进程级随机密钥（64 字节十六进制字符串）。

    每次进程启动都会重新生成，因此重启后旧 token 全部失效——
    这是有意为之，仅用于开发/测试环境。
    """
    return secrets.token_hex(32)


def _warn_insecure_key(reason: str) -> None:
    """打印醒目的安全警告，提醒当前密钥不安全。"""
    _logger.warning(
        "[JWT 安全警告] %s。当前使用进程级随机密钥，重启后所有 token 将失效。"
        "生产环境请通过配置项 jwt.secret_key 显式注入稳定密钥（长度 >= 32）。",
        reason,
    )


class _InstanceOrDefaultMethod:
    """Bind to an explicit instance, or to the configured module singleton."""

    def __init__(self, func):
        self.func = func
        functools.update_wrapper(self, func)

    def __get__(self, instance, owner):
        target = instance
        if target is None:
            target = globals().get('jwt_utils')
            if target is None:
                target = owner()
        return self.func.__get__(target, owner)


class JwtUtils:
    """JWT工具类"""

    ALLOWED_ALGORITHMS = {'HS256', 'HS384', 'HS512'}

    def __init__(self, secret_key: str = None, algorithm: str = 'HS256'):
        self.configure(secret_key=secret_key, algorithm=algorithm)

    def configure(
        self,
        secret_key: Optional[str] = None,
        algorithm: str = 'HS256',
        issuer: Optional[str] = None,
        audience: Optional[str] = None,
        leeway: int = 0,
        access_token_expires_in: Optional[int] = None,
    ) -> None:
        normalized_algorithm = str(algorithm).upper()
        if normalized_algorithm not in self.ALLOWED_ALGORITHMS:
            raise ValueError(f"不允许的 JWT 算法: {normalized_algorithm}")
        # 安全加固：不再使用硬编码默认密钥
        if not secret_key:
            # 优先从环境变量读取（开发环境常用方式）
            secret_key = os.getenv('JWT_SECRET_KEY')
        if not secret_key:
            # 仍无密钥：生成进程级随机密钥并告警
            secret_key = _generate_random_secret_key()
            _warn_insecure_key("未配置 secret_key")
        elif secret_key == _KNOWN_INSECURE_DEFAULT:
            # 检测到用户仍配置为旧版硬编码默认值，拒绝并生成随机密钥
            secret_key = _generate_random_secret_key()
            _warn_insecure_key("检测到旧版硬编码默认密钥，已自动替换为随机密钥")
        self.secret_key = secret_key
        self.algorithm = normalized_algorithm
        self.issuer = issuer
        self.audience = audience
        self.leeway = max(0, int(leeway))
        if access_token_expires_in is not None:
            self.access_token_expires_in = _resolve_access_token_expires_in(access_token_expires_in)
        elif not hasattr(self, 'access_token_expires_in'):
            self.access_token_expires_in = _DEFAULT_ACCESS_TOKEN_EXPIRES_IN
    
    @_InstanceOrDefaultMethod
    def generate_token(self, payload: Dict[str, Any], expires_in: Optional[int] = None) -> str:
        """
        生成 JWT Token
        
        Args:
            payload: 载荷数据
            expires_in: 过期时间（秒）。不传时使用 ``jwt.expires_in`` 配置，
                未配置或配置非法时使用框架默认 3600 秒。
        
        Returns:
            JWT Token字符串
        """
        expires_in = self.access_token_expires_in if expires_in is None else expires_in
        if isinstance(expires_in, bool) or expires_in <= 0:
            raise ValueError("expires_in 必须大于 0")
        now = int(time.time())
        token_payload = {
            **payload,
            'exp': now + expires_in,
            'iat': now,
            'jti': str(uuid.uuid4()),
            'token_type': 'access',
        }
        if self.issuer:
            token_payload['iss'] = self.issuer
        if self.audience:
            token_payload['aud'] = self.audience
        
        return jwt.encode(token_payload, self.secret_key, algorithm=self.algorithm)
    
    @_InstanceOrDefaultMethod
    def generate_refresh_token(self, payload: Dict[str, Any], expires_in: int = 86400) -> str:
        """
        生成刷新 Token

        Args:
            payload: 载荷数据
            expires_in: 过期时间（秒），默认24小时

        Returns:
            刷新 Token 字符串
        """
        if expires_in <= 0:
            raise ValueError("expires_in 必须大于 0")
        now = int(time.time())
        token_payload = {
            **payload,
            'exp': now + expires_in,
            'iat': now,
            'jti': str(uuid.uuid4()),
            'token_type': 'refresh',
        }
        if self.issuer:
            token_payload['iss'] = self.issuer
        if self.audience:
            token_payload['aud'] = self.audience
        return jwt.encode(token_payload, self.secret_key, algorithm=self.algorithm)
    
    @_InstanceOrDefaultMethod
    def validate_token(self, token: str, expected_token_type: Optional[str] = 'access') -> bool:
        """
        验证 Token 是否有效

        Args:
            token: JWT Token
            expected_token_type: 期望的 token 类型（``'access'``/``'refresh'``）。
                默认 ``'access'``，传 ``None`` 跳过类型检查（用于通用有效性验证）。

        Returns:
            是否有效
        """
        try:
            self.decode_token(token, expected_token_type=expected_token_type)
            return True
        except (jwt.PyJWTError, ValueError, TypeError):
            return False

    @_InstanceOrDefaultMethod
    def verify_token(self, token: str) -> Dict[str, Any]:
        """验证并返回 Token 载荷；无效 Token 会抛出解码异常。"""
        return self.decode_token(token)
    
    @_InstanceOrDefaultMethod
    def decode_token(self, token: str, expected_token_type: Optional[str] = 'access') -> Dict[str, Any]:
        """
        解码并验证 Token

        安全加固：默认只接受 access token（``expected_token_type='access'``），
        refresh token 不能用于访问受保护接口（有效期更长，泄露风险更大）。
        ``refresh_token()`` 方法显式传 ``expected_token_type='refresh'`` 来验证刷新令牌。

        Args:
            token: JWT Token
            expected_token_type: 期望的 token 类型（``'access'``/``'refresh'``）。
                默认 ``'access'``，传 ``None`` 跳过类型检查。

        Returns:
            解码后的载荷数据

        Raises:
            jwt.ExpiredSignatureError: Token已过期
            jwt.InvalidTokenError: Token无效或类型不匹配
        """
        options = {
            'require': ['exp', 'iat', 'jti', 'token_type'],
            'verify_aud': self.audience is not None,
            'verify_iss': self.issuer is not None,
        }
        payload = jwt.decode(
            token,
            self.secret_key,
            algorithms=[self.algorithm],
            audience=self.audience,
            issuer=self.issuer,
            leeway=self.leeway,
            options=options,
        )
        # 安全加固：验证 token_type 匹配预期类型
        if expected_token_type is not None and payload.get('token_type') != expected_token_type:
            raise jwt.InvalidTokenError(
                f"Expected {expected_token_type} token, got '{payload.get('token_type')}' token. "
                f"{expected_token_type.capitalize()} tokens cannot be used as "
                f"{'refresh' if expected_token_type == 'access' else 'access'} tokens."
            )
        return payload
    
    @_InstanceOrDefaultMethod
    def get_payload(self, token: str) -> Dict[str, Any]:
        """
        获取 Token 载荷（不验证签名）
        
        Args:
            token: JWT Token
        
        Returns:
            载荷数据
        """
        return jwt.decode(token, options={'verify_signature': False})
    
    @_InstanceOrDefaultMethod
    def is_expired(self, token: str) -> bool:
        """
        检查 Token 是否已过期
        
        Args:
            token: JWT Token
        
        Returns:
            是否已过期
        """
        try:
            payload = self.get_payload(token)
            exp = payload.get('exp', 0)
            return time.time() > exp
        except (jwt.PyJWTError, ValueError, TypeError):
            return True
    
    @_InstanceOrDefaultMethod
    def refresh_token(self, refresh_token: str, expires_in: Optional[int] = None) -> str:
        """
        使用刷新 Token 生成新的访问 Token
        
        Args:
            refresh_token: 刷新 Token
            expires_in: 新 Token 过期时间（秒）。不传时复用 ``jwt.expires_in`` 配置。
        
        Returns:
            新的访问 Token
        """
        payload = self.decode_token(refresh_token, expected_token_type='refresh')
        
        # 移除过期时间相关字段
        payload.pop('exp', None)
        payload.pop('iat', None)
        payload.pop('jti', None)
        payload.pop('token_type', None)
        
        return self.generate_token(payload, expires_in)
    
    @_InstanceOrDefaultMethod
    def extract_user_id(self, token: str) -> Optional[str]:
        """
        从 Token 中提取用户ID
        
        Args:
            token: JWT Token
        
        Returns:
            用户ID
        """
        try:
            payload = self.decode_token(token)
            return payload.get('user_id') or payload.get('sub')
        except (jwt.PyJWTError, ValueError, TypeError):
            return None
    
    @_InstanceOrDefaultMethod
    def extract_roles(self, token: str) -> list:
        """
        从 Token 中提取角色列表
        
        Args:
            token: JWT Token
        
        Returns:
            角色列表
        """
        try:
            payload = self.decode_token(token)
            roles = payload.get('roles', [])
            if isinstance(roles, str):
                return [roles]
            return roles
        except (jwt.PyJWTError, ValueError, TypeError):
            return []
    
    @_InstanceOrDefaultMethod
    def extract_permissions(self, token: str) -> list:
        """
        从 Token 中提取权限列表
        
        Args:
            token: JWT Token
        
        Returns:
            权限列表
        """
        try:
            payload = self.decode_token(token)
            permissions = payload.get('permissions', [])
            if isinstance(permissions, str):
                return [permissions]
            return permissions
        except (jwt.PyJWTError, ValueError, TypeError):
            return []


# 创建全局 JWT 工具实例。模块导入本身不代表应用已经启动；此处预置随机
# 开发密钥，避免 ``springbootai init --help`` 等纯 CLI 操作输出误导性的安全告警。
# 真正应用启动时 ``init_jwt`` 会按配置重新调用 configure()，缺少密钥仍会给出
# 明确警告，并使用新的进程级随机密钥。
jwt_utils = JwtUtils(secret_key=_generate_random_secret_key())


def init_jwt(config: dict) -> None:
    """
    初始化 JWT 配置

    Args:
        config: JWT配置字典，包含 secret_key、expires_in 等。
            若未提供 ``secret_key``，将自动生成进程级随机密钥并打印安全警告。
    """
    config = config if isinstance(config, dict) else {}
    expires_in = config.get('expires_in', config.get('expires-in'))
    jwt_utils.configure(
        secret_key=config.get('secret_key'),
        algorithm=config.get('algorithm', 'HS256'),
        issuer=config.get('issuer'),
        audience=config.get('audience'),
        leeway=config.get('leeway', 0),
        # 每次应用初始化都显式写入默认值，避免同一进程重载配置时沿用旧项目的时长。
        access_token_expires_in=_resolve_access_token_expires_in(expires_in),
    )
