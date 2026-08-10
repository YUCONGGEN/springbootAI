# SpringBootAI BeanUtils 工具指南

> 对齐 `org.springframework.beans.BeanUtils`（Spring）与 `org.apache.commons.beanutils.BeanUtils`（Apache Commons）。
> 提供对象间属性复制、嵌套属性读写、属性描述符、字典填充/导出等能力。
> 框架版本：SpringBootAI 1.8.4

---

## 零、新手先读

BeanUtils 用来复制“字段名相同”的对象属性，常见于 DTO 转 Entity、Entity 转响应对象，以及把配置字典填入对象。它能减少重复赋值代码，但不会替你做业务校验、权限过滤或复杂类型转换。

最容易出错的是浅拷贝：默认复制列表、字典等对象的引用，修改目标对象里的列表可能同时影响源对象。需要完全独立的数据时使用 `copy_deep=True` 或 `clone(..., deep=True)`。

密码哈希、内部权限、审计字段等敏感属性应放进 `ignore`，不能因为字段同名就无条件从请求 DTO 复制到数据库实体。

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
```

---

## 二、API 参考

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
BeanUtils.copy_properties(src, tgt, copy_deep=True)  # 嵌套对象独立
```

### 2. `copy_property(source, target, property_name) -> bool`

对齐 Spring `BeanUtils.copyProperty`。复制单个属性，返回是否成功。

```python
ok = BeanUtils.copy_property(src, tgt, "name")
```

### 3. `clone(source, deep=False) -> Any`

对齐 Apache Commons `BeanUtils.cloneBean`。通过 `type(source).__new__` 创建同类型新对象并复制属性。

```python
new_user = BeanUtils.clone(src)            # 浅克隆
new_user = BeanUtils.clone(src, deep=True) # 深克隆，嵌套对象独立
```

### 4. `get_property(obj, name, default=None) -> Any`

对齐 Apache Commons `BeanUtils.getProperty`。支持点号嵌套路径，支持 Mapping（dict）。

```python
BeanUtils.get_property(user, "address.city")          # 嵌套属性
BeanUtils.get_property(user, "address.city", "N/A")   # 路径中断返回默认值
BeanUtils.get_property({"a": {"b": 1}}, "a.b")        # dict 嵌套 → 1
```

### 5. `set_property(obj, name, value) -> bool`

对齐 Apache Commons `BeanUtils.setProperty`。支持嵌套路径与 Mapping。中间节点为 `None` 时返回 `False`。

```python
BeanUtils.set_property(user, "address.city", "上海")
BeanUtils.set_property({"a": {"b": 1}}, "a.b", 2)
```

### 6. `get_simple_property(obj, name, default=None) -> Any`

对齐 Apache Commons `getSimpleProperty`。不支持嵌套，直接 `getattr`。

### 7. `get_property_descriptors(obj) -> Dict[str, Optional[type]]`

对齐 Spring `BeanUtils.getPropertyDescriptors`。返回属性名 → 值类型的映射。

```python
desc = BeanUtils.get_property_descriptors(user)
# {"name": str, "age": int, "address": dict, ...}
```

### 8. `get_property_descriptor(obj, name) -> Optional[type]`

对齐 Spring `BeanUtils.getPropertyDescriptor`。返回单个属性的类型。

### 9. `populate(obj, properties) -> None`

对齐 Apache Commons `BeanUtils.populate`。用字典批量设置属性，不可写的属性自动跳过。

```python
BeanUtils.populate(tgt, {"name": "bob", "age": 25})
```

### 10. `describe(obj) -> Dict[str, Any]`

对齐 Apache Commons `BeanUtils.describe`。将对象可读属性导出为字典（含 property getter 返回值）。

```python
d = BeanUtils.describe(user)
# {"name": "alice", "age": 30, "address": {...}, ...}
```

---

## 三、与 Java Spring BeanUtils 的差异

| 维度 | Java Spring BeanUtils | SpringBootAI BeanUtils |
|------|----------------------|----------------------|
| 类型转换 | 通过 PropertyEditor/ConversionService 自动转换 | Python 动态类型，原样赋值，不做转换 |
| 底层机制 | Java 反射（java.beans.Introspector） | `__dict__` / `getattr` / `setattr` + 类层 property |
| 支持对象 | JavaBean | 普通类 / dataclass / Pydantic v2 Model / ORM entity |
| 拷贝语义 | 浅拷贝 | 默认浅拷贝，`copy_deep=True` 支持深拷贝 |
| 监听机制 | PropertyChangeListener / VetoableChangeListener | 不支持 |
| 私有属性 | 受访问权限控制 | 单下划线默认复制，双下划线排除 |

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
# entity.name="alice", entity.age=30, entity.email="a@b.com", entity.password_hash="xxx" 保留
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
BeanUtils.set_property(user, "address.city", "上海")
assert user.address.city == "上海"
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

d = BeanUtils.describe(cfg)
assert d == {"host": "0.0.0.0", "port": 8080}
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
```

---

## 五、测试覆盖

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

## 六、代码位置

- 实现：[`spring/utils/bean_utils.py`](../spring/utils/bean_utils.py)
- 导出：[`spring/utils/__init__.py`](../spring/utils/__init__.py) → `from spring.utils import BeanUtils`
- 测试：[`tests/test_bean_utils.py`](../tests/test_bean_utils.py)
