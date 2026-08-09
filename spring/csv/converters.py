"""SpringPy CSV 转换器 —— 复用 Excel 转换器，避免重复造轮子。

设计原则：**复用项目既有范式，不重复造轮子**。CSV 单元格与 Excel 单元格在 Python 值双向
转换上的语义完全一致（Python 值 ↔ 单元格字符串值），因此本模块直接复用
``spring.excel.converters`` 的 ``Converter`` 接口与内置转换器（int/float/bool/str/
datetime/Decimal），仅提供 CSV 友好的别名与解析入口。

转换器接口方法名仍为 ``to_excel`` / ``from_excel``（与 Excel 模块共享同一实现，避免分叉），
本模块在 reader/writer 中以这两个方法驱动转换；如需 CSV 语义别名，可使用下方
``CsvConverter`` 适配基类。

与 Excel 模块的区别：CSV 无单元格样式/数字格式，所有值最终都是字符串；转换器负责把字符串
解析回 Python 类型（读取）或把 Python 值格式化为字符串（写入）。
"""
from __future__ import annotations

from typing import Any, Optional

# 复用 Excel 转换器（spring.excel.converters 不依赖 openpyxl，可安全导入）
from spring.excel.converters import (
    Converter,
    StringConverter,
    IntegerConverter,
    FloatConverter,
    BooleanConverter,
    DateStringConverter,
    BigDecimalConverter,
    resolve_converter,
)


class CsvConverter(Converter):
    """CSV 转换器适配基类：提供 ``to_csv`` / ``from_csv`` 语义别名。

    子类继承 Excel 转换器的 ``to_excel`` / ``from_excel`` 实现，``to_csv`` / ``from_csv``
    直接委托，保持单一实现源（DRY）。用户自定义 CSV 转换器可继承本类，实现任一对方法即可。
    """

    def to_csv(self, value: Any) -> Any:
        return self.to_excel(value)

    def from_csv(self, cell_value: Any) -> Any:
        return self.from_excel(cell_value)


def resolve_csv_converter(
    py_type: Any,
    declared: Any = None,
    date_format: Optional[str] = None,
) -> Optional[Converter]:
    """CSV 转换器解析入口（委托 ``spring.excel.converters.resolve_converter``）。

    优先级与 Excel 一致：显式声明的 converter > 按类型注解自动选择 > None。
    """
    return resolve_converter(py_type, declared=declared, date_format=date_format)


__all__ = [
    "Converter",
    "CsvConverter",
    "StringConverter",
    "IntegerConverter",
    "FloatConverter",
    "BooleanConverter",
    "DateStringConverter",
    "BigDecimalConverter",
    "resolve_converter",
    "resolve_csv_converter",
]
