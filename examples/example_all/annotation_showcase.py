"""默认不应启用的注解的可执行声明示例。

``example_all`` 启动时会扫描自身包。远程客户端、安全开关和备用应用根类不应仅因
启动学习应用就被激活。因此本模块把所有声明放进
:func:`build_annotation_showcase`：导入模块没有副作用，调用函数才会创建真实的
带注解类和方法，供测试和阅读者检查。
"""

from __future__ import annotations

from typing import Any

from springbootai.annotations import (
    Agent,
    AiCache,
    AiRetry,
    ContentModeration,
    After,
    AfterReturning,
    AfterThrowing,
    Around,
    Aspect,
    AsyncResult,
    BatchJob,
    BatchStep,
    Before,
    CacheConfig,
    CacheEvict,
    CachePut,
    Cacheable,
    Caching,
    ComponentScan,
    Conditional,
    ConditionalOnBean,
    ConditionalOnClass,
    ConditionalOnMissingBean,
    ConditionalOnProperty,
    EnableBatchProcessing,
    EnableBus,
    EnableConfigServer,
    EnableCsrf,
    EnableDataRest,
    EnableDevTools,
    EnableFeignClients,
    EnableGateway,
    EnableOAuth2,
    FeignClient,
    CookieValue,
    GraphEdge,
    GraphInvoke,
    GraphNode,
    GraphRoute,
    KafkaListener,
    KafkaTemplate,
    LangChainCall,
    LangChainClient,
    LangGraph,
    MCPCall,
    MCPClient,
    MCPPrompt,
    MCPResource,
    MCPServer,
    MCPTool,
    PathVariable,
    Pointcut,
    PostAuthorize,
    Qualifier,
    RabbitTemplate,
    Recover,
    RepositoryRestResource,
    RequestBody,
    RequestPart,
    FileUpload,
    Embedding,
    Prompt,
    RAG,
    StructuredOutput,
    TokenUsage,
    VectorStore,
    RequestHeader,
    RequestParam,
    Scope,
    Valid,
    Validated,
    kafka_template,
)


# 以下是由后续真实声明展示的全部框架注解。
# AsyncResult 特意不在其中：它是返回值对象而不是装饰器，强行写成
# ``@AsyncResult`` 会造成误导。
SHOWCASED_ANNOTATIONS = frozenset(
    {
        "ComponentScan", "Aspect", "Pointcut", "Before", "After", "Around",
        "AfterReturning", "AfterThrowing", "Qualifier", "Scope", "Recover",
        "PostAuthorize", "EnableFeignClients", "FeignClient", "EnableGateway",
        "Valid", "Validated", "CachePut", "CacheEvict", "CacheConfig", "Caching",
        "Conditional", "ConditionalOnProperty", "ConditionalOnBean",
        "ConditionalOnMissingBean", "ConditionalOnClass", "KafkaListener", "MCPCall",
        "MCPClient", "MCPPrompt", "MCPResource", "MCPServer", "MCPTool",
        "LangChainCall", "LangChainClient", "GraphEdge", "GraphInvoke", "GraphNode",
        "GraphRoute", "LangGraph", "EnableOAuth2", "EnableCsrf", "EnableDevTools",
        "EnableConfigServer", "EnableBus", "EnableBatchProcessing", "EnableDataRest",
        "BatchJob", "BatchStep", "RepositoryRestResource",
        "Prompt", "RAG", "StructuredOutput", "Agent", "Embedding", "VectorStore",
        "AiRetry", "AiCache", "TokenUsage", "ContentModeration",
    }
)

# 以下 API 是值对象或参数描述符，而不是装饰器。示例使用真实 Python 写法，
# 不为了让目录格式统一而虚构无效的 ``@`` 语法。
SHOWCASED_NON_DECORATOR_APIS = frozenset(
    {
        "AsyncResult", "RequestParam", "PathVariable", "RequestBody", "RequestPart", "FileUpload",
        "RequestHeader", "CookieValue", "RabbitTemplate", "KafkaTemplate",
        "kafka_template",
    }
)


