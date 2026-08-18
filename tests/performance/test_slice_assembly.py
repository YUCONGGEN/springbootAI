"""Measure repeated setup and teardown of SpringBootAI test slices."""

import argparse
import json
import math
import time
from pathlib import Path

from springbootai.annotations import GetMapping, RequestMapping, RestController
from springbootai.orm import Column, Id, entity
from springbootai.test import DataJpaTest, SpringBootTest, WebMvcTest
from springbootai.test.slicing import _MinimalApp


@RequestMapping("/slice")
@RestController
class SliceBenchmarkController:
    @GetMapping("/ping")
    def ping(self):
        return {"kind": "slice", "ok": True}


@entity("slice_benchmark_record")
class SliceBenchmarkRecord:
    record_id = Id(name="id")
    name = Column(name="record_name", nullable=False)

    def __init__(self, record_id=None, name=None):
        self.record_id = record_id
        self.name = name


def percentile(values, percent):
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil((percent / 100) * len(ordered)) - 1)
    return ordered[index]


def summarize(values):
    return {
        "min_ms": min(values) if values else None,
        "avg_ms": sum(values) / len(values) if values else None,
        "p50_ms": percentile(values, 50),
        "p95_ms": percentile(values, 95),
        "p99_ms": percentile(values, 99),
        "max_ms": max(values) if values else None,
    }


def _spring_boot_iteration():
    with SpringBootTest(
        _MinimalApp,
        config={"database": {"enabled": False}, "prometheus": {"enabled": False}},
    ) as test_context:
        if test_context.get_context().get_value("database.enabled") is not False:
            raise AssertionError("SpringBootTest did not load its isolated configuration")


def _web_mvc_iteration():
    with WebMvcTest(controllers=[SliceBenchmarkController]) as mvc:
        paths = {getattr(route, "path", None) for route in mvc.get_app().routes}
        if "/slice/ping" not in paths:
            raise AssertionError("WebMvcTest did not assemble the controller route")


def _data_jpa_iteration():
    with DataJpaTest(entities=[SliceBenchmarkRecord]) as jpa:
        repository = jpa.repository_for(SliceBenchmarkRecord)
        repository.save(SliceBenchmarkRecord(record_id=1, name="benchmark"))
        restored = repository.find_by_id(1)
        if restored is None or restored.name != "benchmark":
            raise AssertionError("DataJpaTest repository round-trip failed")


def run_benchmark(iterations=10, warmup=1):
    runners = {
        "spring_boot_test": _spring_boot_iteration,
        "web_mvc_test": _web_mvc_iteration,
        "data_jpa_test": _data_jpa_iteration,
    }
    measurements = {name: [] for name in runners}
    failures = []

    for name, runner in runners.items():
        for current in range(warmup + iterations):
            started = time.perf_counter()
            try:
                runner()
            except Exception as exc:
                failures.append({
                    "slice": name,
                    "iteration": current,
                    "error": str(exc),
                })
            elapsed_ms = (time.perf_counter() - started) * 1000
            if current >= warmup:
                measurements[name].append(elapsed_ms)

    return {
        "benchmark": "test_slice_assembly",
        "iterations_per_slice": iterations,
        "warmup_iterations_per_slice": warmup,
        "failures": failures,
        "result": {
            name: summarize(values)
            for name, values in measurements.items()
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--p95-ms", type=float, default=1000)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    if args.iterations < 1 or args.warmup < 0 or args.p95_ms <= 0:
        parser.error("iterations/p95-ms must be positive and warmup cannot be negative")

    report = run_benchmark(args.iterations, args.warmup)
    report["thresholds"] = {"p95_ms_per_slice": args.p95_ms}
    report["passed"] = (
        not report["failures"]
        and all(
            values["p95_ms"] is not None and values["p95_ms"] < args.p95_ms
            for values in report["result"].values()
        )
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
