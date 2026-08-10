"""
Loguru结构化日志模块
提供企业级日志功能
"""
import logging
import sys
import os
from datetime import datetime
from typing import Optional

# 尝试导入loguru，失败则使用标准logging
try:
    from loguru import logger as loguru_logger
    _loguru_available = True
except ImportError:
    _loguru_available = False
    loguru_logger = None


class SpringLogger:
    """Spring日志管理器"""
    
    _instance = None
    _lock = __import__('threading').Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, level: str = "INFO", log_format: str = None, 
                 log_dir: str = "logs", retention: str = "30 days", 
                 rotation: str = "100 MB"):
        if hasattr(self, '_initialized'):
            return
        self.level = level.upper()
        self.log_dir = log_dir
        self.retention = retention
        self.rotation = rotation
        self._initialized = True
        self._use_loguru = _loguru_available
        self.log_format = log_format or self._default_format()
        
        # 初始化日志配置
        if self._use_loguru:
            self._setup_loguru()
        else:
            self._setup_std_logging()
    
    def reconfigure(self, level: Optional[str] = None, log_format: Optional[str] = None,
                    log_dir: Optional[str] = None, retention: Optional[str] = None,
                    rotation: Optional[str] = None) -> None:
        """重新配置日志参数并重建处理器（读取配置后调用）。

        SpringLogger 为单例，``__init__`` 的 ``_initialized`` 守卫会阻止后续 ``__init__``
        更新参数。``init_logging`` 读取 ``application.yml`` 的 ``logging.log_dir`` 后，
        必须通过本方法重新配置，否则日志目录永远停留在默认 ``'logs'``（相对当前工作目录，
        即 Application.py 所在目录/logs）。

        Args:
            level: 日志级别（如 INFO/DEBUG），None 表示保留原值
            log_format: 日志格式，None 表示保留原值
            log_dir: 日志目录，None 表示保留原值
            retention: 日志保留期，None 表示保留原值
            rotation: 日志轮转大小，None 表示保留原值
        """
        if level is not None:
            self.level = level.upper()
        if log_format is not None:
            self.log_format = log_format
        if log_dir is not None:
            self.log_dir = log_dir
        if retention is not None:
            self.retention = retention
        if rotation is not None:
            self.rotation = rotation
        # 重建日志处理器（_setup_loguru 会 loguru_logger.remove() 清除旧 handler；
        # _setup_std_logging 已清除旧 handler，避免重复 add）
        if self._use_loguru:
            self._setup_loguru()
        else:
            self._setup_std_logging()

    def _default_format(self) -> str:
        """默认日志格式"""
        if self._use_loguru:
            return (
                "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                "<level>{message}</level>"
            )
        return "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
    
    def _setup_loguru(self):
        """配置Loguru"""
        # 清除默认处理器
        loguru_logger.remove()
        
        # 添加控制台输出
        loguru_logger.add(
            sys.stdout,
            format=self.log_format,
            level=self.level,
            colorize=True,
        )
        
        # 添加文件输出（按日期轮转）
        # 创建日志目录，失败则优雅降级（仅控制台日志），保证 import 永不因权限问题崩溃
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            loguru_logger.add(
                os.path.join(self.log_dir, "application_{time:YYYY-MM-DD}.log"),
                format=self.log_format,
                level=self.level,
                rotation=self.rotation,
                retention=self.retention,
                compression="zip",
                encoding="utf-8",
            )
            # 添加错误日志单独输出
            loguru_logger.add(
                os.path.join(self.log_dir, "error_{time:YYYY-MM-DD}.log"),
                format=self.log_format,
                level="ERROR",
                rotation=self.rotation,
                retention=self.retention,
                compression="zip",
                encoding="utf-8",
            )
        except (PermissionError, OSError) as exc:
            # 当前工作目录无写权限（如系统目录/只读位置），降级为仅控制台日志
            loguru_logger.warning(
                f"无法创建日志目录 {self.log_dir!r}，文件日志已禁用，仅使用控制台日志: {exc}"
            )
    
    def _setup_std_logging(self):
        """配置标准logging（fallback）"""
        self._logger = logging.getLogger("Spring")
        self._logger.setLevel(getattr(logging, self.level))
        # 清除旧 handler（reconfigure 重建时避免重复 add 导致日志重复输出）
        for handler in list(self._logger.handlers):
            self._logger.removeHandler(handler)

        # 添加控制台输出（始终启用）
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(self.log_format))
        self._logger.addHandler(console_handler)

        # 添加文件输出：目录创建失败则优雅降级，保证 import 永不崩溃
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            file_handler = logging.FileHandler(
                os.path.join(self.log_dir, "application.log"),
                encoding="utf-8"
            )
            file_handler.setFormatter(logging.Formatter(self.log_format))
            self._logger.addHandler(file_handler)
        except (PermissionError, OSError) as exc:
            self._logger.warning(
                f"无法创建日志目录 {self.log_dir!r}，文件日志已禁用，仅使用控制台日志: {exc}"
            )
    
    def get_logger(self):
        """获取日志实例"""
        if self._use_loguru:
            return loguru_logger
        return self._logger
    
    def info(self, message: str, **kwargs):
        """记录INFO级别日志"""
        if self._use_loguru:
            loguru_logger.info(message, **kwargs)
        else:
            self._logger.info(message)
    
    def debug(self, message: str, **kwargs):
        """记录DEBUG级别日志"""
        if self._use_loguru:
            loguru_logger.debug(message, **kwargs)
        else:
            self._logger.debug(message)
    
    def warning(self, message: str, **kwargs):
        """记录WARNING级别日志"""
        if self._use_loguru:
            loguru_logger.warning(message, **kwargs)
        else:
            self._logger.warning(message)
    
    def error(self, message: str, **kwargs):
        """记录ERROR级别日志"""
        if self._use_loguru:
            loguru_logger.error(message, **kwargs)
        else:
            self._logger.error(message)
    
    def critical(self, message: str, **kwargs):
        """记录CRITICAL级别日志"""
        if self._use_loguru:
            loguru_logger.critical(message, **kwargs)
        else:
            self._logger.critical(message)
    
    def exception(self, message: str, **kwargs):
        """记录异常日志"""
        if self._use_loguru:
            loguru_logger.exception(message, **kwargs)
        else:
            self._logger.exception(message)
    
    def log(self, level: str, message: str, **kwargs):
        """记录指定级别日志"""
        if self._use_loguru:
            loguru_logger.log(level.upper(), message, **kwargs)
        else:
            self._logger.log(getattr(logging, level.upper()), message)
    
    def bind(self, **extra):
        """绑定额外字段到日志上下文"""
        if self._use_loguru:
            return loguru_logger.bind(**extra)
        return self._logger
    
    def patch(self, function):
        """添加额外字段到日志消息"""
        if self._use_loguru:
            return loguru_logger.patch(function)
        return self._logger


