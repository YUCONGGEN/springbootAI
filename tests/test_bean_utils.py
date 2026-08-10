"""
BeanUtils 工具类测试（对齐 Spring BeanUtils + Apache Commons BeanUtils）

覆盖：属性复制、忽略、深浅拷贝、嵌套读写、描述符、populate/describe、
dataclass/Pydantic/只读 property/方法排除等场景。
"""
import pytest
from dataclasses import dataclass, field
from typing import Optional

from spring.utils import BeanUtils


# ---------------- 测试夹具 ----------------

class _Address:
    def __init__(self, city="北京", zip_code="100000"):
        self.city = city
        self.zip_code = zip_code


class _User:
    def __init__(self, name="", age=0, address: Optional[_Address] = None):
        self.name = name
        self.age = age
        self.address = address
        self._token = "secret-token"  # 单下划线私有，默认参与复制

    @property
    def display(self):
        """只读 property，复制时应跳过。"""
        return f"{self.name}({self.age})"

    def greet(self):
        """方法，复制时应排除。"""
        return f"hi {self.name}"


@dataclass
class _Product:
    name: str = ""
    price: float = 0.0
    tags: list = field(default_factory=list)


class _ReadOnlyPoint:
    """只读 property 的目标类。"""

    def __init__(self, x=0, y=0):
        self._x = x
        self._y = y

    @property
    def x(self):
        return self._x

    @property
    def y(self):
        return self._y  # 无 setter -> 只读


# ---------------- copy_properties ----------------

class TestCopyProperties:
    def test_basic_copy(self):
        src = _User(name="alice", age=30, address=_Address("上海", "200000"))
        tgt = _User()
        BeanUtils.copy_properties(src, tgt)
        assert tgt.name == "alice"
        assert tgt.age == 30
        assert tgt.address.city == "上海"
        assert tgt.address.zip_code == "200000"

    def test_ignore(self):
        src = _User(name="bob", age=25)
        tgt = _User(name="old", age=99)
        BeanUtils.copy_properties(src, tgt, ignore=["age", "address"])
        assert tgt.name == "bob"          # 已复制
        assert tgt.age == 99              # 被忽略，保留原值
        assert tgt.address is None        # 被忽略

    def test_private_underscore_copied(self):
        """单下划线私有属性默认参与复制。"""
        src = _User(name="cathy")
        src._token = "tok-123"
        tgt = _User()
        BeanUtils.copy_properties(src, tgt)
        assert tgt._token == "tok-123"

    def test_method_and_dunder_excluded(self):
        src = _User(name="dan")
        tgt = _User()
        BeanUtils.copy_properties(src, tgt)
        # 方法不应进入实例属性
        assert callable(tgt.greet)
        assert tgt.greet() == "hi dan"

    def test_readonly_property_skipped(self):
        """目标只读 property 无 setter：copy_properties 不抛异常，且不会 setattr 该 property 本身。"""
        src = _ReadOnlyPoint(x=10, y=20)
        tgt = _ReadOnlyPoint()
        BeanUtils.copy_properties(src, tgt)  # 不应抛异常
        # _x/_y 是可写实例属性，会被复制（单下划线约定私有但可访问）
        assert tgt._x == 10
        assert tgt._y == 20
        # x/y 是无 setter 的 property，不会被 setattr；其值通过 _x 间接体现
        assert tgt.x == 10
        assert tgt.y == 20

    def test_shallow_copy_default(self):
        """默认浅拷贝：嵌套对象共享引用。"""
        src = _User(address=_Address("广州", "510000"))
        tgt = _User()
        BeanUtils.copy_properties(src, tgt)
        assert tgt.address is src.address  # 同一对象

    def test_deep_copy(self):
        """copy_deep=True：嵌套对象独立。"""
        src = _User(address=_Address("深圳", "518000"))
        tgt = _User()
        BeanUtils.copy_properties(src, tgt, copy_deep=True)
        assert tgt.address is not src.address
        assert tgt.address.city == "深圳"
        src.address.city = "变了"
        assert tgt.address.city == "深圳"  # 深拷贝互不影响

    def test_none_source_or_target(self):
        src = _User(name="x")
        BeanUtils.copy_properties(None, src)   # 不应报错
        BeanUtils.copy_properties(src, None)   # 不应报错
        assert src.name == "x"

    def test_dataclass(self):
        src = _Product(name="phone", price=999.0, tags=["a", "b"])
        tgt = _Product()
        BeanUtils.copy_properties(src, tgt)
        assert tgt.name == "phone"
        assert tgt.price == 999.0
        assert tgt.tags == ["a", "b"]

    def test_pydantic_model(self):
        pydantic = pytest.importorskip("pydantic")

        class _PyUser(pydantic.BaseModel):
            name: str = ""
            age: int = 0

        src = _PyUser(name="eve", age=28)
        tgt = _PyUser()
        BeanUtils.copy_properties(src, tgt)
        assert tgt.name == "eve"
        assert tgt.age == 28


# ---------------- copy_property ----------------

