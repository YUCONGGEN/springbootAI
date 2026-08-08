"""Web 注解完整测试 - 覆盖 Controller/RequestMapping/参数绑定/CORS/异常处理等注解。"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import tests._test_helpers  # noqa: F401  安装模块mock

from spring.annotations.core import (
    RestController, Controller, RequestMapping, GetMapping, PostMapping,
    PutMapping, PatchMapping, DeleteMapping, RequestParam, PathVariable,
    RequestBody, RequestHeader, CookieValue, CrossOrigin, ResponseStatus,
    ControllerAdvice, ExceptionHandler, Valid, Validated,
    get_spring_annotations,
)


class TestControllerAnnotations:
    def test_rest_controller_value(self):
        ann = RestController("api")
        assert ann.value == "api"

    def test_rest_controller_default_empty(self):
        ann = RestController()
        assert ann.value == ""

    def test_controller_value(self):
        ann = Controller("web")
        assert ann.value == "web"

    def test_rest_controller_decorates(self):
        @RestController("api")
        class Api:
            pass

        anns = get_spring_annotations(Api)
        assert len(anns) == 1
        assert isinstance(anns[0], RestController)

    def test_controller_decorates(self):
        @Controller()
        class Web:
            pass

        anns = get_spring_annotations(Web)
        assert len(anns) == 1
        assert isinstance(anns[0], Controller)


class TestRequestMapping:
    def test_path_only(self):
        ann = RequestMapping(path="/api")
        assert ann.path == "/api"
        assert ann.method == []

    def test_method_string_uppercased(self):
        ann = RequestMapping(path="/api", method="get")
        assert ann.method == ["GET"]

    def test_method_list_uppercased(self):
        ann = RequestMapping(path="/api", method=["get", "post"])
        assert ann.method == ["GET", "POST"]

    def test_value_alias_for_path(self):
        ann = RequestMapping(value="/api")
        assert ann.path == "/api"

    def test_path_and_value_raises_typeerror(self):
        with pytest.raises(TypeError):
            RequestMapping(path="/a", value="/b")

    def test_consumes_produces(self):
        ann = RequestMapping(
            path="/items",
            method=["get", "post"],
            consumes="application/json",
            produces="application/json",
        )
        assert ann.consumes == "application/json"
        assert ann.produces == "application/json"

    def test_decorates_method(self):
        @RequestMapping("/api")
        def handler():
            pass

        anns = get_spring_annotations(handler)
        assert len(anns) == 1
        assert isinstance(anns[0], RequestMapping)


class TestGetMapping:
    def test_path_sets_method_get(self):
        ann = GetMapping(path="/items")
        assert ann.path == "/items"
        assert ann.method == ["GET"]

    def test_value_alias(self):
        ann = GetMapping(value="/items")
        assert ann.path == "/items"
        assert ann.method == ["GET"]

    def test_path_and_value_raises(self):
        with pytest.raises(TypeError):
            GetMapping(path="/a", value="/b")


class TestPostMapping:
    def test_path_sets_method_post(self):
        ann = PostMapping(path="/items")
        assert ann.method == ["POST"]

    def test_value_alias(self):
        ann = PostMapping("/items")
        assert ann.path == "/items"


class TestPutMapping:
    def test_method_put(self):
        ann = PutMapping(path="/items/{id}")
        assert ann.method == ["PUT"]

    def test_value_alias(self):
        ann = PutMapping("/items/{id}")
        assert ann.path == "/items/{id}"


class TestPatchMapping:
    def test_method_patch(self):
        ann = PatchMapping(path="/items/{id}")
        assert ann.method == ["PATCH"]


class TestDeleteMapping:
    def test_method_delete(self):
        ann = DeleteMapping(path="/items/{id}")
        assert ann.method == ["DELETE"]


class TestRequestParam:
    def test_name(self):
        ann = RequestParam(name="items")
        assert ann.name == "items"
        assert ann.required is True

    def test_value_alias_for_name(self):
        ann = RequestParam(value="items")
        assert ann.name == "items"

    def test_required_false(self):
        ann = RequestParam(name="items", required=False)
        assert ann.required is False

    def test_default_value(self):
        ann = RequestParam(name="count", default=10)
        assert ann.default == 10


class TestPathVariable:
    def test_name(self):
        ann = PathVariable(name="id")
        assert ann.name == "id"
        assert ann.required is True

    def test_value_alias_for_name(self):
        ann = PathVariable(value="id")
        assert ann.name == "id"

    def test_required_false(self):
        ann = PathVariable(name="id", required=False)
        assert ann.required is False


class TestRequestBody:
    def test_default_required(self):
        ann = RequestBody()
        assert ann.required is True

    def test_required_false(self):
        ann = RequestBody(required=False)
        assert ann.required is False

    def test_value_alias_for_required(self):
        ann = RequestBody(value=False)
        assert ann.required is False


class TestRequestHeader:
    def test_name(self):
        ann = RequestHeader(name="X-Trace")
        assert ann.name == "X-Trace"

    def test_value_alias_for_name(self):
        ann = RequestHeader(value="X-Trace")
        assert ann.name == "X-Trace"


class TestCookieValue:
    def test_name(self):
        ann = CookieValue(name="sid")
        assert ann.name == "sid"

    def test_value_alias_for_name(self):
        ann = CookieValue(value="sid")
        assert ann.name == "sid"


class TestCrossOrigin:
    def test_default_origins(self):
        ann = CrossOrigin()
        assert ann.origins == ["*"]
        assert ann.methods == ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
        assert ann.allowedHeaders == ["*"]
        assert ann.allowCredentials is False
        assert ann.maxAge == 3600

    def test_custom_origins_methods(self):
        ann = CrossOrigin(
            origins=["https://example.test"],
            methods=["GET"],
            allowed_headers=["X-Trace"],
            allow_credentials=True,
            max_age=30,
        )
        assert ann.origins == ["https://example.test"]
        assert ann.methods == ["GET"]
        assert ann.allowedHeaders == ["X-Trace"]
        assert ann.allowCredentials is True
        assert ann.maxAge == 30

    def test_snake_case_aliases(self):
        ann = CrossOrigin(
            allowed_headers=["X-A"],
            allow_credentials=True,
            max_age=120,
        )
        assert ann.allowedHeaders == ["X-A"]
        assert ann.allowCredentials is True
        assert ann.maxAge == 120


class TestResponseStatus:
    def test_code_and_reason(self):
        ann = ResponseStatus(201, "created")
        assert ann.code == 201
        assert ann.reason == "created"

    def test_default_reason(self):
        ann = ResponseStatus(404)
        assert ann.code == 404
        assert ann.reason == ""


class TestControllerAdvice:
    def test_default(self):
        ann = ControllerAdvice()
        assert ann._annotation_type == "advice"

    def test_decorates(self):
        @ControllerAdvice()
        class Advice:
            pass

        anns = get_spring_annotations(Advice)
        assert len(anns) == 1
        assert isinstance(anns[0], ControllerAdvice)


class TestExceptionHandler:
    def test_with_exception(self):
        ann = ExceptionHandler(ValueError)
        assert ValueError in ann.value
        assert isinstance(ann.value, list)

    def test_attribute_name_is_value_not_exception(self):
        ann = ExceptionHandler(ValueError, KeyError)
        assert hasattr(ann, "value")
        assert isinstance(ann.value, list)
        assert ValueError in ann.value
        assert KeyError in ann.value

    def test_value_kwarg(self):
        ann = ExceptionHandler(value=[ValueError])
        assert ann.value == [ValueError]

    def test_no_exceptions_empty_list(self):
        ann = ExceptionHandler()
        assert ann.value == []


class TestValidValidated:
    def test_valid_default_groups(self):
        ann = Valid()
        assert ann.groups == []

    def test_valid_with_groups(self):
        class G1:
            pass

        ann = Valid([G1])
        assert ann.groups == [G1]

    def test_validated_default_groups(self):
        ann = Validated()
        assert ann.groups == []

    def test_validated_with_groups(self):
        class G2:
            pass

        ann = Validated([G2])
        assert ann.groups == [G2]

    def test_valid_decorates(self):
        @Valid()
        class Body:
            pass

        anns = get_spring_annotations(Body)
        assert len(anns) == 1
        assert isinstance(anns[0], Valid)


class TestWebAnnotationAttachment:
    def test_all_mapping_annotations_attach(self):
        @DeleteMapping("/items/{id}")
        @PatchMapping("/items/{id}")
        @PutMapping("/items/{id}")
        @PostMapping("/items")
        @GetMapping("/items")
        @RequestMapping("/api")
        def handler():
            pass

        anns = get_spring_annotations(handler)
        types = [type(a) for a in anns]
        # Decorators apply bottom-up: RequestMapping, GetMapping, PostMapping, PutMapping, PatchMapping, DeleteMapping
        assert RequestMapping in types
        assert GetMapping in types
        assert PostMapping in types
        assert PutMapping in types
        assert PatchMapping in types
        assert DeleteMapping in types
        assert len(anns) == 6

    def test_exception_handler_decorates(self):
        @ExceptionHandler(ValueError)
        def handle(exc):
            return None

        anns = get_spring_annotations(handle)
        assert len(anns) == 1
        assert isinstance(anns[0], ExceptionHandler)

    def test_response_status_decorates(self):
        @ResponseStatus(500, "error")
        def handler():
            pass

        anns = get_spring_annotations(handler)
        assert len(anns) == 1
        assert isinstance(anns[0], ResponseStatus)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
