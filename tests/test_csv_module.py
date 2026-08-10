"""SpringBootAI CSV 注解模块测试 —— 覆盖注解/转换器/读写引擎/EasyCsv 入口/round-trip。

对齐 tests/test_excel_module.py 的 pytest 风格。CSV 使用标准库 ``csv``，无可选依赖，
测试以临时文件与 ``io.StringIO`` 驱动，验证：
- @CsvProperty / @CsvIgnore / @csv_file 元数据与反射解析（描述符 + 函数装饰器两种形式）
- 列排序（index > order > 声明顺序）、全忽略抛错、无注解回退 __init__
- 转换器自动选择与自定义转换器（int/float/bool/date/Decimal）
- CsvReader：表头匹配/位置匹配/无表头/自定义分隔符/跳空行/类文件对象
- CsvWriter：表头/顺序/大数字防丢精度/date_format/无表头/dict 数据
- EasyCsv 流式 + read_csv/write_csv 便捷函数 + round-trip
"""
import io
import os
import sys
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from spring.csv import (
    CsvProperty, CsvIgnore, CsvFile, csv_file,
    CsvColumnModel, parse_csv_columns,
    Converter, CsvConverter,
    StringConverter, IntegerConverter, FloatConverter,
    BooleanConverter, DateStringConverter, BigDecimalConverter,
    resolve_csv_converter,
    CsvReader, CsvWriter, EasyCsv, read_csv, write_csv,
    CsvPropertyError, CsvReadError, CsvWriteError,
)


# ==================== 注解元数据 ====================

class TestAnnotations:
    def test_csv_property_defaults(self):
        p = CsvProperty()
        assert p.value == ""
        assert p.order == 0
        assert p.index is None
        assert p.converter is None
        assert p.big_number is False
        assert p.ignore is False

    def test_csv_property_set_name(self):
        class Demo:
            id = CsvProperty("ID", order=1)
        assert Demo.id.attr_name == "id"
        assert Demo.id.value == "ID"

    def test_csv_property_function_decorator(self):
        class Demo:
            @CsvProperty("姓名", order=2)
            def name(self): ...

        assert hasattr(Demo, "name")
        prop = Demo.name.__csv_property__
        assert isinstance(prop, CsvProperty)
        assert prop.value == "姓名"
        assert prop.attr_name == "name"

    def test_csv_ignore_descriptor_and_decorator(self):
        class Demo:
            remark = CsvIgnore()

            @CsvIgnore()
            def secret(self): ...

        assert Demo.remark.attr_name == "remark"
        assert getattr(Demo.secret, "__csv_ignore__", False) is True

    def test_csv_file_decorator_attaches_meta(self):
        @csv_file("用户列表", delimiter=";", encoding="gbk")
        class Demo:
            pass

        meta = Demo.__csv_file__
        assert isinstance(meta, CsvFile)
        assert meta.file_name == "用户列表"
        assert meta.delimiter == ";"
        assert meta.encoding == "gbk"
        assert meta.has_header is True

    def test_csv_file_defaults(self):
        meta = CsvFile()
        assert meta.delimiter == ","
        assert meta.encoding == "utf-8-sig"
        assert meta.quote_char == '"'
        assert meta.line_terminator == "\r\n"

    def test_resolve_header_fallback(self):
        p = CsvProperty()
        assert p.resolve_header("user_name") == "User Name"
        assert p.resolve_header("userName") == "User Name"
        assert p.resolve_header("id") == "Id"


# ==================== parse_csv_columns 反射解析 ====================

