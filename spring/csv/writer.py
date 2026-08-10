"""SpringBootAI CSV 写入引擎。

按 ``@CsvProperty`` / ``@CsvIgnore`` / ``@csv_file`` 注解把实体对象列表写入 CSV。
底层使用 Python 标准库 ``csv``（**无可选依赖**，开箱即用）。

写入流程对齐 Excel 模块（``spring.excel.writer``）与 alibaba EasyExcel：
    1. 按列模型排序写表头行（``has_header=True`` 时）。
    2. 逐行按 ``converter.to_excel`` 转换并写单元格；处理大数字防丢精度。
"""
from __future__ import annotations

import csv as _csv
from typing import Any, Iterable, List, Optional, Type

from .annotations import (
    CsvColumnModel, CsvFile, _get_class_file_meta, parse_csv_columns,
)
from .converters import resolve_csv_converter
from .exceptions import CsvWriteError


def _get_value(item: Any, attr_name: str) -> Any:
    """从实体对象或 dict 取字段值。镜像 Excel ``_get_value``。"""
    if isinstance(item, dict):
        return item.get(attr_name)
    return getattr(item, attr_name, None)


def _is_large_int(value: Any) -> bool:
    """是否为会丢精度的长整数（>15 位有效数字）。镜像 Excel ``_is_large_int``。"""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return len(str(abs(value))) > 15
    return False


def _open_for_write(target: Any, encoding: str):
    """支持文件路径（str/Path）或类文件对象。"""
    try:
        if isinstance(target, (str, bytes)) or hasattr(target, "__fspath__"):
            return open(target, "w", encoding=encoding, newline="")
        return target
    except Exception as e:
        raise CsvWriteError(f"打开 CSV 文件失败: {e}") from e


class CsvWriter:
    """CSV 写入器。由 ``EasyCsv.write(...)`` 构建，调用 ``doWrite`` 执行。"""

    def __init__(
        self,
        target: Any,
        head: Optional[Type] = None,
        delimiter: Optional[str] = None,
        encoding: Optional[str] = None,
    ):
        self.target = target
        self.head = head
        self._delimiter = delimiter
        self._encoding = encoding
        self._has_header: Optional[bool] = None

    # ---- 流式配置 ----

    def delimiter(self, d: str) -> "CsvWriter":
        self._delimiter = d
        return self

    def encoding(self, enc: str) -> "CsvWriter":
        self._encoding = enc
        return self

    def has_header(self, flag: bool) -> "CsvWriter":
        self._has_header = flag
        return self

    # ---- 执行 ----

    def _resolve_meta(self) -> CsvFile:
        meta = _get_class_file_meta(self.head) if self.head is not None else CsvFile()
        if self._delimiter is not None:
            meta.delimiter = self._delimiter
        if self._encoding is not None:
            meta.encoding = self._encoding
        if self._has_header is not None:
            meta.has_header = self._has_header
        return meta

    def doWrite(self, data: Iterable[Any]) -> Any:
        """写入 CSV 并保存到 ``target``。返回目标路径。"""
        if self.head is None:
            raise CsvWriteError("write 需指定 head 实体类")
        meta = self._resolve_meta()
        columns: List[CsvColumnModel] = parse_csv_columns(self.head)

        f = _open_for_write(self.target, meta.encoding)
        owns_fh = f is not self.target
        try:
            writer = _csv.writer(
                f,
                delimiter=meta.delimiter,
                quotechar=meta.quote_char,
                lineterminator=meta.line_terminator,
            )
            # 1. 表头
            if meta.has_header:
                writer.writerow([m.header for m in columns])
            # 2. 数据行
            for item in data:
                row = []
                for model in columns:
                    raw = _get_value(item, model.attr_name)
                    cell_value = self._convert_to_cell(model, raw)
                    row.append(cell_value)
                writer.writerow(row)
        except Exception as e:
            raise CsvWriteError(f"写入 CSV 文件失败: {e}") from e
        finally:
            if owns_fh:
                try:
                    f.close()
                except Exception:
                    pass
        return self.target

    def _convert_to_cell(self, model: CsvColumnModel, raw: Any) -> str:
        """Python 值 -> CSV 单元格字符串。"""
        converter = resolve_csv_converter(model.py_type, model.converter, model.date_format)
        if converter is not None:
            try:
                converted = converter.to_excel(raw)
            except Exception as e:
                raise CsvWriteError(
                    f"字段 '{model.attr_name}' 转换失败 (值={raw!r}): {e}"
                ) from e
            return self._to_cell_str(converted)
        # 无转换器：按规则处理
        if raw is None:
            return ""
        if model.big_number or _is_large_int(raw):
            return str(raw)
        return self._to_cell_str(raw)

    @staticmethod
    def _to_cell_str(value: Any) -> str:
        """统一转字符串：None -> ""，bool -> "True"/"False"，其余 str(value)。"""
        if value is None:
            return ""
        if isinstance(value, bool):
            return "True" if value else "False"
        return str(value)


__all__ = ["CsvWriter"]
