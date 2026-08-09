"""SpringPy ``EasyExcel`` —— 流式构建入口（对齐 alibaba EasyExcel API）。

用法::

    # 读
    rows = (EasyExcel.read("/tmp/users.xlsx", head=DemoData)
            .head_row_number(1)
            .sheet(sheet_no=0)
            .doRead())

    # 写
    EasyExcel.write("/tmp/users.xlsx", head=DemoData).sheet("用户列表").doWrite(data_list)

    # 多 sheet
    EasyExcel.write("/tmp/multi.xlsx", head=DemoData).doWriteAll({"S1": list1, "S2": list2})

    # 读所有 sheet
    sheets = EasyExcel.read("/tmp/multi.xlsx", head=DemoData).doReadAll()

注解声明不依赖 openpyxl；仅在 ``doRead`` / ``doWrite`` 时检测并提示安装 ``springpy[excel]``。
"""
from __future__ import annotations

from typing import Any, Optional, Type, Union

from .reader import ExcelReader
from .writer import ExcelWriter


class EasyExcel:
    """EasyExcel 流式入口（静态工厂方法风格，对齐 alibaba EasyExcel）。"""

    @staticmethod
    def read(
        source: Any,
        head: Optional[Type] = None,
        head_row_number: Optional[int] = None,
        sheet_no: Optional[int] = None,
        sheet_name: Optional[str] = None,
    ) -> ExcelReader:
        """构建读取器。

        Args:
            source:          文件路径或类文件对象。
            head:            实体类（带 ``@ExcelProperty`` 注解）。
            head_row_number: 表头所在行号（从 1 起）。默认取类 ``@excel_sheet`` 配置或 1。
            sheet_no:        工作表索引（0 起）。
            sheet_name:      工作表名称（优先于 sheet_no）。
        """
        return ExcelReader(
            source=source, head=head, head_row_number=head_row_number,
            sheet_no=sheet_no, sheet_name=sheet_name,
        )

    @staticmethod
    def write(
        target: Any,
        head: Optional[Type] = None,
        sheet_name: Optional[str] = None,
    ) -> ExcelWriter:
        """构建写入器。

        Args:
            target:     文件路径或类文件对象。
            head:       实体类（带 ``@ExcelProperty`` 注解）。
            sheet_name: 工作表名称。默认取类 ``@excel_sheet`` 配置或 "Sheet1"。
        """
        return ExcelWriter(target=target, head=head, sheet_name=sheet_name)


# 便捷函数（非流式，一步到位）
def read_excel(
    source: Any,
    head: Type,
    sheet_no: Optional[int] = None,
    sheet_name: Optional[str] = None,
    head_row_number: Optional[int] = None,
) -> list:
    """一步读取：``read_excel(path, DemoData)``。"""
    return EasyExcel.read(source, head=head, head_row_number=head_row_number,
                          sheet_no=sheet_no, sheet_name=sheet_name).doRead()


def write_excel(
    target: Any,
    head: Type,
    data: list,
    sheet_name: Optional[str] = None,
) -> Any:
    """一步写入：``write_excel(path, DemoData, rows)``。"""
    return EasyExcel.write(target, head=head, sheet_name=sheet_name).doWrite(data)


__all__ = ["EasyExcel", "read_excel", "write_excel"]