def build_annotation_showcase() -> dict[str, type]:
    """创建隔离类，展示完整的声明式注解写法。

    调用本函数只会创建 Python 类和元数据，不会实例化 SpringBootAI 应用、调用远程
    MCP/LangChain、消费 Kafka 消息，也不会启用安全中间件。
    """

    # 不启动 IoC 容器也可以检查组件扫描和 AOP 切点；Advice 函数特意不包含业务逻辑。
    @ComponentScan(base_packages=["example_all.service"])
    class ComponentScanApplication:
        pass

    @Aspect("annotationShowcaseAspect")
    class AnnotationShowcaseAspect:
        @Pointcut("execution(* example_all.service.*.*(..))")
        def service_operations(self) -> None:
            pass

        @Before("service_operations")
        def before_call(self) -> None:
            pass

        @After("service_operations")
        def after_call(self) -> None:
            pass

        @Around("service_operations")
        def around_call(self, join_point: Any) -> Any:
            return join_point.proceed()

        @AfterReturning("service_operations", returning="result")
        def after_success(self, result: Any) -> None:
            pass

        @AfterThrowing("service_operations", throwing="error")
        def after_failure(self, error: Exception) -> None:
            pass

    @Scope("prototype")
    class PrototypeReport:
        pass

    class QualifiedConsumer:
        @Qualifier("showcasePrimaryClient")
        def __init__(self, client: Any) -> None:
            self.client = client

    class RecoveryAndAuthorization:
        @Recover(ConnectionError)
        def recover_transport(self, error: ConnectionError) -> dict[str, str]:
            return {"status": "recovered"}

        @PostAuthorize("returnObject['owner'] == authentication.name")
        def current_document(self) -> dict[str, str]:
            return {"owner": "demo"}

    # 缓存操作是声明式 AOP 元数据；只有受容器管理的 Bean 真正调用这些方法时，
    # 才会访问缓存后端。
    @CacheConfig(cache_names=["showcase_records"])
    class CacheOperations:
        @CachePut(key="record_id")
        def update_record(self, record_id: str) -> dict[str, str]:
            return {"id": record_id}

        @CacheEvict(key="record_id")
        def delete_record(self, record_id: str) -> None:
            return None

        @Caching(
            cacheable=[Cacheable("showcase_records", key="record_id")],
            put=[CachePut("showcase_records", key="record_id")],
            evict=[CacheEvict("showcase_summary", all_entries=True)],
        )
        def refresh_record(self, record_id: str) -> dict[str, str]:
            return {"id": record_id, "refreshed": "true"}

    # 条件示例使用普通类，避免修改条件输入时影响默认 example_all 应用上下文。
    @Conditional(lambda context: bool(context))
    class CustomConditionExample:
        pass

    @ConditionalOnProperty("showcase.feature.enabled", having_value="true")
    class PropertyConditionExample:
        pass

    @ConditionalOnBean(bean_name="showcasePrimaryClient")
    class ExistingBeanConditionExample:
        pass

    @ConditionalOnMissingBean(bean_name="showcaseReplacement")
    class MissingBeanConditionExample:
        pass

    @ConditionalOnClass(name="json.JSONEncoder")
    class ClasspathConditionExample:
        pass

    # Cloud、批处理、REST 和安全开关通常放在专用应用根类中。这里仅做声明，
    # 防止它们改变本项目的标准启动配置。
    @EnableFeignClients(base_packages=["example_all.clients"])
    @EnableGateway
    @EnableOAuth2(issuer="https://issuer.example.invalid", audiences=["showcase"])
    @EnableCsrf(cookie_name="SHOWCASE-XSRF")
    @EnableDevTools(watch_dirs=["examples/example_all"])
    @EnableConfigServer(uri="http://127.0.0.1:8888", backend="file")
    @EnableBus(destination="showcase.events", backend="local")
    @EnableBatchProcessing(job_names=["showcaseImport"], auto_run=False)
    @EnableDataRest(base_path="/showcase-data", default_page_size=10)
    class OptionalInfrastructureApplication:
        pass

    @FeignClient("inventory", url="http://127.0.0.1:8091")
    class InventoryClient:
        def stock(self, sku: str) -> dict[str, str]:
            return {"sku": sku}

    @KafkaListener(topics=["showcase.events"], groupId="example-all-showcase")
    def consume_showcase_event(message: dict[str, Any]) -> None:
        return None

    # MCP、LangChain 和 LangGraph 注解只有在配置对应运行时且调用带注解方法时才会
    # 生效。因此下面的声明可以安全地构造。
    @MCPClient(name="showcase-tools")
    class ShowcaseMcpClient:
        @MCPCall(tool="lookup_record")
        def lookup_record(self, record_id: str) -> dict[str, str]:
            return {"id": record_id}

    @MCPServer(name="showcase-server", allowed_tools=["echo"])
    class ShowcaseMcpServer:
        @MCPTool(name="echo", description="Echo a safe showcase value")
        def echo(self, value: str) -> str:
            return value

        @MCPResource(uri="showcase://records/{record_id}", name="Showcase record")
        def record_resource(self, record_id: str) -> str:
            return record_id

        @MCPPrompt(name="showcase-review", description="Review a showcase record")
        def review_prompt(self) -> str:
            return "Review the record."

    @LangChainClient(chain_service_bean="lcChainService")
    class ShowcaseLangChainClient:
        @LangChainCall(prompt="Summarize this record: {record}")
        def summarize(self, record: str) -> str:
            return record

    @LangGraph(name="showcase-graph", state_schema=dict)
    @GraphEdge(source="validate", target="complete")
    class ShowcaseGraph:
        @GraphNode(name="validate", entry=True)
        def validate(self, state: dict[str, Any]) -> dict[str, Any]:
            return state

        @GraphNode(name="complete", end=True)
        def complete(self, state: dict[str, Any]) -> dict[str, Any]:
            return state

        @GraphRoute(source="validate", paths={"ok": "complete"})
        def route(self, state: dict[str, Any]) -> str:
            return "ok"

        @GraphInvoke(input_name="input_state")
        def invoke(self, input_state: dict[str, Any]) -> dict[str, Any]:
            return input_state

    @BatchJob(name="showcaseImport", description="Metadata-only import job")
    class ShowcaseBatchJob:
        @BatchStep(name="load", chunk_size=25, retry_limit=1)
        def load(self) -> list[str]:
            return []

    @RepositoryRestResource(path="showcase-records", id_type=int, exported=False)
    class ShowcaseRecordRepository:
        pass

    def completed_async_result() -> AsyncResult:
        """不启动工作线程，展示 @Async 方法返回的值对象。"""
        return AsyncResult({"status": "completed"})

    def request_binding_defaults(
        query: str = RequestParam("query", default=""),
        record_id: int = PathVariable("record_id"),
        payload: dict[str, Any] = RequestBody(),
        request_id: str = RequestHeader("X-Request-ID", default=""),
        session_id: str = CookieValue("session_id", default=""),
    ) -> tuple[Any, Any, Any, Any, Any]:
        """按原生参数位置展示全部请求绑定描述符。"""
        return query, record_id, payload, request_id, session_id

    def upload_binding_defaults(
        file: Any = RequestPart("file", allowed_extensions="pdf,docx", max_size=10 * 1024 * 1024),
        images: Any = FileUpload("images", required=False),
    ) -> tuple[Any, Any]:
        """展示单文件和多文件上传字段描述符；不启动 HTTP 服务。"""
        return file, images

    def messaging_templates() -> tuple[RabbitTemplate, KafkaTemplate, KafkaTemplate]:
        """创建消息模板对象，但不打开消息代理连接。"""
        return RabbitTemplate(), KafkaTemplate(), kafka_template

    class ValidationEndpoints:
        @Valid
        def create(self, payload: dict[str, Any]) -> dict[str, Any]:
            return payload

        @Validated(groups=["update"])
        def update(self, payload: dict[str, Any]) -> dict[str, Any]:
            return payload

    # AI 注解只声明能力；真正调用时由 BeanFactory 注入 ChatClient、Agent、
    # EmbeddingModel 和 VectorStore。未配置 AI Bean 时下面的类仍可安全导入。
    @Agent(agent_type="react", max_iterations=3)
    class ShowcaseAiAgent:
        def answer(self, question: str) -> str:
            return question

    @Embedding
    @VectorStore
    class ShowcaseAiService:
        embedding_model = Embedding()
        vector_store = VectorStore()

        @Prompt("请总结焊接记录：{record}")
        @TokenUsage()
        @ContentModeration(blocked_terms=["恶意指令"])
        def summarize(self, record: str) -> str:
            return record

        @RAG(top_k=2)
        @AiRetry(attempts=2, delay_ms=10)
        @AiCache(ttl=30, key="{question}")
        def answer_from_knowledge(self, question: str) -> str:
            return question

        @Prompt("输出 JSON：{text}")
        @StructuredOutput(dict)
        def structured(self, text: str) -> dict[str, Any]:
            return text

    return {
        name: value
        for name, value in locals().items()
        if isinstance(value, type) or callable(value)
    }
