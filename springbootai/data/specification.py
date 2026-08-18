"""Spring Data JPA 风格的动态查询 ``Specification``（对齐 ``org.springframework.data.jpa.domain.Specification``）。

将查询条件抽象为可组合的谓词，``to_predicate()`` 返回 ``(where_sql, params)``，
由 ``PagingAndSortingRepository`` 拼入 SQL。支持 ``and`` / ``or`` / ``not`` 复合。

与 Java 差异：
- Java 的 ``Specification.to_predicate(Root, CriteriaQuery, CriteriaBuilder)`` 依赖 JPA Criteria API；
  Python 无等价物，故简化为返回 ``(where_sql_fragment, params)`` 元组。
- 列名翻译通过 ``col_resolver``（``property_name -> sql_column_name``）回调完成，
  与 ``Pageable.Sort`` 一致，避免 ``Column(name=...)`` 自定义列名时生成错误 SQL。
"""
from abc import ABC, abstractmethod
from typing import Any, Callable, List, Optional, Tuple, TypeVar

T = TypeVar("T")

# 谓词返回类型：(SQL 片段, 参数列表)；SQL 片段为空串表示无条件
Predicate = Tuple[str, List[Any]]
ColResolver = Callable[[str], str]


class Specification(ABC):
    """查询规范抽象基类。"""

    @abstractmethod
    def to_predicate(self, col_resolver: Optional[ColResolver] = None) -> Predicate:
        """返回 ``(where_sql, params)``。``where_sql`` 为空串表示无条件。"""

    def and_(self, other: "Specification") -> "Specification":
        return And(self, other)

    def or_(self, other: "Specification") -> "Specification":
        return Or(self, other)

    def not_(self) -> "Specification":
        return Not(self)


def _resolve(prop: str, col_resolver: Optional[ColResolver]) -> str:
    return col_resolver(prop) if col_resolver else prop


class _Empty(Specification):
    def to_predicate(self, col_resolver: Optional[ColResolver] = None) -> Predicate:
        return "", []


class And(Specification):
    def __init__(self, *specs: Specification):
        self.specs = specs

    def to_predicate(self, col_resolver: Optional[ColResolver] = None) -> Predicate:
        parts: List[str] = []
        params: List[Any] = []
        for s in self.specs:
            sql, p = s.to_predicate(col_resolver)
            if sql:
                parts.append(f"({sql})")
                params.extend(p)
        if not parts:
            return "", []
        return " AND ".join(parts), params


class Or(Specification):
    def __init__(self, *specs: Specification):
        self.specs = specs

    def to_predicate(self, col_resolver: Optional[ColResolver] = None) -> Predicate:
        parts: List[str] = []
        params: List[Any] = []
        for s in self.specs:
            sql, p = s.to_predicate(col_resolver)
            if sql:
                parts.append(f"({sql})")
                params.extend(p)
        if not parts:
            return "", []
        return " OR ".join(parts), params


class Not(Specification):
    def __init__(self, spec: Specification):
        self.spec = spec

    def to_predicate(self, col_resolver: Optional[ColResolver] = None) -> Predicate:
        sql, params = self.spec.to_predicate(col_resolver)
        if not sql:
            return "", []
        return f"NOT ({sql})", params


class _Comparison(Specification):
    """单字段比较谓词基类。"""

    def __init__(self, property: str, op: str, value: Any, negated: bool = False):
        self.property = property
        self.op = op
        self.value = value
        self.negated = negated

    def to_predicate(self, col_resolver: Optional[ColResolver] = None) -> Predicate:
        col = _resolve(self.property, col_resolver)
        op = self.op if not self.negated else _negate_op(self.op)
        return f"{col} {op} ?", [self.value]


def _negate_op(op: str) -> str:
    return {
        "=": "<>", "<>": "=", "!=": "=",
        ">": "<=", "<": ">=", ">=": "<", "<=": ">",
        "LIKE": "NOT LIKE", "IN": "NOT IN", "IS": "IS NOT",
    }.get(op, f"NOT {op}")


class _Like(Specification):
    def __init__(self, property: str, pattern: str, case_insensitive: bool = False):
        self.property = property
        self.pattern = pattern
        self.case_insensitive = case_insensitive

    def to_predicate(self, col_resolver: Optional[ColResolver] = None) -> Predicate:
        col = _resolve(self.property, col_resolver)
        if self.case_insensitive:
            return f"LOWER({col}) LIKE LOWER(?)", [self.pattern]
        return f"{col} LIKE ?", [self.pattern]


class _In(Specification):
    def __init__(self, property: str, values: list):
        self.property = property
        self.values = list(values)

    def to_predicate(self, col_resolver: Optional[ColResolver] = None) -> Predicate:
        col = _resolve(self.property, col_resolver)
        if not self.values:
            return "1=0", []  # 空集合：恒假
        placeholders = ", ".join("?" for _ in self.values)
        return f"{col} IN ({placeholders})", list(self.values)


class _IsNull(Specification):
    def __init__(self, property: str, negate: bool = False):
        self.property = property
        self.negate = negate

    def to_predicate(self, col_resolver: Optional[ColResolver] = None) -> Predicate:
        col = _resolve(self.property, col_resolver)
        return (f"{col} IS NOT NULL" if self.negate else f"{col} IS NULL"), []


class _Between(Specification):
    def __init__(self, property: str, low: Any, high: Any):
        self.property = property
        self.low = low
        self.high = high

    def to_predicate(self, col_resolver: Optional[ColResolver] = None) -> Predicate:
        col = _resolve(self.property, col_resolver)
        return f"{col} BETWEEN ? AND ?", [self.low, self.high]


class Specifications:
    """``Specification`` 静态工厂（对齐 Spring ``Specifications`` 工具类）。"""

    @staticmethod
    def empty() -> Specification:
        return _Empty()

    @staticmethod
    def where(spec: Optional[Specification] = None) -> Specification:
        return spec if spec is not None else _Empty()

    @staticmethod
    def equal(property: str, value: Any) -> Specification:
        return _Comparison(property, "=", value)

    @staticmethod
    def not_equal(property: str, value: Any) -> Specification:
        return _Comparison(property, "<>", value)

    @staticmethod
    def greater_than(property: str, value: Any) -> Specification:
        return _Comparison(property, ">", value)

    @staticmethod
    def greater_equal(property: str, value: Any) -> Specification:
        return _Comparison(property, ">=", value)

    @staticmethod
    def less_than(property: str, value: Any) -> Specification:
        return _Comparison(property, "<", value)

    @staticmethod
    def less_equal(property: str, value: Any) -> Specification:
        return _Comparison(property, "<=", value)

    @staticmethod
    def like(property: str, pattern: str, case_insensitive: bool = False) -> Specification:
        return _Like(property, pattern, case_insensitive)

    @staticmethod
    def in_(property: str, values: list) -> Specification:
        return _In(property, values)

    @staticmethod
    def is_null(property: str) -> Specification:
        return _IsNull(property, negate=False)

    @staticmethod
    def is_not_null(property: str) -> Specification:
        return _IsNull(property, negate=True)

    @staticmethod
    def between(property: str, low: Any, high: Any) -> Specification:
        return _Between(property, low, high)

    @staticmethod
    def and_(spec: Specification, *others: Specification) -> Specification:
        return And(spec, *others)

    @staticmethod
    def or_(spec: Specification, *others: Specification) -> Specification:
        return Or(spec, *others)

    @staticmethod
    def not_(spec: Specification) -> Specification:
        return Not(spec)
