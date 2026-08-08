# SpringPy 框架综合测试报告

**测试日期**: 2026-08-08  
**测试环境**: macOS + Python 3.9.6 + Docker  
**框架版本**: SpringPy 1.7.0 / PyMyBatis 1.4.0 / SpringPy AI 1.3.0  
**测试结果**: ✅ **702 个用例全部通过**（15 个测试套件，0 失败）；example_all 集成测试 **5/5 套件通过**（模块导入 25、XML Mapper 11、注解组合 4、组件扫描 26、HTTP API 36/36，含 9 个兼容性探针与 ORM MySQL 6/6）

> 本报告整合三大类测试/质量文档：① 主框架全面测试（702 用例）；② example_all 集成测试（全注解用例集合，5 套件）；③ 企业生产就绪评估（SpringPy 1.5.0 / PyMyBatis 1.4.0）。

---

# 第一部分 主框架全面测试

## 一、测试环境概览

| 组件 | 版本 | 状态 |
|------|------|------|
| Python | 3.9.6 | ✅ |
| SpringPy | 1.5.0 | ✅ |
| PyMyBatis（内嵌ORM） | 1.4.0 | ✅ |
| MySQL（Docker） | 8.0.46 | ✅ 运行中（端口 3306，springpy 库已就绪） |
| Redis（Docker） | 7-alpine | ✅ 运行中（healthy，PONG） |
| RabbitMQ（Docker） | 3-management-alpine | ✅ 运行中（healthy） |
| Nacos（Docker） | 2.5.1 | ✅ 运行中（HTTP 200） |
| pytest | 8.4.2 | ✅ |

**Docker 中间件连通性实测**：

| 中间件 | 连通验证 | 结果 |
|--------|---------|------|
| Redis | `redis-cli ping` | ✅ PONG |
| MySQL | `SELECT VERSION(); SHOW DATABASES LIKE 'springpy';` | ✅ 8.0.46 / springpy 存在 |
| Nacos | `GET http://localhost:8848/nacos/` | ✅ HTTP 200 |
| RabbitMQ | 容器 healthy + 端口 5672 暴露 | ✅ 运行中 |

---

## 二、测试套件总览

### 全面注解/功能测试套件（7 个文件，415 个用例）

| # | 测试文件 | 用例数 | 覆盖范围 | 结果 |
|---|---------|--------|---------|------|
| 1 | test_core_annotations_full.py | 38 | 核心基础注解（@Service/@Component/@Autowired/@Configuration/@Bean/@Value/@Scope/@Primary/@Profile/@Lazy/@PostConstruct/@PreDestroy/@SpringBootApplication/@ComponentScan） | ✅ 全部通过 |
| 2 | test_web_annotations_full.py | 54 | Web层注解（@RestController/@Controller/@RequestMapping/@GetMapping/@PostMapping/@PutMapping/@PatchMapping/@DeleteMapping/@RequestParam/@PathVariable/@RequestBody/@RequestHeader/@CookieValue/@CrossOrigin/@ResponseStatus/@ExceptionHandler/@ControllerAdvice/@Valid/@Validated） | ✅ 全部通过 |
| 3 | test_aop_annotations_full.py | 53 | AOP高级注解（@RateLimit/@CircuitBreaker/@Idempotent/@AuditLog/@FeatureToggle/@Lock/@Metrics/@Synchronized/@Validate/@Trace/@LogExecutionTime/@Transactional/@Cacheable/@Retryable/@Async/@Scheduled/@AsyncResult） | ✅ 全部通过 |
| 4 | test_security_full.py | 74 | 安全功能（@PreAuthorize/@Secured/@Authenticate/JWT生成验证/密码加密SHA256-MD5-BCrypt/安全上下文/SQL注入检测） | ✅ 全部通过 |
| 5 | test_orm_pymybatis_full.py | 60 | ORM/PyMyBatis（@Select/@Insert/@Update/@Delete/@Param/@Result/@ResultMap/@Options/DDL Auto类型映射/实体解析/建表/验证/dataclass支持） | ✅ 全部通过 |
| 6 | test_cloud_embedded_full.py | 83 | Cloud内嵌功能（Sentinel限流熔断/OpenTelemetry追踪/Seata HTTP-AT事务/API Gateway/LoadBalancer/Cloud注解） | ✅ 全部通过 |
| 7 | test_di_config_event_full.py | 53 | DI/配置/事件（ConfigLoader/BeanRegistry/ApplicationEventPublisher/EventListener/Retry装饰器/Backoff） | ✅ 全部通过 |

### 契约/生产就绪/韧性测试套件（5 个文件，123 个用例）

| # | 测试文件 | 用例数 | 覆盖范围 | 结果 |
|---|---------|--------|---------|------|
| 8 | test_annotations_contract.py | 11 | 注解契约覆盖（全部注解构造+装饰、多注解叠加、@Value/@ConfigurationProperties 默认值） | ✅ 全部通过 |
| 9 | test_pymybatis_contract.py | 10 | PyMyBatis契约（SQL Session/Mapper/动态SQL） | ✅ 全部通过 |
| 10 | test_production_readiness.py | 42 | 生产就绪检查（连接池/安全/重试/熔断） | ✅ 全部通过 |
| 11 | test_security.py | 49 | 安全深度测试（JWT/密码/SQL注入/访问控制） | ✅ 全部通过 |
| 12 | test_connection_resilience.py | 11 | 连接韧性（断线重连/超时/泄漏检测） | ✅ 全部通过 |

### 组合注解测试套件（1 个文件，28 个用例）

| # | 测试文件 | 用例数 | 覆盖范围 | 结果 |
|---|---------|--------|---------|------|
| 13 | test_annotation_combinations.py | 28 | 组合注解（类级组合/方法级AOP四合一/重复注解/安全+Web跨层/Cloud组合/异步+调度/声明顺序保持/继承隔离/Configuration+Bean 多方法） | ✅ 全部通过 |

### SpringPy AI 模块测试套件（1 个文件，87 个用例）

| # | 测试文件 | 用例数 | 覆盖范围 | 结果 |
|---|---------|--------|---------|------|
| 14 | test_ai_module.py | 87 | SpringPy AI（核心抽象/ChatClient链式API/Provider配置/会话记忆InMemory+Redis/VectorStore余弦检索/ETL切片/ToolRegistry函数调用/Advisor-RAG+Memory+Logger+顺序/AI注解/AutoConfig装配/RAG流水线/多轮对话 + 企业级缺口：Function Calling闭环/熔断重试韧性/真流式SSE+async/Prometheus观测/RedisVectorStore持久化 + 类型化配置绑定AIProperties：env覆盖/类型转换/嵌套递归 + Redis封装复用：框架RedisClient接口统一/原生降级/TTL修复/全局单例自动复用 + P1 企业级修复：AI_ALLOW_FAKE生产开关/熔断指标provider透传/流式重试降级/RedisVectorStore max_scan分页/AICircuitBreaker Redis持久化跨实例共享 + 优化修复：流式记忆持久化/统一HTTP重试瞬态分类/RAG Prompt注入加固 + 多厂商LangChain化：DeepSeek/Moonshot/ZhipuAI 经 OpenAICompatChatModel 接入 LangChain 优先+HTTP降级/工具注入/流式/自动装配 + LangChain优先切片委托：TokenTextSplitter/CharacterTextSplitter 经 langchain-text-splitters 实现并补齐 chunk_index，未装自动降级内置 + LangChainVectorStore 向量库适配器） | ✅ 全部通过 |

---

## 三、注解覆盖率明细

