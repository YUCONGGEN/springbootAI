# SpringBootAI CSV 模块 —— 小白也能看懂的使用指南

> 模块随 SpringBootAI 2.3.2 发布
> CSV 模块基于 Python 标准库 `csv`，**零额外依赖**，`pip install springbootAI` 即可用。

---

## CSV vs Excel —— 什么时候用哪个？

| | CSV | Excel（.xlsx） |
|------|-----|-----------------|
| **像什么** | 📝 纯文本备忘录，记事本就能打开 | 📊 精美排版报告 |
| **打开方式** | 任何文本编辑器、Excel、WPS | Excel / WPS |
| **样式** | ❌ 不支持（纯文本） | ✅ 支持颜色、字体、边框、冻结 |
| **多个 Sheet** | ❌ 不支持，一个文件一张表 | ✅ 支持 |
| **文件大小** | 更小（纯文本，无格式开销） | 更大（带格式元数据） |
| **依赖** | Python 自带 `csv` 模块，零依赖 | 需要安装 `openpyxl` |
| **兼容性** | 任何系统、任何语言都能读 | 需要 Excel 或兼容软件 |
| **适合场景** | 系统间交换数据、大数据量导入导出 | 给人看的报表、需要样式的输出 |
| **中文兼容** | 需要指定编码（推荐 `utf-8-sig`） | 自动处理 |
| **防长数字丢失** | 天然不丢（纯文本） | 需要 `big_number=True` |

> **一句话决策**：两个系统之间传数据 → CSV；导出给老板看 → Excel。

---

## 用这个模块 vs 不用这个模块

| | 不用 CSV 模块（用标准库手写） | 用 CSV 模块 |
|---|---|---|
| **代码量** | 手动打开文件、读表头、逐行解析、类型转换…… | 定义类 + 一行 `write_csv()` |
| **列映射** | 手动对应"第几列是什么字段" | `@CsvProperty("姓名", order=1)` 贴个标签就行 |
| **类型转换** | 读回来全是字符串，手动 `int()`、`datetime.strptime()` | 框架自动按类型注解转换 |
| **中文乱码** | 需要自己加 BOM、处理编码 | 默认 `utf-8-sig`，Excel 打开不乱码 |

**举个例子**——读写 5000 条用户数据：

```python
# ❌ 不用 CSV 模块（手写 csv 标准库）
import csv
rows = []
with open("users.csv", "r", encoding="utf-8-sig") as f:
    reader = csv.reader(f)
    header = next(reader)  # 手动读表头
    for line in reader:
        # 手动创建对象、手动转类型
        rows.append({
            "id": int(line[0]),
            "name": line[1],
            "age": int(line[2]),
            "email": line[3],
        })
```

```python
# ✅ 用 CSV 模块（定义类 + 一行代码）
from springbootai.csv import read_csv

rows = read_csv("users.csv", UserCsv)
# rows: [UserCsv(id=1, name="张三", age=28, ...), ...]
# 字段已自动转换类型，age 是 int 不是字符串
```

---

## 第零章：CSV 是什么

### 先认识 CSV 文件

CSV（Comma-Separated Values，逗号分隔值）是最简单的表格格式——**每一行是一条记录，每列用逗号隔开**。用记事本就能打开：

```
ID,姓名,年龄,邮箱
1,张三,28,zhangsan@mail.com
2,李四,35,lisi@mail.com
```

- 形式上就是一个 `.csv` 后缀的纯文本文件
- 没有颜色、没有公式、没有多个 Sheet
- 就是"干净的数据"

### CSV 模块帮你做什么

把 Python 对象列表写入 CSV 文件，或者把 CSV 文件读成 Python 对象列表。它和 [Excel 模块](EXCEL_MODULE.md) 用法几乎一模一样，只是导入路径不同、功能更简单（没有样式、没有多 Sheet）。

---

## 第一章：使用前准备

### 1.1 安装

CSV 模块已包含在核心包中，无需额外安装：

```powershell
python -m pip install springbootAI
```

### 1.2 最短验证流程

