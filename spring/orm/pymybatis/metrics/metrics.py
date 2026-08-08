"""
PyMyBatis监控指标模块

提供Prometheus兼容的指标收集和导出功能

核心指标类型：
- Counter: 计数器，只能递增
- Gauge: 仪表盘，可以增减
- Histogram: 直方图，统计分布
- Timer: 计时器，基于直方图

导出格式：
- Prometheus文本格式
- JSON格式
"""

import time
import threading
import logging
from typing import Dict, Any, List, Optional, Callable
from collections import defaultdict

logger = logging.getLogger(__name__)


class Counter:
    """计数器指标"""

    def __init__(self, name: str, help_text: str, labels: Optional[List[str]] = None):
        """
        初始化计数器

        Args:
            name: 指标名称
            help_text: 帮助文本
            labels: 标签列表
        """
        self.name = name
        self.help_text = help_text
        self.labels = labels or []
        self._values: Dict[str, float] = defaultdict(float)
        self._lock = threading.RLock()

    def inc(self, value: float = 1.0, **labels):
        """
        增加计数

        Args:
            value: 增加的值
            **labels: 标签值
        """
        key = self._generate_key(labels)
        with self._lock:
            self._values[key] += value

    def reset(self, **labels):
        """重置计数"""
        key = self._generate_key(labels)
        with self._lock:
            self._values[key] = 0.0

    def get(self, **labels) -> float:
        """获取当前值"""
        key = self._generate_key(labels)
        return self._values[key]

    def _generate_key(self, labels: Dict[str, Any]) -> str:
        """生成标签key"""
        if not self.labels:
            return ''
        return ','.join([f"{k}={labels.get(k, '')}" for k in self.labels])

    def to_prometheus(self) -> str:
        """转换为Prometheus格式"""
        lines = []
        lines.append(f"# HELP {self.name} {self.help_text}")
        lines.append(f"# TYPE {self.name} counter")

        for key, value in self._values.items():
            if key:
                label_parts = []
                for part in key.split(','):
                    k, v = part.split('=', 1)
                    label_parts.append(f'{k}="{v}"')
                label_str = '{' + ','.join(label_parts) + '}'
                lines.append(f"{self.name}{label_str} {value}")
            else:
                lines.append(f"{self.name} {value}")

        return '\n'.join(lines)


class Gauge:
    """仪表盘指标"""

    def __init__(self, name: str, help_text: str, labels: Optional[List[str]] = None):
        """
        初始化仪表盘

        Args:
            name: 指标名称
            help_text: 帮助文本
            labels: 标签列表
        """
        self.name = name
        self.help_text = help_text
        self.labels = labels or []
        self._values: Dict[str, float] = defaultdict(float)
        self._lock = threading.RLock()

    def set(self, value: float, **labels):
        """设置值"""
        key = self._generate_key(labels)
        with self._lock:
            self._values[key] = value

    def inc(self, value: float = 1.0, **labels):
        """增加"""
        key = self._generate_key(labels)
        with self._lock:
            self._values[key] += value

    def dec(self, value: float = 1.0, **labels):
        """减少"""
        key = self._generate_key(labels)
        with self._lock:
            self._values[key] -= value

    def get(self, **labels) -> float:
        """获取当前值"""
        key = self._generate_key(labels)
        return self._values[key]

    def _generate_key(self, labels: Dict[str, Any]) -> str:
        """生成标签key"""
        if not self.labels:
            return ''
        return ','.join([f"{k}={labels.get(k, '')}" for k in self.labels])

    def to_prometheus(self) -> str:
        """转换为Prometheus格式"""
        lines = []
        lines.append(f"# HELP {self.name} {self.help_text}")
        lines.append(f"# TYPE {self.name} gauge")

        for key, value in self._values.items():
            if key:
                label_parts = []
                for part in key.split(','):
                    k, v = part.split('=', 1)
                    label_parts.append(f'{k}="{v}"')
                label_str = '{' + ','.join(label_parts) + '}'
                lines.append(f"{self.name}{label_str} {value}")
            else:
                lines.append(f"{self.name} {value}")

        return '\n'.join(lines)


