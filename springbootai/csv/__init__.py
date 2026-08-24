"""SpringBootAI CSV 模块 —— 注解驱动的 CSV 读写（对齐 alibaba EasyExcel / commons-csv）。

模块组成（镜像 ``springbootai.excel`` 架构）：
- annotations:  ``@CsvProperty`` / ``@CsvIgnore`` / ``@csv_file`` 字段+类级注解
                 （复用 ORM ``Column``/``@entity`` 与 Excel ``ExcelProperty`` 元数据描述符范式）
- converters:   复用 ``springbootai.excel.converters`` 的 ``Converter`` 接口与内置转换器（DRY）
- reader:       ``CsvReader`` 读取引擎（表头映射/类型转换/位置回退）
- writer:       ``CsvWriter`` 写入引擎（表头/顺序/大数字防丢精度）
- easy_csv:     ``EasyCsv`` 流式构建入口（对齐 ``EasyExcel`` API）
- exceptions:   ``CsvError`` 异常族

与 Excel 模块的核心区别：
- **无可选依赖**：CSV 使用 Python 标准库 ``csv``，``pip install springbootAI`` 即可用，
  无需 ``springbootAI[excel]`` 等额外 extras。
- 转换器复用 Excel 模块（``springbootai.excel.converters`` 不依赖 openpyxl，可安全导入）。
- 无单元格样式/数字格式（CSV 格式本身不支持）。

设计原则：**复用项目既有范式，不重复造轮子**。注解描述符、反射解析、流式 API 全部对齐
既有 Excel/ORM 实现，未引入任何第三方库。
"""
from .exceptions import CsvError, CsvPropertyError, CsvReadError, CsvWriteError
from .annotations import (
    CsvProperty, CsvIgnore, CsvFile, csv_file,
    CsvColumnModel, parse_csv_columns,
)
from .converters import (
    Converter, CsvConverter,
    StringConverter, IntegerConverter, FloatConverter,
    BooleanConverter, DateStringConverter, BigDecimalConverter,
    resolve_converter, resolve_csv_converter,
)
from .reader import CsvReader
from .writer import CsvWriter
from .easy_csv import EasyCsv, read_csv, write_csv

__version__ = "2.3.8"

__all__ = [
    # 异常
    "CsvError", "CsvPropertyError", "CsvReadError", "CsvWriteError",
    # 注解
    "CsvProperty", "CsvIgnore", "CsvFile", "csv_file",
    "CsvColumnModel", "parse_csv_columns",
    # 转换器
    "Converter", "CsvConverter",
    "StringConverter", "IntegerConverter", "FloatConverter",
    "BooleanConverter", "DateStringConverter", "BigDecimalConverter",
    "resolve_converter", "resolve_csv_converter",
    # 引擎
    "CsvReader", "CsvWriter", "EasyCsv", "read_csv", "write_csv",
    "__version__",
]
