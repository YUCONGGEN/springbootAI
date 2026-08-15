# 声明式 AOP、后置鉴权与重试恢复指南

> 框架版本：SpringBootAI 2.3.0
>
> 适用范围：`@Aspect` 通知、`@PostAuthorize` 返回后鉴权、`@Recover` 重试失败兜底。

---

## 先看结论：我该用哪个注解？

| 你遇到的问题 | 使用的注解 | 一句话解释 |
|---|---|---|
| 很多 Service 都要记录日志、统计耗时或统一处理异常 | `@Aspect` + 通知注解 | 把重复的“方法前后逻辑”集中写在一个切面里 |
| 必须看到方法返回的数据，才能判断当前用户能不能读取 | `@PostAuthorize` | 业务方法先执行，再检查返回值 |
| 远程调用重试多次仍失败，需要返回缓存或默认值 | `@Retryable` + `@Recover` | 重试耗尽后自动调用类型匹配的兜底方法 |

这三项能力都作用于框架管理的 Bean。类通常需要加 `@Service`、`@Component`、
`@Repository` 或 `@RestController`，并由组件扫描和依赖注入取得实例。

```python
# 错误：手工创建的对象不会安装框架 AOP
service = OrderService()

# 正确：让 SpringBootAI 扫描和注入 OrderService
@Autowired
def __init__(self, order_service: OrderService):
    self.order_service = order_service
```

---

## 一、声明式 AOP：把重复逻辑集中管理

### 1. 解决什么问题？

假设 20 个 Service 方法都要记录“开始、成功、失败”。在每个方法里复制日志代码，
以后修改格式就要改 20 次。声明式 AOP 可以把这些共同逻辑放进一个切面，业务方法只保留业务代码。

可以把它理解成高速公路收费站：符合切点规则的方法都会经过同一个入口，切面可以在方法执行前、
执行后或发生异常时做统一处理。

### 2. 最小可用示例

```python
from spring.annotations import (
    AfterReturning,
    AfterThrowing,
    Around,
    Aspect,
    Before,
    Pointcut,
    Service,
)
from spring.aop import JoinPoint, ProceedingJoinPoint


@Aspect
class ServiceLogAspect:
    # 匹配所有类名以 Service 结尾的公开方法
    @Pointcut("execution(* *.*Service.*(..))")
    def service_methods(self):
        pass

    @Before("service_methods()")
    def before(self, join_point: JoinPoint):
        print("开始调用:", join_point.signature)

    @Around("service_methods()")
    def around(self, join_point: ProceedingJoinPoint):
        # 不调用 proceed()，目标方法就不会执行
        result = join_point.proceed()
        return result

    @AfterReturning(pointcut="service_methods()", returning="result")
    def success(self, result):
        print("调用成功，返回:", result)

    @AfterThrowing(pointcut="service_methods()", throwing="error")
    def failure(self, error):
        print("调用失败:", error)


@Service
class OrderService:
    def find_order(self, order_id: int):
        return {"id": order_id, "status": "PAID"}
```

Controller 通过注入调用 `OrderService.find_order(1)` 时，切面会自动生效。`@Aspect` 本身就是组件注解，
不需要再叠加 `@Component`。

### 3. 七个 AOP 注解分别做什么？

| 注解 | 执行时机 | 常见用途 |
|---|---|---|
| `@Aspect` | 写在类上 | 声明这个类是切面 Bean |
| `@Pointcut` | 写在空方法上 | 给切点表达式起一个可复用的名字 |
| `@Before` | 目标方法执行前 | 参数检查、入口日志 |
| `@After` | 目标方法结束后 | 无论成功或异常都执行清理逻辑 |
| `@Around` | 包住整个调用 | 计时、改参数、改返回值；必须主动调用 `proceed()` |
| `@AfterReturning` | 目标方法成功返回后 | 记录结果、成功指标 |
| `@AfterThrowing` | 目标方法抛异常后 | 失败日志、错误指标；原异常仍会继续抛出 |

正常调用的顺序是：

```text
@Before -> @Around 调用 proceed() 前 -> 业务方法
        -> @Around 调用 proceed() 后 -> @AfterReturning -> @After
```

异常调用的顺序是：

```text
@Before -> @Around 调用 proceed() 前 -> 业务方法抛异常
        -> @AfterThrowing -> @After -> 原异常继续向外抛出
```

