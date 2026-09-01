"""
PyMyBatis熔断降级模块

实现数据库连接熔断机制，防止数据库故障导致的级联失败

核心特性：
- 三种状态：闭合(Closed)、打开(Open)、半开(Half-Open)
- 基于失败率的熔断触发
- 自动恢复机制
- 支持自定义降级策略
"""

import time
import threading
import logging
import inspect
from enum import Enum
from typing import Callable, Optional, Any, Dict

logger = logging.getLogger(__name__)


class CircuitBreakerState(Enum):
    """
    熔断器状态

    CLOSED: 闭合状态，正常运行，所有请求都被允许通过
    OPEN: 打开状态，熔断器触发，所有请求都被拒绝，直接返回降级结果
    HALF_OPEN: 半开状态，尝试恢复，允许部分请求通过进行试探
    """
    CLOSED = 'closed'
    OPEN = 'open'
    HALF_OPEN = 'half_open'


class CircuitBreakerError(Exception):
    """
    熔断器异常

    当熔断器处于打开状态时，请求被拒绝时抛出此异常
    """

    def __init__(self, message: str, fallback_result: Any = None):
        super().__init__(message)
        self.fallback_result = fallback_result


class CircuitBreaker:
    """
    熔断器实现

    实现经典的熔断器模式：
    1. 闭合状态：正常处理请求，记录失败次数
    2. 打开状态：拒绝所有请求，返回降级结果
    3. 半开状态：允许部分请求通过，检测服务是否恢复

    配置参数：
    - failure_threshold: 失败阈值，当失败次数达到此值时触发熔断
    - recovery_timeout: 恢复超时时间，熔断器打开后经过此时间进入半开状态
    - success_threshold: 成功阈值，半开状态下成功次数达到此值时恢复闭合状态
    - max_concurrent_requests: 最大并发请求数
    - fallback: 降级函数，熔断器打开时调用
    """

    def __init__(self,
                 failure_threshold: int = 5,
                 recovery_timeout: int = 30,
                 success_threshold: int = 3,
                 max_concurrent_requests: int = 100,
                 fallback: Optional[Callable[..., Any]] = None,
                 name: str = 'default'):
        """
        初始化熔断器

        Args:
            failure_threshold: 失败阈值，当失败次数达到此值时触发熔断
            recovery_timeout: 恢复超时时间（秒），熔断器打开后经过此时间进入半开状态
            success_threshold: 成功阈值，半开状态下成功次数达到此值时恢复闭合状态
            max_concurrent_requests: 最大并发请求数
            fallback: 降级函数，熔断器打开时调用
            name: 熔断器名称，用于日志和监控
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.max_concurrent_requests = max_concurrent_requests
        self.fallback = fallback
        self.name = name

        # 状态管理
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._concurrent_requests = 0
        self._last_failure_time = 0
        self._last_state_change_time = 0

        # 锁
        self._lock = threading.RLock()
        self._state_lock = threading.RLock()

        # 统计信息
        self._total_requests = 0
        self._total_failures = 0
        self._total_successes = 0
        self._total_circuit_open = 0

    def _get_state(self) -> CircuitBreakerState:
        """
        获取当前状态（考虑状态自动转换）

        Returns:
            当前状态
        """
        with self._state_lock:
            # 如果是打开状态，检查是否应该进入半开状态
            if self._state == CircuitBreakerState.OPEN:
                elapsed = time.time() - self._last_state_change_time
                if elapsed >= self.recovery_timeout:
                    logger.info(f"熔断器[{self.name}]从OPEN状态转换为HALF_OPEN状态")
                    self._state = CircuitBreakerState.HALF_OPEN
                    self._success_count = 0
                    self._last_state_change_time = time.time()

            return self._state

    def _transition_to_open(self):
        """转换到打开状态"""
        with self._state_lock:
            if self._state != CircuitBreakerState.OPEN:
                logger.warning(f"熔断器[{self.name}]触发熔断，转换为OPEN状态")
                self._state = CircuitBreakerState.OPEN
                self._last_state_change_time = time.time()
                self._total_circuit_open += 1

    def _transition_to_closed(self):
        """转换到闭合状态"""
        with self._state_lock:
            if self._state != CircuitBreakerState.CLOSED:
                logger.info(f"熔断器[{self.name}]恢复正常，转换为CLOSED状态")
                self._state = CircuitBreakerState.CLOSED
                self._failure_count = 0
                self._success_count = 0
                self._last_state_change_time = time.time()

    def _acquire_concurrent_slot(self) -> bool:
        """
        获取并发请求槽位

        Returns:
            是否成功获取
        """
        with self._lock:
            if self._concurrent_requests >= self.max_concurrent_requests:
                logger.warning(f"熔断器[{self.name}]并发请求数已达上限: {self.max_concurrent_requests}")
                return False
            self._concurrent_requests += 1
            return True

    def _release_concurrent_slot(self):
        """释放并发请求槽位"""
        with self._lock:
            self._concurrent_requests = max(0, self._concurrent_requests - 1)

    def call(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        """
        执行受保护的函数调用

        Args:
            func: 受保护的函数
            *args: 函数参数
            **kwargs: 函数关键字参数

        Returns:
            函数执行结果

        Raises:
            CircuitBreakerError: 熔断器打开时抛出
            Exception: 函数执行异常
        """
        state = self._get_state()

        # 检查并发限制
        if not self._acquire_concurrent_slot():
            if self.fallback:
                return self.fallback(*args, **kwargs)
            raise CircuitBreakerError(f"熔断器[{self.name}]并发请求数已达上限")

        release_slot = True
        try:
            # 根据状态处理请求
            if state == CircuitBreakerState.OPEN:
                # 熔断器打开，直接返回降级结果
                self._total_requests += 1
                if self.fallback:
                    result = self.fallback(*args, **kwargs)
                    logger.debug(f"熔断器[{self.name}]OPEN状态，使用降级结果")
                    return result
                raise CircuitBreakerError(f"熔断器[{self.name}]处于OPEN状态，请求被拒绝")

            elif state == CircuitBreakerState.HALF_OPEN:
                # 熔断器半开，允许试探请求
                logger.debug(f"熔断器[{self.name}]HALF_OPEN状态，允许试探请求")
                result = self._execute_with_half_open(func, *args, **kwargs)

            else:
                # 熔断器闭合，正常执行
                result = self._execute_with_closed(func, *args, **kwargs)

            if inspect.isawaitable(result):
                release_slot = False

                async def await_and_release():
                    try:
                        return await result
                    finally:
                        self._release_concurrent_slot()

                return await_and_release()
            return result

        finally:
            if release_slot:
                self._release_concurrent_slot()

    def _execute_with_closed(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        """
        闭合状态下执行函数

        Args:
            func: 函数
            *args: 参数
            **kwargs: 关键字参数

        Returns:
            函数执行结果
        """
        try:
            result = func(*args, **kwargs)
            if inspect.isawaitable(result):
                async def await_result():
                    try:
                        value = await result
                    except Exception:
                        self._on_failure()
                        raise
                    else:
                        self._on_success()
                        return value

                return await_result()
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    def _execute_with_half_open(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        """
        半开状态下执行函数

        Args:
            func: 函数
            *args: 参数
            **kwargs: 关键字参数

        Returns:
            函数执行结果
        """
        # 获取状态锁，确保在执行过程中状态不会被其他线程改变
        with self._state_lock:
            # 再次检查状态，因为可能在等待锁的过程中状态已经改变
            current_state = self._state
            if current_state != CircuitBreakerState.HALF_OPEN:
                # 状态已改变，重新执行
                return self.call(func, *args, **kwargs)

            try:
                result = func(*args, **kwargs)
            except Exception:
                self._on_half_open_failure()
                raise

        if inspect.isawaitable(result):
            async def await_result():
                try:
                    value = await result
                except Exception:
                    self._on_half_open_failure()
                    raise
                else:
                    self._on_half_open_success()
                    return value

            return await_result()
        self._on_half_open_success()
        return result

    def _on_half_open_success(self) -> None:
        with self._state_lock:
            self._success_count += 1
            self._total_successes += 1
            self._total_requests += 1
            if self._success_count >= self.success_threshold:
                self._state = CircuitBreakerState.CLOSED
                self._failure_count = 0
                self._success_count = 0
                self._last_state_change_time = time.time()
                logger.info(
                    "熔断器[%s]恢复正常，转换为CLOSED状态", self.name)

    def _on_half_open_failure(self) -> None:
        with self._state_lock:
            self._total_failures += 1
            self._total_requests += 1
            logger.warning(
                "熔断器[%s]HALF_OPEN状态下请求失败，立即打开", self.name)
            self._state = CircuitBreakerState.OPEN
            self._last_state_change_time = time.time()

    def _on_success(self):
        """处理成功请求"""
        with self._lock:
            self._failure_count = 0
            self._total_successes += 1
            self._total_requests += 1

    def _on_failure(self):
        """处理失败请求"""
        with self._lock:
            self._failure_count += 1
            self._total_failures += 1
            self._total_requests += 1
            self._last_failure_time = time.time()

        # 检查是否达到失败阈值
        if self._failure_count >= self.failure_threshold:
            self._transition_to_open()

    def reset(self):
        """重置熔断器状态"""
        with self._state_lock:
            logger.info(f"熔断器[{self.name}]被重置")
            self._state = CircuitBreakerState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_state_change_time = time.time()

    def force_open(self):
        """强制打开熔断器"""
        with self._state_lock:
            logger.warning(f"熔断器[{self.name}]被强制打开")
            self._state = CircuitBreakerState.OPEN
            self._last_state_change_time = time.time()

    def force_close(self):
        """强制关闭熔断器"""
        with self._state_lock:
            logger.info(f"熔断器[{self.name}]被强制关闭")
            self._state = CircuitBreakerState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_state_change_time = time.time()

    def get_state(self) -> str:
        """获取当前状态字符串"""
        return self._get_state().value

    def get_stats(self) -> Dict[str, Any]:
        """
        获取熔断器统计信息

        Returns:
            统计信息字典
        """
        with self._lock:
            return {
                'name': self.name,
                'state': self._get_state().value,
                'failure_threshold': self.failure_threshold,
                'recovery_timeout': self.recovery_timeout,
                'success_threshold': self.success_threshold,
                'max_concurrent_requests': self.max_concurrent_requests,
                'current_concurrent_requests': self._concurrent_requests,
                'failure_count': self._failure_count,
                'success_count': self._success_count,
                'total_requests': self._total_requests,
                'total_successes': self._total_successes,
                'total_failures': self._total_failures,
                'total_circuit_open': self._total_circuit_open,
                'last_failure_time': self._last_failure_time,
                'last_state_change_time': self._last_state_change_time,
                'failure_rate': round(self._total_failures / self._total_requests * 100, 2) if self._total_requests > 0 else 0.0
            }

    def __enter__(self):
        """上下文管理器进入"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出"""
        pass


