# SpringBootAI Excel 模块使用指南

> 注解驱动的 Excel 读写，对齐 alibaba EasyExcel，复用 SpringBootAI 框架既有注解范式。
> 模块版本：`spring.excel` 1.0.0 ｜ 框架版本：SpringBootAI 1.8.8

---

## 零、新手先读

Excel 模块用于在 Python 对象和 `.xlsx` 文件之间转换。常见场景包括导出报表、批量导入用户、生成财务模板。它处理的是文件，不会自动把数据写入数据库；读到对象后仍应先校验，再由 Service 保存。

使用前安装依赖：

```powershell
python -m pip install "springbootAI[excel]"
```

最短使用流程是：

1. 用 `ExcelProperty` 声明“哪个属性对应哪一列表头”。
2. 用 `@excel_sheet` 设置工作表名称。
3. `write_excel()` 导出对象列表，或 `read_excel()` 读取成对象列表。
4. 打开生成文件检查表头、日期、金额和长数字。

Excel 与 CSV 的选择：Excel 支持工作表和样式，适合给人查看；CSV 更轻量，适合系统交换和大批量纯文本数据。读取用户上传的 Excel 时要限制文件大小、行数和扩展名，不要直接信任单元格内容。

读完本文后应能完成两个验证：导出一个包含中文和日期的文件；再把它读回来，确认字段类型和原值一致。

## 一、模块概述