1. 定义一个带 `@CsvProperty` 的类
2. 用 `write_csv()` 写出 CSV 文件
3. 用 `read_csv()` 读回来，确认字段值一致

> ⚠️ Windows Excel 打开中文 CSV 时容易乱码，推荐始终使用 `encoding="utf-8-sig"`（带 BOM 头，Excel 能识别）。

---

## 第二章：一个完整例子 —— 从零到导入导出 CSV

> **这章带你从零实现：定义实体 → 写入 CSV → 读回来验证。**

### 场景

把用户数据导出成 CSV 文件，供另一个系统消费。要求中文表头、类型自动转换、某个字段不导出。

### 第一步：定义实体类

> **@CsvProperty 是什么？** 给 Python 类属性贴标签，告诉框架"这个属性对应 CSV 文件的第几列、表头叫什么"。和 Excel 模块的 `@ExcelProperty` 一样的概念。  
> **@CsvIgnore 是什么？** 告诉框架"这一列跳过，不读也不写"。  
> **@CsvFile 是什么？** 设置 CSV 文件的全局配置——编码、分隔符、有没有表头行。

```python
# demo/csv_entity.py
from datetime import datetime
from springbootai.csv import CsvProperty, CsvIgnore, CsvFile


@CsvFile("用户列表", delimiter=",", encoding="utf-8-sig")
class UserCsv:
    # order=1：排在第 1 列
    id = CsvProperty("用户ID", order=1)

    # order=2：排在第 2 列
    name = CsvProperty("姓名", order=2)

    # order=3：排在第 3 列
    age = CsvProperty("年龄", order=3)

    # order=4：排在第 4 列
    email = CsvProperty("邮箱", order=4)

    # 这个字段不导入也不导出
    remark = CsvIgnore()

    def __init__(self, id: int = None, name: str = None, age: int = None,
                 email: str = None, remark: str = None):
        self.id = id
        self.name = name
        self.age = age
        self.email = email
        self.remark = remark
```

① `@CsvFile("用户列表", delimiter=",", encoding="utf-8-sig")`：文件名标注"用户列表"，用逗号分隔，编码带 BOM。  
② `@CsvProperty("用户ID", order=1)`：告诉框架第 1 列的表头是"用户ID"。  
③ `@CsvIgnore()`：`remark` 不参与读写。

### 第二步：写入 CSV

```python
# demo/write_csv_demo.py
from springbootai.csv import EasyCsv, write_csv
from demo.csv_entity import UserCsv

# 准备数据
data = [
    UserCsv(id=1, name="张三", age=28, email="zhangsan@mail.com"),
    UserCsv(id=2, name="李四", age=35, email="lisi@mail.com"),
]

# 方式1：流式 API（功能全）
EasyCsv.write("users.csv", head=UserCsv).doWrite(data)

# 方式2：便捷函数（代码最短）
write_csv("users2.csv", UserCsv, data)
```

③ 运行结果：生成的 `users.csv` 内容为：

```
用户ID,姓名,年龄,邮箱
1,张三,28,zhangsan@mail.com
2,李四,35,lisi@mail.com
```

### 第三步：读取 CSV

```python
# demo/read_csv_demo.py
from springbootai.csv import EasyCsv, read_csv
from demo.csv_entity import UserCsv

# 方式1：流式读取
rows = (EasyCsv.read("users.csv", head=UserCsv)
        .has_header(True)       # 文件有表头行
        .delimiter(",")         # 逗号分隔
        .doRead())

print(f"读取到 {len(rows)} 条记录")
# 输出: 读取到 2 条记录

for user in rows:
    print(f"  {user.name}, {user.age}岁, {user.email}")
# 输出:   张三, 28岁, zhangsan@mail.com
# 输出:   李四, 35岁, lisi@mail.com

# 验证类型是否自动转换
print(type(rows[0].age))   # 输出: <class 'int'>
print(type(rows[0].id))    # 输出: <class 'int'>
# age 和 id 读回来就是 int，不是字符串！

# 方式2：便捷函数（一步读回来）
rows2 = read_csv("users.csv", UserCsv)
# 结果: 同上，list[UserCsv]
```

---

