"""需要可选依赖或隔离配置的注解的可复制示例。

这些片段特意保存为字符串：即使未安装 Kafka、MCP、LangChain 或 LangGraph，
example_all 仍可启动，而查询接口仍能展示准确注解写法和所需依赖。
"""

FEATURE_SNIPPETS = {
    "ComponentScan": {
        "code": 'from springbootai.annotations import ComponentScan, SpringBootApplication\n\n@SpringBootApplication\n@ComponentScan(base_packages=["example_all.service"])\nclass DemoApplication:\n    pass',
        "notes": "将组件扫描限制在明确指定的包中。",
    },
    "Aspect": {
        "code": 'from springbootai.annotations import Aspect, Component\n\n@Aspect("audit")\n@Component\nclass AuditAspect:\n    pass',
        "notes": "标记切面 Bean；Advice 方法使用 Before/After/Around 展示。",
    },
    "Pointcut": {
        "code": '@Pointcut("execution(* example_all.service.*.*(..))")\ndef service_methods(self):\n    pass',
        "notes": "定义可复用的切点表达式名称。",
    },
    "Before": {
        "code": '@Before(pointcut="service_methods()")\ndef before_call(self, join_point):\n    pass',
        "notes": "在匹配的方法执行前运行 Advice。",
    },
    "After": {
        "code": '@After(pointcut="service_methods()")\ndef after_call(self, join_point):\n    pass',
        "notes": "在匹配的方法执行后运行 Advice。",
    },
    "Around": {
        "code": '@Around(pointcut="service_methods()")\ndef around_call(self, join_point):\n    return join_point.proceed()',
        "notes": "环绕匹配方法，并可控制 proceed() 是否继续执行。",
    },
    "AfterReturning": {
        "code": '@AfterReturning(pointcut="service_methods()", returning="result")\ndef after_success(self, join_point, result):\n    pass',
        "notes": "接收方法成功执行后的返回值。",
    },
    "AfterThrowing": {
        "code": '@AfterThrowing(pointcut="service_methods()", throwing="exception")\ndef after_failure(self, join_point, exception):\n    pass',
        "notes": "接收匹配方法抛出的异常。",
    },
    "Scope": {
        "code": 'from springbootai.annotations import Service, Scope\n\n@Service\n@Scope("prototype")\nclass RequestWorker:\n    pass',
        "notes": "创建原型作用域 Bean。",
    },
    "Recover": {
        "code": '@Retryable(max_attempts=3)\ndef call_remote(self):\n    raise ConnectionError("temporary failure")\n\n@Recover\n def recover_remote(self, exception):\n    return {"fallback": True}',
        "notes": "与 Retryable 配合，在重试耗尽后执行降级方法。",
    },
    "PostAuthorize": {
        "code": '@PostAuthorize("returnObject.owner == authentication.name")\ndef read_document(self, document_id):\n    pass',
        "notes": "方法执行后检查返回值。",
    },
    "Validated": {
        "code": 'from springbootai.annotations import Validated\n\n@Validated\nclass UserCommand:\n    pass',
        "notes": "在类边界启用校验处理。",
    },
    "CachePut": {
        "code": '@CachePut(value="users", key="user.id")\ndef save_user(self, user):\n    return user',
        "notes": "始终执行方法，并将结果写入缓存。",
    },
    "CacheEvict": {
        "code": '@CacheEvict(value="users", key="user_id")\ndef delete_user(self, user_id):\n    pass',
        "notes": "操作完成后删除指定缓存项。",
    },
    "CacheConfig": {
        "code": '@CacheConfig(cache_names=["users"])\nclass UserService:\n    pass',
        "notes": "设置服务中多个方法共享的缓存默认配置。",
    },
    "Caching": {
        "code": '@Caching(cacheable=[Cacheable("users")], evict=[CacheEvict("user_summary")])\ndef refresh_user(self, user_id):\n    pass',
        "notes": "在一个方法上组合多个缓存操作。",
    },
    "Conditional": {
        "code": '@Conditional(lambda context: context.get("feature.enabled", False))\nclass OptionalFeature:\n    pass',
        "notes": "仅当条件返回 true 时加载 Bean。",
    },
    "ConditionalOnProperty": {
        "code": '@ConditionalOnProperty(name="feature.enabled", having_value="true")\nclass OptionalFeature:\n    pass',
        "notes": "根据配置属性进行条件装配。",
    },
    "ConditionalOnBean": {
        "code": '@ConditionalOnBean(bean_name="paymentClient")\nclass PaymentMetrics:\n    pass',
        "notes": "仅当另一个 Bean 存在时加载当前 Bean。",
    },
    "ConditionalOnMissingBean": {
        "code": '@ConditionalOnMissingBean(bean_name="customClock")\nclass DefaultClock:\n    pass',
        "notes": "仅在应用未提供替代 Bean 时加载默认实现。",
    },
    "ConditionalOnClass": {
        "code": '@ConditionalOnClass(name="redis.Redis")\nclass RedisHealthIndicator:\n    pass',
        "notes": "仅当依赖可导入时加载对应集成。",
    },
    "KafkaListener": {
        "code": 'from springbootai.annotations import KafkaListener\n\n@KafkaListener(topics=["orders"], groupId="welding-workers")\ndef consume_order(message):\n    pass',
        "notes": "需要 Kafka 可选依赖和可访问的消息代理。",
    },
    "KafkaTemplate": {
        "code": 'from springbootai.annotations import KafkaTemplate\n\ntemplate = KafkaTemplate()\ntemplate.send("orders", {"order_id": 1})',
        "notes": "需要 kafka-python 和可访问的消息代理。",
    },
    "kafka_template": {
        "code": 'from springbootai.annotations import kafka_template\n\nkafka_template.send("orders", {"order_id": 1})',
        "notes": "共享 Kafka 模板工具；需要 kafka-python。",
    },
    "MCPCall": {
        "code": '@MCPCall(name="lookup_welder")\ndef lookup_welder(welder_no: str):\n    return {"welder_no": welder_no}',
        "notes": "将可调用对象暴露为 MCP 操作；需要 mcp。",
    },
    "MCPClient": {
        "code": '@MCPClient(name="inspection", value="http://127.0.0.1:8001/mcp")\nclass InspectionClient:\n    pass',
        "notes": "绑定 MCP 客户端端点；需要 mcp。",
    },
    "MCPPrompt": {
        "code": '@MCPPrompt(name="weld_review", description="Review a weld result")\ndef weld_review_prompt():\n    return "Review this result"',
        "notes": "注册 MCP 提示词；需要 mcp。",
    },
    "MCPResource": {
        "code": '@MCPResource(uri="weld://{welder_no}", name="Weld result")\ndef weld_resource(welder_no: str):\n    return "{}"',
        "notes": "注册 MCP 资源；需要 mcp。",
    },
    "MCPServer": {
        "code": '@MCPServer(name="welding-tools", transport="streamable-http", port=8001)\nclass WeldingMcpServer:\n    pass',
        "notes": "声明 MCP 服务端；需要 mcp。",
    },
    "MCPTool": {
        "code": '@MCPTool(name="calculate_passes", description="Calculate weld passes")\ndef calculate_passes(leg_mm: float):\n    return max(1, round(leg_mm / 3))',
        "notes": "将函数暴露为 MCP 工具；需要 mcp。",
    },
    "LangChainCall": {
        "code": '@LangChainCall(prompt="Summarize the weld result", mode="chain")\ndef summarize_weld(result: dict):\n    pass',
        "notes": "通过框架 LangChain 服务路由方法调用。",
    },
    "LangChainClient": {
        "code": '@LangChainClient(chain_service_bean="weldChain")\nclass WeldAssistant:\n    pass',
        "notes": "绑定 LangChain 客户端 Bean；需安装 springbootAI[langchain]。",
    },
    "GraphEdge": {
        "code": 'edge = GraphEdge(source="validate", target="predict")',
        "notes": "声明有向 LangGraph 边。",
    },
    "GraphInvoke": {
        "code": '@GraphInvoke(input_name="weld_request")\ndef invoke_graph(request: dict):\n    pass',
        "notes": "调用已注册的图运行时。",
    },
    "GraphNode": {
        "code": '@GraphNode(name="predict", entry=True)\ndef predict(state: dict):\n    return state',
        "notes": "声明图节点。",
    },
    "GraphRoute": {
        "code": '@GraphRoute(source="validate", paths={"ok": "predict", "bad": "reject"})\ndef route(state: dict):\n    return "ok"',
        "notes": "声明条件图路由。",
    },
    "LangGraph": {
        "code": '@LangGraph(name="welding-flow", state_schema=dict)\nclass WeldingFlow:\n    pass',
        "notes": "启用框架 LangGraph 运行时；需安装 springbootAI[langgraph]。",
    },
    "EnableOAuth2": {
        "code": '@EnableOAuth2(issuer="https://issuer.example.com", audiences=["welding-api"])\nclass SecurityConfig:\n    pass',
        "notes": "启用 OAuth2 资源服务器校验。",
    },
    "EnableCsrf": {
        "code": '@EnableCsrf(cookie_name="XSRF-TOKEN", header_name="X-XSRF-TOKEN")\nclass WebSecurityConfig:\n    pass',
        "notes": "启用 CSRF 令牌保护。",
    },
    "EnableDevTools": {
        "code": '@EnableDevTools(watch_dirs=["entities", "services"])\nclass DevConfig:\n    pass',
        "notes": "启用开发环境文件监听和重启。",
    },
    "EnableConfigServer": {
        "code": '@EnableConfigServer(uri="http://localhost:8888", profile="dev")\nclass ConfigClient:\n    pass',
        "notes": "从配置服务器加载远程配置。",
    },
    "EnableBus": {
        "code": '@EnableBus(destination="springCloudBus", backend="local")\nclass BusConfig:\n    pass',
        "notes": "启用应用事件总线传播。",
    },
    "EnableBatchProcessing": {
        "code": '@EnableBatchProcessing(job_names=["weld_training"], auto_run=False)\nclass BatchConfig:\n    pass',
        "notes": "启用批处理作业基础设施。",
    },
    "EnableDataRest": {
        "code": '@EnableDataRest(base_path="/api/data", default_page_size=20)\nclass DataRestConfig:\n    pass',
        "notes": "启用 Repository 风格的 REST 暴露。",
    },
    "BatchJob": {
        "code": '@BatchJob(name="weld_training", description="Train one welder model")\nclass WeldTrainingJob:\n    pass',
        "notes": "声明批处理作业。",
    },
    "BatchStep": {
        "code": '@BatchStep(name="load_samples", chunk_size=50, retry_limit=2)\ndef load_samples(context):\n    pass',
        "notes": "声明一个批处理步骤。",
    },
    "RepositoryRestResource": {
        "code": '@RepositoryRestResource(path="welders", id_type=int)\nclass WelderRepository:\n    pass',
        "notes": "在 REST 资源路径下发布 Repository 操作。",
    },

    "Qualifier": {
        "code": '@Autowired\n@Qualifier("primaryPaymentClient")\ndef __init__(self, client):\n    self.client = client',
        "notes": "存在多个实现时选择指定 Bean。",
    },
    "RequestParam": {
        "code": '@GetMapping("/search")\ndef search(self, keyword: str = "", page: int = 0):\n    return {"keyword": keyword, "page": page}',
        "notes": "框架按名称和默认值绑定查询参数。",
    },
    "PathVariable": {
        "code": '@GetMapping("/users/{user_id}")\ndef find_user(self, user_id: int):\n    return {"id": user_id}',
        "notes": "框架将路径占位符绑定到同名参数。",
    },
    "RequestBody": {
        "code": '@PostMapping("/users")\ndef create_user(self, payload: dict):\n    return payload',
        "notes": "框架将 JSON 请求体绑定到带类型的参数。",
    },
    "RequestHeader": {
        "code": '@GetMapping("/trace")\ndef trace(self, x_request_id: str):\n    return {"request_id": x_request_id}',
        "notes": "框架将请求头绑定到匹配参数。",
    },
    "CookieValue": {
        "code": '@GetMapping("/session")\ndef session(self, session_id: str = ""):\n    return {"session": session_id}',
        "notes": "框架使用指定默认值绑定匹配的 Cookie。",
    },
    "AsyncResult": {
        "code": '@Async\ndef refresh_metrics(self):\n    return AsyncResult({"refreshed": True})',
        "notes": "表示异步方法生成的结果。",
    },
    "EnableFeignClients": {
        "code": '@EnableFeignClients\nclass ClientConfig:\n    pass',
        "notes": "启用声明式 Feign 风格 HTTP 客户端扫描。",
    },
    "FeignClient": {
        "code": '@FeignClient("inventory", url="http://localhost:8091")\nclass InventoryClient:\n    pass',
        "notes": "声明调用其他服务的类型化 HTTP 客户端。",
    },
    "EnableGateway": {
        "code": '@EnableGateway\nclass GatewayConfig:\n    pass',
        "notes": "启用框架网关路由基础设施。",
    },
    "Valid": {
        "code": '@PostMapping("/users")\ndef create_user(self, command: ValidatedUserCommand):\n    return command',
        "notes": "标记需要框架校验的请求对象。",
    },
    "RabbitTemplate": {
        "code": 'from springbootai.annotations import RabbitTemplate\n\ntemplate = RabbitTemplate()\ntemplate.convert_and_send("weld.events", {"job_id": 1})',
        "notes": "需要 pika 和可访问的 RabbitMQ 消息代理。",
    },}


def get_snippet(name: str):
    return FEATURE_SNIPPETS.get(name)