### 4. 切点表达式怎么写？

| 写法 | 匹配对象 | 示例 |
|---|---|---|
| `execution(...)` | 完整的“模块.类.方法” | `execution(* *.*Service.*(..))` |
| `within(...)` | 类 | `within(myapp.service.*)` |
| `bean(...)` | 容器中的 Bean 名 | `bean(order*)` |
| `@annotation(...)` | 带指定注解的方法 | `@annotation(Retryable)` |
| `pointcutName()` | 当前切面中用 `@Pointcut` 声明的切点 | `service_methods()` |

可以使用 `&&`、`||`、`!` 组合规则，也可以写成 `and`、`or`、`not`：

```python
@Pointcut("bean(order*) && @annotation(Retryable)")
def retrying_order_methods(self):
    pass

@Before("retrying_order_methods()")
def record_retry_entry(self, join_point):
    print(join_point.method_name)
```

通配符规则：`*` 匹配任意字符；`..` 在方法签名和包路径中也按任意范围匹配。建议先用明确的
Service 类名或 Bean 名前缀，避免切点过宽，把框架组件也拦截进去。

### 5. JoinPoint 里有什么？

| 属性/方法 | 含义 |
|---|---|
| `join_point.target` | 当前目标 Bean 实例 |
| `join_point.method` | 原始方法 |
| `join_point.method_name` | 方法名 |
| `join_point.signature` | 完整的模块、类和方法名 |
| `join_point.args` | 本次业务参数，不包含 `self` |
| `join_point.kwargs` | 本次关键字参数 |
| `join_point.proceed()` | 仅 `ProceedingJoinPoint` 有；继续执行调用链 |

`@Around` 还可以替换参数：

```python
@Around("execution(* *.GreetingService.greet(..))")
def normalize_name(self, join_point):
    clean_name = join_point.args[0].strip().title()
    return join_point.proceed(clean_name)
```

### 6. 同步和异步方法

目标方法和通知都支持 `async def`。异步通知必须使用 `await`：

```python
@Around("execution(* *.RemoteService.load(..))")
async def measure(self, join_point):
    result = await join_point.proceed()
    return result
```

不要在同步通知中返回 coroutine。同步调用链无法替你等待异步结果，框架会直接报错，避免悄悄漏执行。

### 7. AOP 常见错误

| 错误现象 | 原因 | 正确做法 |
|---|---|---|
| 切面完全不执行 | 目标对象是手工 `new` 出来的 | 使用组件扫描和 `@Autowired` |
| `@Around` 后业务方法没执行 | 忘了调用 `join_point.proceed()` | 在适当位置调用并返回结果 |
| 启动时报 `Unknown pointcut reference` | 通知引用了不存在的切点方法 | 检查 `@Pointcut` 方法名和 `()` |
| 一个方法被记录太多次 | 切点范围太宽或多个切面同时匹配 | 缩小类名、Bean 名或注解范围 |
| 异常被通知“吃掉”的预期没有实现 | `@AfterThrowing` 只观察异常 | 需要降级时使用 `@Recover` 或业务异常处理 |

---

## 二、@PostAuthorize：看到返回值后再决定能否访问

### 1. 为什么 `@PreAuthorize` 不够？

`@PreAuthorize` 在方法执行前检查权限，适合“只有管理员能调用”这类规则。但有些权限取决于查出来的数据：

- 用户只能读取自己创建的文档；
- 客服只能读取自己负责的工单；
- 返回对象包含 `tenant_id`，必须和当前租户一致。

这些信息在方法执行前还不存在，因此需要 `@PostAuthorize`。

### 2. 完整示例

```python
from spring.annotations import Authenticate, PostAuthorize, Service


@Service
class DocumentService:
    @Authenticate
    @PostAuthorize(
        "returnObject.owner == authentication.name "
        "and hasPermission('document:read')"
    )
    def find_document(self, document_id: int):
        # 实际项目中通常从数据库查询
        return {
            "id": document_id,
            "owner": "alice",
            "content": "private data",
        }
```

执行过程：

1. `@Authenticate` 从 JWT 建立当前用户上下文；
2. `find_document()` 查询并返回文档；
3. `@PostAuthorize` 把返回值放入 `returnObject`；
4. 条件为真则返回数据，为假则抛出 403 `AuthorizationError`。