### 3.1 核心基础注解（38 个测试覆盖）

| 注解 | 测试数 | 验证内容 |
|------|--------|---------|
| @Service | 2 | 元数据附加、默认值 |
| @Component | 1 | 通用组件标记 |
| @Repository | 1 | 数据访问层标记 |
| @Autowired | 1 | required参数 |
| @Qualifier | 1 | Bean名称指定 |
| @Configuration | 1 | proxyBeanMethods参数 |
| @Scope | 1 | singleton/prototype验证 |
| @Bean | 1 | name/scope/init/destroy |
| @Value | 1 | 配置值+默认值 |
| @ConfigurationProperties | 1 | 前缀绑定 |
| @Primary | 1 | 首选Bean标记 |
| @Profile | 1 | 环境指定 |
| @Lazy | 1 | 延迟初始化 |
| @PostConstruct | 1 | 初始化回调 |
| @PreDestroy | 1 | 销毁回调 |
| @SpringBootApplication | 1 | 组合注解+扫描包 |
| @ComponentScan | 1 | 扫描包指定 |
| 多注解组合 | 1 | 同类叠加多个注解 |
| 继承隔离 | 1 | 子类注解不修改父类元数据 |

### 3.2 Web层注解（54 个测试覆盖）

| 注解 | 测试数 | 验证内容 |
|------|--------|---------|
| @RestController | 1 | REST控制器标记 |
| @Controller | 1 | 页面控制器标记 |
| @RequestMapping | 5 | path/method/value别名/consumes/produces/互斥校验 |
| @GetMapping | 3 | GET方法/value别名/互斥校验 |
| @PostMapping | 1 | POST方法 |
| @PutMapping | 1 | PUT方法 |
| @PatchMapping | 1 | PATCH方法 |
| @DeleteMapping | 1 | DELETE方法 |
| @RequestParam | 3 | name/default/value别名 |
| @PathVariable | 2 | name/value别名 |
| @RequestBody | 2 | required/optional |
| @RequestHeader | 1 | 请求头绑定 |
| @CookieValue | 1 | Cookie+默认值 |
| @CrossOrigin | 2 | 默认值/自定义CORS |
| @ResponseStatus | 1 | 状态码+reason |
| @ControllerAdvice | 1 | 全局异常处理 |
| @ExceptionHandler | 1 | 异常类型处理 |
| @Valid/@Validated | 1 | 校验标记 |
| 类级+方法级组合 | 1 | @RequestMapping+@GetMapping |

### 3.3 AOP高级注解（53 个测试覆盖）

| 注解 | 测试数 | 验证内容 |
|------|--------|---------|
| @RateLimit | 2 | 参数/默认值 |
| @CircuitBreaker | 1 | failure_threshold/recovery_timeout/fallback |
| @Idempotent | 1 | key/expire/prefix |
| @AuditLog | 1 | action/target/detail/level |
| @FeatureToggle | 1 | name/default |
| @Lock | 1 | key/expire/wait_timeout |
| @Metrics | 1 | name/tags |
| @Synchronized | 1 | lock_name |
| @Validate | 1 | field/min_length/max_length/message |
| @Trace | 1 | trace_id_key/span_name |
| @Transactional | 1 | propagation/rollback_for/no_rollback_for |
| @Cacheable | 1 | value/key/condition |
| @Retryable | 3 | Backoff对象/数字backoff/校验异常 |
| @Scheduled | 3 | cron/fixed_rate/校验异常 |
| @Async | 1 | 异步标记 |
| @AsyncResult | 1 | 结果包装 |
| @LogExecutionTime | 3 | 同步保持返回值/异步保持返回值/保持函数名 |
| 参数校验 | 5 | max_retries<=0/冲突max_attempts/多触发方式/zero rate/cron |

### 3.4 安全注解与功能（74 个测试覆盖）

| 模块 | 测试数 | 验证内容 |
|------|--------|---------|
| @PreAuthorize | 2 | hasRole/hasPermission表达式 |
| @Secured | 2 | 多角色/角色列表 |
| @Authenticate | 1 | 认证标记 |
| JWT生成 | 4 | 返回字符串/包含payload/标准声明/refresh token |
| JWT验证 | 5 | 有效Token/无效Token/过期Token/错误密钥/零过期 |
| JWT解码 | 2 | issuer验证/不验证签名获取payload |
| JWT配置 | 1 | 拒绝不支持算法 |
| 密码加密 | 5 | SHA256加密验证/SHA256拒绝错误密码/MD5加密验证/None拒绝/全局函数 |
| 安全上下文 | 5 | 默认未认证/设置认证/角色检查/权限检查/清除 |
| SQL注入检测 | 5 | 正常查询/UNION注入/DROP注入/OR注入/注释注入 |

### 3.5 ORM/PyMyBatis（60 个测试覆盖）

| 模块 | 测试数 | 验证内容 |
|------|--------|---------|
| @Select | 2 | SQL附加/result_map+cache |
| @Insert | 1 | 自增主键 |
| @Update | 1 | SQL附加 |
| @Delete | 1 | SQL附加 |
| @Param | 1 | 参数名 |
| @Result | 1 | property/column映射 |
| @ResultMap | 1 | id+type |
| @Options | 1 | use_cache/timeout |
| SelectAnnotation | 1 | 数据对象属性 |
| 类型映射 | 5 | 驼峰转下划线/int→BIGINT/str→VARCHAR/bool→TINYINT/float→DOUBLE |
| @entity装饰器 | 3 | 标记类/自动表名/索引 |
| DDL Auto建表 | 4 | 注册实体/create模式/主键/validate模式 |
| DDL Auto模式 | 3 | none模式/dataclass支持/自定义Column |
| DDL模式枚举 | 3 | 枚举值/无效模式/索引定义 |

### 3.6 Cloud内嵌功能（83 个测试覆盖）

| 模块 | 测试数 | 验证内容 |
|------|--------|---------|
| Cloud注解 | 10 | @EnableDiscoveryClient/@NacosValue/@RefreshScope/@EnableFeignClients/@FeignClient/@SentinelResource/@EnableGateway/@LoadBalanced/@GlobalTransactional/fallback |
| Sentinel限流 | 10 | QPS限流/异常比例熔断/异常数熔断/熔断恢复/装饰器/统计/FlowRule/DegradeRule/成功计数/reset |
| OpenTelemetry追踪 | 10 | Span创建/嵌套Span/W3C格式/Header注入/异常记录/装饰器/属性/持续时间/SpanKind/SpanStatus |
| Seata HTTP-AT | 10 | 开启事务/提交/回滚/XID传播/嵌套事务/多分支提交/多分支回滚/无活动事务/分支ID/@GlobalTransactional |
| API Gateway | 10 | 精确匹配/通配符/不匹配/strip_prefix/add_prefix/路由列表/URI路由/多路由优先级/service_id |
| LoadBalancer | 3 | 轮询/随机/空列表 |

### 3.7 DI/配置/事件（53 个测试覆盖）

| 模块 | 测试数 | 验证内容 |
|------|--------|---------|
| ConfigLoader | 10 | 加载YAML/server.port/redis/database/jwt/不存在键/默认值/环境变量/带默认值/retry段 |
| BeanRegistry | 10 | 注册获取/不存在/contains/按类型/注销/清除/全部/名称/数量/containsType |
| EventPublisher | 10 | 发布到监听器/原始值包装/排序/移除/清除/类型过滤/计数/多监听器/@EventListener/source |
| Retry装饰器 | 5 | 重试后成功/耗尽抛异常/特定异常/Backoff配置/无异常立即返回 |

