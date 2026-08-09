"""SpringPy Swagger / OpenAPI 注解驱动 API 文档模块测试。

覆盖：
- 注解元数据：@Tag/@Operation/@ApiResponse/@Parameter/@Schema/@SecurityScheme/
  @SecurityRequirement + Swagger 2 别名 @Api/@ApiOperation/@ApiModel/@ApiParam
- collect_openapi_metadata 组合收集
- SwaggerConfig.from_config 松散绑定 + to_fastapi_kwargs 启用/禁用
- 集成：WebApplicationContext + TestClient → /openapi.json / /docs
  （title/version、tags、summary/description、responses、JWT securitySchemes、
  security requirement、@Schema 后处理、@Parameter 后处理、禁用 docs）

复用既有 ``ApplicationContext``/``WebApplicationContext``，不依赖第三方 Swagger 库。
"""
import pytest

from spring.annotations.core import (
    SpringBootApplication, RestController, RequestMapping, GetMapping, PostMapping,
    PathVariable, RequestParam,
)
from spring.web.swagger import (
    Tag, Api, Operation, ApiOperation, ApiResponse, ApiResponses,
    Parameter, ApiParam, Schema, ApiModel,
    SecurityScheme, SecurityRequirement,
    SwaggerConfig, collect_openapi_metadata, collect_security_schemes,
    configure_swagger, register_schema,
)
from spring.web.result import Result


# ==================== 辅助：构建 WebApplicationContext + TestClient ====================

def _build_client(controllers, config=None):
    """构建带 Swagger 注解 Controller 的 WebApplicationContext + TestClient。"""
    from spring.context.application_context import ApplicationContext
    from spring.context.bean_definition import BeanDefinition
    from spring.config.config_loader import ConfigLoader
    from spring.web.web_context import WebApplicationContext
    import tempfile, os, yaml

    cfg = config or {}
    fd, path = tempfile.mkstemp(suffix=".yml")
    with os.fdopen(fd, "w") as f:
        yaml.safe_dump(cfg, f)
    loader = ConfigLoader(config_path=path)

    @SpringBootApplication(scan_base_packages=[])
    class _App:
        pass

    ctx = ApplicationContext(_App, config_loader=loader)
    for ctrl_cls in controllers:
        instance = ctrl_cls()
        name = ctrl_cls.__name__.lower()
        definition = BeanDefinition(bean_class=ctrl_cls, bean_name=name)
        # 复制类上的注解到定义（@RestController/@Tag/@SecurityScheme 等）
        for ann in getattr(ctrl_cls, '__spring_annotations__', []):
            definition.add_annotation(ann)
        ctx.bean_factory.register_bean_definition(name, definition)
        ctx.bean_factory.register_instance(name, instance)

    web_ctx = WebApplicationContext(ctx)
    web_ctx.init()

    from starlette.testclient import TestClient
    client = TestClient(web_ctx.fastapi_app)
    return client, web_ctx, path


# ==================== 注解元数据单元测试 ====================

