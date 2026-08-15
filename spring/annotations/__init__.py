from .core import (
    SpringBootApplication,
    ComponentScan,
    ApplicationEvent,
    EventListener,
    RestController,
    Controller,
    RequestMapping,
    GetMapping,
    PostMapping,
    PutMapping,
    PatchMapping,
    DeleteMapping,
    Service,
    Component,
    Aspect,
    Pointcut,
    Before,
    After,
    Around,
    AfterReturning,
    AfterThrowing,
    Repository,
    Autowired,
    Qualifier,
    Configuration,
    Scope,
    Bean,
    Value,
    ConfigurationProperties,
    RequestParam,
    PathVariable,
    RequestBody,
    Valid,
    Validated,
    CrossOrigin,
    ControllerAdvice,
    ExceptionHandler,
    Slf4j,
    LogExecutionTime,
    PostConstruct,
    PreDestroy,
    Primary,
    Profile,
    Lazy,
    RequestHeader,
    CookieValue,
    ResponseStatus,
    Transactional,
    Cacheable,
    Retryable,
    Recover,
    Async,
    Scheduled,
    AsyncResult,
    RateLimit,
    CircuitBreaker,
    Idempotent,
    AuditLog,
    FeatureToggle,
    Lock,
    Metrics,
    Synchronized,
    Validate,
    Trace,
    PreAuthorize,
    PostAuthorize,
    Secured,
    Authenticate,
)

from .cloud import (
    EnableDiscoveryClient,
    NacosValue,
    RefreshScope,
    EnableFeignClients,
    FeignClient,
    SentinelResource,
    EnableGateway,
    LoadBalanced,
    GlobalTransactional,
)

# 缓存增强注解（@CachePut / @CacheEvict / @CacheConfig / @Caching），对齐 Spring Cache
from .cache import (
    CachePut,
    CacheEvict,
    CacheConfig,
    Caching,
)

# 条件装配注解（@Conditional / @ConditionalOnProperty / ...），对齐 Spring Boot
from .conditional import (
    Conditional,
    ConditionalOnProperty,
    ConditionalOnBean,
    ConditionalOnMissingBean,
    ConditionalOnClass,
)

# 可选导入：消息队列注解（RabbitMQ 需要 pika，Kafka 需要 kafka-python）
try:
    from .messaging import (
        RabbitListener,
        RabbitTemplate,
        KafkaListener,
        KafkaTemplate,
        kafka_template,
    )
except ImportError:
    # 依赖未安装，这些注解不可用
    RabbitListener = None
    RabbitTemplate = None
    KafkaListener = None
    KafkaTemplate = None
    kafka_template = None

# Optional MCP annotations are dependency-safe until MCP is enabled.
from spring.mcp.annotations import (
    MCPCall,
    MCPClient,
    MCPPrompt,
    MCPResource,
    MCPServer,
    MCPTool,
)
from .langchain import LangChainCall, LangChainClient
from .langgraph import GraphEdge, GraphInvoke, GraphNode, GraphRoute, LangGraph

# 安全启用型注解（@EnableOAuth2 / @EnableCsrf）
from .security import EnableOAuth2, EnableCsrf

# 企业级启用型注解（@EnableDevTools / @EnableConfigServer / @EnableBus / @EnableBatchProcessing / @EnableDataRest）
from .enterprise import (
    EnableDevTools,
    EnableConfigServer,
    EnableBus,
    EnableBatchProcessing,
    EnableDataRest,
)

# 批处理注解（@BatchJob / @BatchStep）
from .batch import BatchJob, BatchStep

# 数据 REST 注解（@RepositoryRestResource）
from .data import RepositoryRestResource

__all__ = [
    "SpringBootApplication",
    "ComponentScan",
    "ApplicationEvent",
    "EventListener",
    "RestController",
    "Controller",
    "RequestMapping",
    "GetMapping",
    "PostMapping",
    "PutMapping",
    "PatchMapping",
    "DeleteMapping",
    "Service",
    "Component",
    "Aspect",
    "Pointcut",
    "Before",
    "After",
    "Around",
    "AfterReturning",
    "AfterThrowing",
    "Repository",
    "Autowired",
    "Qualifier",
    "Configuration",
    "Scope",
    "Bean",
    "Value",
    "ConfigurationProperties",
    "RequestParam",
    "PathVariable",
    "RequestBody",
    "CrossOrigin",
    "ControllerAdvice",
    "ExceptionHandler",
    "Slf4j",
    "LogExecutionTime",
    "PostConstruct",
    "PreDestroy",
    "Primary",
    "Profile",
    "Lazy",
    "RequestHeader",
    "CookieValue",
    "ResponseStatus",
    "Transactional",
    "Cacheable",
    "Retryable",
    "Recover",
    "Async",
    "Scheduled",
    "AsyncResult",
    "RateLimit",
    "CircuitBreaker",
    "Idempotent",
    "AuditLog",
    "FeatureToggle",
    "Lock",
    "Metrics",
    "Synchronized",
    "Validate",
    "Trace",
    # 安全注解
    "PreAuthorize",
    "PostAuthorize",
    "Secured",
    "Authenticate",
    # Spring Cloud 注解
    "EnableDiscoveryClient",
    "NacosValue",
    "RefreshScope",
    "EnableFeignClients",
    "FeignClient",
    "SentinelResource",
    "EnableGateway",
    "LoadBalanced",
    "GlobalTransactional",
    "Valid",
    "Validated",
    # 缓存增强注解
    "CachePut",
    "CacheEvict",
    "CacheConfig",
    "Caching",
    # 条件装配注解
    "Conditional",
    "ConditionalOnProperty",
    "ConditionalOnBean",
    "ConditionalOnMissingBean",
    "ConditionalOnClass",
    # 消息队列注解
    "RabbitListener",
    "RabbitTemplate",
    "KafkaListener",
    "KafkaTemplate",
    "kafka_template",
    # Model Context Protocol
    "MCPCall",
    "MCPClient",
    "MCPPrompt",
    "MCPResource",
    "MCPServer",
    "MCPTool",
    # LangChain declarative execution
    "LangChainCall",
    "LangChainClient",
    # LangGraph declarative workflow
    "GraphEdge",
    "GraphInvoke",
    "GraphNode",
    "GraphRoute",
    "LangGraph",
    # 安全启用型注解
    "EnableOAuth2",
    "EnableCsrf",
    # 企业级启用型注解
    "EnableDevTools",
    "EnableConfigServer",
    "EnableBus",
    "EnableBatchProcessing",
    "EnableDataRest",
    # 批处理注解
    "BatchJob",
    "BatchStep",
    # 数据 REST 注解
    "RepositoryRestResource",
]
