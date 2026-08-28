"""
AI 调用韧性 - 复用框架 springbootai.retry 的 @Retryable 机制 + 复用 springbootai.aop 的 CircuitBreaker 状态机。

为 LLM HTTP 调用提供：
1. 重试：复用 springbootai.retry.retry_decorator.retry() 便捷装饰器，对网络瞬态错误重试
2. 熔断：CLOSED/OPEN/HALF_OPEN 状态机，复用框架 Redis 持久化电路状态（同 springbootai.aop.comprehensive_aop.circuit_breaker_decorator），
   Redis 不可用时降级本地内存。跨实例共享熔断状态，多副本一致性。
"""
import functools
import logging
import threading
import time
from typing import Callable, Dict, Optional, Tuple, Type

logger = logging.getLogger("Spring.AI.Resilience")

# 复用框架重试基础设施
try:
    from springbootai.retry.retry_decorator import retry as _retry_decorator
    _RETRY_AVAILABLE = True
except ImportError:
    _RETRY_AVAILABLE = False


class CircuitState:
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class AICircuitBreaker:
    """
    熔断器 - 复用框架 springbootai.aop.comprehensive_aop 的 CircuitBreaker 状态机策略。

    状态流转：
        CLOSED --失败数>=threshold--> OPEN
        OPEN   --经过recovery_timeout--> HALF_OPEN
        HALF_OPEN --成功--> CLOSED
        HALF_OPEN --失败--> OPEN

    状态存储策略（与框架 circuit_breaker_decorator 一致）：
    - 优先用 Redis hash 持久化（`circuit_breaker:ai:{name}`），跨实例共享
    - Redis 不可用时降级本地内存
    """

    _local_cache: Dict[str, dict] = {}  # 类级本地缓存的回退

    def __init__(self, failure_threshold: int = 5,
                 recovery_timeout: float = 30.0,
                 fallback: Optional[Callable] = None,
                 name: str = "default",
                 redis_client=None):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.fallback = fallback
        self.name = name
        self._redis_client = redis_client
        self._redis_key = f"circuit_breaker:ai:{name}"
        self._lock = threading.Lock()
        # 本地状态（读透 Redis 缓存）
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._last_failure_time = 0.0

    def _redis_available(self) -> bool:
        """Redis 是否可用"""
        if self._redis_client is None:
            return False
        try:
            rc = (self._redis_client.get_client()
                  if hasattr(self._redis_client, "get_client")
                  else self._redis_client)
            return rc is not None
        except Exception:
            return False

    def _raw_redis(self):
        """获取原生 Redis 客户端"""
        if self._redis_client is None:
            return None
        return (self._redis_client.get_client()
                if hasattr(self._redis_client, "get_client")
                else self._redis_client)

    def _sync_from_redis(self):
        """从 Redis 同步状态到本地（读取透）"""
        r = self._raw_redis()
        if r is None:
            return
        try:
            state_data = r.hgetall(self._redis_key)
            if state_data:
                if not isinstance(state_data, dict):
                    return

                def hash_value(key: str, default):
                    # redis-py returns byte keys unless decode_responses=True.
                    # Supporting both forms is required for distributed state.
                    if key in state_data:
                        return state_data[key]
                    return state_data.get(key.encode("utf-8"), default)

                state = hash_value("state", b"CLOSED")
                if isinstance(state, bytes):
                    state = state.decode("utf-8")
                self._state = state if isinstance(state, str) else "CLOSED"
                failures = hash_value("failures", 0)
                self._failures = int(
                    failures if isinstance(failures, (int, bytes, str)) else 0)
                lf = hash_value("last_failure_time", 0)
                self._last_failure_time = float(lf) if isinstance(lf, (int, float, bytes, str)) else 0.0
        except Exception:
            # Redis 失败，保持本地状态
            pass

    def _sync_to_redis(self):
        """将本地状态同步到 Redis"""
        r = self._raw_redis()
        if r is None:
            return
        try:
            r.hset(self._redis_key, mapping={
                "state": self._state,
                "failures": str(self._failures),
                "last_failure_time": str(self._last_failure_time),
            })
        except Exception:
            pass

    @property
    def state(self) -> str:
        with self._lock:
            self._refresh_state()
            return self._state

    def _refresh_state(self):
        # 先从 Redis 同步（如果可用）
        if self._redis_available():
            self._sync_from_redis()
        if (self._state == CircuitState.OPEN and
                time.time() - self._last_failure_time > self.recovery_timeout):
            self._state = CircuitState.HALF_OPEN
            logger.info("AI 熔断器[%s] 进入 HALF_OPEN，尝试放行探测请求", self.name)
            if self._redis_available():
                self._sync_to_redis()

    def allow(self) -> bool:
        """是否放行请求"""
        with self._lock:
            self._refresh_state()
            return self._state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self):
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                logger.info("AI 熔断器[%s] HALF_OPEN -> CLOSED（探测成功）", self.name)
            self._state = CircuitState.CLOSED
            self._failures = 0
            if self._redis_available():
                self._sync_to_redis()

    def record_failure(self):
        with self._lock:
            self._failures += 1
            self._last_failure_time = time.time()
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning("AI 熔断器[%s] HALF_OPEN -> OPEN（探测失败）", self.name)
            elif self._failures >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning("AI 熔断器[%s] CLOSED -> OPEN（失败数=%d）",
                               self.name, self._failures)
            if self._redis_available():
                self._sync_to_redis()

    def call(self, func: Callable, *args, **kwargs):
        """经熔断器执行函数"""
        from springbootai.ai.observability import ai_metrics
        _provider = kwargs.pop("_cb_provider", "unknown")
        if not self.allow():
            ai_metrics.record_circuit_state(_provider, self._state)
            if self.fallback:
                return self.fallback(*args, **kwargs)
            raise CircuitOpenError(
                f"AI 熔断器[{self.name}] 处于 {self._state} 状态，拒绝请求（失败数={self._failures}）")
        try:
            result = func(*args, **kwargs)
            self.record_success()
            ai_metrics.record_circuit_state(_provider, CircuitState.CLOSED)
            return result
        except Exception as exc:
            # 调用方自行决定哪些异常计入失败
            if isinstance(exc, TransientError):
                self.record_failure()
            ai_metrics.record_circuit_state(_provider, self._state)
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
                   count_as_failure_exc: Tuple[Type[Exception], ...] = (Exception,),
                   provider: str = "unknown",
                   ) -> Callable:
    """
    为 LLM HTTP 调用注入重试 + 熔断。

    - 重试：复用 springbootai.retry.retry_decorator.retry（不可用时降级为简单循环）
    - 熔断：经 AICircuitBreaker.call 放行，count_as_failure_exc 内异常计入失败
    - provider：透传给熔断器指标，确保 ai_circuit_breaker_state label 可区分
    """
    count_as_failure_exc = count_as_failure_exc or (Exception,)

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # 1. 构造带重试的核心函数
        # The shared retry annotation interprets ``max_retries`` as total
        # attempts. Preserve that behavior while allowing zero to explicitly
        # request one un-retried attempt.
        attempts = max(1, int(max_retries))
        if _RETRY_AVAILABLE:
            retried = _retry_decorator(
                max_retries=attempts, delay=retry_delay_ms,
                exceptions=retry_exceptions,
            )(func)
        else:
            retried = func

        # 2. 把 provider 注入 kwargs 让 AICircuitBreaker 可读到
        #    调用实际函数前 pop 掉，避免透传
        kwargs["_cb_provider"] = provider

        # 3. 无熔断器 → 直接重试调用
        if circuit_breaker is None:
            kwargs.pop("_cb_provider", None)
            return retried(*args, **kwargs)

        # 4. 有熔断器 → 经熔断放行，失败计入熔断
        if not circuit_breaker.allow():
            from springbootai.ai.observability import ai_metrics
            kwargs.pop("_cb_provider", None)
            ai_metrics.record_circuit_state(provider, circuit_breaker.state)
            if circuit_breaker.fallback:
                return circuit_breaker.fallback(*args, **kwargs)
            raise CircuitOpenError("AI 熔断器处于 OPEN 状态，拒绝请求")

        try:
            kwargs.pop("_cb_provider", None)
            result = retried(*args, **kwargs)
            circuit_breaker.record_success()
            from springbootai.ai.observability import ai_metrics
            ai_metrics.record_circuit_state(provider, CircuitState.CLOSED)
            return result
        except count_as_failure_exc:
            circuit_breaker.record_failure()
            from springbootai.ai.observability import ai_metrics
            ai_metrics.record_circuit_state(provider, circuit_breaker.state)
            raise

    return wrapper
