"""SpringBootAI 条件装配注解测试 —— 覆盖 @Conditional / @ConditionalOnProperty /
@ConditionalOnBean / @ConditionalOnMissingBean / @ConditionalOnClass 及合取求值。

对齐 tests/test_validation_module.py 的 pytest 风格。条件注解的 ``matches(ctx)`` 接收
``ApplicationContext``（访问 ``config_loader`` / ``bean_factory``），故用轻量 mock 上下文
覆盖各分支，并用真实 ``ApplicationContext`` 验证 ``_matches_conditions`` 集成。
"""
import sys
from pathlib import Path


PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from spring.annotations.conditional import (
    Conditional,
    ConditionalOnProperty,
    ConditionalOnBean,
    ConditionalOnMissingBean,
    ConditionalOnClass,
    CONDITION_ANNOTATIONS,
    all_conditions_match,
)
from spring.annotations.core import Component, get_spring_annotations


# ==================== Mock 上下文 ====================

class _FakeConfigLoader:
    """模拟 ConfigLoader：仅实现 ``get``。"""

    def __init__(self, data=None):
        self._data = data or {}

    def get(self, key, default=None):
        return self._data.get(key, default)


class _FakeBeanDef:
    def __init__(self, bean_class):
        self.bean_class = bean_class


class _FakeBeanFactory:
    """模拟 BeanFactory：仅实现 ``get_bean_names`` 与 ``_bean_definitions``。"""

    def __init__(self, definitions=None):
        self._bean_definitions = definitions or {}

    def get_bean_names(self):
        return list(self._bean_definitions.keys())


class _FakeCtx:
    """模拟 ApplicationContext：含 config_loader / bean_factory。"""

    def __init__(self, config=None, bean_factory=None):
        self.config_loader = config
        self.bean_factory = bean_factory


# ==================== @Conditional ====================

class TestConditional:
    def test_condition_class_instantiated_and_called(self):
        class MyCond:
            def __init__(self):
                self.called = False

            def matches(self, ctx):
                self.called = True
                return ctx is not None

        ann = Conditional(MyCond)
        ctx = _FakeCtx()
        assert ann.matches(ctx) is True

    def test_condition_instance(self):
        class MyCond:
            def matches(self, ctx):
                return ctx.flag

        ann = Conditional(MyCond())
        ctx = _FakeCtx()
        ctx.flag = True
        assert ann.matches(ctx) is True
        ctx.flag = False
        assert ann.matches(ctx) is False

    def test_condition_callable(self):
        ann = Conditional(lambda ctx: getattr(ctx, "ok", False))
        ctx = _FakeCtx()
        ctx.ok = True
        assert ann.matches(ctx) is True
        ctx.ok = False
        assert ann.matches(ctx) is False

    def test_condition_class_init_failure_returns_false(self):
        class BadCond:
            def __init__(self):
                raise RuntimeError("boom")

            def matches(self, ctx):
                return True

        assert Conditional(BadCond).matches(_FakeCtx()) is False

    def test_condition_matches_exception_returns_false(self):
        class ExplodingCond:
            def matches(self, ctx):
                raise ValueError("nope")

        assert Conditional(ExplodingCond()).matches(_FakeCtx()) is False

    def test_condition_no_matches_no_callable_returns_true(self):
        # 既无 matches 也不 callable -> 默认 True
        ann = Conditional(object())
        assert ann.matches(_FakeCtx()) is True

    def test_annotation_type_tagged(self):
        assert Conditional._annotation_type == "conditional"
        assert isinstance(Conditional(lambda c: True), CONDITION_ANNOTATIONS)


# ==================== @ConditionalOnProperty ====================

