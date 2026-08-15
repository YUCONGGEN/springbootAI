# SpringBootAI Bean 生命周期与增强注解指南

> 框架版本：SpringBootAI 2.3.0

---

## 是什么？

本文覆盖 4 组共 11 个注解：Bean 生命周期回调、日志与监控、Bean 配置控制、业务增强。这些都是框架核心注解中"不属于其他模块文档"的补充注解。

### 注解速查表

| 注解 | 一句话作用 | 写在哪 |
|------|----------|--------|
| `@PostConstruct` | Bean 初始化后自动执行 | 方法 |
| `@PreDestroy` | Bean 销毁前自动执行 | 方法 |
| `@Slf4j` | 给类注入 logger | 类 |
| `@LogExecutionTime` | 自动记录方法执行耗时 | 方法 |
| `@Metrics` | 采集方法指标（调用次数/耗时） | 方法 |
| `@Primary` | 同类型多个 Bean 时优先选这个 | 类 |
| `@Scope` | 设置 Bean 作用域（singleton/prototype） | 类 |
| `@Profile` | 按环境名决定是否注册 Bean | 类 |
| `@Lazy` | 延迟初始化（首次使用时才创建） | 类 |
| `@AuditLog` | 自动记录审计日志 | 方法 |
| `@FeatureToggle` | 按配置开关功能 | 方法 |

### 决策指引

