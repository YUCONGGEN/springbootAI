# SpringBootAI 常用注解模块指南

本文集中说明五组最常用、也最容易混淆的功能：Bean Validation、条件装配、缓存增强、CSV 注解，以及 JPA 风格的 `@Version` / `@Transient`。每一节先说明作用，再给出可以照着改的最小示例。

第一次使用框架时，建议先完成 [新手入门指南](BEGINNER_GUIDE.md)。

## 1. Bean Validation：在业务执行前拦住错误数据

### 1.1 它解决什么问题

如果用户名为空、年龄为负数或邮箱格式错误，数据不应该进入 Service 和数据库。Bean Validation 让这些规则跟着 DTO 类声明，避免在每个方法里重复写 `if`。

### 1.2 可用约束

| 约束 | 作用 | 空值行为 |
|---|---|---|
| `NotNull` | 不能是 `None` | `None` 失败，空字符串允许 |
| `NotBlank` | 字符串去掉空格后不能为空 | `None` 和空白字符串失败 |
| `NotEmpty` | 字符串、列表、字典等长度必须大于 0 | `None` 和空集合失败 |
| `Size(min, max)` | 限制字符串或集合长度 | `None` 跳过，应配合 `NotNull` |
| `Min(value)` / `Max(value)` | 限制数值下限/上限 | `None` 跳过 |
| `Positive` / `PositiveOrZero` | 必须大于 0 / 大于等于 0 | `None` 跳过 |
| `Negative` / `NegativeOrZero` | 必须小于 0 / 小于等于 0 | `None` 跳过 |
| `Pattern(regex)` | 正则表达式匹配 | `None` 跳过 |
| `Email` | 基础邮箱格式检查 | `None` 和空串交给非空约束 |
| `AssertTrue` / `AssertFalse` | 布尔值必须为真 / 假 | `None` 跳过 |

### 1.3 定义并手动校验 DTO

```python
from spring.validation import BeanValidator, Email, Min, NotBlank, Size


class CreateUserRequest:
    name = NotBlank(message="姓名不能为空")
    age = Min(0, message="年龄不能小于 0")
    email = Email(message="邮箱格式错误")
    password = Size(min=6, max=20, message="密码长度必须为 6 到 20 位")

    def __init__(self, name=None, age=None, email=None, password=None):
        self.name = name
        self.age = age
        self.email = email
        self.password = password


request = CreateUserRequest("", -1, "bad-email", "123")
violations = BeanValidator.validate(request)
for item in violations:
    print(item.attr_name, item.message)

# 希望发现错误就立即停止时使用：
BeanValidator.validate_or_raise(request)
```

`validate()` 返回全部错误，适合一次性展示给前端；`validate_or_raise()` 有错误就抛 `ValidationError`，适合 Service 入口。

### 1.4 在受管 Service 中自动校验

```python
from spring.annotations import Service
from spring.validation import BeanValidate


@Service
class UserService:
    @BeanValidate("request")
    def create_user(self, request: CreateUserRequest):
        return {"name": request.name}
```

调用 `create_user()` 前框架会校验 `request`。如果参数有类型标注，也可以写不带参数名的 `@BeanValidate`，框架会自动查找带约束的参数类型。

注意：`@BeanValidate` 依赖 AOP，只对容器创建的受管 Bean 生效。自己执行 `UserService()` 得到的裸对象不会自动包装。

## 2. 条件装配：只在条件满足时创建 Bean

### 2.1 它解决什么问题

同一套代码可能在不同环境启用不同实现。例如只有配置 `feature.audit=true` 时才注册审计 Service，或者用户没有提供自定义实现时才创建默认实现。这就是条件装配。

### 2.2 注解选择

| 注解 | 什么时候注册 Bean |
|---|---|
| `@ConditionalOnProperty` | 指定配置存在或等于目标值 |
| `@ConditionalOnBean` | 容器中已经有指定名称/类型的 Bean |
| `@ConditionalOnMissingBean` | 容器中还没有指定 Bean，常用于默认实现 |
| `@ConditionalOnClass` | Python 模块或类可以导入 |
| `@Conditional` | 自定义函数或条件类返回 `True` |

### 2.3 按配置开关功能

`application.yml`：

```yaml
features:
  audit: true
```

Service：

```python
from spring.annotations import ConditionalOnProperty, Service


@ConditionalOnProperty("features.audit", having_value="True")
@Service
class AuditService:
    def record(self, action: str):
        return {"action": action}
```

配置加载后的布尔值会转成字符串比较，因此应根据实际配置值使用 `"True"` 或 `"False"`。只想判断配置是否存在时省略 `having_value`。

### 2.4 提供默认实现

```python
from spring.annotations import ConditionalOnMissingBean, Service


@ConditionalOnMissingBean(bean_name="mailSender")
@Service("mailSender")
class DefaultMailSender:
    def send(self, message: str):
        print(message)
```

扫描顺序会影响 `OnBean` / `OnMissingBean`。被依赖的 Bean 应放在更早扫描的包，复杂自动配置建议使用 `@Configuration` + `@Bean` 明确声明。