class TestConditionalOnProperty:
    def test_having_value_match(self):
        ctx = _FakeCtx(config=_FakeConfigLoader({"feature.x": "on"}))
        assert ConditionalOnProperty("feature.x", having_value="on").matches(ctx) is True

    def test_having_value_mismatch(self):
        ctx = _FakeCtx(config=_FakeConfigLoader({"feature.x": "off"}))
        assert ConditionalOnProperty("feature.x", having_value="on").matches(ctx) is False

    def test_key_missing_default_false(self):
        ctx = _FakeCtx(config=_FakeConfigLoader({}))
        assert ConditionalOnProperty("feature.x", having_value="on").matches(ctx) is False

    def test_key_missing_match_if_missing(self):
        ctx = _FakeCtx(config=_FakeConfigLoader({}))
        ann = ConditionalOnProperty("feature.x", having_value="on", match_if_missing=True)
        assert ann.matches(ctx) is True

    def test_no_having_value_key_present_matches(self):
        # having_value=None：只要键存在（非 None）即匹配
        ctx = _FakeCtx(config=_FakeConfigLoader({"flag": "anything"}))
        assert ConditionalOnProperty("flag").matches(ctx) is True

    def test_no_having_value_key_missing_respects_match_if_missing(self):
        ctx = _FakeCtx(config=_FakeConfigLoader({}))
        assert ConditionalOnProperty("flag").matches(ctx) is False
        assert ConditionalOnProperty("flag", match_if_missing=True).matches(ctx) is True

    def test_value_is_explicit_none_in_config(self):
        # 配置中显式 None 视为缺失
        ctx = _FakeCtx(config=_FakeConfigLoader({"flag": None}))
        assert ConditionalOnProperty("flag", having_value="x").matches(ctx) is False
        assert ConditionalOnProperty("flag", match_if_missing=True).matches(ctx) is True

    def test_no_config_loader(self):
        ctx = _FakeCtx(config=None)
        assert ConditionalOnProperty("flag").matches(ctx) is False
        assert ConditionalOnProperty("flag", match_if_missing=True).matches(ctx) is True

    def test_loader_get_exception_returns_false(self):
        class BoomLoader:
            def get(self, key, default=None):
                raise RuntimeError("db down")

        ctx = _FakeCtx(config=BoomLoader())
        assert ConditionalOnProperty("flag").matches(ctx) is False


# ==================== @ConditionalOnBean / @ConditionalOnMissingBean ====================

class _SvcA:
    pass


class _SvcB(_SvcA):
    pass


class TestConditionalOnBean:
    def _ctx_with(self, defs):
        return _FakeCtx(bean_factory=_FakeBeanFactory(defs))

    def test_bean_name_present(self):
        ctx = self._ctx_with({"svc_a": _FakeBeanDef(_SvcA)})
        assert ConditionalOnBean(bean_name="svc_a").matches(ctx) is True

    def test_bean_name_absent(self):
        ctx = self._ctx_with({"svc_b": _FakeBeanDef(_SvcB)})
        assert ConditionalOnBean(bean_name="svc_a").matches(ctx) is False

    def test_bean_type_exact_match(self):
        ctx = self._ctx_with({"svc_a": _FakeBeanDef(_SvcA)})
        assert ConditionalOnBean(bean_type=_SvcA).matches(ctx) is True

    def test_bean_type_subtype_match(self):
        # issubclass 语义：注册的是 _SvcB，按 _SvcA 类型应命中
        ctx = self._ctx_with({"svc_b": _FakeBeanDef(_SvcB)})
        assert ConditionalOnBean(bean_type=_SvcA).matches(ctx) is True

    def test_value_alias_as_bean_name(self):
        ctx = self._ctx_with({"svc_a": _FakeBeanDef(_SvcA)})
        assert ConditionalOnBean(value="svc_a").matches(ctx) is True

    def test_no_bean_factory_returns_false(self):
        ctx = _FakeCtx(bean_factory=None)
        assert ConditionalOnBean(bean_name="x").matches(ctx) is False

    def test_get_bean_names_exception_returns_false(self):
        class BoomBf:
            def get_bean_names(self):
                raise RuntimeError()

            _bean_definitions = {}

        ctx = _FakeCtx(bean_factory=BoomBf())
        assert ConditionalOnBean(bean_name="x").matches(ctx) is False


class TestConditionalOnMissingBean:
    def _ctx_with(self, defs):
        return _FakeCtx(bean_factory=_FakeBeanFactory(defs))

    def test_missing_assembles(self):
        ctx = self._ctx_with({})
        assert ConditionalOnMissingBean(bean_name="svc_a").matches(ctx) is True

    def test_present_does_not_assemble(self):
        ctx = self._ctx_with({"svc_a": _FakeBeanDef(_SvcA)})
        assert ConditionalOnMissingBean(bean_name="svc_a").matches(ctx) is False

    def test_missing_by_type(self):
        ctx = self._ctx_with({"svc_b": _FakeBeanDef(_SvcB)})
        assert ConditionalOnMissingBean(bean_type=_SvcA).matches(ctx) is False

    def test_inverse_of_on_bean(self):
        ctx = self._ctx_with({"svc_a": _FakeBeanDef(_SvcA)})
        on_bean = ConditionalOnBean(bean_name="svc_a").matches(ctx)
        on_missing = ConditionalOnMissingBean(bean_name="svc_a").matches(ctx)
        assert on_bean is True and on_missing is False


