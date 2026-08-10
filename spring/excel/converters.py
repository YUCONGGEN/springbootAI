"""SpringBootAI Excel 转换器 —— Python 值与 Excel 单元格值之间的双向转换。

对齐 EasyExcel 的 ``Converter`` 机制：用户可实现 ``Converter`` 接口自定义任意类型的读写转换；
内置常用类型（int/float/bool/str/datetime/date/Decimal）的转换器，并在未显式指定 converter 时
按字段类型注解自动选择。
"""
from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Type


class Converter:
    """转换器接口（对齐 EasyExcel ``Converter``）。

    子类需实现：
        - ``to_excel(value)``   ：Python 值 -> Excel 单元格写入值
        - ``from_excel(cell_value)``：Excel 单元格读出值 -> Python 值
    """

    def to_excel(self, value: Any) -> Any:
        raise NotImplementedError

    def from_excel(self, cell_value: Any) -> Any:
        raise NotImplementedError


# ==================== 内置转换器 ====================

class StringConverter(Converter):
    def to_excel(self, value: Any) -> Any:
        return "" if value is None else str(value)

    def from_excel(self, cell_value: Any) -> Optional[str]:
        if cell_value is None:
            return None
        return str(cell_value).strip()


class IntegerConverter(Converter):
    def to_excel(self, value: Any) -> Any:
        if value is None or value == "":
            return None
        return int(value)

    def from_excel(self, cell_value: Any) -> Optional[int]:
        if cell_value is None or cell_value == "":
            return None
        try:
            # 容错：单元格可能是 "12.0" 或 12.9（截断为 int）
            return int(float(str(cell_value).strip()))
        except (TypeError, ValueError):
            return None


class FloatConverter(Converter):
    def to_excel(self, value: Any) -> Any:
        if value is None or value == "":
            return None
        return float(value)

    def from_excel(self, cell_value: Any) -> Optional[float]:
        if cell_value is None or cell_value == "":
            return None
        try:
            return float(str(cell_value).strip())
        except (TypeError, ValueError):
            return None


class BooleanConverter(Converter):
    """布尔转换器：写为 True/False，读时兼容 1/0、true/false、是/否、yes/no。"""

    _TRUE_TOKENS = {"1", "true", "yes", "y", "t", "是", "✓"}
    _FALSE_TOKENS = {"0", "false", "no", "n", "f", "否", ""}

    def to_excel(self, value: Any) -> Any:
        if value is None:
            return None
        return bool(value)

    def from_excel(self, cell_value: Any) -> Optional[bool]:
        if cell_value is None:
            return None
        if isinstance(cell_value, bool):
            return cell_value
        token = str(cell_value).strip().lower()
        if token in self._TRUE_TOKENS:
            return True
        if token in self._FALSE_TOKENS:
            return False
        # 数值非零视为 True
        try:
            return float(token) != 0
        except ValueError:
            return None


class DateStringConverter(Converter):
    """日期/时间按格式串在 Python str 与 Excel 之间转换。

    写入：datetime/date -> 按 ``fmt`` 格式化为字符串（避免 Excel 自动改写日期）。
    读取：单元格值（str 或 datetime）-> 按 ``fmt`` 解析为 datetime。
    """

    def __init__(self, fmt: str = "%Y-%m-%d %H:%M:%S"):
        self.fmt = fmt

    def to_excel(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (datetime.datetime, datetime.date)):
            return value.strftime(self.fmt)
        return str(value)

    def from_excel(self, cell_value: Any) -> Optional[datetime.datetime]:
        if cell_value is None or cell_value == "":
            return None
        if isinstance(cell_value, datetime.datetime):
            return cell_value
        if isinstance(cell_value, datetime.date):
            return datetime.datetime(cell_value.year, cell_value.month, cell_value.day)
        text = str(cell_value).strip()
        try:
            return datetime.datetime.strptime(text, self.fmt)
        except ValueError:
            # 兜底：尝试 ISO 与常见格式
            for fallback in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
                try:
                    return datetime.datetime.strptime(text, fallback)
                except ValueError:
                    continue
            return None


class BigDecimalConverter(Converter):
    """大数/金额转换器：以字符串读写，避免 Excel 浮点精度丢失（EasyExcel 经典特性）。

    写入：Decimal/float/int/str -> 原样字符串。
    读取：单元格值 -> Decimal。
    """

    def to_excel(self, value: Any) -> Any:
        if value is None:
            return None
        return str(value)

    def from_excel(self, cell_value: Any) -> Optional[Decimal]:
        if cell_value is None or cell_value == "":
            return None
        try:
            return Decimal(str(cell_value).strip())
        except (InvalidOperation, ValueError):
            return None


# ==================== 自动选择 ====================

# Python 类型 -> 默认转换器类
_TYPE_CONVERTER_MAP: dict = {
    int: IntegerConverter,
    float: FloatConverter,
    bool: BooleanConverter,
    str: StringConverter,
    Decimal: BigDecimalConverter,
    datetime.datetime: DateStringConverter,
    datetime.date: DateStringConverter,
}


def resolve_converter(py_type: Any, declared: Any = None, date_format: Optional[str] = None) -> Optional[Converter]:
    """解析最终使用的转换器实例。

    优先级：显式声明的 converter > 按类型注解自动选择 > None（由引擎按原值处理）。

    Args:
        py_type:    字段类型注解（可能为 None）。
        declared:   ``@ExcelProperty(converter=...)`` 显式声明的转换器类或实例。
        date_format:日期格式串，仅在自动选择 DateStringConverter 时使用。
    """
    if declared is not None:
        if isinstance(declared, Converter):
            return declared
        if isinstance(declared, type) and issubclass(declared, Converter):
            # DateStringConverter 支持注入 date_format
            if issubclass(declared, DateStringConverter):
                return declared(date_format or "%Y-%m-%d %H:%M:%S")
            return declared()
        # 容错：用户传了非 Converter 对象，直接返回（用户自负其责）
        return declared

    if py_type is None:
        return None
    # 解析 typing 可选类型如 Optional[int]
    origin = getattr(py_type, "__origin__", None)
    args = getattr(py_type, "__args__", ())
    if origin is not None and args:
        # 取非 None 的第一个参数
        candidates = [a for a in args if a is not type(None)]  # noqa: E721
        if len(candidates) == 1:
            py_type = candidates[0]

    converter_cls = _TYPE_CONVERTER_MAP.get(py_type)
    if converter_cls is None:
        # datetime 子类 / Decimal 等
        for mapped_type, cls in _TYPE_CONVERTER_MAP.items():
            try:
                if py_type is not None and isinstance(py_type, type) and issubclass(py_type, mapped_type):
                    converter_cls = cls
                    break
            except TypeError:
                continue
    if converter_cls is None:
        return None
    if issubclass(converter_cls, DateStringConverter):
        fmt = date_format or ("%Y-%m-%d" if py_type is datetime.date else "%Y-%m-%d %H:%M:%S")
        return converter_cls(fmt)
    return converter_cls()


__all__ = [
    "Converter",
    "StringConverter",
    "IntegerConverter",
    "FloatConverter",
    "BooleanConverter",
    "DateStringConverter",
    "BigDecimalConverter",
    "resolve_converter",
]