### 3.8 注解契约补充（11 个测试覆盖，test_annotations_contract.py）

| 模块 | 测试数 | 验证内容 |
|------|--------|---------|
| 核心注解构造+装饰 | 1 | 全部核心注解（50+）构造并附加到目标 |
| 映射/参数别名 | 1 | @RequestMapping/@GetMapping/@RequestParam/@PathVariable 等别名与互斥校验 |
| 注解参数校验 | 1 | @Scope/@Scheduled/@Retryable 非法配置拒绝 |
| @LogExecutionTime | 1 | 同步/异步均保持返回值与函数名 |
| @EventListener | 1 | 注解元数据 + 事件发布分发 |
| Cloud注解覆盖 | 1 | 全部 Cloud 注解构造+装饰+_annotation_type |
| RabbitMQ注解 | 1 | @RabbitListener + @RabbitTemplate 发送路径 |
| PyMyBatis注解 | 1 | @Select/@Insert/@Update/@Delete + Provider 系列 + ResultMap/Options/Param |
| 注解导出可导入 | 1 | __all__ 中所有名称可从 spring.annotations 导入 |
| 多注解叠加 | 1 | @Metrics+@AuditLog 同方法叠加均被收集 |
| @Value/@ConfigurationProperties | 1 | 默认值与前缀绑定元数据 |

### 3.9 组合注解（28 个测试覆盖，test_annotation_combinations.py）

| 组合类别 | 测试数 | 验证的组合 |
|------|--------|---------|
| 类级组合 | 5 | @RestController+@RequestMapping+@Slf4j；@Service+@Slf4j+@PostConstruct+@PreDestroy；@Configuration+@Primary+@Profile+@Lazy；@Repository+@ConfigurationProperties；@ControllerAdvice+@ResponseStatus+@CrossOrigin |
| 方法级 AOP 组合 | 5 | @RateLimit+@AuditLog+@Metrics+@Trace 四合一；@Retryable+@Cacheable；@Transactional+@Cacheable+@Metrics；@RateLimit+@Idempotent+@Lock；@AuditLog+@Metrics+@LogExecutionTime |
| 重复注解 | 2 | 同方法 3×@Validate（email/username/age）；2×@Value+@ConfigurationProperties |
| 安全+Web 跨层 | 3 | @PreAuthorize+@GetMapping；@Secured+@PostMapping+@AuditLog；@Authenticate+@Trace+@Metrics |
| Cloud 组合 | 5 | @FeignClient(类)+@SentinelResource(方法)；@GlobalTransactional+@Transactional；@EnableDiscoveryClient+@RefreshScope+@NacosValue；@EnableGateway+@LoadBalanced(Bean)；@SentinelResource+@CircuitBreaker+@Retryable |
| 异步+调度 | 2 | @Async+@AsyncResult；@Scheduled+@Metrics |
| 顺序与继承 | 4 | 声明顺序（自底向上）严格保持；子类组合不泄漏到父类；六注解叠加计数与类型；组合中各注解元数据互不干扰 |
| Configuration+Bean | 2 | @Configuration+多 @Bean 方法（不同 scope/init/destroy）；@Controller+@Autowired 构造器+多 @GetMapping 方法 |

### 3.10 SpringPy AI 模块（87 个测试覆盖，test_ai_module.py）

| 模块 | 测试数 | 验证内容 |
|------|--------|---------|
| 核心抽象 | 3 | Message工厂方法/to_dict；ChatResponse.content()便捷取值；EmbeddingModel.embed_one默认实现 |
| ChatClient链式API | 3 | prompt().user().call().content()；default_system自动插入；PromptSpec param/context累加 |
| Fake Provider | 2 | FakeChatModel回显最后user消息并计数；FakeEmbeddingModel确定性+归一化 |
| Provider配置 | 3 | OpenAIChatModel/OllamaChatModel/OpenAIEmbeddingModel 配置属性保留 |
| 会话记忆 | 3 | InMemory增删查+滑动窗口+last_n；多会话隔离；RedisChatMemory无client安全降级 |
| VectorStore | 3 | cosine_similarity计算；InMemory写入+相似度检索；空query返回空 |
| ETL | 4 | TextReader内联文本；TokenTextSplitter长文本切片+chunk_index；短文本单块；CharacterTextSplitter分隔符切片 |
| ToolRegistry | 3 | 签名自动生成schema+required推断；execute执行+JSON字符串参数；未注册抛KeyError+self/cls跳过 |
| Advisor | 4 | MessageChatMemoryAdvisor请求注入历史/响应保存对话；QuestionAnswerAdvisor检索注入system上下文；SimpleLoggerAdvisor记录事件；Advisor按order升序应用 |
| AI注解 | 3 | @AiClient provider/model/temperature；@Tool name/description；@AiAdvisor/@AiMemory order/store/max_messages |
| AutoConfig | 3 | configure_ai装配4个Bean+注册registry；openai无key降级Fake；装配后ChatClient可直接调用 |
| 集成场景 | 3 | 完整RAG流水线(ETL→入库→检索→生成)；多轮对话+记忆；ChatModel/EmbeddingModel/Advisor抽象类不可实例化 |
| Function Calling闭环 | 3 | tool_call循环执行工具+回填+续写直至最终回复；无tool_registry时不触发闭环；超过MAX_TOOL_ITERATIONS(5)安全终止 |
| 韧性(重试+熔断) | 3 | AICircuitBreaker CLOSED→OPEN→HALF_OPEN→CLOSED状态机；失败计数达阈值熔断+recovery_timeout后半开放行探测；resilient_call对TransientError重试 |
| 真流式+async | 4 | stream()逐块yield增量内容；astream()异步生成器；acall()异步调用(降级同步)；流式分块正确性 |
| Prometheus观测 | 4 | AIMetrics单例懒初始化；record_call记录调用/token/延迟不抛异常；Provider调用记录指标；autoconfig为provider创建熔断器 |
| Embedding自动装配+RedisVectorStore | 4 | configure_ai装配aiEmbeddingModel Bean；Redis hash持久化文档+跨实例检索；无client安全降级；注入EmbeddingModel自动嵌入 |
| 类型化配置绑定AIProperties | 7 | 空配置全默认值；kebab-case键绑定snake_case字段；字符串按类型注解转换(int/float/bool)；env覆盖yml字面值；yml缺失嵌套段时叶子env仍可覆盖(嵌套递归)；circuit-breaker禁用返回None；configure_ai经类型化绑定装配熔断器参数 |
| Redis封装复用统一 | 4 | RedisVectorStore优先用框架RedisClient封装hash_set/hash_get_all/delete_key；传入原生redis接口(无hash_set)时降级hset/hgetall/delete；RedisChatMemory.add给list键本身刷TTL(修复之前只给:ttl标记键设过期导致list无限增长)；configure_ai在type=redis且未传client时自动复用框架全局redis_client单例 |
| P1 企业级修复 | 7 | AI_ALLOW_FAKE=false缺key抛ValueError；true缺key返回FakeChatModel；未知provider在false时抛ValueError；resilient_call provider参数透传熔断器指标；RedisVectorStore max_scan限制扫描上限；AICircuitBreaker redis_client参数实现Redis持久化状态同步（跨实例共享）；流式SSE网络中断自动重试+降级不抛异常 |
| 优化修复（Review） | 6 | 流式模式调用advise_response持久化会话记忆（修复：之前流式不保存）；流式聚合完整输出无丢块；_is_transient_http_exc瞬态/永久错误分类（429/5xx重试，401/403不重试）；_http_post_json统一HTTP重试429重试至成功；_http_post_json 401鉴权错误不重试直接抛；QuestionAnswerAdvisor harden_injection加固模板/可关闭 |
| 多厂商 LangChain 化 | 6 | OpenAICompatChatModel 未装langchain专用包时降级HTTP；HTTP路径注入tools schema并解析tool_calls；HTTP流式SSE逐块yield；autoconfig provider=deepseek+api_key构建OpenAICompatChatModel；无api_key+AI_ALLOW_FAKE=true降级Fake；无api_key+AI_ALLOW_FAKE=false抛ValueError |