## 第三章：和 Excel 模块的对比 —— 一份代码两种导出

如果你已经会用 Excel 模块，CSV 模块只需要改三行：

| Excel 模块 | CSV 模块 |
|----------|---------|
| `from springbootai.excel import ...` | `from springbootai.csv import ...` |
| `@ExcelProperty` | `@CsvProperty` |
| `@ExcelIgnore` | `@CsvIgnore` |
| `@ExcelSheet` | `@CsvFile` |
| `EasyExcel` | `EasyCsv` |
| `read_excel` / `write_excel` | `read_csv` / `write_csv` |

**迁移示例**——把 Excel 导出改成 CSV 导出：

```python
# Excel 版本
from springbootai.excel import ExcelProperty, ExcelIgnore, ExcelSheet

@ExcelSheet("用户列表")
class UserExcel:
    id = ExcelProperty("用户ID", order=1)
    name = ExcelProperty("姓名", order=2)
    remark = ExcelIgnore()
```

```python
# CSV 版本（只需改 3 行）
from springbootai.csv import CsvProperty, CsvIgnore, CsvFile

@CsvFile("用户列表", encoding="utf-8-sig")
class UserCsv:
    id = CsvProperty("用户ID", order=1)
    name = CsvProperty("姓名", order=2)
    remark = CsvIgnore()
```

---

## 第四章：大数字精度 —— CSV 需要担心吗？

### ① 是什么

CSV 本身就是纯文本，理论上不存在精度丢失。Excel 会把 `76543210987654321` 变成科学计数法，但 CSV 不会——它原原本本存的就是字符串 `"76543210987654321"`。

### ② 但有一个坑

如果你的字段类型注解是 `int`，CSV 模块读的时候会用 `IntegerConverter` 把它转成 Python `int`。对于 >15 位的数字，Python `int` 本身不会丢精度（Python 的 int 是任意精度），但这只在**纯 Python 环境**里保证。如果之后这个数字还要导出到 Excel，就会再遇到精度问题。

### ③ 怎么防护

两种方式：

```python
from decimal import Decimal
from springbootai.csv import CsvProperty, CsvFile

# 方式 1：用 big_number=True，强制按字符串读写
@CsvFile("data")
class Data1:
    uid = CsvProperty("UID", order=1, big_number=True)
    # uid=12345678901234567890 → 原样写入，原样读取
    def __init__(self, uid=None):
        self.uid = uid

# 方式 2：字段类型用 Decimal（自动用 BigDecimalConverter）
@CsvFile("data")
class Data2:
    uid = CsvProperty("UID", order=1)
    def __init__(self, uid: Decimal = None):
        self.uid = uid
```

---

## 第五章：自定义转换器

CSV 模块**复用 Excel 模块的转换器**（`springbootai.excel.converters`）。这意味着：
- 内置转换器（int/float/bool/str/date/Decimal）完全一样
- 自定义转换器写法也一样

| Python 类型 | 自动转换器 | 读回来 | 写出去 |
|-------------|-----------|--------|--------|
| `int` | `IntegerConverter` | `int` | `"28"` |
| `float` | `FloatConverter` | `float` | `"3.14"` |
| `bool` | `BooleanConverter` | `bool`（兼容"是"/"否"） | `"True"` / `"False"` |
| `str` | `StringConverter` | `str` | 原样字符 |
| `datetime`/`date` | `DateStringConverter` | `datetime` 对象 | 按 `date_format` 格式化 |
| `Decimal` | `BigDecimalConverter` | `Decimal` | 原样字符串 |

自定义转换器示例：

```python
from springbootai.csv import Converter, CsvProperty, CsvFile


# 自定义转换器：列表 ↔ 分号分隔的字符串
class TagsConverter(Converter):
    def to_excel(self, value):
        """写入 CSV 时：列表 → 字符串"""
        return ";".join(value) if value else ""
        # ["python", "java"] → "python;java"

    def from_excel(self, cell_value):
        """读取 CSV 时：字符串 → 列表"""
        return str(cell_value).split(";") if cell_value else []
        # "python;java" → ["python", "java"]


@CsvFile("文章")
class Article:
    title = CsvProperty("标题", order=1)
    tags = CsvProperty("标签", order=2, converter=TagsConverter())

    def __init__(self, title="", tags=None):
        self.title = title
        self.tags = tags
```

