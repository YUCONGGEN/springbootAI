# SpringBootAI Excel 模块 —— 小白也能看懂的使用指南

> 模块版本：`spring.excel` 2.2.6 ｜ 框架版本：SpringBootAI 2.2.6

---

## 什么场景用 Excel 模块？

| 场景 | 用 Excel 模块 ✅ | 用 CSV 模块 ✅ | 原因 |
|------|----------------|---------------|------|
| 导出给老板看的报表 | ✅ | ❌ | Excel 支持样式、公式、冻结表头、多个 Sheet |
| 多个工作表的数据 | ✅ | ❌ | CSV 不支持多个 Sheet |
| 需要保护长数字（18 位 ID）不丢失 | ✅ | ❌ | Excel 模块有 `big_number` 保护 |
| 系统之间定时交换数据 | ❌ | ✅ | CSV 更轻量、更快、零依赖 |
| 数据量特别大（>10 万行） | ❌ | ✅ | CSV 是纯文本，读写更快 |
| 不想装 openpyxl | ❌ | ✅ | CSV 用 Python 自带的 `csv` 模块 |

> **一句话决策**：导出给老板看 → Excel。两个系统传数据 → CSV。

---

## 用这个模块 vs 不用这个模块

| | 不用 Excel 模块（用 openpyxl 手写） | 用 Excel 模块 |
|---|---|---|
| **代码量** | 手动打开、建 Sheet、设表头、填单元格、设样式……上百行 | 定义类 + 一行 `write_excel()` |
| **表头映射** | 手动对应 "第几列是什么字段" | `@ExcelProperty("姓名")` 贴个标签就行 |
| **类型转换** | 手动转 `datetime` ↔ `str`、`Decimal` ↔ `float` | 框架自动按类型注解转换 |
| **长数字** | Excel 自动转科学计数法，丢失精度 | `big_number=True` 一行解决 |
| **样式** | 手动调字体、颜色、边框、列宽 | 默认样式自动美化 |

**举个例子**——导出 5000 条用户数据：

```python
# ❌ 不用 Excel 模块（手写 openpyxl，几十行代码）
from openpyxl import Workbook
wb = Workbook()
ws = wb.active
ws.append(["用户ID", "姓名", "年龄", "邮箱", "注册时间", "是否激活"])
for user in users_from_db:
    ws.append([str(user.id), user.name, user.age, user.email,
               user.created_at.strftime("%Y-%m-%d %H:%M:%S"), "是" if user.active else "否"])
# ... 还得调列宽、设样式、冻结表头...
wb.save("users.xlsx")
```

```python
# ✅ 用 Excel 模块（定义类 + 一行代码）
from spring.excel import write_excel
from demo.excel_entity import UserExport

write_excel("users.xlsx", UserExport, users)
```

---

## 第零章：Excel 和代码的关系

### 你手操作 Excel → 代码操作 Excel

| 你手动做的事 | 代码做的事 |
|-------------|-----------|
| 打开 Excel 文件 | `EasyExcel.read("users.xlsx")` |
| 看第一行表头，知道每列是什么 | `@ExcelProperty("姓名")` 告诉代码"这一列叫姓名" |
| 一行行读数据 | `doRead()` 返回 `list[User]` |
| 手动填数据 | `doWrite(data)` 把 5000 条数据一次性写入 |
| 另存为 | `EasyExcel.write("output.xlsx")` |

### 一句话理解注解

**注解就是标签**——你在 Python 类的属性上贴"标签"，告诉代码：
- 这个属性在 Excel 里叫什么名字（表头）
- 这个属性排在第几列
- 这个属性用什么格式显示

```python
# 这行代码的意思是：
# "name 这个属性，在 Excel 里表头叫'姓名'，排在第 2 列，列宽 12 个字符"
name = ExcelProperty("姓名", order=2, width=12)
```

---

## 第一章：使用前准备

### 1.1 安装

```powershell
python -m pip install "springbootAI[excel]"
```

这会自动安装 `openpyxl`。不装的话，`@ExcelProperty` 之类的注解定义不受影响，但实际读写时会报错提示你安装。

### 1.2 最短验证流程

1. 定义一个带 `@ExcelProperty` 的 Python 类
2. 用 `write_excel()` 导出几条数据
3. 打开生成的文件，检查表头和内容
4. 用 `read_excel()` 读回来，验证数据一致

---

## 第二章：一个完整例子 —— 从零到导出 Excel

> **这章带你从零实现：定义实体 → 导出 Excel → 读回来验证 → 在 Web 接口里用。**

