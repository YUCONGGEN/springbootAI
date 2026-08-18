from springbootai.annotations.core import GetMapping, RequestMapping, RestController
from springbootai.web.web_context import WebApplicationContext


@RestController
@RequestMapping("/api/items")
class _RootController:
    @GetMapping("")
    def list_items(self):
        return []


def test_empty_method_mapping_uses_controller_root():
    context = object.__new__(WebApplicationContext)
    context._method_param_meta = {}
    captured = []
    context._create_endpoint = lambda instance, method, path: method
    context._add_route = lambda method, path, endpoint, meta: captured.append((method, path))

    context._register_handler(_RootController(), _RootController.list_items, "/api/items")

    assert captured == [("get", "/api/items")]