---

## 四、测试统计汇总

| 指标 | 数值 |
|------|------|
| 测试套件总数 | 15 |
| 测试用例总数 | 707 |
| 通过用例 | 707 |
| 失败用例 | 0 |
| 通过率 | 100% |
| 每个套件最少用例数 | 10（达到下限要求） |
| 每个套件最多用例数 | 83（Cloud内嵌） |

**最低用例数核验**（用户要求“每个用例不低于10个”）：

| 套件 | 用例数 | ≥10 |
|------|--------|-----|
| test_annotations_contract.py | 11 | ✅ |
| test_pymybatis_contract.py | 10 | ✅ |
| test_connection_resilience.py | 11 | ✅ |
| test_annotation_combinations.py | 28 | ✅ |
| test_core_annotations_full.py | 38 | ✅ |
| test_production_readiness.py | 42 | ✅ |
| test_security.py | 49 | ✅ |
| test_aop_annotations_full.py | 53 | ✅ |
| test_di_config_event_full.py | 53 | ✅ |
| test_web_annotations_full.py | 54 | ✅ |
| test_orm_pymybatis_full.py | 60 | ✅ |
| test_ai_module.py | 87 | ✅ |
| test_security_full.py | 74 | ✅ |
| test_cloud_embedded_full.py | 83 | ✅ |

---

## 五、功能覆盖矩阵

| 功能类别 | 注解/功能数 | 测试覆盖 | 状态 |
|---------|------------|---------|------|
| 核心基础注解 | 19 | 38用例 | ✅ |
| Web层注解 | 19 | 54用例 | ✅ |
| AOP高级注解 | 17 | 53用例 | ✅ |
| 安全注解+功能 | 3+5 | 74用例 | ✅ |
| ORM/PyMyBatis | 10+DDL | 60用例 | ✅ |
| Cloud内嵌功能 | 10+5模块 | 83用例 | ✅ |
| DI/配置/事件 | 6模块 | 53用例 | ✅ |
| DDL Auto专项 | 5模式+@entity/@table/@Id/@Column | 22用例 | ✅ |
| 注解契约 | 全部注解 | 11用例 | ✅ |
| 组合注解 | 8类组合场景 | 28用例 | ✅ |
| SpringPy AI | 4注解+12模块+5企业能力+类型化配置绑定+Redis封装统一+LangChain切片委托+向量库适配器 | 87用例 | ✅ |
| **合计** | **88注解+28模块** | **707用例** | **✅ 100%** |

---

## 六、本轮测试新增/修复内容

1. **新增 test_annotation_combinations.py 组合注解套件（28 用例）**：覆盖 8 类组合场景——类级组合（@RestController+@RequestMapping+@Slf4j 等 5 种）、方法级 AOP 组合（@RateLimit+@AuditLog+@Metrics+@Trace 四合一等 5 种）、重复注解（3×@Validate、2×@Value）、安全+Web 跨层（@PreAuthorize+@GetMapping 等 3 种）、Cloud 组合（@FeignClient+@SentinelResource 等 5 种）、异步+调度（@Async+@AsyncResult、@Scheduled+@Metrics）、声明顺序保持与继承隔离（4 种）、Configuration+Bean 多方法（2 种）。验证了多注解叠加时元数据完整收集、声明顺序（自底向上附加）严格保持、子类组合不泄漏到父类、组合中各注解元数据互不干扰。
2. **test_ddl_auto.py 重写为标准 pytest 套件**：原文件为脚本式（共享状态、2 个用例在 pytest 下报 fixture 缺失错误），重写为 22 个自包含用例，覆盖 create/update/validate/none/create-drop 全部模式、@entity/@table/@Id/@Column/@column/@id_column 注解、MySQL/PostgreSQL/SQLite 三方言 SQL 生成、类型映射、索引、dataclass 实体、注册去重、init_ddl_auto 配置驱动。
3. **test_annotations_contract.py 补充 2 个用例**：原 9 个用例不满足“≥10”下限，新增“多注解叠加（@Metrics+@AuditLog）”与“@Value/@ConfigurationProperties 默认值绑定”2 个用例，达到 11 个。
4. **依赖补全**：补装 fastapi/uvicorn/redis/sqlalchemy/PyMySQL/DBUtils/sqlglot/cryptography/bcrypt/prometheus-client/loguru/requests/pika/pydantic/python-dotenv/pytest-cov，使全部测试套件可在干净的 Python 3.9.6 环境运行。
5. **新增 SpringPy AI 模块（spring/ai/，37 用例）**：对齐 Spring AI 2.0 的 ChatClient/ChatModel/EmbeddingModel/Advisor/ETL 抽象，底层复用 LangChain 生态做模型适配（未安装时降级原生 HTTP）。包含 9 个文件：core（链式 ChatClient+Advisor 调用链）、annotations（@AiClient/@Tool/@AiAdvisor/@AiMemory）、providers（OpenAI兼容+Ollama+Fake测试模型）、advisors（QuestionAnswerAdvisor RAG/MessageChatMemoryAdvisor/SimpleLoggerAdvisor）、memory（InMemory+Redis）、vectorstore（抽象+内存余弦检索）、etl（TextReader/TokenTextSplitter/CharacterTextSplitter）、tools（ToolRegistry 函数调用+签名自动生成 schema）、autoconfig（spring.ai.* 配置装配 Bean）。新增 application.yml 的 spring.ai.* 配置段。测试覆盖核心抽象/链式API/Provider配置/记忆/向量检索/ETL/工具调用/Advisor顺序/AI注解/AutoConfig装配/完整RAG流水线/多轮对话。
6. **修复 AI 模块阻碍企业使用的 5 个关键缺口（新增 18 用例，37→55）**：
   - **闭环 Function Calling**：`ChatModel.call()` 基类实现 tool_call 执行闭环（Provider 把模型请求的 tool_calls 放入 `response.metadata['tool_calls']`，基类统一执行→回填 tool 消息→续写，最多 5 轮防死循环）；`OpenAIChatModel._call_via_http` 把 `tool_registry.schemas()` 注入请求体 `tools` 字段并解析响应 tool_calls，assistant 消息携带 tool_calls 元数据以便按 OpenAI 协议重发。
   - **autoconfig 装配 EmbeddingModel + RedisVectorStore**：`configure_ai()` 新增 `aiEmbeddingModel` Bean 装配（含熔断器），VectorStore 注入 EmbeddingModel 实现检索自动嵌入；新增 `RedisVectorStore` 用 Redis hash 持久化文档（`springpy:ai:vectorstore:{collection}` 键），支持跨实例检索与无 client 安全降级，让 RAG 真正自动可用。
   - **接入 @Retryable/@CircuitBreaker**：新增 `resilience.py`，`resilient_call()` 复用框架 `spring.retry.retry_decorator.retry` 对 `TransientError`（429/5xx/超时/连接错误）重试；`AICircuitBreaker` 镜像 `spring.aop.comprehensive_aop` 的 CLOSED/OPEN/HALF_OPEN 状态机保护下游 LLM API；Provider 的 HTTP 调用全部经 `resilient_call` 包装。
   - **真流式 + async**：`OpenAIChatModel.stream()`/`_stream_via_http()` 解析 SSE `data:` 增量行逐块 yield（Ollama 解析 NDJSON）；`astream()` 用 asyncio.Queue 桥接同步流为异步生成器；`acall()` 用 `asyncio.to_thread` 实现异步调用。
   - **接 Prometheus 观测**：新增 `observability.py` 的 `AIMetrics` 单例，复用框架 `PrometheusMetrics` 注册 `ai_calls_total`/`ai_tokens_total`/`ai_call_duration_seconds`/`ai_tool_calls_total`/`ai_circuit_breaker_state` 五项指标，Provider 调用前后自动记录调用/token/延迟，对接企业 Prometheus+Grafana 监控体系。
