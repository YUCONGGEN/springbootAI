# SpringPy CSV 模块使用文档

> 版本：SpringPy CSV 1.0.0 ｜ 框架版本：SpringPy 1.7.0
> 对齐 alibaba EasyExcel / commons-csv 的注解驱动 CSV 读写，**无可选依赖**（Python 标准库 `csv`），`pip install springpy` 即可用。
> 设计原则：**复用项目既有范式，不重复造轮子**——注解描述符、反射解析、转换器、流式 API 全部对齐既有 Excel/ORM 实现。

---

## 一、模块组成

| 文件 | 职责 |
|------|------|
| `spring/csv/annotations.py` | `@CsvProperty` / `@CsvIgnore` / `@csv_file` 字段+类级注解，`parse_csv_columns` 反射解析（镜像 Excel `parse_excel_columns` / ORM `_parse_entity`） |
| `spring/csv/converters.py` | 复用 `spring.excel.converters` 的 `Converter` 接口与内置转换器（int/float/bool/str/date/Decimal），提供 `CsvConverter` 别名基类 |
| `spring/csv/reader.py` | `CsvReader` 读取引擎（表头映射 / 位置匹配 / 类型转换 / 跳空行） |
| `spring/csv/writer.py` | `CsvWriter` 写入引擎（表头 / 顺序 / 大数字防丢精度 / date_format） |
| `spring/csv/easy_csv.py` | `EasyCsv` 流式构建入口 + `read_csv` / `write_csv` 便捷函数（对齐 `EasyExcel`） |
| `spring/csv/exceptions.py` | `CsvError` 异常族（`CsvPropertyError` / `CsvReadError` / `CsvWriteError`） |

与 Excel 模块的核心区别：CSV 使用标准库 `csv`，**无 openpyxl 依赖**；无单元格样式/数字格式（CSV 格式本身不支持）；转换器复用 Excel 模块（`spring.excel.converters` 不依赖 openpyxl，可安全导入）。

---

## 二、快速上手

### 2.1 定义实体

两种字段声明形式（与 `Column` / `ExcelProperty` 一致）：

```python
from spring.csv import CsvProperty, CsvIgnore, csv_file

@csv_file("用户列表", delimiter=",", encoding="utf-8-sig")
class User:
    id = CsvProperty("ID", order=1)
    name = CsvProperty("姓名", order=2)
    age = CsvProperty("年龄", order=3)
    remark = CsvIgnore()          # 瞬态：不参与读写

    def __init__(self, id: int = None, name: str = None, age: int = None, remark: str = None):
        self.id = id; self.name = name; self.age = age; self.remark = remark
```

函数装饰器形式：

```python
@csv_file("demo")
class Demo:
    @CsvProperty("姓名", order=2)
    def name(self): ...
    # ...（需在 __init__ 中赋值才参与解析回退）
```

### 2.2 写入

```python
from spring.csv import EasyCsv, write_csv

data = [User(id=1, name="Tom", age=18), User(id=2, name="Jerry", age=20)]

# 流式
EasyCsv.write("/tmp/users.csv", head=User).doWrite(data)

# 便捷函数
write_csv("/tmp/users.csv", User, data)
```

### 2.3 读取

```python
from spring.csv import EasyCsv, read_csv

# 流式
rows = (EasyCsv.read("/tmp/users.csv", head=User)
        .has_header(True)
        .delimiter(",")
        .doRead())

# 便捷函数
rows = read_csv("/tmp/users.csv", User)
```

---

## 三、注解详解

### @CsvProperty

| 参数 | 默认 | 说明 |
|------|------|------|
| `value` | `""` | 列标题（表头文案）。为空时用字段名转标题（`user_name` → `User Name`） |
| `order` | `0` | 列顺序，越小越靠前；同 order 按 MRO 声明顺序 |
| `index` | `None` | 绝对列索引（从 0 起），设置后覆盖 `order` |
| `converter` | `None` | 自定义转换器（`Converter` 子类或实例）。默认按 `__init__` 类型注解自动选 |
| `format` | `None` | 通用格式占位（同时作 `date_format` 默认） |
| `date_format` | `None` | 日期格式串，如 `%Y-%m-%d`。读时解析，写时格式化 |
| `big_number` | `False` | 强制按字符串写入（避免长 ID 被解析回 int 后再写丢精度） |
| `ignore` | `False` | 内部等价 `@CsvIgnore` 的快捷开关 |

### @CsvIgnore

标记字段在读写时跳过（镜像 Excel `ExcelIgnore`）。支持类属性描述符与函数装饰器两种形式。

### @csv_file（类级）

| 参数 | 默认 | 说明 |
|------|------|------|
| `file_name` | `""` | 文件名（仅元数据，读写时由调用方传路径） |
| `has_header` | `True` | 是否含表头行 |
| `delimiter` | `,` | 字段分隔符 |
| `encoding` | `utf-8-sig` | 文件编码（带 BOM，兼容 Excel 打开中文 CSV） |
| `quote_char` | `"` | 引用字符 |
| `line_terminator` | `\r\n` | 行终止符 |