# ==================== @ConditionalOnClass ====================

class TestConditionalOnClass:
    def test_value_is_real_class(self):
        # 传入真实类类型 -> True
        assert ConditionalOnClass(value=dict).matches(_FakeCtx()) is True

    def test_value_not_a_type(self):
        assert ConditionalOnClass(value="not a type").matches(_FakeCtx()) is False

    def test_name_module_importable(self):
        # 标准库模块可导入
        assert ConditionalOnClass(name="json").matches(_FakeCtx()) is True

    def test_name_module_attr(self):
        # module.attr 形式：json.loads
        assert ConditionalOnClass(name="json.loads").matches(_FakeCtx()) is True

    def test_name_missing_module(self):
        assert ConditionalOnClass(name="definitely_not_a_module_xyz").matches(_FakeCtx()) is False

    def test_name_missing_attr(self):
        assert ConditionalOnClass(name="json.definitely_not_an_attr").matches(_FakeCtx()) is False

    def test_no_args_returns_false(self):
        assert ConditionalOnClass().matches(_FakeCtx()) is False

    def test_nested_attr_path(self):
        # os.path.join
        assert ConditionalOnClass(name="os.path.join").matches(_FakeCtx()) is True


# ==================== all_conditions_match 合取 ====================

class TestAllConditionsMatch:
    def test_no_conditions_matches(self):
        @Component
        class Plain:
            pass

        assert all_conditions_match(Plain, _FakeCtx()) is True

    def test_single_property_match(self):
        @ConditionalOnProperty("flag", having_value="on")
        @Component
        class C:
            pass

        ctx = _FakeCtx(config=_FakeConfigLoader({"flag": "on"}))
        assert all_conditions_match(C, ctx) is True

    def test_single_property_mismatch(self):
        @ConditionalOnProperty("flag", having_value="on")
        @Component
        class C:
            pass

        ctx = _FakeCtx(config=_FakeConfigLoader({"flag": "off"}))
        assert all_conditions_match(C, ctx) is False

    def test_conjunction_all_true(self):
        @ConditionalOnProperty("a", having_value="1")
        @ConditionalOnClass(name="json")
        @Component
        class C:
            pass

        ctx = _FakeCtx(config=_FakeConfigLoader({"a": "1"}))
        assert all_conditions_match(C, ctx) is True

    def test_conjunction_one_false(self):
        @ConditionalOnProperty("a", having_value="1")
        @ConditionalOnClass(name="definitely_not_a_module_xyz")
        @Component
        class C:
            pass

        ctx = _FakeCtx(config=_FakeConfigLoader({"a": "1"}))
        assert all_conditions_match(C, ctx) is False

    def test_non_conditional_annotations_ignored(self):
        # @Component 等非条件注解不参与求值
        @ConditionalOnProperty("a", having_value="1")
        @Component
        class C:
            pass

        ctx = _FakeCtx(config=_FakeConfigLoader({"a": "1"}))
        assert all_conditions_match(C, ctx) is True

    def test_condition_exception_returns_false(self):
        @Conditional(lambda c: (_ for _ in ()).throw(RuntimeError("x")))
        @Component
        class C:
            pass

        assert all_conditions_match(C, _FakeCtx()) is False


# ==================== 集成：ApplicationContext._matches_conditions ====================

class TestApplicationContextIntegration:
    def _make_context(self, config_data):
        from spring.context.application_context import ApplicationContext

        class FakeMain:
            __module__ = __name__

        ctx = ApplicationContext.__new__(ApplicationContext)
        ctx.config_loader = _FakeConfigLoader(config_data)
        ctx.bean_factory = _FakeBeanFactory({})
        ctx.main_class = FakeMain
        return ctx

    def test_matches_conditions_true(self):
        @ConditionalOnProperty("flag", having_value="on")
        @Component
        class C:
            pass

        ctx = self._make_context({"flag": "on"})
        from spring.context.application_context import ApplicationContext
        assert ApplicationContext._matches_conditions(ctx, C) is True

    def test_matches_conditions_false(self):
        @ConditionalOnProperty("flag", having_value="on")
        @Component
        class C:
            pass

        ctx = self._make_context({"flag": "off"})
        from spring.context.application_context import ApplicationContext
        assert ApplicationContext._matches_conditions(ctx, C) is False

    def test_decorator_attaches_annotation(self):
        @ConditionalOnProperty("flag", having_value="on")
        @Component
        class C:
            pass

        anns = get_spring_annotations(C)
        assert any(isinstance(a, ConditionalOnProperty) for a in anns)
