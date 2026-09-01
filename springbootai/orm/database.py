"""
数据库ORM模块
集成SQLAlchemy实现企业级数据库操作
"""
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.orm import (
    declarative_base, sessionmaker, Session, scoped_session, Query,
)
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
from typing import Optional
import logging
import asyncio
import threading
from contextlib import contextmanager
from springbootai.logging.context import sanitize_url

logger = logging.getLogger("Spring.ORM")

# 创建Base类
Base = declarative_base()


def _session_scope_key():
    """Return an asyncio-task scope when applicable, otherwise a thread scope."""
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return task if task is not None else ("thread", threading.get_ident())


class _ManagedQuery:
    """Close the standalone query session after a terminal operation."""

    _TERMINAL_METHODS = {
        "all", "first", "one", "one_or_none", "scalar", "count",
        "delete", "update", "get",
    }

    def __init__(self, query: Query, session: Session):
        self._query = query
        self._session = session
        self._closed = False

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._session.close()

    def __iter__(self):
        try:
            yield from self._query
        finally:
            self.close()

    def __getattr__(self, name):
        attribute = getattr(self._query, name)
        if not callable(attribute):
            return attribute

        def invoke(*args, **kwargs):
            try:
                result = attribute(*args, **kwargs)
            except Exception:
                self.close()
                raise
            if isinstance(result, Query):
                self._query = result
                return self
            if name in self._TERMINAL_METHODS:
                self.close()
            return result

        return invoke

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class DatabaseManager:
    """数据库管理器"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, db_url: str = "sqlite:///./test.db", echo: bool = False):
        if hasattr(self, '_initialized'):
            return
        self.db_url = db_url
        self.echo = echo
        self._engine = None
        self._session_factory = None
        self._scoped_session = None
        self._resource_lock = threading.RLock()
        self._initialized = True

    def _detach_resources(self):
        scoped = self._scoped_session
        engine = self._engine
        self._engine = None
        self._session_factory = None
        self._scoped_session = None
        if scoped is not None:
            remove = getattr(scoped, "remove", None)
            if callable(remove):
                try:
                    remove()
                except Exception:
                    logger.warning(
                        "Failed to remove database session registry",
                        exc_info=True,
                    )
        if engine is not None:
            dispose = getattr(engine, "dispose", None)
            if callable(dispose):
                try:
                    dispose()
                except Exception:
                    logger.warning(
                        "Failed to dispose database engine",
                        exc_info=True,
                    )

    def configure(self, db_url: Optional[str] = None, echo: Optional[bool] = None) -> None:
        """重新配置单例的数据库连接参数（读取配置后调用）。

        ``DatabaseManager`` 为单例，``__init__`` 的 ``_initialized`` 守卫会阻止后续
        ``__init__`` 更新参数。``init_database`` 读取 ``application.yml`` 的
        ``database.url`` / ``database.echo`` 后，必须通过本方法重新配置，否则
        ``db_url`` 永远停留在默认 ``'sqlite:///./test.db'``，用户配置被静默丢弃。

        重置已建立的 engine/session，强制下次 ``connect()`` 重建。

        Args:
            db_url: 数据库连接 URL，None 表示保留原值
            echo: 是否开启 SQLAlchemy SQL 回显，None 表示保留原值
        """
        with self._resource_lock:
            self._detach_resources()
            if db_url is not None:
                self.db_url = db_url
            if echo is not None:
                self.echo = echo

    def connect(self) -> None:
        """连接数据库"""
        with self._resource_lock:
            if self._engine is not None:
                return
            try:
                engine = create_engine(self.db_url, echo=self.echo)
                session_factory = sessionmaker(
                    bind=engine,
                    autocommit=False,
                    autoflush=False,
                )
                session_registry = scoped_session(
                    session_factory, scopefunc=_session_scope_key)
                self._engine = engine
                self._session_factory = session_factory
                self._scoped_session = session_registry
                logger.info(
                    "Connected to database: %s", sanitize_url(self.db_url))
            except Exception as exc:
                logger.error(
                    "Failed to connect to database error_type=%s",
                    type(exc).__name__,
                )
                raise
    
    def get_engine(self):
        """获取数据库引擎"""
        self.connect()
        with self._resource_lock:
            return self._engine
    
    def get_session(self) -> Session:
        """获取数据库会话"""
        self.connect()
        with self._resource_lock:
            registry = self._scoped_session
        session = registry()
        session.info["springbootai.scoped_registry"] = registry
        return session

    @staticmethod
    def _release_session(session: Session) -> None:
        registry = session.info.pop("springbootai.scoped_registry", None)
        try:
            session.close()
        finally:
            if registry is not None:
                registry.remove()

    @contextmanager
    def session_scope(self):
        """Yield a standalone session and deterministically close it."""
        self.connect()
        with self._resource_lock:
            factory = self._session_factory
        session = factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def close(self) -> None:
        """Release the current scoped session and dispose the connection pool."""
        with self._resource_lock:
            self._detach_resources()
    
    def create_all(self):
        """创建所有表"""
        engine = self.get_engine()
        Base.metadata.create_all(engine)
        logger.info("All tables created")
    
    def drop_all(self):
        """删除所有表"""
        engine = self.get_engine()
        Base.metadata.drop_all(engine)
        logger.info("All tables dropped")
    
    def execute(self, statement, *args, **kwargs):
        """执行SQL语句"""
        session = self.get_session()
        try:
            result = session.execute(statement, *args, **kwargs)
            session.commit()
            return result
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error(
                "SQL execution failed error_type=%s", type(exc).__name__)
            raise
        finally:
            self._release_session(session)
    
    def insert(self, model):
        """插入数据"""
        session = self.get_session()
        try:
            session.add(model)
            session.commit()
            session.refresh(model)
            return model
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error("Insert failed error_type=%s", type(exc).__name__)
            raise
        finally:
            self._release_session(session)
    
    def update(self, model):
        """更新数据"""
        session = self.get_session()
        try:
            # 使用merge处理脱管对象
            merged_model = session.merge(model)
            session.commit()
            session.refresh(merged_model)
            # 更新原始对象的属性
            for attr in ['id', 'created_at', 'updated_at'] + [c.name for c in model.__table__.columns]:
                if hasattr(merged_model, attr):
                    setattr(model, attr, getattr(merged_model, attr))
            return model
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error("Update failed error_type=%s", type(exc).__name__)
            raise
        finally:
            self._release_session(session)
    
    def delete(self, model):
        """删除数据"""
        session = self.get_session()
        try:
            session.delete(model)
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error("Delete failed error_type=%s", type(exc).__name__)
            raise
        finally:
            self._release_session(session)
    
    def query(self, model):
        """Create a query whose standalone session closes on evaluation."""
        self.connect()
        with self._resource_lock:
            factory = self._session_factory
        session = factory()
        return _ManagedQuery(session.query(model), session)
    
    def flush(self):
        """刷新会话"""
        session = self.get_session()
        session.flush()
    
    def commit(self):
        """提交事务"""
        session = self.get_session()
        try:
            session.commit()
        finally:
            self._release_session(session)
    
    def rollback(self):
        """回滚事务"""
        session = self.get_session()
        try:
            session.rollback()
        finally:
            self._release_session(session)


# 创建全局数据库管理器实例
db_manager = DatabaseManager()


def init_database(config: dict) -> None:
    """
    初始化数据库配置

    通过 ``configure`` 重新配置单例 ``DatabaseManager``，使 ``database.url`` /
    ``database.echo`` 配置生效。直接 ``DatabaseManager(db_url=...)`` 因单例
    ``_initialized`` 守卫不会更新参数（与 ``SpringLogger`` 同类问题）。

    Args:
        config: 配置字典，包含url, echo等
    """
    # 单例原地更新配置，避免 _initialized 守卫导致配置被忽略
    db_manager.configure(
        db_url=config.get('url', 'sqlite:///./test.db'),
        echo=config.get('echo', False),
    )
    db_manager.connect()

    # 创建所有表
    db_manager.create_all()


# ==================== 基础实体类 ====================

class BaseEntity(Base):
    """基础实体类"""
    __abstract__ = True
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
    deleted = Column(Boolean, default=False, nullable=False)


class User(BaseEntity):
    """用户实体"""
    __tablename__ = 'users'
    
    username = Column(String(50), unique=True, nullable=False)
    password = Column(String(255), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    phone = Column(String(20))
    role = Column(String(50), default='USER')
    status = Column(Integer, default=1)


class AuditLog(BaseEntity):
    """审计日志实体"""
    __tablename__ = 'audit_logs'
    
    action = Column(String(100), nullable=False)
    target = Column(String(200))
    detail = Column(Text)
    operator = Column(String(100))
    status = Column(String(20), default='SUCCESS')
    duration = Column(Float)