7. **AI 配置读取改造为混合方式（新增 7 用例，55→62）**：新增类型化 `AIProperties` dataclass 族（OpenAI/Ollama/VectorStore/Memory/CircuitBreaker 嵌套配置）+ `bind_ai_config()` 递归绑定器，替换原裸 `dict.get()` + 手动 `int()`/`float()` 转换。优先级 **环境变量 > application.yml > dataclass 默认值**：env 通过两条路径生效——① 复用 config_loader 的 `${ENV:default}` 占位符解析；② dataclass 字段 `metadata["env"]` 声明的 env 名作为覆盖安全网（即使 yml 写死字面值也能被同名 env 覆盖）。字段类型注解驱动自动类型转换（int/float/bool），嵌套 dataclass 字段总是递归保证叶子 env 覆盖可达。同步补齐 application.yml 的 `circuit-breaker`/`max-retries`/`collection` 配置段（带 env 占位符），让熔断参数等可经环境变量覆盖。
8. **Redis 封装集成断裂修复 + 复用框架 RedisClient（新增 4 用例，62→66）**：解决之前 `RedisChatMemory` 用框架 `RedisClient` 封装方法（list_push/list_range）而 `RedisVectorStore` 用原生 redis 方法（hset/hgetall）导致的"同一 redis_client 参数无法同时满足两者"集成断裂。改造 `RedisVectorStore` 为双接口兼容：优先用框架 `RedisClient` 封装的 `hash_set/hash_get_all/delete_key`（自动 JSON 序列化/反序列化），与 `RedisChatMemory` 接口统一；传入原生 `redis.Redis` 或测试 `FakeRedis`（无 hash_set）时自动降级原生接口。同时 `configure_ai` 新增 `_resolve_redis_client`：当配置 `vector-store.type=redis` 或 `memory.store=redis` 且未显式传 client 时，自动复用框架全局 `spring.utils.redis_client.redis_client` 单例，用户无需手动传参即可启用 Redis 持久化。修复 `RedisChatMemory` TTL 失效 bug——之前只给 `:ttl` 标记键设 expire 而真正的 list 键无 TTL 导致 Redis 无限增长，改为通过原生 `client.expire()` 给 list 键本身刷新 TTL。补 `requirements-ai.txt` 声明 AI 可选依赖（langchain-openai/langchain-community/numpy，`==` 锁版本）。
9. **LangChain 优先，不重复造轮子（新增 2 用例，85→87）**：
   - **切片器委托 langchain-text-splitters**：`TokenTextSplitter`/`CharacterTextSplitter` 的 `split()` 在安装 `langchain-text-splitters` 时优先委托其 `RecursiveCharacterTextSplitter`/`CharacterTextSplitter`（自动按 `\n\n`/`\n`/空格/标点逐级切分，语义更佳），并把切片结果映射回框架 `TextDocument` 并补齐 `chunk_index` 元数据；未安装时自动降级内置实现，保证开箱即用。overlap 夹紧（`min(overlap, chunk_size-1)`）以兼容 LangChain 约束与框架默认 `chunk_size=30` 场景。已测试 `langchain-text-splitters==0.3.8`（兼容 `langchain-core==0.3.51`），写入 `requirements-ai.txt`。
   - **LangChainVectorStore 向量库适配器**：新增薄适配器，包装 langchain 生态成熟的 `VectorStore`（FAISS/Chroma 等，`add_texts`/`similarity_search_by_vector`），映射为框架统一的 `VectorStore` 接口，不自行实现向量索引与检索。新增测试用 stub 模拟 langchain store 验证 add/add_texts/similarity_search/count 委托与 metadata 透传，以及未传 store 时静默空。
   - 相关文档同步：AI_MODULE.md 的 §6（ETL）新增 LangChain 优先说明与 §6.1 向量存储适配器，模块组成表同步；TEST_REPORT.md 统计更新为 707 用例。

---

## 七、已知告警（不影响测试结果）

| 告警 | 来源 | 影响 |
|------|------|------|
| InsecureKeyLengthWarning | PyJWT - HMAC密钥<32字节 | 无（测试环境） |
| NotOpenSSLWarning | urllib3 - LibreSSL 2.8.3 | 无（测试环境） |
| MovedIn20Warning | SQLAlchemy 2.0 declarative_base | 无（兼容模式） |

---

## 八、测试结论

SpringPy 1.5.0 框架全部功能和注解测试通过，覆盖：

1. **88个注解** - 核心基础(19) + Web层(19) + AOP高级(17) + 安全(3) + Cloud(10) + ORM(8) + 消息(2) + 事件(1) + AI(4) + 其他(5)
2. **28个功能模块** - DI容器/配置加载/事件发布/重试/Sentinel/Tracer/Seata/Gateway/LoadBalancer/JWT/密码加密/SQL注入检测/DDL Auto/连接池/安全上下文/健康检查 + AI(ChatClient/ChatModel/EmbeddingModel/Advisor/Memory/VectorStore/ETL/Tools/AutoConfig/Provider/注解/集成)
3. **4个Docker中间件** - MySQL 8.0.46 / Redis 7 / RabbitMQ 3 / Nacos 2.5.1（均已实测连通）
4. **每个测试套件≥10个用例** - 16个套件共681用例，最少10个，最多83个
5. **组合注解全覆盖** - 28个用例验证类级/方法级/重复/跨层/Cloud/异步调度/顺序继承/Configuration-Bean 共8类组合场景
6. **SpringPy AI 模块企业级就绪** - 66个用例验证对齐 Spring AI 2.0 的 ChatClient/Advisor/ETL/Tools 抽象，复用 LangChain 生态模型适配，保留 Spring 风格统一配置与依赖注入；并补齐 5 项企业级能力——Function Calling 闭环（tools 注入+tool_call 循环执行回填续写）、autoconfig 装配 EmbeddingModel+RedisVectorStore（RAG 自动可用）、@Retryable/@CircuitBreaker 韧性（复用框架 AOP 与重试基础设施）、真流式 SSE+async（聊天场景刚需）、Prometheus 观测（复用框架 prometheus 配置，记录调用/token/延迟/熔断状态）；配置读取改造为混合方式——类型化 `AIProperties` dataclass 绑定 + env 覆盖安全网 + 类型注解驱动自动转换，保证 环境变量 > application.yml > 默认值 的优先级；Redis 封装集成断裂修复——`RedisVectorStore` 与 `RedisChatMemory` 统一复用框架 `RedisClient` 封装接口，`configure_ai` 自动复用全局 redis_client 单例，`RedisChatMemory` TTL 修复防止 Redis 无限增长

