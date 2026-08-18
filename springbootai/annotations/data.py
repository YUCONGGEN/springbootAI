"""
数据 REST 注解

提供 Spring Data REST 风格的注解，将 Repository 自动暴露为 REST API。

使用示例::

    @RepositoryRestResource(path="users")
    class UserRepository(PagingAndSortingRepository):
        entity_class = User
        # ... CRUD 方法已由基类提供

    # 应用启动时自动注册以下端点：
    # GET    /api/users          列表（分页+排序）
    # GET    /api/users/{id}     详情
    # POST   /api/users          创建
    # PUT    /api/users/{id}     更新
    # DELETE /api/users/{id}     删除

对齐 Java Spring Data REST：
- Java 通过 @RepositoryRestResource 注解标记 Repository
- Python 版本提供同名注解，配合 @EnableDataRest 使用
"""
from typing import Optional, Type

from .core import SpringAnnotation


class RepositoryRestResource(SpringAnnotation):
    """标记 Repository 为可暴露的 REST 资源

    标记了此注解的 Repository 类会在应用启动时
    自动注册 CRUD REST 端点。

    Attributes:
        path: REST 路径（如 'users' → /api/users）
        entity_class: 实体类（必须指定，用于创建实例和文档）
        id_type: ID 字段类型（默认 int）
        exported: 是否暴露为 REST（默认 True，设为 False 可临时禁用）

    使用示例::

        @RepositoryRestResource(path="users", entity_class=User)
        class UserRestController:
            def find_all(self, pageable):
                ...

        @RepositoryRestResource(path="orders", entity_class=Order, exported=False)
        class OrderRepository:  # exported=False 时不注册 REST 端点
            ...
    """

    _annotation_type = "repository_rest"

    def __init__(
        self,
        path: str,
        entity_class: Optional[Type] = None,
        id_type: type = int,
        exported: bool = True,
    ):
        super().__init__(
            path=path,
            entity_class=entity_class,
            id_type=id_type,
            exported=exported,
        )
