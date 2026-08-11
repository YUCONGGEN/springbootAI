"""
输出解析器工厂 - 封装 langchain classic 的 OutputParser，作为 @Component Bean。

封装的解析器：
- comma-list: CommaSeparatedListOutputParser（逗号分隔列表）
- datetime: DatetimeOutputParser（日期时间）
- pydantic: PydanticOutputParser（按 pydantic 模型结构化输出）
- json: SimpleJsonOutputParser（JSON）
- enum: EnumOutputParser（枚举）
"""
import logging
from typing import Any, Type


logger = logging.getLogger("Spring.LangChain")


class OutputParserFactory:
    """输出解析器工厂 Bean - 统一创建各类 OutputParser。"""

    @staticmethod
    def create_comma_list_parser() -> Any:
        """逗号分隔列表解析器。"""
        from langchain_core.output_parsers import CommaSeparatedListOutputParser
        return CommaSeparatedListOutputParser()

    @staticmethod
    def create_datetime_parser() -> Any:
        """日期时间解析器（langchain 1.x 已从 core 移除，按需从 classic 导入）。"""
        try:
            from langchain_core.output_parsers import DatetimeOutputParser
        except ImportError:
            from langchain_classic.output_parsers import DatetimeOutputParser
        return DatetimeOutputParser()

    @staticmethod
    def create_json_parser() -> Any:
        """简单 JSON 解析器。"""
        from langchain_core.output_parsers import SimpleJsonOutputParser
        return SimpleJsonOutputParser()

    @staticmethod
    def create_pydantic_parser(pydantic_model: Type) -> Any:
        """
        Pydantic 结构化输出解析器。

        Args:
            pydantic_model: pydantic.BaseModel 子类
        """
        from langchain_core.output_parsers import PydanticOutputParser
        return PydanticOutputParser(pydantic_object=pydantic_model)

    @staticmethod
    def create_enum_parser(enum_class: Type) -> Any:
        """枚举解析器。

        langchain 1.x 已把 EnumOutputParser 从 core 迁到 langchain_classic，
        这里做兼容导入。
        """
        try:
            from langchain_core.output_parsers import EnumOutputParser
        except ImportError:
            from langchain_classic.output_parsers import EnumOutputParser
        return EnumOutputParser(enum=enum_class)

    @staticmethod
    def create(parser_type: str, **kwargs) -> Any:
        """
        统一入口。

        Args:
            parser_type: comma-list | datetime | json | pydantic | enum
        """
        if parser_type == "comma-list":
            return OutputParserFactory.create_comma_list_parser()
        if parser_type == "datetime":
            return OutputParserFactory.create_datetime_parser()
        if parser_type == "json":
            return OutputParserFactory.create_json_parser()
        if parser_type == "pydantic":
            return OutputParserFactory.create_pydantic_parser(kwargs["pydantic_model"])
        if parser_type == "enum":
            return OutputParserFactory.create_enum_parser(kwargs["enum_class"])
        raise ValueError(f"未知 parser_type: {parser_type}")
