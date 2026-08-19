"""AOP 切点表达式增强测试。

覆盖新增的 AspectJ 风格切点：
- ``args``：参数类型匹配
- ``@within`` / ``@target``：类级注解匹配
- ``@Order``：切面优先级排序
- 组合表达式（``&&`` / ``||`` / ``!``）
"""
import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from springbootai.aop.aspect import (
    _matches_expression,
    _matches_atom,
    _aspect_order,
    _method_parameter_types,
)
from springbootai.annotations.core import Order, Component, Aspect


class _Target:
    def method_with_str(self, name: str) -> str:
        return name

    def method_with_int(self, count: int) -> int:
        return count

    def method_no_annotations(self, x):
        return x


def _target_class_with_annotation():
    @Component("annotated")
    class _Annotated:
        def run(self):
            pass

    return _Annotated


# ==================== args 切点 ====================


class TestArgsPointcut:
    def test_args_matches_str_parameter(self):
        target = _Target()
        method = target.method_with_str
        assert _matches_expression(
            "args(str)",
            bean_name="target",
            target_class=_Target,
            method=method,
            pointcuts={},
        ) is True

    def test_args_rejects_mismatched_type(self):
        target = _Target()
        method = target.method_with_str
        assert _matches_expression(
            "args(int)",
            bean_name="target",
            target_class=_Target,
            method=method,
            pointcuts={},
        ) is False

    def test_args_matches_multiple_params(self):
        class _Multi:
            def op(self, a: int, b: str):
                pass

        method = _Multi().op
        assert _matches_expression(
            "args(int, str)",
            bean_name="m",
            target_class=_Multi,
            method=method,
            pointcuts={},
        ) is True


# ==================== @within / @target 切点 ====================


class TestWithinTargetPointcut:
    def test_within_matches_class_annotation(self):
        annotated = _target_class_with_annotation()
        method = annotated.run
        assert _matches_expression(
            "@within(Component)",
            bean_name="a",
            target_class=annotated,
            method=method,
            pointcuts={},
        ) is True

    def test_target_matches_class_annotation(self):
        annotated = _target_class_with_annotation()
        method = annotated.run
        assert _matches_expression(
            "@target(Component)",
            bean_name="a",
            target_class=annotated,
            method=method,
            pointcuts={},
        ) is True

    def test_within_rejects_unannotated_class(self):
        method = _Target().method_with_str
        assert _matches_expression(
            "@within(Component)",
            bean_name="a",
            target_class=_Target,
            method=method,
            pointcuts={},
        ) is False


# ==================== 组合表达式 ====================


class TestCombinedExpressions:
    def test_and_combination(self):
        annotated = _target_class_with_annotation()
        method = annotated.run
        # @within(Component) && bean(a) —— 类注解 + Bean 名同时匹配
        expr = "@within(Component) && bean(a)"
        assert _matches_expression(
            expr,
            bean_name="a",
            target_class=annotated,
            method=method,
            pointcuts={},
        ) is True

    def test_or_combination(self):
        method = _Target().method_with_int
        expr = "args(str) || args(int)"
        assert _matches_expression(
            expr,
            bean_name="a",
            target_class=_Target,
            method=method,
            pointcuts={},
        ) is True

    def test_not_combination(self):
        method = _Target().method_with_int
        expr = "!args(str)"
        assert _matches_expression(
            expr,
            bean_name="a",
            target_class=_Target,
            method=method,
            pointcuts={},
        ) is True


# ==================== @Order 优先级 ====================


class TestOrderPriority:
    def test_order_annotation_parses_value(self):
        @Order(5)
        @Aspect
        class _Aspect:
            pass

        assert _aspect_order(_Aspect) == 5

    def test_order_defaults_to_zero(self):
        class _NoOrder:
            pass

        assert _aspect_order(_NoOrder) == 0

    def test_order_get_order_method(self):
        ann = Order(3)
        assert ann.get_order() == 3
        assert ann.value == 3


# ==================== 辅助函数 ====================


class TestParameterTypeExtraction:
    def test_extracts_annotated_types(self):
        target = _Target()
        types_list = _method_parameter_types(target.method_with_str)
        assert types_list == [str]

    def test_unannotated_param_is_object(self):
        target = _Target()
        types_list = _method_parameter_types(target.method_no_annotations)
        assert types_list == [object]
