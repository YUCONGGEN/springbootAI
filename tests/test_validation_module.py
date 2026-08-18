"""SpringBootAI Bean Validation 模块测试 —— 覆盖约束注解/验证器/方法级 AOP。

对齐 tests/test_excel_module.py 的 pytest 风格（class TestXxx + test_* 方法）。
覆盖：14 个约束的单值校验、BeanValidator 反射收集/多字段校验/分组、函数装饰器形式、
@BeanValidate 方法级 AOP（显式参数名 + 自动探测）、ValidationError 汇总。
"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from springbootai.validation import (
    BeanValidator, BeanValidate,
    NotNull, NotBlank, NotEmpty, Size, Min, Max,
    Positive, PositiveOrZero, Negative, NegativeOrZero,
    Pattern, Email, AssertTrue, AssertFalse,
    ConstraintViolation, ValidationError,
)


# ==================== 测试用实体 ====================

class UserDto:
    name = NotBlank(message="姓名不能为空")
    age = Min(0, message="年龄不能为负")
    email = Email()
    password = Size(min=6, max=20)

    def __init__(self, name=None, age=None, email=None, password=None):
        self.name = name
        self.age = age
        self.email = email
        self.password = password


class OrderDto:
    id = NotNull()
    quantity = Positive()
    note = NotEmpty()

    def __init__(self, id=None, quantity=None, note=None):
        self.id = id
        self.quantity = quantity
        self.note = note


# 函数装饰器形式实体
class FuncForm:
    @NotBlank()
    def title(self): ...

    @Size(min=3, max=10)
    def code(self): ...

    def __init__(self, title=None, code=None):
        self.title = title
        self.code = code


# ==================== 单约束校验 ====================

class TestConstraints:
    def test_not_null_pass_and_fail(self):
        assert NotNull().validate("x") is None
        assert NotNull().validate(None) is not None
        assert NotNull().validate("") is None  # 空串允许

    def test_not_blank(self):
        assert NotBlank().validate("abc") is None
        assert NotBlank().validate("  ") is not None
        assert NotBlank().validate(None) is not None
        assert NotBlank().validate(123) is None  # 非字符串不强制

    def test_not_empty(self):
        assert NotEmpty().validate("x") is None
        assert NotEmpty().validate([]) is not None
        assert NotEmpty().validate({}) is not None
        assert NotEmpty().validate(None) is not None
        assert NotEmpty().validate([1]) is None

    def test_size_min_max(self):
        s = Size(min=2, max=4)
        assert s.validate("ab") is None
        assert s.validate("a") is not None
        assert s.validate("abcde") is not None
        assert s.validate([1, 2, 3]) is None
        assert s.validate(None) is None  # null 交给 NotNull

    def test_size_invalid_args(self):
        with pytest.raises(ValueError):
            Size(min=5, max=2)
        with pytest.raises(ValueError):
            Size(min=-1)

    def test_min_max(self):
        assert Min(10).validate(15) is None
        assert Min(10).validate(5) is not None
        assert Max(10).validate(5) is None
        assert Max(10).validate(15) is not None
        # 字符串数值
        assert Min(10).validate("15") is None
        assert Min(10).validate(None) is None

    def test_positive_negative_family(self):
        assert Positive().validate(1) is None
        assert Positive().validate(0) is not None
        assert PositiveOrZero().validate(0) is None
        assert Negative().validate(-1) is None
        assert Negative().validate(0) is not None
        assert NegativeOrZero().validate(0) is None

    def test_pattern(self):
        p = Pattern(r"^\d{4}$")
        assert p.validate("2026") is None
        assert p.validate("abc") is not None
        with pytest.raises(ValueError):
            Pattern(r"(")  # 非法正则

    def test_email(self):
        assert Email().validate("a@b.com") is None
        assert Email().validate("not-email") is not None
        assert Email().validate(None) is None
        assert Email().validate("") is None  # 空串交给 NotBlank

    def test_assert_true_false(self):
        assert AssertTrue().validate(True) is None
        assert AssertTrue().validate(False) is not None
        assert AssertFalse().validate(False) is None
        assert AssertFalse().validate(True) is not None

    def test_custom_message_override(self):
        c = NotBlank(message="自定义")
        assert c.validate("") == "自定义"

    def test_constraint_set_name_and_call(self):
        c = NotBlank()
        c.__set_name__(object, "field_x")
        assert c.attr_name == "field_x"


# ==================== BeanValidator 反射收集 ====================

class TestValidatorReflection:
    def test_collect_constraints_class_attr(self):
        cmap = BeanValidator.get_constraints(UserDto)
        assert "name" in cmap and "age" in cmap
        assert isinstance(cmap["name"][0], NotBlank)
        assert isinstance(cmap["age"][0], Min)

    def test_collect_constraints_function_decorator(self):
        cmap = BeanValidator.get_constraints(FuncForm)
        assert "title" in cmap and "code" in cmap
        assert isinstance(cmap["title"][0], NotBlank)
        assert isinstance(cmap["code"][0], Size)
        # attr_name 回填
        assert cmap["title"][0].attr_name == "title"

    def test_multiple_constraints_per_field(self):
        class Multi:
            x = NotNull()
            x2 = Min(1)
            # 同字段两个约束（描述符实例）
            def __init__(self, x=None): self.x = x
        # 注意：同名字段后定义的描述符会覆盖；这里验证两约束叠加用函数装饰器
        class Multi2:
            @NotNull()
            @Min(1)
            def x(self): ...
            def __init__(self, x=None): self.x = x
        cmap = BeanValidator.get_constraints(Multi2)
        assert len(cmap["x"]) == 2


# ==================== BeanValidator 校验 ====================

class TestBeanValidation:
    def test_valid_object_passes(self):
        u = UserDto(name="Tom", age=18, email="tom@x.com", password="secret1")
        violations = BeanValidator.validate(u)
        assert violations == []

    def test_invalid_object_collects_violations(self):
        u = UserDto(name="", age=-1, email="bad", password="12")
        violations = BeanValidator.validate(u)
        assert len(violations) == 4  # name/age/email/password
        attrs = {v.attr_name for v in violations}
        assert attrs == {"name", "age", "email", "password"}

    def test_validate_or_raise(self):
        u = UserDto(name="Tom", age=18, email="tom@x.com", password="secret1")
        BeanValidator.validate_or_raise(u)  # 不抛
        bad = UserDto(name="", age=-1, email="bad", password="12")
        with pytest.raises(ValidationError) as exc:
            BeanValidator.validate_or_raise(bad)
        assert len(exc.value.violations) == 4
        assert len(exc.value.messages) == 4

    def test_is_valid(self):
        assert BeanValidator.is_valid(UserDto(name="A", age=1, email="a@b.c", password="123456"))
        assert not BeanValidator.is_valid(UserDto(name=""))

    def test_violation_fields(self):
        v = ConstraintViolation("f", 5, NotNull(), "msg")
        assert v.attr_name == "f"
        assert v.value == 5
        assert v.message == "msg"
        assert "NotNull" in repr(v)

    def test_order_dto(self):
        ok = OrderDto(id=1, quantity=3, note="x")
        assert BeanValidator.validate(ok) == []
        bad = OrderDto(id=None, quantity=0, note="")
        vs = BeanValidator.validate(bad)
        assert len(vs) == 3

    def test_none_object_returns_empty(self):
        assert BeanValidator.validate(None) == []


# ==================== @BeanValidate 方法级 AOP ====================

def _apply_aop(cls):
    """模拟 IoC 容器对受管 Bean 方法应用 comprehensive_aop 注解。

    ``@BeanValidate`` 作为元数据注解，包裹发生在 ``apply_annotations``（与
    ``@Validate``/``@Cacheable`` 同一路径）。对齐 Jakarta ``@Validated`` 需
    ``MethodValidationPostProcessor`` 代理的语义：注解本身只声明元数据，代理负责包裹。
    """
    import inspect as _inspect
    from springbootai.aop.comprehensive_aop import apply_annotations

    for name, method in _inspect.getmembers(cls):
        if not name.startswith('_') and _inspect.isfunction(method):
            wrapped = apply_annotations(None, method)
            setattr(cls, name, wrapped)
    return cls()


class TestBeanValidateAop:
    def test_explicit_param_validation_pass(self):
        class Svc:
            @BeanValidate("user")
            def create(self, user: UserDto):
                return f"created:{user.name}"

        svc = _apply_aop(Svc)
        ok = UserDto(name="Tom", age=18, email="t@x.com", password="secret1")
        assert svc.create(ok) == "created:Tom"

    def test_explicit_param_validation_fail(self):
        class Svc:
            @BeanValidate("user")
            def create(self, user: UserDto):
                return "ok"

        svc = _apply_aop(Svc)
        bad = UserDto(name="", age=-1, email="bad", password="12")
        with pytest.raises(ValidationError):
            svc.create(bad)

    def test_auto_detect_by_type_annotation(self):
        class Svc:
            @BeanValidate  # 不传参，自动探测含约束的参数
            def update(self, user: UserDto, flag: bool):
                return ("updated", flag)

        svc = _apply_aop(Svc)
        ok = UserDto(name="Tom", age=18, email="t@x.com", password="secret1")
        assert svc.update(ok, True) == ("updated", True)
        bad = UserDto(name="")
        with pytest.raises(ValidationError):
            svc.update(bad, False)

    def test_bean_validate_registered_in_aop(self):
        # 验证 @BeanValidate 已注册到 comprehensive_aop 分发表
        from springbootai.aop.comprehensive_aop import ANNOTATION_DECORATORS
        from springbootai.validation.aop import BeanValidate as _BV
        assert _BV in ANNOTATION_DECORATORS

    def test_none_param_skipped(self):
        class Svc:
            @BeanValidate("user")
            def create(self, user: UserDto):
                return "ok"
        svc = _apply_aop(Svc)
        # user=None 不校验，直接通过
        assert svc.create(None) == "ok"

    def test_groups_passthrough(self):
        # groups 功能为兼容预留：约束未声明 groups 时始终执行
        class Svc:
            @BeanValidate("user", groups=[int])
            def create(self, user: UserDto):
                return "ok"
        svc = _apply_aop(Svc)
        bad = UserDto(name="")
        with pytest.raises(ValidationError):
            svc.create(bad)

    def test_list_param_names(self):
        # value 传列表：同时校验多个参数
        class Svc:
            @BeanValidate(["user", "order"])
            def merge(self, user: UserDto, order: OrderDto):
                return "ok"
        svc = _apply_aop(Svc)
        ok_user = UserDto(name="Tom", age=18, email="t@x.com", password="secret1")
        ok_order = OrderDto(id=1, quantity=2, note="x")
        assert svc.merge(ok_user, ok_order) == "ok"
        with pytest.raises(ValidationError):
            svc.merge(UserDto(name=""), ok_order)

    def test_unmanaged_class_without_aop_passthrough(self):
        # 未经过 apply_annotations 包裹的裸方法：注解只存元数据，不阻断调用
        class Svc:
            @BeanValidate("user")
            def create(self, user: UserDto):
                return "raw"
        # 不调用 _apply_aop，方法未被代理包裹
        assert Svc().create(UserDto(name="")) == "raw"
        # 元数据已登记
        from springbootai.aop.comprehensive_aop import apply_annotations
        wrapped = apply_annotations(None, Svc.create)
        with pytest.raises(ValidationError):
            wrapped(Svc(), UserDto(name=""))
