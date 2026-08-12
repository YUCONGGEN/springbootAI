"""SpringBootAI Excel 模块 —— 注解驱动的 Excel 读写（对齐 alibaba EasyExcel）。

模块组成：
- annotations:  ``@ExcelProperty`` / ``@ExcelIgnore`` / ``@excel_sheet`` 字段+类级注解
                 （复用 ORM ``Column``/``@entity`` 元数据描述符范式）
- converters:   ``Converter`` 接口 + 内置 int/float/bool/str/date/Decimal 转换器（按类型自动选择）
- reader:       ``ExcelReader`` 读取引擎（表头映射/类型转换/多 sheet/head_row_number）
- writer:       ``ExcelWriter`` 写入引擎（表头/顺序/样式/大数字防丢精度/多 sheet）
- easy_excel:   ``EasyExcel`` 流式构建入口（对齐 alibaba EasyExcel API）
- style:        默认表头/内容样式
- exceptions:   ``ExcelError`` 异常族

安装（可选依赖）::

    pip install springbootAI[excel]      # 同时安装 openpyxl
    pip install springbootAI[ai]         # AI 模块
    pip install springbootAI[full]       # 全部可选依赖

注解声明无需 openpyxl；仅 read/write 时检测，未安装抛 ``ExcelDependencyError`` 提示安装。
"""
from .exceptions import (
    ExcelError, ExcelPropertyError, ExcelReadError, ExcelWriteError, ExcelDependencyError,
)
from .annotations import (
    ExcelProperty, ExcelIgnore, ExcelSheet, excel_sheet,
    ExcelColumnModel, parse_excel_columns,
)
from .converters import (
    Converter, StringConverter, IntegerConverter, FloatConverter,
    BooleanConverter, DateStringConverter, BigDecimalConverter, resolve_converter,
)
from .reader import ExcelReader
from .writer import ExcelWriter
from .easy_excel import EasyExcel, read_excel, write_excel

__version__ = "2.2.0"

__all__ = [
    # 异常
    "ExcelError", "ExcelPropertyError", "ExcelReadError", "ExcelWriteError",
    "ExcelDependencyError",
    # 注解
    "ExcelProperty", "ExcelIgnore", "ExcelSheet", "excel_sheet",
    "ExcelColumnModel", "parse_excel_columns",
    # 转换器
    "Converter", "StringConverter", "IntegerConverter", "FloatConverter",
    "BooleanConverter", "DateStringConverter", "BigDecimalConverter", "resolve_converter",
    # 引擎
    "ExcelReader", "ExcelWriter", "EasyExcel", "read_excel", "write_excel",
    "__version__",
]
