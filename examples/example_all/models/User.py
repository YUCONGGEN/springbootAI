"""example_all 学习应用使用的框架优先 ORM 实体。

本文件重点是声明，而不是手写样板：@Entity 将类注册到 DDL 自动建表，Id 标记
生成主键，Required 表达 NOT NULL 约束，Index 创建数据库索引，CreateTime/UpdateTime
提供审计时间。@Data、@Get、@Set 和 @ToString 自动生成访问器与对象表示方法，
同时保留普通方法供调试和扩展。
"""

from springbootai.annotations import Data, Get, Set, ToString
from springbootai.orm import CreateTime, Entity, Id, Index, Required, UpdateTime


@Data
@Entity(
    "users",
    indexes=[
        Index("idx_user_username", ["username"], unique=True),
        Index("idx_user_email", ["email"], unique=True),
    ],
    comment="example_all user entity",
)
class User:
    """使用 @Data 生成完整模型样板的用户实体。

    email: str 这样的普通类型声明交给 @Entity 类型推断，会成为可空的 Column() 字段。
    只有数据库必须拒绝 NULL 时才使用 Required。@Data 会生成 get_<field>()、
    set_<field>()、__str__/__repr__ 和基于值的相等判断。
    """

    id: int = Id()
    username: str = Required(length=50)
    email: str
    phone: str
    created_at: str = CreateTime()
    updated_at: str = UpdateTime()

    def to_dict(self) -> dict:
        """将实体转换为 Mapper 示例返回的数据结构。"""
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "phone": self.phone,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@Get
@Set
@ToString
@Entity(
    "orders",
    indexes=[Index("idx_order_user", ["user_id"])],
    comment="example_all order entity",
)
class Order:
    """订单实体，展示 @Data 由哪些独立注解组合而成。"""

    id: int = Id()
    user_id: int = Required()
    product_name: str = Required(length=200)
    amount: float = Required(default=0.0)
    status: str = Required(length=20, default="pending")
    created_at: str = CreateTime()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "product_name": self.product_name,
            "amount": self.amount,
            "status": self.status,
            "created_at": self.created_at,
        }
