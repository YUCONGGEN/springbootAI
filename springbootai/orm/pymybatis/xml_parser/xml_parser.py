"""
PyMyBatis XML映射文件解析器

解析MyBatis风格的XML映射文件，支持：
- select/insert/update/delete标签
- resultMap标签
- sql片段
- 动态SQL标签
"""

import os
import re
from dataclasses import dataclass, field
from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException
from xml.etree import ElementTree as ET
from typing import Dict, List, Optional


@dataclass
class NestedResultMapping:
    """Metadata for MyBatis ``association``/``collection`` mappings."""

    property: str
    result_map: Optional[str] = None
    result_type: Optional[str] = None
    select: Optional[str] = None
    column: Optional[str] = None
    java_type: Optional[str] = None
    of_type: Optional[str] = None
    mapping: Optional['ResultMap'] = None


@dataclass
class DiscriminatorMapping:
    column: str
    cases: Dict[str, str] = field(default_factory=dict)


class MappedStatement:
    """
    映射语句

    封装XML中定义的SQL语句及其配置
    """

    def __init__(self, id: str, sql_type: str, sql: str, result_map: Optional[str] = None,
                 parameter_type: Optional[str] = None, result_type: Optional[str] = None,
                 fetch_size: Optional[int] = None, timeout: Optional[int] = None,
                 use_cache: bool = True, flush_cache: bool = False,
                 use_generated_keys: bool = False,
                 key_property: Optional[str] = None,
                 key_column: Optional[str] = None,
                 database_id: Optional[str] = None,
                 select_key_sql: Optional[str] = None,
                 select_key_order: str = 'AFTER',
                 select_key_result_type: Optional[str] = None,
                 select_key_key_property: Optional[str] = None,
                 select_key_key_column: Optional[str] = None):
        """
        初始化映射语句

        Args:
            id: 语句ID
            sql_type: SQL类型（SELECT/INSERT/UPDATE/DELETE）
            sql: SQL语句
            result_map: 结果映射ID
            parameter_type: 参数类型
            result_type: 结果类型
            fetch_size: 抓取大小
            timeout: 超时时间
        """
        self.id = id
        self.sql_type = sql_type.upper()
        self.sql = sql
        self.result_map = result_map
        self.parameter_type = parameter_type
        self.result_type = result_type
        self.fetch_size = fetch_size
        self.timeout = timeout
        self.use_cache = use_cache
        self.flush_cache = flush_cache
        self.use_generated_keys = use_generated_keys
        self.key_property = key_property
        self.key_column = key_column
        self.database_id = database_id
        self.select_key_sql = select_key_sql
        self.select_key_order = (select_key_order or 'AFTER').upper()
        self.select_key_result_type = select_key_result_type
        self.select_key_key_property = select_key_key_property
        self.select_key_key_column = select_key_key_column

    def __repr__(self) -> str:
        return f"<MappedStatement id={self.id}, type={self.sql_type}>"


class ResultMap:
    """
    结果映射

    定义数据库列到Java对象属性的映射关系
    """

    def __init__(self, id: str, type: str):
        """
        初始化结果映射

        Args:
            id: 结果映射ID
            type: 目标类型
        """
        self.id = id
        self.type = type
        self.mappings: Dict[str, str] = {}  # column -> property
        self.id_columns: List[str] = []
        self.associations: List[NestedResultMapping] = []
        self.collections: List[NestedResultMapping] = []
        self.discriminator: Optional[DiscriminatorMapping] = None
        self.extends: Optional[str] = None

    def add_mapping(self, column: str, property: str) -> None:
        """
        添加列映射

        Args:
            column: 数据库列名
            property: 对象属性名
        """
        self.mappings[column] = property

    def add_id_mapping(self, column: str, property: str) -> None:
        self.add_mapping(column, property)
        if column and column not in self.id_columns:
            self.id_columns.append(column)

    def get_property(self, column: str) -> Optional[str]:
        """
        获取列对应的属性名

        Args:
            column: 数据库列名

        Returns:
            对象属性名，未找到返回None
        """
        return self.mappings.get(column)

    def add_nested(self, nested: NestedResultMapping, collection: bool = False) -> None:
        (self.collections if collection else self.associations).append(nested)

    def __repr__(self) -> str:
        return f"<ResultMap id={self.id}, type={self.type}, mappings={self.mappings}>"