class TestParseColumns:
    def test_explicit_properties_sorted_by_order(self):
        @csv_file("demo")
        class Demo:
            age = CsvProperty("年龄", order=3)
            id = CsvProperty("ID", order=1)
            name = CsvProperty("姓名", order=2)

            def __init__(self, id: int = None, name: str = None, age: int = None):
                self.id = id; self.name = name; self.age = age

        cols = parse_csv_columns(Demo)
        assert [c.attr_name for c in cols] == ["id", "name", "age"]
        assert [c.header for c in cols] == ["ID", "姓名", "年龄"]

    def test_index_overrides_order(self):
        class Demo:
            a = CsvProperty("A", order=1, index=2)
            b = CsvProperty("B", order=2, index=0)
            c = CsvProperty("C", order=3, index=1)

            def __init__(self, a=None, b=None, c=None):
                self.a = a; self.b = b; self.c = c

        cols = parse_csv_columns(Demo)
        assert [c.attr_name for c in cols] == ["b", "c", "a"]

    def test_ignore_field_skipped(self):
        class Demo:
            id = CsvProperty("ID", order=1)
            remark = CsvIgnore()
            name = CsvProperty("姓名", order=2)

            def __init__(self, id=None, name=None, remark=None):
                self.id = id; self.name = name; self.remark = remark

        cols = parse_csv_columns(Demo)
        assert {c.attr_name for c in cols} == {"id", "name"}

    def test_ignore_via_property_flag(self):
        class Demo:
            id = CsvProperty("ID", order=1)
            secret = CsvProperty("秘", order=2, ignore=True)

            def __init__(self, id=None, secret=None):
                self.id = id; self.secret = secret

        cols = parse_csv_columns(Demo)
        assert [c.attr_name for c in cols] == ["id"]

    def test_all_ignored_raises(self):
        class Demo:
            remark = CsvIgnore()

            def __init__(self, remark=None):
                self.remark = remark

        with pytest.raises(CsvPropertyError):
            parse_csv_columns(Demo)

    def test_fallback_to_init_params(self):
        class Demo:
            def __init__(self, id: int = None, name: str = None):
                self.id = id; self.name = name

        cols = parse_csv_columns(Demo)
        # 无 CsvProperty -> 回退 __init__ 参数
        assert {c.attr_name for c in cols} == {"id", "name"}
        assert cols[0].header == "Id"

    def test_type_hints_attached(self):
        class Demo:
            id = CsvProperty("ID", order=1)

            def __init__(self, id: int = None):
                self.id = id

        cols = parse_csv_columns(Demo)
        assert cols[0].py_type is int

    def test_column_model_sort_key(self):
        m = CsvColumnModel("a", "A", 1, None, None, None, False, None)
        assert m.sort_key == (float("inf"), 1, "a")
        m2 = CsvColumnModel("b", "B", 0, 5, None, None, False, None)
        assert m2.sort_key == (5, 0, "b")


# ==================== 转换器 ====================

class TestConverters:
    def test_resolve_by_type(self):
        assert isinstance(resolve_csv_converter(int), IntegerConverter)
        assert isinstance(resolve_csv_converter(float), FloatConverter)
        assert isinstance(resolve_csv_converter(bool), BooleanConverter)
        assert isinstance(resolve_csv_converter(str), StringConverter)
        assert isinstance(resolve_csv_converter(Decimal), BigDecimalConverter)

    def test_integer_converter(self):
        c = IntegerConverter()
        assert c.to_excel(3) == 3
        assert c.from_excel("42") == 42
        assert c.from_excel("") is None
        assert c.from_excel("12.9") == 12  # 容错截断

    def test_float_converter(self):
        c = FloatConverter()
        assert c.to_excel(1.5) == 1.5
        assert c.from_excel("3.14") == pytest.approx(3.14)
        assert c.from_excel("") is None

    def test_boolean_converter_tokens(self):
        c = BooleanConverter()
        assert c.from_excel("true") is True
        assert c.from_excel("1") is True
        assert c.from_excel("是") is True
        assert c.from_excel("false") is False
        assert c.from_excel("0") is False
        assert c.from_excel("否") is False
        assert c.to_excel(True) is True

    def test_date_string_converter(self):
        c = DateStringConverter("%Y-%m-%d")
        d = datetime(2026, 8, 9)
        assert c.to_excel(d) == "2026-08-09"
        assert c.from_excel("2026-08-09") == d

    def test_big_decimal_converter(self):
        c = BigDecimalConverter()
        assert c.to_excel(Decimal("12345678901234567890")) == "12345678901234567890"
        assert c.from_excel("3.14") == Decimal("3.14")

    def test_custom_converter_overrides_type(self):
        class UpperStr(Converter):
            def to_excel(self, value):
                return str(value).upper()

            def from_excel(self, cell_value):
                return str(cell_value).lower() if cell_value else None

        assert isinstance(resolve_csv_converter(str, declared=UpperStr()), UpperStr)

    def test_csv_converter_aliases(self):
        class Mine(CsvConverter):
            def to_excel(self, value):
                return f"[{value}]"

            def from_excel(self, cell_value):
                return f"({cell_value})"

        m = Mine()
        assert m.to_csv("x") == "[x]"
        assert m.from_csv("y") == "(y)"


