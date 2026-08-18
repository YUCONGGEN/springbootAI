"""
Loguru结构化日志模块
提供企业级日志功能
"""
import logging
import sys
import os
import re
from typing import Optional

# 尝试导入loguru，失败则使用标准logging
try:
    from loguru import logger as loguru_logger
    _loguru_available = True
except ImportError:
    _loguru_available = False
    loguru_logger = None


# ---------------------------------------------------------------------------
# LoguruHandler：将标准 logging 日志转发到 Loguru
# 必须定义在 SpringLogger 之前，因为 _setup_loguru / _intercept_third_party_loggers
# 需要引用它来拦截 Uvicorn/Starlette/FastAPI 的标准 logging 输出。
# ---------------------------------------------------------------------------
if _loguru_available:
    class LoguruHandler(logging.Handler):
        """将标准 logging 日志转发到 Loguru 的处理器。

        Uvicorn/Starlette/FastAPI 使用标准 ``logging`` 模块输出日志，
        默认配置了各自的 StreamHandler 且 ``propagate=False``，
        导致日志只输出到控制台、不经过 Loguru 的文件 handler。
        本处理器替换它们的 StreamHandler，使日志统一写入配置的日志文件。
        """

        def emit(self, record: logging.LogRecord):
            """将 LogRecord 转发到 loguru。"""
            try:
                # 将标准 logging 级名映射到 loguru 级名
                level = self._resolve_loguru_level(record)
                # ``uvicorn.access`` 保持 DEBUG 是为了让原始 INFO 的 4xx/5xx
                # 有机会被重新分级。适配器入口也执行阈值判断，避免额外的
                # INFO sink 将已配置为 WARNING 的 200 响应再次输出。
                if self._is_below_configured_threshold(level):
                    return
                # 标准 logging 会经由 Logger/Handler 等包装层才到达这里。
                # 依据 LogRecord 回溯真实调用帧，避免日志总显示为 emit 的行号。
                depth = self._resolve_caller_depth(record)
                message = record.getMessage()
                logger = loguru_logger.bind(name=record.name)
                if record.exc_info:
                    logger.opt(depth=depth, exception=record.exc_info).log(level, message)
                else:
                    logger.opt(depth=depth).log(level, message)
            except Exception:
                self.handleError(record)

        @staticmethod
        def _resolve_loguru_level(record: logging.LogRecord) -> str:
            """按 Uvicorn 访问状态码映射为实际的日志严重级别。"""
            if record.name == "uvicorn.access":
                match = re.search(r"\s([1-5]\d{2})(?:\s|$)", record.getMessage())
                if match:
                    status_code = int(match.group(1))
                    if 400 <= status_code < 500:
                        return "WARNING"
                    if 500 <= status_code < 600:
                        return "ERROR"
            try:
                return loguru_logger.level(record.levelname).name
            except (ValueError, TypeError):
                return record.levelname.upper()

        @staticmethod
        def _is_below_configured_threshold(level: str) -> bool:
            """判断标准 logging 转发记录是否低于当前框架日志阈值。"""
            configured_logger = globals().get("spring_logger")
            configured_name = getattr(configured_logger, "level", "INFO")
            configured_name = _LOG_LEVEL_ALIASES.get(
                str(configured_name).upper(), str(configured_name).upper()
            )
            level_no = logging._nameToLevel.get(level.upper(), logging.INFO)
            configured_no = logging._nameToLevel.get(configured_name, logging.INFO)
            return level_no < configured_no

        @staticmethod
        def _resolve_caller_depth(record: logging.LogRecord) -> int:
            """返回指向原始 logging 调用方的 Loguru depth。"""
            try:
                target_path = os.path.normcase(os.path.abspath(record.pathname))
                frame = sys._getframe(1)  # 当前为 LoguruHandler.emit 调用帧。
                depth = 0
                while frame is not None and depth < 64:
                    frame_path = os.path.normcase(os.path.abspath(frame.f_code.co_filename))
                    if frame_path == target_path and frame.f_code.co_name == record.funcName:
                        return depth
                    frame = frame.f_back
                    depth += 1
            except (AttributeError, OSError, ValueError):
                pass
            return 0

    # 将 root logger 的日志也转发到 Loguru（兼容未拦截的第三方库）
    logging.basicConfig(handlers=[LoguruHandler()], level=logging.INFO)
else:
    LoguruHandler = None


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


# 兼容标准 logging、Log4j 与 Spring Boot 中常见的日志等级别名。
_LOG_LEVEL_ALIASES = {"WARN": "WARNING", "FATAL": "CRITICAL"}
_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


