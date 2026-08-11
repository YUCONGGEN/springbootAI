"""
Prometheus监控模块
提供指标暴露和采集功能
"""
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Summary,
    generate_latest,
)
from prometheus_client.exposition import start_http_server
import logging
import os

logger = logging.getLogger("Spring.Monitoring.Prometheus")


class PrometheusMetrics:
    """Prometheus指标管理器"""
    
    _instance = None
    _lock = __import__('threading').Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, namespace: str = "spring", subsystem: str = "python"):
        if hasattr(self, '_initialized'):
            return
        self.namespace = namespace
        self.subsystem = subsystem
        self._registry = CollectorRegistry()
        self._metric_registry = self._registry
        if os.getenv('PROMETHEUS_MULTIPROC_DIR'):
            from prometheus_client import multiprocess
            multiprocess.MultiProcessCollector(self._registry)
            # Metrics write their values to multiprocess files and must not also
            # register live collectors in the exposition registry.
            self._metric_registry = None
        self._metrics: dict = {}
        self._initialized = True

    def configure(self, namespace: str, subsystem: str) -> None:
        if self._metrics and (namespace != self.namespace or subsystem != self.subsystem):
            raise RuntimeError("Prometheus namespace/subsystem cannot change after metrics are created")
        self.namespace = namespace
        self.subsystem = subsystem
    
    def create_counter(self, name: str, documentation: str, labelnames: list = None) -> Counter:
        """
        创建计数器指标
        
        Args:
            name: 指标名称
            documentation: 指标描述
            labelnames: 标签名称列表
        
        Returns:
            Counter对象
        """
        key = f"{self.namespace}_{self.subsystem}_{name}"
        if key not in self._metrics:
            self._metrics[key] = Counter(
                name=name,
                documentation=documentation,
                labelnames=labelnames or [],
                namespace=self.namespace,
                subsystem=self.subsystem,
                registry=self._metric_registry,
            )
        return self._metrics[key]
    
    def create_gauge(self, name: str, documentation: str, labelnames: list = None) -> Gauge:
        """
        创建仪表盘指标
        
        Args:
            name: 指标名称
            documentation: 指标描述
            labelnames: 标签名称列表
        
        Returns:
            Gauge对象
        """
        key = f"{self.namespace}_{self.subsystem}_{name}"
        if key not in self._metrics:
            self._metrics[key] = Gauge(
                name=name,
                documentation=documentation,
                labelnames=labelnames or [],
                namespace=self.namespace,
                subsystem=self.subsystem,
                registry=self._metric_registry,
            )
        return self._metrics[key]
    
    def create_histogram(self, name: str, documentation: str, labelnames: list = None, 
                         buckets: list = None) -> Histogram:
        """
        创建直方图指标
        
        Args:
            name: 指标名称
            documentation: 指标描述
            labelnames: 标签名称列表
            buckets: 桶边界列表
        
        Returns:
            Histogram对象
        """
        key = f"{self.namespace}_{self.subsystem}_{name}"
        if key not in self._metrics:
            self._metrics[key] = Histogram(
                name=name,
                documentation=documentation,
                labelnames=labelnames or [],
                buckets=buckets or Histogram.DEFAULT_BUCKETS,
                namespace=self.namespace,
                subsystem=self.subsystem,
                registry=self._metric_registry,
            )
        return self._metrics[key]
    
    def create_summary(self, name: str, documentation: str, labelnames: list = None,
                       objectives: dict = None) -> Summary:
        """
        创建摘要指标
        
        Args:
            name: 指标名称
            documentation: 指标描述
            labelnames: 标签名称列表
            objectives: 分位数目标
        
        Returns:
            Summary对象
        """
        key = f"{self.namespace}_{self.subsystem}_{name}"
        if key not in self._metrics:
            self._metrics[key] = Summary(
                name=name,
                documentation=documentation,
                labelnames=labelnames or [],
                objectives=objectives or Summary.DEFAULT_OBJECTIVES,
                namespace=self.namespace,
                subsystem=self.subsystem,
                registry=self._metric_registry,
            )
        return self._metrics[key]
    
    def get_metrics(self) -> dict:
        """获取所有指标"""
        return self._metrics
    
    def get_registry(self) -> CollectorRegistry:
        """获取指标注册表"""
        return self._registry
    
    def generate_metrics_data(self) -> bytes:
        """生成Prometheus格式的指标数据"""
        return generate_latest(self._registry)
    
    def start_server(self, port: int = 8000):
        """
        启动Prometheus指标暴露HTTP服务器
        
        Args:
            port: 监听端口
        """
        start_http_server(port, registry=self._registry)
        logger.info(f"Prometheus metrics server started on port {port}")


# 创建全局Prometheus指标管理器实例
prometheus_metrics = PrometheusMetrics()


def init_prometheus(config: dict) -> None:
    """
    初始化Prometheus配置
    
    Args:
        config: 配置字典，包含namespace, subsystem, port等
    """
    prometheus_metrics.configure(
        namespace=config.get('namespace', 'spring'),
        subsystem=config.get('subsystem', 'python'),
    )
    # 默认通过主应用 /actuator/prometheus 暴露，避免多 worker 争抢端口。
    if config.get('standalone_server', False):
        prometheus_metrics.start_server(config.get('port', 8000))
