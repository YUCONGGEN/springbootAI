"""
ORM 实体模型示例 — @Entity + @Table JPA 风格（v2.2.3）
================================================================
演示三种实体声明写法和字段自动推断：
  1. @Entity + @Table(...) 分离风格（推荐）
  2. @Entity 无括号（表名自动推导）
  3. @Entity("name", ...) 一体化风格（兼容）

字段自动推断规则：
  - name: str               → Column()（无默认值，仅记录类型）
  - name: str = ""          → Column(default="")（赋值即为默认值）
  - name: str = Column(...) → 保留原 Column，不覆盖
  - name: int = Id()        → 保留原 Id，不覆盖
  - _xxx: dict = {}         → 私有字段，跳过
"""
from springbootai.orm import Entity, Table, Column, Id, Index, CreateTime, Required, Text


# ============ 1. 推荐写法：@Entity + @Table 分离 ============

@Entity
@Table(
    name="welding_admin_users",
    indexes=[Index("idx_admin_username", ["username"], unique=True)],
    comment="焊工智能系统管理员",
)
class AdminUser:
    """管理员实体 — JPA @Entity + @Table 分离风格"""
    id: int = Id()                          # 主键，显式声明 Id
    username: str = ""                      # 赋值 → Column(default="")
    password_hash: str = ""                 # 赋值 → Column(default="")
    display_name: str = "系统管理员"         # 赋值 → Column(default="系统管理员")
    role: str = "ROLE_ADMIN"                # 赋值 → Column(default="ROLE_ADMIN")
    enabled: bool = True                    # 赋值 → Column(default=True)
    last_login_at: str                      # 无赋值 → Column() 无默认值
    created_at: str = CreateTime()          # 显式 CreateTime，自动填充创建时间
    _cache: dict = {}                       # 私有字段，跳过不持久化


# ============ 2. 简化写法：仅 @Entity，表名自动推导 ============

@Entity
class Product:
    """产品实体 — 表名自动推导为 'product'"""
    id: int = Id()
    name: str = ""                          # 赋值 → Column(default="")
    price: float = 0.0                      # 赋值 → Column(default=0.0)
    stock: int = 0                          # 赋值 → Column(default=0)
    description: str                        # 无赋值 → Column() 无默认值


# ============ 3. 兼容写法：一体化 @Entity("name", ...) ============

@Entity("sys_log", comment="系统日志")
class SysLog:
    """系统日志实体 — 一体化风格，完全兼容"""
    id: int = Id()
    module: str = Required(length=50)
    message: str = Text(required=True)
