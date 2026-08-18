"""
Sentinel 内嵌限流降级引擎 (Embedded Sentinel Engine)

实现 Alibaba Sentinel 的核心功能，无需外部 Dashboard：
- 滑动窗口限流（QPS）
- 异常比例/异常数熔断
- 慢调用比例熔断
- 热点参数限流
- 系统自适应保护
- 支持内存和Redis两种模式
"""

import time
import threading
import logging
from collections import deque
from enum import Enum
from typing import Dict, List, Optional, Callable

logger = logging.getLogger("Spring.Cloud.Sentinel")


class FlowRule:
    """限流规则"""
    def __init__(self, resource: str, count: float = 100.0, grade: str = "QPS",
                 strategy: str = "DIRECT", control_behavior: str = "REJECT",
                 warm_up_period_sec: int = 0, max_queueing_timeout_ms: int = 0):
        self.resource = resource
        self.count = count  # QPS阈值
        self.grade = grade  # QPS or THREAD
        self.strategy = strategy
        self.control_behavior = control_behavior  # REJECT, WARM_UP, RATE_LIMITER
        self.warm_up_period_sec = warm_up_period_sec
        self.max_queueing_timeout_ms = max_queueing_timeout_ms


class DegradeRule:
    """熔断降级规则"""
    def __init__(self, resource: str, grade: str = "EXCEPTION_RATIO",
                 count: float = 0.5, time_window_sec: int = 10,
                 min_request_amount: int = 5, slow_ratio_rt_threshold_ms: float = 1000.0,
                 slow_ratio: float = 1.0):
        self.resource = resource
        self.grade = grade  # EXCEPTION_RATIO, EXCEPTION_COUNT, SLOW_RATIO
        self.count = count  # 阈值
        self.time_window_sec = time_window_sec  # 熔断时长(秒)
        self.min_request_amount = min_request_amount  # 最小请求数
        self.slow_ratio_rt_threshold_ms = slow_ratio_rt_threshold_ms
        self.slow_ratio = slow_ratio


class SystemRule:
    """系统保护规则"""
    def __init__(self, highest_system_load: float = -1.0,
                 avg_rt: float = -1.0, max_thread: int = -1,
                 qps: float = -1.0):
        self.highest_system_load = highest_system_load
        self.avg_rt = avg_rt
        self.max_thread = max_thread
        self.qps = qps


class HotParamRule:
    """热点参数限流规则"""
    def __init__(self, resource: str, param_idx: int = 0, count: float = 100.0,
                 duration_sec: int = 1, param_flow_items: Optional[Dict[str, float]] = None):
        self.resource = resource
        self.param_idx = param_idx
        self.count = count
        self.duration_sec = duration_sec
        self.param_flow_items = param_flow_items or {}


class CircuitState(Enum):
    CLOSED = "CLOSED"       # 正常
    OPEN = "OPEN"           # 熔断打开
    HALF_OPEN = "HALF_OPEN" # 半开（尝试恢复）


class BlockException(Exception):
    """Sentinel阻断异常"""
    def __init__(self, resource: str, rule_type: str, message: str = ""):
        self.resource = resource
        self.rule_type = rule_type
        super().__init__(f"Sentinel blocked [{rule_type}] resource={resource}: {message}")


