# Changelog

## [2.2.3] - 2026-08-13

### 新增

- ORM 实体字段自动推断：类型注解无需显式 `= Column(...)` 赋值，对齐 Java JPA 字段自动映射。
  - `name: str` → 自动创建 `Column(default=None)`
  - `name: str = ""` → 自动创建 `Column(default="")`
  - `name: int = 0` → 自动创建 `Column(default=0)`
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

- 新增独立 `spring.langgraph` 模块，锁定 `langgraph==1.2.9`，提供状态图、条件路由、人工中断、恢复、流式调用和注解式工作流。
- 新增官方 SQLite checkpointer 安全工厂；关闭 pickle fallback、限制反序列化类型，并验证连接关闭后重新打开仍能恢复流程。
- 新增 `spring.mcp` 客户端和服务端，基于官方 MCP Python SDK，支持 Tool、Resource、Prompt 及注解调用。
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
