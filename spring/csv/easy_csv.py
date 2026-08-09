"""SpringPy ``EasyCsv`` —— 流式构建入口（对齐 ``EasyExcel`` API）。

用法::

    # 读
    rows = (EasyCsv.read("/tmp/users.csv", head=DemoData)
            .has_header(True)
            .delimiter(",")
            .doRead())

    # 写
    EasyCsv.write("/tmp/users.csv", head=DemoData).has_header(True).doWrite(data_list)

    # 一步到位
    rows = read_csv("/tmp/users.csv", DemoData)
    write_csv("/tmp/users.csv", DemoData, rows)

CSV 使用 Python 标准库 ``csv``，**无可选依赖**，注解声明与读写均开箱即用。
"""
from __future__ import annotations

from typing import Any, Optional, Type

from .reader import CsvReader
from .writer import CsvWriter


class EasyCsv:
    """EasyCsv 流式入口（静态工厂方法风格，对齐 ``EasyExcel``）。"""

    @staticmethod
    def read(
        source: Any,
        head: Optional[Type] = None,
        has_header: Optional[bool] = None,
        delimiter: Optional[str] = None,
        encoding: Optional[str] = None,
    ) -> CsvReader:
        """构建读取器。

        Args:
            source:     文件路径或类文件对象。
            head:       实体类（带 ``@CsvProperty`` 注解）。
            has_header: 是否含表头。默认取类 ``@csv_file`` 配置或 True。
            delimiter:  字段分隔符。默认取类配置或 ``,``。
            encoding:   文件编码。默认取类配置或 ``utf-8-sig``。
        """
        return CsvReader(
            source=source, head=head, has_header=has_header,
            delimiter=delimiter, encoding=encoding,
        )

    @staticmethod
    def write(
        target: Any,
        head: Optional[Type] = None,
        delimiter: Optional[str] = None,
        encoding: Optional[str] = None,
    ) -> CsvWriter:
        """构建写入器。

        Args:
            target:    文件路径或类文件对象。
            head:      实体类（带 ``@CsvProperty`` 注解）。
            delimiter: 字段分隔符。默认取类配置或 ``,``。
            encoding:  文件编码。默认取类配置或 ``utf-8-sig``。
        """
        return CsvWriter(target=target, head=head, delimiter=delimiter, encoding=encoding)


# 便捷函数（非流式，一步到位）
def read_csv(
    source: Any,
    head: Type,
    has_header: Optional[bool] = None,
    delimiter: Optional[str] = None,
    encoding: Optional[str] = None,
) -> list:
    """一步读取：``read_csv(path, DemoData)``。"""
    return EasyCsv.read(source, head=head, has_header=has_header,
                        delimiter=delimiter, encoding=encoding).doRead()


def write_csv(
    target: Any,
    head: Type,
    data: list,
    delimiter: Optional[str] = None,
    encoding: Optional[str] = None,
) -> Any:
    """一步写入：``write_csv(path, DemoData, rows)``。"""
    return EasyCsv.write(target, head=head, delimiter=delimiter, encoding=encoding).doWrite(data)


__all__ = ["EasyCsv", "read_csv", "write_csv"]
