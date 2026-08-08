"""
PyMyBatis SqlSessionFactory模块

SqlSessionFactory是SqlSession的工厂类，负责创建SqlSession实例
"""

from typing import Optional
from ..configuration import Configuration
from .sql_session import SqlSession, create_pool_from_configuration


class SqlSessionFactory:
    """
    SqlSession工厂类

    核心功能：
    1. 创建SqlSession实例
    2. 管理配置
    """

    def __init__(self, configuration: Optional[Configuration] = None):
        """
        初始化SqlSessionFactory

        Args:
            configuration: 配置对象，不指定则使用默认配置
        """
        self.configuration = configuration or Configuration()
        self.connection_pool = create_pool_from_configuration(self.configuration)
        self._closed = False

    def open_session(self) -> SqlSession:
        """
        创建SqlSession实例

        Returns:
            SqlSession实例
        """
        if self._closed:
            raise RuntimeError("SqlSessionFactory 已关闭")
        return SqlSession(self.configuration, connection_pool=self.connection_pool)

    def get_configuration(self) -> Configuration:
        """
        获取配置对象

        Returns:
            配置对象
        """
        return self.configuration

    def set_configuration(self, configuration: Configuration) -> None:
        """
        设置配置对象

        Args:
            configuration: 配置对象
        """
        self.connection_pool.close()
        self.configuration = configuration
        self.connection_pool = create_pool_from_configuration(configuration)
        self._closed = False

    def close(self) -> None:
        """关闭工厂拥有的共享连接池。"""
        if self._closed:
            return
        self.connection_pool.close()
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
