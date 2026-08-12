# SpringBootAI BeanUtils 工具指南

> 对齐 `org.springframework.beans.BeanUtils`（Spring）与 `org.apache.commons.beanutils.BeanUtils`（Apache Commons）。
> 提供对象间属性复制、嵌套属性读写、属性描述符、字典填充/导出等能力。
> 框架版本：SpringBootAI 2.1.0

---

## 大白话开篇：BeanUtils 是什么？

**BeanUtils 就是帮你把对象 A 的属性值复制到对象 B**。

比如你有一个"用户输入"对象（UserDTO）和一个"数据库实体"对象（UserEntity），它们的字段名都一样（name、age、email），你想把 UserDTO 的值搬到 UserEntity 里去。不用 BeanUtils 你得写：

```python
entity.name = dto.name
entity.age = dto.age
entity.email = dto.email
entity.password_hash = entity.password_hash  # 这个字段不覆盖
```

用 BeanUtils 你只需要一行：

```python
BeanUtils.copy_properties(dto, entity, ignore=["password_hash"])
# 结果: entity 的 name/age/email 被更新，password_hash 保持不变
```

### 决策指引：我该用 BeanUtils 吗？

| 场景 | 该用吗 | 原因 |
|------|--------|------|
| DTO → Entity 转换（字段名相同） | ✅ 用 | 减少重复赋值代码 |
| Entity → 响应对象 | ✅ 用 | 快速构造返回数据 |
| 把配置字典填入对象 | ✅ 用 `populate()` | 一行代码搞定 |
| 把对象导出为字典 | ✅ 用 `describe()` | 方便序列化 |
| 需要类型转换（如字符串 "123" → 整数 123） | ❌ 手动处理 | BeanUtils 不做类型转换，原样赋值 |
| 列表/字典对象需要完全复制（不影响原对象） | ⚠️ 用 `copy_deep=True` | 默认浅拷贝共享引用 |
| 字段名不同的两个对象 | ❌ 不行 | BeanUtils 按**字段名**匹配，名字不同不复制 |

---

## 一、快速开始

```python
from spring.utils import BeanUtils

class UserSrc:
    def __init__(self):
        self.name = "alice"
        self.age = 30
        self.address = {"city": "北京", "zip": "100000"}

class UserTgt:
    def __init__(self):
        self.name = ""
        self.age = 0
        self.address = None

src = UserSrc()
tgt = UserTgt()
BeanUtils.copy_properties(src, tgt)
assert tgt.name == "alice" and tgt.age == 30
# 结果: tgt.name = "alice", tgt.age = 30, tgt.address = {"city": "北京", "zip": "100000"}
```

---

## 二、浅拷贝 vs 深拷贝（重要！）

> **生活比喻**：浅拷贝就像复印了一份文档目录（目录是新的，但指的还是同一个文件柜）；深拷贝就像把文件柜里的每一个文件都复印了一份，两份完全独立。

```python
# 浅拷贝（默认）：address 共享同一个 dict 对象
BeanUtils.copy_properties(src, tgt)
tgt.address["city"] = "上海"
print(src.address["city"])
# 输出: 上海  ← ⚠️ 修改 tgt 竟然影响了 src！因为两个对象共用同一个 dict

# 深拷贝：address 是独立的新 dict
BeanUtils.copy_properties(src, tgt, copy_deep=True)
tgt.address["city"] = "上海"
print(src.address["city"])
# 输出: 北京  ← ✅ 修改 tgt 不影响 src
```

---

## 三、API 参考

### 1. `copy_properties(source, target, ignore=None, copy_deep=False)`

对齐 Spring `BeanUtils.copyProperties`。将源对象同名可读属性复制到目标对象。

| 参数 | 类型 | 说明 |
|------|------|------|
| `source` | Any | 源对象（`None` 时直接返回） |
| `target` | Any | 目标对象（`None` 时直接返回） |
| `ignore` | Iterable[str] | 忽略的属性名集合（对齐 Java `ignoreProperties`） |
| `copy_deep` | bool | 是否深拷贝属性值，默认 `False`（浅拷贝，与 Spring 一致） |

**规则**：
- 仅复制源对象存在且可读的属性；目标只读 property（无 setter）自动跳过。
- 双下划线属性（`__xxx`）与方法（callable）自动排除；单下划线私有属性默认参与复制。
- 目标 `setattr` 失败（Pydantic frozen / slots 限制）时跳过，不抛异常。