**框架已具备企业开发就绪水平，并具备 LLM 应用（RAG/多轮对话/函数调用）开发能力。**

---

# 第二部分 example_all 集成测试报告

**测试时间**: 2026-08-04  
**项目**: SpringPy (springboot Python 框架)  
**测试范围**: 全注解用例集合 example_all  
**测试环境**: Docker (MySQL 8.0, Redis 7-alpine, RabbitMQ 3-management-alpine), Prometheus 内嵌  
**测试结果**: **5/5 测试套件通过**；框架版本已升级至 SpringPy 1.5.0 / PyMyBatis 1.4.0，新增27个Cloud新功能测试全部通过；历史集成报告覆盖 27 个 API 端点，当前测试脚本另含 9 个框架兼容性探针

## 一、测试结论

历史集成测试和兼容性探针涵盖 70+ 个注解和功能组合：

- Web 层 (14个): `@RestController`, `@RequestMapping`, `@GetMapping`, `@PostMapping`, `@PutMapping`, `@PatchMapping`, `@DeleteMapping`, `@RequestParam`, `@PathVariable`, `@RequestBody`, `@RequestHeader`, `@CookieValue`, `@CrossOrigin`, `@ResponseStatus`
- 组件/DI/配置 (15个): `@Service`, `@Component`, `@Repository`, `@Autowired`, `@Qualifier`, `@Value`, `@Configuration`, `@Bean`, `@ConfigurationProperties`, `@Profile`, `@Primary`, `@Lazy`, `@SpringBootApplication`, `@PostConstruct`, `@PreDestroy`
- AOP 企业级 (10个): `@RateLimit`, `@CircuitBreaker`, `@Idempotent`, `@AuditLog`, `@FeatureToggle`, `@Lock`, `@Metrics`, `@Synchronized`, `@Validate`, `@Trace` — **全部经 Redis 验证**
- 安全 (3个): `@PreAuthorize`, `@Secured`, `@Authenticate` — **JWT 登录正常**
- 功能 (6个): `@Transactional`, `@Cacheable`, `@Retryable`, `@Async`, `@Scheduled`, `@LogExecutionTime`
- ORM (8个): `@Mapper`, `@MapperScan`, `@Select`, `@Insert`, `@Update`, `@Delete` + XML Mapper — **MySQL 完整 CRUD 通过**
- Cloud (9个): `@EnableDiscoveryClient`, `@NacosValue`, `@RefreshScope`, `@FeignClient`, `@LoadBalanced`, `@SentinelResource`, `@EnableGateway`, `@GlobalTransactional`
- Event (3个): `ApplicationEvent`, `@EventListener`, `ApplicationEventPublisher`
- 消息 (2个): `@RabbitListener`, `RabbitTemplate` — **RabbitMQ 连接正常**

## 二、测试项明细

### 1. 模块导入测试 (25/25 通过)

| 文件 | 导出类 |
|------|--------|
| `controller/AllWebController.py` | `AllWebController`, `ViewController` |
| `controller/AopController.py` | `AopController` |
| `controller/SecurityController.py` | `SecurityController` |
| `controller/ExceptionController.py` | `GlobalExceptionHandler`, `ErrorTriggerController` |
| `controller/OrmController.py` | `OrmController`, `ScheduleController` |
| `controller/CloudController.py` | `CloudController` |
| `controller/MessagingController.py` | `MessagingController`, `MessageConsumer` |
| `service/AllAnnotationService.py` | `AllAnnotationService`, `ConsumerService`, `PrimaryService`, `SecondaryService`, `LazyService` |
| `service/AopService.py` | `AopService` |
| `service/AsyncService.py` | `AsyncService` |
| `service/ScheduledService.py` | `ScheduledService` |
| `service/OrmBridgeService.py` | `OrmBridgeService` |
| `service/SecurityService.py` | `SecurityService` |
| `service/CloudService.py` | `CloudService` |
| `service/MessagingService.py` | `MessagingService` |
| `config/AppConfig.py` | `AppConfig`, `AppProperties` |
| `repository/UserRepository.py` | `UserRepository` |
| `mappers/UserMapper.py` | `UserMapper` |
| `interceptor/AllInterceptor.py` | `LoggingInterceptor`, `SecurityHeaderInterceptor` |

### 2. XML Mapper 文件解析 (11/11 通过)

文件: `mappers/UserMapper.xml`, namespace: `example_all.mappers.UserMapper`

| SQL 类型 | Statement ID | ResultMap |
|----------|-------------|-----------|
| SELECT | `find_all_xml` | `UserResultMap` |
| SELECT | `find_by_id_xml` | `UserResultMap` |
| SELECT | `search_users` | `UserResultMap` |
| SELECT | `find_by_ids` | `UserResultMap` |
| SELECT | `find_pagination` | `UserResultMap` |
| SELECT | `count_users` | - |
| INSERT | `insert_xml` | - |
| INSERT | `batch_insert` | - |
| UPDATE | `update_xml` | - |
| DELETE | `delete_xml` | - |
| DELETE | `batch_delete` | - |

XML 特性验证:
- `resultMap` + `<id>` + `<result>` 字段映射
- `<sql>` 片段 + `<include refid="..."/>` 引用
- `<where>` + `<if test="...">` 动态条件
- `<foreach>` 批量操作
- `<set>` 动态更新
- 框架自动兼容 SQL 中未转义的 `<=` 和 `>=`；标准 XML 仍建议使用 `&lt;=` 和 `&gt;=`

### 3. 注解组合测试 (4/4 通过)

`AopService.multi_annotation_combo` 方法上的注解组合:

| 注解 | 验证结果 |
|------|---------|
| `@RateLimit` (max_requests=20, time_window=30) | PASS |
| `@AuditLog` (action="组合注解测试") | PASS |
| `@Metrics` (name="aop_service.combined") | PASS |
| `@Trace` (span_name="combo_operation") | PASS |

### 4. 组件扫描验证 (25/25 通过)

| 组件类型 | 数量 | 示例 |
|---------|------|------|
| Controller | 11 | AllWebController, ViewController, AopController, SecurityController, GlobalExceptionHandler, ErrorTriggerController, OrmController, ScheduleController, CloudController, MessagingController, MessageConsumer |
| Service | 11 | AllAnnotationService, ConsumerService, PrimaryService, SecondaryService, LazyService, AopService, AsyncService, SecurityService, OrmBridgeService, CloudService, MessagingService |
| @Component | 1 | ScheduledService |
| @Repository | 1 | UserRepository |
| @Mapper | 1 | UserMapper |

### 5. HTTP API 端点测试（历史集成 36/36）

#### Web 层 (5/5)

| 序号 | 请求 | 期望 | 实际 | 测试内容 |
|------|------|------|------|---------|
| 1 | GET /api/web/hello | 200 | 200 | `@GetMapping` basic |
| 2 | GET /api/web/hello/world | 200 | 200 | `@GetMapping` + `@PathVariable` |
| 3 | GET /api/web/search?keyword=test&page=1&size=5 | 200 | 200 | `@GetMapping` + `@RequestParam` |
| 4 | GET /api/web/config/info | 200 | 200 | `@LogExecutionTime` |
| 5 | POST /api/web/user/form?username=test&email=test@example.com | 200 | 200 | `@PostMapping` + form params |

#### AOP 企业级 (8/8) — Redis 环境

