import logging
from typing import Optional


class SpringLogger:
    _instance: Optional['SpringLogger'] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, '_initialized', False):
            return

        self._logger = logging.getLogger("Spring")
        # 输出由 ``init_logging`` 集中配置；本地 INFO handler 会绕过
        # 配置阈值，并与根日志处理器造成重复输出。
        self._logger.setLevel(logging.NOTSET)
        self._logger.propagate = True
        self._initialized = True

    def get_logger(self) -> logging.Logger:
        return self._logger

    def info(self, message: str) -> None:
        self._logger.info(message, stacklevel=2)

    def warn(self, message: str) -> None:
        self._logger.warning(message, stacklevel=2)

    def warning(self, message: str) -> None:
        """Expose the standard-library logging spelling used by framework code."""
        self._logger.warning(message, stacklevel=2)

    def error(self, message: str) -> None:
        self._logger.error(message, stacklevel=2)

    def debug(self, message: str) -> None:
        self._logger.debug(message, stacklevel=2)

    def trace(self, message: str) -> None:
        self._logger.debug(message, stacklevel=2)

    def set_level(self, level: int) -> None:
        self._logger.setLevel(level)
        for handler in self._logger.handlers:
            handler.setLevel(level)


def get_logger(name: str = "Spring") -> logging.Logger:
    logger = logging.getLogger(name)
    # 命名 logger 只负责产生记录，由根处理器为框架和业务代码统一过滤。
    logger.setLevel(logging.NOTSET)
    logger.propagate = True
    return logger