> 注意：自定义转换器的方法名还叫 `to_excel` / `from_excel`，因为 CSV 模块**直接复用** Excel 的转换器代码，没有单独实现。

---

## 第〇章：新手常见错误

> 刚开始用 CSV 模块最容易踩的坑。

### 错误 1："CSV 和 Excel 只是后缀不同"

❌ **错误想法**：把 `.csv` 后缀改成 `.xlsx` 就能当 Excel 用。

✅ **实际情况**：CSV 是纯文本，Excel 是二进制 zip 包。它们是**完全不同**的格式。CSV 没有样式、公式、多 Sheet。需要这些功能必须用 [Excel 模块](EXCEL_MODULE.md)。

---

### 错误 2："`utf-8` 和 `utf-8-sig` 没区别"

❌ **错误想法**：反正都是 UTF-8。

✅ **实际情况**：`utf-8-sig` 在文件开头加了一个 BOM（字节序标记 `\ufeff`），Windows Excel 看到 BOM 才知道这是 UTF-8 编码。没有 BOM 的话 Excel 按 ANSI 解码，中文就乱了。

```python
# ❌ 乱码风险
@CsvFile(encoding="utf-8")  # Windows Excel 打开可能乱码

# ✅ 推荐
@CsvFile(encoding="utf-8-sig")  # Windows Excel 能正确显示中文
```

---

### 错误 3："读 CSV 不需要关心编码"

❌ **错误想法**：编码是写文件的人才需要关心的事。

✅ **实际情况**：读文件时编码必须和写文件时一致。如果你用 `utf-8-sig` 写，就必须用 `utf-8-sig` 读。编码不匹配会导致乱码或读取失败。

```python
# ❌ 写入用 utf-8-sig，读取用 utf-8
write_csv("data.csv", User, data, encoding="utf-8-sig")
rows = read_csv("data.csv", User, encoding="utf-8")  # 编码不匹配！

# ✅ 读写编码一致
write_csv("data.csv", User, data, encoding="utf-8-sig")
rows = read_csv("data.csv", User, encoding="utf-8-sig")  # 一致
```

---

### 错误 4："CSV 读回来全是字符串"

❌ **错误想法**：CSV 是纯文本，读回来肯定都是 `str` 类型。

✅ **实际情况**：CSV 模块有转换器，会根据字段的**类型注解**自动转换。`age: int` 读回来就是 `int`，`created_at: datetime` 读回来就是 `datetime` 对象。不需要手动转。

```python
@CsvFile("data")
class User:
    age = CsvProperty("年龄", order=1)
    def __init__(self, age: int = 0):  # 类型注解 = int
        self.age = age

rows = read_csv("data.csv", User)
print(type(rows[0].age))  # 输出: <class 'int'> —— 自动转好了！
```

---

### 错误 5："CSV 只有逗号一种分隔符"

❌ **错误想法**：CSV 的 C 就是 Comma，只能是逗号。

✅ **实际情况**：实际项目中也常用 Tab（`\t`）、分号（`;`）、管道符（`|`）等。通过 `delimiter` 参数设置：

```python
# Tab 分隔的 CSV（也叫 TSV）
@CsvFile("data", delimiter="\t")
class Data:
    name = CsvProperty("姓名", order=1)
    ...

# 分号分隔
@CsvFile("data", delimiter=";")
class Data:
    ...
```

---

### 错误 6："CSV 模块的转换器和 Excel 模块是两套"

❌ **错误想法**：CSV 有自己的转换器实现。

✅ **实际情况**：CSV 模块**直接复用** Excel 的转换器（`springbootai.excel.converters`，这个模块不依赖 openpyxl）。所以方法名还叫 `to_excel` / `from_excel`——因为它们共享同一份代码。

---

## 常见报错和解决方法

### 报错 1：Excel 打开中文 CSV 乱码