### 场景

把数据库里的用户信息导出成 `.xlsx` 文件，要求：中文表头、日期格式化显示、长 ID 不丢失精度。

### 第一步：定义实体类

> **@ExcelProperty 是什么？** 给 Python 类属性贴标签，告诉框架"这个属性对应 Excel 里哪一列、表头叫什么"。好比你在箱子上贴快递单——"这个箱子里装的是姓名，放在第 2 个位置"。  
> **@ExcelIgnore 是什么？** 告诉框架"这一列跳过，不导入也不导出"。好比快递单上有个"内部备注"你不希望寄件人看到。  
> **@excel_sheet 是什么？** 设置这个 Excel 文件的全局配置——工作表的名称、表头在第几行、要不要冻结表头。

```python
# demo/excel_entity.py
from datetime import datetime
from decimal import Decimal
from spring.excel import ExcelProperty, ExcelIgnore, excel_sheet, BigDecimalConverter


@excel_sheet("用户列表", freeze_head=True, auto_width=True)
class UserExport:
    # 长 ID：big_number=True 强制按文本写入，防止 Excel 把 76543210987654321 变成 7.65432E+16
    id = ExcelProperty("用户ID", order=1, big_number=True)

    # width=15：列宽 15 个字符
    name = ExcelProperty("姓名", order=2, width=15)

    # 普通字段：不需要特殊设置
    age = ExcelProperty("年龄", order=3)

    # BigDecimalConverter：金额用 Decimal 类型，保留精确精度
    amount = ExcelProperty("账户余额", order=4, converter=BigDecimalConverter)

    # date_format：日期的显示格式
    created_at = ExcelProperty("注册时间", order=5, date_format="%Y-%m-%d %H:%M:%S")

    # bool 类型自动转 "是"/"否"
    active = ExcelProperty("是否激活", order=6)

    # 这个字段不导出
    remark = ExcelIgnore()

    def __init__(self, id=None, name=None, age=None, amount=None,
                 created_at=None, active=None, remark=None):
        self.id = id
        self.name = name
        self.age = age
        self.amount = amount
        self.created_at = created_at
        self.active = active
        self.remark = remark
```

① `@excel_sheet("用户列表")` 设置 Sheet 名字叫"用户列表"，冻结表头（滚动时表头始终可见），自动列宽。  
② `@ExcelProperty("用户ID", order=1, big_number=True)` 告诉框架：第 1 列表头叫"用户ID"，内容按文本写入。  
③ `@ExcelIgnore()` 告诉框架：`remark` 这个字段不参与读写。

### 第二步：准备数据并导出

```python
# demo/export_users.py
from datetime import datetime
from decimal import Decimal
from spring.excel import EasyExcel, write_excel
from demo.excel_entity import UserExport

# 准备数据（实际项目中数据从数据库查）
users = [
    UserExport(
        id=76543210987654321,
        name="张三",
        age=28,
        amount=Decimal("12345.67"),
        created_at=datetime(2026, 8, 9, 12, 0, 0),
        active=True,
        remark="内部备注（不会出现在 Excel 里）"
    ),
    UserExport(
        id=2,
        name="李四",
        age=35,
        amount=Decimal("999.00"),
        created_at=datetime(2026, 1, 2, 3, 4, 5),
        active=False,
        remark="外部备注（不会出现在 Excel 里）"
    ),
]

# 方式1：流式 API（功能最全）
EasyExcel.write("用户列表.xlsx", head=UserExport).sheet("用户列表").doWrite(users)
# 结果：生成"用户列表.xlsx"，长 ID 不会被截断，日期格式正确

# 方式2：便捷函数（代码最短）
write_excel("用户列表_便捷.xlsx", UserExport, users)
# 结果：同样生成 Excel 文件，一步到位
```

③ 运行结果：生成 `用户列表.xlsx`，打开后能看到：
- 表头：用户ID | 姓名 | 年龄 | 账户余额 | 注册时间 | 是否激活
- 张三那行的 ID 是 `76543210987654321`，没有被截断
- 注册时间显示为 `2026-08-09 12:00:00`
- `remark` 列不会出现

### 第三步：读回来验证

