"""
DevTools 文件变更监听模块（类似 Spring Boot DevTools）

提供文件监视和去抖回调。回调可由外部 reloader/进程管理器用来重启
应用；本模块本身不在运行中进程内冒充“已热重载”。

功能：
- 监视 Python 文件变化，触发去抖回调
- 支持配置排除目录（.git, __pycache__, venv 等）
- 支持配置轮询间隔
- 触发回调时打印变更文件路径

与 Java Spring Boot DevTools 的差异：
- Java 使用类加载器重启；Python 进程重启交给 Uvicorn ``--reload``
  或其他外部进程管理器
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
import math
import os
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
        try:
            self.poll_interval = float(poll_interval)
        except (TypeError, ValueError) as exc:
            raise ValueError("DevTools poll_interval must be a positive number") from exc
        if not math.isfinite(self.poll_interval) or self.poll_interval <= 0:
            raise ValueError("DevTools poll_interval must be a positive number")
        self.patterns = patterns or {".py"}
        self._file_mtimes: dict = {}
        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._callback = None
        self._restart_trigger = None

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
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("DevTools FileWatcher is already running")
        self._callback = callback
        self._file_mtimes = self._scan_files()
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._watch_loop, daemon=True, name="devtools-watcher")
        self._thread.start()
        logger.info(f"DevTools FileWatcher started: watching {len(self._file_mtimes)} files")

    def stop(self) -> None:
        """停止文件监视。"""
        self._running = False
        self._stop_event.set()
        trigger = self._restart_trigger
        if trigger is not None:
            trigger.stop()
        if (self._thread and self._thread.is_alive()
                and self._thread is not threading.current_thread()):
            self._thread.join(timeout=3)
        self._callback = None
        self._restart_trigger = None

    def _watch_loop(self) -> None:
        """文件监视循环。"""
        while self._running:
            if self._stop_event.wait(self.poll_interval) or not self._running:
                break
            current_mtimes = self._scan_files()
            changed = []
            for filepath, mtime in current_mtimes.items():
                old_mtime = self._file_mtimes.get(filepath)
                if old_mtime is None or mtime != old_mtime:
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
                        logger.error(
                            "DevTools callback failed error_type=%s",
                            type(e).__name__,
                        )


class RestartTrigger:
    """去抖回调触发器（避免连续保存多个文件时频繁回调）。

    ``restart_callback`` 保持历史的无参数契约。是否重启进程由调用方
    决定；SpringApplication 默认只记录变更通知。
    """

    def __init__(self, quiet_period: float = 0.5, restart_callback=None):
        try:
            self.quiet_period = float(quiet_period)
        except (TypeError, ValueError) as exc:
            raise ValueError("DevTools quiet_period must not be negative") from exc
        if not math.isfinite(self.quiet_period) or self.quiet_period < 0:
            raise ValueError("DevTools quiet_period must not be negative")
        self.restart_callback = restart_callback
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._stopped = False

    def on_file_changed(self, changed_files: List[str]) -> None:
        with self._lock:
            if self._stopped:
                return
            for f in changed_files:
                logger.info(f"DevTools: file changed: {f}")
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.quiet_period, self._trigger_restart)
            self._timer.daemon = True
            self._timer.start()

    def _trigger_restart(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self._timer = None
            callback = self.restart_callback
        if callback:
            logger.info("DevTools: triggering debounced change callback")
            try:
                callback()
            except Exception as e:
                logger.error(
                    "DevTools change callback failed error_type=%s",
                    type(e).__name__,
                )

    def stop(self) -> None:
        """取消尚未触发的回调，防止应用停止后仍执行。"""
        with self._lock:
            self._stopped = True
            timer = self._timer
            self._timer = None
            self.restart_callback = None
        if timer is not None:
            timer.cancel()


def _config_value(config: dict, *keys: str, default=None):
    """按顺序读取 kebab/snake 别名，并保留 ``False``/0/空列表。"""
    for key in keys:
        if key in config:
            return config[key]
    return default


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _as_string_list(value, default: List[str]) -> List[str]:
    if value is None:
        return list(default)
    if isinstance(value, (str, os.PathLike)):
        return [os.fspath(value)]
    try:
        return [os.fspath(item) for item in value]
    except (TypeError, ValueError):
        return list(default)


def create_devtools_watcher(config: dict, restart_callback=None) -> Optional[FileWatcher]:
    """从配置创建 DevTools 文件监视器。"""
    root_config = config if isinstance(config, dict) else {}
    spring_config = root_config.get('spring', {})
    spring_config = spring_config if isinstance(spring_config, dict) else {}
    devtools_config = spring_config.get('devtools', {})
    devtools_config = devtools_config if isinstance(devtools_config, dict) else {}
    restart_config = devtools_config.get('restart', {})
    restart_config = restart_config if isinstance(restart_config, dict) else {}
    if not _as_bool(restart_config.get('enabled', False)):
        return None
    watch_dirs = _as_string_list(
        _config_value(restart_config, 'watch-dirs', 'watch_dirs', default=['.']),
        ['.'],
    )
    exclude_dirs = set(_as_string_list(
        _config_value(
            restart_config, 'exclude', 'exclude-dirs', 'exclude_dirs', default=[]),
        [],
    ))
    poll_interval = _config_value(
        restart_config, 'poll-interval', 'poll_interval', default=1.0)
    quiet_period = _config_value(
        restart_config, 'quiet-period', 'quiet_period', default=0.5)
    trigger = RestartTrigger(quiet_period=quiet_period, restart_callback=restart_callback)
    watcher = FileWatcher(watch_dirs=watch_dirs, exclude_dirs=exclude_dirs, poll_interval=poll_interval)
    watcher._restart_trigger = trigger
    watcher.start(trigger.on_file_changed)
    return watcher
