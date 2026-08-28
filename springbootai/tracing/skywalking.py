"""
SkyWalking分布式追踪模块
集成SkyWalking实现分布式链路追踪
"""
import logging
import threading
import time
import uuid
from typing import Any, Dict

from springbootai.logging.context import safe_log_field, sanitize_url

logger = logging.getLogger("Spring.Tracing.SkyWalking")

# 可选导入SkyWalking
try:
    from skywalking import agent, config
    from skywalking.trace import context, tag
    from skywalking.trace.carrier import Carrier
    _skywalking_available = True
except ImportError:
    agent = None
    config = None
    context = None
    tag = None
    Carrier = None
    _skywalking_available = False


class SkyWalkingTracer:
    """SkyWalking追踪器"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, service_name: str = "spring-python-app", 
                 collector_address: str = "127.0.0.1:11800"):
        if hasattr(self, '_initialized'):
            return
        self.service_name = service_name
        self.collector_address = collector_address
        self._initialized = False
        self._local_context = threading.local()
        
        # Agent startup is explicit via ``init_skywalking``. Starting a
        # telemetry process at module import used default values before the
        # application configuration was available and made late config a no-op.

    def configure(self, service_name: str, collector_address: str) -> None:
        self.service_name = str(service_name or "spring-python-app")
        self.collector_address = str(
            collector_address or "127.0.0.1:11800")
        if _skywalking_available and not self._initialized:
            self._init_skywalking()
    
    def _init_skywalking(self):
        """初始化SkyWalking Agent"""
        try:
            # 配置SkyWalking
            config.service_name = self.service_name
            config.collector_address = self.collector_address
            config.protocol = 'grpc'
            
            # 启动SkyWalking Agent
            agent.start()
            
            self._initialized = True
            collector = (
                sanitize_url(self.collector_address)
                if "://" in self.collector_address
                else safe_log_field(self.collector_address)
            )
            logger.info(
                "[SkyWalking] Agent started service=%s collector=%s",
                safe_log_field(self.service_name), collector,
            )
        except Exception as exc:
            logger.warning(
                "[SkyWalking] Initialization failed error_type=%s; "
                "falling back to local tracing",
                type(exc).__name__,
            )
            self._initialized = False
    
    def create_span(self, operation_name: str, span_type: str = "Local", 
                    peer: str = "") -> Any:
        """
        创建Span
        
        参数：
            operation_name: 操作名称
            span_type: Span类型（Local/Remote/DB/MQ等）
            peer: 对端地址
        
        返回：
            Span对象
        """
        if _skywalking_available and self._initialized:
            # 使用SkyWalking创建Span
            try:
                span = context.create_entry_span(operation_name, Carrier())
                span.tag(tag.Tag(key="span.type", val=span_type))
                if peer:
                    span.tag(tag.Tag(key="peer", val=peer))
                return span
            except Exception as exc:
                logger.warning(
                    "[SkyWalking] Create span failed operation=%s error_type=%s",
                    safe_log_field(operation_name), type(exc).__name__,
                )
        
        # 回退到本地Span
        return LocalSpan(operation_name, span_type, peer)
    
    def create_exit_span(self, operation_name: str, peer: str) -> Any:
        """
        创建Exit Span（调用外部服务）
        
        参数：
            operation_name: 操作名称
            peer: 对端地址
        
        返回：
            Span对象
        """
        if _skywalking_available and self._initialized:
            try:
                span = context.create_exit_span(operation_name, peer, Carrier())
                return span
            except Exception as exc:
                logger.warning(
                    "[SkyWalking] Create exit span failed operation=%s "
                    "error_type=%s",
                    safe_log_field(operation_name), type(exc).__name__,
                )
        
        # 回退到本地Span
        return LocalSpan(operation_name, "Remote", peer)
    
    def get_trace_id(self) -> str:
        """获取当前Trace ID"""
        if _skywalking_available and self._initialized:
            try:
                active_span = context.get_active_span()
                if active_span:
                    return str(active_span.trace_id)
            except Exception as exc:
                logger.warning(
                    "[SkyWalking] Get trace ID failed error_type=%s",
                    type(exc).__name__,
                )
        
        # 回退到本地Trace ID
        return getattr(self._local_context, 'trace_id', "")
    
    def set_trace_id(self, trace_id: str):
        """设置当前Trace ID"""
        self._local_context.trace_id = trace_id
    
    def inject_carrier(self, headers: Dict[str, str]) -> Dict[str, str]:
        """
        将Trace信息注入到请求头中
        
        参数：
            headers: 请求头字典
        
        返回：
            包含Trace信息的请求头
        """
        if _skywalking_available and self._initialized:
            try:
                carrier = Carrier()
                context.inject(carrier)
                for item in carrier:
                    headers[item.key] = item.val
            except Exception as exc:
                logger.warning(
                    "[SkyWalking] Inject carrier failed error_type=%s",
                    type(exc).__name__,
                )
        
        return headers
    
    def extract_carrier(self, headers: Dict[str, str]):
        """
        从请求头中提取Trace信息
        
        参数：
            headers: 请求头字典
        """
        if _skywalking_available and self._initialized:
            try:
                carrier = Carrier()
                for item in carrier:
                    if item.key in headers:
                        item.val = headers[item.key]
                context.extract(carrier)
            except Exception as exc:
                logger.warning(
                    "[SkyWalking] Extract carrier failed error_type=%s",
                    type(exc).__name__,
                )


class LocalSpan:
    """本地Span（SkyWalking不可用时的回退实现）"""
    
    def __init__(self, operation_name: str, span_type: str, peer: str = ""):
        self.operation_name = operation_name
        self.span_type = span_type
        self.peer = peer
        self.start_time = time.time()
        self.end_time = None
        self.tags = {}
        self.trace_id = str(uuid.uuid4())[:16]
        
        logger.info(
            "[LocalTrace] Start span=%s trace_id=%s type=%s",
            safe_log_field(operation_name), safe_log_field(self.trace_id),
            safe_log_field(span_type),
        )
    
    def tag(self, tag_obj):
        """添加标签"""
        if hasattr(tag_obj, 'key') and hasattr(tag_obj, 'val'):
            self.tags[tag_obj.key] = tag_obj.val
        elif isinstance(tag_obj, tuple):
            self.tags[tag_obj[0]] = tag_obj[1]
    
    def finish(self):
        """结束Span"""
        self.end_time = time.time()
        duration = (self.end_time - self.start_time) * 1000
        logger.info(
            "[LocalTrace] End span=%s trace_id=%s duration_ms=%.2f type=%s",
            safe_log_field(self.operation_name), safe_log_field(self.trace_id),
            duration, safe_log_field(self.span_type),
        )
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.finish()
        if exc_val:
            logger.error(
                "[LocalTrace] Span failed span=%s error_type=%s",
                safe_log_field(self.operation_name), type(exc_val).__name__,
            )


# 创建全局SkyWalking追踪器实例
skywalking_tracer = SkyWalkingTracer()


def init_skywalking(config: dict) -> None:
    """
    初始化SkyWalking配置
    
    参数：
        config: 配置字典，包含service_name, collector_address等
    """
    root = config if isinstance(config, dict) else {}
    skywalking_tracer.configure(
        service_name=root.get('service_name', 'spring-python-app'),
        collector_address=root.get('collector_address', '127.0.0.1:11800'),
    )