```python
# demo/import_users.py
from spring.excel import EasyExcel, read_excel
from demo.excel_entity import UserExport

# 方式1：流式读取
rows = (EasyExcel.read("用户列表.xlsx", head=UserExport)
        .head_row_number(1)       # 表头在第 1 行
        .sheet(sheet_no=0)        # 读取第 0 个工作表（第一个 Sheet）
        .doRead())

print(f"读取到 {len(rows)} 条记录")
# 输出: 读取到 2 条记录

for user in rows:
    print(f"  {user.name}: 余额={user.amount}, 注册={user.created_at}")
# 输出:   张三: 余额=12345.67, 注册=2026-08-09 12:00:00
# 输出:   李四: 余额=999.00, 注册=2026-01-02 03:04:05

# 验证类型是否正确转换
print(type(rows[0].amount))      # 输出: <class 'decimal.Decimal'>
print(type(rows[0].created_at))  # 输出: <class 'datetime.datetime'>
print(type(rows[0].active))      # 输出: <class 'bool'>

# 方式2：便捷函数（一步读回来）
rows2 = read_excel("用户列表.xlsx", UserExport)
# 结果: list[UserExport]，字段已按类型注解自动转换
```

### 第四步：在 Web 接口里使用

```python
# demo/controller/export_controller.py
from spring.web import RestController, GetMapping
from spring.http import FileResponse
from spring.excel import write_excel
from demo.excel_entity import UserExport
from demo.service.user_service import UserService


@RestController("/api/export")
class ExportController:
    def __init__(self, user_service: UserService):
        self.user_service = user_service

    @GetMapping("/users")
    def export_users(self):
        """GET /api/export/users → 下载用户列表 Excel 文件"""
        # 从数据库查出用户
        db_users = self.user_service.list_all()

        # 转换成导出实体
        export_data = [
            UserExport(
                id=u.id, name=u.name, age=u.age,
                amount=u.amount, created_at=u.created_at,
                active=u.active, remark=""
            )
            for u in db_users
        ]

        # 导出到临时文件
        filepath = "/tmp/用户列表_export.xlsx"
        write_excel(filepath, UserExport, export_data)

        # 返回文件下载
        return FileResponse(filepath, filename="用户列表.xlsx")
```

---

## 第三章：多 Sheet 读写 —— 一个文件多个工作表

### ① 是什么

一个 Excel 文件里可以有多个 Sheet（工作表），比如"1 月数据"、"2 月数据"、"汇总"。Excel 模块支持一次读写所有 Sheet。

### ② 怎么用

**写入多个 Sheet：**

```python
# demo/multi_sheet_export.py
from spring.excel import EasyExcel
from demo.excel_entity import UserExport

# 准备不同 Sheet 的数据
january_users = [UserExport(1, "张三", 28), UserExport(2, "李四", 35)]
february_users = [UserExport(3, "王五", 22), UserExport(4, "赵六", 40)]

# 一次写入所有 Sheet
EasyExcel.write("多Sheet示例.xlsx", head=UserExport).doWriteAll({
    "1月用户": january_users,   # Sheet 名叫 "1月用户"
    "2月用户": february_users,  # Sheet 名叫 "2月用户"
})
```

**读取多个 Sheet：**

```python
# demo/multi_sheet_import.py
from spring.excel import EasyExcel
from demo.excel_entity import UserExport

# 读取所有 Sheet
all_data = EasyExcel.read("多Sheet示例.xlsx", head=UserExport).doReadAll()
# all_data: {"1月用户": [UserExport(...), ...], "2月用户": [UserExport(...), ...]}

for sheet_name, rows in all_data.items():
    print(f"{sheet_name}: {len(rows)} 条记录")
# 输出: 1月用户: 2 条记录
# 输出: 2月用户: 2 条记录

# 只读取特定 Sheet（按名字）
jan_users = (EasyExcel.read("多Sheet示例.xlsx", head=UserExport)
             .sheet(sheet_name="1月用户").doRead())

# 只读取特定 Sheet（按索引，0 表示第一个）
jan_users = (EasyExcel.read("多Sheet示例.xlsx", head=UserExport)
             .sheet(sheet_no=0).doRead())
```

### ③ 运行结果

生成的 `多Sheet示例.xlsx` 有两个 Sheet，名字分别是"1 月用户"和"2 月用户"。读回来时，`doReadAll()` 返回一个字典，key 是 Sheet 名，value 是该 Sheet 的数据列表。

---

## 第四章：大数字精度问题 —— 为什么 15 位以上数字会丢失

### ① 是什么

Excel 有个著名的坑：**超过 15 位的数字会自动丢失精度**。比如身份证号 `123456789012345678`（18 位），Excel 会把它变成 `123456789012345000`，最后 3 位变成了 0。这是因为 Excel 内部用浮点数存储数字，最多只能精确表示 15 位有效数字。

