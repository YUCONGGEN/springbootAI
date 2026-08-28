"""
Spring Security AOP 切面实现
提供认证授权功能
"""
from typing import Any, Callable, Dict
import ast
import functools
import inspect
from springbootai.security.security_context import SecurityContext, SecurityContextHolder
from springbootai.security.jwt_utils import jwt_utils


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


class _ExpressionValue:
    """Read-only attribute view for security expression values."""

    def __init__(self, value: Any):
        self._value = value

    def get(self, name: str) -> Any:
        if name.startswith('_'):
            raise ValueError("Private attributes are not allowed in security expressions")
        if isinstance(self._value, dict):
            value = self._value.get(name)
        else:
            value = getattr(self._value, name)
        return _wrap_expression_value(value)

    def unwrap(self) -> Any:
        return self._value


def _wrap_expression_value(value: Any) -> Any:
    if isinstance(value, _ExpressionValue):
        return value
    if isinstance(value, (dict, list, tuple)) or (
        value is not None and not isinstance(value, (str, int, float, bool))
    ):
        return _ExpressionValue(value)
    return value


def _unwrap_expression_value(value: Any) -> Any:
    return value.unwrap() if isinstance(value, _ExpressionValue) else value


class _SecurityExpressionEvaluator:
    """Evaluate a small, non-executable Spring Security expression subset."""

    def __init__(self, variables: Dict[str, Any]):
        self.variables = variables
        self.functions = {
            'hasRole': SecurityContextHolder.has_role,
            'hasAnyRole': SecurityContextHolder.has_any_role,
            'hasPermission': SecurityContextHolder.has_permission,
            'hasAnyPermission': SecurityContextHolder.has_any_permission,
        }

    def evaluate(self, expression: str) -> bool:
        normalized = expression.replace('#returnObject', 'returnObject')
        tree = ast.parse(normalized, mode='eval')
        return bool(_unwrap_expression_value(self._visit(tree.body)))

    def _visit(self, node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id == 'true':
                return True
            if node.id == 'false':
                return False
            if node.id == 'null':
                return None
            if node.id in self.variables:
                return _wrap_expression_value(self.variables[node.id])
            if node.id in self.functions:
                return self.functions[node.id]
            raise ValueError(f"Unknown security expression name: {node.id}")
        if isinstance(node, ast.Attribute):
            value = self._visit(node.value)
            if not isinstance(value, _ExpressionValue):
                value = _ExpressionValue(_unwrap_expression_value(value))
            return value.get(node.attr)
        if isinstance(node, ast.Subscript):
            value = _unwrap_expression_value(self._visit(node.value))
            key = _unwrap_expression_value(self._visit(node.slice))
            return _wrap_expression_value(value[key])
        if isinstance(node, (ast.List, ast.Tuple)):
            values = [_unwrap_expression_value(self._visit(item)) for item in node.elts]
            return values if isinstance(node, ast.List) else tuple(values)
        if isinstance(node, ast.Call):
            function = self._visit(node.func)
            if function not in self.functions.values() or node.keywords:
                raise ValueError("Only security helper calls with positional arguments are allowed")
            args = [_unwrap_expression_value(self._visit(item)) for item in node.args]
            return function(*args)
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(bool(_unwrap_expression_value(self._visit(item))) for item in node.values)
            if isinstance(node.op, ast.Or):
                return any(bool(_unwrap_expression_value(self._visit(item))) for item in node.values)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not bool(_unwrap_expression_value(self._visit(node.operand)))
        if isinstance(node, ast.Compare):
            left = _unwrap_expression_value(self._visit(node.left))
            for operator, comparator in zip(node.ops, node.comparators):
                right = _unwrap_expression_value(self._visit(comparator))
                if isinstance(operator, ast.Eq):
                    matched = left == right
                elif isinstance(operator, ast.NotEq):
                    matched = left != right
                elif isinstance(operator, ast.In):
                    matched = left in right
                elif isinstance(operator, ast.NotIn):
                    matched = left not in right
                elif isinstance(operator, ast.Is):
                    matched = left is right
                elif isinstance(operator, ast.IsNot):
                    matched = left is not right
                else:
                    raise ValueError("Unsupported security comparison operator")
                if not matched:
                    return False
                left = right
            return True
        raise ValueError(
            f"Unsupported security expression syntax: {type(node).__name__}"
        )


def _authentication_expression_value() -> Dict[str, Any]:
    authentication = SecurityContextHolder.get_authentication() or {}
    principal = authentication.get('principal')
    if isinstance(principal, dict):
        name = principal.get('name') or principal.get('username') or principal.get('id')
    else:
        name = principal
    value = dict(authentication)
    value.setdefault('name', name)
    value.setdefault('principal', principal)
    return value


def _evaluate_expression(expression: str, **variables: Any) -> bool:
    """
    评估权限表达式
    
    Args:
        expression: 权限表达式
    
    Returns:
        是否满足条件
    """
    if not expression:
        return True
    context = {
        'authentication': _authentication_expression_value(),
        'principal': SecurityContextHolder.get_principal(),
        **variables,
    }
    try:
        return _SecurityExpressionEvaluator(context).evaluate(expression)
    except (SyntaxError, TypeError, ValueError, KeyError, AttributeError, IndexError):
        return False


def post_authorize_decorator(annotation):
    """Authorize after successful completion with ``returnObject`` available."""
    def decorator(func: Callable) -> Callable:
        def authorize(result: Any) -> None:
            if not SecurityContextHolder.is_authenticated():
                raise AuthenticationError("Authentication required")
            if not _evaluate_expression(annotation.value, returnObject=result):
                raise AuthorizationError("Access denied")

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                result = await func(*args, **kwargs)
                authorize(result)
                return result
            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            authorize(result)
            return result
        return wrapper
    return decorator


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
                from springbootai.security.oauth2 import oauth2_resource_server
                if oauth2_resource_server.is_configured:
                    payload = oauth2_resource_server.validate_token(token)
                else:
                    payload = jwt_utils.decode_token(token)
            except Exception as exc:
                # 对外不泄露签名算法、issuer、kid 等验证细节；详细原因保留在异常链中。
                raise AuthenticationError("Invalid token") from exc

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
    'PostAuthorize': post_authorize_decorator,
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