**现象**：生成的 CSV 用 Windows Excel 打开，中文全是乱码。

**原因**：Excel 默认用 ANSI 编码打开 CSV，不认识 UTF-8。

**解决**：编码使用 `utf-8-sig`（带 BOM 标记，Excel 能识别）：

```python
@CsvFile(encoding="utf-8-sig")
class User:
    ...

# 或写入时指定
write_csv("users.csv", User, data, encoding="utf-8-sig")
```

---

### 报错 2：列数据对不上（姓名字段读到了年龄）

**现象**：读取 CSV 后，姓名变成了年龄的值。

**原因**：表头匹配失败（有空格、全角/半角差异），框架按**位置**匹配了。

**解决**：两种方式：

```python
# 方式 1：确保表头文字完全一致
name = CsvProperty("姓名", order=1)  # CSV 表头必须完全等于"姓名"

# 方式 2：用 index 固定列位置（不看表头）
name = CsvProperty("姓名", index=0)   # 强制读第 0 列
age = CsvProperty("年龄", index=1)    # 强制读第 1 列
```

---

### 报错 3：字段内含逗号导致数据错位

**现象**：某个字段的值里有逗号（如地址"北京市,朝阳区"），读回来列错位。

**原因**：CSV 用逗号分隔列，字段值里的逗号必须被引号包裹。

**解决**：本框架写入时自动处理（含逗号的字段自动加双引号包裹）。如果是外部 CSV，确认字段是否被双引号包裹。

---

### 报错 4：读回来对象全是空值

**现象**：`read_csv` 返回的对象列表不为空，但所有字段都是 `None`。

**原因**：表头行判断错了——CSV 第一行不是表头，但代码认为它是。

**解决**：

```python
# 如果 CSV 没有表头行
rows = EasyCsv.read("file.csv", head=User).has_header(False).doRead()

# 如果表头不在第一行
rows = EasyCsv.read("file.csv", head=User).has_header(True).doRead()
# 但注意：CSV 不像 Excel 可以设多个表头行号。表头只可能是第一行或不存在。
```

---

### 报错 5：写入后 Windows 记事本不换行

**现象**：生成的 CSV 在 Windows 记事本里全显示在一行。

**原因**：行终止符不匹配。

**解决**：

```python
@CsvFile(line_terminator="\r\n")  # Windows 换行（默认）
# 或
@CsvFile(line_terminator="\n")    # Linux 换行
```

---

## 注解参考（速查）

### `@CsvProperty` —— 对应 CSV 文件第几列

| 参数 | 默认 | 大白话 |
|------|------|--------|
| `value` | `""` | 表头文字，为空时自动用字段名生成 |
| `order` | `0` | 排第几列，越小越靠前 |
| `index` | `None` | 固定第几列（从 0 起），设置后忽略 `order` |
| `converter` | `None` | 自定义转换器，未设置时按类型注解自动选 |
| `date_format` | `None` | 日期格式，如 `%Y-%m-%d` |
| `big_number` | `False` | 长数字强制按字符串写入 |
| `ignore` | `False` | 跳过这一列，等价 `@CsvIgnore` |

两种声明形式：

```python
# 形式 1：类属性描述符（推荐）
class User:
    id = CsvProperty("ID", order=1)
    name = CsvProperty("姓名", order=2)

    def __init__(self, id: int = None, name: str = None):
        self.id = id
        self.name = name

# 形式 2：函数装饰器
class Demo:
    @CsvProperty("姓名", order=2)
    def name(self): ...
```

### `@CsvIgnore` —— 跳过这一列，不读也不写

```python
class Demo:
    remark = CsvIgnore()
    # 或
    @CsvIgnore()
    def remark(self): ...
```

### `@CsvFile` —— 设置 CSV 文件的全局配置

| 参数 | 默认 | 大白话 |
|------|------|--------|
| `file_name` | `""` | 文件名（元数据，读写时由调用方传路径） |
| `has_header` | `True` | 有没有表头行 |
| `delimiter` | `,` | 列用什么分隔（逗号、Tab、分号等） |
| `encoding` | `utf-8-sig` | 文件编码，带 BOM 兼容 Excel |
| `quote_char` | `"` | 引用字符，字段含逗号时自动加引号包裹 |
| `line_terminator` | `\r\n` | 行终止符，Windows 默认 `\r\n` |

