# SpringPy / PyMyBatis 企业生产就绪评估

## 结论

当前代码已完成v1.5.0版本，核心功能、微服务治理和Cloud高级功能均已内嵌实现并通过27个新功能测试。适合企业内部系统、中后台API服务和AI集成场景。核心交易系统仍建议完成下方外部验证项后再采用。

## 本轮已完成

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

## 上生产前仍必须完成

1. 对实际使用的 MySQL/PostgreSQL/Oracle 版本执行集成测试、故障注入和连接中断恢复测试。目前自动化契约使用 SQLite。
2. 建立数据库迁移流程；生产环境使用DDL Auto的validate模式或独立迁移脚本(Alembic/Flyway)，开发环境可使用update模式自动同步表结构。
3. 建立 CI 门禁：单元测试、数据库集成测试、静态检查、依赖漏洞扫描、许可证扫描和构建制品签名。
4. 锁定依赖版本并生成 SBOM；当前 `setup.py` 使用兼容范围，不是可复现部署锁文件。
5. 在反向代理或网关终止 TLS，配置可信代理、请求体大小、超时、限流和访问日志脱敏。
6. 使用密钥管理系统注入 JWT、数据库、Redis 和消息队列凭据，不把生产密钥写入 YAML。
7. 验证备份恢复、主从切换、容量上限、慢 SQL、连接池耗尽和进程优雅退出。
8. 针对业务模型完成授权、越权、SQL 注入、重放攻击和审计留痕测试。

## 生产最低配置

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

## 支持边界

- 这是一套 Python 框架，不兼容 Java 字节码、Spring Bean 生命周期扩展点或 Java MyBatis 插件。
- 本地事务支持全部七种 Spring 传播模式；`NESTED` 使用数据库 savepoint。`REQUIRES_NEW` 和 `NOT_SUPPORTED` 会临时占用第二条连接，生产连接池必须按嵌套深度预留容量。
- ORM 源码存在两份是发布结构约束，修改后必须运行跨包源码一致性测试，禁止单边修复。
- Sentinel、OpenTelemetry追踪、Seata HTTP-AT分布式事务均为内嵌实现，无需部署外部Server。生产环境如需更强大的治理能力，可对接外部Sentinel Dashboard或Seata Server。
- API Gateway为轻量内嵌网关，适合简单路由转发场景。复杂网关需求建议使用Kong/APISIX等专业网关。
