"""隔离注解展示示例的回归测试。"""

import inspect

from springbootai.annotations.core import get_spring_annotations

from example_all.annotation_showcase import SHOWCASED_ANNOTATIONS, build_annotation_showcase


def _collect_annotation_names(targets):
    names = set()
    for target in targets.values():
        names.update(type(annotation).__name__ for annotation in get_spring_annotations(target))
        if inspect.isclass(target):
            for member in vars(target).values():
                names.update(
                    type(annotation).__name__
                    for annotation in get_spring_annotations(member)
                )
    return names


def test_all_isolated_annotation_examples_are_real_declarations():
    targets = build_annotation_showcase()
    seen = _collect_annotation_names(targets)

    assert SHOWCASED_ANNOTATIONS <= seen
    assert targets["completed_async_result"]().value == {"status": "completed"}
    bindings = targets["request_binding_defaults"]()
    assert [type(value).__name__ for value in bindings] == [
        "RequestParam", "PathVariable", "RequestBody", "RequestHeader", "CookieValue",
    ]
    templates = targets["messaging_templates"]()
    assert [type(value).__name__ for value in templates] == [
        "RabbitTemplate", "KafkaTemplate", "KafkaTemplate",
    ]
