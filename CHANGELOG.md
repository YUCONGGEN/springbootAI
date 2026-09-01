# Changelog

## [2.3.11] - 2026-09-01

- 修复 PyMyBatis 访问控制仅覆盖查询、行级条件直接拼接及 SQL 尾部条件位置错误，写操作和字段权限现在失败关闭，动态租户值必须使用绑定参数。
- 修复事务提交前监听器异常被吞掉及 `REQUIRES_NEW`/`NOT_SUPPORTED` 同步上下文错误，提交否决会触发回滚并恢复外层上下文。
- 修复 Spring Cloud Bus RabbitMQ API 调用错误和缺失消费者，增加 Broker 确认、广播消费者、去重、消息大小限制及明确的失败状态。
- 加固 MCP/AI 工具边界：限制 HTTP 响应、队列、集合和 Schema 深度，拒绝压缩炸弹及高风险正则表达式。
- 修复 Prometheus Summary 创建失败、Tracer 已结束 Span 无界增长以及 Actuator/启动日志暴露原始异常的问题。
- 修复 CI 在 AI 测试切片后提前执行总覆盖率门槛的问题，覆盖率阈值现在只在全部测试切片完成后统一校验。
- 修复 LangChain 完整演示未声明文档加载根目录的问题，并为临时文件自动清理及 Windows 重定向控制台增加 UTF-8 输出兼容。

## [2.3.10] - 2026-08-29

- 修复 AI 代理上下游消息被 SQL 注入检测误报：`#{...}` 绑定值始终按数据处理，不再扫描消息内容；`${...}` 原始替换仍默认拒绝，只有配置允许且值完整匹配严格白名单时才能使用。
- 加固企业级 AOP 注解：完善限流、熔断、幂等和分布式锁的共享后端、失败关闭与异步语义，并补充企业安全回归测试。
- 加固 OAuth2、CSRF 与 Data REST：完善 JWKS/issuer/audience/algorithm 校验、签名 CSRF Token、默认鉴权以及读写字段白名单。
- 完善受限 Seata AT 补偿模式：限制可解析 SQL 子集，使用绑定参数采集快照，原子写入 undo_log，增加冲突检测、自动安装代理和恢复线程生命周期管理；该模式仍不提供官方 TC 全局锁或跨服务强一致性。
- 审计并修正文档：统一当前版本号，修复 Starter 损坏的依赖示例、无效 Spring 官方链接、不可运行的 ChatClient 示例、过期改进记录、配置元数据偏差、Sphinx 包名及乱码注释。
- README 开头增加对阿里、华为、讯飞、心之声、字节、OpenAI、DeepSeek 等公司支持的致谢，不声明其使用或官方背书。

## [2.3.9] - 2026-08-28

- 加固 OpenAI 兼容接口与 Ollama 的同步/异步流式协议：校验终止帧、错误信封和畸形响应，限制事件与响应大小，并完善超时、有限重试、重定向拒绝及 SDK 重试边界。
- 修复 AI 异步流阻塞事件循环、请求参数覆盖受保护字段、输出 Token 上限绕过、工具调用闭环和多租户 Memory/RAG 隔离等问题。
- 加固 Feign、Gateway、Config Center、Admin 与 Discovery：正确释放响应、执行路由谓词和过滤器、过滤逐跳头、传播请求 ID，并增加路径、响应大小、故障回退与生命周期保护。
- 新增统一日志脱敏和日志注入防护，覆盖异常链、Bearer/Basic/Cookie、云事件、Nacos、Seata 与 SkyWalking，避免敏感负载进入日志或健康响应。
- 修复原子脚手架写入、TextReader 文件边界、DevTools 停止/重启语义、SkyWalking 显式初始化和 Banner 版本读取错误。
- 新增企业加固回归测试；完整测试结果为 3170 passed、11 skipped、0 failed，Bandit 中高危扫描为 0。

## [2.3.8] - 2026-08-24