> **提示：** `CsvFile` 是类级装饰器（也可作元数据类使用），与 ORM `@Table` 风格一致。框架还提供了小写函数别名向后兼容，推荐统一用大写。
>
> ```python
> from springbootai.csv import CsvFile
>
> @CsvFile("用户列表", delimiter=",", encoding="utf-8-sig")
> class DemoData:
>     id = CsvProperty("ID", order=1)
> ```

---

## 模块组成

| 文件 | 职责 |
|------|------|
| `springbootai/csv/annotations.py` | `@CsvProperty` / `@CsvIgnore` / `@CsvFile` 注解定义 |
| `springbootai/csv/converters.py` | 复用 Excel 模块的 `Converter` 接口和内置转换器 |
| `springbootai/csv/reader.py` | `CsvReader` 读取引擎 |
| `springbootai/csv/writer.py` | `CsvWriter` 写入引擎 |
| `springbootai/csv/easy_csv.py` | `EasyCsv` 流式 API 入口 + `read_csv` / `write_csv` 便捷函数 |
| `springbootai/csv/exceptions.py` | `CsvError` 异常族 |

与 Excel 模块的核心区别：CSV 使用 Python 标准库 `csv`，**零依赖**；无单元格样式（CSV 格式本身不支持）；转换器复用 Excel 模块。

---

## 进阶：复用已有实体类

上面的示例都是"从头定义一个专门的导入导出类"。但很多时候你**已经有实体类了**（比如 ORM 模型、API 返回的数据类），不想再写一遍。

框架支持 3 种复用方式，**不需要 `@CsvFile` 装饰器，不需要重写类**：

### 方式一：零改造，直接用

已有类有 `__init__`，框架自动扫描 `__init__` 参数建列，表头按参数名生成：

```python
# 已有的实体类，完全不改
class User:
    def __init__(self, id=None, name=None, age=None, email=None):
        self.id = id
        self.name = name
        self.age = age
        self.email = email

# 直接导出，不需要 @CsvFile
from springbootai.csv import EasyCsv
EasyCsv.write("users.csv").doWrite(users)
# CSV 表头自动生成为：Id / Name / Age / Email
```

### 方式二：加注解控制列名和顺序

在已有类的属性上加 `@CsvProperty`，只改你想控制的列：

```python
from springbootai.csv import CsvProperty, CsvIgnore

class User:
    id = CsvProperty("用户ID", order=1)      # 自定义表头和顺序
    name = CsvProperty("姓名", order=2)
    age = CsvProperty("年龄", order=3)
    email = CsvProperty("邮箱", order=4)
    password = CsvIgnore()                    # 不导出

    def __init__(self, id=None, name=None, age=None, email=None, password=None):
        self.id = id
        self.name = name
        self.age = age
        self.email = email
        self.password = password
```

### 方式三：ORM 风格，类型注解自动建列

用类型注解声明字段，未标注 `@CsvProperty` 的字段也会自动建列：

```python
from springbootai.csv import CsvProperty, CsvFile

@CsvFile("用户列表")
class User:
    id: int = CsvProperty("用户ID", order=1)  # 显式标注
    name: str = ""                              # 自动建列，表头 "Name"
    age: int = 0                                # 自动建列，表头 "Age"
    # 不需要手写 __init__，@CsvFile 自动生成
```

### 三种方式对比

| 方式 | 需要装饰器 | 需要改类 | 表头控制 | 适用场景 |
|------|-----------|---------|---------|---------|
| 零改造直接用 | 不需要 | 不需要 | 按参数名自动生成 | 快速导出，不在意表头 |
| 加注解控制 | 不需要 | 加 `@CsvProperty` | 完全自定义 | 生产环境导出 |
| ORM 风格 | `@CsvFile` | 类型注解 | 标注的自定义，其他自动 | 新建导出类 |

