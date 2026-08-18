"""
安全注解控制器 — 测试 @PreAuthorize, @Secured, @Authenticate
"""
from springbootai.annotations.core import (
    RestController, RequestMapping, GetMapping, PostMapping, DeleteMapping,
    Autowired, PreAuthorize, Secured, Authenticate, Slf4j,
)
from springbootai.web.result import Result
from example_all.service.SecurityService import SecurityService


@RestController
@RequestMapping("/api/security")
@Slf4j
class SecurityController:
    """安全注解测试控制器"""

    @Autowired
    def __init__(self, security_service: SecurityService):
        self.security_service = security_service

    # ==================== @Authenticate 认证测试 ====================

    @PostMapping("/login")
    def login(self, username: str, role: str = "USER"):
        """模拟登录 — 生成 JWT Token 并设置安全上下文"""
        token = self.security_service.generate_token(username, role)
        return Result.success(data={"token": token, "username": username, "role": role})

    @GetMapping("/profile")
    @Authenticate
    def get_profile(self):
        """@Authenticate — 需要 JWT 认证"""
        return Result.success(data=self.security_service.get_current_user())

    # ==================== @PreAuthorize 权限测试 ====================

    @GetMapping("/admin/data")
    @Authenticate
    @PreAuthorize("hasRole('ROLE_ADMIN')")
    def admin_data(self):
        """@PreAuthorize — hasRole('ROLE_ADMIN')"""
        return Result.success(data={"secret": "Admin-only data", "level": "top_secret"})

    @GetMapping("/user/data")
    @Authenticate
    @PreAuthorize("hasAnyRole('ROLE_ADMIN', 'ROLE_USER')")
    def user_data(self):
        """@PreAuthorize — hasAnyRole"""
        return Result.success(data={"data": "User-level data"})

    @GetMapping("/resource/read")
    @Authenticate
    @PreAuthorize("hasPermission('resource:read')")
    def resource_read(self):
        """@PreAuthorize — hasPermission"""
        return Result.success(data={"permission": "resource:read", "granted": True})

    @GetMapping("/resource/write")
    @Authenticate
    @PreAuthorize("hasAnyPermission('resource:write', 'admin:all')")
    def resource_write(self):
        """@PreAuthorize — hasAnyPermission"""
        return Result.success(data={"permission": "resource:write", "granted": True})

    # ==================== @Secured 角色测试 ====================

    @DeleteMapping("/user/{user_id}")
    @Authenticate
    @Secured(["ROLE_ADMIN"])
    def delete_user(self, user_id: int):
        """@Secured — 只有 ROLE_ADMIN 可以删除用户"""
        return Result.success(data={"deleted": user_id, "by": "admin"})

    @PostMapping("/data/update")
    @Authenticate
    @Secured(["ROLE_ADMIN", "ROLE_MODERATOR"])
    def update_data(self, data: dict):
        """@Secured — ROLE_ADMIN 或 ROLE_MODERATOR"""
        return Result.success(data={"updated": data, "by": "moderator_or_admin"})

    # ==================== 组合测试 ====================

    @GetMapping("/combined")
    @Authenticate
    @PreAuthorize("hasRole('ROLE_ADMIN')")
    @Secured(["ROLE_ADMIN"])
    def combined_security(self):
        """@Authenticate + @PreAuthorize + @Secured 组合"""
        return Result.success(data={"message": "Triple security check passed"})

    # ==================== 公开端点 ====================

    @GetMapping("/public")
    def public_data(self):
        """无需认证的公开端点"""
        return Result.success(data={"message": "这是公开数据"})
