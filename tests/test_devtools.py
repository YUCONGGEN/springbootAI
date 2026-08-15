"""DevTools 热重载模块测试。

覆盖 ``spring.devtools`` 的核心组件：
- ``FileWatcher``：基于轮询的文件变更监视器
- ``RestartTrigger``：带静默期的应用重启触发器
- ``create_devtools_watcher``：从配置创建监视器的工厂函数

文件变更类测试使用 ``tmp_path`` 创建真实临时文件，
并通过 ``threading.Event`` 同步后台线程，避免固定 sleep 导致的抖动。
"""
import threading
import time
from pathlib import Path

import pytest

from spring.devtools import FileWatcher, RestartTrigger, create_devtools_watcher


# ==================== FileWatcher 测试 ====================

class TestFileWatcher:
    """FileWatcher 文件监视器测试。"""

    def test_init_defaults(self):
        """使用默认参数构造时，应使用合理的默认值。"""
        watcher = FileWatcher(["."])
        try:
            assert watcher.poll_interval == 1.0
            assert ".py" in watcher.patterns
            # 默认排除常见缓存/虚拟环境目录
            assert "__pycache__" in watcher.exclude_dirs
            assert ".git" in watcher.exclude_dirs
            assert watcher._running is False
            assert watcher._thread is None
            assert watcher._file_mtimes == {}
        finally:
            watcher.stop()

    def test_init_custom_params(self, tmp_path):
        """自定义参数应被正确保存。"""
        watcher = FileWatcher(
            watch_dirs=[str(tmp_path)],
            exclude_dirs={"custom_excl"},
            poll_interval=0.5,
            patterns={".py", ".txt"},
        )
        try:
            assert str(watcher.watch_dirs[0]) == str(tmp_path)
            assert "custom_excl" in watcher.exclude_dirs
            assert watcher.poll_interval == 0.5
            assert ".py" in watcher.patterns
            assert ".txt" in watcher.patterns
        finally:
            watcher.stop()

    def test_scan_files_finds_py_files(self, tmp_path):
        """_scan_files 应返回监视目录下的 .py 文件。"""
        (tmp_path / "a.py").write_text("# a\n")
        (tmp_path / "b.py").write_text("# b\n")
        (tmp_path / "c.txt").write_text("not python\n")  # 非 .py，默认不扫描

        watcher = FileWatcher([str(tmp_path)])
        try:
            scanned = watcher._scan_files()
            paths = list(scanned.keys())
            assert any(p.endswith("a.py") for p in paths)
            assert any(p.endswith("b.py") for p in paths)
            assert not any(p.endswith("c.txt") for p in paths)
            # 返回值为 {filepath: mtime}，mtime 为浮点数
            assert all(isinstance(m, float) for m in scanned.values())
        finally:
            watcher.stop()

    def test_scan_files_excludes_dirs(self, tmp_path):
        """_scan_files 应跳过默认排除目录（如 __pycache__）中的文件。"""
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "cached.py").write_text("# cached\n")
        (tmp_path / "main.py").write_text("# main\n")

        watcher = FileWatcher([str(tmp_path)])  # 使用默认排除目录
        try:
            scanned = watcher._scan_files()
            paths = list(scanned.keys())
            assert any(p.endswith("main.py") for p in paths)
            assert not any("__pycache__" in p for p in paths)
            assert not any(p.endswith("cached.py") for p in paths)
        finally:
            watcher.stop()

    def test_scan_files_respects_patterns(self, tmp_path):
        """自定义 patterns 时，应只返回匹配扩展名的文件。"""
        (tmp_path / "a.py").write_text("# py\n")
        (tmp_path / "b.txt").write_text("text\n")
        (tmp_path / "c.log").write_text("log\n")

        watcher = FileWatcher([str(tmp_path)], patterns={".txt"})
        try:
            scanned = watcher._scan_files()
            paths = list(scanned.keys())
            assert any(p.endswith("b.txt") for p in paths)
            assert not any(p.endswith("a.py") for p in paths)
            assert not any(p.endswith("c.log") for p in paths)
        finally:
            watcher.stop()

    def test_start_stop_watcher(self, tmp_path):
        """start/stop 应正确管理后台线程生命周期。"""
        watcher = FileWatcher([str(tmp_path)], poll_interval=0.1)
        # 启动前状态
        assert watcher._running is False
        assert watcher._thread is None

        watcher.start(lambda files: None)
        try:
            assert watcher._running is True
            assert watcher._thread is not None
            assert watcher._thread.is_alive()
            assert watcher._callback is not None
        finally:
            watcher.stop()

        # 停止后线程应结束
        assert watcher._running is False
        assert not watcher._thread.is_alive()

    def test_callback_called_on_file_change(self, tmp_path):
        """修改已存在文件后，回调应被调用并包含变更文件路径。"""
        f = tmp_path / "service.py"
        f.write_text("value = 1\n")
        time.sleep(0.1)  # 确保 mtime 与后续修改有足够差异（Windows 分辨率）

        changed_files = []
        event = threading.Event()

        def callback(files):
            changed_files.extend(files)
            event.set()

        watcher = FileWatcher([str(tmp_path)], poll_interval=0.15)
        watcher.start(callback)
        try:
            time.sleep(0.1)
            f.write_text("value = 2\n")  # 修改文件内容
            assert event.wait(timeout=3.0), "文件修改后回调未被调用"
            assert any(p.endswith("service.py") for p in changed_files)
        finally:
            watcher.stop()

    def test_callback_called_on_file_create(self, tmp_path):
        """新建文件后，回调应被调用并包含新文件路径。"""
        changed_files = []
        event = threading.Event()

        def callback(files):
            changed_files.extend(files)
            event.set()

        watcher = FileWatcher([str(tmp_path)], poll_interval=0.15)
        watcher.start(callback)
        try:
            time.sleep(0.2)  # 等待首次轮询完成，建立基线 mtime
            new_file = tmp_path / "new_module.py"
            new_file.write_text("# new module\n")  # 创建新文件
            assert event.wait(timeout=3.0), "文件创建后回调未被调用"
            assert any(p.endswith("new_module.py") for p in changed_files)
        finally:
            watcher.stop()

    def test_exclude_dirs_not_scanned(self, tmp_path):
        """排除目录中的文件变更不应触发回调。"""
        excluded_dir = tmp_path / "excluded"
        excluded_dir.mkdir()
        (excluded_dir / "hidden.py").write_text("# hidden\n")
        (tmp_path / "visible.py").write_text("# visible\n")
        time.sleep(0.1)

        changed_files = []
        event = threading.Event()

        def callback(files):
            changed_files.extend(files)
            event.set()

        watcher = FileWatcher(
            [str(tmp_path)],
            exclude_dirs={"excluded"},
            poll_interval=0.15,
        )
        watcher.start(callback)
        try:
            time.sleep(0.2)  # 等待首次轮询
            # 修改排除目录中的文件
            (excluded_dir / "hidden.py").write_text("# changed\n")
            time.sleep(0.4)  # 等待多个轮询周期
            # 排除目录的变更不应触发回调
            assert not event.is_set(), "排除目录中的文件变更不应触发回调"
            assert not any("excluded" in p for p in changed_files)
        finally:
            watcher.stop()


