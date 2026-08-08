"""
PyMyBatis XML解析模块

解析XML映射文件，支持动态SQL标签
"""

from .xml_parser import XmlParser, MappedStatement, ResultMap

__all__ = ['XmlParser', 'MappedStatement', 'ResultMap']
