"""
数据库ORM模块
集成SQLAlchemy实现企业级数据库操作
"""
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship, scoped_session
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger("Spring.ORM")

# 创建Base类
Base = declarative_base()


class DatabaseManager:
    """数据库管理器"""
    
    _instance = None
    _lock = __import__('threading').Lock()
    
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
        self._initialized = True

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
        if db_url is not None:
            self.db_url = db_url
        if echo is not None:
            self.echo = echo
        # 重置已建立的连接，强制 connect() 重建 engine
        self._engine = None
        self._session_factory = None
        self._scoped_session = None

    def connect(self) -> None:
        """连接数据库"""
        try:
            self._engine = create_engine(self.db_url, echo=self.echo)
            
            # 创建Session工厂
            self._session_factory = sessionmaker(
                bind=self._engine,
                autocommit=False,
                autoflush=False,
            )
            
            # 创建线程安全的Scoped Session
            self._scoped_session = scoped_session(self._session_factory)
            
            logger.info(f"Connected to database: {self.db_url}")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
    
    def get_engine(self):
        """获取数据库引擎"""
        if self._engine is None:
            self.connect()
        return self._engine
    
    def get_session(self) -> Session:
        """获取数据库会话"""
        if self._scoped_session is None:
            self.connect()
        return self._scoped_session()
    
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
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"SQL execution failed: {e}")
            raise
        finally:
            session.close()
    
    def insert(self, model):
        """插入数据"""
        session = self.get_session()
        try:
            session.add(model)
            session.commit()
            session.refresh(model)
            return model
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Insert failed: {e}")
            raise
        finally:
            session.close()
    
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
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Update failed: {e}")
            raise
        finally:
            session.close()
    
    def delete(self, model):
        """删除数据"""
        session = self.get_session()
        try:
            session.delete(model)
            session.commit()
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Delete failed: {e}")
            raise
        finally:
            session.close()
    
    def query(self, model):
        """创建查询对象"""
        session = self.get_session()
        return session.query(model)
    
    def flush(self):
        """刷新会话"""
        session = self.get_session()
        session.flush()
    
    def commit(self):
        """提交事务"""
        session = self.get_session()
        session.commit()
    
    def rollback(self):
        """回滚事务"""
        session = self.get_session()
        session.rollback()


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