```python
BeanUtils.copy_properties(src, tgt, ignore=["age", "address"])
# 结果: 只复制非 age、非 address 的属性

BeanUtils.copy_properties(src, tgt, copy_deep=True)
# 结果: 嵌套对象完全独立，修改 tgt 不影响 src
```

### 2. `copy_property(source, target, property_name) -> bool`

对齐 Spring `BeanUtils.copyProperty`。复制单个属性，返回是否成功。

```python
ok = BeanUtils.copy_property(src, tgt, "name")
# 结果: tgt.name = src.name，ok = True（成功）
# 如果 property_name 不存在，ok = False
```

### 3. `clone(source, deep=False) -> Any`

对齐 Apache Commons `BeanUtils.cloneBean`。通过 `type(source).__new__` 创建同类型新对象并复制属性。

```python
new_user = BeanUtils.clone(src)            # 浅克隆（嵌套对象共享引用）
new_user = BeanUtils.clone(src, deep=True) # 深克隆（嵌套对象完全独立）
# 结果: new_user 是 src 的同类型新对象，属性值相同
```

### 4. `get_property(obj, name, default=None) -> Any`

对齐 Apache Commons `BeanUtils.getProperty`。支持点号嵌套路径，支持 Mapping（dict）。

```python
BeanUtils.get_property(user, "address.city")
# 输出: "北京"（读取 user.address.city）
# 过程: 先读 user.address，再读 address.city

BeanUtils.get_property(user, "address.city", "N/A")
# 输出: "N/A"（路径中断时返回默认值，不会抛异常）

BeanUtils.get_property({"a": {"b": 1}}, "a.b")
# 输出: 1（dict 也支持点号嵌套读取）
```

### 5. `set_property(obj, name, value) -> bool`

对齐 Apache Commons `BeanUtils.setProperty`。支持嵌套路径与 Mapping。中间节点为 `None` 时返回 `False`。

```python
BeanUtils.set_property(user, "address.city", "上海")
# 结果: user.address.city = "上海"，返回 True

BeanUtils.set_property({"a": {"b": 1}}, "a.b", 2)
# 结果: {"a": {"b": 2}}，返回 True
```

### 6. `get_simple_property(obj, name, default=None) -> Any`

对齐 Apache Commons `getSimpleProperty`。不支持嵌套，直接 `getattr`。

```python
BeanUtils.get_simple_property(user, "name")
# 输出: "alice"（等同于 user.name）

BeanUtils.get_simple_property(user, "nonexistent", "默认值")
# 输出: "默认值"
```

### 7. `get_property_descriptors(obj) -> Dict[str, Optional[type]]`

对齐 Spring `BeanUtils.getPropertyDescriptors`。返回属性名 → 值类型的映射。

```python
desc = BeanUtils.get_property_descriptors(user)
# 输出: {"name": str, "age": int, "address": dict, ...}
```

### 8. `get_property_descriptor(obj, name) -> Optional[type]`

对齐 Spring `BeanUtils.getPropertyDescriptor`。返回单个属性的类型。

```python
t = BeanUtils.get_property_descriptor(user, "age")
# 输出: int（如果属性不存在返回 None）
```

### 9. `populate(obj, properties) -> None`

对齐 Apache Commons `BeanUtils.populate`。用字典批量设置属性，不可写的属性自动跳过。

```python
BeanUtils.populate(tgt, {"name": "bob", "age": 25})
# 结果: tgt.name = "bob", tgt.age = 25
```

### 10. `describe(obj) -> Dict[str, Any]`

对齐 Apache Commons `BeanUtils.describe`。将对象可读属性导出为字典（含 property getter 返回值）。

```python
d = BeanUtils.describe(user)
# 输出: {"name": "alice", "age": 30, "address": {...}, ...}
```

---

## 四、使用示例

### 示例 1：DTO ↔ Entity 转换

```python
from spring.utils import BeanUtils
from dataclasses import dataclass

@dataclass
class UserDTO:
    name: str = ""
    age: int = 0
    email: str = ""

class UserEntity:
    def __init__(self):
        self.name = ""
        self.age = 0
        self.email = ""
        self.password_hash = ""  # 实体独有，DTO 无

dto = UserDTO(name="alice", age=30, email="a@b.com")
entity = UserEntity()
entity.password_hash = "xxx"

BeanUtils.copy_properties(dto, entity)
# 结果: entity.name="alice", entity.age=30, entity.email="a@b.com", entity.password_hash 保持 "xxx"
```

