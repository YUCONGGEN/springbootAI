"""日志配置测试：验证 init_logging / reconfigure 使 logging.log_dir 等配置生效。

回归场景：SpringLogger 为单例，``__init__`` 的 ``_initialized`` 守卫会阻止后续
``SpringLogger(log_dir=...)`` 更新参数，导致 ``init_logging`` 读取 application.yml 的
``logging.log_dir`` 后日志目录仍停留在默认 ``'logs'``（相对当前工作目录，即 Application.py
所在目录/logs）。修复后 ``init_logging`` 通过 ``reconfigure`` 重新配置单例。

严格校验场景：用户显式配置的 log_dir 路径不合法/不可创建/不可写入时，必须抛出
``LoggingConfigError``（含明确错误信息），而不是静默降级到默认目录。
"""
import glob
import os
import time

import pytest

from spring.logging.loguru_logger import (
    init_logging, spring_logger, LoggingConfigError, SpringLogger, LoguruHandler,
)


class TestLoggingConfig:
    """init_logging / reconfigure 配置生效测试"""

    def test_init_logging_updates_log_dir(self, tmp_path):
        """init_logging 传入 log_dir 后，单例 log_dir 应更新为配置值（核心回归点）"""
        custom = str(tmp_path / "custom_logs")
        init_logging({"level": "INFO", "log_dir": custom})
        assert spring_logger.log_dir == custom

    def test_reconfigure_updates_log_dir(self, tmp_path):
        """reconfigure 直接更新 log_dir"""
        custom = str(tmp_path / "reconfigure_logs")
        spring_logger.reconfigure(log_dir=custom)
        assert spring_logger.log_dir == custom

    def test_init_logging_writes_log_to_configured_dir(self, tmp_path):
        """init_logging 后日志文件应实际写到配置的 log_dir（端到端验证）"""
        custom = str(tmp_path / "write_logs")
        init_logging({"level": "INFO", "log_dir": custom})
        spring_logger.info("test message for configured log_dir")
        # loguru 文件 sink 同步写入，留少量缓冲确保落盘
        time.sleep(0.3)
        log_files = glob.glob(os.path.join(custom, "*.log"))
        assert len(log_files) > 0, f"期望日志文件出现在 {custom}，实际: {log_files}"

    def test_reconfigure_preserves_unspecified_values(self, tmp_path):
        """reconfigure 未传的参数应保留原值（None 不覆盖）"""
        custom = str(tmp_path / "preserve_logs")
        spring_logger.reconfigure(log_dir=custom, level="DEBUG")
        assert spring_logger.log_dir == custom
        assert spring_logger.level == "DEBUG"
        old_retention = spring_logger.retention
        # 只传 level，不传 log_dir/retention
        spring_logger.reconfigure(level="INFO")
        assert spring_logger.log_dir == custom  # 保留
        assert spring_logger.retention == old_retention  # 保留
        assert spring_logger.level == "INFO"  # 更新

    def test_init_logging_empty_config_preserves_log_dir(self, tmp_path):
        """init_logging({}) 不传 log_dir 时，保留当前 log_dir（不重置为默认 'logs'）"""
        custom = str(tmp_path / "empty_config_logs")
        spring_logger.reconfigure(log_dir=custom)
        init_logging({})  # 空 config，log_dir 为 None
        assert spring_logger.log_dir == custom  # 保留，不重置为 'logs'

    def test_init_logging_updates_level(self, tmp_path):
        """init_logging 传入 level 后，单例 level 应更新"""
        init_logging({"level": "WARNING", "log_dir": str(tmp_path / "level_logs")})
        assert spring_logger.level == "WARNING"
        # 恢复 INFO 避免影响后续测试
        spring_logger.reconfigure(level="INFO")


