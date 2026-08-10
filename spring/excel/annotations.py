"""SpringBootAI Excel 注解 —— 字段/类级映射元数据。

设计原则：**复用项目既有范式，不重复造轮子**。本模块的字段级注解完全镜像 ORM 层
``spring/orm/ddl_auto.py`` 的 ``Column`` / ``Id`` / ``@entity`` 元数据描述符范式：

- 字段级：``ExcelProperty`` / ``ExcelIgnore`` 作为类属性标记（描述符实例）或函数装饰器，
  元数据通过 ``cls.__dict__`` + MRO 反射读取（与 ``Column``/``__column__`` 一致）。
- 类级：``@excel_sheet`` 装饰器在类上设置 ``__excel_sheet__``（与 ``@entity`` 设置
  ``__entity__``/``__table__`` 一致）。

注解本身**不依赖 openpyxl**，可独立声明；仅 read/write 引擎实际需要 openpyxl。

对齐 alibaba EasyExcel 的核心注解：``@ExcelProperty`` / ``@ExcelIgnore`` / ``@ExcelSheet``。
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional, Type, Union


# ==================== 字段级注解 ====================

class ExcelProperty:
    """字段级注解：声明实体字段与 Excel 列的映射关系（镜像 ORM ``Column``）。

    两种使用方式（与 ``Column`` 一致）：

    1. 类属性描述符（推荐）::

           @excel_sheet("用户列表")
           class DemoData:
               id = ExcelProperty("ID", order=1)
               name = ExcelProperty("姓名", order=2)
               age = ExcelProperty("年龄", order=3, converter=IntConverter)

               def __init__(self, id=None, name=None, age=None):
                   self.id = id; self.name = name; self.age = age

    2. 函数装饰器（镜像 ``@column``）::

           @ExcelProperty("姓名", order=2)
           def name(self): ...

    属性说明（对齐 EasyExcel ``@ExcelProperty``）：
        value:        列标题（表头文案）。为空时用字段名转标题。
        order:        列顺序，越小越靠前；同 order 按 MRO 声明顺序。默认 0。
        index:        绝对列索引（从 0 起），设置后覆盖 order。默认 None。
        converter:    自定义转换器（``Converter`` 子类或实例）。默认 None（按类型自动选）。
        format:       通用格式占位（同时作 date_format/num_format 默认）。
        date_format:  日期格式串，如 ``%Y-%m-%d``。读时按此解析，写时按此格式化。
        num_format:   Excel 数字格式串，如 ``#,##0.00``。写时应用到单元格。
        width:        列宽（字符数）。0 表示自适应。
        big_number:   是否按字符串写入以避免 Excel 精度丢失（长 ID/大数）。默认 False。
        head_style:   自定义表头样式名（见 style 模块）。默认 None（用默认表头样式）。
        content_style:自定义内容样式名。默认 None。
        ignore:       内部等价 @ExcelIgnore 的快捷开关。默认 False。
    """

    def __init__(
        self,
        value: str = "",
        order: int = 0,
        index: Optional[int] = None,
        converter: Optional[Union[Type, Any]] = None,
        format: Optional[str] = None,
        date_format: Optional[str] = None,
        num_format: Optional[str] = None,
        width: float = 0,
        big_number: bool = False,
        head_style: Optional[str] = None,
        content_style: Optional[str] = None,
        ignore: bool = False,
    ):
        self.value = value
        self.order = order
        self.index = index
        self.converter = converter
        self.format = format
        self.date_format = date_format or format
        self.num_format = num_format
        self.width = width
        self.big_number = big_number
        self.head_style = head_style
        self.content_style = content_style
        self.ignore = ignore
        # 反射时回填
        self.attr_name: str = ""

    def __set_name__(self, owner: type, name: str) -> None:
        """类属性描述符形式时，Python 自动回填字段名。"""
        self.attr_name = name

    def __call__(self, target: Callable) -> Callable:
        """函数装饰器形式：``@ExcelProperty(...)``，把元数据挂到 ``__excel_property__``。

        镜像 ORM ``column()`` 装饰器的 ``setattr(f, '__column__', col)`` 写法。
        """
        setattr(target, "__excel_property__", self)
        # 函数上的 attr_name 取函数名
        self.attr_name = getattr(target, "__name__", "")
        return target

    def resolve_header(self, attr_name: str) -> str:
        """计算最终表头文案。"""
        return self.value or _field_to_header(attr_name)


class ExcelIgnore:
    """字段级注解：标记字段在读写时跳过（镜像 ORM 中跳过未标注字段的语义）。

    用法与 ``ExcelProperty`` 一致，支持类属性描述符与函数装饰器两种形式::

        remark = ExcelIgnore()
        # 或
        @ExcelIgnore()
        def remark(self): ...
    """

    def __init__(self):
        self.attr_name: str = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.attr_name = name

    def __call__(self, target: Callable) -> Callable:
        setattr(target, "__excel_ignore__", True)
        self.attr_name = getattr(target, "__name__", "")
        return target


# ==================== 类级注解 ====================

class ExcelSheet:
    """类级注解元数据：Excel 工作表配置（镜像 ORM ``Table``）。

    属性说明（对齐 EasyExcel ``@ExcelProperty`` + sheet 配置）：
        sheet_name:      工作表名称。为空时用 "Sheet1"（写）或按索引读（读）。
        head_row_number: 表头所在行号（从 1 起）。默认 1。读时数据从该行之后开始。
        freeze_head:     是否冻结表头行。默认 True（写时生效）。
        auto_width:      是否自适应列宽。默认 True。字段 ``width>0`` 时以字段为准。
        head_style:      默认表头样式名。
        content_style:   默认内容样式名。
    """

    def __init__(
        self,
        sheet_name: str = "",
        head_row_number: int = 1,
        freeze_head: bool = True,
        auto_width: bool = True,
        head_style: Optional[str] = None,
        content_style: Optional[str] = None,
    ):
        self.sheet_name = sheet_name
        self.head_row_number = head_row_number
        self.freeze_head = freeze_head
        self.auto_width = auto_width
        self.head_style = head_style
        self.content_style = content_style


def excel_sheet(
    sheet_name: str = "",
    head_row_number: int = 1,
    freeze_head: bool = True,
    auto_width: bool = True,
    head_style: Optional[str] = None,
    content_style: Optional[str] = None,
) -> Callable[[type], type]:
    """类级装饰器：标注实体类对应的 Excel 工作表配置（镜像 ORM ``@entity``）。

    用法::

        @excel_sheet("用户列表", head_row_number=1)
        class DemoData:
            id = ExcelProperty("ID", order=1)
            ...

    不使用本装饰器时，读写引擎使用默认配置（sheet_name="Sheet1"，head_row_number=1）。
    """
    meta = ExcelSheet(
        sheet_name=sheet_name,
        head_row_number=head_row_number,
        freeze_head=freeze_head,
        auto_width=auto_width,
        head_style=head_style,
        content_style=content_style,
    )

    def decorator(cls: type) -> type:
        setattr(cls, "__excel_sheet__", meta)
        return cls

    return decorator


# ==================== 元数据解析（复用 ORM 反射范式） ====================

class ExcelColumnModel:
    """解析后的列模型，供 reader/writer 统一消费。"""

    __slots__ = (
        "attr_name", "header", "order", "index", "converter", "date_format",
        "num_format", "width", "big_number", "head_style", "content_style",
        "py_type",
    )

    def __init__(
        self,
        attr_name: str,
        header: str,
        order: int,
        index: Optional[int],
        converter: Optional[Union[Type, Any]],
        date_format: Optional[str],
        num_format: Optional[str],
        width: float,
        big_number: bool,
        head_style: Optional[str],
        content_style: Optional[str],
        py_type: Any,
    ):
        self.attr_name = attr_name
        self.header = header
        self.order = order
        self.index = index
        self.converter = converter
        self.date_format = date_format
        self.num_format = num_format
        self.width = width
        self.big_number = big_number
        self.head_style = head_style
        self.content_style = content_style
        self.py_type = py_type

    @property
    def sort_key(self):
        """排序键：index 优先（None 视作大值靠后），其次 order，最后 attr_name 稳定。"""
        return (self.index if self.index is not None else float("inf"),
                self.order, self.attr_name)


def _field_to_header(name: str) -> str:
    """字段名转表头：snake_case/camelCase -> 友好标题。

    例：``user_name`` -> ``User Name``；``userName`` -> ``User Name``；``id`` -> ``Id``。
    """
    import re
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1 \2", name)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s1)
    return " ".join(part.capitalize() for part in s2.replace("_", " ").split())


def _get_class_sheet_meta(cls: type) -> ExcelSheet:
    """读取类上的 ``__excel_sheet__``，缺失则返回默认。镜像 ORM ``_parse_entity`` 读 ``__table__``。"""
    meta = getattr(cls, "__excel_sheet__", None)
    if isinstance(meta, ExcelSheet):
        return meta
    return ExcelSheet()


def _resolve_init_hints(cls: type) -> dict:
    """获取 ``__init__`` 参数的类型注解（用于无类属性注解时的类型推断）。"""
    import inspect
    try:
        from typing import get_type_hints
        return get_type_hints(cls.__init__)
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


def parse_excel_columns(cls: type) -> List[ExcelColumnModel]:
    """解析实体类的 Excel 列模型。

    解析顺序（镜像 ORM ``_parse_entity`` 对 ``Column`` 的处理）：
    1. 遍历 ``cls.__mro__`` 的 ``__dict__``，收集 ``ExcelProperty`` 实例或带
       ``__excel_property__`` 的成员；遇到 ``ExcelIgnore`` / ``__excel_ignore__`` 则跳过。
    2. 若类上没有任何 ``ExcelProperty`` 标记，回退到 ``__init__`` 参数列表，按字段名自动
       生成表头（让未改造的纯 ``__init__`` 模型如 ``example_all/models/User.py`` 也能导出）。
    3. 按 ``index`` -> ``order`` -> 声明顺序排序。
    """
    from .exceptions import ExcelPropertyError

    seen: dict = {}  # attr_name -> ExcelProperty
    ignored: set = set()
    declaration_order: dict = {}
    counter = 0

    for base in reversed(cls.__mro__):  # 自底向上，子类覆盖父类
        for attr_name, value in vars(base).items():
            if attr_name.startswith("__"):
                continue
            prop = None
            if isinstance(value, ExcelProperty):
                prop = value
                if not prop.attr_name:
                    prop.attr_name = attr_name
            elif hasattr(value, "__excel_property__"):
                prop = getattr(value, "__excel_property__")
                if not isinstance(prop, ExcelProperty):
                    continue
                if not prop.attr_name:
                    prop.attr_name = attr_name
            else:
                if isinstance(value, ExcelIgnore):
                    ignored.add(attr_name)
                    continue
                if getattr(value, "__excel_ignore__", False) is True:
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
        # 有显式 ExcelProperty 标记
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
        # 回退：没有任何 ExcelProperty 标记 -> 用 __init__ 参数自动建列
        for pname in _get_init_param_names(cls):
            if pname in ignored:
                continue
            columns.append(_to_column_model(
                attr_name=pname,
                prop=ExcelProperty(),  # 默认元数据
                decl_order=0,
                py_type=init_hints.get(pname, None),
            ))

    # 全部被 @ExcelIgnore 或无可导出字段时，统一抛错
    if not columns:
        raise ExcelPropertyError(
            f"类 {cls.__name__} 没有可导出字段（全部被 @ExcelIgnore，或无 __init__ 字段？）"
        )
    return columns


def _to_column_model(attr_name: str, prop: ExcelProperty, decl_order: int, py_type: Any) -> ExcelColumnModel:
    """把 ExcelProperty + 类型注解组装为 ExcelColumnModel。"""
    return ExcelColumnModel(
        attr_name=attr_name,
        header=prop.resolve_header(attr_name),
        order=prop.order if prop.order else decl_order,
        index=prop.index,
        converter=prop.converter,
        date_format=prop.date_format,
        num_format=prop.num_format,
        width=prop.width,
        big_number=prop.big_number,
        head_style=prop.head_style,
        content_style=prop.content_style,
        py_type=py_type,
    )


__all__ = [
    "ExcelProperty",
    "ExcelIgnore",
    "ExcelSheet",
    "excel_sheet",
    "ExcelColumnModel",
    "parse_excel_columns",
    "_get_class_sheet_meta",
]