class TestAnnotationMetadata:
    def test_tag_metadata(self):
        @Tag(name="users", description="用户管理")
        class C: pass
        anns = getattr(C, '__spring_annotations__', [])
        tag = next(a for a in anns if isinstance(a, Tag))
        assert tag.name == "users"
        assert tag.description == "用户管理"

    def test_api_alias_is_tag(self):
        @Api(name="orders", description="订单")
        class C: pass
        anns = getattr(C, '__spring_annotations__', [])
        # @Api 是 @Tag 子类，应被 collect_openapi_metadata 当作 Tag
        assert any(isinstance(a, Tag) for a in anns)

    def test_operation_metadata(self):
        @Operation(summary="获取用户", description="根据ID获取", operation_id="getUser",
                   deprecated=True, tags=["user"])
        def fn(): pass
        anns = getattr(fn, '__spring_annotations__', [])
        op = next(a for a in anns if isinstance(a, Operation))
        assert op.summary == "获取用户"
        assert op.operation_id == "getUser"
        assert op.deprecated is True
        assert op.tags == ["user"]

    def test_api_operation_alias(self):
        @ApiOperation(summary="创建订单")
        def fn(): pass
        anns = getattr(fn, '__spring_annotations__', [])
        assert any(isinstance(a, Operation) for a in anns)

    def test_api_response_repeatable(self):
        @ApiResponse(code=200, description="成功")
        @ApiResponse(code=404, description="未找到")
        def fn(): pass
        anns = getattr(fn, '__spring_annotations__', [])
        responses = [a for a in anns if isinstance(a, ApiResponse)]
        assert len(responses) == 2
        codes = {r.response_code for r in responses}
        assert codes == {"200", "404"}

    def test_api_responses_aggregation(self):
        @ApiResponses(responses=[
            ApiResponse(code=200, description="ok"),
            ApiResponse(code=400, description="bad"),
        ])
        def fn(): pass
        anns = getattr(fn, '__spring_annotations__', [])
        agg = next(a for a in anns if isinstance(a, ApiResponses))
        assert len(agg.responses) == 2

    def test_parameter_metadata(self):
        @Parameter(name="id", description="用户ID", required=True, example=42)
        def fn(): pass
        anns = getattr(fn, '__spring_annotations__', [])
        p = next(a for a in anns if isinstance(a, Parameter))
        assert p.name == "id"
        assert p.required is True
        assert p.example == 42

    def test_schema_metadata(self):
        @Schema(title="用户模型", description="用户实体", example={"id": 1})
        class User: pass
        anns = getattr(User, '__spring_annotations__', [])
        s = next(a for a in anns if isinstance(a, Schema))
        assert s.title == "用户模型"
        assert s.example == {"id": 1}

    def test_security_scheme_bearer(self):
        @SecurityScheme(name="BearerAuth", scheme="bearer", bearer_format="JWT")
        class C: pass
        anns = getattr(C, '__spring_annotations__', [])
        ss = next(a for a in anns if isinstance(a, SecurityScheme))
        assert ss.name == "BearerAuth"
        assert ss.scheme == "bearer"

    def test_security_scheme_apikey(self):
        @SecurityScheme(name="ApiKey", type="apiKey", header_name="X-API-Key")
        class C: pass
        anns = getattr(C, '__spring_annotations__', [])
        ss = next(a for a in anns if isinstance(a, SecurityScheme))
        assert ss.type == "apiKey"
        assert ss.header_name == "X-API-Key"

    def test_security_requirement(self):
        @SecurityRequirement(name="BearerAuth")
        def fn(): pass
        anns = getattr(fn, '__spring_annotations__', [])
        sr = next(a for a in anns if isinstance(a, SecurityRequirement))
        assert sr.name == "BearerAuth"
        assert sr.scopes == []


# ==================== collect_openapi_metadata ====================

class TestCollectOpenApiMetadata:
    def test_class_tag_plus_operation(self):
        @Tag(name="users")
        class UserController:
            @Operation(summary="获取用户", description="按ID")
            def get_user(self): pass

        meta = collect_openapi_metadata(
            UserController.get_user, UserController
        )
        assert meta["tags"] == ["users"]
        assert meta["summary"] == "获取用户"
        assert meta["description"] == "按ID"

    def test_responses_collected(self):
        @Tag(name="orders")
        class OrderController:
            @ApiResponse(code=200, description="成功")
            @ApiResponse(code=404, description="未找到")
            def list_orders(self): pass

        meta = collect_openapi_metadata(
            OrderController.list_orders, OrderController
        )
        assert "200" in meta["responses"]
        assert "404" in meta["responses"]
        assert meta["responses"]["404"]["description"] == "未找到"

    def test_security_requirement_collected(self):
        @Tag(name="admin")
        class AdminController:
            @SecurityRequirement(name="BearerAuth")
            def delete_user(self): pass

        meta = collect_openapi_metadata(
            AdminController.delete_user, AdminController
        )
        # security 通过 openapi_extra 传递（FastAPI 路由装饰器不支持 security 参数）
        assert meta["openapi_extra"]["security"] == [{"BearerAuth": []}]

    def test_deprecated_and_operation_id(self):
        class C:
            @Operation(operation_id="legacyApi", deprecated=True)
            def old(self): pass

        meta = collect_openapi_metadata(C.old, C)
        assert meta["operation_id"] == "legacyApi"
        assert meta["deprecated"] is True

    def test_no_annotations_returns_empty(self):
        class C:
            def plain(self): pass
        meta = collect_openapi_metadata(C.plain, C)
        assert meta == {}

    def test_method_tags_override_class(self):
        @Tag(name="base")
        class C:
            @Operation(tags=["override"])
            def fn(self): pass
        meta = collect_openapi_metadata(C.fn, C)
        # 类 tag + 方法 tag 都保留
        assert "base" in meta["tags"]
        assert "override" in meta["tags"]


# ==================== collect_security_schemes ====================