# ==================== CsvReader ====================

class TestCsvReader:
    def test_read_with_header_match(self):
        @csv_file("users")
        class User:
            id = CsvProperty("ID", order=1)
            name = CsvProperty("姓名", order=2)

            def __init__(self, id: int = None, name: str = None):
                self.id = id; self.name = name

        text = "ID,姓名\n1,Tom\n2,Jerry\n"
        rows = EasyCsv.read(io.StringIO(text), head=User).doRead()
        assert len(rows) == 2
        assert rows[0].id == 1 and rows[0].name == "Tom"
        assert rows[1].id == 2 and rows[1].name == "Jerry"

    def test_read_no_header_position_match(self):
        @csv_file("users", has_header=False)
        class User:
            id = CsvProperty(order=1)
            name = CsvProperty(order=2)

            def __init__(self, id: int = None, name: str = None):
                self.id = id; self.name = name

        text = "1,Tom\n2,Jerry\n"
        rows = EasyCsv.read(io.StringIO(text), head=User).doRead()
        assert rows[0].id == 1 and rows[1].name == "Jerry"

    def test_read_skips_empty_rows(self):
        @csv_file("u")
        class U:
            id = CsvProperty("ID", order=1)

            def __init__(self, id: int = None):
                self.id = id

        text = "ID\n1\n\n2\n"
        rows = EasyCsv.read(io.StringIO(text), head=U).doRead()
        assert [r.id for r in rows] == [1, 2]

    def test_read_custom_delimiter(self):
        @csv_file("u", delimiter="|")
        class U:
            id = CsvProperty("ID", order=1)
            name = CsvProperty("N", order=2)

            def __init__(self, id: int = None, name: str = None):
                self.id = id; self.name = name

        text = "ID|N\n1|Tom\n"
        rows = EasyCsv.read(io.StringIO(text), head=U).doRead()
        assert rows[0].id == 1 and rows[0].name == "Tom"

    def test_read_type_conversion_int_float_bool(self):
        @csv_file("m")
        class M:
            id = CsvProperty("ID", order=1)
            score = CsvProperty("Score", order=2)
            active = CsvProperty("Active", order=3)

            def __init__(self, id: int = None, score: float = None, active: bool = None):
                self.id = id; self.score = score; self.active = active

        text = "ID,Score,Active\n1,95.5,true\n2,80.0,false\n"
        rows = EasyCsv.read(io.StringIO(text), head=M).doRead()
        assert rows[0].id == 1 and rows[0].score == 95.5 and rows[0].active is True
        assert rows[1].active is False

    def test_read_big_number_as_decimal(self):
        @csv_file("m")
        class M:
            amount = CsvProperty("金额", order=1)

            def __init__(self, amount: Decimal = None):
                self.amount = amount

        big = "12345678901234567890.12"
        text = f"金额\n{big}\n"
        rows = EasyCsv.read(io.StringIO(text), head=M).doRead()
        assert rows[0].amount == Decimal(big)

    def test_read_date_format(self):
        @csv_file("m")
        class M:
            ts = CsvProperty("时间", order=1, date_format="%Y-%m-%d")

            def __init__(self, ts: datetime = None):
                self.ts = ts

        text = "时间\n2026-08-09\n"
        rows = EasyCsv.read(io.StringIO(text), head=M).doRead()
        assert rows[0].ts == datetime(2026, 8, 9)

    def test_read_custom_converter(self):
        class TagsConverter(Converter):
            def to_excel(self, value):
                return ";".join(value) if value else ""

            def from_excel(self, cell_value):
                return str(cell_value).split(";") if cell_value else []

        @csv_file("m")
        class M:
            tags = CsvProperty("Tags", order=1, converter=TagsConverter())

            def __init__(self, tags=None):
                self.tags = tags

        text = "Tags\na;b;c\n"
        rows = EasyCsv.read(io.StringIO(text), head=M).doRead()
        assert rows[0].tags == ["a", "b", "c"]

    def test_read_requires_head(self):
        with pytest.raises(CsvReadError):
            EasyCsv.read(io.StringIO("x\n")).doRead()

    def test_read_from_file_path(self, tmp_path):
        @csv_file("u")
        class U:
            id = CsvProperty("ID", order=1)

            def __init__(self, id: int = None):
                self.id = id

        p = tmp_path / "u.csv"
        p.write_text("ID\n1\n2\n", encoding="utf-8-sig")
        rows = read_csv(str(p), U)
        assert [r.id for r in rows] == [1, 2]

    def test_read_conversion_error(self):
        @csv_file("m")
        class M:
            id = CsvProperty("ID", order=1)

            def __init__(self, id: int = None):
                self.id = id

        # IntegerConverter 容错不抛错（返回 None），故用自定义严格转换器触发错误
        class StrictInt(Converter):
            def to_excel(self, value):
                return int(value)

            def from_excel(self, cell_value):
                return int(str(cell_value).strip())

        @csv_file("m2")
        class M2:
            id = CsvProperty("ID", order=1, converter=StrictInt())

            def __init__(self, id: int = None):
                self.id = id

        text = "ID\nnot_int\n"
        with pytest.raises(CsvReadError):
            EasyCsv.read(io.StringIO(text), head=M2).doRead()