### ② 怎么防护

```python
# ❌ 不设 big_number，长 ID 会被截断
id = ExcelProperty("用户ID", order=1)
# 写入 76543210987654321 → Excel 显示 7.65432E+16（科学计数法）
# 读回来变成 76543210987654300（末尾精度丢失！）

# ✅ 设 big_number=True，强制按文本写入
id = ExcelProperty("用户ID", order=1, big_number=True)
# 写入 76543210987654321 → Excel 里原样显示 76543210987654321
# 读回来还是 76543210987654321（完整精度）
```

### ③ 注意

`big_number=True` 会把数字当**文本**写入，所以 Excel 里无法对这些列做数学运算（比如求和、平均值）。只在真正需要（如身份证号、长 ID、订单号）时才用它。

---

## 第五章：自定义转换器 —— 特殊格式自己写

### ① 是什么

内置的转换器（int/float/str/date/Decimal）不够用，比如你想把列表 `["python", "java"]` 存成 Excel 里的 `python;java`，就需要自己写转换器。

### ② 怎么用

```python
# demo/custom_converter.py
from spring.excel import Converter, ExcelProperty, excel_sheet


# 自定义转换器：列表 ↔ 分号分隔的字符串
class TagsConverter(Converter):
    def to_excel(self, value):
        """写入 Excel 时：列表 → 字符串"""
        return ";".join(value) if value else ""
        # ["python", "java"] → "python;java"

    def from_excel(self, cell_value):
        """读取 Excel 时：字符串 → 列表"""
        return str(cell_value).split(";") if cell_value else []
        # "python;java" → ["python", "java"]


@excel_sheet("文章列表")
class Article:
    title = ExcelProperty("标题", order=1)
    tags = ExcelProperty("标签", order=2, converter=TagsConverter())
    # tags 写进去是 "技术;Python"，读回来是 ["技术", "Python"]

    def __init__(self, title="", tags=None):
        self.title = title
        self.tags = tags


# 测试
from spring.excel import write_excel, read_excel

data = [
    Article("Python 入门", ["python", "教程"]),
    Article("Excel 模块", ["技术", "Python", "Excel"]),
]
write_excel("articles.xlsx", Article, data)

rows = read_excel("articles.xlsx", Article)
print(rows[0].tags)  # 输出: ['python', '教程']
print(rows[1].tags)  # 输出: ['技术', 'Python', 'Excel']
```

### ③ 运行结果

Excel 里的"标签"列显示为 `python;教程`，读回 Python 后自动变回列表 `["python", "教程"]`。

---

## 第〇章：新手常见错误

> 刚开始用 Excel 模块最容易踩的坑。

### 错误 1："Excel 模块能直接代替数据库"

❌ **错误想法**：用 Excel 存数据，连数据库都不用装了。

✅ **实际情况**：Excel 模块处理的是**文件**——它负责"Python 对象 ↔ .xlsx 文件"之间的转换。读到对象后，你需要自己写代码存到数据库。它不会自动帮你入库。

---

### 错误 2："所有数字字段都加 `big_number=True`"

❌ **错误想法**：`big_number=True` 一劳永逸，全加上保险。

✅ **实际情况**：`big_number=True` 把数字当文本写入，Excel 里**无法对文本做求和、平均值等计算**。只在真正需要（身份证号、长 ID、订单号）时才用。

---

### 错误 3："表头行号从 0 开始"

❌ **错误想法**：编程习惯从 0 开始，`head_row_number=0` 表示第一行。

✅ **实际情况**：`head_row_number` 从 **1** 开始，和 Excel 行号保持一致。`head_row_number=1` 表示第一行是表头。`head_row_number=2` 表示前两行是无关内容，第三行才是表头。

```python
# ✅ 正确
EasyExcel.read("file.xlsx", head=Demo).head_row_number(1)  # 第一行是表头

# ❌ 错误
EasyExcel.read("file.xlsx", head=Demo).head_row_number(0)  # 没有第 0 行
```

---

### 错误 4："读取用户上传的 Excel 不需要校验"

❌ **错误想法**：`read_excel` 成功了就说明数据没问题。

✅ **实际情况**：Excel 模块只做**格式转换**，不做**业务校验**。必填字段可能为空、手机号可能格式错误、金额可能为负数。读到对象后，你必须在 Service 层做业务校验。