class DatabaseCircuitBreaker(CircuitBreaker):
    """
    数据库连接专用熔断器

    针对数据库连接场景优化：
    - 默认配置适合数据库连接场景
    - 支持连接池集成
    """

    def __init__(self,
                 failure_threshold: int = 3,
                 recovery_timeout: int = 60,
                 success_threshold: int = 3,
                 max_concurrent_requests: int = 50,
                 fallback: Optional[Callable[..., Any]] = None,
                 name: str = 'database'):
        """
        初始化数据库熔断器

        Args:
            failure_threshold: 失败阈值，默认3次
            recovery_timeout: 恢复超时时间，默认60秒
            success_threshold: 成功阈值，默认3次
            max_concurrent_requests: 最大并发请求数，默认50
            fallback: 降级函数
            name: 熔断器名称
        """
        super().__init__(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            success_threshold=success_threshold,
            max_concurrent_requests=max_concurrent_requests,
            fallback=fallback,
            name=name
        )


# 全局默认数据库熔断器
DEFAULT_DB_CIRCUIT_BREAKER = DatabaseCircuitBreaker()


def with_circuit_breaker(circuit_breaker: CircuitBreaker = None):
    """
    装饰器：使用熔断器保护函数

    Args:
        circuit_breaker: 熔断器实例，默认使用全局数据库熔断器

    Returns:
        装饰器函数
    """
    cb = circuit_breaker or DEFAULT_DB_CIRCUIT_BREAKER

    def decorator(func: Callable[..., Any]):
        import functools

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                return await cb.call(func, *args, **kwargs)

            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return cb.call(func, *args, **kwargs)

        return wrapper

    return decorator