也支持 Spring 风格的 `#returnObject` 别名：

```python
@PostAuthorize("#returnObject.owner == authentication.name")
```

### 3. 支持的表达式

| 表达式 | 含义 |
|---|---|
| `returnObject.owner` | 读取对象属性或字典键 `owner` |
| `returnObject['owner']` | 使用下标读取返回值 |
| `authentication.name` | 当前认证用户名称 |
| `principal` | 当前用户主体 |
| `hasRole('ROLE_ADMIN')` | 是否有指定角色 |
| `hasAnyRole('ROLE_ADMIN', 'ROLE_AUDITOR')` | 是否有任一角色 |
| `hasPermission('document:read')` | 是否有指定权限 |
| `hasAnyPermission(...)` | 是否有任一权限 |
| `and` / `or` / `not` | 组合多个条件 |
| `==` / `!=` / `in` / `not in` / `is null` | 比较返回值和身份信息 |

表达式使用白名单 AST 解释器，不执行任意 Python 代码。函数调用、私有属性和不支持的语法会按鉴权失败处理，
不会回退到 `eval()`。

### 4. 必须知道的边界

`@PostAuthorize` 是“先执行业务，再拦住返回值”。如果方法已经扣款、发消息或写数据库，即使最后返回 403，
这些副作用也已经发生。因此：

- 修改、删除、付款等操作优先使用 `@PreAuthorize`；
- `@PostAuthorize` 更适合查询结果的所有者校验；
- 必须前后都检查时，可以同时使用 `@PreAuthorize` 和 `@PostAuthorize`；
- 返回集合时，`@PostAuthorize` 只决定整个返回值能否放行，不会自动过滤集合中的某几项。

### 5. 状态码语义

| 情况 | 异常/HTTP 状态 |
|---|---|
| 没有认证上下文 | `AuthenticationError` / 401 |
| 已认证，但返回值不满足表达式 | `AuthorizationError` / 403 |
| 业务方法本身抛异常 | 保留原业务异常，不执行后置鉴权 |
| 表达式语法非法或尝试执行代码 | 按无权限处理 / 403 |

---

## 三、@Recover：重试全部失败后的兜底方法

### 1. 解决什么问题？

`@Retryable` 能处理偶发网络抖动，但远程服务持续不可用时，继续抛异常可能不是最合适的用户体验。
`@Recover` 可以在所有重试都失败后，返回缓存、默认值或明确的降级结果。

### 2. 完整示例

```python
from spring.annotations import Recover, Retryable, Service
from spring.retry import Backoff


@Service
class InventoryService:
    @Retryable(
        value=(ConnectionError, TimeoutError),
        max_attempts=3,
        backoff=Backoff(delay=200, multiplier=2.0),
    )
    def get_stock(self, product_id: int):
        return self.remote_client.get_stock(product_id)

    @Recover(ConnectionError)
    def connection_fallback(self, error, product_id: int):
        return {"product_id": product_id, "stock": 0, "reason": str(error)}

    @Recover(TimeoutError)
    def timeout_fallback(self, error, product_id: int):
        return {"product_id": product_id, "stock": 0, "reason": "timeout"}
```

`max_attempts=3` 包含第一次调用，即最多执行目标方法 3 次，不是“第一次再加 3 次”。第三次仍抛出匹配异常时，
框架才查找 `@Recover` 方法。

### 3. 恢复方法签名规则

```python
@Recover(ConnectionError)
def fallback(self, error, product_id, region="cn"):
    ...
```

规则如下：

1. 第一个业务参数是最终异常 `error`；
2. 后续参数必须能接收原 `@Retryable` 方法的业务参数；
3. 返回值就是原方法最终返回给调用者的值；
4. 找不到类型和签名都匹配的方法时，重新抛出最后一次原异常；
5. 恢复方法自己抛异常时，恢复异常会正常向外传播，不会被静默吞掉。

也可以用类型注解推断异常，无需给 `@Recover` 传参数：

```python
@Recover
def fallback(self, error: ConnectionError, product_id: int):
    return {"product_id": product_id, "stock": 0}
```

### 4. 多个 @Recover 怎么选择？

框架选择和最终异常类型最接近的方法。例如 `ConnectionError` 是 `OSError` 的子类：