class SqlFragment:
    """
    SQL片段

    可复用的SQL片段
    """

    def __init__(self, id: str, sql: str):
        """
        初始化SQL片段

        Args:
            id: 片段ID
            sql: SQL内容
        """
        self.id = id
        self.sql = sql

    def __repr__(self) -> str:
        return f"<SqlFragment id={self.id}>"


class XmlParser:
    """
    XML映射文件解析器

    解析MyBatis风格的XML映射文件
    """

    def __init__(self):
        """初始化XML解析器"""
        self.mapped_statements: Dict[str, MappedStatement] = {}
        self._statement_variants: Dict[str, List[MappedStatement]] = {}
        self.result_maps: Dict[str, ResultMap] = {}
        self.sql_fragments: Dict[str, SqlFragment] = {}
        self.namespace: Optional[str] = None

    @staticmethod
    def _normalize_comparison_operators(xml_content: str) -> str:
        """Make raw SQL comparison operators safe for XML parsing.

        Mapper SQL often contains ``<=`` and ``>=``. The former is invalid
        XML unless escaped. Normalize both operators outside comments and
        CDATA blocks; ElementTree decodes the entities back to SQL text.
        """
        protected_pattern = re.compile(
            r'(<!\[CDATA\[.*?\]\]>|<!--.*?-->)',
            flags=re.DOTALL,
        )
        parts = protected_pattern.split(xml_content)
        for index in range(0, len(parts), 2):
            parts[index] = parts[index].replace('<=', '&lt;=')
            parts[index] = parts[index].replace('>=', '&gt;=')
        return ''.join(parts)

    def parse(self, file_path: str) -> Dict[str, MappedStatement]:
        """
        解析XML文件（兼容接口）

        Args:
            file_path: XML文件路径

        Returns:
            映射语句字典

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: XML格式错误
        """
        self.parse_file(file_path)
        return self.mapped_statements

    def parse_file(self, file_path: str) -> None:
        """
        解析XML文件

        Args:
            file_path: XML文件路径

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: XML格式错误
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"XML文件不存在: {file_path}")

        try:
            with open(file_path, 'r', encoding='utf-8-sig') as xml_file:
                xml_content = xml_file.read()
            root = self._secure_fromstring(xml_content)

            # 解析namespace
            self.namespace = root.get('namespace', '')

            # 解析各个标签
            for child in root:
                self._parse_element(child)

            self._resolve_result_map_extends()
            # 替换SQL片段引用
            self._replace_sql_fragments()

        except (ET.ParseError, DefusedXmlException) as e:
            raise ValueError(f"XML解析错误: {e}")

    def parse_string(self, xml_string: str) -> None:
        """
        解析XML字符串

        Args:
            xml_string: XML字符串
        """
        try:
            root = self._secure_fromstring(xml_string)
        except (ET.ParseError, DefusedXmlException) as e:
            raise ValueError(f"XML parse error: {e}") from e

        # 解析namespace
        self.namespace = root.get('namespace', '')

        # 解析各个标签
        for child in root:
            self._parse_element(child)

        self._resolve_result_map_extends()
        # 替换SQL片段引用
        self._replace_sql_fragments()

    @classmethod
    def _secure_fromstring(cls, xml_content: str):
        # MyBatis mapper files conventionally contain this fixed public DTD.
        # It is metadata only for this parser, so strip the exact allowlisted
        # declaration without resolving the remote system identifier. Any
        # other DTD or entity declaration remains forbidden by defusedxml.
        xml_content = re.sub(
            r'<!DOCTYPE\s+mapper\s+PUBLIC\s+'
            r'["\']-//mybatis\.org//DTD Mapper 3\.0//EN["\']\s+'
            r'["\']https?://mybatis\.org/dtd/mybatis-3-mapper\.dtd["\']\s*>',
            '',
            xml_content,
            count=1,
            flags=re.IGNORECASE,
        )
        return DefusedET.fromstring(
            cls._normalize_comparison_operators(xml_content),
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )

    def _parse_element(self, element: ET.Element) -> None:
        """
        解析单个元素

        Args:
            element: XML元素
        """
        tag_name = element.tag

        if tag_name == 'select':
            self._parse_select(element)
        elif tag_name == 'insert':
            self._parse_insert(element)
        elif tag_name == 'update':
            self._parse_update(element)
        elif tag_name == 'delete':
            self._parse_delete(element)
        elif tag_name == 'resultMap':
            self._parse_result_map(element)
        elif tag_name == 'sql':
            self._parse_sql(element)

    def _parse_select(self, element: ET.Element) -> None:
        """
        解析<select>标签

        Args:
            element: select元素
        """
        statement_id = element.get('id', '')
        result_map = element.get('resultMap')
        result_type = element.get('resultType')
        parameter_type = element.get('parameterType')
        fetch_size = element.get('fetchSize')
        timeout = element.get('timeout')

        sql = self._get_element_text(element)

        mapped_statement = MappedStatement(
            id=statement_id,
            sql_type='SELECT',
            sql=sql,
            result_map=result_map,
            parameter_type=parameter_type,
            result_type=result_type,
            fetch_size=int(fetch_size) if fetch_size else None,
            timeout=int(timeout) if timeout else None,
            use_cache=self._parse_bool(element.get('useCache'), default=True),
            flush_cache=self._parse_bool(element.get('flushCache'), default=False),
            database_id=element.get('databaseId'),
        )

        self._add_mapped_statement(mapped_statement)

    def _parse_insert(self, element: ET.Element) -> None:
        """
        解析<insert>标签

        Args:
            element: insert元素
        """
        statement_id = element.get('id', '')
        parameter_type = element.get('parameterType')

        sql = self._get_statement_text(element, excluded_tags={'selectKey'})
        select_key = self._parse_select_key(element)

        mapped_statement = MappedStatement(
            id=statement_id,
            sql_type='INSERT',
            sql=sql,
            parameter_type=parameter_type,
            timeout=self._parse_optional_int(element.get('timeout')),
            flush_cache=self._parse_bool(element.get('flushCache'), default=True),
            use_generated_keys=self._parse_bool(
                element.get('useGeneratedKeys'), default=False
            ),
            key_property=element.get('keyProperty'),
            key_column=element.get('keyColumn'),
            database_id=element.get('databaseId'),
            select_key_sql=select_key[0] if select_key else None,
            select_key_order=select_key[1] if select_key else 'AFTER',
            select_key_result_type=select_key[2] if select_key else None,
            select_key_key_property=select_key[3] if select_key else None,
            select_key_key_column=select_key[4] if select_key else None,
        )

        self._add_mapped_statement(mapped_statement)

    def _parse_update(self, element: ET.Element) -> None:
        """
        解析<update>标签

        Args:
            element: update元素
        """
        statement_id = element.get('id', '')
        parameter_type = element.get('parameterType')

        sql = self._get_element_text(element)

        mapped_statement = MappedStatement(
            id=statement_id,
            sql_type='UPDATE',
            sql=sql,
            parameter_type=parameter_type,
            timeout=self._parse_optional_int(element.get('timeout')),
            flush_cache=self._parse_bool(element.get('flushCache'), default=True),
            database_id=element.get('databaseId'),
        )

        self._add_mapped_statement(mapped_statement)

    def _parse_delete(self, element: ET.Element) -> None:
        """
        解析<delete>标签

        Args:
            element: delete元素
        """
        statement_id = element.get('id', '')
        parameter_type = element.get('parameterType')

        sql = self._get_element_text(element)

        mapped_statement = MappedStatement(
            id=statement_id,
            sql_type='DELETE',
            sql=sql,
            parameter_type=parameter_type,
            timeout=self._parse_optional_int(element.get('timeout')),
            flush_cache=self._parse_bool(element.get('flushCache'), default=True),
            database_id=element.get('databaseId'),
        )

        self._add_mapped_statement(mapped_statement)

    def _parse_result_map(self, element: ET.Element) -> None:
        """
        解析<resultMap>标签

        Args:
            element: resultMap元素
        """
        result_map_id = element.get('id', '')
        result_type = element.get('type', '')

        result_map = ResultMap(id=result_map_id, type=result_type)

        # 解析子标签
        result_map.extends = element.get('extends')
        for child in element:
            if child.tag == 'id':
                column = child.get('column', '')
                property = child.get('property', '')
                result_map.add_id_mapping(column, property)
            elif child.tag == 'result':
                column = child.get('column', '')
                property = child.get('property', '')
                result_map.add_mapping(column, property)
            elif child.tag in {'association', 'collection'}:
                nested = self._parse_nested_mapping(child)
                result_map.add_nested(nested, collection=child.tag == 'collection')
            elif child.tag == 'discriminator':
                discriminator = DiscriminatorMapping(
                    column=child.get('column', '')
                )
                for case in child:
                    if case.tag != 'case':
                        continue
                    case_result_map = case.get('resultMap')
                    if not case_result_map:
                        # Inline case result maps are represented by a
                        # synthetic map and filled recursively below.
                        inline_id = f"{result_map_id}.__case_{case.get('value', '')}"
                        inline = ResultMap(inline_id, case.get('type', result_type))
                        self._parse_result_map_children(case, inline)
                        self.result_maps[inline_id] = inline
                        case_result_map = inline_id
                    discriminator.cases[str(case.get('value'))] = case_result_map
                result_map.discriminator = discriminator

        self.result_maps[result_map_id] = result_map
        # 同时存储带namespace的key（但只存一份实例）
        if self.namespace:
            namespaced_id = f"{self.namespace}.{result_map_id}"
            self.result_maps[namespaced_id] = result_map

    def _parse_result_map_children(self, element: ET.Element, result_map: ResultMap) -> None:
        """Parse mapping children shared by normal maps and discriminator cases."""
        for child in element:
            if child.tag == 'id':
                result_map.add_id_mapping(child.get('column', ''), child.get('property', ''))
            elif child.tag == 'result':
                result_map.add_mapping(child.get('column', ''), child.get('property', ''))
            elif child.tag in {'association', 'collection'}:
                result_map.add_nested(
                    self._parse_nested_mapping(child),
                    collection=child.tag == 'collection',
                )

    def _parse_nested_mapping(self, element: ET.Element) -> NestedResultMapping:
        nested = NestedResultMapping(
            property=element.get('property', ''),
            result_map=element.get('resultMap'),
            result_type=element.get('resultType'),
            select=element.get('select'),
            column=element.get('column'),
            java_type=element.get('javaType'),
            of_type=element.get('ofType'),
        )
        if nested.result_map is None and list(element):
            nested_id = f"__nested_{nested.property}_{id(element)}"
            nested.mapping = ResultMap(nested_id, nested.result_type or nested.of_type or '')
            self._parse_result_map_children(element, nested.mapping)
            nested.result_map = nested_id
            self.result_maps[nested_id] = nested.mapping
        return nested

    def _resolve_result_map_extends(self) -> None:
        """Merge inherited result-map fields after the document is parsed."""
        visiting = set()

        def resolve(result_map: ResultMap) -> None:
            if not result_map.extends:
                return
            if id(result_map) in visiting:
                raise ValueError(f"resultMap extends 存在循环: {result_map.id}")
            visiting.add(id(result_map))
            parent_id = result_map.extends
            parent = self.result_maps.get(parent_id)
            if parent is None and self.namespace:
                parent = self.result_maps.get(f"{self.namespace}.{parent_id}")
            if parent is None:
                raise ValueError(f"未找到 resultMap extends: {parent_id}")
            resolve(parent)
            inherited = dict(parent.mappings)
            inherited.update(result_map.mappings)
            result_map.mappings = inherited
            result_map.id_columns = list(dict.fromkeys(parent.id_columns + result_map.id_columns))
            result_map.associations = list(parent.associations) + list(result_map.associations)
            result_map.collections = list(parent.collections) + list(result_map.collections)
            if result_map.discriminator is None:
                result_map.discriminator = parent.discriminator
            visiting.remove(id(result_map))

        seen = set()
        for result_map in self.result_maps.values():
            if id(result_map) in seen:
                continue
            seen.add(id(result_map))
            resolve(result_map)

    def _parse_select_key(self, element: ET.Element):
        for child in element:
            if child.tag != 'selectKey':
                continue
            return (
                self._get_element_text(child),
                child.get('order', 'AFTER').upper(),
                child.get('resultType'),
                child.get('keyProperty'),
                child.get('keyColumn'),
            )
        return None

    def _get_statement_text(self, element: ET.Element, excluded_tags: set) -> str:
        """Get statement text while dropping non-SQL child controls."""
        parts = []
        if element.text:
            parts.append(element.text)
        for child in element:
            if child.tag not in excluded_tags:
                parts.append(ET.tostring(child, encoding='unicode'))
            if child.tail:
                parts.append(child.tail)
        text = ''.join(parts)
        for entity, value in {
            '&gt;': '>', '&lt;': '<', '&amp;': '&',
            '&quot;': '"', '&apos;': "'",
        }.items():
            text = text.replace(entity, value)
        return text.strip()

    def _parse_sql(self, element: ET.Element) -> None:
        """
        解析<sql>标签

        Args:
            element: sql元素
        """
        sql_id = element.get('id', '')
        sql = self._get_element_text(element)

        sql_fragment = SqlFragment(id=sql_id, sql=sql)
        key = f"{self.namespace}.{sql_id}" if self.namespace else sql_id
        self.sql_fragments[key] = sql_fragment

    @staticmethod
    def _parse_bool(value: Optional[str], default: bool) -> bool:
        if value is None:
            return default
        normalized = value.strip().lower()
        if normalized in {'true', '1', 'yes', 'on'}:
            return True
        if normalized in {'false', '0', 'no', 'off'}:
            return False
        raise ValueError(f"布尔属性值无效: {value}")

    @staticmethod
    def _parse_optional_int(value: Optional[str]) -> Optional[int]:
        return int(value) if value is not None else None

    def _get_element_text(self, element: ET.Element) -> str:
        """
        获取元素的文本内容（包括子元素）

        Args:
            element: XML元素

        Returns:
            文本内容（保留原始XML标签）
        """
        # 使用ET.tostring获取完整内容，然后提取标签内部的部分
        full_str = ET.tostring(element, encoding='unicode')
        # 移除开始和结束标签，只保留内部内容
        # 匹配 <tag ...> 开始标签
        start_tag_end = full_str.find('>') + 1
        # 匹配 </tag> 结束标签
        end_tag_start = full_str.rfind('</')
        if end_tag_start == -1:
            # 自闭合标签
            return ''
        inner_content = full_str[start_tag_end:end_tag_start]
        
        # 将XML实体编码转换回原始字符
        inner_content = inner_content.replace('&gt;', '>')
        inner_content = inner_content.replace('&lt;', '<')
        inner_content = inner_content.replace('&amp;', '&')
        inner_content = inner_content.replace('&quot;', '"')
        inner_content = inner_content.replace('&apos;', "'")
        
        return inner_content.strip()

    def _add_mapped_statement(self, statement: MappedStatement) -> None:
        """
        添加映射语句

        Args:
            statement: 映射语句
        """
        key = f"{self.namespace}.{statement.id}" if self.namespace else statement.id
        if not statement.id:
            raise ValueError("Mapper statement 必须设置 id")
        variants = self._statement_variants.setdefault(key, [])
        if any(item.database_id == statement.database_id for item in variants):
            raise ValueError(f"重复的 Mapper statement id/databaseId: {key}/{statement.database_id}")
        variants.append(statement)
        # Keep the generic statement as the compatibility lookup.  If there
        # is no generic variant, expose the first database-specific statement.
        if key not in self.mapped_statements or statement.database_id is None:
            self.mapped_statements[key] = statement

    def _replace_sql_fragments(self) -> None:
        """
        替换SQL片段引用

        将<include refid="xxx"/>替换为对应的SQL片段
        """
        include_pattern = re.compile(
            r'<include\s+([^>]*)>(.*?)</include>|<include\s+([^>]*)/\s*>',
            flags=re.DOTALL,
        )

        def replace_include(match: re.Match) -> str:
            attributes = match.group(1) or match.group(3) or ''
            content = match.group(2) or ''
            attrs = dict(re.findall(r'(\w+)\s*=\s*["\']([^"\']*)["\']', attributes))
            refid = attrs.get('refid')
            if not refid:
                raise ValueError("<include> 必须设置 refid")

            fragment = self.sql_fragments.get(refid)
            if fragment is None and self.namespace:
                fragment = self.sql_fragments.get(f"{self.namespace}.{refid}")
            if fragment is None:
                raise ValueError(f"未找到 SQL fragment: {refid}")

            properties = {}
            for property_attrs in re.findall(
                r'<property\s+([^>]*)/\s*>', content, flags=re.DOTALL
            ):
                property_values = dict(re.findall(
                    r'(\w+)\s*=\s*["\']([^"\']*)["\']', property_attrs
                ))
                name = property_values.get('name')
                if name is not None and 'value' in property_values:
                    properties[name] = property_values['value']
            sql = fragment.sql
            for name, value in properties.items():
                sql = sql.replace('${' + name + '}', value)
            return sql

        for statement in self.get_all_mapped_statements():
            previous = None
            while previous != statement.sql:
                previous = statement.sql
                statement.sql = include_pattern.sub(replace_include, statement.sql)
            if statement.select_key_sql:
                previous = None
                while previous != statement.select_key_sql:
                    previous = statement.select_key_sql
                    statement.select_key_sql = include_pattern.sub(
                        replace_include, statement.select_key_sql
                    )

    def get_mapped_statement(self, id: str) -> Optional[MappedStatement]:
        """
        获取映射语句

        Args:
            id: 语句ID

        Returns:
            映射语句，未找到返回None
        """
        return self.mapped_statements.get(id)

    def get_result_map(self, id: str) -> Optional[ResultMap]:
        """
        获取结果映射

        Args:
            id: 结果映射ID

        Returns:
            结果映射，未找到返回None
        """
        return self.result_maps.get(id)

    def get_all_mapped_statements(self) -> List[MappedStatement]:
        """
        获取所有映射语句

        Returns:
            映射语句列表
        """
        statements = []
        seen = set()
        for variants in self._statement_variants.values():
            for statement in variants:
                if id(statement) not in seen:
                    seen.add(id(statement))
                    statements.append(statement)
        return statements

    def get_all_result_maps(self) -> List[ResultMap]:
        """
        获取所有结果映射

        Returns:
            结果映射列表
        """
        # 使用id()去重，因为同一个对象可能有多个key
        seen = set()
        unique_maps = []
        for rm in self.result_maps.values():
            if id(rm) not in seen:
                seen.add(id(rm))
                unique_maps.append(rm)
        return unique_maps

    def get_namespace(self) -> Optional[str]:
        """
        获取命名空间

        Returns:
            命名空间
        """
        return self.namespace