```python
# ✅ 读完后做业务校验
rows = read_excel("用户上传.xlsx", UserImport)
for user in rows:
    if not user.name:
        raise ValueError("姓名不能为空")
    if not user.phone or len(user.phone) != 11:
        raise ValueError("手机号格式不正确")
    if user.age < 0 or user.age > 150:
        raise ValueError("年龄不合理")
```

---

### 错误 5："Excel 模块能处理任意大小的文件"

❌ **错误想法**：10 万行 Excel 随便读写。

✅ **实际情况**：当前基于 openpyxl 全量加载到内存，大文件（>5 万行）会很吃内存。超过 5 万行建议：
1. 用 CSV 代替（见 [CSV 模块文档](CSV_MODULE.md)）
2. 或者把 Excel 按 5000 行分片导出

---

### 错误 6："`auto_width=True` 会精确计算列宽"

❌ **错误想法**：自动列宽会完美适配内容。

✅ **实际情况**：自适应列宽是一个**估算值**，对中文宽字符可能不够准。如果列宽不够，手动设 `width`：

```python
name = ExcelProperty("姓名", order=2, width=20)  # 手动设 20 个字符宽
```

---

## 常见报错和解决方法

### 报错 1：`ExcelDependencyError: openpyxl is required`

**现象**：调用 `write_excel` 或 `read_excel` 时报错。

**原因**：没有安装 `openpyxl`。

**解决**：
```powershell
pip install "springbootAI[excel]"
```

---

### 报错 2：长数字变成科学计数法

**现象**：导出的 Excel 里，`76543210987654321` 变成了 `7.65432E+16`。

**原因**：Excel 对超过 15 位的数字自动截断精度。

**解决**：字段上加 `big_number=True`：
```python
id = ExcelProperty("ID", order=1, big_number=True)
```

---

### 报错 3：日期读回来变成了数字（如 `45557.0`）

**现象**：`read_excel` 读出的日期是 `45557.0` 之类的浮点数。

**原因**：没有设置 `date_format`，框架不知道按什么格式解析。

**解决**：
```python
created_at = ExcelProperty("创建时间", order=5, date_format="%Y-%m-%d %H:%M:%S")
```

---

### 报错 4：多 Sheet 时 `doRead()` 返回空列表

**现象**：`doRead()` 返回空列表，但文件明明有数据。

**原因**：默认读的是第一个 Sheet（索引 0），数据可能在第二个 Sheet。

**解决**：明确指定 Sheet 名称或索引：
```python
# 按名称读
rows = EasyExcel.read("file.xlsx", head=Demo).sheet(sheet_name="数据").doRead()

# 按索引读（0 是第一个，1 是第二个）
rows = EasyExcel.read("file.xlsx", head=Demo).sheet(sheet_no=1).doRead()
```

---

### 报错 5：中文表头读取失败

**现象**：Excel 表头明明是"姓名"，但代码不认。

**原因**：表头和 `@ExcelProperty("value")` 有细微差异（空格、全角/半角）。

**解决**：要么确保表头完全一致，要么改用 `index` 按位置读取（不看表头）：
```python
name = ExcelProperty("姓名", index=0)  # 固定读取第 0 列，不看表头文字
```

---

## 注解参考（速查）

### `@ExcelProperty` —— 给属性贴上"对应 Excel 哪一列"的标签

| 参数 | 默认 | 大白话 | 说明 |
|------|------|--------|------|
| `value` | `""` | 列标题文案 | 为空时自动用字段名转标题（`user_name` → `User Name`） |
| `order` | `0` | 排第几列 | 越小越靠前；同 order 按声明顺序 |
| `index` | `None` | 固定第几列 | 绝对列索引（从 0 起），设置后覆盖 `order` |
| `converter` | `None` | 自定义转换器 | 未设置时按字段类型注解自动选择 |
| `date_format` | `None` | 日期显示格式 | 如 `%Y-%m-%d` |
| `num_format` | `None` | 数字显示格式 | 如 `#,##0.00` |
| `width` | `0` | 列宽 | 0 表示自适应 |
| `big_number` | `False` | 长数字防截断 | 按文本写入，避免 Excel 丢失精度 |
| `ignore` | `False` | 跳过这一列 | 等价 `@ExcelIgnore` 的快捷开关 |

两种声明形式：

```python
# 形式 1：类属性描述符（推荐）
class Demo:
    name = ExcelProperty("姓名", order=2, width=12)

# 形式 2：函数装饰器
class Demo:
    @ExcelProperty("姓名", order=2)
    def name(self): ...
```

### `@ExcelIgnore` —— 这一列跳过，不导入也不导出

