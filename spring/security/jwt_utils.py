"""
JWT 工具类
提供 Token 生成、验证、解析等功能
"""
import jwt
import time
import uuid
import functools
from typing import Optional, Dict, Any


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
    ) -> None:
        normalized_algorithm = str(algorithm).upper()
        if normalized_algorithm not in self.ALLOWED_ALGORITHMS:
            raise ValueError(f"不允许的 JWT 算法: {normalized_algorithm}")
        self.secret_key = secret_key or 'spring-python-secret-key-change-in-production'
        self.algorithm = normalized_algorithm
        self.issuer = issuer
        self.audience = audience
        self.leeway = max(0, int(leeway))
    
    @_InstanceOrDefaultMethod
    def generate_token(self, payload: Dict[str, Any], expires_in: int = 3600) -> str:
        """
        生成 JWT Token
        
        Args:
            payload: 载荷数据
            expires_in: 过期时间（秒），默认1小时
        
        Returns:
            JWT Token字符串
        """
        if expires_in <= 0:
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
        token = self.generate_token(payload, expires_in)
        decoded = jwt.decode(token, options={'verify_signature': False})
        decoded['token_type'] = 'refresh'
        return jwt.encode(decoded, self.secret_key, algorithm=self.algorithm)
    
    @_InstanceOrDefaultMethod
    def validate_token(self, token: str) -> bool:
        """
        验证 Token 是否有效
        
        Args:
            token: JWT Token
        
        Returns:
            是否有效
        """
        try:
            self.decode_token(token)
            return True
        except (jwt.PyJWTError, ValueError, TypeError):
            return False

    @_InstanceOrDefaultMethod
    def verify_token(self, token: str) -> Dict[str, Any]:
        """验证并返回 Token 载荷；无效 Token 会抛出解码异常。"""
        return self.decode_token(token)
    
    @_InstanceOrDefaultMethod
    def decode_token(self, token: str) -> Dict[str, Any]:
        """
        解码并验证 Token
        
        Args:
            token: JWT Token
        
        Returns:
            解码后的载荷数据
        
        Raises:
            jwt.ExpiredSignatureError: Token已过期
            jwt.InvalidTokenError: Token无效
        """
        options = {
            'require': ['exp', 'iat', 'jti', 'token_type'],
            'verify_aud': self.audience is not None,
            'verify_iss': self.issuer is not None,
        }
        return jwt.decode(
            token,
            self.secret_key,
            algorithms=[self.algorithm],
            audience=self.audience,
            issuer=self.issuer,
            leeway=self.leeway,
            options=options,
        )
    
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
    def refresh_token(self, refresh_token: str, expires_in: int = 3600) -> str:
        """
        使用刷新 Token 生成新的访问 Token
        
        Args:
            refresh_token: 刷新 Token
            expires_in: 新 Token 过期时间（秒）
        
        Returns:
            新的访问 Token
        """
        payload = self.decode_token(refresh_token)
        if payload.get('token_type') != 'refresh':
            raise jwt.InvalidTokenError("访问令牌不能用于刷新")
        
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


# 创建全局 JWT 工具实例
jwt_utils = JwtUtils()


def init_jwt(config: dict) -> None:
    """
    初始化 JWT 配置
    
    Args:
        config: JWT配置字典，包含secret_key等
    """
    jwt_utils.configure(
        secret_key=config.get('secret_key', 'spring-python-secret-key-change-in-production'),
        algorithm=config.get('algorithm', 'HS256'),
        issuer=config.get('issuer'),
        audience=config.get('audience'),
        leeway=config.get('leeway', 0),
    )
