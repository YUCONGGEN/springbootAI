# SpringBootAI 常用注解模块指南

> 框架版本：SpringBootAI 2.0.0

---

## 注解模块是什么？

**注解模块 = 常用工具注解集——就像瑞士军刀，每个注解解决一个特定问题。** 本文介绍五组最常用的注解工具：数据校验、条件装配、缓存、CSV 读写、并发保护。你不需要一次性全部学会——用到哪个看哪个就行。

### 🔥 新手最常用的 5 个注解速查

| 注解 | 一句话作用 | 写在哪 | 示例 |
|------|----------|--------|------|
| `@NotBlank` | 字符串不能为空（去空格后判断） | 类属性 | `name = NotBlank(message="姓名不能为空")` |
| `@ConditionalOnProperty` | 根据配置文件决定是否启用功能 | 类上 | `@ConditionalOnProperty("features.audit")` |
| `@Cacheable` | 缓存方法结果，下次直接拿 | 方法上 | `@Cacheable(key="{id}")` |
| `@Version` | 乐观锁——防止两个人同时编辑同一条数据 | 类属性 | `version = Version()` |
| `@Transient` | 这个字段不存数据库 | 类属性 | `display_name = Transient()` |

### 决策指引：我想做什么该看哪节？

| 我想做的事 | 看哪节 |
|-----------|--------|
| 让接口自动校验输入数据（如"用户名不能为空"） | [Bean Validation](#1-bean-validation数据校验) |
| 根据配置文件开关功能（如"只有配置了才启用审计"） | [条件装配](#2-条件装配) |
| 缓存查询结果，减少重复查询 | [缓存增强](#3-缓存增强) |
| 把对象列表导出为 CSV 文件 | [CSV 注解](#4-csv-注解) |
| 防止多人同时修改同一条数据 | [@Version / @Transient](#5-version--transient) |

---

## 1. Bean Validation：数据校验

### 是什么？

**就像门卫检查——不满足条件不让进。** 在数据进入你的业务代码之前，自动检查：用户名有没有填？年龄是负数吗？邮箱格式对吗？不用在每个方法里手写一大堆 `if` 判断。

### 怎么用？

**步骤一：在类属性上声明校验规则**

```python
from spring.validation import BeanValidator, Email, Min, NotBlank, Size


class CreateUserRequest:
    # 校验规则：name 不能为空、age 不小于 0、email 格式正确、password 长度 6~20
    name = NotBlank(message="姓名不能为空")
    age = Min(0, message="年龄不能小于 0")
    email = Email(message="邮箱格式错误")
    password = Size(min=6, max=20, message="密码长度必须为 6 到 20 位")

    def __init__(self, name=None, age=None, email=None, password=None):
        self.name = name
        self.age = age
        self.email = email
        self.password = password
```

**步骤二：调用校验**

```python
# 创建一条错误数据（所有字段都不合法）
request = CreateUserRequest(name="", age=-1, email="bad-email", password="123")

# 方式一：返回所有错误列表，适合一次性展示给前端
violations = BeanValidator.validate(request)
for item in violations:
    print(item.attr_name, item.message)
# 输出:
# name 姓名不能为空
# age 年龄不能小于 0
# email 邮箱格式错误
# password 密码长度必须为 6 到 20 位

# 方式二：有错误直接抛异常，适合 Service 入口
BeanValidator.validate_or_raise(request)
# 结果: 如果有错误，抛出 ValidationError，后续代码不执行
```

**步骤三（可选）：在 Service 中自动校验**

```python
from spring.annotations import Service
from spring.validation import BeanValidate


@Service
class UserService:
    @BeanValidate("request")  # 框架在调用方法前自动校验 request 参数
    def create_user(self, request: CreateUserRequest):
        return {"name": request.name}
```

### 可用约束速查表

| 注解 | 一句话解释 | 使用场景 |
|------|-----------|---------|
| `NotNull` | 不能是 `None` | 必填的 ID、外键 |
| `NotBlank` | 去掉空格后不能为空 | 姓名、标题等文本字段 |
| `NotEmpty` | 长度必须大于 0 | 列表参数、标签集合 |
| `Size(min, max)` | 限制字符串或集合长度 | 密码、简介等有长度限制的字段 |
| `Min(value)` / `Max(value)` | 限制数值下限/上限 | 年龄、价格、数量 |
| `Positive` / `PositiveOrZero` | 必须大于 0 / 大于等于 0 | 价格、库存、ID |
| `Negative` / `NegativeOrZero` | 必须小于 0 / 小于等于 0 | 欠款、温度等负值场景 |
| `Pattern(regex)` | 正则表达式匹配 | 手机号、身份证格式 |
| `Email` | 基础邮箱格式检查 | 邮箱字段 |
| `AssertTrue` / `AssertFalse` | 布尔值必须为真/假 | 同意协议、开关选项 |

> 注意：`Size`、`Min`、`Max` 等遇到 `None` 会跳过，不报错。如果要强制非空，请配合 `NotNull` 一起使用。

### 新手常见错误

| ❌ 错误做法 | ✅ 正确做法 |
|------------|------------|
| 自己 `new UserService()` 想让它自动校验 | `@BeanValidate` 依赖 AOP，只对框架管理的 Bean 生效。你手动 `new` 出来的对象不会被自动校验 |
| 用 `NotNull` 拦空字符串 | `NotNull` 只拦 `None`，空字符串 `""` 能通过。要拦空字符串用 `NotBlank` |
| 只用 `@Size` 不加 `@NotNull` | `@Size` 遇到 `None` 会跳过！要配合 `@NotNull` 一起用才能保证非空 |

---

## 2. 条件装配

### 是什么？

**根据配置决定是否启用某个功能。** 就像遥控器上有"3D 模式"按钮才启用 3D 功能——某个条件满足时，框架才创建和管理这个 Bean。

### 五种条件注解速查表

| 注解 | 一句话解释 | 使用场景 |
|------|-----------|---------|
| `@ConditionalOnProperty` | 指定配置存在或等于目标值时注册 Bean | 功能开关：`features.audit=true` 才启用审计 |
| `@ConditionalOnBean` | 容器中有指定 Bean 时才注册 | 有 DataSource 才注册 Repository |
| `@ConditionalOnMissingBean` | 容器中没有指定 Bean 时才注册 | 提供默认实现：用户没自定义就用默认的 |
| `@ConditionalOnClass` | 指定模块或类可以导入时才注册 | 装了 openpyxl 才启用 Excel 功能 |
| `@Conditional` | 自定义条件函数返回 `True` 才注册 | 复杂的自定义规则 |

### 怎么用？

**场景一：按配置开关功能**

`application.yml`:
```yaml
features:
  audit: true
```

```python
from spring.annotations import ConditionalOnProperty, Service


@ConditionalOnProperty("features.audit", having_value="True")
@Service
class AuditService:
    def record(self, action: str):
        return {"action": action}  # 仅当 features.audit=true 时才生效
```

**场景二：别人有就用别人的，没有才用自己的**

```python
from spring.annotations import ConditionalOnMissingBean, Service


@ConditionalOnMissingBean(bean_name="mailSender")
@Service("mailSender")
class DefaultMailSender:
    def send(self, message: str):
        print(message)  # 仅当容器中还没有名为 mailSender 的 Bean 时才生效
```

### 新手常见错误

| ❌ 错误做法 | ✅ 正确做法 |
|------------|------------|
| `having_value=True`（布尔值） | 配置值是字符串，要写 `having_value="True"` |
| 不管扫描顺序，随便放 | `OnBean` / `OnMissingBean` 依赖扫描顺序。被依赖的 Bean 应放在更早扫描的包中 |
| 以为条件注解能动态切换 | 条件注解只在启动时判断一次，运行期间不会动态切换 |

---

## 3. 缓存增强

### 是什么？

**就像备忘录——第一次算完记下来，下次直接拿结果。** 第一次查数据库后把结果暂存，下次再查直接用缓存，速度飞快。

### 四个缓存注解速查表

| 注解 | 一句话解释 | 使用场景 |
|------|-----------|---------|
| `@Cacheable` | 有缓存就返回缓存，没有就执行方法并缓存 | 查询用户、商品详情 |
| `@CachePut` | 每次都执行方法，并把返回值写入缓存 | 更新数据后刷新缓存 |
| `@CacheEvict` | 删除指定缓存 | 删除数据时让旧缓存失效 |
| `@Caching` | 组合多个缓存操作 | 同时更新多个缓存 |
| `@CacheConfig` | 放在类上，提供默认缓存名称 | 给一组方法设置共用缓存名 |

### 怎么用？

```python
from spring.annotations import Cacheable, Service
from spring.annotations.cache import CacheConfig, CacheEvict, CachePut


@CacheConfig(cache_names=["users"])  # 默认缓存名
@Service
class UserService:

    @Cacheable(key="{id}")  # 第一次查完记下来，下次直接用缓存
    def get_user(self, id: int):
        print("实际查询数据库")  # 只有缓存未命中时才会打印
        return {"id": id, "name": "张三"}

    @CachePut(key="{id}")  # 更新数据后同时刷新缓存
    def update_user(self, id: int, name: str):
        # 实际项目中应先更新数据库
        return {"id": id, "name": name}

    @CacheEvict(key="{id}")  # 删除数据后同时删缓存
    def delete_user(self, id: int):
        return None
```

**运行结果：**
- 连续两次调用 `get_user(1)`，日志"实际查询数据库"只出现一次
- 调用 `update_user(1, "李四")` 后再查，直接返回"李四"，不查数据库
- 调用 `delete_user(1)` 后再查，重新执行方法查数据库

### 新手常见错误

| ❌ 错误做法 | ✅ 正确做法 |
|------------|------------|
| 以为多台服务器共享缓存 | 默认缓存是进程内的，多台服务器各存各的。需要共享要接入 Redis |
| 以为 `@CacheEvict` 删了缓存就一定成功 | `@CacheEvict` 默认在方法**成功**后才删缓存。如果方法抛异常了，缓存不会被删 |
| 以为 `@CachePut` 和 `@Cacheable` 一样 | `@CachePut` **每次都执行方法**，只是顺便更新缓存；`@Cacheable` 命中缓存时**不执行方法** |

---

## 4. CSV 注解

### 是什么？

**CSV 是最朴素的表格格式——纯文本，逗号分隔。** 就像用记事本打开一个表格：每行一条数据，每列用逗号分开。适合简单表格、系统间数据交换和批量导入。

> 注意：CSV 是纯文本格式，不支持 Excel 的颜色、公式、合并单元格和工作表。如果你需要这些，请看 [EXCEL_MODULE.md](EXCEL_MODULE.md)。

### CSV 注解速查表

| 注解 | 一句话解释 | 使用场景 |
|------|-----------|---------|
| `@CsvProperty` | 标记一个字段映射到 CSV 的哪一列 | 定义 CSV 列名和顺序 |
| `@CsvIgnore` | 这个字段不导入导出 | 内部用的临时字段 |
| `@csv_file` | 放在类上，指定文件相关信息 | 设置文件名和编码 |

### 怎么用？

```python
from spring.csv import CsvIgnore, CsvProperty, csv_file, read_csv, write_csv


@csv_file("users", encoding="utf-8-sig")  # utf-8-sig 编码让 Excel 正确显示中文
class UserRow:
    id = CsvProperty("ID", order=1)        # 第一列，列名 "ID"
    name = CsvProperty("姓名", order=2)    # 第二列，列名 "姓名"
    internal_note = CsvIgnore()            # 不导出

    def __init__(self, id=None, name=None, internal_note=None):
        self.id = id
        self.name = name
        self.internal_note = internal_note


# 写入 CSV 文件
write_csv("users.csv", [UserRow(1, "Alice"), UserRow(2, "Bob")], UserRow)
# 结果: 生成 users.csv，内容为 "ID,姓名\n1,Alice\n2,Bob"

# 从 CSV 文件读取
rows = read_csv("users.csv", UserRow)
print(rows[0].name)
# 输出: Alice
```

### 新手常见错误

| ❌ 错误做法 | ✅ 正确做法 |
|------------|------------|
| 把 CSV 当 Excel 用 | CSV 是纯文本，不支持颜色、公式、合并单元格 |
| 中文在 Excel 里打开乱码 | 用 `utf-8-sig` 编码（带 BOM），Windows Excel 才能正确识别中文 |
| 长数字（如身份证号）打开变成科学计数法 | CSV 本身不存格式信息，要在 Excel 中打开时设置列格式为文本 |

> 更多高级功能（自定义分隔符、类型转换、流式读取等）见 [CSV_MODULE.md](CSV_MODULE.md)。

---

## 5. @Version / @Transient

### 是什么？

**`@Version` = 乐观锁——防止两个人同时编辑同一条数据。** 就像你和同事同时打开同一个 Google 文档编辑，后保存的人会看到"文档已被他人修改"的提示。数据库记录会有一个版本号字段，更新时检查版本号有没有被改过。

**`@Transient` = 这个字段不存数据库。** 就像白板上的草图——只在内存里有用，不需要存档。

### 注解速查表

| 注解 | 一句话解释 | 使用场景 |
|------|-----------|---------|
| `@Version` | 乐观锁版本号，更新时自动检查+自增 | 防止并发更新覆盖 |
| `@Transient` | 标记字段不存数据库 | 临时计算字段、展示用字段 |

### 怎么用？

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


@entity("sys_user")  # 对应数据库表名
class User:
    id = Id()                           # 主键
    name = Column(nullable=False, length=50)  # 数据库列
    version = Version()                 # 乐观锁版本号
    display_name = Transient()          # 不存数据库，只在代码里用

    def __init__(self, id=None, name=None, version=0, display_name=None):
        self.id = id
        self.name = name
        self.version = version
        self.display_name = display_name


# 使用乐观锁更新
executor = OptimisticLockExecutor(connection_pool, dialect="mysql")

try:
    new_version = executor.update(
        entity_class=User,
        entity=user,
        set_fields={"name": "新名称"},
    )
    print("更新成功，新版本号：", new_version)
    # 输出: 更新成功，新版本号：2（version 从 1 变成 2）
except OptimisticLockError:
    print("数据已被其他人修改，请重新读取后再提交")
    # 输出: 数据已被其他人修改，请重新读取后再提交
```

### 运行结果说明

当两个人同时读取了 `version=1` 的同一条用户记录：
1. 第一个人更新成功 → `version` 变成 2
2. 第二个人更新时，数据库里 `version` 已经是 2 了，而他拿的还是 `version=1` → 抛出 `OptimisticLockError`

### 新手常见错误

| ❌ 错误做法 | ✅ 正确做法 |
|------------|------------|
| 以为加了 `@Version` 后普通 `@Update` 也会自动加版本判断 | `Version` 会生成版本列，但普通 `@Update` 不会自动检查版本。要获得乐观锁语义，必须用 `OptimisticLockExecutor.update()` |
| 以为 `@Transient` 标记的字段在代码里不能用 | 可以用，只是不会存到数据库、不会生成数据库列 |
| 在 `@Version` 字段上手动改值 | 版本号由 `OptimisticLockExecutor` 自动管理，不要手动修改 |

---

## 代码位置与测试

| 模块 | 实现位置 | 测试文件 | 用例数 |
|------|---------|---------|--------|
| Bean Validation | `spring/validation/` | `tests/test_validation_module.py` | 30 |
| 条件装配 | `spring/annotations/conditional.py` | `tests/test_conditional_annotations.py` | 45 |
| 缓存增强 | `spring/annotations/cache.py` | `tests/test_cache_annotations.py` | 25 |
| CSV 注解 | `spring/csv/` | `tests/test_csv_module.py` | 46 |
| @Version / @Transient | `spring/orm/` | `tests/test_jpa_version_transient.py` | 20 |

完整测试报告见 [TEST_REPORT.md](TEST_REPORT.md)。

---

## FAQ

### Q1: 注解到底是怎么生效的？

框架启动时会扫描你写的所有类，看到带注解的类/方法就把它们注册到容器里。AOP 注解（如 `@BeanValidate`、`@Cacheable`）则是在注册时给方法包了一层拦截器，调用方法前/后自动执行额外逻辑。

### Q2: Bean Validation 和 @BeanValidate 是什么关系？

- `BeanValidator.validate()` 是手动校验，你自己写代码调用
- `@BeanValidate` 是自动校验，贴在 Service 方法上，框架在调用方法前自动校验参数

### Q3: 条件注解和 @Profile 有什么区别？

- `@Profile` 是按环境名判断（dev / test / prod）
- `@ConditionalOnProperty` 是按具体配置值判断，更灵活

### Q4: 缓存的 key 能用多个参数吗？

可以。例如 `@Cacheable(key="{id}-{type}")` 会根据 `id` 和 `type` 两个参数的值组合成 key。
