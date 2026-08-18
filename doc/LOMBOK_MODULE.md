# Lombok 风格模型注解

`springbootai.annotations` 提供四个装饰器，让 Python 领域模型保持简洁，同时不隐藏运行时行为。
它们会在被装饰的类上生成普通方法，因此生成结果依然易于检查、扩展和调试。

```python
from springbootai.annotations import Data
from springbootai.orm import Entity, Id, Required


@Data
@Entity("users")
class User:
    id: int = Id()
    username: str = Required(length=50)
    email: str


user = User(id=1, username="alice")
user.set_username("alice-2")
print(user.get_username())  # alice-2
print(user)                 # User(id=1, username='alice-2', email=None)
```

## `@Data`

`@Data` 是实体类和 DTO 类的一站式选项。它会生成：

- 为声明的公共字段生成 `get_<字段名>()` 方法；
- 链式调用的 `set_<字段名>(value)` 方法，每个方法返回 `self`；
- 可读的 `__str__` 和 `__repr__`，格式为 `Class(field=value)`；
- 当类未定义时，生成基于值的 `__eq__` 方法；
- 当不存在构造函数时，生成仅关键字参数的 `__init__(**values)`。

生成的构造函数接受来自类型注解的字段，应用普通默认值，并遵循 ORM 列（如
`Id`、`Required`、`Text`）提供的 `.default` 值。未知关键字参数会抛出 `TypeError`。

`@Data` 支持两种 ORM 装饰器顺序。当 `@Entity` 在内部时，保留 ORM 的构造函数。
当 `@Data` 在内部时，其生成的构造函数会被 `@Entity` 保留。

```python
@Data
@Entity("projects")
class Project:
    id: int = Id()
    name: str = Required()
```

## `@Get` 和 `@Set`

当模型需要暴露访问器但不需要 `@Data` 的全部功能时，使用这两个装饰器。
不传参数时，它们覆盖所有声明的公共字段。传入字段名或列表可以只暴露子集。

```python
from springbootai.annotations import Get, Set


@Get(["id", "status"])
@Set("status")
class Job:
    id: int
    status: str
    internal_trace: str
```

上面的类会获得 `get_id`、`get_status` 和 `set_status`；不会为
`internal_trace` 暴露访问器。

## `@ToString`

`@ToString` 生成与 `@Data` 相同的可读表示形式，但不生成访问器、构造函数或相等比较。
使用 `exclude` 可以隐藏密码哈希或大型载荷等字段。

```python
from springbootai.annotations import ToString


@ToString(exclude=["password_hash"])
class Account:
    username: str
    password_hash: str
```

此时 `repr(Account(...))` 会包含 `username`，但不包含 `password_hash`。

## 显式声明的方法优先

装饰器永远不会替换类或父类上显式声明的方法。
这使得模型可以使用生成的访问器，同时自定义特定的 getter、setter、
`__str__`、`__repr__`、`__init__` 或 `__eq__`。

生成的 setter 仅执行赋值操作。请将验证逻辑放在已有的框架验证边界
（`@Valid`、`@Validated`、字段约束或服务层检查），而不是将便捷 setter
当作验证机制。

## 学习示例与查询

`examples/example_all/models/User.py` 包含两种推荐风格：

- `User` 使用 `@Data` 配合 `@Entity`，是常见的简洁实体形式。
- `Order` 分别组合 `@Get`、`@Set` 和 `@ToString`，让每个效果都清晰可见。

示例应用加载到模块路径后，可以通过实时目录定位这些用法：

```powershell
python -m example_all.feature_catalog Data
python -m example_all.feature_catalog ToString
```