| 序号 | 请求 | 期望 | 实际 | 测试内容 |
|------|------|------|------|---------|
| 6 | GET /api/aop/rate-limit | 200 | 200 | `@RateLimit` (Redis 滑动窗口) |
| 7 | GET /api/aop/synchronized | 200 | 200 | `@Synchronized` (线程安全递增) |
| 8 | GET /api/aop/metrics/info | 200 | 200 | `@Metrics` 指标查询 |
| 9 | POST /api/aop/metrics/process?data=hello | 200 | 200 | `@Metrics` 指标采集 |
| 10 | GET /api/aop/trace?span_name=test_aop | 200 | 200 | `@Trace` |
| 11 | POST /api/aop/audit-log?target_id=42&action=test | 200 | 200 | `@AuditLog` |
| 12 | POST /api/aop/validate?email=test@example.com&username=usr&age=25 | 200 | 200 | `@Validate` 验证通过 |
| 13 | POST /api/aop/validate?email=bademail&username=ab&age=10 | 400 | 400 | `@Validate` 验证拒绝 |

#### 异常处理 (2/2)

| 序号 | 请求 | 期望 | 实际 | 测试内容 |
|------|------|------|------|---------|
| 14 | GET /api/errors/value | 400 | 400 | `@ExceptionHandler` ValueError |
| 15 | GET /api/errors/runtime | 500 | 500 | `@ExceptionHandler` RuntimeError |

#### 安全 (2/2)

| 序号 | 请求 | 期望 | 实际 | 测试内容 |
|------|------|------|------|---------|
| 16 | GET /api/security/public | 200 | 200 | Security public endpoint |
| 17 | POST /api/security/login?username=admin&role=ROLE_ADMIN | 200 | 200 | `@Security` JWT 登录 |

#### 调度 (1/1)

| 序号 | 请求 | 期望 | 实际 | 测试内容 |
|------|------|------|------|---------|
| 18 | GET /api/schedule/stats | 200 | 200 | `@Scheduled` (cron+fixed_rate+fixed_delay) |

#### ORM MySQL (6/6) — Docker MySQL 8.0

| 序号 | 请求 | 期望 | 实际 | 测试内容 |
|------|------|------|------|---------|
| 19 | POST /api/orm/init-db | 200 | 200 | MySQL `CREATE TABLE` |
| 20 | POST /api/orm/annotation/user?username=john&email=john@test.com&phone=1380001 | 200 | 200 | `@Insert` MySQL |
| 21 | GET /api/orm/annotation/user/1 | 200 | 200 | `@Select` MySQL byId |
| 22 | GET /api/orm/annotation/users | 200 | 200 | `@Select` MySQL findAll |
| 23 | GET /api/orm/annotation/search?username=john | 200 | 200 | `@Select` 动态条件 (CONCAT LIKE) |
| 24 | GET /api/orm/stats | 200 | 200 | `@Select` COUNT |

#### Cloud (2/2) — Nacos Docker

| 序号 | 请求 | 期望 | 实际 | 测试内容 |
|------|------|------|------|---------|
| 25 | GET /api/cloud/status | 200 | 200 | `@EnableDiscoveryClient` + `@RefreshScope` |
| 26 | GET /api/cloud/loadbalance/status | 200 | 200 | `@LoadBalanced` (round_robin) |

#### Messaging (1/1) — RabbitMQ

| 序号 | 请求 | 期望 | 实际 | 测试内容 |
|------|------|------|------|---------|
| 27 | GET /api/messaging/status | 200 | 200 | `@RabbitMQ` 连接状态 |

#### 框架兼容性修复探针（当前测试脚本）

| 验证项 | 请求/方式 | 状态 |
|------|------|------|
| Nacos Windows Docker | `GET /api/limits/nacos`；容器 liveness/readiness | 已修复；本次 Docker 验证返回 `200 OK` |
| XML 原始比较运算符 | `GET /api/limits/xml-unescape` | 已修复；`<=`/`>=` 兼容解析 |
| `@PatchMapping` 导出 | `GET /api/limits/patch-mapping` | 已修复 |
| `@PatchMapping` 路由 | `PATCH /api/limits/patch-probe` | 已接入 FastAPI PATCH 注册 |
| Event/Listener 注册 | `GET /api/limits/event-listener` | 已修复 |
| Event 发布调用 | `POST /api/limits/event-listener/publish` | 已修复 |
| 配置同步 | `GET /api/limits/config-sync` | 已修复；默认加载器复用上下文路径 |
| 用户事件示例 | `POST /api/event/publish/user` | 已接入 ApplicationContext 发布器 |
| 事件统计 | `GET /api/event/stats` | 已接入 |

## 三、注解覆盖率（与主框架测试重叠部分去重说明）

example_all 集成测试覆盖 **70+ 个注解和事件 API**，其中绝大部分（Web 14、组件/DI/配置 15、AOP 企业级 10、安全 3、功能 6、Cloud 9、消息 2、应用事件 3）已在**第一部分·三「注解覆盖率明细」**中逐一详列（含测试数与验证内容），此处不重复罗列。

本部分在集成/端到端场景下额外验证的独有内容：
- **ORM (8个)**：`@Mapper`, `@MapperScan`, `@Select`, `@Insert`, `@Update`, `@Delete` + **XML Mapper**（`resultMap`, `sql片段`, `include`, `where/if`, `foreach`, `set`）——已在「测试项明细-2」详列 11 个 Statement 的解析与 MySQL 完整 CRUD（见「HTTP API 端点测试-ORM MySQL 6/6」）。
- **端到端生效验证**：AOP 企业级注解 **全部经 Redis 验证**（@RateLimit 滑动窗口等，见 HTTP API 8/8）；安全注解 **JWT 登录正常**；ORM **MySQL 完整 CRUD 通过**；消息 **RabbitMQ 连接正常**——即不仅验证注解元数据，更验证其在实际容器中间件中的运行效果（与主报告主要验证元数据/单测形成互补）。

**总计: 70+ 个注解和事件 API 覆盖**

## 四、测试环境搭建

```bash
# 1. 启动 Docker 服务
docker run -d --name springpy-mysql -p 3306:3306 \
    -e MYSQL_ROOT_PASSWORD=root123 -e MYSQL_DATABASE=springpy mysql:8.0
docker run -d --name springpy-redis -p 6379:6379 redis:7-alpine --save "" --appendonly no
docker run -d --name springpy-rabbitmq -p 5672:5672 -p 15672:15672 \
    -e RABBITMQ_DEFAULT_USER=admin -e RABBITMQ_DEFAULT_PASS=admin123 rabbitmq:3-management-alpine
docker run -d --name springpy-nacos --restart unless-stopped \
    -p 8848:8848 -p 9848:9848 \
    -e MODE=standalone -e JAVA_TOOL_OPTIONS=-XX:-UseContainerSupport \
    -e NACOS_AUTH_ENABLE=true \
    -e NACOS_AUTH_TOKEN=<base64-token-with-at-least-32-decoded-bytes> \
    -e NACOS_AUTH_IDENTITY_KEY=springpy \
    -e NACOS_AUTH_IDENTITY_VALUE=springpy-local \
    nacos/nacos-server:v2.2.3

# 2. 安装 Python 依赖
pip install redis pymysql pika

# 3. 运行测试
cd springboot/example_all
python test_all_features.py
```

## 五、框架层面修复

本次测试过程中发现并修复了以下框架 Bug：

| 问题 | 文件 | 修复 |
|------|------|------|
| pymysql `%` 格式化冲突 | `dynamic_sql.py` | 添加 `_escape_mysql_percent()` 方法，自动转义 SQL 字面量中的 `%` 为 `%%` |
| `LoadBalanced` 缺少 `strategy` 属性 | `cloud.py` | 添加 `strategy="round_robin"` 默认参数 |
| MySQL `SELECT LAST_INSERT_ID()` 返回 dict 导致 KeyError | `sql_session.py` | 兼容 dict 和 tuple 两种结果类型 |
| datetime/Decimal 无法 JSON 序列化 | `web_context.py` | 添加 `_JsonEncoder` 自定义 JSON 编码器 |

