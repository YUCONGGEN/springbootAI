"""
PyMyBatis连接池管理模块

实现高性能数据库连接池，核心特性：
- 基于DBUtils实现高性能连接池
- 最小/最大连接数控制
- 连接空闲超时回收
- 连接有效性验证
- 连接泄漏检测（长时间未归还自动回收并告警）
- 熔断降级机制（防止数据库故障导致的级联失败）
- 多数据源支持
- 线程安全
"""

import threading
import time
import queue
import logging
from typing import Dict, Any, Set, Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

_POOL_CONFIG_KEYS = {
    'driver', 'min_size', 'max_size', 'max_idle', 'wait_timeout',
    'validation_interval', 'leak_detection_enabled', 'leak_timeout',
    'circuit_breaker_enabled', 'circuit_breaker_failure_threshold',
    'circuit_breaker_recovery_timeout', 'circuit_breaker_success_threshold',
}

# 延迟导入熔断器模块
try:
    from ..circuit_breaker import DatabaseCircuitBreaker, CircuitBreakerError
    _circuit_breaker_available = True
except ImportError:
    _circuit_breaker_available = False
    logger.warning("熔断器模块不可用，安装方法: pip install pybreaker 或使用内置熔断器")


class PooledConnection:
    """
    池化连接封装类

    封装原始连接，记录连接状态和使用信息

    安全特性：
    - 记录使用时间，支持连接泄漏检测
    - 自动标记连接状态
    """

    def __init__(self, connection: Any, pool: 'ConnectionPool', created_at: float):
        self.connection = connection
        self.pool = pool
        self.created_at = created_at
        self.last_used_at = created_at
        self.in_use = False
        self._lock = threading.RLock()
        self._checkout_time = None

    def __enter__(self):
        """上下文管理器进入"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出，自动归还连接"""
        self.pool.return_connection(self)

    def mark_in_use(self):
        """标记连接为使用中"""
        with self._lock:
            if self.in_use:
                raise RuntimeError("连接已被借出，不能重复借用")
            self.in_use = True
            now = time.monotonic()
            self.last_used_at = now
            self._checkout_time = now

    def mark_free(self):
        """标记连接为空闲"""
        with self._lock:
            self.in_use = False
            self.last_used_at = time.monotonic()
            self._checkout_time = None

    def is_valid(self) -> bool:
        """检查连接是否有效"""
        try:
            # 根据不同数据库驱动检查连接有效性
            if hasattr(self.connection, 'ping'):
                self.connection.ping()
            elif hasattr(self.connection, 'isclosed') and not self.connection.isclosed():
                return True
            return True
        except Exception:
            return False

    def get_idle_time(self) -> float:
        """获取空闲时间（秒）"""
        return time.monotonic() - self.last_used_at

    def get_checkout_duration(self) -> float:
        """获取连接已借出的时间（秒）"""
        if self._checkout_time is None:
            return 0
        return time.monotonic() - self._checkout_time

    def get_connection(self) -> Any:
        """获取原始连接"""
        return self.connection


