"""
安全上下文管理
用于存储当前用户的认证信息
"""
from contextvars import ContextVar, Token
from typing import Optional, Dict, Any, List


class SecurityContext:
    """安全上下文，存储当前用户信息"""
    
    def __init__(self):
        self._authentication: Optional[Dict[str, Any]] = None
        self._principal: Optional[Any] = None
        self._credentials: Optional[str] = None
        self._roles: List[str] = []
        self._permissions: List[str] = []
    
    @property
    def authentication(self) -> Optional[Dict[str, Any]]:
        return self._authentication
    
    @authentication.setter
    def authentication(self, value: Optional[Dict[str, Any]]):
        self._authentication = value
    
    @property
    def principal(self) -> Optional[Any]:
        return self._principal
    
    @principal.setter
    def principal(self, value: Optional[Any]):
        self._principal = value
    
    @property
    def credentials(self) -> Optional[str]:
        return self._credentials
    
    @credentials.setter
    def credentials(self, value: Optional[str]):
        self._credentials = value
    
    @property
    def roles(self) -> List[str]:
        return self._roles
    
    @roles.setter
    def roles(self, value: List[str]):
        self._roles = value
    
    @property
    def permissions(self) -> List[str]:
        return self._permissions
    
    @permissions.setter
    def permissions(self, value: List[str]):
        self._permissions = value
    
    def is_authenticated(self) -> bool:
        """判断当前用户是否已认证"""
        return self._authentication is not None
    
    def has_role(self, role: str) -> bool:
        """判断当前用户是否拥有指定角色"""
        return role in self._roles
    
    def has_any_role(self, *roles: str) -> bool:
        """判断当前用户是否拥有任一指定角色"""
        return any(role in self._roles for role in roles)
    
    def has_permission(self, permission: str) -> bool:
        """判断当前用户是否拥有指定权限"""
        return permission in self._permissions
    
    def has_any_permission(self, *permissions: str) -> bool:
        """判断当前用户是否拥有任一指定权限"""
        return any(permission in self._permissions for permission in permissions)
    
    def clear(self):
        """清除安全上下文"""
        self._authentication = None
        self._principal = None
        self._credentials = None
        self._roles = []
        self._permissions = []


class SecurityContextHolder:
    """安全上下文持有者，隔离线程和 asyncio Task。"""
    
    _context_var: ContextVar[Optional[SecurityContext]] = ContextVar(
        'spring_security_context', default=None
    )
    
    @classmethod
    def get_context(cls) -> SecurityContext:
        """获取当前执行上下文的安全上下文"""
        context = cls._context_var.get()
        if context is None:
            context = SecurityContext()
            cls._context_var.set(context)
        return context
    
    @classmethod
    def set_context(cls, context: SecurityContext) -> Token:
        """设置当前执行上下文并返回可用于恢复的 token"""
        return cls._context_var.set(context)

    @classmethod
    def reset_context(cls, token: Token) -> None:
        """恢复设置新上下文之前的安全上下文"""
        cls._context_var.reset(token)
    
    @classmethod
    def clear_context(cls):
        """清除当前执行上下文，避免身份泄漏到后续调用"""
        cls._context_var.set(SecurityContext())
    
    @classmethod
    def get_authentication(cls) -> Optional[Dict[str, Any]]:
        """获取当前认证信息"""
        return cls.get_context().authentication
    
    @classmethod
    def set_authentication(cls, authentication: Dict[str, Any]):
        """设置当前认证信息"""
        context = cls.get_context()
        context.authentication = authentication
        context.principal = authentication.get('principal')
        context.credentials = authentication.get('credentials')
        context.roles = authentication.get('roles', [])
        context.permissions = authentication.get('permissions', [])
    
    @classmethod
    def get_principal(cls) -> Optional[Any]:
        """获取当前用户主体"""
        return cls.get_context().principal
    
    @classmethod
    def get_roles(cls) -> List[str]:
        """获取当前用户角色列表"""
        return cls.get_context().roles
    
    @classmethod
    def get_permissions(cls) -> List[str]:
        """获取当前用户权限列表"""
        return cls.get_context().permissions
    
    @classmethod
    def is_authenticated(cls) -> bool:
        """判断当前用户是否已认证"""
        return cls.get_context().is_authenticated()
    
    @classmethod
    def has_role(cls, role: str) -> bool:
        """判断当前用户是否拥有指定角色"""
        return cls.get_context().has_role(role)
    
    @classmethod
    def has_any_role(cls, *roles: str) -> bool:
        """判断当前用户是否拥有任一指定角色"""
        return cls.get_context().has_any_role(*roles)
    
    @classmethod
    def has_permission(cls, permission: str) -> bool:
        """判断当前用户是否拥有指定权限"""
        return cls.get_context().has_permission(permission)
    
    @classmethod
    def has_any_permission(cls, *permissions: str) -> bool:
        """判断当前用户是否拥有任一指定权限"""
        return cls.get_context().has_any_permission(*permissions)
