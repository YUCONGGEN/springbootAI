"""Benchmark conditional BeanDefinition assembly without HTTP routing noise."""

import argparse
import json
import math
import sys
import time
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from springbootai.annotations import (
    Component,
    Conditional,
    ConditionalOnBean,
    ConditionalOnClass,
    ConditionalOnMissingBean,
    ConditionalOnProperty,
)
from springbootai.context.application_context import ApplicationContext
from springbootai.context.bean_definition import BeanDefinition
from springbootai.context.bean_factory import BeanFactory


class StaticConfigLoader:
    def __init__(self):
        self._values = {"benchmark.feature": "enabled"}

    def get(self, key, default=None):
        return self._values.get(key, default)


class AssemblyAnchor:
    pass


def make_components(count):
    components = []
    expected_registered = 0
    for index in range(count):
        component = type(
            f"ConditionalAssemblyComponent{index}",
            (),
            {"__module__": __name__},
        )
        component = Component()(component)
        component = ConditionalOnClass(name="springbootai.context.bean_factory.BeanFactory")(component)
        component = ConditionalOnMissingBean(bean_name=f"missing-{index}")(component)
        component = ConditionalOnBean(bean_name="assemblyAnchor")(component)
        expected_value = "disabled" if index % 5 == 0 else "enabled"
        component = ConditionalOnProperty(
            "benchmark.feature", having_value=expected_value
        )(component)
        component = Conditional(lambda context: context is not None)(component)
        components.append(component)
        if expected_value == "enabled":
            expected_registered += 1
    return components, expected_registered


def create_context(loader):
    context = ApplicationContext.__new__(ApplicationContext)
    context.config_loader = loader
    context.bean_factory = BeanFactory(loader)
    context.bean_factory.register_bean_definition(
        "assemblyAnchor",
        BeanDefinition(bean_class=AssemblyAnchor, bean_name="assemblyAnchor"),
    )
    return context


def percentile(values, percent):
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil((percent / 100) * len(ordered)) - 1)
    return ordered[index]


def run_benchmark(iterations, component_count, warmup):
    loader = StaticConfigLoader()
    components, expected_registered = make_components(component_count)
    durations_ms = []
    failures = []

    for current in range(warmup + iterations):
        started = time.perf_counter()
        try:
            context = create_context(loader)
            for component in components:
                ApplicationContext._register_component(context, component)
            actual = context.bean_factory.get_bean_count() - 1
            if actual != expected_registered:
                raise AssertionError(
                    f"registered {actual} components, expected {expected_registered}"
                )
        except Exception as exc:
            failures.append({"iteration": current, "error": str(exc)})
        elapsed_ms = (time.perf_counter() - started) * 1000
        if current >= warmup:
            durations_ms.append(elapsed_ms)

    return {
        "benchmark": "conditional_assembly",
        "iterations": iterations,
        "warmup_iterations": warmup,
        "components_per_iteration": component_count,
        "registered_per_iteration": expected_registered,
        "declared_conditions_per_iteration": component_count * 5,
        "failures": failures,
        "result": {
            "min_ms": min(durations_ms) if durations_ms else None,
            "avg_ms": sum(durations_ms) / len(durations_ms) if durations_ms else None,
            "p50_ms": percentile(durations_ms, 50),
            "p95_ms": percentile(durations_ms, 95),
            "p99_ms": percentile(durations_ms, 99),
            "max_ms": max(durations_ms) if durations_ms else None,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--components", type=int, default=200)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--p95-ms", type=float, default=250)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    if args.iterations < 1 or args.components < 1 or args.warmup < 0:
        parser.error("iterations/components must be positive and warmup cannot be negative")

    report = run_benchmark(args.iterations, args.components, args.warmup)
    report["thresholds"] = {"p95_ms": args.p95_ms}
    report["passed"] = (
        not report["failures"]
        and report["result"]["p95_ms"] is not None
        and report["result"]["p95_ms"] < args.p95_ms
    )
    rendered = json.dumps(report, ensure_ascii=True, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
