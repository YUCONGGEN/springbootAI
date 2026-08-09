"""SpringPy Excel 模块端到端演示（可独立运行）。

运行::

    pip install springpy[excel]      # 或 pip install openpyxl==3.1.5
    python example_excel_demo.py

演示内容：
  1. 注解声明（@excel_sheet / @ExcelProperty / @ExcelIgnore，复用 ORM Column 范式）
  2. 写入：多字段类型、大数字防丢精度、自定义转换器、金额 Decimal、日期格式
  3. 读取：round-trip、字段按类型还原
  4. 多 sheet 读写
  5. 无注解纯 __init__ 模型自动回退
  6. 便捷函数 read_excel / write_excel
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from decimal import Decimal

# 让脚本在未安装时也能从仓库根目录导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from spring.excel import (
    EasyExcel, ExcelProperty, ExcelIgnore, excel_sheet,
    BigDecimalConverter, Converter, read_excel, write_excel,
)


# ==================== 1. 注解声明（复用 ORM Column 元数据描述符范式） ====================

class LevelConverter(Converter):
    """自定义转换器：职级在 Python 用整数 1-9，Excel 中显示为 'L1'..'L9'。"""
    def to_excel(self, value):
        return f"L{value}" if value is not None else value

    def from_excel(self, cell_value):
        if not cell_value:
            return None
        text = str(cell_value).strip()
        if text.startswith("L") and text[1:].isdigit():
            return int(text[1:])
        try:
            return int(text)
        except ValueError:
            return None


@excel_sheet("员工列表", head_row_number=1)
class Employee:
    """员工实体：演示注解 / 转换器 / 大数字 / 日期 / 忽略字段。"""
    emp_id = ExcelProperty("工号", order=1, big_number=True)          # 长 ID 防丢精度
    name = ExcelProperty("姓名", order=2, width=14)
    age = ExcelProperty("年龄", order=3)
    salary = ExcelProperty("薪资", order=4, converter=BigDecimalConverter, num_format="#,##0.00")
    hire_date = ExcelProperty("入职日期", order=5, date_format="%Y-%m-%d")
    level = ExcelProperty("职级", order=6, converter=LevelConverter())
    internal_note = ExcelIgnore()                                     # 跳过不导出

    def __init__(self, emp_id=None, name=None, age=None, salary=None,
                 hire_date=None, level=None, internal_note=None):
        self.emp_id = emp_id
        self.name = name
        self.age = age
        self.salary = salary
        self.hire_date = hire_date
        self.level = level
        self.internal_note = internal_note

    def __repr__(self):
        return (f"Employee(emp_id={self.emp_id!r}, name={self.name!r}, age={self.age!r}, "
                f"salary={self.salary!r}, hire_date={self.hire_date!r}, level={self.level!r})")


# 无注解的纯 __init__ 模型（如 example_all/models/User.py）——自动按字段名生成表头
class PlainProduct:
    def __init__(self, id=None, product_name=None, price=None):
        self.id = id
        self.product_name = product_name
        self.price = price

    def __repr__(self):
        return f"PlainProduct(id={self.id}, product_name={self.product_name!r}, price={self.price})"


def banner(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="springpy_excel_demo_")

    # ==================== 2. 写入单 sheet ====================
    banner("1. 写入员工列表（注解 / 大数字 / Decimal / 日期 / 自定义转换器 / 忽略字段）")
    employees = [
        Employee(76543210987654321, "张三", 28, Decimal("12345.67"),
                 datetime(2026, 8, 9), 5, "内部备注-不导出"),
        Employee(2, "李四", 35, Decimal("99999.00"),
                 datetime(2024, 3, 15), 8, "另一个人"),
        Employee(3, "王五", 42, Decimal("50000.50"),
                 datetime(2020, 12, 1), 3, ""),
    ]
    emp_file = os.path.join(tmp, "employees.xlsx")
    EasyExcel.write(emp_file, head=Employee).sheet("员工列表").doWrite(employees)
    print(f"写入完成 -> {emp_file}")

    # ==================== 3. 读取 round-trip ====================
    banner("2. 读取 round-trip（字段按类型还原：Decimal / datetime / int 职级）")
    rows = EasyExcel.read(emp_file, head=Employee).doRead()
    for r in rows:
        print(" ", r)
    print(f"大数字保留 17 位: {rows[0].emp_id} (len={len(str(rows[0].emp_id))})")
    print(f"薪资为 Decimal: {type(rows[0].salary).__name__} = {rows[0].salary}")
    print(f"入职日期为 datetime: {type(rows[0].hire_date).__name__} = {rows[0].hire_date}")
    print(f"职级自定义转换器还原: {rows[0].level} (int)")
    print(f"internal_note 被 @ExcelIgnore 跳过: {getattr(rows[0], 'internal_note', None)}")

    # ==================== 4. 多 sheet ====================
    banner("3. 多 sheet 读写")
    multi_file = os.path.join(tmp, "multi.xlsx")
    EasyExcel.write(multi_file, head=Employee).doWriteAll({
        "北京分公司": [employees[0]],
        "上海分公司": employees[1:],
    })
    print(f"多 sheet 写入完成 -> {multi_file}")
    sheets = EasyExcel.read(multi_file, head=Employee).doReadAll()
    for name, sheet_rows in sheets.items():
        print(f"  [{name}] {len(sheet_rows)} 行: {[r.name for r in sheet_rows]}")

    # ==================== 5. 无注解纯 __init__ 模型自动回退 ====================
    banner("4. 无注解纯 __init__ 模型自动回退（表头按字段名生成）")
    plain_file = os.path.join(tmp, "products.xlsx")
    products = [PlainProduct(1, "键盘", 199.0), PlainProduct(2, "鼠标", 49.5)]
    write_excel(plain_file, PlainProduct, products)
    print(f"写入完成 -> {plain_file}")
    print("读回:", read_excel(plain_file, PlainProduct))

    # ==================== 6. 表头非首行 ====================
    banner("5. 表头非首行（前置说明行，表头在第 2 行）")
    import openpyxl
    head2_file = os.path.join(tmp, "head2.xlsx")
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "S"
    ws.append(["说明：本表表头在第2行", None, None])   # row1 占位
    ws.append(["姓名", "年龄", "薪资"])                 # row2 表头
    ws.append(["ann", "30", "1.5"])
    wb.save(head2_file); wb.close()

    @excel_sheet(head_row_number=2)
    class C:
        name = ExcelProperty("姓名", order=1)
        age = ExcelProperty("年龄", order=2)
        salary = ExcelProperty("薪资", order=3, converter=BigDecimalConverter)
        def __init__(self, name=None, age=None, salary=None):
            self.name = name; self.age = age; self.salary = salary
        def __repr__(self):
            return f"C(name={self.name!r}, age={self.age!r}, salary={self.salary!r})"
    print("读回:", EasyExcel.read(head2_file, head=C).doRead())

    banner("演示完成 ✅  所有临时文件位于: " + tmp)


if __name__ == "__main__":
    main()