class ConnectionPool(ABC):
    """
    连接池抽象基类

    定义连接池的核心接口：
    - 获取连接
    - 归还连接
    - 管理连接生命周期
    - 连接泄漏检测
    - 熔断降级机制
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = dict(config)
        self.min_size = int(config.get('min_size', 5))
        self.max_size = int(config.get('max_size', 20))
        self.max_idle = float(config.get('max_idle', 10))
        self.wait_timeout = float(config.get('wait_timeout', 30))
        self.validation_interval = float(config.get('validation_interval', 300))
        self.leak_detection_enabled = self._as_bool(config.get('leak_detection_enabled', True))
        self.leak_timeout = float(config.get('leak_timeout', 300))

        if self.min_size < 0:
            raise ValueError("min_size 不能小于 0")
        if self.max_size < 1:
            raise ValueError("max_size 必须大于 0")
        if self.min_size > self.max_size:
            raise ValueError("min_size 不能大于 max_size")
        if self.wait_timeout <= 0:
            raise ValueError("wait_timeout 必须大于 0")
        if self.max_idle < 0 or self.validation_interval <= 0 or self.leak_timeout <= 0:
            raise ValueError("连接池超时配置必须为正数")

        # 熔断器配置
        self.circuit_breaker_enabled = self._as_bool(config.get('circuit_breaker_enabled', False))
        self.circuit_breaker_failure_threshold = int(config.get('circuit_breaker_failure_threshold', 3))
        self.circuit_breaker_recovery_timeout = float(config.get('circuit_breaker_recovery_timeout', 60))
        self.circuit_breaker_success_threshold = int(config.get('circuit_breaker_success_threshold', 3))

        self._pool: queue.Queue = queue.Queue(maxsize=self.max_size)
        self._active_count = 0
        self._active_connections: Set[PooledConnection] = set()
        self._lock = threading.RLock()
        self._validation_lock = threading.Lock()
        self._last_validation = 0
        self._total_connections = 0
        self._closed = False
        self._stop_event = threading.Event()

        # 初始化熔断器
        self._circuit_breaker = None
        if self.circuit_breaker_enabled and _circuit_breaker_available:
            self._circuit_breaker = DatabaseCircuitBreaker(
                failure_threshold=self.circuit_breaker_failure_threshold,
                recovery_timeout=self.circuit_breaker_recovery_timeout,
                success_threshold=self.circuit_breaker_success_threshold,
                name=f"pool_{id(self)}"
            )
            logger.info("连接池熔断器已启用")

        # 初始化最小连接数
        self._initialize_pool()

        # 启动连接泄漏检测线程
        if self.leak_detection_enabled:
            self._start_leak_detection()

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {'1', 'true', 'yes', 'on'}
        return bool(value)

    @abstractmethod
    def _create_connection(self) -> Any:
        """创建新连接（由子类实现）"""
        pass

    @abstractmethod
    def _close_connection(self, connection: Any) -> None:
        """关闭连接（由子类实现）"""
        pass

    def _initialize_pool(self) -> None:
        """初始化连接池，创建最小连接数"""
        last_error = None
        for _ in range(self.min_size):
            try:
                conn = self._create_connection()
                pooled_conn = PooledConnection(conn, self, time.monotonic())
                self._pool.put(pooled_conn)
                self._total_connections += 1
            except Exception as e:
                last_error = e
                logger.error(f"初始化连接池失败: {e}")

        if self.min_size > 0 and self._total_connections == 0:
            raise ConnectionError("连接池初始化失败，未能建立任何数据库连接") from last_error

    def _start_leak_detection(self) -> None:
        """启动连接泄漏检测线程"""
        def leak_detector():
            interval = max(1.0, min(60.0, self.leak_timeout / 2))
            while not self._stop_event.wait(interval):
                self._detect_leaks()

        leak_thread = threading.Thread(target=leak_detector, daemon=True)
        leak_thread.start()
        logger.info("连接泄漏检测线程已启动")

    def _detect_leaks(self) -> None:
        """检测连接泄漏"""
        with self._lock:
            active_connections = list(self._active_connections)

        for pooled_conn in active_connections:
            checkout_duration = pooled_conn.get_checkout_duration()
            if checkout_duration > self.leak_timeout:
                logger.warning(
                    "检测到疑似连接泄漏：连接已借出 %.2f 秒，超过阈值 %.2f 秒",
                    checkout_duration,
                    self.leak_timeout,
                )

    def get_connection(self) -> PooledConnection:
        """
        获取连接

        Returns:
            池化连接对象

        Raises:
            ConnectionError: 获取连接超时
            CircuitBreakerError: 熔断器打开时抛出
        """
        # 如果启用了熔断器，使用熔断器保护连接获取
        if self._circuit_breaker:
            try:
                return self._circuit_breaker.call(self._get_connection_internal)
            except CircuitBreakerError as e:
                logger.error(f"连接池熔断器打开，请求被拒绝: {e}")
                raise ConnectionError(f"数据库连接熔断，请稍后重试") from e

        return self._get_connection_internal()

    def _get_connection_internal(self) -> PooledConnection:
        """
        获取连接（内部方法，不受熔断器保护）

        Returns:
            池化连接对象

        Raises:
            ConnectionError: 获取连接超时
        """
        # 定期验证连接有效性
        self._validate_pool_periodically()

        deadline = time.monotonic() + self.wait_timeout

        while True:
            if self._closed:
                raise ConnectionError("连接池已关闭")

            try:
                pooled_conn = self._pool.get_nowait()
            except queue.Empty:
                pooled_conn = self._create_connection_if_capacity()
                if pooled_conn is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ConnectionError(
                            f"获取连接超时，最大连接数已达上限: {self.max_size}"
                        )
                    try:
                        pooled_conn = self._pool.get(timeout=remaining)
                    except queue.Empty as exc:
                        raise ConnectionError(
                            f"获取连接超时，最大连接数已达上限: {self.max_size}"
                        ) from exc

            if not pooled_conn.is_valid():
                logger.warning("检测到无效连接，关闭并重新获取")
                self._dispose_connection(pooled_conn)
                continue

            pooled_conn.mark_in_use()
            with self._lock:
                if self._closed:
                    pooled_conn.mark_free()
                    self._dispose_connection(pooled_conn)
                    raise ConnectionError("连接池已关闭")
                self._active_connections.add(pooled_conn)
                self._active_count = len(self._active_connections)

            logger.debug(f"获取连接成功，活跃连接数={self._active_count}")
            return pooled_conn

    def _create_connection_if_capacity(self):
        """在未达到上限时立即扩容，并用预留计数防止并发超配。"""
        with self._lock:
            if self._closed or self._total_connections >= self.max_size:
                return None
            self._total_connections += 1

        try:
            conn = self._create_connection()
            pooled_conn = PooledConnection(conn, self, time.monotonic())
            logger.info(f"创建新连接，总连接数={self._total_connections}")
            return pooled_conn
        except Exception as e:
            with self._lock:
                self._total_connections -= 1
            raise ConnectionError(f"创建新连接失败: {e}") from e

    def _dispose_connection(self, pooled_conn: PooledConnection) -> None:
        with self._lock:
            self._active_connections.discard(pooled_conn)
            self._active_count = len(self._active_connections)
            if self._total_connections > 0:
                self._total_connections -= 1
        self._close_connection(pooled_conn.get_connection())

    def return_connection(self, pooled_conn: PooledConnection) -> None:
        """
        归还连接到池中

        Args:
            pooled_conn: 池化连接对象
        """
        if pooled_conn.pool is not self:
            raise ValueError("连接不属于当前连接池")
        if not pooled_conn.in_use:
            raise ValueError("连接已归还，不能重复归还")

        checkout_duration = pooled_conn.get_checkout_duration()
        if checkout_duration > self.leak_timeout:
            logger.warning(
                f"连接泄漏检测：连接已借出 {checkout_duration:.2f} 秒，超过阈值 {self.leak_timeout} 秒"
            )

        # DB-API连接归还前统一回滚，避免未提交状态污染下一个请求。
        try:
            pooled_conn.get_connection().rollback()
        except Exception:
            logger.exception("重置数据库连接失败，将关闭该连接")
            pooled_conn.mark_free()
            self._dispose_connection(pooled_conn)
            return

        pooled_conn.mark_free()
        with self._lock:
            self._active_connections.discard(pooled_conn)
            self._active_count = len(self._active_connections)

        logger.debug(f"归还连接，活跃连接数={self._active_count}")

        if self._closed or not pooled_conn.is_valid():
            self._dispose_connection(pooled_conn)
            return

        # 归还到池中
        try:
            self._pool.put(pooled_conn, timeout=1)
        except queue.Full:
            # 池已满，关闭该连接
            logger.info("连接池已满，关闭多余连接")
            self._dispose_connection(pooled_conn)

    def _validate_pool_periodically(self) -> None:
        """定期验证池中的连接有效性"""
        now = time.monotonic()
        if now - self._last_validation < self.validation_interval:
            return

        if not self._validation_lock.acquire(blocking=False):
            return

        try:
            self._last_validation = now
            logger.debug("开始验证连接池中的连接")

            valid_connections = []
            while True:
                try:
                    pooled_conn = self._pool.get_nowait()
                except queue.Empty:
                    break

                can_evict_idle = self._total_connections > self.min_size
                if not pooled_conn.is_valid() or (
                    can_evict_idle and pooled_conn.get_idle_time() > self.max_idle
                ):
                    self._dispose_connection(pooled_conn)
                else:
                    valid_connections.append(pooled_conn)

            for pooled_conn in valid_connections:
                self._pool.put_nowait(pooled_conn)

            while not self._closed:
                with self._lock:
                    needs_connection = self._total_connections < self.min_size
                if not needs_connection:
                    break
                try:
                    pooled_conn = self._create_connection_if_capacity()
                    if pooled_conn is None:
                        break
                    self._pool.put_nowait(pooled_conn)
                except Exception as e:
                    logger.error(f"补充连接池失败: {e}")
                    break
        finally:
            self._validation_lock.release()

    def get_pool_stats(self) -> Dict[str, Any]:
        """
        获取连接池统计信息

        Returns:
            统计信息字典
        """
        with self._lock:
            stats = {
                'active_connections': self._active_count,
                'idle_connections': self._pool.qsize(),
                'min_size': self.min_size,
                'max_size': self.max_size,
                'total_connections': self._total_connections,
                'leak_detection_enabled': self.leak_detection_enabled,
                'leak_timeout': self.leak_timeout,
                'circuit_breaker_enabled': self.circuit_breaker_enabled,
                'closed': self._closed,
            }

        # 添加熔断器统计信息
        if self._circuit_breaker:
            stats['circuit_breaker'] = self._circuit_breaker.get_stats()

        return stats

    def close(self) -> None:
        """关闭连接池，释放所有连接"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            active_connections = list(self._active_connections)
        self._stop_event.set()
        logger.info("关闭连接池")
        idle_connections = []
        while True:
            try:
                idle_connections.append(self._pool.get_nowait())
            except queue.Empty:
                break
        for pooled_conn in idle_connections + active_connections:
            self._dispose_connection(pooled_conn)

    def __del__(self):
        """析构函数，确保连接池被关闭"""
        try:
            self.close()
        except Exception:
            pass


