"""
Loguru结构化日志模块
提供企业级日志功能
"""
import logging
import sys
import os
import tempfile
from datetime import datetime
from typing import Optional

# 尝试导入loguru，失败则使用标准logging
try:
    from loguru import logger as loguru_logger
    _loguru_available = True
except ImportError:
    _loguru_available = False
    loguru_logger = None


def _format_config_error(config_key: str, config_value, reason: str,
                         suggestions: list = None) -> str:
    """格式化配置错误信息为清晰可读的多行文本。

    统一所有配置校验失败的输出格式，让用户一眼定位是哪个配置项、什么值、
    为什么错、怎么修，而不是看到框架内部 traceback 不知道哪里出问题。

    Args:
        config_key: 配置项名（如 ``logging.log_dir``）
        config_value: 用户配置的值
        reason: 错误原因
        suggestions: 修复建议列表
    """
    lines = [
        "=" * 64,
        f"[配置错误] {config_key} 配置无效",
        "-" * 64,
        f"  配置项: {config_key}",
        f"  配置值: {config_value!r}",
        f"  错误原因: {reason}",
    ]
    if suggestions:
        lines.append("  修复建议:")
        for i, s in enumerate(suggestions, 1):
            lines.append(f"    {i}. {s}")
    lines.append("=" * 64)
    return "\n".join(lines)


