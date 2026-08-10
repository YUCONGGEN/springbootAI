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
    init_logging, spring_logger, LoggingConfigError, SpringLogger,
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

    def test_empty_string_log_dir_raises(self, tmp_path):
        """空字符串 log_dir 应抛 LoggingConfigError。"""
        with pytest.raises(LoggingConfigError) as exc_info:
            init_logging({"level": "INFO", "log_dir": ""})
        assert "logging.log_dir" in str(exc_info.value)
        assert "空字符串" in str(exc_info.value)

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
