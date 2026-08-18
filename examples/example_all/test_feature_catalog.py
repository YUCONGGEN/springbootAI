"""example_all 实时功能目录的回归检查。"""

from springbootai.annotations import __all__ as ANNOTATION_EXPORTS

from example_all.feature_catalog import scan, search, summary


def test_every_public_annotation_has_a_learning_path():
    entries = scan()
    annotation_entries = {
        entry.name: entry
        for entry in entries
        if entry.module == "springbootai.annotations.__init__"
    }

    missing = [name for name in ANNOTATION_EXPORTS if name not in annotation_entries]
    assert not missing, f"Catalog missed public annotations: {missing}"

    uncovered = [
        name for name in ANNOTATION_EXPORTS
        if annotation_entries[name].status != "executable_example"
    ]
    assert not uncovered, f"Annotations need an executable example: {uncovered}"


def test_query_returns_definition_and_learning_material():
    results = search("SpringBootApplication")
    assert any(
        result["name"] == "SpringBootApplication"
        and result["status"] == "executable_example"
        and result["references"]
        for result in results
    )

    optional_results = search("MCPTool")
    assert any(result["snippet"] for result in optional_results)
    assert summary()["framework_entries"] > 0
