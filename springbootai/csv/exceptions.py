"""SpringBootAI CSV 模块异常定义。

设计对齐 Excel 模块（``springbootai.excel.exceptions``）的错误语义：注解配置错误、读写过程错误
均通过本模块的异常抛出，便于上层统一捕获。

与 Excel 模块的区别：CSV 使用 Python 标准库 ``csv``，**无可选依赖**，因此没有
``CsvDependencyError``（对应 Excel 的 ``ExcelDependencyError``）。
"""


class CsvError(Exception):
    """CSV 模块所有异常的基类。"""


class CsvPropertyError(CsvError):
    """实体类字段上的 @CsvProperty / @CsvIgnore 配置不合法时抛出。"""


class CsvReadError(CsvError):
    """读取 CSV 过程中发生的错误（表头缺失、行数据无法转换等）。"""


class CsvWriteError(CsvError):
    """写入 CSV 过程中发生的错误。"""


__all__ = ["CsvError", "CsvPropertyError", "CsvReadError", "CsvWriteError"]