```python
@Recover(ConnectionError)
def recover_connection(self, error, key):
    return "连接错误专用兜底"

@Recover(OSError)
def recover_io(self, error, key):
    return "通用 IO 兜底"
```

最终异常是 `ConnectionError` 时选择第一个；是其他 `OSError` 时选择第二个。

### 5. 兼容旧式 recover 参数

原有按方法名指定恢复方法的写法继续支持：

```python
@Retryable(max_attempts=3, recover="fallback")
def call_remote(self, key):
    ...

def fallback(self, key):
    return "legacy fallback"
```

新代码建议使用 `@Recover`，因为它能按异常类型选择不同方法，并显式接收最终异常。旧式恢复方法保持旧签名，
默认不自动插入异常参数。如果显式命名的方法同时加了 `@Recover`，则使用新签名规则。

### 6. 异步恢复

异步重试方法可以配异步或同步恢复方法：

```python
@Retryable(value=(TimeoutError,), max_attempts=2, backoff=0)
async def load(self, key):
    raise TimeoutError("slow")

@Recover(TimeoutError)
async def recover(self, error, key):
    return {"key": key, "status": "degraded"}
```

### 7. 重试与恢复的常见错误

| 错误现象 | 原因 | 正确做法 |
|---|---|---|
| 实际请求了 4 次 | 把 `max_attempts=3` 理解成“额外重试 3 次” | 它表示总尝试次数为 3 |
| `@Recover` 没执行 | 异常不在 `@Retryable.value` 中，或被 `exclude` 排除 | 检查异常类型配置 |
| `@Recover` 没匹配 | 恢复方法参数接不住原方法参数 | 保留 `error`，后面写齐业务参数 |
| 写操作重试后产生重复数据 | 方法不是幂等操作 | 使用幂等键或事务约束后再开启重试 |
| 兜底一直返回假数据 | 把降级当成永久成功 | 返回明确降级状态，并记录指标和告警 |

---

## 四、三项能力一起使用时

```python
@Service
class OrderQueryService:
    @PostAuthorize("returnObject.owner == authentication.name")
    @Retryable(value=(ConnectionError,), max_attempts=3, backoff=200)
    def find_order(self, order_id):
        return self.remote_client.find_order(order_id)

    @Recover(ConnectionError)
    def recover_order(self, error, order_id):
        return self.local_cache.find_order(order_id)
```

调用链会先完成重试；重试耗尽则调用恢复方法；无论结果来自远程服务还是本地恢复，最终都会再经过
`@PostAuthorize`。因此缓存里的兜底数据也必须满足所有者校验。

声明式 `@Aspect` 是受管 Bean 的最外层扩展，可观察内置重试和安全包装后的最终成功或失败。切面内部不要打印
JWT、密码、完整请求体或敏感返回值。

---

## 五、怎么验证你的代码真的生效？

至少验证以下场景：

| 功能 | 必测场景 |
|---|---|
| AOP | 正常返回、业务异常、`@After` 两条路径都执行、异步方法、切点不匹配的方法不执行通知 |
| PostAuthorize | 返回值匹配、返回值不匹配、未认证、异步方法、恶意表达式被拒绝 |
| Recover | 第 N 次成功、耗尽后恢复、最具体异常匹配、无匹配时保留原异常、异步恢复 |

运行本仓库对应测试：

```powershell
conda run -n py3.10 python -m pytest tests/test_declarative_aop_post_authorize_recover.py -q
```

生产上线前还要验证真实并发、超时、外部服务故障、日志脱敏和降级数据的新鲜度。单元测试通过不代表可以把
无上限重试或宽泛切点直接放到生产环境。

---

## 改进记录

### AOP 异步切面未正确 await 返回值 — 中 ⏳ 待处理 (v2.3.0)

**位置**：`spring/aop/aspect.py` 异步包装路径

**现象**：异步函数上的 advice 包装未完全考虑 `await` 传播。若 `around` advice 返回 coroutine 但未被 await，会导致协程从未执行（静默跳过业务逻辑）。

**改进方案**：统一使用 `async def` + `await` 调用 advice；增加 `inspect.iscoroutinefunction(target)` 检测，对同步/异步方法走不同包装路径；补充异步 `@Around`、`@AfterReturning` 测试。
