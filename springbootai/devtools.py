"""
DevTools 热重载模块（类似 Spring Boot DevTools）

提供文件监视和自动重启功能，开发时修改代码无需手动重启。

功能：
- 监视 Python 文件变化，自动重启应用
- 支持配置排除目录（.git, __pycache__, venv 等）
- 支持配置轮询间隔
- 触发重启时打印变更文件路径

与 Java Spring Boot DevTools 的差异：
- Java 使用类加载器重启，Python 使用进程重启
- Java 监视 classpath，Python 监视 .py 文件

配置（application.yml）：
    spring:
      devtools:
        restart:
          enabled: false  # 仅开发环境开启
          poll-interval: 1.0  # 轮询间隔（秒）
          exclude: ["__pycache__", ".git", "venv", ".venv", "node_modules"]
"""
import logging
import os
import sys
import time
import threading
from pathlib import Path
from typing import List, Optional, Set

logger = logging.getLogger("Spring.DevTools")


class FileWatcher:
    """文件变更监视器（轮询模式）。

    轮询比 inotify/watchdog 更简单，且不依赖第三方库。
    对于开发环境（文件数 < 1000），轮询性能完全足够。
    """

    def __init__(self, watch_dirs: List[str],
                 exclude_dirs: Optional[Set[str]] = None,
                 poll_interval: float = 1.0,
                 patterns: Optional[Set[str]] = None):
        self.watch_dirs = [Path(d) for d in watch_dirs]
        self.exclude_dirs = exclude_dirs or {"__pycache__", ".git", "venv", ".venv", ".idea", "node_modules", ".tox", "dist", "build"}
        self.poll_interval = poll_interval
        self.patterns = patterns or {".py"}
        self._file_mtimes: dict = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callback = None

    def _scan_files(self) -> dict:
        """扫描所有监视目录，返回 {path: mtime}。"""
        result = {}
        for watch_dir in self.watch_dirs:
            if not watch_dir.exists():
                continue
            for root, dirs, files in os.walk(watch_dir):
                dirs[:] = [d for d in dirs if d not in self.exclude_dirs and not d.startswith(".")]
                for filename in files:
                    ext = Path(filename).suffix
                    if ext in self.patterns:
                        filepath = Path(root) / filename
                        try:
                            result[str(filepath)] = filepath.stat().st_mtime
                        except OSError:
                            pass
        return result

    def start(self, callback) -> None:
        """启动文件监视（在后台线程中运行）。"""
        self._callback = callback
        self._file_mtimes = self._scan_files()
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True, name="devtools-watcher")
        self._thread.start()
        logger.info(f"DevTools FileWatcher started: watching {len(self._file_mtimes)} files")

    def stop(self) -> None:
        """停止文件监视。"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    def _watch_loop(self) -> None:
        """文件监视循环。"""
        while self._running:
            time.sleep(self.poll_interval)
            if not self._running:
                break
            current_mtimes = self._scan_files()
            changed = []
            for filepath, mtime in current_mtimes.items():
                old_mtime = self._file_mtimes.get(filepath)
                if old_mtime is None or mtime > old_mtime:
                    changed.append(filepath)
            for filepath in self._file_mtimes:
                if filepath not in current_mtimes:
                    changed.append(filepath)
            if changed:
                self._file_mtimes = current_mtimes
                if self._callback:
                    try:
                        self._callback(changed)
                    except Exception as e:
                        logger.error(f"DevTools callback error: {e}")


class RestartTrigger:
    """应用重启触发器（带静默期，防止连续保存多个文件时频繁重启）。"""

    def __init__(self, quiet_period: float = 0.5, restart_callback=None):
        self.quiet_period = quiet_period
        self.restart_callback = restart_callback
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def on_file_changed(self, changed_files: List[str]) -> None:
        with self._lock:
            for f in changed_files:
                logger.info(f"DevTools: file changed: {f}")
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.quiet_period, self._trigger_restart)
            self._timer.daemon = True
            self._timer.start()

    def _trigger_restart(self) -> None:
        if self.restart_callback:
            logger.warning("DevTools: triggering application restart...")
            try:
                self.restart_callback()
            except Exception as e:
                logger.error(f"DevTools restart error: {e}")


def create_devtools_watcher(config: dict, restart_callback=None) -> Optional[FileWatcher]:
    """从配置创建 DevTools 文件监视器。"""
    devtools_config = config.get('spring', {}).get('devtools', {})
    restart_config = devtools_config.get('restart', {})
    if not restart_config.get('enabled', False):
        return None
    watch_dirs = restart_config.get('watch-dirs', ['.'])
    exclude_dirs = set(restart_config.get('exclude', []))
    poll_interval = restart_config.get('poll-interval', 1.0)
    quiet_period = restart_config.get('quiet-period', 0.5)
    trigger = RestartTrigger(quiet_period=quiet_period, restart_callback=restart_callback)
    watcher = FileWatcher(watch_dirs=watch_dirs, exclude_dirs=exclude_dirs, poll_interval=poll_interval)
    watcher.start(trigger.on_file_changed)
    return watcher