`spring.excel` 是 SpringBootAI 框架的可选模块，提供 **注解驱动** 的 Excel 读写能力，API 与
[alibaba EasyExcel](https://github.com/alibaba/easyexcel) 对齐，让"实体类 ↔ Excel"的映射像 ORM 一样声明式完成。

**设计原则：复用项目既有范式，不重复造轮子。** 字段级注解完全镜像 ORM 层
[`spring/orm/ddl_auto.py`](file:///e:/python_springboot_AI/spring/orm/ddl_auto.py) 的 `Column` / `Id` / `@entity`
元数据描述符范式，类级 `@excel_sheet` 镜像 `@entity`。这意味着：

- 字段级：`ExcelProperty` / `ExcelIgnore` 作为类属性标记或函数装饰器，元数据通过 `cls.__dict__` + MRO 反射读取（与 `Column`/`__column__` 一致）。
- 类级：`@excel_sheet` 装饰器在类上设置 `__excel_sheet__`（与 `@entity` 设置 `__entity__`/`__table__` 一致）。

**注解声明不依赖任何第三方库**；仅 `read` / `write` 实际执行时检测 `openpyxl`，未安装抛 `ExcelDependencyError` 并提示安装。

### 模块组成

| 文件 | 职责 |
|------|------|
| [`annotations.py`](file:///e:/python_springboot_AI/spring/excel/annotations.py) | `@ExcelProperty` / `@ExcelIgnore` / `@excel_sheet` 字段+类级注解，列模型解析 |
| [`converters.py`](file:///e:/python_springboot_AI/spring/excel/converters.py) | `Converter` 接口 + 内置 int/float/bool/str/date/Decimal 转换器，按类型自动选择 |
| [`reader.py`](file:///e:/python_springboot_AI/spring/excel/reader.py) | `ExcelReader` 读取引擎（表头映射/类型转换/多 sheet/head_row_number） |
| [`writer.py`](file:///e:/python_springboot_AI/spring/excel/writer.py) | `ExcelWriter` 写入引擎（表头/顺序/样式/大数字防丢精度/多 sheet） |
| [`easy_excel.py`](file:///e:/python_springboot_AI/spring/excel/easy_excel.py) | `EasyExcel` 流式构建入口（对齐 alibaba EasyExcel API） |
| [`style.py`](file:///e:/python_springboot_AI/spring/excel/style.py) | 默认表头/内容样式 |
| [`exceptions.py`](file:///e:/python_springboot_AI/spring/excel/exceptions.py) | `ExcelError` 异常族 |

---

## 二、安装

Excel 引擎是**可选依赖**，按需安装（不安装不影响框架核心与注解声明）：

```bash
pip install springbootAI[excel]      # 推荐：经 extras 安装，自动装 openpyxl==3.1.5
# 或
pip install -r requirements-excel.txt
# 或
pip install openpyxl==3.1.5
```

> 同时，本次发布还为 **AI 模块**补齐了单独安装能力：`pip install springbootAI[ai]`。
> 一键全量安装：`pip install springbootAI[full]`。

---

## 三、注解参考

### 3.1 `@ExcelProperty`（字段级）

声明实体字段与 Excel 列的映射。支持两种形式（与 ORM `Column` 一致）：

```python
# 形式 1：类属性描述符（推荐）
class Demo:
    name = ExcelProperty("姓名", order=2, width=12)

# 形式 2：函数装饰器（镜像 @column）
class Demo:
    @ExcelProperty("姓名", order=2)
    def name(self): ...
```

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `value` | str | `""` | 列标题（表头文案）。为空时按字段名自动转标题。 |
| `order` | int | `0` | 列顺序，越小越靠前；同 order 按 MRO 声明顺序。 |
| `index` | int | `None` | 绝对列索引（0 起），设置后覆盖 `order`。 |
| `converter` | Converter/类 | `None` | 自定义转换器。未设置时按字段类型注解自动选择。 |
| `format` | str | `None` | 通用格式占位（同时作 date_format/num_format 默认）。 |
| `date_format` | str | `None` | 日期格式串，如 `%Y-%m-%d`。读时解析、写时格式化为字符串。 |
| `num_format` | str | `None` | Excel 数字格式串，如 `#,##0.00`。写时应用到数值单元格。 |
| `width` | float | `0` | 列宽（字符数）。0 表示自适应。 |
| `big_number` | bool | `False` | 是否按字符串写入，避免 Excel 精度丢失（长 ID/大数）。 |
| `head_style` | str | `None` | 自定义表头样式名。 |
| `content_style` | str | `None` | 自定义内容样式名。 |
| `ignore` | bool | `False` | 等价 `@ExcelIgnore` 的快捷开关。 |

### 3.2 `@ExcelIgnore`（字段级）

标记字段在读写时跳过。用法与 `ExcelProperty` 一致：

```python
class Demo:
    remark = ExcelIgnore()
    # 或
    @ExcelIgnore()
    def remark(self): ...
```

### 3.3 `@excel_sheet`（类级）

声明实体类对应的 Excel 工作表配置（镜像 `@entity`）：

```python
@excel_sheet("用户列表", head_row_number=1, freeze_head=True, auto_width=True)
class DemoData:
    id = ExcelProperty("ID", order=1)
    ...
```

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `sheet_name` | str | `""` | 工作表名称。空时写用 `Sheet1`，读按索引。 |
| `head_row_number` | int | `1` | 表头所在行号（1 起）。数据从该行之后开始。 |
| `freeze_head` | bool | `True` | 是否冻结表头行（写时生效）。 |
| `auto_width` | bool | `True` | 是否自适应列宽。字段 `width>0` 时以字段为准。 |
| `head_style` / `content_style` | str | `None` | 默认样式名。 |

---

## 四、快速上手

### 4.1 定义实体

```python
from datetime import datetime
from decimal import Decimal
from spring.excel import ExcelProperty, ExcelIgnore, excel_sheet, BigDecimalConverter

@excel_sheet("用户列表")
class DemoUser:
    id = ExcelProperty("ID", order=1, big_number=True)        # 长ID防丢精度
    name = ExcelProperty("姓名", order=2, width=12)
    age = ExcelProperty("年龄", order=3)
    amount = ExcelProperty("金额", order=4, converter=BigDecimalConverter)
    created_at = ExcelProperty("创建时间", order=5, date_format="%Y-%m-%d %H:%M:%S")
    active = ExcelProperty("是否启用", order=6)
    remark = ExcelIgnore()                                     # 跳过不导出

    def __init__(self, id=None, name=None, age=None, amount=None,
                 created_at=None, active=None, remark=None):
        self.id = id; self.name = name; self.age = age
        self.amount = amount; self.created_at = created_at
        self.active = active; self.remark = remark
```

### 4.2 写入

```python
from spring.excel import EasyExcel

data = [
    DemoUser(76543210987654321, "张三", 28, Decimal("123.45"),
             datetime(2026, 8, 9, 12, 0, 0), True, "内部备注"),
    DemoUser(2, "李四", 35, Decimal("999.00"),
             datetime(2026, 1, 2, 3, 4, 5), False, "外部备注"),
]

EasyExcel.write("users.xlsx", head=DemoUser).sheet("用户列表").doWrite(data)
```

### 4.3 读取

```python
rows = (EasyExcel.read("users.xlsx", head=DemoUser)
        .head_row_number(1)
        .sheet(sheet_no=0)
        .doRead())
# rows: List[DemoUser] —— 字段已按类型转换：amount=Decimal, created_at=datetime
```

### 4.4 便捷函数（一步到位）

```python
from spring.excel import read_excel, write_excel

write_excel("users.xlsx", DemoUser, data)
rows = read_excel("users.xlsx", DemoUser)
```

### 4.5 多 sheet

```python
# 写多 sheet
EasyExcel.write("multi.xlsx", head=DemoUser).doWriteAll({"S1": data1, "S2": data2})

# 读所有 sheet -> {sheet_name: [实体列表]}
sheets = EasyExcel.read("multi.xlsx", head=DemoUser).doReadAll()

# 按名称/索引读单 sheet
EasyExcel.read("multi.xlsx", head=DemoUser).sheet(sheet_name="S2").doRead()
EasyExcel.read("multi.xlsx", head=DemoUser).sheet(sheet_no=0).doRead()
```

---

## 五、功能特性

| 特性 | 说明 |
|------|------|
| **注解映射** | `@ExcelProperty` 声明列标题/顺序/格式/转换器；`@ExcelIgnore` 跳过字段。 |
| **自动表头** | 无注解的纯 `__init__` 模型（如 `example_all/models/User.py`）自动按字段名生成表头、按位置映射。 |
| **类型转换** | 内置 int/float/bool/str/date/Decimal 转换器，按 `__init__` 类型注解自动选择；支持 `Optional[T]`。 |
| **自定义转换器** | 实现 `Converter.to_excel` / `from_excel` 即可，通过 `converter=` 注入。 |
| **大数字防丢精度** | `big_number=True` 或 >15 位整数自动按字符串写入，避免 Excel 截断到 15 位有效数字。 |
| **多 sheet 读写** | `doWriteAll` / `doReadAll` / `sheet(sheet_name=..., sheet_no=...)`。 |
| **表头行可配置** | `head_row_number` 支持表头不在第 1 行（前置说明行场景）。 |
| **样式** | 默认表头加粗居中+填充+边框、冻结表头、自适应列宽；支持 `width`/`num_format`。 |
| **流式 API** | `EasyExcel.read(...).head_row_number(...).sheet(...).doRead()`，对齐 alibaba EasyExcel。 |
| **可选依赖降级** | 注解声明无需 openpyxl；未安装时 read/write 抛 `ExcelDependencyError` 提示 `pip install springbootAI[excel]`。 |

---

## 六、与 Java EasyExcel 的差异与限制

| 维度 | Java EasyExcel | SpringBootAI Excel | 说明 |
|------|----------------|----------------|------|
| 注解载体 | Java 注解（编译期） | Python 描述符/装饰符（运行时反射） | 复用 ORM `Column` 范式，无原生注解。 |
| 字段声明 | 反射字段 | 类属性标记或 `__init__` 参数 | 无类属性时自动回退到 `__init__` 参数。 |
| 图片导出 | 支持 | **不支持** | 仅做表格数据读写，不处理图片。 |
| SAX 流式读取 | 支持（超大文件） | **不支持** | 基于 openpyxl 全量加载，适合常规体量；超大文件建议分片。 |
| 模板填充 | 支持 | **不支持** | 后续可扩展。 |
| 监听器（ReadListener） | 支持 | **不支持** | 当前返回完整列表；如需流式可后续扩展 listener 模式。 |

---

## 七、与 SpringBootAI 框架的集成

- **注解范式一致**：Excel 注解与 ORM `@entity`/`@Column` 同属"映射元数据"族，复用 `cls.__dict__` + MRO 反射，不侵入 DI/AOP 注解通道（`__spring_annotations__`）。
- **可选安装**：通过 `pyproject.toml` 的 `[project.optional-dependencies]` extras 单独安装，`spring.excel` 不在 `spring/__init__.py` 顶层导出，保持核心包轻量。
- **可与 Web 层联动**：在 `@RestController` 中用 `EasyExcel.write(...).doWrite(...)` 生成临时文件后返回文件下载响应；或读取上传的 xlsx 解析为实体列表入库。

---

## 八、测试

测试套件：[`tests/test_excel_module.py`](file:///e:/python_springboot_AI/tests/test_excel_module.py)，**42 个用例全部通过**（pytest，Python 3.11.9 + openpyxl 3.1.5）。

覆盖范围：

- **注解与元数据解析（11 用例）**：`@ExcelProperty` 元数据、表头解析、`@ExcelIgnore`、`@excel_sheet` 类配置、列排序（order/index）、无注解回退、函数装饰器形式、全忽略抛错。
- **转换器（11 用例）**：int/float/bool/str/date/Decimal 双向转换、按类型自动选择、`Optional[T]`、显式覆盖、日期格式注入、自定义转换器 round-trip。
- **读写 round-trip（7 用例）**：完整写读、大数字字符串保留 17 位、`@ExcelIgnore` 字段跳过、表头顺序、纯 `__init__` 模型回退、便捷函数、空行跳过。
- **多 sheet（4 用例）**：写多 sheet、按名称/索引读、不存在 sheet 抛错。
- **配置与降级（6 用例）**：表头非首行、流式构建器返回 self、无 head 抛错、openpyxl 缺失抛 `ExcelDependencyError`、注解无需 openpyxl。
- **样式与格式（3 用例）**：冻结表头+表头加粗、`num_format` 应用、自定义列宽。

运行：

```bash
pip install springbootAI[excel]      # 或 pip install openpyxl==3.1.5
pytest tests/test_excel_module.py -v
```

---

## 九、API 速查

```python
from spring.excel import (
    # 注解
    ExcelProperty, ExcelIgnore, excel_sheet, ExcelSheet,
    # 转换器
    Converter, StringConverter, IntegerConverter, FloatConverter,
    BooleanConverter, DateStringConverter, BigDecimalConverter,
    # 引擎
    EasyExcel, ExcelReader, ExcelWriter, read_excel, write_excel,
    # 异常
    ExcelError, ExcelPropertyError, ExcelReadError, ExcelWriteError, ExcelDependencyError,
)

EasyExcel.read(source, head=Cls).head_row_number(n).sheet(sheet_no=0, sheet_name="S").doRead()
EasyExcel.read(source, head=Cls).doReadAll()                                   # -> {sheet: [obj]}
EasyExcel.write(target, head=Cls).sheet("S").doWrite(data_list)
EasyExcel.write(target, head=Cls).doWriteAll({"S1": list1, "S2": list2})

read_excel(source, Cls)          # 便捷读
write_excel(target, Cls, data)   # 便捷写
```