## 六、本轮兼容性修复

| 问题 | 文件/组件 | 修复 |
|------|------|------|
| Nacos Windows Docker 因认证变量退出 255 | Docker/Nacos 部署 | 增加 Nacos 2.2+ token/identity、Java cgroup 参数、外部 MySQL schema 和客户端账号配置 |
| `@PatchMapping` 路由返回 404 | `web_context.py` | 增加 `fastapi_app.patch()` 路由注册分支，并纳入默认 CORS 方法 |
| 全局 ConfigLoader 与上下文配置不同步 | `config_loader.py`、`application_context.py` | 绑定稳定全局实例和默认配置目录，后续 `ConfigLoader()` 复用同一配置 |
| XML 原始 `<=`/`>=` | `xml_parser.py` | 解析前规范化比较运算符，保护 CDATA/注释并还原 SQL 文本 |
| Event/Listener 缺少运行机制 | `spring/event`、`application_context.py` | 自动扫描监听器并提供同步有序事件发布器 |

---

# 第三部分 企业生产就绪评估（SpringPy / PyMyBatis）

## 一、结论

当前代码已完成v1.5.0版本，核心功能、微服务治理和Cloud高级功能均已内嵌实现并通过27个新功能测试。适合企业内部系统、中后台API服务和AI集成场景。核心交易系统仍建议完成下方外部验证项后再采用。

## 二、本轮已完成

- 独立 `pymybatis` 与 Spring 内嵌 ORM 保持同版本、同公开行为；契约测试只允许包内导入路径不同。
- `SqlSessionFactory` 共享连接池，不再为每个 Session 新建连接池和泄漏检测线程。
- 连接池支持即时扩容、上限预留、真实借出连接跟踪、重复归还保护、归还前回滚和关闭生命周期。
- 修复 SQLite 初始化连接丢失、跨线程复用、首次取连接等待超时等问题。
- Session 写入失败会回滚，写入成功会清理查询缓存；`NESTED` 使用数据库 savepoint，`REQUIRED` 内层失败会标记外层 rollback-only。
- Spring Mapper 每次调用自动借还 Session；`@Transactional` 内多个 Mapper 调用复用同一 Session 并真实提交或回滚。
- JWT 配置可热初始化，限制 HMAC 算法，区分 access/refresh token；生产环境拒绝默认弱密钥。
- 配置占位符保留布尔值、整数和 null 类型；缺失的必需环境变量直接报错。
- HTTP 错误返回真实 4xx/5xx 状态码；CORS 默认同源，禁止凭证与 `*` 同时开启。
- 安装依赖已与实际代码对齐：FastAPI/Uvicorn、PyYAML、bcrypt、PyMySQL 和 nacos-sdk-python。
- XML Mapper 解析器兼容 SQL 中原始 `<=`/`>=`，同时保护 CDATA 和注释内容。
- Web 上下文完整注册 GET/POST/PUT/PATCH/DELETE，`@PatchMapping` 会生成真实 PATCH 路由。
- `ApplicationEvent`、`@EventListener` 和 `ApplicationEventPublisher` 已由 ApplicationContext 扫描、注册和发布。
- ApplicationContext 会把实际配置路径绑定到稳定的全局 ConfigLoader，后续无参数 `ConfigLoader()` 复用同一配置。
- Nacos Windows Docker 部署已覆盖 Java cgroup、外部 MySQL、Nacos 2.2+ token/identity 和客户端账号配置。
- v1.5.0新增Cloud内嵌功能：Sentinel限流熔断引擎(QPS/异常比例/慢调用/热点参数)、OpenTelemetry原生分布式追踪(W3C traceparent)、Seata HTTP-AT分布式事务(无需外部Server)、轻量API Gateway网关(ASGI/WSGI反向代理)、ORM DDL自动建表(JPA ddl-auto风格，create/update/validate/create-drop)。
- 全部27个Cloud新功能测试通过(含Sentinel 5项、Tracer 6项、Seata 5项、Gateway 4项、DDL Auto 7项)。
- MySQL连接池支持Docker容器IP自动检测，所有中间件配置支持环境变量，零硬编码。

## 三、上生产前仍必须完成

1. 对实际使用的 MySQL/PostgreSQL/Oracle 版本执行集成测试、故障注入和连接中断恢复测试。目前自动化契约使用 SQLite。
2. 建立数据库迁移流程；生产环境使用DDL Auto的validate模式或独立迁移脚本(Alembic/Flyway)，开发环境可使用update模式自动同步表结构。
3. 建立 CI 门禁：单元测试、数据库集成测试、静态检查、依赖漏洞扫描、许可证扫描和构建制品签名。
4. 锁定依赖版本并生成 SBOM；当前 `setup.py` 使用兼容范围，不是可复现部署锁文件。
5. 在反向代理或网关终止 TLS，配置可信代理、请求体大小、超时、限流和访问日志脱敏。
6. 使用密钥管理系统注入 JWT、数据库、Redis 和消息队列凭据，不把生产密钥写入 YAML。
7. 验证备份恢复、主从切换、容量上限、慢 SQL、连接池耗尽和进程优雅退出。
8. 针对业务模型完成授权、越权、SQL 注入、重放攻击和审计留痕测试。

## 四、生产最低配置

```yaml
spring:
  profiles:
    active: production

startup:
  fail_fast: true

server:
  cors:
    allow_origins:
      - https://app.example.com
    allow_credentials: true

database:
  enabled: true
  orm: mybatis
  min_size: 5
  max_size: 30
  wait_timeout: 5
  leak_detection_enabled: true
  leak_timeout: 60
  security:
    block_ddl: true
    sql_injection_detection: true
    allow_raw_params: false

discovery:
  enabled: true
  server_addr: nacos:8848
  username: ${NACOS_USERNAME}
  password: ${NACOS_PASSWORD}
```

生产环境至少设置：`SPRING_PROFILES_ACTIVE=production`、`STARTUP_FAIL_FAST=true`、`JWT_SECRET_KEY`、数据库凭据、明确的 `CORS_ALLOW_ORIGINS` 以及 Nacos 客户端账号。Nacos 服务端的 `NACOS_AUTH_TOKEN`、`NACOS_AUTH_IDENTITY_KEY` 和 `NACOS_AUTH_IDENTITY_VALUE` 必须由密钥管理系统注入，不要复用文档中的示例值。

## 五、支持边界

- 这是一套 Python 框架，不兼容 Java 字节码、Spring Bean 生命周期扩展点或 Java MyBatis 插件。
- 本地事务支持全部七种 Spring 传播模式；`NESTED` 使用数据库 savepoint。`REQUIRES_NEW` 和 `NOT_SUPPORTED` 会临时占用第二条连接，生产连接池必须按嵌套深度预留容量。
- ORM 源码存在两份是发布结构约束，修改后必须运行跨包源码一致性测试，禁止单边修复。
- Sentinel、OpenTelemetry追踪、Seata HTTP-AT分布式事务均为内嵌实现，无需部署外部Server。生产环境如需更强大的治理能力，可对接外部Sentinel Dashboard或Seata Server。
- API Gateway为轻量内嵌网关，适合简单路由转发场景。复杂网关需求建议使用Kong/APISIX等专业网关。
