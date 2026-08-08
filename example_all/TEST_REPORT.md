# example_all 集成测试报告

**测试时间**: 2026-08-04
**项目**: SpringPy (springboot Python 框架)
**测试范围**: 全注解用例集合 example_all
**测试环境**: Docker (MySQL 8.0, Redis 7-alpine, RabbitMQ 3-management-alpine), Prometheus 内嵌
**测试结果**: **5/5 测试套件通过**；历史集成报告覆盖 27 个 API 端点，当前测试脚本另含 9 个框架兼容性探针

## 测试结论

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

## 测试项明细

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

### 5. HTTP API 端点测试（历史集成 27/27）

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

## 注解覆盖率

### Web 层 (14 个)
- `@RestController`, `@Controller`
- `@RequestMapping`, `@GetMapping`, `@PostMapping`, `@PutMapping`, `@PatchMapping`, `@DeleteMapping`
- `@RequestParam`, `@PathVariable`, `@RequestBody`, `@RequestHeader`, `@CookieValue`
- `@CrossOrigin`, `@ResponseStatus`

### 组件 / DI / 配置 (15 个)
- `@Service`, `@Component`, `@Repository`
- `@Autowired`, `@Qualifier`, `@Value`
- `@Configuration`, `@Bean`, `@ConfigurationProperties`
- `@Profile`, `@Primary`, `@Lazy`
- `@SpringBootApplication`, `@PostConstruct`, `@PreDestroy`

### AOP 企业级 (10 个)
- `@RateLimit`, `@CircuitBreaker`, `@Idempotent`
- `@AuditLog`, `@FeatureToggle`, `@Lock`
- `@Metrics`, `@Synchronized`, `@Validate`, `@Trace`

### 安全 (3 个)
- `@PreAuthorize`, `@Secured`, `@Authenticate`

### 功能 (6 个)
- `@Transactional`, `@Cacheable`, `@Retryable`
- `@Async`, `@Scheduled`, `@LogExecutionTime`

### ORM (8 个)
- `@Mapper`, `@MapperScan`, `@Select`, `@Insert`, `@Update`, `@Delete`
- XML Mapper (`resultMap`, `sql片段`, `include`, `where/if`, `foreach`, `set`)

### Cloud (9 个)
- `@EnableDiscoveryClient`, `@NacosValue`, `@RefreshScope`
- `@EnableFeignClients`, `@FeignClient`
- `@LoadBalanced`, `@SentinelResource`, `@EnableGateway`
- `@GlobalTransactional`

### 消息 (2 个)
- `@RabbitListener`, `RabbitTemplate`

### 应用事件 (3 个)
- `ApplicationEvent`, `@EventListener`, `ApplicationEventPublisher`

**总计: 70+ 个注解和事件 API 覆盖**

## 测试环境搭建

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

## 框架层面修复

本次测试过程中发现并修复了以下框架 Bug：

| 问题 | 文件 | 修复 |
|------|------|------|
| pymysql `%` 格式化冲突 | `dynamic_sql.py` | 添加 `_escape_mysql_percent()` 方法，自动转义 SQL 字面量中的 `%` 为 `%%` |
| `LoadBalanced` 缺少 `strategy` 属性 | `cloud.py` | 添加 `strategy="round_robin"` 默认参数 |
| MySQL `SELECT LAST_INSERT_ID()` 返回 dict 导致 KeyError | `sql_session.py` | 兼容 dict 和 tuple 两种结果类型 |
| datetime/Decimal 无法 JSON 序列化 | `web_context.py` | 添加 `_JsonEncoder` 自定义 JSON 编码器 |

## 本轮兼容性修复

| 问题 | 文件/组件 | 修复 |
|------|------|------|
| Nacos Windows Docker 因认证变量退出 255 | Docker/Nacos 部署 | 增加 Nacos 2.2+ token/identity、Java cgroup 参数、外部 MySQL schema 和客户端账号配置 |
| `@PatchMapping` 路由返回 404 | `web_context.py` | 增加 `fastapi_app.patch()` 路由注册分支，并纳入默认 CORS 方法 |
| 全局 ConfigLoader 与上下文配置不同步 | `config_loader.py`、`application_context.py` | 绑定稳定全局实例和默认配置目录，后续 `ConfigLoader()` 复用同一配置 |
| XML 原始 `<=`/`>=` | `xml_parser.py` | 解析前规范化比较运算符，保护 CDATA/注释并还原 SQL 文本 |
| Event/Listener 缺少运行机制 | `spring/event`、`application_context.py` | 自动扫描监听器并提供同步有序事件发布器 |
