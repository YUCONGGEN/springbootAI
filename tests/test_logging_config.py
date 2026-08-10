"""日志配置测试：验证 init_logging / reconfigure 使 logging.log_dir 等配置生效。

回归场景：SpringLogger 为单例，``__init__`` 的 ``_initialized`` 守卫会阻止后续
``SpringLogger(log_dir=...)`` 更新参数，导致 ``init_logging`` 读取 application.yml 的
``logging.log_dir`` 后日志目录仍停留在默认 ``'logs'``（相对当前工作目录，即 Application.py
所在目录/logs）。修复后 ``init_logging`` 通过 ``reconfigure`` 重新配置单例。
"""
import glob
import os
import time

from spring.logging.loguru_logger import init_logging, spring_logger


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
