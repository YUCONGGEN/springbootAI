"""Spring Data 风格的分页/排序值对象（对齐 ``org.springframework.data.domain``）。

提供 ``Pageable`` / ``Page`` / ``Sort`` / ``Order``，供 ``PagingAndSortingRepository``
与上层服务使用。纯值对象，无 IO 依赖，便于单测。

与 Java 差异：
- ``Pageable`` 为可实例化的值对象（Python 无接口），``.offset`` 直接计算为 ``(page_number) * page_size``。
- ``Sort.Order`` 的 ``direction`` 用枚举 ``Direction.ASC/DESC``。
- 页码从 0 起（与 Spring Data 一致），``page_number=0`` 为第一页。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, List, Optional, TypeVar

T = TypeVar("T")


class Direction(Enum):
    ASC = "ASC"
    DESC = "DESC"


@dataclass(frozen=True)
class Order:
    """单字段排序指令。"""
    property: str
    direction: Direction = Direction.ASC

    @staticmethod
    def asc(property: str) -> "Order":
        return Order(property=property, direction=Direction.ASC)

    @staticmethod
    def desc(property: str) -> "Order":
        return Order(property=property, direction=Direction.DESC)

    def to_sql(self, col_resolver=None) -> str:
        """转 SQL 片段 ``"col" ASC``。

        Args:
            col_resolver: 可选 ``property_name -> sql_column_name`` 映射函数，
                          用于把 Python 属性名翻译为真实列名（对齐 ``Column(name=...)``）。
        """
        col = col_resolver(self.property) if col_resolver else self.property
        return f"{col} {self.direction.value}"


class Sort:
    """多字段排序（对齐 ``Sort``）。空 ``orders`` 表示不排序。

    不可变值对象：构造后 ``orders`` 为 tuple。
    """

    __slots__ = ("orders",)

    def __init__(self, *orders):
        object.__setattr__(self, "orders", tuple(orders))

    def __setattr__(self, name, value):
        raise AttributeError("Sort 是不可变值对象")

    def __delattr__(self, name):
        raise AttributeError("Sort 是不可变值对象")

    def __eq__(self, other):
        return isinstance(other, Sort) and self.orders == other.orders

    def __repr__(self):
        return f"Sort({', '.join(repr(o) for o in self.orders)})"

    @staticmethod
    def by(*properties: str) -> "Sort":
        return Sort(*[Order(p) for p in properties])

    @staticmethod
    def unsorted() -> "Sort":
        return Sort()

    @property
    def is_sorted(self) -> bool:
        return bool(self.orders)

    def to_sql(self, col_resolver=None) -> str:
        if not self.orders:
            return ""
        return ", ".join(o.to_sql(col_resolver) for o in self.orders)


@dataclass(frozen=True)
class Pageable:
    """分页请求（页码从 0 起）。"""
    page_number: int = 0
    page_size: int = 20
    sort: Sort = field(default_factory=Sort.unsorted)

    def __post_init__(self):
        if self.page_number < 0:
            raise ValueError(f"page_number 不能为负: {self.page_number}")
        if self.page_size <= 0:
            raise ValueError(f"page_size 必须为正: {self.page_size}")

    @property
    def offset(self) -> int:
        return self.page_number * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size

    def next(self) -> "Pageable":
        return Pageable(self.page_number + 1, self.page_size, self.sort)

    def previous_or_first(self) -> "Pageable":
        return Pageable(max(0, self.page_number - 1), self.page_size, self.sort)

    def first(self) -> "Pageable":
        return Pageable(0, self.page_size, self.sort)

    @staticmethod
    def of(page_number: int = 0, page_size: int = 20, sort: Optional[Sort] = None) -> "Pageable":
        return Pageable(page_number, page_size, sort or Sort.unsorted())


@dataclass
class Page(Generic[T]):
    """分页结果（对齐 ``Page<T>``）。"""
    content: List[T]
    pageable: Pageable
    total: int

    @property
    def number(self) -> int:
        return self.pageable.page_number

    @property
    def size(self) -> int:
        return self.pageable.page_size

    @property
    def total_pages(self) -> int:
        if self.size == 0:
            return 0
        return (self.total + self.size - 1) // self.size

    @property
    def number_of_elements(self) -> int:
        return len(self.content)

    @property
    def has_content(self) -> bool:
        return bool(self.content)

    @property
    def has_next(self) -> bool:
        return self.number + 1 < self.total_pages

    @property
    def has_previous(self) -> bool:
        return self.number > 0

    @property
    def is_first(self) -> bool:
        return self.number == 0

    @property
    def is_last(self) -> bool:
        return not self.has_next

    @property
    def is_empty(self) -> bool:
        return not self.has_content

    def next_pageable(self) -> Optional[Pageable]:
        return self.pageable.next() if self.has_next else None

    def previous_pageable(self) -> Optional[Pageable]:
        return self.pageable.previous_or_first() if self.has_previous else None

    @staticmethod
    def empty(pageable: Pageable) -> "Page":
        return Page([], pageable, 0)