> **底层原理**：框架解析列模型时按 3 级回退——先找 `@CsvProperty` 标注的属性，再扫描类型注解自动建列，最后回退到 `__init__` 参数列表。所以已有类不需要任何改造也能导入导出。

---

## API 速查

```python
from springbootai.csv import (
    # 注解
    CsvProperty, CsvIgnore, CsvFile,
    # 引擎
    EasyCsv, read_csv, write_csv,
    # 转换器（复用 Excel 模块，也可从 springbootai.csv 导入）
    Converter, StringConverter, IntegerConverter, FloatConverter,
    BooleanConverter, DateStringConverter, BigDecimalConverter,
    # 异常
    CsvError, CsvPropertyError, CsvReadError, CsvWriteError,
)

# ===== 读取 =====
rows = (EasyCsv.read("file.csv", head=Demo)
        .has_header(True)      # 有表头行
        .delimiter(",")        # 逗号分隔
        .encoding("utf-8-sig") # 编码
        .doRead())
# 结果: list[Demo]，字段已按类型自动转换

# 便捷函数
rows = read_csv("file.csv", Demo, has_header=True, delimiter=",", encoding="utf-8-sig")
# 结果: list[Demo]

# ===== 写入 =====
EasyCsv.write("file.csv", head=Demo).doWrite(data_list)

# 便捷函数
filepath = write_csv("file.csv", Demo, data, delimiter=",", encoding="utf-8-sig")
# 结果: 目标文件路径
```

`source` / `target` 支持文件路径（`str` 或 `Path`）或类文件对象。

---

## FAQ

**Q: CSV 和 Excel 到底怎么选？**

A: 两个系统之间传数据、数据量大（>5 万行）→ CSV。导出报表给人看、需要样式和多 Sheet → Excel。详见 [Excel 模块文档](EXCEL_MODULE.md)。

**Q: CSV 模块需要装 openpyxl 吗？**

A: 不需要。CSV 模块用 Python 自带的 `csv` 库，零额外依赖。转换器虽然复用 Excel 模块的代码，但 `springbootai.excel.converters` 不依赖 openpyxl，可以安全导入。

**Q: 为什么 Windows Excel 打开中文 CSV 是乱码？**

A: Excel 默认用 ANSI 编码，不认识 UTF-8。解决方案：用 `encoding="utf-8-sig"`（在文件头加 BOM 标记，Excel 看到 BOM 就知道是 UTF-8）。

**Q: CSV 读取和写入的编码必须一致吗？**

A: 必须一致。用 `utf-8-sig` 写就用 `utf-8-sig` 读，用 `utf-8` 写就用 `utf-8` 读。

**Q: CSV 模块和 Excel 模块的代码可以共用吗？**

A: 几乎可以。把 `springbootai.excel` 改成 `springbootai.csv`，`ExcelProperty` 改成 `CsvProperty`，`@ExcelSheet` 改成 `@CsvFile` 就行。功能上会少掉样式和多 Sheet。

**Q: CSV 模块和 ORM 模块有什么关系？**

A: 没有直接关系。CSV 管文件读写，ORM 管数据库操作。你可以先把数据库里的数据用 ORM 查出来，再用 CSV 模块导出成文件。参见 [ORM 模块文档](ORM_MODULE.md)。

**Q: 从一个已有的 Excel 实体类改成 CSV 实体类需要改什么？**

A: 只需三步：
1. `from springbootai.excel` → `from springbootai.csv`
2. `ExcelProperty` → `CsvProperty`、`ExcelIgnore` → `CsvIgnore`
3. `@ExcelSheet` → `@CsvFile`

---

## 改进记录

### 大文件读取未流式处理，内存溢出风险 — 高 ✅ 已修复 (v2.3.0)

**位置**：`springbootai/csv/reader.py` doRead()

**现象**：CSV 读取使用 `csv.reader()` 虽然逐行读取，但结果列表全部收集后返回。10 万行以上的大文件内存占用可能超过 1GB。

**修复方案**：新增 `doReadLazy()` 流式生成器方法，逐行 yield 实体对象，不一次性加载全部行到内存。调用方按需消费：`for row in reader.doReadLazy(): process(row)`。