# 创建全局日志管理器实例
spring_logger = SpringLogger()


def init_logging(config: dict) -> None:
    """初始化日志配置（读取 application.yml 的 logging 段后调用）。

    通过 ``reconfigure`` 重新配置单例 SpringLogger，使 ``logging.log_dir`` / ``level``
    等配置生效。直接 ``SpringLogger(log_dir=...)`` 因单例 ``_initialized`` 守卫不会更新参数。

    Args:
        config: 配置字典（logging 子字典），包含 level/log_dir/retention/rotation 等
    """
    global spring_logger
    spring_logger.reconfigure(
        level=config.get('level'),
        log_format=config.get('log_format'),
        log_dir=config.get('log_dir'),
        retention=config.get('retention'),
        rotation=config.get('rotation'),
    )


# 兼容标准logging模块
if _loguru_available:
    class LoguruHandler(logging.Handler):
        """Loguru处理器，用于将标准logging日志转发到Loguru"""
        
        def emit(self, record: logging.LogRecord):
            """处理日志记录"""
            try:
                level = loguru_logger.level(record.levelname).name
                message = self.format(record)
                loguru_logger.log(level, message)
            except Exception:
                self.handleError(record)
    
    # 将标准logging日志转发到Loguru
    logging.basicConfig(handlers=[LoguruHandler()], level=logging.INFO)