# ==================== RestartTrigger 测试 ====================

class TestRestartTrigger:
    """RestartTrigger 重启触发器测试。"""

    def test_trigger_restart_calls_callback(self):
        """on_file_changed 被调用后，静默期结束后应触发 restart_callback。"""
        called = threading.Event()
        trigger = RestartTrigger(
            quiet_period=0.05,
            restart_callback=called.set,
        )
        trigger.on_file_changed(["/some/path/service.py"])
        # 静默期内等待回调被调用
        assert called.wait(timeout=2.0), "静默期后 restart_callback 未被调用"

    def test_trigger_restart_with_empty_list(self):
        """传入空文件列表时，不应抛出异常，定时器仍正常工作。

        实现中 on_file_changed 不检查空列表，仍会启动静默期定时器。
        """
        called = threading.Event()
        trigger = RestartTrigger(
            quiet_period=0.05,
            restart_callback=called.set,
        )
        # 空列表不应抛出异常
        trigger.on_file_changed([])
        assert called.wait(timeout=2.0), "空列表也应触发 restart_callback"

    def test_quiet_period_defers_restart(self):
        """静默期内连续变更应重置定时器，只在最后一次变更后触发。"""
        call_times = []
        lock = threading.Lock()

        def callback():
            with lock:
                call_times.append(time.time())

        trigger = RestartTrigger(quiet_period=0.2, restart_callback=callback)
        # 连续触发两次，间隔小于静默期
        trigger.on_file_changed(["a.py"])
        time.sleep(0.05)
        trigger.on_file_changed(["b.py"])  # 重置定时器
        # 静默期内不应已调用
        assert len(call_times) == 0
        # 等待静默期结束
        assert _wait_until(lambda: len(call_times) >= 1, timeout=2.0)
        # 只应触发一次
        assert len(call_times) == 1


