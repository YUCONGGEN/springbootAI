"""SpringBootAI CSV 读取引擎。

按 ``@CsvProperty`` / ``@CsvIgnore`` / ``@csv_file`` 注解把 CSV 文件读为实体对象列表。
底层使用 Python 标准库 ``csv``（**无可选依赖**，开箱即用）。

读取流程对齐 Excel 模块（``spring.excel.reader``）与 alibaba EasyExcel：
    1. 读取表头行（``has_header``，默认 True）。
    2. 表头文案 -> ``CsvColumnModel`` 映射（按 ``value`` 匹配；无注解时按列位置匹配）。
    3. 数据行逐行按 ``converter.from_excel`` 转换，构造实体实例。
"""
from __future__ import annotations

import csv as _csv
import inspect
from typing import Any, List, Optional, Type

from .annotations import (
    CsvColumnModel, CsvFile, _get_class_file_meta, has_explicit_properties,
    parse_csv_columns,
)
from .converters import resolve_csv_converter
from .exceptions import CsvReadError


def _build_instance(cls: Type, kwargs: dict) -> Any:
    """构造实体实例：优先 ``cls(**kwargs)``，失败则逐字段 setattr（兼容纯 ``__init__`` 模型）。

    镜像 Excel ``_build_instance``。
    """
    try:
        sig = inspect.signature(cls.__init__)
        params = list(sig.parameters.values())[1:]  # 跳过 self
        accept_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)
        if accept_kwargs:
            return cls(**kwargs)
        allowed = {p.name for p in params if p.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY,
        )}
        filtered = {k: v for k, v in kwargs.items() if k in allowed}
        return cls(**filtered)
    except TypeError:
        pass
    # 回退：无参构造 + setattr
    try:
        obj = cls()
    except Exception:
        obj = object.__new__(cls)
    for k, v in kwargs.items():
        try:
            setattr(obj, k, v)
        except Exception:
            pass
    return obj


def _open_for_read(source: Any, encoding: str):
    """支持文件路径（str/Path）或类文件对象。"""
    try:
        if isinstance(source, (str, bytes)) or hasattr(source, "__fspath__"):
            return open(source, "r", encoding=encoding, newline="")
        # 类文件对象，直接使用
        return source
    except Exception as e:
        raise CsvReadError(f"打开 CSV 文件失败: {e}") from e


class CsvReader:
    """CSV 读取器。由 ``EasyCsv.read(...)`` 构建，调用 ``doRead`` 执行。"""

    def __init__(
        self,
        source: Any,
        head: Optional[Type] = None,
        has_header: Optional[bool] = None,
        delimiter: Optional[str] = None,
        encoding: Optional[str] = None,
    ):
        self.source = source
        self.head = head
        self._has_header = has_header
        self._delimiter = delimiter
        self._encoding = encoding

    # ---- 流式配置 ----

    def has_header(self, flag: bool) -> "CsvReader":
        self._has_header = flag
        return self

    def delimiter(self, d: str) -> "CsvReader":
        self._delimiter = d
        return self

    def encoding(self, enc: str) -> "CsvReader":
        self._encoding = enc
        return self

    # ---- 执行 ----

    def _resolve_meta(self) -> CsvFile:
        meta = _get_class_file_meta(self.head) if self.head is not None else CsvFile()
        if self._has_header is not None:
            meta.has_header = self._has_header
        if self._delimiter is not None:
            meta.delimiter = self._delimiter
        if self._encoding is not None:
            meta.encoding = self._encoding
        return meta

    def doRead(self) -> List[Any]:
        """读取 CSV，返回实体列表。"""
        if self.head is None:
            raise CsvReadError("read 需指定 head 实体类")
        meta = self._resolve_meta()
        columns: List[CsvColumnModel] = parse_csv_columns(self.head)
        explicit = has_explicit_properties(self.head)

        f = _open_for_read(self.source, meta.encoding)
        owns_fh = f is not self.source
        try:
            reader = _csv.reader(f, delimiter=meta.delimiter, quotechar=meta.quote_char)
            rows = list(reader)
        finally:
            if owns_fh:
                try:
                    f.close()
                except Exception:
                    pass

        if not rows:
            return []

        # 表头
        start_idx = 0
        header_cells: List[str] = []
        if meta.has_header:
            header_cells = [str(c).strip() if c is not None else "" for c in rows[0]]
            start_idx = 1

        # 列映射：列序号(0-based) -> CsvColumnModel
        col_mapping = self._map_columns(columns, header_cells, explicit, meta.has_header)

        results: List[Any] = []
        for row in rows[start_idx:]:
            if not row or all((v is None or str(v).strip() == "") for v in row):
                continue  # 跳过全空行
            kwargs = {}
            for col_idx, model in col_mapping.items():
                cell_value = row[col_idx] if col_idx < len(row) else None
                value = self._convert_from_cell(model, cell_value)
                kwargs[model.attr_name] = value
            results.append(_build_instance(self.head, kwargs))
        return results

    def _map_columns(
        self,
        columns: List[CsvColumnModel],
        header_cells: List[str],
        explicit: bool,
        has_header: bool,
    ) -> dict:
        """表头 -> 列模型映射。返回 {列序号(0-based): CsvColumnModel}。"""
        col_mapping: dict = {}
        if explicit and has_header and any(c.header for c in columns):
            # 按表头文案匹配
            header_to_col = {}
            for idx, h in enumerate(header_cells):
                if h == "":
                    continue
                header_to_col.setdefault(h, idx)
            for model in columns:
                col_idx = header_to_col.get(model.header)
                if col_idx is None:
                    continue
                col_mapping[col_idx] = model
        else:
            # 按列位置匹配（无注解或无表头）
            for offset, model in enumerate(columns):
                col_idx = (model.index if model.index is not None else offset)
                col_mapping[col_idx] = model
        return col_mapping

    def _convert_from_cell(self, model: CsvColumnModel, cell_value: Any) -> Any:
        converter = resolve_csv_converter(model.py_type, model.converter, model.date_format)
        if converter is None:
            return cell_value
        try:
            return converter.from_excel(cell_value)
        except Exception as e:
            raise CsvReadError(
                f"字段 '{model.attr_name}' 转换失败 (单元格值={cell_value!r}): {e}"
            ) from e


__all__ = ["CsvReader"]