class TestLogDirStrictValidation:
    """用户显式配置 log_dir 时，路径错误必须报错而非静默降级。"""

    def test_invalid_path_raises_error(self, tmp_path):
        """路径穿过一个文件（无法创建目录）应抛 LoggingConfigError。"""
        # 先创建一个文件，然后尝试在其下创建子目录（ENOTDIR）
        blocker = tmp_path / "blocker_file"
        blocker.write_text("I am a file", encoding="utf-8")
        bad_path = str(blocker / "subdir" / "logs")
        with pytest.raises(LoggingConfigError) as exc_info:
            init_logging({"level": "INFO", "log_dir": bad_path})
        # 错误信息应包含配置项名和配置值（用子串避免 repr 转义反斜杠）
        msg = str(exc_info.value)
        assert "logging.log_dir" in msg
        assert "blocker_file" in msg

    def test_empty_string_log_dir_no_file_output(self, tmp_path):
        """空字符串 log_dir 视为未配置，只有控制台输出，不创建文件、不抛异常。"""
        # 不应抛 LoggingConfigError（空字符串 = 未配置 = 仅控制台）
        init_logging({"level": "INFO", "log_dir": ""})

    def test_no_log_dir_means_console_only(self, tmp_path):
        """不配置 log_dir 时只有控制台输出，不创建任何日志文件。"""
        import os
        original_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            init_logging({"level": "INFO"})  # 没有 log_dir 键
            spring_logger.info("console only message")
            time.sleep(0.2)
            # 不应创建 logs/ 目录或任何 .log 文件
            assert not (tmp_path / 'logs').exists(), "未配置 log_dir 时不应创建 logs/ 目录"
            log_files = glob.glob(str(tmp_path / "*.log"))
            assert len(log_files) == 0, f"未配置 log_dir 时不应创建日志文件，实际: {log_files}"
        finally:
            os.chdir(original_cwd)

    def test_file_path_not_directory_raises(self, tmp_path):
        """log_dir 指向一个已存在的文件（非目录）应抛 LoggingConfigError。"""
        file_path = tmp_path / "a_file_not_dir"
        file_path.write_text("I am a file", encoding="utf-8")
        with pytest.raises(LoggingConfigError):
            init_logging({"level": "INFO", "log_dir": str(file_path)})

    def test_error_message_contains_suggestions(self, tmp_path):
        """错误信息应包含修复建议，让用户知道怎么修。"""
        blocker = tmp_path / "suggestion_blocker"
        blocker.write_text("file", encoding="utf-8")
        bad_path = str(blocker / "logs")
        with pytest.raises(LoggingConfigError) as exc_info:
            init_logging({"level": "INFO", "log_dir": bad_path})
        msg = str(exc_info.value)
        assert "修复建议" in msg
        assert "检查路径拼写" in msg

    def test_valid_path_does_not_raise(self, tmp_path):
        """合法路径不应抛异常，且日志文件应写入该目录。"""
        valid_path = str(tmp_path / "valid_strict_logs")
        init_logging({"level": "INFO", "log_dir": valid_path})
        assert spring_logger.log_dir == valid_path
        spring_logger.info("strict validation test message")
        time.sleep(0.3)
        log_files = glob.glob(os.path.join(valid_path, "*.log"))
        assert len(log_files) > 0

    def test_non_strict_mode_for_default_log_dir(self, tmp_path):
        """init_logging({}) 不传 log_dir 时（保留旧值），不应因默认 logs 目录报错。"""
        # 先设一个有效目录
        valid = str(tmp_path / "preset_logs")
        init_logging({"level": "INFO", "log_dir": valid})
        # 再传空配置（log_dir=None → 保留旧值，非 strict 模式）
        init_logging({})  # 不应抛异常
        assert spring_logger.log_dir == valid

    def test_reconfigure_explicit_log_dir_strict(self, tmp_path):
        """reconfigure 显式传 log_dir 时走 strict 模式。"""
        blocker = tmp_path / "reconfigure_blocker"
        blocker.write_text("file", encoding="utf-8")
        bad_path = str(blocker / "deep" / "path")
        with pytest.raises(LoggingConfigError):
            spring_logger.reconfigure(log_dir=bad_path)

    def test_reconfigure_no_log_dir_non_strict(self, tmp_path):
        """reconfigure 不传 log_dir 时走非 strict 模式（保留旧值）。"""
        valid = str(tmp_path / "reconfigure_keep")
        spring_logger.reconfigure(log_dir=valid)
        # 只传 level，不传 log_dir → 非 strict，不应报错
        spring_logger.reconfigure(level="DEBUG")
        assert spring_logger.log_dir == valid
        assert spring_logger.level == "DEBUG"
        # 恢复
        spring_logger.reconfigure(level="INFO")

    def test_import_does_not_create_logs_directory(self, tmp_path):
        """SpringLogger 构造时不应创建 logs/ 目录（文件 handler 延迟到 init_logging）。

        回归场景：模块级 ``spring_logger = SpringLogger()`` 在 import 时执行，
        旧代码会立即创建 ``logs/`` 目录和文件 handler，导致即使用户配置了
        ``logging.log_dir``，CWD 下仍会多出一份 ``logs/``。
        修复后 ``__init__`` 只添加控制台 handler，文件 handler 由
        ``reconfigure`` (即 ``init_logging``) 创建。
        """
        import os
        original_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            # 构造 SpringLogger（模拟 import 时的模块级构造）
            SpringLogger._instance = None
            import spring.logging.loguru_logger as ll
            ll.spring_logger = SpringLogger()
            # logs/ 目录不应被创建
            assert not (tmp_path / 'logs').exists(), \
                "SpringLogger() 构造时不应创建 logs/ 目录"
        finally:
            SpringLogger._instance = None
            os.chdir(original_cwd)

    def test_enable_file_false_does_not_create_directory(self, tmp_path):
        """_setup_loguru(enable_file=False) 不应创建日志目录。"""
        SpringLogger._instance = None
        logger = SpringLogger()
        logger.log_dir = str(tmp_path / 'should_not_exist')
        logger._setup_loguru(strict=False, enable_file=False)
        assert not (tmp_path / 'should_not_exist').exists(), \
            "enable_file=False 时不应创建日志目录"