| 我想做的事 | 看哪节 |
|-----------|--------|
| Bean 创建后/销毁前执行逻辑 | [1. 生命周期回调](#1-生命周期回调) |
| 自动记录日志和执行耗时 | [2. 日志与监控](#2-日志与监控) |
| 控制多个同类 Bean 的选择优先级 | [3. Bean 配置](#3-bean-配置) |
| 记录谁在什么时候做了什么操作 | [4. 业务增强](#4-业务增强) |

---

## 1. 生命周期回调

### 是什么？

**`@PostConstruct` = Bean 出生后的第一件事。** 就像新生儿体检——Bean 创建完毕、依赖注入完成后，框架自动调用这个方法。

**`@PreDestroy` = Bean 销毁前的最后一件事。** 就像关店前盘点——Bean 被销毁前，框架自动调用这个方法清理资源。

### 怎么用？

```python
from spring.annotations import Service, PostConstruct, PreDestroy


@Service
class DatabaseService:
    """模拟数据库连接管理"""

    @PostConstruct
    def init(self):
        """Bean 创建后自动执行：建立连接池"""
        print("初始化数据库连接池...")
        self.pool = create_connection_pool()

    @PreDestroy
    def cleanup(self):
        """Bean 销毁前自动执行：关闭连接池"""
        print("关闭数据库连接池...")
        self.pool.close()
```

### 执行时机

| 注解 | 何时执行 | 典型用途 |
|------|---------|---------|
| `@PostConstruct` | Bean 实例化 + 依赖注入完成后 | 初始化连接池、加载配置、预热缓存 |
| `@PreDestroy` | 容器关闭、Bean 被移除前 | 关闭连接、释放资源、保存状态 |

### 新手常见错误

| 错误做法 | 正确做法 |
|---------|---------|
| 在 `@PostConstruct` 里访问尚未注入的依赖 | `@PostConstruct` 在注入完成后执行，依赖已可用 |
| 在 `@PostConstruct` 里做耗时操作阻塞启动 | 耗时初始化用 `@Async` 或后台线程 |
| `@PreDestroy` 方法抛异常导致关闭卡住 | 清理逻辑要捕获异常，保证不阻塞关闭 |

---

## 2. 日志与监控

### 是什么？

**`@Slf4j` = 自动给类加一个 logger。** 不用每次手写 `logger = logging.getLogger(__name__)`。

**`@LogExecutionTime` = 自动记录方法耗时。** 就像秒表——方法执行完自动打印"耗时 0.35 秒"。

**`@Metrics` = 采集方法运行指标。** 记录调用次数、执行耗时，配合 Actuator/Prometheus 暴露。

### 怎么用？

```python
from spring.annotations import Service, Slf4j, LogExecutionTime, Metrics


@Slf4j
@Service
class OrderService:

    @LogExecutionTime(log_level="info")  # 执行完自动打印耗时
    def calculate_price(self, order_id: str):
        self.logger.info(f"计算订单 {order_id} 价格")  # self.logger 自动可用
        # 业务逻辑...
        return {"total": 99.9}
        # 日志输出: Execution time for calculate_price: 0.0234s

    @Metrics(name="order.create", tags=["api", "order"])  # 采集指标
    def create_order(self, user_id: str):
        # 框架记录：调用次数 +1、耗时
        return {"order_id": "123"}
```

### 参数说明

**@Slf4j：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `logger_name` | `str` | None | 自定义 logger 名（默认用模块名） |

**@LogExecutionTime：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `log_level` | `str` | "info" | 日志级别（debug/info/warning/error） |

**@Metrics：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | None | 指标名 |
| `tags` | `List[str]` | [] | 标签列表 |

### 新手常见错误

| 错误做法 | 正确做法 |
|---------|---------|
| `@Slf4j` 后直接用 `print()` 输出 | 用 `self.logger.info()` 走框架日志 |
| 给每个方法都加 `@LogExecutionTime` | 只给关键方法加，避免日志爆炸 |

---

## 3. Bean 配置

### 是什么？

这 4 个注解控制 Bean 在容器中的行为：谁优先、什么作用域、什么环境启用、何时创建。

### 注解速查表

| 注解 | 一句话解释 | 使用场景 |
|------|-----------|---------|
| `@Primary` | 同类型多个 Bean 时，优先选这个 | 有默认实现 + 可选实现 |
| `@Scope` | singleton（单例）/ prototype（多例） | 无状态用 singleton，有状态用 prototype |
| `@Profile` | 按环境名（dev/test/prod）决定是否注册 | 不同环境用不同实现 |
| `@Lazy` | 延迟到首次使用时才创建 | 启动慢的 Bean 按需加载 |

### 怎么用？

**@Primary：多个同类 Bean 选一个默认的**

```python
from spring.annotations import Service, Primary, Autowired


@Primary  # 有多个 DataSource 时，优先选这个
@Service("primaryDataSource")
class PrimaryDataSource:
    pass


@Service("secondaryDataSource")
class SecondaryDataSource:
    pass


@Service
class UserService:
    @Autowired
    def __init__(self, data_source: PrimaryDataSource):  # 注入 @Primary 的
        self.ds = data_source
```

**@Scope：控制单例还是多例**

```python
from spring.annotations import Component, Scope


@Scope("singleton")  # 全局唯一实例（默认）
@Component
class SingletonService:
    pass


@Scope("prototype")  # 每次注入都创建新实例
@Component
class PrototypeService:
    pass
```

**@Profile：按环境切换实现**

```python
from spring.annotations import Service, Profile


@Profile("dev")  # 只有 SPRING_PROFILES_ACTIVE=dev 时才注册
@Service
class DevEmailService:
    def send(self, to): print(f"[DEV] 模拟发送给 {to}")


@Profile("prod")  # 只有 SPRING_PROFILES_ACTIVE=prod 时才注册
@Service
class ProdEmailService:
    def send(self, to): print(f"[PROD] 真实发送给 {to}")
```

**@Lazy：延迟初始化**

```python
from spring.annotations import Service, Lazy


@Lazy  # 不在启动时创建，首次被注入时才创建
@Service
class HeavyService:
    def __init__(self):
        print("HeavyService 初始化（可能很慢）")  # 首次使用时才打印
```

### 参数说明

**@Scope：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `value` | `str` | "singleton" | 只支持 `singleton` 或 `prototype` |

**@Profile：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `value` | `str` / `List[str]` | 环境名（如 `"dev"`, `["dev", "test"]`） |

**@Lazy：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `value` | `bool` | True | True=延迟，False=立即（等同不加） |

### 新手常见错误

| 错误做法 | 正确做法 |
|---------|---------|
| `@Scope("request")` | 框架只支持 `singleton` 和 `prototype` |
| `@Profile("DEV")` 大写 | 配置值是字符串，要和 `SPRING_PROFILES_ACTIVE` 的值匹配 |
| `@Lazy` 加在已经被启动流程依赖的 Bean 上 | 如果启动时就被注入，`@Lazy` 无效 |
| 以为 `@Primary` 能覆盖 `@Qualifier` | `@Qualifier` 是显式指定，优先级高于 `@Primary` |

---

## 4. 业务增强

### 是什么？

**`@AuditLog` = 自动记录审计日志。** 谁在什么时候做了什么操作——框架自动记录，不用手动写日志。

**`@FeatureToggle` = 按配置开关功能。** 就像电灯开关——配置开了功能才执行，关了就跳过或返回默认值。

### 怎么用？

**@AuditLog：审计日志**

```python
from spring.annotations import Service, AuditLog


@Service
class UserService:

    @AuditLog(action="删除用户", target="user", level="WARNING")
    def delete_user(self, user_id: int):
        return {"deleted": user_id}
        # 框架自动记录：[AUDIT] 用户 admin 执行了"删除用户"，目标 user，时间 2026-08-15
```

**@FeatureToggle：功能开关**

```python
from spring.annotations import Service, FeatureToggle


@Service
class SearchService:

    @FeatureToggle(name="features.ai_search", default=False)
    def search(self, query: str):
        # 只有 features.ai_search=true 时才执行
        return {"results": ai_search(query)}
        # 配置为 false 时返回 None（功能关闭）
```

`application.yml` 配置：

```yaml
features:
  ai_search: true  # 开启 AI 搜索功能
```

### 参数说明

**@AuditLog：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `action` | `str` | "" | 操作描述（如"删除用户"） |
| `target` | `str` | "" | 操作目标（如"user"） |
| `detail` | `str` | "" | 详细信息 |
| `level` | `str` | "INFO" | 日志级别（INFO/WARNING/ERROR） |

**@FeatureToggle：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | (必填) | 配置项名（如"features.ai_search"） |
| `default` | `bool` | False | 配置不存在时的默认值 |

### 新手常见错误

| 错误做法 | 正确做法 |
|---------|---------|
| `@AuditLog` 加在内部方法上 | 加在入口方法（Controller/Service 公开方法）上才有审计价值 |
| `@FeatureToggle(name="ai_search")` 配置名不完整 | 要写完整配置路径如 `features.ai_search` |
| 以为 `@FeatureToggle` 关闭后方法不执行 | 方法仍被调用，框架根据配置决定是否执行业务逻辑 |

---

## 代码位置与测试

| 注解组 | 实现位置 | 测试文件 |
|--------|---------|---------|
| 生命周期 | `spring/annotations/core.py` | `tests/test_lifecycle_annotations.py` |
| 日志与监控 | `spring/annotations/core.py` | `tests/test_logging_annotations.py` |
| Bean 配置 | `spring/annotations/core.py` | `tests/test_bean_config_annotations.py` |
| 业务增强 | `spring/annotations/core.py` | `tests/test_comprehensive_aop.py` |

完整测试报告见 [TEST_REPORT.md](TEST_REPORT.md)。

---

## FAQ

### Q1: @PostConstruct 和 __init__ 有什么区别？

`__init__` 是 Python 构造方法，在实例化时执行，此时依赖注入可能尚未完成。`@PostConstruct` 在依赖注入完成后执行，可以安全地使用 `@Autowired` 注入的依赖。

### Q2: @Primary 和 @Qualifier 怎么配合？

`@Primary` 标记默认首选 Bean。当注入点没有 `@Qualifier` 时选 `@Primary` 的；有 `@Qualifier` 时显式指定优先。

### Q3: @Profile 和 @ConditionalOnProperty 有什么区别？

- `@Profile` 按环境名判断（`SPRING_PROFILES_ACTIVE=dev`），适合整体环境切换
- `@ConditionalOnProperty` 按具体配置值判断，更细粒度

### Q4: @Lazy 能省内存吗？

能延迟初始化，但不会减少总内存。如果 Bean 最终都会被使用，`@Lazy` 只是把创建时机推迟，不影响最终内存占用。主要价值是加快启动速度。

---

## 改进记录

暂无。
