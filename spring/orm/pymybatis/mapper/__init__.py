"""
PyMyBatis映射器模块

包含Mapper接口定义和代理实现
"""

from .mapper import Mapper, MapperProxy, MapperRegistry

__all__ = ['Mapper', 'MapperProxy', 'MapperRegistry']