class LoggingConfigError(RuntimeError):
    """日志配置校验失败（路径不可创建/不可写入等）。

    继承 RuntimeError 而非直接用 ConfigurationError，避免与 config_loader 的
    循环导入；信息格式由 ``_format_config_error`` 统一。
    """


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

        # 初始化日志配置（import 时用默认 'logs'，strict=False 允许降级保证不崩溃）
        if self._use_loguru:
            self._setup_loguru(strict=False)
        else:
            self._setup_std_logging(strict=False)

    def reconfigure(self, level: Optional[str] = None, log_format: Optional[str] = None,
                    log_dir: Optional[str] = None, retention: Optional[str] = None,
                    rotation: Optional[str] = None) -> None:
        """重新配置日志参数并重建处理器（读取配置后调用）。

        SpringLogger 为单例，``__init__`` 的 ``_initialized`` 守卫会阻止后续 ``__init__``
        更新参数。``init_logging`` 读取 ``application.yml`` 的 ``logging.log_dir`` 后，
        必须通过本方法重新配置，否则日志目录永远停留在默认 ``'logs'``（相对当前工作目录，
        即 Application.py 所在目录/logs）。

        本方法以 **strict 模式** 校验日志目录：用户显式配置的 ``log_dir`` 如果路径
        不合法/不可创建/不可写入，将抛出 ``LoggingConfigError``（含明确错误信息），
        而不是静默降级到默认目录——配置写错必须让用户知道。

        Args:
            level: 日志级别（如 INFO/DEBUG），None 表示保留原值
            log_format: 日志格式，None 表示保留原值
            log_dir: 日志目录，None 表示保留原值
            retention: 日志保留期，None 表示保留原值
            rotation: 日志轮转大小，None 表示保留原值

        Raises:
            LoggingConfigError: 日志目录不可创建或不可写入（strict 模式）
        """
        if level is not None:
            self.level = level.upper()
        if log_format is not None:
            self.log_format = log_format
        # 记录是否是用户显式配置了 log_dir：只有显式配置才 strict 校验，
        # 保留旧值（log_dir=None）时用非严格模式，避免默认 'logs' 在只读 CWD 报错
        log_dir_explicitly_set = log_dir is not None
        if log_dir_explicitly_set:
            self.log_dir = log_dir
        if retention is not None:
            self.retention = retention
        if rotation is not None:
            self.rotation = rotation
        # 重建日志处理器：用户显式配置 log_dir 时 strict=True（路径错必须报错），
        # 否则 strict=False（保留旧值/默认值时允许降级）
        strict_mode = log_dir_explicitly_set
        if self._use_loguru:
            self._setup_loguru(strict=strict_mode)
        else:
            self._setup_std_logging(strict=strict_mode)

    def _validate_log_dir(self, strict: bool) -> bool:
        """校验日志目录可创建且可写入。

        ``strict=True``（用户配置生效路径）：校验失败抛 ``LoggingConfigError``，
        错误信息含配置项名、配置值、具体 errno 原因、修复建议。
        ``strict=False``（import 时默认配置）：校验失败仅 warning 并返回 False，
        保证 import 不崩溃。

        Args:
            strict: 是否严格模式（True=报错，False=降级）

        Returns:
            True 表示目录可用，False 表示不可用（仅 strict=False 时返回）

        Raises:
            LoggingConfigError: strict=True 且目录不可用时
        """
        suggestions = [
            "检查路径拼写是否正确",
            "确认父目录存在且有写权限",
            "使用绝对路径避免工作目录歧义",
            "Windows 路径用双反斜杠或正斜杠: \"C:/Users/xxx/logs\"",
        ]

        # 1. 空值校验
        if not self.log_dir or not str(self.log_dir).strip():
            msg = _format_config_error(
                'logging.log_dir', self.log_dir,
                '日志目录为空字符串，无法创建', suggestions)
            if strict:
                raise LoggingConfigError(msg)
            print(f"[WARNING] {msg}", file=sys.stderr)
            return False

        log_dir = str(self.log_dir).strip()

        # 2. 尝试创建目录（捕获所有 OSError 子类：PermissionError/FileNotFoundError 等）
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError as exc:
            # 根据 errno 给出具体原因
            import errno
            if exc.errno == errno.EACCES:
                reason = f"无写权限（Permission denied）: {exc}"
            elif exc.errno == errno.ENOENT:
                reason = f"父目录不存在且无法创建: {exc}"
            elif exc.errno == errno.ENOTDIR:
                reason = f"路径中某一段不是目录（可能是文件）: {exc}"
            elif exc.errno == errno.EROFS:
                reason = f"只读文件系统: {exc}"
            else:
                reason = f"{type(exc).__name__} (errno={exc.errno}): {exc}"
            msg = _format_config_error(
                'logging.log_dir', self.log_dir, reason, suggestions)
            if strict:
                raise LoggingConfigError(msg) from exc
            print(f"[WARNING] {msg}", file=sys.stderr)
            return False

        # 3. 测试可写入（创建临时文件后删除）
        test_file = os.path.join(log_dir, f".spring_write_test_{os.getpid()}")
        try:
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write("write permission test")
            os.remove(test_file)
        except OSError as exc:
            import errno
            if exc.errno == errno.EACCES:
                reason = f"目录已创建但无写权限: {exc}"
            else:
                reason = f"目录已创建但无法写入文件: {type(exc).__name__}: {exc}"
            msg = _format_config_error(
                'logging.log_dir', self.log_dir, reason, suggestions)
            if strict:
                raise LoggingConfigError(msg) from exc
            print(f"[WARNING] {msg}", file=sys.stderr)
            return False

        return True

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
    
    def _setup_loguru(self, strict: bool = False):
        """配置Loguru。

        Args:
            strict: True 时日志目录校验失败抛 ``LoggingConfigError``（用户配置路径）；
                    False 时降级为仅控制台日志（import 时默认配置，保证不崩溃）
        """
        # 清除默认处理器
        loguru_logger.remove()

        # 添加控制台输出（始终启用，确保错误信息至少能打印到控制台）
        loguru_logger.add(
            sys.stdout,
            format=self.log_format,
            level=self.level,
            colorize=True,
        )

        # 校验日志目录：strict 模式下失败会抛异常（由 reconfigure 捕获并输出），
        # 非 strict 模式下返回 False 则仅使用控制台日志
        if not self._validate_log_dir(strict=strict):
            return

        # 添加文件输出（按日期轮转）
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

    def _setup_std_logging(self, strict: bool = False):
        """配置标准logging（fallback）。

        Args:
            strict: True 时日志目录校验失败抛 ``LoggingConfigError``；
                    False 时降级为仅控制台日志（import 时保证不崩溃）
        """
        self._logger = logging.getLogger("Spring")
        self._logger.setLevel(getattr(logging, self.level))
        # 清除旧 handler（reconfigure 重建时避免重复 add 导致日志重复输出）
        for handler in list(self._logger.handlers):
            self._logger.removeHandler(handler)

        # 添加控制台输出（始终启用）
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(self.log_format))
        self._logger.addHandler(console_handler)

        # 校验日志目录
        if not self._validate_log_dir(strict=strict):
            return

        # 添加文件输出
        file_handler = logging.FileHandler(
            os.path.join(self.log_dir, "application.log"),
            encoding="utf-8"
        )
        file_handler.setFormatter(logging.Formatter(self.log_format))
        self._logger.addHandler(file_handler)
    
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

    如果用户配置的 ``log_dir`` 路径不合法/不可创建/不可写入，``reconfigure`` 会抛出
    ``LoggingConfigError``。本函数捕获后打印明确错误横幅到 stderr（确保用户看到），
    然后重新抛出，让上层 fail-fast 终止启动——配置写错必须让用户知道，而不是静默
    降级到默认目录。

    Args:
        config: 配置字典（logging 子字典），包含 level/log_dir/retention/rotation 等

    Raises:
        LoggingConfigError: 日志目录配置无效（路径不合法/不可创建/不可写入）
    """
    global spring_logger
    try:
        spring_logger.reconfigure(
            level=config.get('level'),
            log_format=config.get('log_format'),
            log_dir=config.get('log_dir'),
            retention=config.get('retention'),
            rotation=config.get('rotation'),
        )
    except LoggingConfigError as e:
        # 只打印格式化的错误信息（含配置项/值/原因/建议），不输出框架 traceback
        print(f"\n{e}\n", file=sys.stderr)
        raise


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