## 3. 缓存增强：减少重复查询并保持缓存同步

### 3.1 四个缓存注解的区别

| 注解 | 方法是否执行 | 典型用途 |
|---|---|---|
| `@Cacheable` | 命中缓存时不执行 | 查询用户、商品详情 |
| `@CachePut` | 每次都执行，返回值写缓存 | 更新数据后刷新缓存 |
| `@CacheEvict` | 执行前或成功后删除缓存 | 删除数据或让旧缓存失效 |
| `@Caching` | 组合多个缓存操作 | 同时更新/删除多个缓存 |

`@CacheConfig` 放在类上，为方法提供默认缓存名称。

### 3.2 查询、更新和删除的完整示例

```python
from spring.annotations import Cacheable, Service
from spring.annotations.cache import CacheConfig, CacheEvict, CachePut


@CacheConfig(cache_names=["users"])
@Service
class UserService:
    @Cacheable(key="{id}")
    def get_user(self, id: int):
        print("实际查询数据库")
        return {"id": id, "name": "old"}

    @CachePut(key="{id}")
    def update_user(self, id: int, name: str):
        # 实际项目应先更新数据库，再返回最新对象
        return {"id": id, "name": name}

    @CacheEvict(key="{id}")
    def delete_user(self, id: int):
        return None
```

验证方式：连续两次调用 `get_user(1)`，日志“实际查询数据库”应只出现一次；调用 `update_user(1, "new")` 后再次查询，应得到新名称；调用 `delete_user(1)` 后再次查询，应重新执行方法。

当前缓存抽象默认复用 BeanFactory 的进程内缓存。多 worker 或多主机部署时，各进程缓存并不共享；需要集群一致缓存时应接入 Redis 并验证失效传播。

## 4. CSV 注解：把对象列表导入导出为 CSV

CSV 适合简单表格、系统间交换和批量导入。它不支持 Excel 的颜色、公式、合并单元格和工作表。

```python
from spring.csv import CsvIgnore, CsvProperty, csv_file, read_csv, write_csv


@csv_file("users", encoding="utf-8-sig")
class UserRow:
    id = CsvProperty("ID", order=1)
    name = CsvProperty("姓名", order=2)
    internal_note = CsvIgnore()

    def __init__(self, id=None, name=None, internal_note=None):
        self.id = id
        self.name = name
        self.internal_note = internal_note


write_csv("users.csv", [UserRow(1, "Alice")], UserRow)
rows = read_csv("users.csv", UserRow)
print(rows[0].name)
```

Windows Excel 打开中文 CSV 时建议使用 `utf-8-sig`。更完整的分隔符、类型转换、大整数和流式 API 说明见 [CSV 模块指南](CSV_MODULE.md)。

## 5. `@Version` / `@Transient`：并发更新保护和非持久字段

### 5.1 `Version` 的作用

两个人同时修改同一条订单时，后保存的人可能覆盖前一个人的结果。乐观锁给记录增加版本号：更新时要求数据库版本仍等于读取时的版本，否则报告冲突。

### 5.2 `Transient` 的作用

有些属性只用于展示或临时计算，例如 `display_name`、`cache_key`，不应该生成数据库列。使用 `Transient` 后 DDL 和 ORM 映射会跳过它。

### 5.3 实体和更新示例

```python
from spring.orm import (
    Column,
    Id,
    OptimisticLockError,
    OptimisticLockExecutor,
    Transient,
    Version,
    entity,
)


@entity("sys_user")
class User:
    id = Id()
    name = Column(nullable=False, length=50)
    version = Version()
    display_name = Transient()

    def __init__(self, id=None, name=None, version=0, display_name=None):
        self.id = id
        self.name = name
        self.version = version
        self.display_name = display_name


executor = OptimisticLockExecutor(connection_pool, dialect="mysql")
try:
    new_version = executor.update(
        entity_class=User,
        entity=user,
        set_fields={"name": "new name"},
    )
    print("更新成功，新版本：", new_version)
except OptimisticLockError:
    print("记录已被其他请求修改，请重新读取后再提交")
```

`Version` 会生成版本列，但 PyMyBatis 普通 `@Update` 不会自动插入版本条件；要获得乐观锁语义，必须使用 `OptimisticLockExecutor.update()` 或 `try_update()`。

## 6. 上线前检查

1. Validation：用空值、边界值和错误格式测试每条约束。
2. Conditional：分别在条件为真、假、缺失时启动应用，检查 Bean 是否注册。
3. Cache：测试命中、更新、删除、异常时是否失效，以及多 worker 行为。
4. CSV：测试中文、空行、超长数字、错误列名和大文件内存占用。
5. Version：使用两个旧版本对象并发更新，确认第二次更新发生冲突。

对应自动化测试位于 `tests/test_validation_module.py`、`tests/test_conditional_annotations.py`、`tests/test_cache_annotations.py`、`tests/test_csv_module.py` 和 `tests/test_jpa_version_transient.py`。
