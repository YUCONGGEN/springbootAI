"""Spring Boot 风格测试切片（对齐 ``@SpringBootTest`` / ``@WebMvcTest`` / ``@DataJpaTest``）。

提供三种测试上下文切片，复用既有 ``ApplicationContext`` / ``WebApplicationContext`` /
``DdlAutoManager`` / ``PagingAndSortingRepository`` 基础设施：

- **``SpringBootTest``**：全量应用上下文（扫描+装配所有 Bean），对齐 ``@SpringBootTest``。
- **``WebMvcTest``**：仅 Web 切片——只注册指定 Controller（依赖用 ``MagicMock`` 注入），
  返回 FastAPI ``TestClient``，对齐 ``@WebMvcTest``。
- **``DataJpaTest``**：仅数据切片——内存 SQLite + ``DdlAutoManager`` 建表 +
  ``PagingAndSortingRepository`` 工厂，对齐 ``@DataJpaTest``。

设计原则：**复用既有范式**，不重复造轮子；切片上下文提供 ``close()`` 清理，便于 pytest 夹具使用。

与 Java 的差异：
- Spring Boot 切片用专用 ``ApplicationContextInitializer`` 裁剪自动配置；本实现通过手动注册
  指定 Bean + Mock 依赖实现等价裁剪，更轻量。
- ``@WebMvcTest`` 在 Spring 中自动 Mock ``@Service``/``@Repository``；本实现 Mock 构造函数依赖。
"""
from __future__ import annotations

import inspect
import os
import sqlite3
import tempfile
from typing import Any, Dict, List, Optional, Type
from unittest.mock import MagicMock

import yaml


# ==================== 通用：内存连接池（DataJpaTest 复用）====================

class _PooledConn:
    """连接池包装：``close()`` 为 no-op（池化语义），其余委托底层连接。"""

    def __init__(self, conn):
        self._conn = conn

    def cursor(self, *a, **k):
        return self._conn.cursor(*a, **k)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return None

    def __getattr__(self, item):
        return getattr(self._conn, item)


class _DbutilsPooled:
    """DBUtils 风格池化连接：``.connection`` 暴露底层连接（``DdlAutoManager`` 期望）。"""

    def __init__(self, conn):
        self.connection = conn


class TestPool:
    """三接口内存连接池：
    - ``get_connection``/``return_connection`` + ``.connection``：``DdlAutoManager``
    - ``connection()``：``PagingAndSortingRepository``
    """

    def __init__(self, conn):
        self._conn = conn

    def get_connection(self):
        return _DbutilsPooled(self._conn)

    def return_connection(self, pooled):
        return None

    def connection(self):
        return _PooledConn(self._conn)

    def get_pool_stats(self):
        return {"dialect": "sqlite"}


# ==================== 工具 ====================

