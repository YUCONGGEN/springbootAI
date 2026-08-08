"""
Spring Security 模块
提供认证授权、JWT支持等企业级安全功能
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

__all__ = [
    'JwtUtils',
    'SecurityContext',
    'SecurityContextHolder',
    'pre_authorize_decorator',
    'secured_decorator',
    'authenticate_decorator',
]