class Histogram:
    """直方图指标"""

    def __init__(self, name: str, help_text: str,
                 buckets: Optional[List[float]] = None,
                 labels: Optional[List[str]] = None):
        """
        初始化直方图

        Args:
            name: 指标名称
            help_text: 帮助文本
            buckets: 桶边界
            labels: 标签列表
        """
        self.name = name
        self.help_text = help_text
        self.buckets = buckets or [0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0]
        self.labels = labels or []

        # 每个标签组合对应一组桶
        self._buckets: Dict[str, List[int]] = defaultdict(lambda: [0] * (len(self.buckets) + 1))
        self._sums: Dict[str, float] = defaultdict(float)
        self._counts: Dict[str, int] = defaultdict(int)
        self._lock = threading.RLock()

    def observe(self, value: float, **labels):
        """
        观察值

        Args:
            value: 观察的值
            **labels: 标签值
        """
        key = self._generate_key(labels)

        with self._lock:
            self._counts[key] += 1
            self._sums[key] += value

            # 更新桶计数
            buckets = self._buckets[key]
            for i, bucket in enumerate(self.buckets):
                if value <= bucket:
                    buckets[i] += 1
            buckets[-1] += 1  # +Inf桶

    def get_counts(self, **labels) -> List[int]:
        """获取桶计数"""
        key = self._generate_key(labels)
        return list(self._buckets[key])

    def get_sum(self, **labels) -> float:
        """获取总和"""
        key = self._generate_key(labels)
        return self._sums[key]

    def get_count(self, **labels) -> int:
        """获取计数"""
        key = self._generate_key(labels)
        return self._counts[key]

    def _generate_key(self, labels: Dict[str, Any]) -> str:
        """生成标签key"""
        if not self.labels:
            return ''
        return ','.join([f"{k}={labels.get(k, '')}" for k in self.labels])

    def to_prometheus(self) -> str:
        """转换为Prometheus格式"""
        lines = []
        lines.append(f"# HELP {self.name} {self.help_text}")
        lines.append(f"# TYPE {self.name} histogram")

        for key, buckets in self._buckets.items():
            # 解析标签
            label_items = []
            if key:
                for part in key.split(','):
                    k, v = part.split('=', 1)
                    label_items.append(f'{k}="{v}"')

            # 输出桶
            for i, bucket in enumerate(self.buckets):
                bucket_labels = label_items + [f'le="{bucket}"']
                bucket_label_str = '{' + ','.join(bucket_labels) + '}'
                lines.append(f"{self.name}_bucket{bucket_label_str} {buckets[i]}")

            # +Inf桶
            inf_labels = label_items + ['le="+Inf"']
            inf_label_str = '{' + ','.join(inf_labels) + '}'
            lines.append(f"{self.name}_bucket{inf_label_str} {buckets[-1]}")

            # sum和count
            base_label_str = '{' + ','.join(label_items) + '}' if label_items else ''
            lines.append(f"{self.name}_sum{base_label_str} {self._sums[key]}")
            lines.append(f"{self.name}_count{base_label_str} {self._counts[key]}")

        return '\n'.join(lines)


class Timer:
    """计时器指标"""

    def __init__(self, name: str, help_text: str,
                 buckets: Optional[List[float]] = None,
                 labels: Optional[List[str]] = None):
        """
        初始化计时器

        Args:
            name: 指标名称
            help_text: 帮助文本
            buckets: 桶边界（秒）
            labels: 标签列表
        """
        self._histogram = Histogram(name, help_text, buckets, labels)

    def observe(self, duration: float, **labels):
        """观察耗时（秒）"""
        self._histogram.observe(duration, **labels)

    def time(self, **labels) -> 'TimerContext':
        """
        上下文管理器，自动计时

        Returns:
            计时器上下文
        """
        return TimerContext(self, labels)

    def to_prometheus(self) -> str:
        """转换为Prometheus格式"""
        return self._histogram.to_prometheus()


