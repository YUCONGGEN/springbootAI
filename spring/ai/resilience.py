"""
AI 调用韧性 - 复用框架 spring.retry 的 @Retryable 机制 + 镜像 spring.aop 的 CircuitBreaker 状态机。

为 LLM HTTP 调用提供：
1. 重试：复用 spring.retry.retry_decorator.retry() 便捷装饰器，对网络瞬态错误重试
2. 熔断：CLOSED/OPEN/HALF_OPEN 状态机（同 spring.aop.comprehensive_aop），保护下游 LLM API
"""
import functools
import logging
import threading
import time
from typing import Callable, Optional, Tuple, Type

logger = logging.getLogger("Spring.AI.Resilience")

# 复用框架重试基础设施
try:
    from spring.retry.retry_decorator import retry as _retry_decorator
    from spring.retry.retry_annotations import Backoff
    _RETRY_AVAILABLE = True
except ImportError:
    _RETRY_AVAILABLE = False


class CircuitState:
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class AICircuitBreaker:
    """
    轻量熔断器 - 镜像 spring.aop.comprehensive_aop 的 CircuitBreaker 状态机。

    状态流转：
        CLOSED --失败数>=threshold--> OPEN
        OPEN   --经过recovery_timeout--> HALF_OPEN
        HALF_OPEN --成功--> CLOSED
        HALF_OPEN --失败--> OPEN
    """

    def __init__(self, failure_threshold: int = 5,
                 recovery_timeout: float = 30.0,
                 fallback: Optional[Callable] = None):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.fallback = fallback
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._last_failure_time = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            self._refresh_state()
            return self._state

    def _refresh_state(self):
        if (self._state == CircuitState.OPEN and
                time.time() - self._last_failure_time > self.recovery_timeout):
            self._state = CircuitState.HALF_OPEN
            logger.info("AI 熔断器进入 HALF_OPEN，尝试放行探测请求")

    def allow(self) -> bool:
        """是否放行请求"""
        with self._lock:
            self._refresh_state()
            return self._state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self):
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                logger.info("AI 熔断器 HALF_OPEN -> CLOSED（探测成功）")
            self._state = CircuitState.CLOSED
            self._failures = 0

    def record_failure(self):
        with self._lock:
            self._failures += 1
            self._last_failure_time = time.time()
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning("AI 熔断器 HALF_OPEN -> OPEN（探测失败）")
            elif self._failures >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning("AI 熔断器 CLOSED -> OPEN（失败数=%d）",
                               self._failures)

    def call(self, func: Callable, *args, **kwargs):
        """经熔断器执行函数"""
        from spring.ai.observability import ai_metrics
        if not self.allow():
            ai_metrics.record_circuit_state(
                kwargs.get("provider", "unknown"), self._state)
            if self.fallback:
                return self.fallback(*args, **kwargs)
            raise CircuitOpenError(
                f"AI 熔断器处于 OPEN 状态，拒绝请求（失败数={self._failures}）")
        try:
            result = func(*args, **kwargs)
            self.record_success()
            ai_metrics.record_circuit_state(
                kwargs.get("provider", "unknown"), CircuitState.CLOSED)
            return result
        except Exception as exc:
            # 调用方自行决定哪些异常计入失败
            if isinstance(exc, TransientError):
                self.record_failure()
            ai_metrics.record_circuit_state(
                kwargs.get("provider", "unknown"), self._state)
            raise


class TransientError(Exception):
    """瞬态错误（网络抖动/超时/429），应触发重试与熔断计数"""


class CircuitOpenError(Exception):
    """熔断器开启"""


def resilient_call(func: Callable,
                   max_retries: int = 3,
                   retry_delay_ms: int = 500,
                   retry_exceptions: Tuple[Type[Exception], ...] = (Exception,),
                   circuit_breaker: Optional[AICircuitBreaker] = None,
                   count_as_failure_exc: Tuple[Type[Exception], ...] = (Exception,)
                   ) -> Callable:
    """
    为 LLM HTTP 调用注入重试 + 熔断。

    - 重试：复用 spring.retry.retry_decorator.retry（不可用时降级为简单循环）
    - 熔断：经 AICircuitBreaker.call 放行，count_as_failure_exc 内异常计入失败
    """
    count_as_failure_exc = count_as_failure_exc or (Exception,)

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # 1. 构造带重试的核心函数
        if _RETRY_AVAILABLE:
            retried = _retry_decorator(
                max_retries=max_retries, delay=retry_delay_ms,
                exceptions=retry_exceptions,
            )(func)
        else:
            retried = func

        # 2. 无熔断器 → 直接重试调用
        if circuit_breaker is None:
            return retried(*args, **kwargs)

        # 3. 有熔断器 → 经熔断放行，失败计入熔断
        if not circuit_breaker.allow():
            if circuit_breaker.fallback:
                return circuit_breaker.fallback(*args, **kwargs)
            raise CircuitOpenError("AI 熔断器处于 OPEN 状态，拒绝请求")

        try:
            result = retried(*args, **kwargs)
            circuit_breaker.record_success()
            return result
        except count_as_failure_exc as exc:
            circuit_breaker.record_failure()
            raise

    return wrapper