def _write_temp_config(config: Dict[str, Any]) -> str:
    """把配置字典写到临时 yml 文件，返回路径。"""
    fd, path = tempfile.mkstemp(suffix=".yml", prefix="springboot_test_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        yaml.safe_dump(config or {}, f, allow_unicode=True)
    return path


def _instantiate_with_mocks(cls: Type) -> Any:
    """实例化类，所有非 self 构造参数用 ``MagicMock`` 注入（``@WebMvcTest`` Mock 依赖）。

    无论参数是否有默认值都注入 Mock，确保 ``@Autowired`` 依赖被替换为可控桩对象，
    对齐 Spring ``@WebMvcTest`` 自动 Mock ``@Service``/``@Repository`` 的语义。
    """
    sig = inspect.signature(cls.__init__)
    kwargs = {}
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        # *args / **kwargs 不注入
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        kwargs[name] = MagicMock()
    return cls(**kwargs)


# ==================== SpringBootTest（全量上下文）====================

class SpringBootTest:
    """全量应用上下文测试切片（对齐 ``@SpringBootTest``）。

    Args:
        main_class: ``@SpringBootApplication`` 标注的入口类。
        config: 可选配置字典，写入临时 yml；未提供则用入口类所在目录的 application.yml。
    """

    def __init__(self, main_class: Type, config: Optional[Dict[str, Any]] = None):
        from springbootai.context.application_context import ApplicationContext
        from springbootai.config.config_loader import ConfigLoader

        self._temp_config_path: Optional[str] = None
        if config is not None:
            self._temp_config_path = _write_temp_config(config)
            loader = ConfigLoader(config_path=self._temp_config_path)
        else:
            loader = None
        self._context = ApplicationContext(main_class, config_loader=loader)
        self._context.refresh()

    def get_context(self):
        return self._context

    def get_bean(self, name: str) -> Any:
        return self._context.get_bean(name)

    def get_bean_by_type(self, bean_type: Type) -> Any:
        return self._context.get_bean_by_type(bean_type)

    def publish_event(self, event: Any) -> Any:
        return self._context.publish_event(event)

    def close(self) -> None:
        try:
            self._context.destroy()
        finally:
            if self._temp_config_path and os.path.exists(self._temp_config_path):
                os.unlink(self._temp_config_path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


# ==================== WebMvcTest（Web 切片）====================

class WebMvcTest:
    """Web 切片测试（对齐 ``@WebMvcTest``）：只注册指定 Controller，依赖 Mock 注入。

    Args:
        controllers: 要注册的 Controller 类列表。
        config: 可选配置字典。
        mock_dependencies: 是否用 ``MagicMock`` 注入构造函数依赖（默认 True）。
        controller_advice: 可选的 ``@ControllerAdvice`` 类列表，注册全局异常处理。

    用法::

        with WebMvcTest(controllers=[UserController]) as mvc:
            resp = mvc.get_client().get("/users")
    """

    def __init__(
        self,
        controllers: List[Type],
        config: Optional[Dict[str, Any]] = None,
        mock_dependencies: bool = True,
        controller_advice: Optional[List[Type]] = None,
    ):
        from springbootai.context.application_context import ApplicationContext
        from springbootai.context.bean_definition import BeanDefinition
        from springbootai.config.config_loader import ConfigLoader
        from springbootai.web.web_context import WebApplicationContext

        if not controllers:
            raise ValueError("controllers 不能为空")

        self._temp_config_path: Optional[str] = None
        loader = ConfigLoader(
            config_path=(_write_temp_config(config) if config is not None else _write_temp_config({}))
        )
        self._temp_config_path = loader.config_path
        # 构造一个不 refresh 的最小上下文，手动注册 Controller Bean
        self._context = ApplicationContext(_MinimalApp, config_loader=loader)

        for ctrl_cls in controllers:
            instance = _instantiate_with_mocks(ctrl_cls) if mock_dependencies else ctrl_cls()
            bean_name = self._generate_bean_name(ctrl_cls)
            definition = BeanDefinition(bean_class=ctrl_cls, bean_name=bean_name)
            # 复制类上的注解到定义（@RestController 等）
            for ann in getattr(ctrl_cls, '__spring_annotations__', []):
                definition.add_annotation(ann)
            self._context.bean_factory.register_bean_definition(bean_name, definition)
            self._context.bean_factory.register_instance(bean_name, instance)

        # 注册 ControllerAdvice（全局异常处理）
        for advice_cls in (controller_advice or []):
            advice_instance = advice_cls()
            advice_name = self._generate_bean_name(advice_cls)
            advice_def = BeanDefinition(bean_class=advice_cls, bean_name=advice_name)
            for ann in getattr(advice_cls, '__spring_annotations__', []):
                advice_def.add_annotation(ann)
            self._context.bean_factory.register_bean_definition(advice_name, advice_def)
            self._context.bean_factory.register_instance(advice_name, advice_instance)

        # 构建 WebApplicationContext 并初始化路由
        self._web_context = WebApplicationContext(self._context)
        self._web_context.init()
        self._client = None

    @staticmethod
    def _generate_bean_name(cls: Type) -> str:
        name = cls.__name__
        return name[0].lower() + name[1:] if name else name

    def get_app(self):
        return self._web_context.get_app()

    def get_context(self):
        return self._context

    def get_client(self):
        from fastapi.testclient import TestClient
        if self._client is None:
            self._client = TestClient(self.get_app())
        return self._client

    def get_controller(self, ctrl_cls: Type) -> Any:
        return self._context.get_bean_by_type(ctrl_cls)

    def close(self) -> None:
        try:
            self._context.destroy()
        finally:
            if self._temp_config_path and os.path.exists(self._temp_config_path):
                os.unlink(self._temp_config_path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


# ==================== DataJpaTest（数据切片）====================

class DataJpaTest:
    """数据切片测试（对齐 ``@DataJpaTest``）：内存 SQLite + 建表 + Repository 工厂。

    Args:
        entities: 实体类列表（``@entity`` 标注）。
        dialect: 数据库方言（默认 ``sqlite``，内存库）。

    用法::

        with DataJpaTest(entities=[User]) as jpa:
            repo = jpa.repository_for(User)
            repo.save(User(name="tom"))
    """

    def __init__(self, entities: List[Type], dialect: str = "sqlite"):
        if not entities:
            raise ValueError("entities 不能为空")
        from springbootai.orm.ddl_auto import DdlAutoManager

        self._entities = list(entities)
        self._dialect = dialect
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = None
        self._pool = TestPool(self._conn)
        self._mgr = DdlAutoManager(self._pool, dialect=dialect, mode="create")
        for entity_cls in self._entities:
            self._mgr.register_entity(entity_cls)
        self._mgr.execute()

    def get_connection(self):
        return self._conn

    def get_pool(self) -> TestPool:
        return self._pool

    def repository_for(self, entity_class: Type):
        """为指定实体构造 ``PagingAndSortingRepository``（复用 Spring Data 抽象）。"""
        from springbootai.data import PagingAndSortingRepository
        return PagingAndSortingRepository(self._pool, entity_class, dialect=self._dialect)

    def get_entities(self) -> List[Type]:
        return list(self._entities)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


# ==================== 最小入口类 ====================

class _MinimalApp:
    """``WebMvcTest`` 用的最小 ``@SpringBootApplication`` 入口（空扫描基包）。"""
    pass


# 应用 @SpringBootApplication 注解到最小入口，满足 ApplicationContext 构造
try:
    from springbootai.annotations.core import SpringBootApplication
    _MinimalApp = SpringBootApplication(scan_base_packages=[])(_MinimalApp)
except ImportError:  # pragma: no cover
    pass


__all__ = [
    "TestPool",
    "SpringBootTest",
    "WebMvcTest",
    "DataJpaTest",
]