不使用本装饰器时，读写引擎使用默认配置。

---

## 四、列模型解析规则

`parse_csv_columns(cls)` 镜像 ORM `_parse_entity` / Excel `parse_excel_columns`：

1. 遍历 `cls.__mro__` 的 `__dict__`，收集 `CsvProperty` 实例或带 `__csv_property__` 的成员；遇到 `CsvIgnore` / `__csv_ignore__` 则跳过。子类覆盖父类同名字段。
2. 若类上没有任何 `CsvProperty` 标记，回退到 `__init__` 参数列表，按字段名自动生成表头（让未改造的纯 `__init__` 模型也能导入导出）。
3. 按 `index` → `order` → 声明顺序排序。
4. 全部被 `@CsvIgnore` 或无可导出字段时，抛 `CsvPropertyError`。

---

## 五、转换器

复用 `spring.excel.converters`（DRY），按 `__init__` 类型注解自动选择：

| Python 类型 | 转换器 | 读（from_excel） | 写（to_excel） |
|-------------|--------|------------------|----------------|
| `int` | `IntegerConverter` | `int(float(str))` 容错 | `int(value)` |
| `float` | `FloatConverter` | `float(str)` | `float(value)` |
| `bool` | `BooleanConverter` | 兼容 1/0、true/false、是/否、yes/no | `True`/`False` |
| `str` | `StringConverter` | `str` | `str` |
| `datetime` / `date` | `DateStringConverter` | 按 `date_format` 解析（兜底多格式） | 按 `date_format` 格式化 |
| `Decimal` | `BigDecimalConverter` | `Decimal(str)` | 原样字符串（防丢精度） |

自定义转换器：继承 `Converter` 实现 `to_excel` / `from_excel`，或继承 `CsvConverter` 用 `to_csv` / `from_csv` 别名。

```python
from spring.csv import Converter, CsvProperty

class TagsConverter(Converter):
    def to_excel(self, value):
        return ";".join(value) if value else ""
    def from_excel(self, cell_value):
        return str(cell_value).split(";") if cell_value else []

@csv_file("m")
class M:
    tags = CsvProperty("Tags", order=1, converter=TagsConverter())
    def __init__(self, tags=None): self.tags = tags
```

---

## 六、大数字防丢精度

CSV 本身即字符串，但若字段类型注解为 `int`，读取时会被 `IntegerConverter` 解析回 int，长 ID（>15 位）可能丢精度。两种防护：

1. 字段类型用 `Decimal`（自动用 `BigDecimalConverter` 以字符串读写）。
2. 设 `big_number=True` 强制按字符串写入。

```python
@csv_file("u")
class U:
    uid = CsvProperty("UID", order=1, big_number=True)
    def __init__(self, uid=None): self.uid = uid
# uid=12345678901234567890 -> 原样字符串写入，不丢精度
```

---

## 七、API 速查

### EasyCsv（流式入口）

| 方法 | 说明 |
|------|------|
| `EasyCsv.read(source, head=, has_header=, delimiter=, encoding=)` | 构建读取器 |
| `EasyCsv.write(target, head=, delimiter=, encoding=)` | 构建写入器 |

### CsvReader

| 方法 | 说明 |
|------|------|
| `.has_header(flag)` | 是否含表头 |
| `.delimiter(d)` | 分隔符 |
| `.encoding(enc)` | 编码 |
| `.doRead()` | 执行读取，返回实体列表 |

### CsvWriter

| 方法 | 说明 |
|------|------|
| `.delimiter(d)` / `.encoding(enc)` / `.has_header(flag)` | 流式配置 |
| `.doWrite(data)` | 执行写入，返回目标路径 |

### 便捷函数

- `read_csv(source, head, has_header=, delimiter=, encoding=)` → `list`
- `write_csv(target, head, data, delimiter=, encoding=)` → 目标路径

`source` / `target` 支持文件路径（str/Path）或类文件对象。

---

## 八、与 Java 的差异（已标注）

- **无样式/数字格式**：CSV 格式本身不支持单元格样式与数字格式，故无 `@ExcelProperty` 的 `num_format` / `style` 等价物；`date_format` 仅控制日期字符串的解析/格式化。
- **转换器方法名仍为 `to_excel` / `from_excel`**：与 Excel 模块共享同一实现（DRY），避免分叉。`CsvConverter` 提供 `to_csv` / `from_csv` 语义别名。
- **无可选依赖**：CSV 使用 Python 标准库 `csv`，无需 `pip install springpy[excel]`；注解声明与读写均开箱即用。
- **列匹配**：有显式 `@CsvProperty` 且含表头时按表头文案匹配；无注解或无表头时按列位置匹配（与 EasyExcel 一致）。

---

## 九、测试

测试套件：`tests/test_csv_module.py`（46 用例），覆盖注解元数据 / 列模型解析 / 转换器 / CsvReader / CsvWriter / round-trip / EasyCsv 流式。详见 [TEST_REPORT.md](TEST_REPORT.md) 第 TOP5 节。