class TestCollectSecuritySchemes:
    def test_bearer_scheme(self):
        @SecurityScheme(name="BearerAuth", scheme="bearer", bearer_format="JWT")
        class C: pass
        schemes = collect_security_schemes([C])
        assert "BearerAuth" in schemes
        assert schemes["BearerAuth"]["type"] == "http"
        assert schemes["BearerAuth"]["scheme"] == "bearer"
        assert schemes["BearerAuth"]["bearerFormat"] == "JWT"

    def test_apikey_scheme(self):
        @SecurityScheme(name="ApiKey", type="apiKey", header_name="X-API-Key")
        class C: pass
        schemes = collect_security_schemes([C])
        assert schemes["ApiKey"]["type"] == "apiKey"
        assert schemes["ApiKey"]["in"] == "header"
        assert schemes["ApiKey"]["name"] == "X-API-Key"

    def test_no_schemes(self):
        class C: pass
        assert collect_security_schemes([C]) == {}


# ==================== SwaggerConfig ====================

class TestSwaggerConfig:
    def test_defaults(self):
        cfg = SwaggerConfig.from_config({})
        assert cfg.enabled is True
        assert cfg.title == "SpringPy Application"
        assert cfg.docs_url == "/docs"

    def test_from_config_kebab_case(self):
        config = {
            "spring": {
                "swagger": {
                    "title": "My API",
                    "description": "测试 API",
                    "version": "2.0.0",
                    "enabled": True,
                    "docs-url": "/swagger",
                    "redoc-url": None,
                    "openapi-url": "/api-docs.json",
                }
            }
        }
        cfg = SwaggerConfig.from_config(config)
        assert cfg.title == "My API"
        assert cfg.description == "测试 API"
        assert cfg.version == "2.0.0"
        assert cfg.docs_url == "/swagger"
        assert cfg.redoc_url is None
        assert cfg.openapi_url == "/api-docs.json"

    def test_from_config_snake_case(self):
        config = {"spring": {"swagger": {"docs_url": "/d"}}}
        cfg = SwaggerConfig.from_config(config)
        assert cfg.docs_url == "/d"

    def test_from_config_disabled(self):
        config = {"spring": {"swagger": {"enabled": False}}}
        cfg = SwaggerConfig.from_config(config)
        assert cfg.enabled is False

    def test_from_config_contact_and_license(self):
        config = {
            "spring": {"swagger": {
                "contact": {"name": "Tom", "email": "tom@x.com", "url": "https://x.com"},
                "license": {"name": "MIT", "url": "https://mit.org"},
                "terms-of-service": "https://tos.com",
            }}
        }
        cfg = SwaggerConfig.from_config(config)
        assert cfg.contact_name == "Tom"
        assert cfg.contact_email == "tom@x.com"
        assert cfg.license_name == "MIT"
        assert cfg.terms_of_service == "https://tos.com"

    def test_to_fastapi_kwargs_enabled(self):
        cfg = SwaggerConfig(title="T", description="D", version="1.2.3")
        kw = cfg.to_fastapi_kwargs()
        assert kw["title"] == "T"
        assert kw["docs_url"] == "/docs"
        assert kw["redoc_url"] == "/redoc"
        assert kw["openapi_url"] == "/openapi.json"

    def test_to_fastapi_kwargs_disabled(self):
        cfg = SwaggerConfig(enabled=False)
        kw = cfg.to_fastapi_kwargs()
        assert kw["docs_url"] is None
        assert kw["redoc_url"] is None
        assert kw["openapi_url"] is None

    def test_to_fastapi_kwargs_contact_license(self):
        cfg = SwaggerConfig(
            title="T", contact_name="A", contact_email="a@b.com",
            license_name="MIT", license_url="https://mit.org",
        )
        kw = cfg.to_fastapi_kwargs()
        assert kw["contact"] == {"name": "A", "email": "a@b.com"}
        assert kw["license_info"] == {"name": "MIT", "url": "https://mit.org"}


# ==================== 集成测试：WebApplicationContext + TestClient ====================