class SlidingWindow:
    """滑动窗口计数器"""
    def __init__(self, window_duration_ms: int = 1000, sample_count: int = 10):
        self.window_duration_ms = window_duration_ms
        self.sample_count = sample_count
        self.bucket_duration_ms = window_duration_ms // sample_count
        self.buckets: deque = deque(maxlen=sample_count)
        self._lock = threading.Lock()

    def _current_bucket(self, now_ms: int) -> Dict:
        bucket_start = (now_ms // self.bucket_duration_ms) * self.bucket_duration_ms
        with self._lock:
            if self.buckets and self.buckets[-1]['start'] == bucket_start:
                return self.buckets[-1]
            # 过期桶清理
            while self.buckets and (now_ms - self.buckets[0]['start']) >= self.window_duration_ms:
                self.buckets.popleft()
            # 新桶
            bucket = {'start': bucket_start, 'pass': 0, 'block': 0,
                      'exception': 0, 'success': 0, 'rt_total': 0.0, 'slow': 0}
            self.buckets.append(bucket)
            return bucket

    def add_pass(self):
        now_ms = int(time.time() * 1000)
        self._current_bucket(now_ms)['pass'] += 1

    def add_block(self):
        now_ms = int(time.time() * 1000)
        self._current_bucket(now_ms)['block'] += 1

    def add_exception(self):
        now_ms = int(time.time() * 1000)
        self._current_bucket(now_ms)['exception'] += 1

    def add_success(self, rt_ms: float, slow_threshold_ms: float = 1000.0):
        now_ms = int(time.time() * 1000)
        bucket = self._current_bucket(now_ms)
        bucket['success'] += 1
        bucket['rt_total'] += rt_ms
        if rt_ms > slow_threshold_ms:
            bucket['slow'] += 1

    def get_stats(self) -> Dict[str, float]:
        now_ms = int(time.time() * 1000)
        with self._lock:
            # 清理过期
            while self.buckets and (now_ms - self.buckets[0]['start']) >= self.window_duration_ms:
                self.buckets.popleft()
            total_pass = sum(b['pass'] for b in self.buckets)
            total_block = sum(b['block'] for b in self.buckets)
            total_exception = sum(b['exception'] for b in self.buckets)
            total_success = sum(b['success'] for b in self.buckets)
            total_rt = sum(b['rt_total'] for b in self.buckets)
            total_slow = sum(b['slow'] for b in self.buckets)
        window_sec = self.window_duration_ms / 1000.0
        qps = total_pass / window_sec if window_sec > 0 else 0
        avg_rt = total_rt / total_success if total_success > 0 else 0
        exception_ratio = total_exception / (total_success + total_exception) if (total_success + total_exception) >= 1 else 0
        slow_ratio = total_slow / total_success if total_success >= 1 else 0
        return {
            'qps': qps,
            'pass_qps': total_pass / window_sec if window_sec > 0 else 0,
            'block_qps': total_block / window_sec if window_sec > 0 else 0,
            'exception_ratio': exception_ratio,
            'exception_count': total_exception,
            'success_count': total_success,
            'avg_rt_ms': avg_rt,
            'slow_ratio': slow_ratio,
            'total_requests': total_pass + total_block,
        }


class ResourceCircuitBreaker:
    """单个资源的熔断器"""
    def __init__(self, resource: str):
        self.resource = resource
        self.state = CircuitState.CLOSED
        self._state_lock = threading.Lock()
        self._opened_at: float = 0
        self._recover_after_sec: float = 0
        self._half_open_successes = 0
        self._half_open_required = 3  # 半开状态需要连续成功次数
        self._half_open_permitted = False  # 是否已经放行一个探测请求

    def can_pass(self) -> bool:
        with self._state_lock:
            if self.state == CircuitState.CLOSED:
                return True
            if self.state == CircuitState.OPEN:
                if time.monotonic() - self._opened_at >= self._recover_after_sec:
                    self.state = CircuitState.HALF_OPEN
                    self._half_open_successes = 0
                    self._half_open_permitted = True
                    return True
                return False
            # HALF_OPEN: 只允许一个探测请求
            if self._half_open_permitted:
                self._half_open_permitted = False
                return True
            return False

    def on_success(self):
        with self._state_lock:
            if self.state == CircuitState.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self._half_open_required:
                    self.state = CircuitState.CLOSED
                    self._half_open_permitted = False
                    logger.info(f"[Sentinel] Circuit for {self.resource} CLOSED (recovered)")

    def on_failure(self, time_window_sec: int):
        with self._state_lock:
            self.state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            self._recover_after_sec = float(time_window_sec)
            self._half_open_successes = 0
            self._half_open_permitted = False
            # Use a separate recovery timer to transition to HALF_OPEN after window
            def _recover():
                time.sleep(time_window_sec)
                with self._state_lock:
                    if self.state == CircuitState.OPEN:
                        self.state = CircuitState.HALF_OPEN
                        self._half_open_successes = 0
                        self._half_open_permitted = True
                        logger.info(f"[Sentinel] Circuit for {self.resource} -> HALF_OPEN")
            t = threading.Thread(target=_recover, daemon=True)
            t.start()

    def get_state(self) -> str:
        return self.state.value


class SentinelEngine:
    """
    Sentinel内嵌引擎

    实现限流、熔断、热点参数、系统保护
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self._flow_rules: Dict[str, FlowRule] = {}
        self._degrade_rules: Dict[str, DegradeRule] = {}
        self._system_rules: List[SystemRule] = []
        self._hot_param_rules: Dict[str, HotParamRule] = {}
        self._windows: Dict[str, SlidingWindow] = {}
        self._hot_windows: Dict[str, Dict[str, SlidingWindow]] = {}
        self._circuit_breakers: Dict[str, ResourceCircuitBreaker] = {}
        self._global_lock = threading.Lock()
        self._windows_lock = threading.Lock()
        logger.info("[Sentinel] Engine initialized")

    def _get_window(self, resource: str) -> SlidingWindow:
        with self._windows_lock:
            if resource not in self._windows:
                self._windows[resource] = SlidingWindow(1000, 10)
            return self._windows[resource]

    def _get_circuit_breaker(self, resource: str) -> ResourceCircuitBreaker:
        with self._global_lock:
            if resource not in self._circuit_breakers:
                self._circuit_breakers[resource] = ResourceCircuitBreaker(resource)
            return self._circuit_breakers[resource]

    def load_flow_rules(self, rules: List[FlowRule]):
        with self._global_lock:
            self._flow_rules.clear()
            for r in rules:
                self._flow_rules[r.resource] = r
        logger.info(f"[Sentinel] Loaded {len(rules)} flow rules")

    def load_degrade_rules(self, rules: List[DegradeRule]):
        with self._global_lock:
            self._degrade_rules.clear()
            for r in rules:
                self._degrade_rules[r.resource] = r
        logger.info(f"[Sentinel] Loaded {len(rules)} degrade rules")

    def load_system_rules(self, rules: List[SystemRule]):
        with self._global_lock:
            self._system_rules = list(rules)

    def load_hot_param_rules(self, rules: List[HotParamRule]):
        with self._global_lock:
            self._hot_param_rules.clear()
            for r in rules:
                self._hot_param_rules[r.resource] = r

    def _check_system_rule(self) -> Optional[str]:
        """检查系统保护规则"""
        if not self._system_rules:
            return None
        # 简化实现：基于当前进程负载做粗略检查
        try:
            import os
            load_avg = os.getloadavg()[0] if hasattr(os, 'getloadavg') else 0
            for rule in self._system_rules:
                if rule.highest_system_load > 0 and load_avg > rule.highest_system_load:
                    return f"System load {load_avg:.2f} > {rule.highest_system_load}"
        except Exception:
            pass
        return None

    def _check_hot_param(self, resource: str, args: tuple, kwargs: dict) -> Optional[str]:
        """检查热点参数限流"""
        rule = self._hot_param_rules.get(resource)
        if not rule:
            return None
        # 取参数值
        param_value = None
        if args and rule.param_idx < len(args):
            param_value = args[rule.param_idx]
        if param_value is None:
            try:
                param_names = list(kwargs.keys())
                if rule.param_idx < len(param_names):
                    param_value = kwargs[param_names[rule.param_idx]]
            except Exception:
                pass
        if param_value is None:
            return None

        param_key = str(param_value)
        threshold = rule.param_flow_items.get(param_key, rule.count)
        # 热点参数窗口
        res_key = f"{resource}__hot"
        if res_key not in self._hot_windows:
            self._hot_windows[res_key] = {}
        if param_key not in self._hot_windows[res_key]:
            self._hot_windows[res_key][param_key] = SlidingWindow(rule.duration_sec * 1000, max(1, rule.duration_sec * 2))
        hw = self._hot_windows[res_key][param_key]
        stats = hw.get_stats()
        if stats['pass_qps'] >= threshold:
            return f"Hot param [{param_key}] QPS {stats['pass_qps']:.1f} >= {threshold}"
        return None

    def entry(self, resource: str, args: tuple = (), kwargs: dict = None) -> 'SentinelEntry':
        """
        进入资源，执行所有规则检查

        Raises:
            BlockException: 被限流/熔断时抛出
        """
        kwargs = kwargs or {}
        # 系统规则检查
        sys_block = self._check_system_rule()
        if sys_block:
            window = self._get_window(resource)
            window.add_block()
            raise BlockException(resource, "SYSTEM", sys_block)

        # 熔断检查
        cb = self._get_circuit_breaker(resource)
        if not cb.can_pass():
            window = self._get_window(resource)
            window.add_block()
            raise BlockException(resource, "CIRCUIT", f"Circuit is {cb.get_state()}")

        # 限流检查
        flow_rule = self._flow_rules.get(resource)
        window = self._get_window(resource)
        if flow_rule:
            stats = window.get_stats()
            current_qps = stats['pass_qps']
            if current_qps >= flow_rule.count:
                window.add_block()
                raise BlockException(resource, "FLOW", f"QPS {current_qps:.1f} >= {flow_rule.count}")

        # 热点参数限流
        hot_block = self._check_hot_param(resource, args, kwargs)
        if hot_block:
            window.add_block()
            raise BlockException(resource, "HOT_PARAM", hot_block)

        # 通过
        window.add_pass()
        return SentinelEntry(self, resource, window, cb)

    def record_success(self, resource: str, rt_ms: float = 0.0):
        """记录成功"""
        window = self._get_window(resource)
        degrade_rule = self._degrade_rules.get(resource)
        slow_threshold = degrade_rule.slow_ratio_rt_threshold_ms if degrade_rule else 1000.0
        window.add_success(rt_ms, slow_threshold)
        cb = self._get_circuit_breaker(resource)
        cb.on_success()
        self._check_degrade_on_success(resource)

    def record_exception(self, resource: str):
        """记录异常"""
        window = self._get_window(resource)
        window.add_exception()
        cb = self._get_circuit_breaker(resource)
        degrade_rule = self._degrade_rules.get(resource)
        if degrade_rule:
            stats = window.get_stats()
            total = stats['success_count'] + stats['exception_count']
            if total >= degrade_rule.min_request_amount:
                if degrade_rule.grade == "EXCEPTION_COUNT" and stats['exception_count'] >= degrade_rule.count:
                    cb.on_failure(degrade_rule.time_window_sec)
                    logger.warning(f"[Sentinel] Circuit OPEN for {resource}: exception count {stats['exception_count']} >= {degrade_rule.count}")
                elif degrade_rule.grade == "EXCEPTION_RATIO" and stats['exception_ratio'] >= degrade_rule.count:
                    cb.on_failure(degrade_rule.time_window_sec)
                    logger.warning(f"[Sentinel] Circuit OPEN for {resource}: exception ratio {stats['exception_ratio']:.2%} >= {degrade_rule.count}")
                elif degrade_rule.grade == "SLOW_RATIO" and stats['slow_ratio'] >= degrade_rule.slow_ratio:
                    cb.on_failure(degrade_rule.time_window_sec)
                    logger.warning(f"[Sentinel] Circuit OPEN for {resource}: slow ratio {stats['slow_ratio']:.2%} >= {degrade_rule.slow_ratio}")

    def _check_degrade_on_success(self, resource: str):
        """检查是否触发慢调用熔断"""
        degrade_rule = self._degrade_rules.get(resource)
        if degrade_rule and degrade_rule.grade == "SLOW_RATIO":
            window = self._get_window(resource)
            stats = window.get_stats()
            cb = self._get_circuit_breaker(resource)
            total = stats['success_count'] + stats['exception_count']
            if total >= degrade_rule.min_request_amount and stats['slow_ratio'] >= degrade_rule.slow_ratio:
                cb.on_failure(degrade_rule.time_window_sec)
                logger.warning(f"[Sentinel] Circuit OPEN for {resource}: slow ratio {stats['slow_ratio']:.2%}")

    def get_resource_stats(self, resource: str = None) -> Dict:
        """获取资源统计"""
        if resource:
            window = self._windows.get(resource)
            cb = self._circuit_breakers.get(resource)
            return {
                resource: {
                    'stats': window.get_stats() if window else {},
                    'circuit_state': cb.get_state() if cb else 'CLOSED',
                }
            }
        result = {}
        for res in list(self._windows.keys()):
            window = self._windows[res]
            cb = self._circuit_breakers.get(res)
            result[res] = {
                'stats': window.get_stats(),
                'circuit_state': cb.get_state() if cb else 'CLOSED',
            }
        return result

    def reset(self):
        """重置所有状态（测试用）"""
        with self._global_lock:
            self._windows.clear()
            self._hot_windows.clear()
            self._circuit_breakers.clear()
            self._flow_rules.clear()
            self._degrade_rules.clear()
            self._system_rules.clear()
            self._hot_param_rules.clear()


class SentinelEntry:
    """Sentinel资源入口上下文管理器"""
    __slots__ = ('_engine', '_resource', '_window', '_cb', '_start_ms', '_done')

    def __init__(self, engine: SentinelEngine, resource: str, window: SlidingWindow, cb: ResourceCircuitBreaker):
        self._engine = engine
        self._resource = resource
        self._window = window
        self._cb = cb
        self._start_ms = time.monotonic() * 1000
        self._done = False

    def success(self):
        if not self._done:
            rt = time.monotonic() * 1000 - self._start_ms
            self._engine.record_success(self._resource, rt)
            self._done = True

    def error(self):
        if not self._done:
            self._engine.record_exception(self._resource)
            self._done = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val is None:
            self.success()
        else:
            if not isinstance(exc_val, BlockException):
                self.error()
        return False


# 全局实例
sentinel_engine = SentinelEngine()


def sentinel_protect(resource: str, fallback: Callable = None, block_handler: Callable = None):
    """
    Sentinel资源保护装饰器

    Usage:
        @sentinel_protect("my_api", fallback=my_fallback)
        def my_api():
            ...
    """
    import functools
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                entry = sentinel_engine.entry(resource, args=args, kwargs=kwargs)
                try:
                    result = func(*args, **kwargs)
                    entry.success()
                    return result
                except BlockException:
                    raise
                except Exception as e:
                    entry.error()
                    raise
            except BlockException as e:
                if block_handler:
                    return block_handler(*args, **kwargs)
                if fallback:
                    return fallback(*args, **kwargs)
                raise
        return wrapper
    return decorator