def _normalize_logging_level(level) -> str:
    """将日志配置规范为 Loguru 和标准 logging 都能识别的等级。"""
    if isinstance(level, dict):
        level = level.get("root") or next(
            (value for value in level.values() if isinstance(value, str)), "INFO"
        )
    if not isinstance(level, str):
        raise LoggingConfigError(_format_config_error(
            "logging.level", level, "日志等级必须是字符串",
            ["使用 DEBUG、INFO、WARNING、ERROR 或 CRITICAL", "WARN 可作为 WARNING 的兼容写法"],
        ))
    normalized = _LOG_LEVEL_ALIASES.get(level.strip().upper(), level.strip().upper())
    if normalized not in _VALID_LOG_LEVELS:
        raise LoggingConfigError(_format_config_error(
            "logging.level", level, f"不支持的日志等级: {level!r}",
            ["使用 DEBUG、INFO、WARNING、ERROR 或 CRITICAL", "WARN 可作为 WARNING 的兼容写法"],
        ))
    return normalized


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
        # 兼容 dict 格式的 level（Spring Boot 风格）
        self.level = _normalize_logging_level(level)
        self.log_dir = log_dir
        self.retention = retention
        self.rotation = rotation
        self._initialized = True
        self._use_loguru = _loguru_available
        self.log_format = log_format or self._default_format()

        # import 时只设置控制台输出，不创建文件 handler（不创建 logs/ 目录）。
        # 文件 handler 在 init_logging → reconfigure 读取用户配置后创建，
        # 避免在 CWD 下提前生成 logs/ 目录与用户配置的 log_dir 产生双份日志。
        if self._use_loguru:
            loguru_logger.remove()
            loguru_logger.add(
                sys.stdout,
                format=self.log_format,
                level=self.level,
                colorize=True,
                backtrace=True,
                diagnose=True,
            )
        else:
            self._setup_std_logging(strict=False, enable_file=False)

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
            # 兼容两种配置格式：
            # 1) 字符串：logging.level: INFO
            # 2) dict（Spring Boot 风格）：logging.level: {root: INFO, spring: DEBUG}
            self.level = _normalize_logging_level(level)
        if log_format is not None:
            self.log_format = log_format
        # 记录是否是用户显式配置了 log_dir：
        # - 有值 → strict 校验 + 创建文件 handler（日志写入用户指定目录）
        # - None（未配置）→ 不创建文件 handler，只有控制台输出
        log_dir_explicitly_set = log_dir is not None and str(log_dir).strip() != ''
        if log_dir_explicitly_set:
            self.log_dir = log_dir
        if retention is not None:
            self.retention = retention
        if rotation is not None:
            self.rotation = rotation
        # 重建日志处理器：
        # - 用户显式配置 log_dir → strict=True + enable_file=True（路径错必须报错）
        # - 用户未配置 log_dir → strict=False + enable_file=False（只有控制台，不创建文件）
        strict_mode = log_dir_explicitly_set
        enable_file = log_dir_explicitly_set
        if self._use_loguru:
            self._setup_loguru(strict=strict_mode, enable_file=enable_file)
        else:
            self._setup_std_logging(strict=strict_mode, enable_file=enable_file)

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
                "<cyan>{name}</cyan> | <cyan>{file.path}</cyan>:"
                "<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                "<level>{message}</level>"
            )
        return "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
    
    def _setup_loguru(self, strict: bool = False, enable_file: bool = True):
        """配置Loguru。

        Args:
            strict: True 时日志目录校验失败抛 ``LoggingConfigError``（用户配置路径）；
                    False 时降级为仅控制台日志（import 时默认配置，保证不崩溃）
            enable_file: True 时添加文件 handler（创建日志目录+文件）；
                         False 时仅控制台输出（import 时避免提前创建 logs/ 目录）
        """
        # 清除默认处理器
        loguru_logger.remove()

        # 添加控制台输出（始终启用，确保错误信息至少能打印到控制台）
        loguru_logger.add(
            sys.stdout,
            format=self.log_format,
            level=self.level,
            colorize=True,
            backtrace=True,
            diagnose=True,
        )

        # enable_file=False 时只输出到控制台（import 时使用，不创建 logs/ 目录）
        self._configure_stdlib_forwarding()
        if not enable_file:
            # 仅控制台输出时也必须统一接管 Web 访问日志。
            self._intercept_third_party_loggers()
            return

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
            backtrace=True,
            diagnose=True,
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
            backtrace=True,
            diagnose=True,
        )

        # 拦截 Uvicorn/Starlette/FastAPI 的标准 logging，转发到 Loguru
        # 使访问日志（GET /api/xxx 200 OK）和启动日志也写入日志文件
        self._intercept_third_party_loggers()

    def _configure_stdlib_forwarding(self) -> None:
        """让标准库 logging 记录也经过同一套配置级别过滤。"""
        configured_level = getattr(logging, self.level, logging.INFO)
        root_logger = logging.getLogger()
        root_logger.setLevel(configured_level)

        # 模块导入时由 ``basicConfig`` 注册；若被第三方清除则在启动时补回。
        if not any(isinstance(handler, LoguruHandler) for handler in root_logger.handlers):
            root_logger.addHandler(LoguruHandler())

        # utils.logger 曾单独持有 INFO 控制台处理器，既会绕过配置级别，
        # 又会和根 LoguruHandler 的转发结果重复输出。
        spring_stdlib_logger = logging.getLogger("Spring")
        for handler in list(spring_stdlib_logger.handlers):
            spring_stdlib_logger.removeHandler(handler)
            handler.close()
        spring_stdlib_logger.setLevel(configured_level)
        spring_stdlib_logger.propagate = True

    def _intercept_third_party_loggers(self):
        """拦截第三方库（Uvicorn/Starlette/FastAPI）的标准 logging，转发到 Loguru。

        Uvicorn 默认 LOGGING_CONFIG 为 ``uvicorn`` 和 ``uvicorn.access`` logger
        配置了各自的 StreamHandler 且 ``propagate=False``，导致：

        1. 访问日志（``GET /api/xxx 200 OK``）只输出到控制台，不写入日志文件
        2. 启动/关闭日志（``Started server process``、``Application startup complete``）同理

        本方法移除这些 logger 的 StreamHandler，替换为 ``LoguruHandler``，
        使其日志统一通过 Loguru 输出（含控制台 + 文件）。

        配合 ``WebApplicationContext.run()`` 传 ``log_config=None`` 给 Uvicorn，
        防止 Uvicorn 启动时重新添加 StreamHandler 覆盖本拦截。

        拦截的 logger：
        - ``uvicorn`` — 服务器启动/关闭日志
        - ``uvicorn.error`` — 服务器错误日志
        - ``uvicorn.access`` — HTTP 访问日志（请求方法/路径/状态码）
        - ``fastapi`` — FastAPI 框架日志
        - ``starlette`` — Starlette ASGI 框架日志
        """
        if not self._use_loguru or LoguruHandler is None:
            # 非 loguru 模式：让第三方 logger 传播到 root（root 有 Spring logger 的 handler）
            for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access',
                         'fastapi', 'starlette'):
                logging.getLogger(name).propagate = True
            return

        for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access',
                     'fastapi', 'starlette'):
            third_party_logger = logging.getLogger(name)
            # 移除原有 handler（Uvicorn 的 StreamHandler），避免控制台重复输出
            third_party_logger.handlers.clear()
            # 添加 LoguruHandler 转发到 loguru（统一控制台 + 文件输出）
            third_party_logger.addHandler(LoguruHandler())
            # 不传播到 root（root 也有 LoguruHandler，避免重复转发）
            third_party_logger.propagate = False
            # ``uvicorn.access`` 原始会将所有响应写为 INFO。必须先进入
            # Loguru，才能按状态码提升 4xx/5xx 后再套用配置阈值。
            if name == 'uvicorn.access':
                third_party_logger.setLevel(logging.DEBUG)

    def _setup_std_logging(self, strict: bool = False, enable_file: bool = True):
        """配置标准logging（fallback）。

        Args:
            strict: True 时日志目录校验失败抛 ``LoggingConfigError``；
                    False 时降级为仅控制台日志（import 时保证不崩溃）
            enable_file: True 时添加文件 handler；False 时仅控制台输出
                         （import 时避免提前创建 logs/ 目录）
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

        # enable_file=False 时只输出到控制台
        if not enable_file:
            return

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
            loguru_logger.opt(depth=1).info(message, **kwargs)
        else:
            self._logger.info(message)
    
    def debug(self, message: str, **kwargs):
        """记录DEBUG级别日志"""
        if self._use_loguru:
            loguru_logger.opt(depth=1).debug(message, **kwargs)
        else:
            self._logger.debug(message)
    
    def warning(self, message: str, **kwargs):
        """记录WARNING级别日志"""
        if self._use_loguru:
            loguru_logger.opt(depth=1).warning(message, **kwargs)
        else:
            self._logger.warning(message)
    
    def error(self, message: str, **kwargs):
        """记录ERROR级别日志"""
        if self._use_loguru:
            loguru_logger.opt(depth=1).error(message, **kwargs)
        else:
            self._logger.error(message)
    
    def critical(self, message: str, **kwargs):
        """记录CRITICAL级别日志"""
        if self._use_loguru:
            loguru_logger.opt(depth=1).critical(message, **kwargs)
        else:
            self._logger.critical(message)
    
    def exception(self, message: str, **kwargs):
        """记录异常日志"""
        if self._use_loguru:
            loguru_logger.opt(depth=1, exception=True).error(message, **kwargs)
        else:
            self._logger.exception(message)
    
    def log(self, level: str, message: str, **kwargs):
        """记录指定级别日志"""
        if self._use_loguru:
            loguru_logger.opt(depth=1).log(level.upper(), message, **kwargs)
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

    行为说明：
    - 用户**配置了** ``log_dir`` → 控制台 + 日志文件（strict 校验路径，错则抛异常）
    - 用户**未配置** ``log_dir`` → **仅控制台输出**，不创建日志文件
    - 用户配置的 ``log_dir`` 路径不合法/不可创建/不可写入 → 抛 ``LoggingConfigError``

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