class TestCopyProperty:
    def test_copy_single(self):
        src = _User(name="frank", age=40)
        tgt = _User(name="old", age=1)
        assert BeanUtils.copy_property(src, tgt, "name") is True
        assert tgt.name == "frank"
        assert tgt.age == 1  # 未动

    def test_missing_attr(self):
        src = _User(name="g")
        tgt = _User()
        assert BeanUtils.copy_property(src, tgt, "not_exist") is False

    def test_readonly_target(self):
        src = _ReadOnlyPoint(x=5)
        tgt = _ReadOnlyPoint()
        assert BeanUtils.copy_property(src, tgt, "x") is False
        assert tgt.x == 0


# ---------------- clone ----------------

class TestClone:
    def test_shallow_clone(self):
        src = _User(name="hank", age=50, address=_Address("成都", "610000"))
        tgt = BeanUtils.clone(src)
        assert isinstance(tgt, _User)
        assert tgt.name == "hank"
        assert tgt.age == 50
        assert tgt.address is src.address  # 浅拷贝共享

    def test_deep_clone(self):
        src = _User(name="ivy", age=60, address=_Address("重庆", "400000"))
        tgt = BeanUtils.clone(src, deep=True)
        assert tgt.address is not src.address
        assert tgt.address.city == "重庆"
        src.address.city = "改了"
        assert tgt.address.city == "重庆"

    def test_clone_none(self):
        assert BeanUtils.clone(None) is None


# ---------------- 嵌套 get/set property ----------------

class TestNestedAccess:
    def test_get_nested(self):
        src = _User(name="jack", address=_Address("杭州", "310000"))
        assert BeanUtils.get_property(src, "address.city") == "杭州"
        assert BeanUtils.get_property(src, "address.zip_code") == "310000"

    def test_get_nested_missing(self):
        src = _User(name="kate")
        assert BeanUtils.get_property(src, "address.city", default="N/A") == "N/A"

    def test_get_nested_none_middle(self):
        src = _User(name="leo", address=None)
        assert BeanUtils.get_property(src, "address.city", default="empty") == "empty"

    def test_get_from_mapping(self):
        obj = {"user": {"name": "mia"}}
        assert BeanUtils.get_property(obj, "user.name") == "mia"

    def test_set_nested(self):
        src = _User(name="nick", address=_Address("南京", "210000"))
        assert BeanUtils.set_property(src, "address.city", "苏州") is True
        assert src.address.city == "苏州"

    def test_set_nested_none_middle(self):
        src = _User(name="oscar", address=None)
        # 中间节点为 None，无法继续下沉
        assert BeanUtils.set_property(src, "address.city", "无锡") is False

    def test_set_mapping(self):
        obj = {"a": {"b": 1}}
        assert BeanUtils.set_property(obj, "a.b", 2) is True
        assert obj["a"]["b"] == 2

    def test_set_simple(self):
        src = _User()
        assert BeanUtils.set_property(src, "name", "paul") is True
        assert src.name == "paul"


# ---------------- 简单属性 / 描述符 ----------------

class TestSimpleAndDescriptors:
    def test_get_simple_property(self):
        src = _User(name="quinn", age=33)
        assert BeanUtils.get_simple_property(src, "name") == "quinn"
        assert BeanUtils.get_simple_property(src, "missing", default="d") == "d"

    def test_get_property_descriptors(self):
        src = _User(name="ray", age=20, address=_Address())
        desc = BeanUtils.get_property_descriptors(src)
        assert "name" in desc
        assert desc["name"] is str
        assert desc["age"] is int
        assert desc["address"] is _Address
        # 方法/dunder 不应出现
        assert "greet" not in desc
        assert "__init__" not in desc

    def test_get_property_descriptor(self):
        src = _User(name="sam", age=40)
        assert BeanUtils.get_property_descriptor(src, "name") is str
        assert BeanUtils.get_property_descriptor(src, "age") is int
        assert BeanUtils.get_property_descriptor(src, "missing") is None


# ---------------- populate / describe ----------------

class TestPopulateDescribe:
    def test_populate(self):
        tgt = _User()
        BeanUtils.populate(tgt, {"name": "tom", "age": 18, "address": _Address("天津", "300000")})
        assert tgt.name == "tom"
        assert tgt.age == 18
        assert tgt.address.city == "天津"

    def test_populate_skip_unwritable(self):
        tgt = _ReadOnlyPoint()
        # x/y 只读，应被跳过
        BeanUtils.populate(tgt, {"x": 10, "y": 20})
        assert tgt.x == 0
        assert tgt.y == 0

    def test_populate_none_or_empty(self):
        tgt = _User(name="keep")
        BeanUtils.populate(tgt, None)
        BeanUtils.populate(tgt, {})
        assert tgt.name == "keep"

    def test_describe(self):
        src = _User(name="uma", age=22, address=_Address("武汉", "430000"))
        d = BeanUtils.describe(src)
        assert d["name"] == "uma"
        assert d["age"] == 22
        assert d["address"].city == "武汉"
        assert "_token" in d  # 单下划线参与
        assert "greet" not in d  # 方法排除
        # property（display）的 getter 返回值会被 describe 收集
        assert "display" in d
        assert d["display"] == "uma(22)"

    def test_describe_none(self):
        assert BeanUtils.describe(None) == {}


# ---------------- 顶层导出 ----------------

class TestExport:
    def test_export_from_spring_utils(self):
        from spring.utils import BeanUtils as BU
        assert BU is BeanUtils

    def test_export_from_spring_top(self):
        import spring
        # 顶层 spring.utils 应可访问 BeanUtils
        assert hasattr(spring.utils, "BeanUtils")
