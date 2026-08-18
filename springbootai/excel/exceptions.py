"""SpringBootAI Excel 模块异常定义。

设计对齐 EasyExcel 的错误语义：注解配置错误、读写过程错误、可选依赖缺失均通过
本模块的异常抛出，便于上层统一捕获。
"""


class ExcelError(Exception):
    """Excel 模块所有异常的基类。"""


class ExcelPropertyError(ExcelError):
    """实体类字段上的 @ExcelProperty / @ExcelIgnore 配置不合法时抛出。"""


class ExcelReadError(ExcelError):
    """读取 Excel 过程中发生的错误（表头缺失、行数据无法转换等）。"""


class ExcelWriteError(ExcelError):
    """写入 Excel 过程中发生的错误。"""


class ExcelDependencyError(ExcelError):
    """缺少可选依赖 openpyxl 时抛出。

    Excel 读写引擎底层依赖 openpyxl。注解声明（@ExcelProperty 等）不依赖任何第三方库，
    仅在实际 read/write 时检测。未安装时给出明确的安装提示::

        pip install springbootAI[excel]
    """
