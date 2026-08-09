"""SpringPy CSV 注解 —— 字段/类级映射元数据。

设计原则：**复用项目既有范式，不重复造轮子**。本模块的字段级注解完全镜像 Excel 模块
``spring/excel/annotations.py`` 的 ``@ExcelProperty`` / ``@ExcelIgnore`` / ``@excel_sheet``
元数据描述符范式（该范式又源自 ORM ``Column``/``@entity``）：

- 字段级：``CsvProperty`` / ``CsvIgnore`` 作为类属性标记（描述符实例）或函数装饰器，
  元数据通过 ``cls.__dict__`` + MRO 反射读取（与 ``Column``/``__column__`` 一致）。
- 类级：``@csv_file`` 装饰器在类上设置 ``__csv_file__``（与 ``@entity`` 设置
  ``__entity__``/``__table__``、``@excel_sheet`` 设置 ``__excel_sheet__`` 一致）。

注解本身不依赖任何第三方库（CSV 使用 Python 标准库 ``csv``）。

对齐常见 CSV 注解库（如 Python ``csv`` + 注解映射、Java ``commons-csv`` + 注解）的核心注解：
``@CsvProperty`` / ``@CsvIgnore`` / ``@CsvFile``。
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional, Type, Union


# ==================== 字段级注解 ====================

class CsvProperty:
    """字段级注解：声明实体字段与 CSV 列的映射关系（镜像 ORM ``Column`` / Excel ``ExcelProperty``）。

    两种使用方式（与 ``Column`` / ``ExcelProperty`` 一致）：

    1. 类属性描述符（推荐）::

           @csv_file("用户列表")
           class DemoData:
               id = CsvProperty("ID", order=1)
               name = CsvProperty("姓名", order=2)
               age = CsvProperty("年龄", order=3)

               def __init__(self, id=None, name=None, age=None):
                   self.id = id; self.name = name; self.age = age

    2. 函数装饰器（镜像 ``@column`` / ``@ExcelProperty``）::

           @CsvProperty("姓名", order=2)
           def name(self): ...

    属性说明（对齐 CSV 注解映射 + 复用 Excel 语义）：
        value:       列标题（表头文案）。为空时用字段名转标题。
        order:       列顺序，越小越靠前；同 order 按 MRO 声明顺序。默认 0。
        index:       绝对列索引（从 0 起），设置后覆盖 order。默认 None。
        converter:   自定义转换器（``Converter`` 子类或实例）。默认 None（按类型自动选）。
        format:      通用格式占位（同时作 date_format 默认）。
        date_format: 日期格式串，如 ``%Y-%m-%d``。读时按此解析，写时按此格式化。
        big_number:  是否按字符串写入（CSV 本身即字符串，此标记用于强制把数值原样保留，
                     避免 long ID 被解析回 int 后再写时丢精度）。默认 False。
        ignore:      内部等价 @CsvIgnore 的快捷开关。默认 False。
    """

    def __init__(
        self,
        value: str = "",
        order: int = 0,
        index: Optional[int] = None,
        converter: Optional[Union[Type, Any]] = None,
        format: Optional[str] = None,
        date_format: Optional[str] = None,
        big_number: bool = False,
        ignore: bool = False,
    ):
        self.value = value
        self.order = order
        self.index = index
        self.converter = converter
        self.format = format
        self.date_format = date_format or format
        self.big_number = big_number
        self.ignore = ignore
        # 反射时回填
        self.attr_name: str = ""

    def __set_name__(self, owner: type, name: str) -> None:
        """类属性描述符形式时，Python 自动回填字段名（镜像 ``ExcelProperty``）。"""
        self.attr_name = name

    def __call__(self, target: Callable) -> Callable:
        """函数装饰器形式：``@CsvProperty(...)``，把元数据挂到 ``__csv_property__``。

        镜像 ORM ``column()`` 的 ``setattr(f, '__column__', col)`` 与
        ``ExcelProperty.__call__`` 的 ``setattr(target, '__excel_property__', self)``。
        """
        setattr(target, "__csv_property__", self)
        self.attr_name = getattr(target, "__name__", "")
        return target

    def resolve_header(self, attr_name: str) -> str:
        """计算最终表头文案。"""
        return self.value or _field_to_header(attr_name)


class CsvIgnore:
    """字段级注解：标记字段在读写时跳过（镜像 ORM 中跳过未标注字段、Excel ``ExcelIgnore``）。

    用法与 ``CsvProperty`` 一致，支持类属性描述符与函数装饰器两种形式::

        remark = CsvIgnore()
        # 或
        @CsvIgnore()
        def remark(self): ...
    """

    def __init__(self):
        self.attr_name: str = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.attr_name = name

    def __call__(self, target: Callable) -> Callable:
        setattr(target, "__csv_ignore__", True)
        self.attr_name = getattr(target, "__name__", "")
        return target


# ==================== 类级注解 ====================

class CsvFile:
    """类级注解元数据：CSV 文件配置（镜像 ORM ``Table`` / Excel ``ExcelSheet``）。

    属性说明：
        file_name:     文件名（仅元数据，读写时由调用方传路径）。
        has_header:    是否包含表头行。默认 True（读时第一行作表头，写时先写表头）。
        delimiter:     字段分隔符。默认 ``,``。
        encoding:      文件编码。默认 ``utf-8-sig``（带 BOM，兼容 Excel 打开中文 CSV）。
        quote_char:    引用字符。默认 ``"``。
        line_terminator: 行终止符。默认 ``\\r\\n``（CSV 标准，复用 Excel 兼容）。
    """

    def __init__(
        self,
        file_name: str = "",
        has_header: bool = True,
        delimiter: str = ",",
        encoding: str = "utf-8-sig",
        quote_char: str = '"',
        line_terminator: str = "\r\n",
    ):
        self.file_name = file_name
        self.has_header = has_header
        self.delimiter = delimiter
        self.encoding = encoding
        self.quote_char = quote_char
        self.line_terminator = line_terminator


def csv_file(
    file_name: str = "",
    has_header: bool = True,
    delimiter: str = ",",
    encoding: str = "utf-8-sig",
    quote_char: str = '"',
    line_terminator: str = "\r\n",
) -> Callable[[type], type]:
    """类级装饰器：标注实体类对应的 CSV 文件配置（镜像 ORM ``@entity`` / Excel ``@excel_sheet``）。

    用法::

        @csv_file("用户列表", delimiter=",", encoding="utf-8-sig")
        class DemoData:
            id = CsvProperty("ID", order=1)
            ...

    不使用本装饰器时，读写引擎使用默认配置（has_header=True，delimiter=","，utf-8-sig）。
    """
    meta = CsvFile(
        file_name=file_name,
        has_header=has_header,
        delimiter=delimiter,
        encoding=encoding,
        quote_char=quote_char,
        line_terminator=line_terminator,
    )

    def decorator(cls: type) -> type:
        setattr(cls, "__csv_file__", meta)
        return cls

    return decorator


# ==================== 元数据解析（复用 ORM/Excel 反射范式） ====================

class CsvColumnModel:
    """解析后的列模型，供 reader/writer 统一消费（镜像 ``ExcelColumnModel``）。"""

    __slots__ = (
        "attr_name", "header", "order", "index", "converter", "date_format",
        "big_number", "py_type",
    )

    def __init__(
        self,
        attr_name: str,
        header: str,
        order: int,
        index: Optional[int],
        converter: Optional[Union[Type, Any]],
        date_format: Optional[str],
        big_number: bool,
        py_type: Any,
    ):
        self.attr_name = attr_name
        self.header = header
        self.order = order
        self.index = index
        self.converter = converter
        self.date_format = date_format
        self.big_number = big_number
        self.py_type = py_type

    @property
    def sort_key(self):
        """排序键：index 优先（None 视作大值靠后），其次 order，最后 attr_name 稳定。"""
        return (self.index if self.index is not None else float("inf"),
                self.order, self.attr_name)


def _field_to_header(name: str) -> str:
    """字段名转表头：snake_case/camelCase -> 友好标题（镜像 Excel ``_field_to_header``）。

    例：``user_name`` -> ``User Name``；``userName`` -> ``User Name``；``id`` -> ``Id``。
    """
    import re
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1 \2", name)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s1)
    return " ".join(part.capitalize() for part in s2.replace("_", " ").split())


def _get_class_file_meta(cls: type) -> CsvFile:
    """读取类上的 ``__csv_file__``，缺失则返回默认。镜像 ORM ``_parse_entity`` 读 ``__table__``。"""
    meta = getattr(cls, "__csv_file__", None)
    if isinstance(meta, CsvFile):
        return meta
    return CsvFile()


def _resolve_init_hints(cls: type) -> dict:
    """获取 ``__init__`` 参数的类型注解（用于无类属性注解时的类型推断）。

    返回的承载类型已解包 ``Optional[X]``：Python 3.10 的 ``get_type_hints`` 会把带
    ``None`` 默认值的参数注解自动包装为 ``Optional[X]``，3.11+ 不再包装。统一解包
    为承载类型，使转换器选择/类型推断与 Python 版本无关（可空性不由类型承载）。
    """
    import inspect
    try:
        from typing import get_type_hints
        from spring.core.typing_utils import unwrap_optional_type
        hints = get_type_hints(cls.__init__)
        return {k: unwrap_optional_type(v) for k, v in hints.items()}
    except Exception:
        try:
            return dict(inspect.signature(cls).parameters)
        except Exception:
            return {}


def _get_init_param_names(cls: type) -> List[str]:
    """提取 ``__init__`` 中 ``self.xxx`` 以外的参数名，作为字段名回退顺序。"""
    import inspect
    try:
        sig = inspect.signature(cls.__init__)
    except (TypeError, ValueError):
        return []
    names = []
    for pname, param in list(sig.parameters.items())[1:]:  # 跳过 self
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        names.append(pname)
    return names


def parse_csv_columns(cls: type) -> List[CsvColumnModel]:
    """解析实体类的 CSV 列模型（镜像 Excel ``parse_excel_columns``）。

    解析顺序（镜像 ORM ``_parse_entity`` 对 ``Column`` 的处理）：
    1. 遍历 ``cls.__mro__`` 的 ``__dict__``，收集 ``CsvProperty`` 实例或带
       ``__csv_property__`` 的成员；遇到 ``CsvIgnore`` / ``__csv_ignore__`` 则跳过。
    2. 若类上没有任何 ``CsvProperty`` 标记，回退到 ``__init__`` 参数列表，按字段名自动
       生成表头（让未改造的纯 ``__init__`` 模型也能导入导出）。
    3. 按 ``index`` -> ``order`` -> 声明顺序排序。
    """
    from .exceptions import CsvPropertyError

    seen: dict = {}  # attr_name -> CsvProperty
    ignored: set = set()
    declaration_order: dict = {}
    counter = 0

    for base in reversed(cls.__mro__):  # 自底向上，子类覆盖父类
        for attr_name, value in vars(base).items():
            if attr_name.startswith("__"):
                continue
            prop = None
            if isinstance(value, CsvProperty):
                prop = value
                if not prop.attr_name:
                    prop.attr_name = attr_name
            elif hasattr(value, "__csv_property__"):
                prop = getattr(value, "__csv_property__")
                if not isinstance(prop, CsvProperty):
                    continue
                if not prop.attr_name:
                    prop.attr_name = attr_name
            else:
                if isinstance(value, CsvIgnore):
                    ignored.add(attr_name)
                    continue
                if getattr(value, "__csv_ignore__", False) is True:
                    ignored.add(attr_name)
                    continue
                continue
            if attr_name in ignored:
                continue
            if prop.ignore:
                ignored.add(attr_name)
                continue
            if attr_name not in declaration_order:
                declaration_order[attr_name] = counter
                counter += 1
            # 子类覆盖父类
            seen[attr_name] = (prop, declaration_order[attr_name])

    init_hints = _resolve_init_hints(cls)

    columns = []

    if seen:
        # 有显式 CsvProperty 标记
        for attr_name, (prop, decl_order) in seen.items():
            columns.append(_to_column_model(
                attr_name=attr_name,
                prop=prop,
                decl_order=decl_order,
                py_type=init_hints.get(attr_name, None),
            ))
        # 排序：index 优先，其次 order，最后声明顺序
        columns.sort(key=lambda c: (
            c.index if c.index is not None else float("inf"),
            c.order,
            declaration_order.get(c.attr_name, 0),
        ))
    else:
        # 回退：没有任何 CsvProperty 标记 -> 用 __init__ 参数自动建列
        for pname in _get_init_param_names(cls):
            if pname in ignored:
                continue
            columns.append(_to_column_model(
                attr_name=pname,
                prop=CsvProperty(),  # 默认元数据
                decl_order=0,
                py_type=init_hints.get(pname, None),
            ))

    # 全部被 @CsvIgnore 或无可导出字段时，统一抛错
    if not columns:
        raise CsvPropertyError(
            f"类 {cls.__name__} 没有可导出字段（全部被 @CsvIgnore，或无 __init__ 字段？）"
        )
    return columns


def _to_column_model(attr_name: str, prop: CsvProperty, decl_order: int, py_type: Any) -> CsvColumnModel:
    """把 CsvProperty + 类型注解组装为 CsvColumnModel。"""
    return CsvColumnModel(
        attr_name=attr_name,
        header=prop.resolve_header(attr_name),
        order=prop.order if prop.order else decl_order,
        index=prop.index,
        converter=prop.converter,
        date_format=prop.date_format,
        big_number=prop.big_number,
        py_type=py_type,
    )


def has_explicit_properties(cls: type) -> bool:
    """类上是否声明了至少一个 CsvProperty（用于决定按表头还是按位置匹配）。"""
    for base in cls.__mro__:
        for value in vars(base).values():
            if isinstance(value, CsvProperty):
                return True
            if hasattr(value, "__csv_property__"):
                return True
    return False


__all__ = [
    "CsvProperty",
    "CsvIgnore",
    "CsvFile",
    "csv_file",
    "CsvColumnModel",
    "parse_csv_columns",
    "_get_class_file_meta",
    "has_explicit_properties",
]