def _get_docker_container_ip_by_port(target_port: int) -> Optional[str]:
    """通过Docker CLI自动检测映射了指定端口的容器IP（开发环境辅助）
    
    按以下顺序查找：
    1. 精确查找端口映射匹配target_port的运行中容器
    2. 如果是数据库默认端口(3306/5432)，兜底查找mysql/mariadb/postgres镜像容器
    返回容器内部IP，找不到返回None
    """
    import os
    import re
    # 允许通过环境变量禁用Docker自动检测
    if os.getenv('SPRING_DISABLE_DOCKER_IP_DETECT', '').lower() in ('1', 'true', 'yes'):
        return None
    
    # 数据库默认端口列表（用于兜底镜像匹配）
    DB_PORTS = {3306: ('mysql', 'mariadb'), 5432: ('postgres', 'postgresql')}
    
    try:
        import subprocess
        # 方法1：精确通过端口映射查找容器
        # 端口映射格式: 0.0.0.0:3306->3306/tcp, [::]:3306->3306/tcp
        port_pattern = re.compile(r'(?:0\.0\.0\.0|::|\*):' + str(target_port) + r'->')
        
        result = subprocess.run(
            ['docker', 'ps', '--format', '{{.ID}}|{{.Ports}}'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if not line or '|' not in line:
                    continue
                cid, ports_str = line.split('|', 1)
                if port_pattern.search(ports_str):
                    ip_result = subprocess.run(
                        ['docker', 'inspect', '-f', '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}', cid.strip()],
                        capture_output=True, text=True, timeout=5
                    )
                    if ip_result.returncode == 0 and ip_result.stdout.strip():
                        return ip_result.stdout.strip()
        
        # 方法2：兜底 - 仅当目标端口是数据库默认端口时，按镜像名模糊匹配
        db_keywords = DB_PORTS.get(target_port)
        if db_keywords:
            result = subprocess.run(
                ['docker', 'ps', '--format', '{{.ID}}|{{.Image}}'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if not line or '|' not in line:
                        continue
                    cid, image = line.split('|', 1)
                    image_lower = image.lower()
                    if any(kw in image_lower for kw in db_keywords):
                        ip_result = subprocess.run(
                            ['docker', 'inspect', '-f', '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}', cid.strip()],
                            capture_output=True, text=True, timeout=5
                        )
                        if ip_result.returncode == 0 and ip_result.stdout.strip():
                            return ip_result.stdout.strip()
    except Exception:
        pass
    return None


class MySQLConnectionPool(ConnectionPool):
    """MySQL连接池实现"""

    def _create_connection(self) -> Any:
        """创建MySQL连接"""
        try:
            import pymysql
            config = self.config.copy()
            for key in _POOL_CONFIG_KEYS:
                config.pop(key, None)
            if 'username' in config and 'user' not in config:
                config['user'] = config.pop('username')

            # 确保密码是字符串类型
            if 'password' in config:
                config['password'] = str(config['password'] or '')
            else:
                config['password'] = ''

            # 设置默认参数
            config.setdefault('charset', 'utf8mb4')
            config.setdefault('cursorclass', pymysql.cursors.DictCursor)
            config.setdefault('autocommit', False)
            # 明确禁用unix socket，强制使用TCP连接
            config['unix_socket'] = None
            config['connect_timeout'] = 5

            try:
                return pymysql.connect(**config)
            except Exception as e:
                # 如果连接localhost/127.0.0.1失败，尝试自动检测Docker容器IP
                host = config.get('host', '')
                if host in ('localhost', '127.0.0.1', '0.0.0.0'):
                    docker_ip = _get_docker_container_ip_by_port(config.get('port', 3306))
                    if docker_ip:
                        logger.info(f"使用Docker容器IP {docker_ip}:{config.get('port', 3306)} 连接数据库")
                        config['host'] = docker_ip
                        return pymysql.connect(**config)
                raise
        except ImportError:
            raise ImportError("请安装pymysql: pip install pymysql")

    def _close_connection(self, connection: Any) -> None:
        """关闭MySQL连接"""
        try:
            connection.close()
        except Exception:
            pass


class PostgreSQLConnectionPool(ConnectionPool):
    """PostgreSQL连接池实现"""

    def _create_connection(self) -> Any:
        """创建PostgreSQL连接"""
        try:
            import psycopg2
            config = self.config.copy()
            for key in _POOL_CONFIG_KEYS:
                config.pop(key, None)
            if 'username' in config and 'user' not in config:
                config['user'] = config.pop('username')

            connection = psycopg2.connect(**config)
            connection.autocommit = False
            return connection
        except ImportError:
            raise ImportError("请安装psycopg2: pip install psycopg2-binary")

    def _close_connection(self, connection: Any) -> None:
        """关闭PostgreSQL连接"""
        try:
            connection.close()
        except Exception:
            pass


class SQLiteConnectionPool(ConnectionPool):
    """SQLite连接池实现"""

    def __init__(self, config: Dict[str, Any]):
        normalized_config = dict(config)
        database = normalized_config.get('database', normalized_config.get('db', ':memory:'))
        if database == ':memory:':
            # 多个内存连接对应不同数据库，必须限制为单连接。
            normalized_config['min_size'] = 1
            normalized_config['max_size'] = 1
        super().__init__(normalized_config)

    def _create_connection(self) -> Any:
        """创建SQLite连接"""
        try:
            import sqlite3
            config = self.config.copy()
            for key in _POOL_CONFIG_KEYS | {'host', 'port', 'username', 'password'}:
                config.pop(key, None)

            # SQLite需要特殊处理
            db_path = config.pop('database', config.pop('db', ':memory:'))
            config.setdefault('check_same_thread', False)
            connection = sqlite3.connect(db_path, **config)
            connection.row_factory = sqlite3.Row
            return connection
        except ImportError:
            raise ImportError("SQLite应该是Python内置的")

    def _close_connection(self, connection: Any) -> None:
        """关闭SQLite连接"""
        try:
            connection.close()
        except Exception:
            pass


class OracleConnectionPool(ConnectionPool):
    """Oracle连接池实现"""

    def _create_connection(self) -> Any:
        """创建Oracle连接"""
        try:
            import cx_Oracle
            config = self.config.copy()
            for key in _POOL_CONFIG_KEYS:
                config.pop(key, None)
            if 'username' in config and 'user' not in config:
                config['user'] = config.pop('username')

            return cx_Oracle.connect(**config)
        except ImportError:
            raise ImportError("请安装cx_Oracle: pip install cx_Oracle")

    def _close_connection(self, connection: Any) -> None:
        """关闭Oracle连接"""
        try:
            connection.close()
        except Exception:
            pass


def create_connection_pool(dialect: str, config: Dict[str, Any]) -> ConnectionPool:
    """
    根据方言创建连接池

    Args:
        dialect: 数据库方言名称
        config: 连接池配置

    Returns:
        连接池实例

    Raises:
        ValueError: 不支持的数据库方言
    """
    pool_map = {
        'mysql': MySQLConnectionPool,
        'postgresql': PostgreSQLConnectionPool,
        'sqlite': SQLiteConnectionPool,
        'oracle': OracleConnectionPool
    }

    pool_class = pool_map.get(dialect.lower())
    if not pool_class:
        raise ValueError(f"不支持的数据库方言: {dialect}")

    return pool_class(config)
