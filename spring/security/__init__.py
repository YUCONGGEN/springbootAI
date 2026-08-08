"""
Spring Security 模块
提供认证授权、JWT支持、密钥管理、重放防护等企业级安全功能
"""
from .security_context import SecurityContext, SecurityContextHolder
from .security_aop import (
    pre_authorize_decorator,
    secured_decorator,
    authenticate_decorator,
)

# 可选导入：JWT工具（需要pyjwt）
try:
    from .jwt_utils import JwtUtils
except ImportError:
    JwtUtils = None

# 密钥管理器
from .secret_manager import SecretManager, is_sensitive_key, mask_secret, resolve_secret_config

# 重放攻击防护
from .replay_protection import ReplayProtection, NonceCache, RedisNonceCache, create_replay_protection

__all__ = [
    'JwtUtils',
    'SecurityContext',
    'SecurityContextHolder',
    'pre_authorize_decorator',
    'secured_decorator',
    'authenticate_decorator',
    'SecretManager',
    'is_sensitive_key',
    'mask_secret',
    'resolve_secret_config',
    'ReplayProtection',
    'NonceCache',
    'RedisNonceCache',
    'create_replay_protection',
]