### 示例 2：嵌套属性读写

```python
class Address:
    def __init__(self, city=""):
        self.city = city

class User:
    def __init__(self):
        self.address = Address("北京")

user = User()
assert BeanUtils.get_property(user, "address.city") == "北京"
# 输出: True（读取成功）

BeanUtils.set_property(user, "address.city", "上海")
assert user.address.city == "上海"
# 输出: True（写入成功）
```

### 示例 3：字典填充与导出

```python
class Config:
    def __init__(self):
        self.host = ""
        self.port = 0

cfg = Config()
BeanUtils.populate(cfg, {"host": "0.0.0.0", "port": 8080})
assert cfg.host == "0.0.0.0" and cfg.port == 8080
# 输出: True（一行代码批量设置属性）

d = BeanUtils.describe(cfg)
assert d == {"host": "0.0.0.0", "port": 8080}
# 输出: True（导出为字典）
```

### 示例 4：Pydantic Model 复制

```python
from pydantic import BaseModel
from spring.utils import BeanUtils

class UserIn(BaseModel):
    name: str = ""
    age: int = 0

class UserOut(BaseModel):
    name: str = ""
    age: int = 0

src = UserIn(name="bob", age=25)
tgt = UserOut()
BeanUtils.copy_properties(src, tgt)
assert tgt.name == "bob" and tgt.age == 25
# 输出: True（支持 Pydantic v2 Model）
```

---

## 五、与 Java Spring BeanUtils 的差异

| 维度 | Java Spring BeanUtils | SpringBootAI BeanUtils |
|------|----------------------|----------------------|
| 类型转换 | 通过 PropertyEditor/ConversionService 自动转换 | Python 动态类型，原样赋值，不做转换 |
| 底层机制 | Java 反射（java.beans.Introspector） | `__dict__` / `getattr` / `setattr` + 类层 property |
| 支持对象 | JavaBean | 普通类 / dataclass / Pydantic v2 Model / ORM entity |
| 拷贝语义 | 浅拷贝 | 默认浅拷贝，`copy_deep=True` 支持深拷贝 |
| 监听机制 | PropertyChangeListener / VetoableChangeListener | 不支持 |
| 私有属性 | 受访问权限控制 | 单下划线默认复制，双下划线排除 |

---

## 六、新手常见误区

| 误区 | 真相 |
|------|------|
| "复制后修改目标对象不影响源对象" | **默认是浅拷贝**！如果属性值是列表/字典/对象，两个对象共享同一个引用。要完全独立用 `copy_deep=True` |
| "BeanUtils 会自动转换类型" | Python 版不做类型转换。Java 版会通过 `ConversionService` 自动转，Python 版是原样赋值 |
| "密码等敏感字段复制了也没关系" | 从请求 DTO 复制到数据库实体时，请把 `password_hash`、`salt` 等敏感字段放入 `ignore`，防止被覆盖 |
| "所有同名字段都会被复制" | 双下划线字段 `__xxx` 和 callable（方法）自动排除；目标只读 property 自动跳过 |
| "字段名不一样也能复制" | BeanUtils 按**字段名精确匹配**，名字不同就不复制。如果要映射不同名字段，需要人工处理 |
| "clone 创建的是完全独立的对象" | 默认 `clone()` 是浅克隆。要深克隆用 `clone(src, deep=True)` |

---

## 七、测试覆盖

测试文件：[`tests/test_bean_utils.py`](../tests/test_bean_utils.py) — **34 用例**，覆盖：

- 基本复制 / ignore 忽略 / 单下划线私有属性 / 方法与 dunder 排除 / 只读 property 跳过
- 浅拷贝 / 深拷贝 / None 源与目标
- dataclass / Pydantic v2 Model
- copy_property 单属性 / 缺失属性 / 只读目标
- clone 浅克隆 / 深克隆 / None
- 嵌套 get/set（对象 + Mapping）/ 中间 None / 简单 set
- get_simple_property / get_property_descriptors / get_property_descriptor
- populate / populate 跳过不可写 / None 与空字典
- describe / describe None
- 顶层导出（`spring.utils.BeanUtils` / `spring.utils.BeanUtils`）

---

## 八、代码位置

- 实现：[`spring/utils/bean_utils.py`](../spring/utils/bean_utils.py)
- 导出：[`spring/utils/__init__.py`](../spring/utils/__init__.py) → `from spring.utils import BeanUtils`
- 测试：[`tests/test_bean_utils.py`](../tests/test_bean_utils.py)
