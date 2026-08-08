"""
Spring Security AOP 切面实现
提供认证授权功能
"""
from typing import Any, Callable, Dict, List
import functools
import inspect
from spring.security.security_context import SecurityContext, SecurityContextHolder
from spring.security.jwt_utils import jwt_utils


class SecurityError(Exception):
    """Base exception carrying an HTTP status for the web adapter."""

    status_code = 500


class AuthenticationError(SecurityError):
    status_code = 401


class AuthorizationError(SecurityError):
    status_code = 403


# ==================== @PreAuthorize 注解切面 ====================
def pre_authorize_decorator(annotation):
    """
    @PreAuthorize 注解切面
    支持表达式：
    - hasRole('ROLE_ADMIN')
    - hasAnyRole('ROLE_ADMIN', 'ROLE_USER')
    - hasPermission('user:read')
    - hasAnyPermission('user:read', 'user:write')
    - authentication.name == 'admin'
    """
    def decorator(func: Callable) -> Callable:
        def authorize() -> None:
            expression = annotation.value
            if not SecurityContextHolder.is_authenticated():
                raise AuthenticationError("Authentication required")
            if not _evaluate_expression(expression):
                raise AuthorizationError("Access denied")

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                authorize()
                return await func(*args, **kwargs)

            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            authorize()
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def _evaluate_expression(expression: str) -> bool:
    """
    评估权限表达式
    
    Args:
        expression: 权限表达式
    
    Returns:
        是否满足条件
    """
    if not expression:
        return True
    
    # 处理 hasRole 表达式
    if expression.startswith('hasRole('):
        role = expression.replace('hasRole(', '').replace(')', '').strip().strip("'\"")
        return SecurityContextHolder.has_role(role)
    
    # 处理 hasAnyRole 表达式
    if expression.startswith('hasAnyRole('):
        roles_str = expression.replace('hasAnyRole(', '').replace(')', '').strip()
        roles = [r.strip().strip("'\"") for r in roles_str.split(',')]
        return SecurityContextHolder.has_any_role(*roles)
    
    # 处理 hasPermission 表达式
    if expression.startswith('hasPermission('):
        permission = expression.replace('hasPermission(', '').replace(')', '').strip().strip("'\"")
        return SecurityContextHolder.has_permission(permission)
    
    # 处理 hasAnyPermission 表达式
    if expression.startswith('hasAnyPermission('):
        permissions_str = expression.replace('hasAnyPermission(', '').replace(')', '').strip()
        permissions = [p.strip().strip("'\"") for p in permissions_str.split(',')]
        return SecurityContextHolder.has_any_permission(*permissions)
    
    # 处理 authentication.name == 'xxx' 表达式
    if 'authentication.name' in expression:
        # 提取用户名
        import re
        match = re.search(r"authentication\.name\s*==\s*['\"]([^'\"]+)['\"]", expression)
        if match:
            expected_name = match.group(1)
            authentication = SecurityContextHolder.get_authentication()
            if authentication:
                principal = authentication.get('principal', {})
                if isinstance(principal, dict):
                    name = principal.get('name', '')
                else:
                    name = str(principal)
                return name == expected_name
    
    return False


# ==================== @Secured 注解切面 ====================
def secured_decorator(annotation):
    """
    @Secured 注解切面
    检查当前用户是否拥有指定角色中的任一角色
    """
    def decorator(func: Callable) -> Callable:
        def authorize() -> None:
            roles = annotation.value
            if not SecurityContextHolder.is_authenticated():
                raise AuthenticationError("Authentication required")
            if not SecurityContextHolder.has_any_role(*roles):
                raise AuthorizationError(f"Required role(s) {roles}")

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                authorize()
                return await func(*args, **kwargs)

            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            authorize()
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


# ==================== @Authenticate 注解切面 ====================
def authenticate_decorator(annotation):
    """
    @Authenticate 注解切面
    从请求头中获取 Token 并验证，设置安全上下文
    """
    def decorator(func: Callable) -> Callable:
        def prepare_context(args, kwargs):
            request = kwargs.pop('_spring_request', None)
            token = kwargs.get('token') or kwargs.get('authorization')

            accepted_parameters = inspect.signature(func).parameters
            if 'token' not in accepted_parameters:
                kwargs.pop('token', None)
            if 'authorization' not in accepted_parameters:
                kwargs.pop('authorization', None)

            candidates = list(args)
            if request is not None:
                candidates.append(request)
            if token is None:
                for candidate in candidates:
                    if hasattr(candidate, 'headers'):
                        token = candidate.headers.get('Authorization')
                        break

            if isinstance(token, str) and token.lower().startswith('bearer '):
                token = token[7:].strip()
            if not token:
                raise AuthenticationError("Token required")

            try:
                payload = jwt_utils.decode_token(token)
            except Exception as exc:
                raise AuthenticationError(f"Invalid token: {exc}") from exc

            authentication = {
                'principal': payload.get('user_id') or payload.get('sub'),
                'credentials': token,
                'roles': payload.get('roles', []),
                'permissions': payload.get('permissions', []),
                'details': payload,
            }
            context = SecurityContext()
            context.authentication = authentication
            context.principal = authentication['principal']
            context.credentials = token
            context.roles = authentication['roles']
            context.permissions = authentication['permissions']
            return SecurityContextHolder.set_context(context)

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                context_token = prepare_context(args, kwargs)
                try:
                    return await func(*args, **kwargs)
                finally:
                    SecurityContextHolder.reset_context(context_token)

            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            context_token = prepare_context(args, kwargs)
            try:
                return func(*args, **kwargs)
            finally:
                SecurityContextHolder.reset_context(context_token)

        return wrapper
    return decorator


# ==================== 注解处理映射 ====================
SECURITY_ANNOTATION_DECORATORS = {
    'PreAuthorize': pre_authorize_decorator,
    'Secured': secured_decorator,
    'Authenticate': authenticate_decorator,
}


def apply_security_annotations(target: Any, method: Callable) -> Callable:
    """应用所有安全注解"""
    annotations = getattr(method, '__spring_annotations__', [])
    
    wrapped = method
    
    # Authentication must be the outermost wrapper so it runs before checks.
    ordered = sorted(
        annotations,
        key=lambda item: 1 if type(item).__name__ == 'Authenticate' else 0,
    )
    for annotation in ordered:
        annotation_type = type(annotation).__name__
        decorator_func = SECURITY_ANNOTATION_DECORATORS.get(annotation_type)
        if decorator_func:
            wrapped = decorator_func(annotation)(wrapped)
    
    return wrapped
