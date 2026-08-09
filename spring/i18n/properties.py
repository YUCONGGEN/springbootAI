"""Java 风格 ``.properties`` 文件解析器。

对齐 ``java.util.Properties.load`` 的常见行为：
- ``key=value`` / ``key:value`` / ``key value`` 三种分隔符。
- ``#`` / ``!`` 开头为注释行。
- 反斜杠续行：行尾 ``\\`` 与下一行拼接（去除前导空白）。
- 转义序列：``\\n`` ``\\t`` ``\\r`` ``\\f`` ``\\\\`` ``\\:`` ``\\=`` ``\\uXXXX``。
- 默认 UTF-8 编码（Java 9+ ``Properties`` 默认 ISO-8859-1，但 Spring
  ``ResourceBundleMessageSource.setDefaultEncoding("UTF-8")`` 是事实标准）。

不实现：
- ``Properties.store`` 写出（本框架仅读取国际化资源）。
- XML 属性文件（``Properties.loadFromXML``）。
"""
from __future__ import annotations

import io
import re
from typing import Dict, Mapping, TextIO, Union


# ==================== 转义序列处理 ====================

_ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "f": "\f",
    "\\": "\\", ":": ":", "=": "=", "#": "#", "!": "!", "\"": "\"", "'": "'",
    "0": "\0",
    # 单引号在 Java Properties 中并非转义，但 MessageFormat 中是；此处保守保留原样
}

_UNICODE_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")


def _unescape(text: str) -> str:
    """反转义 ``\\n``/``\\t``/``\\uXXXX`` 等序列。"""
    # 先处理 \uXXXX（4 位十六进制 Unicode）
    text = _UNICODE_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), text)
    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            nxt = text[i + 1]
            out.append(_ESCAPES.get(nxt, "\\" + nxt))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _split_kv(line: str) -> "tuple[str, str]":
    """按首个未转义的 ``=``/``:`` 或连续空白拆分 key/value。

    对齐 Java ``Properties`` 的宽松分隔规则。
    """
    i = 0
    n = len(line)
    # 跳过前导空白
    while i < n and line[i] in " \t\f":
        i += 1
    key_chars = []
    # key 中允许转义分隔符（\= \:）
    while i < n:
        ch = line[i]
        if ch == "\\" and i + 1 < n:
            key_chars.append(ch)
            key_chars.append(line[i + 1])
            i += 2
            continue
        if ch in "=: \t\f":
            break
        key_chars.append(ch)
        i += 1
    # 跳过 key 后的分隔符（一个 = 或 : 或空白序列）
    sep_seen = False
    while i < n and line[i] in "=: \t\f":
        if line[i] in "=:":
            if sep_seen:
                break
            sep_seen = True
            i += 1
            # 分隔符后的空白也吞掉
            while i < n and line[i] in " \t\f":
                i += 1
            break
        else:
            i += 1
    value = line[i:]
    return _unescape("".join(key_chars)).strip(), _unescape(value)


def _read_logical_lines(stream: TextIO) -> "list[str]":
    """读取逻辑行：合并续行（行尾 ``\\``），跳过注释与空行。

    返回每条逻辑行的原始字符串（已合并续行、未拆 key/value）。
    """
    logical: list = []
    buf = ""
    in_continuation = False
    for raw in stream:
        # 统一换行
        line = raw.rstrip("\r\n")
        # 注释/空行仅在非续行状态下生效
        if not in_continuation:
            stripped = line.lstrip(" \t\f")
            if not stripped or stripped[0] in "#!":
                continue
            buf = line
        else:
            # 续行：拼接，去除前导空白
            buf += line.lstrip(" \t\f")
        # 续行判定：行尾奇数个反斜杠表示续行
        backslashes = 0
        idx = len(buf) - 1
        while idx >= 0 and buf[idx] == "\\":
            backslashes += 1
            idx -= 1
        if backslashes % 2 == 1:
            # 去掉最后一个反斜杠，进入续行
            buf = buf[:-1]
            in_continuation = True
            continue
        logical.append(buf)
        buf = ""
        in_continuation = False
    # 文件末尾仍在续行（异常文件）—— 兜底加入
    if buf:
        logical.append(buf)
    return logical


def parse_properties(content: str) -> Dict[str, str]:
    """解析 properties 文本内容，返回 ``{key: value}`` 字典。"""
    result: Dict[str, str] = {}
    with io.StringIO(content) as s:
        for line in _read_logical_lines(s):
            key, value = _split_kv(line)
            if key:
                result[key] = value
    return result


def load_properties(path: str, encoding: str = "utf-8") -> Dict[str, str]:
    """从文件路径加载 properties，返回 ``{key: value}`` 字典。

    Args:
        path:     文件路径。
        encoding: 文件编码，默认 UTF-8（对齐 Spring ``defaultEncoding``）。
    """
    with open(path, "r", encoding=encoding, newline="") as f:
        return parse_properties(f.read())


def merge_properties(*mappings: Mapping[str, str]) -> Dict[str, str]:
    """合并多个 properties 映射，后者覆盖前者（用于多 basename 合并）。"""
    merged: Dict[str, str] = {}
    for m in mappings:
        merged.update(m)
    return merged


__all__ = [
    "parse_properties",
    "load_properties",
    "merge_properties",
]