- 修复配置加载的原子性与数据库 URL 优先级：请求监控不再误落到根目录 `test.db`，SQLite 运行目录会自动创建，显式 URL/驱动/数据库名称按统一优先级生效。
- 新增可选配置监控（默认关闭），兼容 YAML、环境变量和 Nacos，提供脱敏历史、变更键、来源、耗时与成功/失败信息，并接入 Actuator/Admin 面板。
- 修复 Nacos 热更新失败后不重试、客户端状态污染和 Web/Actuator/请求监控配置不刷新的问题；热更新现在安全重绑运行时配置。
- 修复默认 profile 占位符未参与 profile 文件选择的问题，支持自动加载 `application-default.yml`；同时限制 Nacos 请求超时（最多 120 秒）和热刷新间隔（最多 1 小时）。
- 为 Nacos 服务发现与 RabbitMQ 增加有限连接/请求超时和重试上限，未配置或服务不可用时不会无限阻塞启动；补充 MCP 本机代理兼容、Redis 单次探测和 AI Cache 并发/容量保护。
- 加固 Spring Cloud Config 可选客户端：容忍空/错误配置层级，限制 timeout、重试次数与退避间隔，避免配置中心异常反向拖垮启动。
- 补充条件装配注解示例、可选组件超时回归测试，并同步配置元数据与模块文档。

## [2.3.7] - 2026-08-20

### PyPI 项目说明修正

- PyPI 恢复使用完整的 `README.md`，与 GitHub 项目主页保持相同的内容、功能总览图和状态徽章。
- 撤销 `2.3.6` 中单独维护精简版 PyPI README 的方案，避免两处项目说明内容不一致。
- 发布版本升级到 `2.3.7`，同步框架主包、扩展模块、PyMyBatis 内嵌版本、README 版本矩阵和打包元数据。

## [2.3.6] - 2026-08-20

### PyPI 展示修复

- 新增不含外链图片的 `README_PYPI.md`，作为 PyPI 项目说明，避免外链图片被转换到不可访问的 PyPI Camo 代理后显示为破损图片。
- GitHub 继续使用包含功能总览图和状态徽章的 `README.md`，两端展示互不影响。
- 发布版本升级到 `2.3.6`，同步框架主包、扩展模块、PyMyBatis 内嵌版本、README 版本矩阵和打包元数据。

## [2.3.5] - 2026-08-20

### 文档与发布

