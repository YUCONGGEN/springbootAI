"""SpringBootAI Spring Data 模块（对齐 Spring Data Commons / Spring Data JPA）。

提供基于实体元数据的统一数据访问抽象：分页（``Pageable``/``Page``）、排序（``Sort``）、
动态查询（``Specification``）、CRUD 仓库基类（``PagingAndSortingRepository``）。

复用现有范式：
- 实体解析复用 ``springbootai.orm.ddl_auto.DdlAutoManager._parse_entity``
- SQL 执行复用 ``OptimisticLockExecutor`` 的轻量范式（pool + cursor）
- 无需 PyMyBatis ``SqlSession`` 即可使用

用法::

    from springbootai.data import PagingAndSortingRepository, Pageable, Sort, Specifications
    from springbootai.orm import entity, Id, Column

    @entity("user")
    class User:
        id = Id()
        name = Column("user_name")
        age = Column()
        def __init__(self, id=None, name=None, age=None):
            self.id = id; self.name = name; self.age = age

    repo = PagingAndSortingRepository(pool, User, dialect="sqlite")
    repo.save(User(name="Tom", age=18))
    page = repo.find_all(pageable=Pageable.of(0, 10, Sort.by("age")))
    adults = repo.find_all(specification=Specifications.greater_equal("age", 18))
"""
from springbootai.data.page import Direction, Order, Sort, Pageable, Page
from springbootai.data.specification import (
    Specification,
    And, Or, Not,
    Predicate, ColResolver,
    Specifications,
)
from springbootai.data.repository import (
    PagingAndSortingRepository,
    DataRepository,
    get_data_repository_entity,
)

__version__ = "2.3.8"

__all__ = [
    # 分页/排序
    "Direction", "Order", "Sort", "Pageable", "Page",
    # 动态查询
    "Specification", "And", "Or", "Not", "Predicate", "ColResolver",
    "Specifications",
    # 仓库
    "PagingAndSortingRepository",
    "DataRepository", "get_data_repository_entity",
    "__version__",
]