# ==================== CsvWriter ====================

class TestCsvWriter:
    def test_write_with_header_and_order(self):
        @csv_file("u")
        class U:
            age = CsvProperty("年龄", order=3)
            id = CsvProperty("ID", order=1)
            name = CsvProperty("姓名", order=2)

            def __init__(self, id=None, name=None, age=None):
                self.id = id; self.name = name; self.age = age

        buf = io.StringIO()
        EasyCsv.write(buf, head=U).doWrite([
            U(id=1, name="Tom", age=18),
            U(id=2, name="Jerry", age=20),
        ])
        out = buf.getvalue()
        lines = out.strip().split("\r\n")
        assert lines[0] == "ID,姓名,年龄"
        assert lines[1] == "1,Tom,18"
        assert lines[2] == "2,Jerry,20"

    def test_write_no_header(self):
        @csv_file("u", has_header=False)
        class U:
            id = CsvProperty(order=1)
            name = CsvProperty(order=2)

            def __init__(self, id=None, name=None):
                self.id = id; self.name = name

        buf = io.StringIO()
        EasyCsv.write(buf, head=U).doWrite([U(id=1, name="Tom")])
        out = buf.getvalue()
        assert out.strip() == "1,Tom"

    def test_write_big_number_preserved(self):
        @csv_file("u")
        class U:
            uid = CsvProperty("UID", order=1, big_number=True)

            def __init__(self, uid=None):
                self.uid = uid

        big = 12345678901234567890
        buf = io.StringIO()
        EasyCsv.write(buf, head=U).doWrite([U(uid=big)])
        out = buf.getvalue()
        assert str(big) in out  # 原样字符串，未被科学计数/截断

    def test_write_date_format(self):
        @csv_file("u")
        class U:
            ts = CsvProperty("时间", order=1, date_format="%Y-%m-%d")

            def __init__(self, ts: datetime = None):
                self.ts = ts

        buf = io.StringIO()
        EasyCsv.write(buf, head=U).doWrite([U(ts=datetime(2026, 8, 9))])
        assert "2026-08-09" in buf.getvalue()

    def test_write_dict_data(self):
        @csv_file("u")
        class U:
            id = CsvProperty("ID", order=1)
            name = CsvProperty("姓名", order=2)

            def __init__(self, id=None, name=None):
                self.id = id; self.name = name

        buf = io.StringIO()
        EasyCsv.write(buf, head=U).doWrite([{"id": 1, "name": "Tom"}])
        assert "1,Tom" in buf.getvalue()

    def test_write_custom_delimiter(self):
        @csv_file("u")
        class U:
            id = CsvProperty("ID", order=1)
            name = CsvProperty("姓名", order=2)

            def __init__(self, id=None, name=None):
                self.id = id; self.name = name

        buf = io.StringIO()
        EasyCsv.write(buf, head=U).delimiter(";").doWrite([U(id=1, name="Tom")])
        out = buf.getvalue()
        assert "ID;姓名" in out
        assert "1;Tom" in out

    def test_write_none_and_bool(self):
        @csv_file("u")
        class U:
            id = CsvProperty("ID", order=1)
            active = CsvProperty("Active", order=2)

            def __init__(self, id: int = None, active: bool = None):
                self.id = id; self.active = active

        buf = io.StringIO()
        EasyCsv.write(buf, head=U).doWrite([U(id=None, active=True)])
        out = buf.getvalue()
        lines = out.strip().split("\r\n")
        assert lines[1] == ",True"  # None -> 空串

    def test_write_requires_head(self):
        with pytest.raises(CsvWriteError):
            EasyCsv.write(io.StringIO()).doWrite([{"a": 1}])

    def test_write_to_file_path(self, tmp_path):
        @csv_file("u")
        class U:
            id = CsvProperty("ID", order=1)

            def __init__(self, id: int = None):
                self.id = id

        p = tmp_path / "out.csv"
        write_csv(str(p), U, [U(id=1), U(id=2)])
        content = p.read_text(encoding="utf-8-sig")
        assert "ID" in content and "1" in content and "2" in content