- 发布版本升级到 `2.3.5`，同步框架主包、扩展模块、PyMyBatis 内嵌版本、README 版本矩阵和打包元数据。
- README 首页新增 SpringBootAI 在线考试认证与证书说明，提供认证入口、适用场景、备考流程和重点知识范围。
- 认证平台入口：[http://www.yucg.cn:8230](http://www.yucg.cn:8230)。

## [2.3.4] - 2026-08-19

### 新增与完善

- 新增声明式 AI 注解：`@Prompt`、`@RAG`、`@StructuredOutput`、`@Agent`、`@Embedding`、`@VectorStore`、`@AiRetry`、`@AiCache`、`@TokenUsage`、`@ContentModeration`；复用 ChatClient、RAG、Agent、向量库和可观测性组件，并支持同步、异步与 Pydantic v1/v2。
- 新增 AI 注解中文用例、实时功能目录和模块文档；未配置 AI Bean 或可选依赖时不影响普通应用启动。
- 完善 Actuator Admin、Nacos 动态刷新、请求监控与文件上传能力，并补充对应文档与回归测试。
- 修复 PyMyBatis 参数检测将 Python 源码中的普通 `#` 注释误判为 SQL 注入的问题；真实引号/分号后的 SQL 注释截断攻击仍会被拦截。

### 兼容性

- AI 自动配置同时支持 `springbootai.ai` 与 Spring 风格的 `spring.ai` 配置前缀，避免已有配置中的 API Key 被遗漏。

## [2.3.3] - 2026-08-18

### 测试补充与文档完善

- 补充单元测试覆盖核心模块：新增 `test_core.py`（22个，覆盖 typing_utils/graceful_shutdown）、`test_retry.py`（29个，覆盖 Backoff/Retryable/@retry/recovery）、`test_scheduling.py`（18个，覆盖 cron解析/调度器）、`test_tracing.py`（17个，覆盖 LocalSpan/SkyWalkingTracer 降级）共86个测试用例
- 文档中文化：将 `doc/LOMBOK_MODULE.md` 等英文文档完整翻译为中文
- 安全加固：生产环境配置校验强化；取消 GitHub Actions 定时测试触发
- 完整测试套件 2964+ 个测试通过

## [2.3.2] - 2026-08-16

### 文档与打包修正

- 统一框架、文档和构建元数据版本；修正测试目录、可选依赖和生产 Profile 示例。

## [2.3.0] - 2026-08-15

### 新增

- **企业级注解驱动**：新增 10 个注解，将 16 项企业级功能改造为注解驱动模式。标记在 `@SpringBootApplication` 主类上即可启用，注解参数优先于配置文件。
  - `@EnableOAuth2` — 启用 OAuth2 资源服务器（支持 HS256/RS256、issuer/audience/scope 校验）
  - `@EnableCsrf` — 启用 CSRF 防护（Double Submit Cookie 模式）
  - `@EnableDevTools` — 启用开发环境热重载（文件变更自动重启）
  - `@EnableConfigServer` — 启用 Spring Cloud Config 配置中心客户端
  - `@EnableBus` — 启用 Spring Cloud Bus 事件总线
  - `@EnableBatchProcessing` — 启用 Spring Batch 批处理
  - `@EnableDataRest` — 启用 Spring Data REST（自动暴露 Repository 为 CRUD API）
  - `@BatchJob` / `@BatchStep` — 标记批处理作业和步骤
  - `@RepositoryRestResource` — 标记 Repository 为 REST 资源
- **OAuth2 资源服务器**：新增 `springbootai/security/oauth2.py`，支持 JWT Access Token 验证，HS256 对称密钥和 RS256 公钥（JWKS）两种算法。
- **CSRF 防护**：新增 `springbootai/web/csrf.py`，实现 Double Submit Cookie 模式中间件。
- **Kafka 支持**：新增 `springbootai/messaging/kafka.py`，提供 `KafkaClient`（生产者+消费者管理）和 `@KafkaListener`/`KafkaTemplate` 注解。
- **DevTools 热重载**：新增 `springbootai/devtools.py`，提供 `FileWatcher`（轮询文件变更）和 `RestartTrigger`（静默期防抖）。
- **数据库迁移完善**：新增 Undo 回滚迁移（U{version}__{desc}.sql）、迁移锁（MySQL/PostgreSQL/SQLite）、变量替换（${var}）、validate 校验方法。
- **Actuator /heapdump 端点**：返回 tracemalloc 内存分配快照 + GC 统计（JSON 格式），对齐 Spring Boot /actuator/heapdump。
- **配置元数据**：新增 `springbootai/config/spring-configuration-metadata.json`，IDE 可读取提供配置自动补全。
- **项目脚手架**：新增 `springbootai/cli/scaffold.py`，支持 `springbootai init` 命令创建新项目。
- **Spring CLI**：新增 `springbootai/cli/main.py`，提供 `springbootai` 统一命令入口（version/info/list/init/run/docs）。
- **Starter 机制**：pyproject.toml 新增 `web`/`cloud`/`all` 组合 Starter extras。
- **Spring Cloud Config**：新增 `springbootai/cloud/config_center.py`，支持 HTTP 和本地文件后端。
- **Spring Cloud Bus**：新增 `springbootai/cloud/bus.py`，支持进程内和 MQ 后端事件总线。
- **Spring Batch**：新增 `springbootai/batch/`，支持 Job/Step/Reader/Processor/Writer 组件。
- **Spring Data REST**：新增 `springbootai/data/rest.py`，自动生成 Repository CRUD REST 端点。
- **Spring HATEOAS**：新增 `springbootai/web/hateoas.py`，包含 Link/EntityModel/CollectionModel/PagedModel。
- **Sphinx API 文档**：新增 `docs/conf.py` 和 `docs/index.rst`。

### 测试

- 新增 7 个测试文件，共 198 个测试用例：
  - `test_kafka.py`（75）、`test_migration.py`（44）、`test_oauth2.py`（21）、`test_csrf.py`（19）、`test_devtools.py`（16）、`test_starter.py`（13）、`test_metadata.py`（10）
- 新增 `test_new_annotations.py`（37 个注解测试）
- 完整测试套件 **2821 passed, 11 skipped, 0 failed**

### 文档

- 新增 `doc/ENTERPRISE_ANNOTATIONS.md` — 10 个企业级注解完整教程
- 新增 `doc/MIGRATION_MODULE.md` — 数据库迁移模块文档（10 章节）
- 新增 `doc/STARTER_MODULE.md` — Starter 机制文档（8 章节）
- 新增 `doc/CLI_MODULE.md` — CLI 和脚手架文档（10 章节）
- `doc/MESSAGING_MODULE.md` 追加 Kafka 章节
- `doc/WEB_MODULE.md` 追加 HATEOAS 章节
- `doc/CONFIG_BINDING_MODULE.md` 追加配置元数据章节
- 35 个文件版本号从 2.2.6 更新到 2.3.0

## [2.2.6] - 2026-08-15

### 新增

- **Seata AT 数据源代理**：新增 `springbootai/cloud/seata_at_proxy.py`（500 行），在 ORM 拦截器层自动记录 SQL 的 before/after image，生成 undo_log，全局事务回滚时自动反向恢复数据。支持 MySQL(`%s`) 和 SQLite(`?`) 占位符自动适配。Seata 模式从三模式（local/http/distributed）扩展为四模式（新增 `at`）。
- **AT 代理测试**：新增 `tests/test_seata_at_proxy.py`（18 项全通过），覆盖 SQL 解析、undo_log CRUD、undo 反向恢复（INSERT→DELETE / UPDATE→UPDATE before / DELETE→INSERT before）、AT 拦截器记录、提交删除 undo_log。

### 重构

- **目录整合**：`example_all`、`example_langchain`、`example_langgraph`、`example_mcp`、`test_cloud_app` 五个散落目录合并到 `examples/` 下；`tests_integration`、`tests_performance`、`tests_runtime` 合并到 `tests/integration/`、`tests/performance/`、`tests/runtime/`。`pyproject.toml` 的 `pythonpath` 增加 `examples`，5 个入口脚本修复 `sys.path`。
- **文档整理**：`REPOSITORY_MODULE.md` 合并到 `ORM_MODULE.md`（减少文档碎片），更新 README 导航表和 3 处引用。
- **路径引用同步**：CI 4 个 workflow、11 个文档、Dockerfile、benchmark_app.py 中的 example/tests 路径全部更新。

### 文档

- `README.md` Seata 边界说明从"⚠️ 有边界"改为"✅ 可用"（3 处）。
- `doc/CLOUD_MODULE.md` 新增 AT 模式使用指南（工作流程图 + 代码示例 + 限制说明）。
- `doc/ORM_MODULE.md` 新增"Repository 分页查询"章节（原 REPOSITORY_MODULE.md 内容）。
- 25 个文件版本号从 2.2.5 更新到 2.2.6。

## [2.2.5] - 2026-08-14

### 新增

- **Spring Boot Admin 风格可视化面板**：访问 `/actuator/admin` 即可在浏览器查看整合后的 HTML 仪表盘，包含健康状态、系统信息、内存 & CPU、线程概览、日志级别管理（点击切换）、Prometheus 指标（原始数据 + 摘要表格）、Bean 列表七大区块。每 30 秒自动刷新，无需独立部署 Admin Server。
- **Prometheus 指标暴露端点** `/actuator/prometheus`：以 Prometheus 文本格式（`text/plain; version=0.0.4`）暴露应用指标，供 Prometheus Server 抓取。支持多 worker 部署（`PROMETHEUS_MULTIPROC_DIR`），未安装 `prometheus_client` 时返回 503。
- **进程系统指标端点** `/actuator/sysmetrics`：通过 `psutil` 采集进程级 RSS、虚拟内存、CPU 使用率、线程数、文件描述符数。
- **ORM 分页查询注解 `@SelectPage`**：自动提取 `page_num`/`page_size` 参数并返回 `{total, page_num, page_size, data}` 结构，支持 `pageNum`/`page`/`pageSize`/`size` 等参数名变体，可自定义 COUNT 语句。

### 文档

- `doc/ACTUATOR_MODULE.md` 新增第四章（Spring Boot Admin 可视化面板）、第五章（Prometheus + Grafana 工业级监控，含三步接入流程与多 worker 注意事项）、第六章（自定义业务指标）。
- `doc/ORM_MODULE.md` 第五章新增"方法 1：@SelectPage 注解（推荐）"小节。
- `README.md` 4.8 健康检查表新增 `/actuator/admin`、`/actuator/prometheus`、`/actuator/sysmetrics` 三个端点。

### 测试

- 新增 `tests/test_actuator_prometheus_admin.py`（9 项测试全部通过）：覆盖 Prometheus 端点格式、Admin 面板 HTML、sysmetrics 端点、端点目录。
- 新增 `tests/test_select_page.py`：覆盖 `@SelectPage` 分页注解。

## [2.2.4] - 2026-08-13

### 完善

- 自动推断逻辑调整：无赋值的字段仅创建 `Column()` 记录类型，不设默认值；只有显式赋值才作为 `default`。
- `_parse_entity` 跳过以 `_` 开头的私有字段，不生成 DDL 列。
- 新增 `example_all/models/EntityModels.py` 实体示例和 `test_06_entity_jpa_style` 测试（4 项全通过）。

## [2.2.3] - 2026-08-13

### 新增

- ORM 实体字段自动推断：类型注解无需显式 `= Column(...)` 赋值，对齐 Java JPA 字段自动映射。
  -
ame: str` → 自动创建 `Column()`（无默认值，仅记录类型）
  -
ame: str = ""` → 自动创建 `Column(default="")`（赋值即为默认值）
  -
ame: int = 0` → 自动创建 `Column(default=0)`
  - 已有 `Column()`/`Id()`/`CreateTime()` 等描述符的字段保留不覆盖
  - 以 `_` 开头的私有字段自动跳过

  ```python
  @Entity
  @Table(name="sys_user", comment="用户表")
  class User:
      id: int = Id()
      username: str = ""               # 自动推断 Column(default="")
      display_name: str = "系统管理员"  # 自动推断 Column(default="系统管理员")
      enabled: bool = True             # 自动推断 Column(default=True)
      _cache: dict = {}                # 私有字段，跳过
  ```

- `_parse_entity` 跳过以 `_` 开头的私有字段，不生成 DDL 列。

## [2.2.2] - 2026-08-13

### 新增

- ORM `@Entity` / `@Table` 注解对齐 Java JPA 分离风格，支持三种写法（均向后兼容）：

  | 写法 | 说明 | 对齐 Java |
  |------|------|-----------|
  | `@Entity` + `@Table(...)` | 分离风格（推荐） | `@Entity` + `@Table` |
  | `@Entity` 无括号 | 表名自动推导为 snake_case | `@Entity`（无 `@Table`） |
  | `@Entity("name", ...)` | 一体化风格（完全兼容） | 原有写法不变 |

- `Table` 类新增 `__call__`，可直接作为类装饰器使用（`@Table(name=..., indexes=[...], comment=...)`）。
- `@Entity` 支持无括号形式（`@Entity`），检测到已有 `@Table` 时不覆盖表元数据。
- 提取 `_auto_generate_init` 辅助函数，消除 `Entity` 与 `Table.__call__` 间的重复代码。

## [2.2.1] - 2026-08-13

### 修复

- 修复 ORM `@Entity`/`@entity` 实体解析、DDL 字段推断和 MyBatis 连接池初始化。
- 加强 SQL 注入检测、敏感数据脱敏、Mapper XML 解析和 Web 根路由映射。
- 增加对应回归测试，确保实体描述符、容器参数和静态资源路由行为稳定。

本项目从 `2.1.0` 开始按 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 记录面向使用者的变化，并使用语义化版本号。

## [2.2.0] - 2026-08-12

### 新增

- 新增声明式 AOP：`@Aspect`、`@Pointcut`、`@Before`、`@After`、`@Around`、`@AfterReturning`、`@AfterThrowing`。支持受管 Bean 自动代理、同步/异步通知、`JoinPoint` / `ProceedingJoinPoint`，以及 `execution`、`within`、`bean`、`@annotation` 和切点引用。
- 新增 `@PostAuthorize`，方法成功返回后可使用 `returnObject` / `#returnObject`、当前认证信息、角色和权限进行授权。
- 新增 `@Recover`，在 `@Retryable` 重试耗尽后按异常类型选择最具体的恢复方法；兼容原有 `recover="method"` 写法和独立重试装饰器入口。
- 新增面向新手的 [`AOP_SECURITY_RETRY.md`](doc/AOP_SECURITY_RETRY.md)，包含完整示例、执行顺序、表达式速查、安全边界和常见错误。

### 安全与兼容性

- 安全表达式改为白名单 AST 求值，不执行任意 Python 代码；不支持的语法按授权失败处理。
- 声明式切面作为受管 Bean 的最外层扩展，可观察内置 AOP、重试和安全包装后的最终结果；手工实例化对象不会自动代理。
- 旧式命名恢复方法继续保持原签名；显式命名的方法同时标记 `@Recover` 时使用包含最终异常的新签名。

### 测试

- 新增 26 个声明式 AOP、后置鉴权和重试恢复专项用例，并将 9 个新公共注解加入 172 项注解契约检查。
- Conda Python 3.10.20 完整回归：2372 passed、4 skipped、172 subtests passed，覆盖率 68.63%。
- Docker 真实集成测试：MySQL、Redis、RabbitMQ、Nacos、Seata TCC 共 5 项通过；Redis 和 Seata bridge 停机失败关闭 2 项通过。

## [2.1.1] - 2026-08-12

### 修复

- 锁定兼容的 `langchain-core==1.5.4` 与 `langchain-openai==1.4.2`，避免可选 AI 依赖解析冲突。
- CI 中间件恢复命令改用 `docker compose up -d --wait <service>`，兼容不支持 `start --wait` 的 Compose 版本。

## [2.1.0] - 2026-08-12

### 新增

- 新增独立 `springbootai.langgraph` 模块，锁定 `langgraph==1.2.9`，提供状态图、条件路由、人工中断、恢复、流式调用和注解式工作流。
- 新增官方 SQLite checkpointer 安全工厂；关闭 pickle fallback、限制反序列化类型，并验证连接关闭后重新打开仍能恢复流程。
- 新增 `springbootai.mcp` 客户端和服务端，基于官方 MCP Python SDK，支持 Tool、Resource、Prompt 及注解调用。
- 新增 LangChain 和 LangGraph 注解 API；注解只负责声明，执行继续委托官方框架。
- 压测新增 AI、LangChain、LangGraph、MCP workload，并纳入 9 小时 mixed 稳定性脚本。
- CI 新增真实 MySQL、Redis、RabbitMQ、Nacos、Seata TCC 集成测试和依赖停机测试。

### 修复

- 同步 Controller 由有界线程池执行，避免阻塞 ASGI 事件循环。
- Gateway 支持正确的 ASGI 挂载和异步请求体/上游转发。
- Seata distributed 模式对接真实 Seata Server 与 Java bridge，并通过 TCC prepare/commit/rollback 合同测试。
- 健康检查会把 Nacos、RabbitMQ 和 Seata 状态纳入总体状态和 readiness。
- 修复动态 SQL/DDL 的不安全表达式求值、XML 外部实体、Redis pickle 反序列化、动态排序标识符和 callback SSRF 风险。
- 补齐 `requests`、`defusedxml`、LangGraph SQLite checkpoint 和 MCP 的发布依赖。

### 安全与发布

- Bandit 所有中高危发现和四份 `pip-audit` 结果成为强制门禁，不再使用 `|| true` 放行。
- 发布工作流要求 git tag 与 `pyproject.toml` 版本完全一致，并在上传前执行全量测试、覆盖率、安全审计、wheel 内容和干净安装检查。
- `langgraph-checkpoint-sqlite` 使用已修复公开漏洞的 `3.1.1`，并启用严格反序列化策略。

### 兼容性提醒

- Redis ORM 缓存不再接受 `pickle` 序列化。旧 pickle 缓存应在升级前清理，并改用 JSON。
- Seata `distributed` 提供真实 TC + TCC 协调，不是 Python AT 数据源代理，不会自动生成 `undo_log`。
- 内存 LangGraph checkpointer 仅用于测试；多 worker 生产环境必须注入共享存储后端。

[2.2.0]: https://github.com/YUCONGGEN/springbootAI/compare/v2.1.1...v2.2.0
[2.1.1]: https://github.com/YUCONGGEN/springbootAI/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/YUCONGGEN/springbootAI/compare/v2.0.2...v2.1.0
