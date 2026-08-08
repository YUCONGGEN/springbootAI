import logging
import sys
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
        self._logger.setLevel(logging.INFO)

        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)

        self._logger.addHandler(console_handler)
        self._initialized = True

    def get_logger(self) -> logging.Logger:
        return self._logger

    def info(self, message: str) -> None:
        self._logger.info(message)

    def warn(self, message: str) -> None:
        self._logger.warning(message)

    def warning(self, message: str) -> None:
        """Expose the standard-library logging spelling used by framework code."""
        self._logger.warning(message)

    def error(self, message: str) -> None:
        self._logger.error(message)

    def debug(self, message: str) -> None:
        self._logger.debug(message)

    def trace(self, message: str) -> None:
        self._logger.debug(message)

    def set_level(self, level: int) -> None:
        self._logger.setLevel(level)
        for handler in self._logger.handlers:
            handler.setLevel(level)


def get_logger(name: str = "Spring") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    return logger