class TimerContext:
    """计时器上下文管理器"""

    def __init__(self, timer: Timer, labels: Dict[str, Any]):
        self._timer = timer
        self._labels = labels
        self._start_time = None

    def __enter__(self):
        """进入上下文，开始计时"""
        self._start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文，记录耗时"""
        if self._start_time is not None:
            duration = time.time() - self._start_time
            self._timer.observe(duration, **self._labels)


class MetricsCollector:
    """
    指标收集器

    收集和管理所有指标，支持Prometheus格式导出
    """

    def __init__(self):
        """初始化指标收集器"""
        self._counters: Dict[str, Counter] = {}
        self._gauges: Dict[str, Gauge] = {}
        self._histograms: Dict[str, Histogram] = {}
        self._timers: Dict[str, Timer] = {}
        self._lock = threading.RLock()

    def counter(self, name: str, help_text: str, labels: Optional[List[str]] = None) -> Counter:
        """
        获取或创建计数器

        Args:
            name: 指标名称
            help_text: 帮助文本
            labels: 标签列表

        Returns:
            计数器实例
        """
        with self._lock:
            if name not in self._counters:
                self._counters[name] = Counter(name, help_text, labels)
            return self._counters[name]

    def gauge(self, name: str, help_text: str, labels: Optional[List[str]] = None) -> Gauge:
        """
        获取或创建仪表盘

        Args:
            name: 指标名称
            help_text: 帮助文本
            labels: 标签列表

        Returns:
            仪表盘实例
        """
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = Gauge(name, help_text, labels)
            return self._gauges[name]

    def histogram(self, name: str, help_text: str,
                  buckets: Optional[List[float]] = None,
                  labels: Optional[List[str]] = None) -> Histogram:
        """
        获取或创建直方图

        Args:
            name: 指标名称
            help_text: 帮助文本
            buckets: 桶边界
            labels: 标签列表

        Returns:
            直方图实例
        """
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = Histogram(name, help_text, buckets, labels)
            return self._histograms[name]

    def timer(self, name: str, help_text: str,
              buckets: Optional[List[float]] = None,
              labels: Optional[List[str]] = None) -> Timer:
        """
        获取或创建计时器

        Args:
            name: 指标名称
            help_text: 帮助文本
            buckets: 桶边界（秒）
            labels: 标签列表

        Returns:
            计时器实例
        """
        with self._lock:
            if name not in self._timers:
                self._timers[name] = Timer(name, help_text, buckets, labels)
            return self._timers[name]

    def collect(self) -> List[str]:
        """
        收集所有指标

        Returns:
            指标字符串列表
        """
        lines = []

        for counter in self._counters.values():
            lines.append(counter.to_prometheus())

        for gauge in self._gauges.values():
            lines.append(gauge.to_prometheus())

        for histogram in self._histograms.values():
            lines.append(histogram.to_prometheus())

        for timer in self._timers.values():
            lines.append(timer.to_prometheus())

        return lines

    def to_prometheus(self) -> str:
        """
        转换为Prometheus文本格式

        Returns:
            Prometheus格式字符串
        """
        return '\n'.join(self.collect()) + '\n'

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典格式

        Returns:
            指标字典
        """
        result = {}

        # 计数器
        result['counters'] = {}
        for name, counter in self._counters.items():
            result['counters'][name] = {
                'help': counter.help_text,
                'labels': counter.labels,
                'values': dict(counter._values)
            }

        # 仪表盘
        result['gauges'] = {}
        for name, gauge in self._gauges.items():
            result['gauges'][name] = {
                'help': gauge.help_text,
                'labels': gauge.labels,
                'values': dict(gauge._values)
            }

        # 直方图
        result['histograms'] = {}
        for name, histogram in self._histograms.items():
            result['histograms'][name] = {
                'help': histogram.help_text,
                'labels': histogram.labels,
                'buckets': histogram.buckets,
                'data': {}
            }

        # 计时器
        result['timers'] = {}
        for name, timer in self._timers.items():
            result['timers'][name] = {
                'help': timer._histogram.help_text,
                'labels': timer._histogram.labels,
                'buckets': timer._histogram.buckets
            }

        return result

    def reset(self):
        """重置所有指标"""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self._timers.clear()


# 全局默认指标收集器
_global_collector = MetricsCollector()


def get_default_collector() -> MetricsCollector:
    """
    获取全局默认指标收集器

    Returns:
        指标收集器实例
    """
    return _global_collector


# 便捷函数
def counter(name: str, help_text: str, labels: Optional[List[str]] = None) -> Counter:
    """便捷函数：获取或创建计数器"""
    return _global_collector.counter(name, help_text, labels)


def gauge(name: str, help_text: str, labels: Optional[List[str]] = None) -> Gauge:
    """便捷函数：获取或创建仪表盘"""
    return _global_collector.gauge(name, help_text, labels)


def histogram(name: str, help_text: str,
              buckets: Optional[List[float]] = None,
              labels: Optional[List[str]] = None) -> Histogram:
    """便捷函数：获取或创建直方图"""
    return _global_collector.histogram(name, help_text, buckets, labels)


def timer(name: str, help_text: str,
          buckets: Optional[List[float]] = None,
          labels: Optional[List[str]] = None) -> Timer:
    """便捷函数：获取或创建计时器"""
    return _global_collector.timer(name, help_text, buckets, labels)


# 预定义的PyMyBatis核心指标
# 查询计数
QUERY_COUNTER = counter(
    'pymybatis_query_total',
    'Total number of SQL queries executed',
    labels=['operation', 'table', 'status']
)

# 查询耗时
QUERY_TIMER = timer(
    'pymybatis_query_duration_seconds',
    'Duration of SQL queries in seconds',
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0],
    labels=['operation', 'table']
)

# 连接池活跃连接数
ACTIVE_CONNECTIONS = gauge(
    'pymybatis_connection_pool_active_connections',
    'Number of active connections in the pool',
    labels=['pool']
)

# 连接池空闲连接数
IDLE_CONNECTIONS = gauge(
    'pymybatis_connection_pool_idle_connections',
    'Number of idle connections in the pool',
    labels=['pool']
)

# 缓存命中率
CACHE_HIT_COUNTER = counter(
    'pymybatis_cache_hits_total',
    'Total number of cache hits',
    labels=['cache_type']
)

CACHE_MISS_COUNTER = counter(
    'pymybatis_cache_misses_total',
    'Total number of cache misses',
    labels=['cache_type']
)

# 事务计数
TRANSACTION_COUNTER = counter(
    'pymybatis_transactions_total',
    'Total number of transactions',
    labels=['status']
)

# 熔断器状态
CIRCUIT_BREAKER_STATE = gauge(
    'pymybatis_circuit_breaker_state',
    'Circuit breaker state (0=closed, 1=open, 2=half-open)',
    labels=['name']
)

# 熔断器失败率
CIRCUIT_BREAKER_FAILURE_RATE = gauge(
    'pymybatis_circuit_breaker_failure_rate',
    'Circuit breaker failure rate percentage',
    labels=['name']
)