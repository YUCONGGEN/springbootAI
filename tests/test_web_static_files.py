from types import SimpleNamespace

from spring.web.web_context import WebApplicationContext


class _ApplicationContextStub:
    bean_factory = SimpleNamespace(get_bean_names=lambda: [])

    @staticmethod
    def get_config():
        return {}


def test_register_static_files_uses_module_os_import(tmp_path):
    (tmp_path / "index.html").write_text("<main>ok</main>", encoding="utf-8")
    web_context = WebApplicationContext(_ApplicationContextStub(), str(tmp_path))

    web_context._register_static_files()

    paths = {route.path for route in web_context.fastapi_app.routes}
    assert "/" in paths
    assert "/{full_path:path}" in paths
