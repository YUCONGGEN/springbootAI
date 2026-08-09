"""``Locale`` 区域对象（对齐 ``java.util.Locale``）。

表示一个特定的地理、政治或文化区域。本实现采用最常见的 ``language_country`` 字符串
表示（如 ``en``/``en_US``/``zh_CN``），同时支持 BCP 47 语言标签（``en-US``/``zh-CN``）。

与 Java 的差异：
- Java ``Locale`` 是不可变重量级对象（含 ``Locale.Builder``）；本实现是轻量不可变 dataclass 风格。
- 不支持 ``Locale.LanguageRange`` 列表解析的完整 RFC 4647 算法，仅实现最常见的
  前缀匹配（``AcceptHeaderLocaleResolver`` 用）。
- ``getDisplayLanguage`` 等显示名 API 不实现（依赖 ``Locale`` 数据集），使用方可按需扩展。
"""
from __future__ import annotations

from typing import Optional


class Locale:
    """不可变区域对象。

    Args:
        language: ISO 639 语言代码（小写，如 ``en``/``zh``）。
        country:  ISO 3166 国家代码（大写，如 ``US``/``CN``）。可选。
        variant:  变体（任意大小写，如 ``POSIX``/``Traditional_WIN``）。可选。

    规范化：
    - ``language`` 转小写；``country`` 转大写；``variant`` 保留原样。
    - 空/None 视为未设置。
    """

    __slots__ = ("language", "country", "variant")

    def __init__(self, language: str = "", country: str = "", variant: str = ""):
        self.language = (language or "").lower()
        self.country = (country or "").upper()
        self.variant = variant or ""

    # ==================== 工厂 ====================

    @classmethod
    def parse(cls, tag: str) -> "Locale":
        """从字符串解析 ``Locale``，兼容以下格式：

        - ``en`` / ``zh``                         → ``Locale("en")``
        - ``en_US`` / ``zh_CN``                   → ``Locale("en", "US")``
        - ``en_US_POSIX``                         → ``Locale("en", "US", "POSIX")``
        - ``en-US`` / ``zh-CN``（BCP 47，``-`` 分隔）→ 同上
        - ``en-US-x-posix``（BCP 47 私有用）        → variant 取最后一段
        """
        if not tag:
            return cls()
        tag = tag.strip()
        # 统一分隔符：BCP 47 用 '-'，Java 用 '_'；优先拆 '_' 再拆 '-'
        # 仅当不含 '_' 时才替换 '-'，避免误处理含 '_' 的 variant
        if "_" in tag:
            parts = tag.split("_")
        elif "-" in tag:
            parts = tag.split("-")
        else:
            parts = [tag]
        language = parts[0] if len(parts) >= 1 else ""
        country = parts[1] if len(parts) >= 2 else ""
        # variant：第 3 段及以上拼接（Java 风格单段 variant 取最后一段即可）
        variant = parts[2] if len(parts) >= 3 else ""
        # 处理 BCP 47 扩展：x-private 子段拼到 variant
        if len(parts) > 3:
            variant = "_".join(parts[2:])
        return cls(language, country, variant)

    # ==================== 表示 ====================

    def to_string(self) -> str:
        """Java ``toString`` 风格：``en``/``en_US``/``en_US_POSIX``。"""
        if self.variant:
            return f"{self.language}_{self.country}_{self.variant}" if self.country else \
                   f"{self.language}__{self.variant}"
        if self.country:
            return f"{self.language}_{self.country}"
        return self.language

    def to_language_tag(self) -> str:
        """BCP 47 语言标签：``en``/``en-US``/``zh-CN``。"""
        if self.variant:
            return f"{self.language}-{self.country}-{self.variant}" if self.country else \
                   f"{self.language}-x-{self.variant}"
        if self.country:
            return f"{self.language}-{self.country}"
        return self.language

    def __str__(self) -> str:
        return self.to_string()

    def __repr__(self) -> str:
        return f"Locale({self.to_string()!r})"

    # ==================== 比较 / 哈希 ====================

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Locale):
            return NotImplemented
        return (self.language, self.country, self.variant) == \
               (other.language, other.country, other.variant)

    def __hash__(self) -> int:
        return hash((self.language, self.country, self.variant))

    # ==================== 工具 ====================

    @property
    def is_empty(self) -> bool:
        return not (self.language or self.country or self.variant)

    def matches(self, other: "Locale") -> bool:
        """前缀匹配：``Locale("en")`` matches ``Locale("en_US")``，反之不成立。

        用于 ``AcceptHeaderLocaleResolver`` 的回退匹配。
        """
        if self.is_empty or other.is_empty:
            return False
        if self.language != other.language:
            return False
        if self.country and other.country and self.country != other.country:
            return False
        if self.country and not other.country:
            return False  # self 更具体，不能 matches 更宽泛的 other
        return True


# ==================== 预定义常量（对齐 Java ``Locale.*``） ====================

LOCALE_EN = Locale("en")
LOCALE_US = Locale("en", "US")
LOCALE_UK = Locale("en", "GB")
LOCALE_CHINA = Locale("zh", "CN")
LOCALE_TAIWAN = Locale("zh", "TW")
LOCALE_JAPAN = Locale("ja", "JP")
LOCALE_KOREA = Locale("ko", "KR")
LOCALE_GERMANY = Locale("de", "DE")
LOCALE_FRANCE = Locale("fr", "FR")


def parse_locale(tag: str) -> Locale:
    """``Locale.parse`` 的函数式别名。"""
    return Locale.parse(tag)


__all__ = [
    "Locale",
    "LOCALE_EN", "LOCALE_US", "LOCALE_UK",
    "LOCALE_CHINA", "LOCALE_TAIWAN", "LOCALE_JAPAN", "LOCALE_KOREA",
    "LOCALE_GERMANY", "LOCALE_FRANCE",
    "parse_locale",
]
