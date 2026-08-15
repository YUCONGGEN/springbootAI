"""Spring Cloud 微服务组件包"""

from spring.cloud.discovery import NacosDiscoveryClient
try:
    from spring.cloud.discovery import nacos_client as nacos_discovery_client
except ImportError:
    nacos_discovery_client = None
from spring.cloud.load_balancer import LoadBalancer, load_balancer
from spring.cloud.feign import (
    FeignClientProxy,
    FeignClientFactory,
    create_feign_client,
    create_declared_feign_client,
)
from spring.cloud.seata import (
    seata_manager,
    init_seata,
    SeataTransactionManager,
    BranchStatus,
)
from spring.cloud.transaction_store import SQLiteTransactionStore
from spring.cloud.seata_bridge import SeataBridgeClient, SeataBridgeError
from spring.cloud.seata_at_proxy import (
    SeataATProxy,
    SeataATInterceptor,
    UndoLogManager,
    UndoExecutor,
    parse_sql,
)
from spring.cloud.sentinel import (
    sentinel_engine,
    SentinelEngine,
    FlowRule,
    DegradeRule,
    SystemRule,
    HotParamRule,
    BlockException,
    sentinel_protect,
)
from spring.cloud.tracer import (
    Tracer,
    get_tracer,
    trace_span,
    SpanKind,
    SpanStatus,
    _build_traceparent,
    _parse_traceparent,
)
from spring.cloud.gateway import (
    GatewayRouter,
    Route,
    GatewayFilter,
    AuthenticationFilter,
    RateLimitFilter,
    TracingFilter,
    LoggingFilter,
    get_gateway,
)
from spring.cloud.config_center import (
    ConfigCenterClient,
    ConfigCenterError,
    config_client,
    init_config_center,
    create_config_refresh_endpoint,
)
from spring.cloud.bus import (
    BusEvent,
    EventBus,
    event_bus,
    init_bus,
    create_bus_refresh_endpoint,
)

try:
    from spring.messaging.rabbitmq import rabbitmq_client, RabbitMQClient
except ImportError:
    rabbitmq_client = None
    RabbitMQClient = None

__all__ = [
    # 服务发现
    'nacos_discovery_client', 'NacosDiscoveryClient',
    # 负载均衡
    'LoadBalancer', 'load_balancer',
    # Feign
    'FeignClientProxy', 'FeignClientFactory', 'create_feign_client', 'create_declared_feign_client',
    # 分布式事务
    'seata_manager', 'init_seata', 'SeataTransactionManager', 'BranchStatus',
    'SQLiteTransactionStore', 'SeataBridgeClient', 'SeataBridgeError',
    'SeataATProxy', 'SeataATInterceptor', 'UndoLogManager', 'UndoExecutor', 'parse_sql',
    # 熔断限流
    'sentinel_engine', 'SentinelEngine', 'FlowRule', 'DegradeRule',
    'SystemRule', 'HotParamRule', 'BlockException', 'sentinel_protect',
    # 链路追踪
    'Tracer', 'get_tracer', 'trace_span', 'SpanKind', 'SpanStatus',
    # 网关
    'GatewayRouter', 'Route', 'GatewayFilter',
    'AuthenticationFilter', 'RateLimitFilter', 'TracingFilter', 'LoggingFilter', 'get_gateway',
    # 配置中心
    'ConfigCenterClient', 'ConfigCenterError', 'config_client', 'init_config_center',
    'create_config_refresh_endpoint',
    # 事件总线
    'BusEvent', 'EventBus', 'event_bus', 'init_bus', 'create_bus_refresh_endpoint',
    # 消息队列
    'rabbitmq_client', 'RabbitMQClient',
]
