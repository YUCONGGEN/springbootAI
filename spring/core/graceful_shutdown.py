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
import concurrent.futures
import inspect
import math
from typing import Optional, Callable, List, Dict
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
        self.drain_timeout = self._normalize_timeout(drain_timeout, 30.0)
        self.shutdown_timeout = self._normalize_timeout(shutdown_timeout, 30.0)
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

    @staticmethod
    def _normalize_timeout(value: object, default: float) -> float:
        """Return a finite, non-negative timeout.

        Configuration binders may provide strings or small mapping objects.  A
        malformed value must not make the signal handler thread die while it is
        evaluating ``deadline = monotonic() + timeout``.
        """
        if isinstance(value, dict):
            value = value.get("value", value.get("timeout", default))
        try:
            timeout = float(value)
        except (TypeError, ValueError):
            return float(default)
        if not math.isfinite(timeout) or timeout < 0:
            return float(default)
        return timeout

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

    def request_started(self) -> bool:
        """请求开始时调用，跟踪在途请求数。

        Once draining starts, new work must not be counted as in-flight.  The
        boolean return value lets middleware reject such requests while older
        callers can continue to ignore it.
        """
        with self._phase_lock:
            if self._phase != ShutdownPhase.RUNNING:
                return False
            with self._inflight_lock:
                self._inflight_count += 1
        return True

    def request_finished(self) -> bool:
        """请求结束时调用，防止计数在重复清理时下溢。"""
        with self._inflight_lock:
            if self._inflight_count <= 0:
                self._inflight_count = 0
                logger.warning("request_finished called with no in-flight requests")
                return False
            self._inflight_count -= 1
        return True

    @property
    def is_draining(self) -> bool:
        """是否正在排空请求（不应接收新请求）"""
        with self._phase_lock:
            return self._phase in (ShutdownPhase.DRAINING, ShutdownPhase.SHUTTING_DOWN, ShutdownPhase.STOPPED)

    @property
    def is_shutting_down(self) -> bool:
        with self._phase_lock:
            return self._phase in (ShutdownPhase.SHUTTING_DOWN, ShutdownPhase.STOPPED)

    @property
    def phase(self) -> ShutdownPhase:
        with self._phase_lock:
            return self._phase

    @property
    def inflight_count(self) -> int:
        with self._inflight_lock:
            return self._inflight_count

    def initiate_shutdown(self) -> bool:
        """启动优雅关闭流程。

        The completion event is always set, even if an unexpected error occurs
        while draining or executing hooks, so callers waiting for shutdown do
        not block forever.
        """
        with self._phase_lock:
            if self._phase != ShutdownPhase.RUNNING:
                return False
            self._phase = ShutdownPhase.DRAINING
            self._shutdown_start_time = time.monotonic()

        try:
            logger.info("Phase 1: Draining - stopping new requests, waiting for in-flight requests...")

            # 等待在途请求完成
            deadline = time.monotonic() + self.drain_timeout
            while time.monotonic() < deadline:
                with self._inflight_lock:
                    inflight = self._inflight_count
                if inflight == 0:
                    break
                logger.info(f"Waiting for {inflight} in-flight request(s)... ({deadline - time.monotonic():.1f}s remaining)")
                time.sleep(min(0.5, max(0.01, deadline - time.monotonic())))

            with self._inflight_lock:
                remaining = self._inflight_count
            if remaining > 0:
                logger.warning(f"{remaining} request(s) still in-flight after drain timeout, proceeding to shutdown")

            # 关闭资源
            with self._phase_lock:
                self._phase = ShutdownPhase.SHUTTING_DOWN

            logger.info("Phase 2: Shutting down resources...")
            hook_deadline = time.monotonic() + self.shutdown_timeout
            self._execute_hooks(deadline=hook_deadline)
        except Exception:
            # A malformed hook or an unexpected lifecycle error must not leave
            # wait_for_shutdown() blocked indefinitely.
            logger.exception("Unexpected error during graceful shutdown")
        finally:
            with self._phase_lock:
                self._phase = ShutdownPhase.STOPPED

            start_time = self._shutdown_start_time or time.monotonic()
            elapsed = time.monotonic() - start_time
            logger.info(f"Graceful shutdown completed in {elapsed:.2f}s")
            self._shutdown_event.set()
        return True

    @staticmethod
    def _run_awaitable(awaitable, timeout: float) -> None:
        """Resolve an awaitable from a synchronous shutdown worker."""
        async def wait_for_result():
            return await asyncio.wait_for(awaitable, timeout=max(0.001, timeout))

        # A regular coroutine has no loop until it is run.  ``asyncio.run``
        # creates and closes an isolated loop, which also works when shutdown
        # was initiated from inside an already-running ASGI loop.
        loop = None
        get_loop = getattr(awaitable, "get_loop", None)
        if callable(get_loop):
            try:
                loop = get_loop()
            except (RuntimeError, AttributeError):
                loop = None
        if loop is not None:
            if loop.is_closed():
                raise RuntimeError("async shutdown hook is bound to a closed event loop")
            if loop.is_running():
                # Blocking on a Future from the thread that owns its running
                # loop would deadlock that loop.  Shutdown hooks normally run
                # in a worker thread, but fail explicitly for custom callers
                # that invoke this helper from inside the loop itself.
                try:
                    current_loop = asyncio.get_running_loop()
                except RuntimeError:
                    current_loop = None
                if current_loop is loop:
                    raise RuntimeError(
                        "cannot synchronously wait for an async shutdown hook "
                        "from its running event-loop thread"
                    )
                future = asyncio.run_coroutine_threadsafe(wait_for_result(), loop)
                try:
                    return future.result(timeout=max(0.001, timeout))
                except concurrent.futures.TimeoutError:
                    future.cancel()
                    raise TimeoutError("async shutdown hook timed out")

            # ``asyncio.Future`` instances retain the loop they were created
            # on even when that loop is idle.  Running the wrapper on a fresh
            # loop (``asyncio.run``) would raise a cross-loop RuntimeError, so
            # execute it on the owning loop instead.
            return loop.run_until_complete(wait_for_result())
        return asyncio.run(wait_for_result())

    def _execute_hook(self, name: str, hook: Callable, timeout: float) -> None:
        """Run one hook in a daemon worker so a stuck hook cannot block shutdown."""
        result_holder: Dict[str, BaseException] = {}
        elapsed_holder: Dict[str, float] = {}
        done = threading.Event()

        def invoke() -> None:
            started = time.monotonic()
            try:
                result = hook()
                if inspect.isawaitable(result):
                    self._run_awaitable(result, timeout)
            except BaseException as exc:  # keep shutdown alive for hook failures
                result_holder["error"] = exc
            finally:
                elapsed_holder["value"] = time.monotonic() - started
                done.set()

        worker = threading.Thread(
            target=invoke,
            name=f"SpringShutdown-{name}",
            daemon=True,
        )
        try:
            worker.start()
        except Exception as exc:
            logger.error("Shutdown hook '%s' could not start: %s", name, exc)
            return

        if not done.wait(timeout=max(0.001, timeout)):
            logger.error("Shutdown hook '%s' timed out after %.2fs", name, timeout)
            return
        error = result_holder.get("error")
        if error is not None:
            logger.error(
                "Shutdown hook '%s' failed after %.2fs: %s",
                name,
                elapsed_holder.get("value", 0.0),
                error,
            )
            return
        logger.info(
            "Shutdown hook '%s' completed in %.2fs",
            name,
            elapsed_holder.get("value", 0.0),
        )

    def _execute_hooks(self, deadline: Optional[float] = None):
        """Execute hooks in order within the configured shutdown budget."""
        if deadline is None:
            deadline = time.monotonic() + self.shutdown_timeout
        with self._phase_lock:
            hook_names = list(self._hooks_order)
            hooks = {name: self._hooks.get(name) for name in hook_names}
        for name in hook_names:
            entry = hooks.get(name)
            if not entry:
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning("Shutdown hook budget exhausted; skipping remaining hooks")
                break
            _, hook = entry
            self._execute_hook(name, hook, remaining)

    def _force_shutdown(self):
        """强制关闭"""
        logger.critical("Force shutdown initiated")
        with self._phase_lock:
            self._phase = ShutdownPhase.STOPPED
        self._shutdown_event.set()

    def wait_for_shutdown(self, timeout: Optional[float] = None) -> bool:
        """等待关闭完成，返回是否在给定超时内完成。"""
        return self._shutdown_event.wait(timeout=timeout)


# 全局单例
shutdown_handler = GracefulShutdown()
