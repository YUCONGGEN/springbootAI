"""
优雅退出处理器 (Graceful Shutdown)

功能：
- 捕获 SIGTERM/SIGINT 信号
- 停止接收新请求（健康检查返回 NOT_READY）
- 等待在途请求完成（可配置超时）
- 关闭连接池、消息消费者等资源
- 注销服务发现
"""

import signal
import time
import logging
import threading
import asyncio
from typing import Optional, Callable, List, Dict, Any
from enum import Enum

logger = logging.getLogger("Spring.Core.Shutdown")


class ShutdownPhase(Enum):
    RUNNING = "RUNNING"
    DRAINING = "DRAINING"     # 停止接收新请求
    SHUTTING_DOWN = "SHUTTING_DOWN"  # 关闭资源
    STOPPED = "STOPPED"


class GracefulShutdown:
    """
    优雅退出管理器

    Usage:
        shutdown = GracefulShutdown()
        shutdown.register_hook("db_pool", pool.close)
        shutdown.register_hook("redis", redis_client.close)
        # 信号会自动注册
    """

    def __init__(self, drain_timeout: float = 30.0, shutdown_timeout: float = 30.0):
        self.drain_timeout = drain_timeout
        self.shutdown_timeout = shutdown_timeout
        self._phase = ShutdownPhase.RUNNING
        self._phase_lock = threading.RLock()
        self._hooks: Dict[str, Callable] = {}
        self._hooks_order: List[str] = []
        self._inflight_count = 0
        self._inflight_lock = threading.RLock()
        self._shutdown_event = threading.Event()
        self._original_sigterm = None
        self._original_sigint = None
        self._signal_received = False
        self._shutdown_start_time: Optional[float] = None

    def register_signals(self):
        """注册系统信号处理器"""
        try:
            self._original_sigterm = signal.getsignal(signal.SIGTERM)
            self._original_sigint = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)
            logger.info("Graceful shutdown signal handlers registered (SIGTERM/SIGINT)")
        except (ValueError, OSError) as e:
            # 在非主线程中无法注册信号，忽略
            logger.debug(f"Cannot register signal handlers: {e}")

    def _signal_handler(self, signum, frame):
        """信号处理回调"""
        if self._signal_received:
            logger.warning("Second signal received, forcing immediate shutdown")
            self._force_shutdown()
            return
        self._signal_received = True
        sig_name = signal.Signals(signum).name
        logger.info(f"Received signal {sig_name}, starting graceful shutdown...")
        threading.Thread(target=self.initiate_shutdown, daemon=True).start()

    def register_hook(self, name: str, hook: Callable, order: int = 0):
        """
        注册关闭钩子

        Args:
            name: 钩子名称（唯一标识）
            hook: 无参可调用对象
            order: 执行顺序（越小越先执行）
        """
        with self._phase_lock:
            self._hooks[name] = (order, hook)
            self._hooks_order = sorted(self._hooks.keys(), key=lambda n: self._hooks[n][0])
        logger.debug(f"Registered shutdown hook: {name} (order={order})")

    def request_started(self):
        """请求开始时调用，跟踪在途请求数"""
        with self._inflight_lock:
            self._inflight_count += 1

    def request_finished(self):
        """请求结束时调用"""
        with self._inflight_lock:
            self._inflight_count -= 1

    @property
    def is_draining(self) -> bool:
        """是否正在排空请求（不应接收新请求）"""
        with self._phase_lock:
            return self._phase in (ShutdownPhase.DRAINING, ShutdownPhase.SHUTTING_DOWN, ShutdownPhase.STOPPED)

    @property
    def is_shutting_down(self) -> bool:
        return self._phase in (ShutdownPhase.SHUTTING_DOWN, ShutdownPhase.STOPPED)

    @property
    def phase(self) -> ShutdownPhase:
        return self._phase

    @property
    def inflight_count(self) -> int:
        return self._inflight_count

    def initiate_shutdown(self):
        """启动优雅关闭流程"""
        with self._phase_lock:
            if self._phase != ShutdownPhase.RUNNING:
                return
            self._phase = ShutdownPhase.DRAINING
            self._shutdown_start_time = time.monotonic()

        logger.info("Phase 1: Draining - stopping new requests, waiting for in-flight requests...")

        # 等待在途请求完成
        deadline = time.monotonic() + self.drain_timeout
        while time.monotonic() < deadline:
            with self._inflight_lock:
                inflight = self._inflight_count
            if inflight == 0:
                break
            logger.info(f"Waiting for {inflight} in-flight request(s)... ({deadline - time.monotonic():.1f}s remaining)")
            time.sleep(0.5)

        with self._inflight_lock:
            remaining = self._inflight_count
        if remaining > 0:
            logger.warning(f"{remaining} request(s) still in-flight after drain timeout, proceeding to shutdown")

        # 关闭资源
        with self._phase_lock:
            self._phase = ShutdownPhase.SHUTTING_DOWN

        logger.info("Phase 2: Shutting down resources...")
        self._execute_hooks()

        with self._phase_lock:
            self._phase = ShutdownPhase.STOPPED

        elapsed = time.monotonic() - self._shutdown_start_time
        logger.info(f"Graceful shutdown completed in {elapsed:.2f}s")
        self._shutdown_event.set()

    def _execute_hooks(self):
        """执行所有关闭钩子"""
        for name in self._hooks_order:
            _, hook = self._hooks[name]
            hook_start = time.monotonic()
            try:
                result = hook()
                if asyncio.iscoroutine(result):
                    # 尝试在当前事件循环中运行协程
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.ensure_future(result)
                        else:
                            loop.run_until_complete(result)
                    except RuntimeError:
                        pass
                elapsed = time.monotonic() - hook_start
                logger.info(f"Shutdown hook '{name}' completed in {elapsed:.2f}s")
            except Exception as e:
                elapsed = time.monotonic() - hook_start
                logger.error(f"Shutdown hook '{name}' failed after {elapsed:.2f}s: {e}")

    def _force_shutdown(self):
        """强制关闭"""
        logger.critical("Force shutdown initiated")
        with self._phase_lock:
            self._phase = ShutdownPhase.STOPPED
        self._shutdown_event.set()

    def wait_for_shutdown(self, timeout: Optional[float] = None):
        """等待关闭完成"""
        self._shutdown_event.wait(timeout=timeout)


# 全局单例
shutdown_handler = GracefulShutdown()