class TestUvicornLogInterception:
    """验证 Uvicorn/Starlette/FastAPI 的标准 logging 被拦截转发到 Loguru。

    回归场景：Uvicorn 默认 LOGGING_CONFIG 为 uvicorn 和 uvicorn.access logger
    配置了各自的 StreamHandler 且 propagate=False，导致访问日志（GET /api/xxx 200 OK）
    和启动日志（Started server process）只输出到控制台，不写入日志文件。
    """

    def test_uvicorn_loggers_have_loguru_handler(self, tmp_path):
        """init_logging 后 Uvicorn logger 应使用 LoguruHandler 而非 StreamHandler。"""
        import logging
        custom = str(tmp_path / "uvicorn_test_logs")
        init_logging({'level': 'INFO', 'log_dir': custom})

        for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access',
                     'fastapi', 'starlette'):
            logger = logging.getLogger(name)
            handler_types = [type(h).__name__ for h in logger.handlers]
            assert 'LoguruHandler' in handler_types, \
                f"{name} logger 应有 LoguruHandler，实际: {handler_types}"
            assert 'StreamHandler' not in handler_types, \
                f"{name} logger 不应有 StreamHandler（会被 LoguruHandler 替代）"

    def test_uvicorn_loggers_propagate_false(self, tmp_path):
        """拦截后 Uvicorn logger 的 propagate 应为 False（避免重复转发到 root）。"""
        import logging
        custom = str(tmp_path / "propagate_test")
        init_logging({'level': 'INFO', 'log_dir': custom})

        for name in ('uvicorn', 'uvicorn.access', 'fastapi', 'starlette'):
            logger = logging.getLogger(name)
            assert logger.propagate is False, \
                f"{name} logger propagate 应为 False，实际: {logger.propagate}"

    def test_uvicorn_access_log_written_to_file(self, tmp_path):
        """Uvicorn 访问日志应通过 LoguruHandler 写入配置的日志文件。

        注意：pytest logging 插件会拦截标准 logging 调用，导致
        ``access_logger.info()`` 的记录被 pytest 捕获而不到达 LoguruHandler。
        本测试直接构造 LogRecord 并调用 LoguruHandler.handle()，绕过 pytest
        干预，验证 LoguruHandler → loguru → 文件 handler 的完整链路。
        生产环境无 pytest 干预，``access_logger.info()`` 正常到达 LoguruHandler。
        """
        import logging
        import time
        import os
        custom = str(tmp_path / "access_log_test")
        init_logging({'level': 'INFO', 'log_dir': custom})

        # 直接构造 LogRecord 并调用 LoguruHandler.handle，绕过 pytest logging 插件
        handler = logging.getLogger('uvicorn.access').handlers[0]
        assert isinstance(handler, LoguruHandler), \
            f"uvicorn.access handler 应为 LoguruHandler，实际: {type(handler)}"
        record = logging.LogRecord(
            name='uvicorn.access', level=logging.INFO, pathname=__file__,
            lineno=1, msg='127.0.0.1:52073 - "GET /api/hello/Alice HTTP/1.1" 200 OK',
            args=None, exc_info=None,
        )
        handler.handle(record)

        time.sleep(0.3)

        # 验证日志文件包含访问日志
        log_files = glob.glob(os.path.join(custom, "*.log"))
        assert len(log_files) > 0, f"期望日志文件出现在 {custom}"
        all_content = ''
        for lf in log_files:
            with open(lf, 'r', encoding='utf-8') as f:
                all_content += f.read()
        assert 'GET /api/hello/Alice' in all_content, \
            "Uvicorn 访问日志应通过 LoguruHandler 写入日志文件"
        assert '200 OK' in all_content

    def test_uvicorn_startup_log_written_to_file(self, tmp_path):
        """Uvicorn 启动日志应通过 LoguruHandler 写入配置的日志文件。"""
        import logging
        import time
        import os
        custom = str(tmp_path / "startup_log_test")
        init_logging({'level': 'INFO', 'log_dir': custom})

        # 直接构造 LogRecord 并调用 LoguruHandler.handle，绕过 pytest logging 插件
        handler = logging.getLogger('uvicorn').handlers[0]
        assert isinstance(handler, LoguruHandler), \
            f"uvicorn handler 应为 LoguruHandler，实际: {type(handler)}"
        for msg in ('Started server process [49412]',
                     'Application startup complete.',
                     'Uvicorn running on http://127.0.0.1:8080'):
            record = logging.LogRecord(
                name='uvicorn', level=logging.INFO, pathname=__file__,
                lineno=1, msg=msg, args=None, exc_info=None,
            )
            handler.handle(record)

        time.sleep(0.3)

        log_files = glob.glob(os.path.join(custom, "*.log"))
        assert len(log_files) > 0
        all_content = ''
        for lf in log_files:
            with open(lf, 'r', encoding='utf-8') as f:
                all_content += f.read()
        assert 'Started server process' in all_content
        assert 'Application startup complete' in all_content
        assert 'Uvicorn running on' in all_content