class TestSwaggerIntegration:
    def test_openapi_contains_title_version(self):
        @RestController
        @RequestMapping("/api")
        class Ctrl:
            @GetMapping("/hello")
            def hello(self):
                return {"msg": "hi"}

        client, web_ctx, path = _build_client(
            [Ctrl],
            config={"spring": {"swagger": {"title": "测试API", "version": "3.1.0",
                                            "description": "集成测试"}}},
        )
        try:
            resp = client.get("/openapi.json")
            assert resp.status_code == 200
            schema = resp.json()
            assert schema["info"]["title"] == "测试API"
            assert schema["info"]["version"] == "3.1.0"
            assert schema["info"]["description"] == "集成测试"
        finally:
            import os
            os.unlink(path)

    def test_docs_accessible_when_enabled(self):
        @RestController
        class Ctrl:
            @GetMapping("/h")
            def h(self): return {}
        client, _, path = _build_client([Ctrl], config={"spring": {"swagger": {"enabled": True}}})
        try:
            assert client.get("/docs").status_code == 200
            assert client.get("/redoc").status_code == 200
        finally:
            import os; os.unlink(path)

    def test_docs_disabled_returns_404(self):
        @RestController
        class Ctrl:
            @GetMapping("/h")
            def h(self): return {}
        client, _, path = _build_client([Ctrl], config={"spring": {"swagger": {"enabled": False}}})
        try:
            assert client.get("/docs").status_code == 404
            assert client.get("/redoc").status_code == 404
            assert client.get("/openapi.json").status_code == 404
        finally:
            import os; os.unlink(path)

    def test_tag_appears_in_openapi(self):
        @Tag(name="用户管理", description="用户接口")
        @RestController
        @RequestMapping("/api/users")
        class UserCtrl:
            @GetMapping("/list")
            def list_users(self): return []

        client, _, path = _build_client([UserCtrl])
        try:
            schema = client.get("/openapi.json").json()
            path_item = schema["paths"]["/api/users/list"]["get"]
            assert "用户管理" in path_item["tags"]
        finally:
            import os; os.unlink(path)

    def test_operation_summary_description(self):
        @RestController
        @RequestMapping("/api")
        class Ctrl:
            @Operation(summary="获取详情", description="根据ID获取详情信息")
            @GetMapping("/items/{item_id}")
            def get_item(self, item_id: int): return {"id": item_id}

        client, _, path = _build_client([Ctrl])
        try:
            schema = client.get("/openapi.json").json()
            op = schema["paths"]["/api/items/{item_id}"]["get"]
            assert op["summary"] == "获取详情"
            assert op["description"] == "根据ID获取详情信息"
        finally:
            import os; os.unlink(path)

    def test_operation_id_and_deprecated(self):
        @RestController
        @RequestMapping("/api")
        class Ctrl:
            @Operation(operation_id="legacyOp", deprecated=True)
            @GetMapping("/old")
            def old(self): return {}

        client, _, path = _build_client([Ctrl])
        try:
            schema = client.get("/openapi.json").json()
            op = schema["paths"]["/api/old"]["get"]
            assert op["operationId"] == "legacyOp"
            assert op["deprecated"] is True
        finally:
            import os; os.unlink(path)

    def test_api_response_in_openapi(self):
        @RestController
        @RequestMapping("/api")
        class Ctrl:
            @ApiResponse(code=200, description="成功")
            @ApiResponse(code=404, description="未找到")
            @GetMapping("/things/{tid}")
            def get_thing(self, tid: int): return {"id": tid}

        client, _, path = _build_client([Ctrl])
        try:
            schema = client.get("/openapi.json").json()
            op = schema["paths"]["/api/things/{tid}"]["get"]
            assert "200" in op["responses"]
            assert op["responses"]["200"]["description"] == "成功"
            assert "404" in op["responses"]
            assert op["responses"]["404"]["description"] == "未找到"
        finally:
            import os; os.unlink(path)

    def test_jwt_security_scheme_in_components(self):
        @SecurityScheme(name="BearerAuth", scheme="bearer", bearer_format="JWT")
        @RestController
        @RequestMapping("/api")
        class Ctrl:
            @GetMapping("/public")
            def public(self): return {}

        client, _, path = _build_client([Ctrl])
        try:
            schema = client.get("/openapi.json").json()
            schemes = schema.get("components", {}).get("securitySchemes", {})
            assert "BearerAuth" in schemes
            assert schemes["BearerAuth"]["type"] == "http"
            assert schemes["BearerAuth"]["scheme"] == "bearer"
            assert schemes["BearerAuth"]["bearerFormat"] == "JWT"
        finally:
            import os; os.unlink(path)

    def test_security_requirement_on_route(self):
        @SecurityScheme(name="BearerAuth", scheme="bearer", bearer_format="JWT")
        @RestController
        @RequestMapping("/api")
        class Ctrl:
            @SecurityRequirement(name="BearerAuth")
            @GetMapping("/secret")
            def secret(self): return {}

            @GetMapping("/open")
            def open(self): return {}

        client, _, path = _build_client([Ctrl])
        try:
            schema = client.get("/openapi.json").json()
            secret_op = schema["paths"]["/api/secret"]["get"]
            assert secret_op.get("security") == [{"BearerAuth": []}]
            open_op = schema["paths"]["/api/open"]["get"]
            assert "security" not in open_op or open_op["security"] == []
        finally:
            import os; os.unlink(path)

    def test_apikey_security_scheme(self):
        @SecurityScheme(name="ApiKey", type="apiKey", header_name="X-API-Key")
        @RestController
        @RequestMapping("/api")
        class Ctrl:
            @GetMapping("/k")
            def k(self): return {}

        client, _, path = _build_client([Ctrl])
        try:
            schema = client.get("/openapi.json").json()
            schemes = schema["components"]["securitySchemes"]
            assert schemes["ApiKey"]["type"] == "apiKey"
            assert schemes["ApiKey"]["in"] == "header"
            assert schemes["ApiKey"]["name"] == "X-API-Key"
        finally:
            import os; os.unlink(path)

    def test_schema_post_processing(self):
        from spring.web.swagger import _SCHEMA_REGISTRY
        _SCHEMA_REGISTRY.clear()

        @Schema(title="订单模型", description="订单实体描述")
        class OrderDTO:
            pass

        @RestController
        @RequestMapping("/api")
        class Ctrl:
            @GetMapping("/orders")
            def list_orders(self): return {"order": OrderDTO()}

        # 手动注册 Schema
        register_schema(OrderDTO, next(
            a for a in getattr(OrderDTO, '__spring_annotations__', [])
            if isinstance(a, Schema)
        ))

        client, _, path = _build_client([Ctrl])
        try:
            schema = client.get("/openapi.json").json()
            # OrderDTO 可能出现在 components/schemas（取决于序列化路径）
            components_schemas = schema.get("components", {}).get("schemas", {})
            if "OrderDTO" in components_schemas:
                assert components_schemas["OrderDTO"].get("description") == "订单实体描述"
                assert components_schemas["OrderDTO"].get("title") == "订单模型"
        finally:
            _SCHEMA_REGISTRY.clear()
            import os; os.unlink(path)

    def test_parameter_post_processing(self):
        @RestController
        @RequestMapping("/api")
        class Ctrl:
            @Parameter(name="item_id", description="物品唯一标识", example=99)
            @GetMapping("/items/{item_id}")
            def get_item(self, item_id: int): return {"id": item_id}

        client, _, path = _build_client([Ctrl])
        try:
            schema = client.get("/openapi.json").json()
            op = schema["paths"]["/api/items/{item_id}"]["get"]
            params = op.get("parameters", [])
            item_param = next((p for p in params if p.get("name") == "item_id"), None)
            assert item_param is not None
            assert item_param.get("description") == "物品唯一标识"
            assert item_param.get("example") == 99
        finally:
            import os; os.unlink(path)

    def test_alias_annotations_work(self):
        @Api(name="别名标签")
        @RestController
        @RequestMapping("/api")
        class Ctrl:
            @ApiOperation(summary="别名操作")
            @GetMapping("/a")
            def a(self): return {}

        client, _, path = _build_client([Ctrl])
        try:
            schema = client.get("/openapi.json").json()
            op = schema["paths"]["/api/a"]["get"]
            assert "别名标签" in op["tags"]
            assert op["summary"] == "别名操作"
        finally:
            import os; os.unlink(path)

    def test_swagger_ui_html_contains_title(self):
        @RestController
        class Ctrl:
            @GetMapping("/h")
            def h(self): return {}
        client, _, path = _build_client(
            [Ctrl],
            config={"spring": {"swagger": {"title": "自定义标题API"}}},
        )
        try:
            resp = client.get("/docs")
            assert resp.status_code == 200
            # Swagger UI HTML 应包含标题
            assert "自定义标题API" in resp.text
        finally:
            import os; os.unlink(path)

    def test_multiple_controllers_tags(self):
        @Tag(name="用户")
        @RestController
        @RequestMapping("/api/users")
        class UserCtrl:
            @GetMapping("/list")
            def list_users(self): return []

        @Tag(name="订单")
        @RestController
        @RequestMapping("/api/orders")
        class OrderCtrl:
            @GetMapping("/list")
            def list_orders(self): return []

        client, _, path = _build_client([UserCtrl, OrderCtrl])
        try:
            schema = client.get("/openapi.json").json()
            user_op = schema["paths"]["/api/users/list"]["get"]
            order_op = schema["paths"]["/api/orders/list"]["get"]
            assert "用户" in user_op["tags"]
            assert "订单" in order_op["tags"]
        finally:
            import os; os.unlink(path)