```python
class Demo:
    remark = ExcelIgnore()
    # 或
    @ExcelIgnore()
    def remark(self): ...
```

### `@excel_sheet` —— 设置工作表的全局配置

| 参数 | 默认 | 大白话 |
|------|------|--------|
| `sheet_name` | `""` | Sheet 页名称 |
| `head_row_number` | `1` | 表头在第几行（从 1 开始） |
| `freeze_head` | `True` | 冻结表头（滚动时表头始终可见） |
| `auto_width` | `True` | 自动列宽 |

---

## 内置转换器

| Python 类型 | 自动使用 | 写出去什么样 | 读回来什么样 |
|-------------|---------|-------------|-------------|
| `int` | `IntegerConverter` | 数字 | `int` |
| `float` | `FloatConverter` | 数字 | `float` |
| `bool` | `BooleanConverter` | "是"/"否" | `bool` |
| `str` | `StringConverter` | 文本 | `str` |
| `datetime`/`date` | `DateStringConverter` | 按 `date_format` 格式化 | `datetime` 对象 |
| `Decimal` | `BigDecimalConverter` | 文本（防精度丢失） | `Decimal` 对象 |

---

## API 速查

```python
from spring.excel import (
    # 注解
    ExcelProperty, ExcelIgnore, excel_sheet,
    # 转换器
    Converter, StringConverter, IntegerConverter, FloatConverter,
    BooleanConverter, DateStringConverter, BigDecimalConverter,
    # 引擎
    EasyExcel, read_excel, write_excel,
    # 异常
    ExcelError, ExcelPropertyError, ExcelReadError, ExcelWriteError, ExcelDependencyError,
)

# ===== 读取 =====
# 读一个 Sheet
rows = (EasyExcel.read("file.xlsx", head=Demo)
        .head_row_number(1)         # 表头行号
        .sheet(sheet_no=0)          # 或 sheet(sheet_name="数据")
        .doRead())
# 结果: list[Demo]，字段已按类型自动转换

# 读所有 Sheet
all_data = EasyExcel.read("file.xlsx", head=Demo).doReadAll()
# 结果: {"Sheet1": [Demo, ...], "Sheet2": [Demo, ...]}

# 便捷函数
rows = read_excel("file.xlsx", Demo)
# 结果: list[Demo]

# ===== 写入 =====
# 写一个 Sheet
EasyExcel.write("file.xlsx", head=Demo).sheet("数据").doWrite(data_list)

# 写多个 Sheet
EasyExcel.write("file.xlsx", head=Demo).doWriteAll({
    "Sheet1": list1,
    "Sheet2": list2,
})

# 便捷函数
filepath = write_excel("file.xlsx", Demo, data)
# 结果: 目标文件路径
```

---

## FAQ

**Q: Excel 和 CSV 模块怎么选？**

A: 导出报表给老板看、需要样式和多个 Sheet → Excel。系统间定时传数据、数据量大 → CSV。详见 [CSV 模块文档](CSV_MODULE.md)。

**Q: 不装 openpyxl 能用吗？**

A: 定义 `@ExcelProperty` 之类的注解不需要 openpyxl。但实际读写 Excel 文件时必须有 openpyxl，否则会报错。

**Q: 读 Excel 时如何跳过表头前的空行？**

A: 用 `head_row_number` 指定表头在哪一行。比如表头前有 2 行标题说明，就设 `head_row_number=3`。

**Q: 怎么确保长 ID 不被截断？**

A: 两个方法：① `big_number=True`（推荐）；② 字段类型用 `Decimal` + `BigDecimalConverter`。

**Q: Excel 模块和 ORM 模块的注解有关系吗？**

A: 设计范式一致（都用类属性描述符 + MRO 反射），但功能独立。`@ExcelProperty` 管 Excel，`@entity` 管数据库表。参见 [ORM 模块文档](ORM_MODULE.md)。

---

## 改进记录

### 大文件读取未流式处理，内存溢出风险 — 高 ✅ 已修复 (v2.2.6)

**位置**：`spring/excel/reader.py` doRead()

**现象**：Excel 读取使用 `openpyxl.load_workbook()` 一次性加载整个文件到内存。10 万行以上的大文件内存占用可能超过 1GB。

**修复方案**：新增 `doReadLazy()` 流式生成器方法，使用 openpyxl `read_only=True` 模式逐行 yield 实体对象，不将整个文件加载到内存。新增 `_iter_one_sheet()` 内部方法实现逐行迭代。