# ==================== Round-trip 集成 ====================

class TestRoundTrip:
    def test_round_trip_full(self, tmp_path):
        @csv_file("users", delimiter=",")
        class User:
            id = CsvProperty("ID", order=1)
            name = CsvProperty("姓名", order=2)
            age = CsvProperty("年龄", order=3)
            score = CsvProperty("分数", order=4)
            active = CsvProperty("启用", order=5)
            remark = CsvIgnore()

            def __init__(self, id: int = None, name: str = None, age: int = None,
                         score: float = None, active: bool = None, remark: str = None):
                self.id = id; self.name = name; self.age = age
                self.score = score; self.active = active; self.remark = remark

        src = [
            User(id=1, name="Tom", age=18, score=95.5, active=True, remark="x"),
            User(id=2, name="Jerry", age=20, score=80.0, active=False, remark="y"),
        ]
        p = tmp_path / "rt.csv"
        write_csv(str(p), User, src)

        # 读回：remark 不参与读写
        back = read_csv(str(p), User)
        assert len(back) == 2
        assert back[0].id == 1 and back[0].name == "Tom"
        assert back[0].age == 18 and back[0].score == 95.5
        assert back[0].active is True
        assert back[1].active is False
        # remark 未写入列，读回为默认 None
        assert back[0].remark is None

    def test_round_trip_no_header_position(self, tmp_path):
        @csv_file("u", has_header=False)
        class U:
            a = CsvProperty(order=1, index=0)
            b = CsvProperty(order=2, index=1)

            def __init__(self, a: int = None, b: str = None):
                self.a = a; self.b = b

        src = [U(a=1, b="x"), U(a=2, b="y")]
        p = tmp_path / "nh.csv"
        write_csv(str(p), U, src)
        back = read_csv(str(p), U)
        assert back[0].a == 1 and back[0].b == "x"
        assert back[1].a == 2 and back[1].b == "y"

    def test_easycsv_fluent_chain_read(self):
        @csv_file("u")
        class U:
            id = CsvProperty("ID", order=1)

            def __init__(self, id: int = None):
                self.id = id

        text = "ID\n1\n"
        rows = (EasyCsv.read(io.StringIO(text), head=U)
                .has_header(True)
                .delimiter(",")
                .encoding("utf-8")
                .doRead())
        assert rows[0].id == 1
