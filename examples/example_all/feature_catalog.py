"""example_all 的实时框架功能目录和查询 CLI。

每次查询都会从框架源码重新构建目录，避免新增注解或公开 API 后示例索引过期。
目录记录定义位置、真实示例引用，以及可安全复制的可选集成代码片段。
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .feature_snippets import get_snippet


_EXAMPLE_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _EXAMPLE_ROOT.parents[1]
_FRAMEWORK_ROOT = _PROJECT_ROOT / "springbootai"
_IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".git"}


@dataclass(frozen=True)
class FeatureEntry:
    name: str
    qualified_name: str
    module: str
    kind: str
    source_path: str
    line: int
    references: tuple[str, ...]
    status: str
    snippet: dict[str, str] | None = None


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(_PROJECT_ROOT).with_suffix("").parts)


def _all_names(tree: ast.Module) -> list[str] | None:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                return None
            return [name for name in value if isinstance(name, str)]
    return None


def _top_level_definitions(tree: ast.Module) -> dict[str, tuple[str, int]]:
    definitions: dict[str, tuple[str, int]] = {}
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            definitions[node.name] = (
                "class" if isinstance(node, ast.ClassDef) else "function",
                node.lineno,
            )
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    continue
                definitions[alias.asname or alias.name.split(".")[-1]] = ("re-export", node.lineno)
    return definitions


def _kind(module: str, name: str, definitions: dict[str, tuple[str, int]]) -> str:
    if module.startswith("springbootai.annotations"):
        return "annotation"
    if module.endswith(".annotations") or name.startswith("Enable"):
        return "annotation"
    return definitions.get(name, ("feature", 0))[0]


def _framework_entries() -> list[FeatureEntry]:
    entries: list[FeatureEntry] = []
    for path in sorted(_FRAMEWORK_ROOT.rglob("*.py")):
        if _IGNORED_PARTS.intersection(path.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module = _module_name(path)
        definitions = _top_level_definitions(tree)
        exported = _all_names(tree)
        names = exported if exported is not None else [
            name for name, (kind, _) in definitions.items()
            if not name.startswith("_") and kind in {"class", "function"}
        ]
        for name in dict.fromkeys(names):
            kind, line = definitions.get(name, ("re-export", 1))
            snippet = get_snippet(name)
            entries.append(
                FeatureEntry(
                    name=name,
                    qualified_name=f"{module}.{name}",
                    module=module,
                    kind=_kind(module, name, definitions),
                    source_path=str(path.relative_to(_PROJECT_ROOT)).replace("\\", "/"),
                    line=line,
                    references=(),
                    status="definition_only",
                    snippet=snippet,
                )
            )
    return entries


def _example_references() -> dict[str, tuple[str, ...]]:
    references: dict[str, set[str]] = {}
    excluded = {"feature_catalog.py", "feature_snippets.py", "test_feature_catalog.py"}
    for path in sorted(_EXAMPLE_ROOT.rglob("*.py")):
        if _IGNORED_PARTS.intersection(path.parts) or path.name in excluded:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
        relative = str(path.relative_to(_PROJECT_ROOT)).replace("\\", "/")
        for name in names:
            references.setdefault(name, set()).add(relative)
    return {name: tuple(sorted(paths)) for name, paths in references.items()}


def scan() -> list[FeatureEntry]:
    references = _example_references()
    result: list[FeatureEntry] = []
    for entry in _framework_entries():
        paths = references.get(entry.name, ())
        status = "executable_example" if paths else (
            "copy_ready_snippet" if entry.snippet else "definition_only"
        )
        result.append(
            FeatureEntry(
                **{
                    **asdict(entry),
                    "references": paths,
                    "status": status,
                }
            )
        )
    return result


def search(query: str = "", limit: int = 50) -> list[dict[str, Any]]:
    """按短名称或完整限定名查询注解/功能。"""
    normalized = query.strip().lower()
    entries = scan()
    if normalized:
        exact = [
            entry for entry in entries
            if entry.name.lower() == normalized
            or entry.qualified_name.lower() == normalized
        ]
        partial = [
            entry for entry in entries
            if normalized in entry.name.lower()
            or normalized in entry.qualified_name.lower()
        ]
        ordered = exact + [entry for entry in partial if entry not in exact]
    else:
        ordered = entries
    return [asdict(entry) for entry in ordered[: max(1, limit)]]


def summary() -> dict[str, int]:
    entries = scan()
    return {
        "framework_entries": len(entries),
        "annotations": sum(entry["kind"] == "annotation" for entry in map(asdict, entries)),
        "executable_examples": sum(entry.status == "executable_example" for entry in entries),
        "copy_ready_snippets": sum(entry.status == "copy_ready_snippet" for entry in entries),
        "definition_only": sum(entry.status == "definition_only" for entry in entries),
    }


def render_markdown(entries: Iterable[FeatureEntry]) -> str:
    rows = [
        "# example_all 框架功能目录",
        "",
        "由 feature_catalog.py 生成。可使用 python -m example_all.feature_catalog GetMapping 查询。",
        "",
        "| Name | Kind | Status | Definition | Example references |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in entries:
        references = "<br>".join(entry.references) or "-"
        rows.append(
            f"| {entry.name} | {entry.kind} | {entry.status} | "
            f"{entry.source_path}:{entry.line} | {references} |"
        )
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="查询 example_all 实时框架功能目录")
    parser.add_argument("query", nargs="?", default="", help="annotation or feature name")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--write", action="store_true", help="write FEATURE_CATALOG.md")
    args = parser.parse_args(argv)

    entries = scan()
    if args.write:
        output = _EXAMPLE_ROOT / "FEATURE_CATALOG.md"
        output.write_text(render_markdown(entries), encoding="utf-8")
        print(f"wrote {output}")
    if not args.query:
        print(json.dumps(summary(), ensure_ascii=False, indent=2))
        return 0
    results = search(args.query, args.limit)
    if args.as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for item in results:
            print(f"[{item['status']}] {item['qualified_name']}")
            print(f"  definition: {item['source_path']}:{item['line']}")
            print(f"  examples: {', '.join(item['references']) or '-'}")
            if item["snippet"]:
                print(f"  usage: {item['snippet']['notes']}")
                print(item["snippet"]["code"])
                print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