# ==================== create_devtools_watcher 测试 ====================

class TestCreateDevtoolsWatcher:
    """create_devtools_watcher 工厂函数测试。"""

    def test_create_watcher_disabled_returns_none(self):
        """devtools.restart.enabled 为 False 时应返回 None。"""
        config = {
            "spring": {
                "devtools": {
                    "restart": {"enabled": False}
                }
            }
        }
        assert create_devtools_watcher(config) is None

    def test_create_watcher_enabled_returns_watcher(self, tmp_path):
        """devtools.restart.enabled 为 True 时应返回已启动的 FileWatcher。"""
        config = {
            "spring": {
                "devtools": {
                    "restart": {
                        "enabled": True,
                        "watch-dirs": [str(tmp_path)],
                    }
                }
            }
        }
        watcher = create_devtools_watcher(config, restart_callback=lambda: None)
        try:
            assert isinstance(watcher, FileWatcher)
            assert watcher._running is True
            assert watcher._thread is not None
            assert watcher._thread.is_alive()
        finally:
            if watcher:
                watcher.stop()

    def test_create_watcher_with_custom_dirs(self, tmp_path):
        """自定义 watch-dirs 和 poll-interval 应传递给 FileWatcher。"""
        config = {
            "spring": {
                "devtools": {
                    "restart": {
                        "enabled": True,
                        "watch-dirs": [str(tmp_path)],
                        "poll-interval": 0.5,
                    }
                }
            }
        }
        watcher = create_devtools_watcher(config, restart_callback=lambda: None)
        try:
            assert watcher is not None
            assert any(str(d) == str(tmp_path) for d in watcher.watch_dirs)
            assert watcher.poll_interval == 0.5
        finally:
            if watcher:
                watcher.stop()

    def test_create_watcher_default_exclude_dirs(self, tmp_path):
        """未配置 exclude 时，FileWatcher 应使用内置默认排除目录。

        create_devtools_watcher 传入空 set，FileWatcher.__init__ 中
        ``exclude_dirs or {默认集}`` 会回退到默认值。
        """
        config = {
            "spring": {
                "devtools": {
                    "restart": {
                        "enabled": True,
                        "watch-dirs": [str(tmp_path)],
                    }
                }
            }
        }
        watcher = create_devtools_watcher(config, restart_callback=lambda: None)
        try:
            assert watcher is not None
            # 默认排除目录应包含常见缓存/构建目录
            assert "__pycache__" in watcher.exclude_dirs
            assert ".git" in watcher.exclude_dirs
            assert "venv" in watcher.exclude_dirs
        finally:
            if watcher:
                watcher.stop()


# ==================== 工具函数 ====================

def _wait_until(predicate, timeout=2.0, interval=0.05):
    """轮询等待条件成立，超时返回 False。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()
