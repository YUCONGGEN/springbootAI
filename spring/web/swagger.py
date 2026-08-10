"""SpringBootAI Swagger / OpenAPI 注解驱动 API 文档模块。

对齐 SpringDoc OpenAPI 3 注解体系（``@Tag``/``@Operation``/``@ApiResponse``/
``@Parameter``/``@Schema``/``@SecurityScheme``/``@SecurityRequirement``），
同时提供 Swagger 2 风格别名（``@Api``/``@ApiOperation``/``@ApiModel``/
``@ApiResponses``/``@ApiParam``）以兼容习惯。

设计原则（对齐项目既有范式）：
- 注解复用 ``SpringAnnotation`` 描述符，元数据存入 ``__spring_annotations__``。
- ``collect_openapi_metadata`` 从 Controller 类 + 方法注解反射收集 OpenAPI 元数据，
  供 ``WebApplicationContext._add_route`` 传递给 FastAPI 路由参数。
- ``configure_swagger`` 自定义 ``app.openapi()``，注入全局 ``securitySchemes`` 与
  ``@Schema`` 模型描述（``title``/``description``/``example``）。
- 配置由 ``application.yml`` 的 ``spring.swagger.*`` 驱动，对齐 Spring Boot
  ``springdoc.api-docs.*`` / ``springdoc.swagger-ui.*``。

与 Java Spring 的差异：
- Java 用 ``springdoc-openapi-starter-webmvc-ui`` 自动扫描；本实现由
  ``WebApplicationContext`` 注册路由时同步注入 OpenAPI 元数据，无额外依赖。
- ``@Schema`` 通过后处理 ``components/schemas`` 注入（Pydantic 模型自动生成 schema
  的基础上叠加注解元数据），不支持完整的 OpenAPI Schema 属性全集。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type, Union

from spring.annotations.core import SpringAnnotation, get_spring_annotations

logger = logging.getLogger("Spring.Web.Swagger")


# ============================================================================
# 注解定义（对齐 SpringDoc OpenAPI 3 + Swagger 2 别名）
# ============================================================================

class Tag(SpringAnnotation):
    """类级标签，对齐 ``io.swagger.v3.oas.annotations.tags.Tag``。

    用在 ``@RestController`` 类上，为该 Controller 所有路由分组。
    """

    _annotation_type = "swagger_tag"

    def __init__(self, name: str = "", description: str = ""):
        super().__init__(name=name, description=description)


# Swagger 2 别名
class Api(Tag):
    """``@Api`` —— Swagger 2 风格的 ``@Tag`` 别名。"""

    _annotation_type = "swagger_tag"


class Operation(SpringAnnotation):
    """方法级操作描述，对齐 ``io.swagger.v3.oas.annotations.Operation``。

    用在 ``@GetMapping``/``@PostMapping`` 等方法上，设置 Swagger UI 的
    ``summary``/``description``/``operationId``/``deprecated``/``tags``。
    """

    _annotation_type = "swagger_operation"

    def __init__(
        self,
        summary: str = "",
        description: str = "",
        operation_id: str = "",
        deprecated: bool = False,
        tags: Optional[List[str]] = None,
    ):
        super().__init__(
            summary=summary,
            description=description,
            operation_id=operation_id,
            deprecated=deprecated,
            tags=tags or [],
        )


# Swagger 2 别名
class ApiOperation(Operation):
    """``@ApiOperation`` —— Swagger 2 风格的 ``@Operation`` 别名。"""

    _annotation_type = "swagger_operation"


class ApiResponse(SpringAnnotation):
    """方法级响应描述，对齐 ``io.swagger.v3.oas.annotations.responses.ApiResponse``。

    可重复使用（多个 ``@ApiResponse`` 描述不同状态码）。``response_model`` 为
    Python 类型（Pydantic 模型或普通类），用于生成响应 Schema。
    """

    _annotation_type = "swagger_api_response"

    def __init__(
        self,
        code: Union[int, str] = 200,
        description: str = "",
        response_model: Optional[Type] = None,
    ):
        super().__init__(
            response_code=str(code),
            description=description,
            response_model=response_model,
        )


class ApiResponses(SpringAnnotation):
    """``@ApiResponses`` —— 聚合多个 ``@ApiResponse``（Swagger 2 风格）。

    也支持直接多次使用 ``@ApiResponse``，二者等价。
    """

    _annotation_type = "swagger_api_responses"

    def __init__(self, responses: Optional[List[ApiResponse]] = None):
        super().__init__(responses=responses or [])


class Parameter(SpringAnnotation):
    """参数描述，对齐 ``io.swagger.v3.oas.annotations.Parameter``。

    用在方法上，按 ``name`` 匹配参数（path/query/header），注入 ``description``/
    ``example``/``deprecated``/``required`` 到 OpenAPI schema。
    """

    _annotation_type = "swagger_parameter"

    def __init__(
        self,
        name: str = "",
        description: str = "",
        required: Optional[bool] = None,
        deprecated: bool = False,
        example: Any = None,
    ):
        super().__init__(
            name=name,
            description=description,
            required=required,
            deprecated=deprecated,
            example=example,
        )


# Swagger 2 别名
class ApiParam(Parameter):
    """``@ApiParam`` —— Swagger 2 风格的 ``@Parameter`` 别名。"""

    _annotation_type = "swagger_parameter"


class Schema(SpringAnnotation):
    """模型描述，对齐 ``io.swagger.v3.oas.annotations.media.Schema``。

    用在响应/请求体类型上，设置 ``title``/``description``/``example``。
    通过后处理 ``components/schemas`` 注入。
    """

    _annotation_type = "swagger_schema"

    def __init__(
        self,
        title: str = "",
        description: str = "",
        example: Any = None,
        deprecated: bool = False,
    ):
        super().__init__(
            title=title,
            description=description,
            example=example,
            deprecated=deprecated,
        )


# Swagger 2 别名
class ApiModel(Schema):
    """``@ApiModel`` —— Swagger 2 风格的 ``@Schema`` 别名。"""

    _annotation_type = "swagger_schema"


class SecurityScheme(SpringAnnotation):
    """全局安全方案，对齐 ``io.swagger.v3.oas.annotations.security.SecurityScheme``。

    用在配置类或主类上，声明全局可用的认证方案。常见用法：
    ``@SecurityScheme(name="BearerAuth", scheme="bearer", bearer_format="JWT")``
    生成 OpenAPI ``securitySchemes``，Swagger UI 顶部出现 Authorize 按钮。
    """

    _annotation_type = "swagger_security_scheme"

    def __init__(
        self,
        name: str = "BearerAuth",
        scheme: str = "bearer",            # bearer / basic
        bearer_format: str = "JWT",
        type: str = "http",                # http / apiKey
        in_: str = "header",               # apiKey 时：header / query / cookie
        header_name: str = "Authorization",
        description: str = "",
    ):
        super().__init__(
            name=name,
            scheme=scheme,
            bearer_format=bearer_format,
            type=type,
            in_=in_,
            header_name=header_name,
            description=description,
        )


class SecurityRequirement(SpringAnnotation):
    """方法级安全要求，对齐 ``io.swagger.v3.oas.annotations.security.SecurityRequirement``。

    用在需要认证的方法上，标记该路由需要指定的安全方案。
    Swagger UI 会显示锁图标。
    """

    _annotation_type = "swagger_security_requirement"

    def __init__(self, name: str = "BearerAuth", scopes: Optional[List[str]] = None):
        super().__init__(name=name, scopes=scopes or [])


# ============================================================================
# SwaggerConfig —— 从 application.yml 读取
# ============================================================================

@dataclass
class SwaggerConfig:
    """Swagger/OpenAPI 配置，对齐 ``springdoc.*`` 配置项。

    从 ``application.yml`` 的 ``spring.swagger.*``（或 ``springdoc.*``）读取：
    ``spring.swagger.title`` / ``description`` / ``version`` / ``enabled`` /
    ``docs-url`` / ``redoc-url`` / ``openapi-url`` / ``contact.name`` ...
    """

    enabled: bool = True
    title: str = "SpringBootAI Application"
    description: str = ""
    version: str = "1.0.0"
    terms_of_service: str = ""
    contact_name: str = ""
    contact_email: str = ""
    contact_url: str = ""
    license_name: str = ""
    license_url: str = ""
    docs_url: Optional[str] = "/docs"
    redoc_url: Optional[str] = "/redoc"
    openapi_url: Optional[str] = "/openapi.json"

    @classmethod
    def from_config(cls, config: Any) -> "SwaggerConfig":
        """从配置字典构建。读取 ``spring.swagger.*`` 或 ``springdoc.*``。"""
        if not isinstance(config, dict):
            return cls()
        spring = config.get("spring", {}) if isinstance(config.get("spring"), dict) else {}
        swagger = spring.get("swagger", {}) if isinstance(spring, dict) else {}
        if not isinstance(swagger, dict) or not swagger:
            # 兼容 springdoc.* 顶层配置
            swagger = config.get("springdoc", {}) if isinstance(config.get("springdoc"), dict) else {}
        if not isinstance(swagger, dict):
            return cls()

        def _get(key: str, default: Any = None) -> Any:
            # 松散绑定：kebab-case / snake_case
            if key in swagger:
                return swagger[key]
            alt = key.replace("-", "_")
            if alt in swagger:
                return swagger[alt]
            alt2 = key.replace("_", "-")
            if alt2 in swagger:
                return swagger[alt2]
            return default

        contact = _get("contact", {}) or {}
        if not isinstance(contact, dict):
            contact = {}
        license_info = _get("license", {}) or {}
        if not isinstance(license_info, dict):
            license_info = {}

        def _opt(key: str, default: str = "") -> str:
            v = _get(key, default)
            return v if v is not None else default

        return cls(
            enabled=bool(_get("enabled", True)),
            title=_opt("title", "SpringBootAI Application"),
            description=_opt("description", ""),
            version=_opt("version", "1.0.0"),
            terms_of_service=_opt("terms-of-service", ""),
            contact_name=_opt("contact-name", "") or (contact.get("name", "") if isinstance(contact, dict) else ""),
            contact_email=_opt("contact-email", "") or (contact.get("email", "") if isinstance(contact, dict) else ""),
            contact_url=_opt("contact-url", "") or (contact.get("url", "") if isinstance(contact, dict) else ""),
            license_name=_opt("license-name", "") or (license_info.get("name", "") if isinstance(license_info, dict) else ""),
            license_url=_opt("license-url", "") or (license_info.get("url", "") if isinstance(license_info, dict) else ""),
            docs_url=_get("docs-url", "/docs"),
            redoc_url=_get("redoc-url", "/redoc"),
            openapi_url=_get("openapi-url", "/openapi.json"),
        )

    def to_fastapi_kwargs(self) -> Dict[str, Any]:
        """转换为 ``FastAPI()`` 构造参数。``enabled=False`` 时禁用所有文档端点。"""
        if not self.enabled:
            return dict(
                title=self.title,
                description=self.description,
                version=self.version,
                docs_url=None,
                redoc_url=None,
                openapi_url=None,
            )
        kwargs: Dict[str, Any] = dict(
            title=self.title,
            description=self.description,
            version=self.version,
            docs_url=self.docs_url,
            redoc_url=self.redoc_url,
            openapi_url=self.openapi_url,
        )
        if self.terms_of_service:
            kwargs["terms_of_service"] = self.terms_of_service
        if self.contact_name or self.contact_email or self.contact_url:
            kwargs["contact"] = {
                k: v for k, v in {
                    "name": self.contact_name,
                    "email": self.contact_email,
                    "url": self.contact_url,
                }.items() if v
            }
        if self.license_name:
            lic: Dict[str, Any] = {"name": self.license_name}
            if self.license_url:
                lic["url"] = self.license_url
            kwargs["license_info"] = lic
        return kwargs


# ============================================================================
# 元数据收集
# ============================================================================

def collect_openapi_metadata(
    method: Callable,
    controller_class: Optional[Type] = None,
) -> Dict[str, Any]:
    """从 Controller 方法 + 类的 Swagger 注解收集 OpenAPI 路由元数据。

    返回的 dict 可直接拆包为 FastAPI 路由装饰器参数（``tags``/``summary``/
    ``description``/``operation_id``/``deprecated``/``responses``/``security``）。
    """
    result: Dict[str, Any] = {}

    # ---- 类级 @Tag ----
    class_tags: List[str] = []
    if controller_class is not None:
        for ann in get_spring_annotations(controller_class):
            if isinstance(ann, Tag):
                class_tags.append(ann.name)

    # ---- 方法级注解 ----
    method_annotations = get_spring_annotations(method) or getattr(method, "__spring_annotations__", [])

    operation: Optional[Operation] = None
    responses: Dict[str, Dict[str, Any]] = {}
    security: List[Dict[str, List[str]]] = []
    method_tags: List[str] = []

    for ann in method_annotations:
        if isinstance(ann, Operation):
            operation = ann
            if ann.tags:
                method_tags.extend(ann.tags)
        elif isinstance(ann, ApiResponse):
            code = ann.response_code
            entry: Dict[str, Any] = {"description": ann.description or ""}
            if ann.response_model is not None:
                entry["model"] = ann.response_model
            responses[code] = entry
        elif isinstance(ann, ApiResponses):
            for sub in ann.responses:
                if isinstance(sub, ApiResponse):
                    code = sub.response_code
                    e: Dict[str, Any] = {"description": sub.description or ""}
                    if sub.response_model is not None:
                        e["model"] = sub.response_model
                    responses[code] = e
        elif isinstance(ann, SecurityRequirement):
            security.append({ann.name: ann.scopes})

    # ---- 组装 ----
    tags = class_tags + method_tags
    if tags:
        result["tags"] = tags

    if operation is not None:
        if operation.summary:
            result["summary"] = operation.summary
        if operation.description:
            result["description"] = operation.description
        if operation.operation_id:
            result["operation_id"] = operation.operation_id
        if operation.deprecated:
            result["deprecated"] = True

    if responses:
        result["responses"] = responses

    if security:
        # ``security`` 是 OpenAPI operation 级属性，FastAPI 路由装饰器不支持该参数，
        # 通过 ``openapi_extra`` 合并到 operation schema（对齐 SpringDoc @SecurityRequirement）。
        result["openapi_extra"] = {"security": security}

    return result


def collect_security_schemes(controller_classes: List[Type]) -> Dict[str, Dict[str, Any]]:
    """从 Controller 类（或配置类）收集全局 ``@SecurityScheme`` 注解。

    返回 OpenAPI ``securitySchemes`` 字典：
    ``{"BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}``
    """
    schemes: Dict[str, Dict[str, Any]] = {}
    for cls in controller_classes:
        for ann in get_spring_annotations(cls):
            if isinstance(ann, SecurityScheme):
                schemes[ann.name] = _security_scheme_to_dict(ann)
    return schemes


def _security_scheme_to_dict(ann: SecurityScheme) -> Dict[str, Any]:
    """将 ``@SecurityScheme`` 注解转为 OpenAPI securityScheme 对象。"""
    if ann.type == "apiKey":
        return {
            "type": "apiKey",
            "in": ann.in_,
            "name": ann.header_name,
            "description": ann.description,
        }
    # http (bearer / basic)
    scheme: Dict[str, Any] = {
        "type": "http",
        "scheme": ann.scheme,
        "description": ann.description,
    }
    if ann.scheme == "bearer":
        scheme["bearerFormat"] = ann.bearer_format
    return {k: v for k, v in scheme.items() if v}


# ============================================================================
# Schema 后处理
# ============================================================================

# 注册的 @Schema 元数据：{类: Schema注解}
_SCHEMA_REGISTRY: Dict[Type, Schema] = {}


def register_schema(model_class: Type, schema_ann: Schema) -> None:
    """注册模型类的 ``@Schema`` 元数据，供 ``configure_swagger`` 后处理注入。"""
    _SCHEMA_REGISTRY[model_class] = schema_ann


def _scan_registered_schemas() -> Dict[str, Schema]:
    """扫描所有已注册 ``@Schema`` 的类，返回 ``{类名: Schema注解}``。"""
    result: Dict[str, Schema] = {}
    for cls, ann in _SCHEMA_REGISTRY.items():
        result[cls.__name__] = ann
    return result


def _apply_schema_metadata(openapi_schema: Dict[str, Any]) -> None:
    """后处理：将 ``@Schema`` 注解的 title/description/example 注入到
    ``components/schemas`` 中对应模型。"""
    components = openapi_schema.get("components", {})
    schemas = components.get("schemas", {})
    if not schemas:
        return
    for cls_name, schema_ann in _scan_registered_schemas().items():
        if cls_name in schemas:
            model_schema = schemas[cls_name]
            if schema_ann.title:
                model_schema["title"] = schema_ann.title
            if schema_ann.description:
                model_schema["description"] = schema_ann.description
            if schema_ann.example is not None:
                model_schema["example"] = schema_ann.example
            if schema_ann.deprecated:
                model_schema["deprecated"] = True


def _apply_parameter_metadata(
    openapi_schema: Dict[str, Any],
    method_param_meta: Dict[str, List[Parameter]],
) -> None:
    """后处理：将 ``@Parameter`` 注解的 description/example 注入到对应 path 的
    parameters 中。

    ``method_param_meta``: ``{path:method: [Parameter...]}``，key 为
    ``f"{path}:{http_method}"``（与 ``WebApplicationContext`` 注册时一致）。
    """
    paths = openapi_schema.get("paths", {})
    for path, path_item in paths.items():
        for http_method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            # 用 path:method 作为 key 查找（与注册时一致）
            key = f"{path}:{http_method}"
            params_meta = method_param_meta.get(key, [])
            if not params_meta:
                continue
            params = operation.get("parameters", [])
            for p_meta in params_meta:
                for p in params:
                    if p.get("name") == p_meta.name:
                        if p_meta.description:
                            p["description"] = p_meta.description
                        if p_meta.example is not None:
                            p["example"] = p_meta.example
                        if p_meta.deprecated:
                            p["deprecated"] = True
                        if p_meta.required is not None:
                            p["required"] = p_meta.required
                        break


# ============================================================================
# configure_swagger —— 配置 FastAPI 应用
# ============================================================================

def configure_swagger(
    app: Any,
    swagger_config: Optional[SwaggerConfig] = None,
    security_schemes: Optional[Dict[str, Dict[str, Any]]] = None,
    method_param_meta: Optional[Dict[str, List[Parameter]]] = None,
) -> None:
    """自定义 ``app.openapi()``，注入全局 ``securitySchemes`` 与 ``@Schema``/
    ``@Parameter`` 后处理。

    在 ``WebApplicationContext.init()`` 末尾调用（路由注册完成后）。
    """
    if swagger_config is not None and not swagger_config.enabled:
        # 已在 FastAPI 创建时禁用 docs_url/openapi_url，无需后处理
        return

    security_schemes = security_schemes or {}
    method_param_meta = method_param_meta or {}

    original_openapi = app.openapi

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        try:
            schema = original_openapi()
        except Exception:
            logger.debug("openapi() 生成失败，跳过 Swagger 后处理", exc_info=True)
            return app.openapi_schema or {}
        # 注入全局 securitySchemes
        if security_schemes:
            components = schema.setdefault("components", {})
            components.setdefault("securitySchemes", {}).update(security_schemes)
        # @Schema 后处理
        try:
            _apply_schema_metadata(schema)
        except Exception:
            logger.debug("@Schema 后处理失败", exc_info=True)
        # @Parameter 后处理
        try:
            _apply_parameter_metadata(schema, method_param_meta)
        except Exception:
            logger.debug("@Parameter 后处理失败", exc_info=True)
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi


__all__ = [
    # 注解（OpenAPI 3）
    "Tag", "Operation", "ApiResponse", "ApiResponses",
    "Parameter", "Schema", "SecurityScheme", "SecurityRequirement",
    # 别名（Swagger 2）
    "Api", "ApiOperation", "ApiModel", "ApiParam",
    # 配置
    "SwaggerConfig",
    # 元数据收集
    "collect_openapi_metadata", "collect_security_schemes",
    "register_schema",
    # 配置函数
    "configure_swagger",
]
