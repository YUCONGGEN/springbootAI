"""SpringBootAI 项目脚手架。

提供中文交互式 ``init`` 向导和兼容旧版的 ``create_project`` API。生成的项目
默认可以在没有 Redis、MySQL、Nacos 或 AI 服务的机器上启动，并包含统一响应、
全局异常处理、完整配置模板、测试、Docker 文件和中文启动文档。
"""

from __future__ import annotations

import argparse
import keyword
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional


_SUPPORTED_MODULES = ("web", "orm", "ai", "cloud", "redis")
_DATABASE_TYPES = ("none", "sqlite", "mysql", "postgresql")
_MODULE_DESCRIPTIONS = {
    "web": "Web MVC、统一响应、健康检查和 OpenAPI",
    "orm": "MyBatis 风格数据库访问和可扩展 CRUD 示例",
    "ai": "Spring AI 配置骨架和按需调用示例",
    "cloud": "Nacos/Cloud 配置骨架（默认不连接外部服务）",
    "redis": "Redis 客户端配置骨架（默认关闭）",
}


def _atomic_write_text(path: Path, content: str) -> None:
    """Durably replace one generated file without exposing partial content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        try:
            temporary_path.unlink(missing_ok=True)
        finally:
            raise


@dataclass
class ProjectOptions:
    project_path: str
    package: Optional[str] = None
    modules: str = "web"
    port: int = 8000
    database: str = "none"
    redis: bool = False
    ai: bool = False
    cloud: bool = False
    docker: bool = True
    sample_crud: bool = False


def _derive_package_name(project_name: str) -> str:
    """从项目名派生合法 Python 包名。"""
    pkg = re.sub(r"[-\s]+", "_", project_name or "")
    pkg = re.sub(r"[^a-zA-Z0-9_]", "", pkg)
    if pkg and pkg[0].isdigit():
        pkg = "_" + pkg
    return pkg.lower() or "app"


def _validate_package_name(package: str) -> bool:
    return bool(
        isinstance(package, str)
        and re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", package)
        and not keyword.iskeyword(package)
    )


def _normalise_modules(modules: str | Iterable[str] | None) -> List[str]:
    """规范化模块列表并检查拼写。"""
    if modules is None:
        values: List[str] = []
    elif isinstance(modules, str):
        values = [item.strip().lower() for item in modules.split(",")]
    else:
        values = [str(item).strip().lower() for item in modules]
    aliases = {"database": "orm", "mybatis": "orm", "nacos": "cloud", "cache": "redis"}
    result: List[str] = []
    for item in values:
        if not item:
            continue
        item = aliases.get(item, item)
        if item not in _SUPPORTED_MODULES:
            raise ValueError(
                f"模块 '{item}' 不支持，可选模块：{', '.join(_SUPPORTED_MODULES)}"
            )
        if item not in result:
            result.append(item)
    return result or ["web"]


def _as_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "是", "开启", "启用"}:
        return True
    if text in {"0", "false", "no", "n", "off", "否", "关闭", "禁用"}:
        return False
    return default


def _validate_options(options: ProjectOptions) -> ProjectOptions:
    if not str(options.project_path or "").strip():
        raise ValueError("项目目录不能为空")
    modules = _normalise_modules(options.modules)
    package = options.package or _derive_package_name(Path(options.project_path).name)
    if not _validate_package_name(package):
        raise ValueError(f"包名 '{package}' 不合法，必须是 Python 标识符且不能是关键字")
    try:
        port = int(options.port)
    except (TypeError, ValueError) as exc:
        raise ValueError("端口必须是数字") from exc
    if not 1 <= port <= 65535:
        raise ValueError("端口范围必须是 1-65535 (must be between 1 and 65535)")

    database = str(options.database or "none").strip().lower()
    database = {"postgres": "postgresql", "pg": "postgresql", "无": "none"}.get(
        database, database
    )
    if database not in _DATABASE_TYPES:
        raise ValueError(f"数据库类型 '{database}' 不支持，可选：{', '.join(_DATABASE_TYPES)}")
    if database != "none" and "orm" not in modules:
        modules.append("orm")
    if "orm" in modules and database == "none":
        database = "sqlite"

    redis_enabled = _as_bool(options.redis)
    ai_enabled = _as_bool(options.ai)
    cloud_enabled = _as_bool(options.cloud)
    if redis_enabled and "redis" not in modules:
        modules.append("redis")
    if ai_enabled and "ai" not in modules:
        modules.append("ai")
    if cloud_enabled and "cloud" not in modules:
        modules.append("cloud")
    sample_enabled = _as_bool(options.sample_crud, "orm" in modules and "web" in modules)
    if sample_enabled and "web" not in modules:
        modules.append("web")
    return ProjectOptions(
        project_path=str(options.project_path),
        package=package,
        modules=",".join(modules),
        port=port,
        database=database,
        redis=redis_enabled,
        ai=ai_enabled or "ai" in modules,
        cloud=cloud_enabled or "cloud" in modules,
        docker=_as_bool(options.docker, True),
        sample_crud=sample_enabled,
    )


def _read_answer(prompt: str, default: str) -> str:
    suffix = f" [{default}]" if default != "" else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return answer or default


def _read_bool(prompt: str, default: bool) -> bool:
    answer = _read_answer(f"{prompt}（是/否）", "是" if default else "否")
    return _as_bool(answer, default)


def collect_project_options(
    project: Optional[str] = None,
    *,
    package: Optional[str] = None,
    modules: Optional[str] = None,
    port: Optional[int] = None,
    database: Optional[str] = None,
    redis: Optional[bool] = None,
    ai: Optional[bool] = None,
    cloud: Optional[bool] = None,
    docker: Optional[bool] = None,
    sample_crud: Optional[bool] = None,
) -> ProjectOptions:
    """中文问答向导；传入参数会作为问题默认值。"""
    project = _read_answer("项目名称或目录", project or "demo-app")
    derived = _derive_package_name(Path(project).name)
    package = _read_answer("Python 包名（回车自动推导）", package or derived) or None
    modules = _read_answer(
        "功能模块（逗号分隔：web, orm, ai, cloud, redis）", modules or "web"
    )
    port_text = _read_answer("HTTP 端口", str(port or 8000))
    try:
        parsed_port = int(port_text)
    except ValueError:
        parsed_port = 8000
    module_values = _normalise_modules(modules)
    database = _read_answer(
        "数据库类型（none/sqlite/mysql/postgresql）",
        database or ("sqlite" if "orm" in module_values else "none"),
    )
    redis = _read_bool("是否启用 Redis 配置", redis if redis is not None else "redis" in module_values)
    ai = _read_bool("是否启用 AI 配置", ai if ai is not None else "ai" in module_values)
    cloud = _read_bool("是否启用 Cloud/Nacos 配置", cloud if cloud is not None else "cloud" in module_values)
    docker = _read_bool("是否生成 Docker 文件", docker if docker is not None else True)
    sample_crud = _read_bool(
        "是否生成示例 CRUD（需要 ORM）",
        sample_crud if sample_crud is not None else "orm" in module_values,
    )
    return _validate_options(ProjectOptions(
        project_path=project, package=package, modules=modules, port=parsed_port,
        database=database, redis=redis, ai=ai, cloud=cloud, docker=docker,
        sample_crud=sample_crud,
    ))


def _version() -> str:
    try:
        from springbootai import __version__
        return __version__
    except Exception:
        return "2.3.10"


def _replace(template: str, **values: object) -> str:
    """哨兵替换，避免 YAML 的 ``${ENV:default}`` 被 ``str.format`` 解析。"""
    result = template
    for key, value in values.items():
        result = result.replace(f"__{key.upper()}__", str(value))
    return result


_APPLICATION_TEMPLATE = '''"""__PROJECT_NAME__ 的 SpringBootAI 启动入口。"""
from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# 显式导入通用组件，组件扫描会继续扫描整个包。
from __PACKAGE__.common import handlers as _global_handlers  # noqa: F401
try:
    from __PACKAGE__.controllers import *  # noqa: F401,F403
except ImportError:
    # 没有启用 web 模块时仍可启动上下文。
    pass

from springbootai.annotations import SpringBootApplication


@SpringBootApplication(scan_base_packages=["__PACKAGE__"])
class Application:
    """应用启动入口。"""

    @staticmethod
    def main() -> None:
        from springbootai.main import SpringApplication
        SpringApplication(Application).run()


def create_app():
    """供 uvicorn Application:create_app --factory 使用。"""
    from springbootai.main import create_app as _create_app
    return _create_app(Application)


if __name__ == "__main__":
    Application.main()
'''

_INIT_TEMPLATE = '''"""__PROJECT_NAME__ 应用包。"""
'''

_COMMON_INIT = '''"""通用基础组件。"""
from .response import ApiResponse, PageResponse
from .exceptions import BusinessException, ResourceNotFoundException

__all__ = [
    "ApiResponse", "PageResponse", "BusinessException", "ResourceNotFoundException",
]
'''

_RESPONSE_TEMPLATE = '''"""项目层统一 API 响应模型。"""
from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from springbootai.web.result import Result

T = TypeVar("T")


class ApiResponse(Result[T], Generic[T]):
    """沿用框架 Result 字段的项目响应类型。"""

    @classmethod
    def success(cls, data: Optional[T] = None, message: str = "操作成功") -> "ApiResponse[T]":
        return cls(code=200, message=message, data=data)

    @classmethod
    def error(cls, code: int = 500, message: str = "系统处理失败") -> "ApiResponse[T]":
        return cls(code=code, message=message, data=None)


class PageResponse(Generic[T]):
    """轻量分页结构，接入数据库分页时可以直接复用。"""

    def __init__(self, items: list[T], page: int = 1, size: int = 20, total: Optional[int] = None):
        self.items = items
        self.page = max(1, int(page))
        self.size = max(1, int(size))
        self.total = len(items) if total is None else max(0, int(total))

    def to_dict(self) -> dict[str, Any]:
        return {"items": self.items, "page": self.page, "size": self.size, "total": self.total}
'''

_EXCEPTIONS_TEMPLATE = '''"""项目业务异常。"""
from __future__ import annotations


class BusinessException(Exception):
    """可安全展示给客户端的业务错误。"""

    def __init__(self, message: str, code: int = 400, *, detail: object = None):
        super().__init__(message)
        self.message = message
        self.code = int(code)
        self.detail = detail


class ResourceNotFoundException(BusinessException):
    """资源不存在。"""

    def __init__(self, message: str = "资源不存在", *, detail: object = None):
        super().__init__(message, code=404, detail=detail)
'''

_HANDLERS_TEMPLATE = '''"""全局异常处理器。

框架已有兜底异常处理，这里覆盖项目业务异常和参数错误，并隐藏未知异常细节。
"""
from __future__ import annotations

import logging

from springbootai.annotations import ControllerAdvice, ExceptionHandler

from .exceptions import BusinessException, ResourceNotFoundException
from .response import ApiResponse

logger = logging.getLogger("__PACKAGE__.exception")


@ControllerAdvice()
class GlobalExceptionAdvice:
    @ExceptionHandler(value=[ResourceNotFoundException])
    def handle_not_found(self, exc: ResourceNotFoundException) -> ApiResponse:
        return ApiResponse.error(code=404, message=exc.message)

    @ExceptionHandler(value=[BusinessException])
    def handle_business(self, exc: BusinessException) -> ApiResponse:
        return ApiResponse.error(code=exc.code, message=exc.message)

    @ExceptionHandler(ValueError, TypeError)
    def handle_bad_request(self, exc: Exception) -> ApiResponse:
        return ApiResponse.error(code=400, message=str(exc) or "请求参数不正确")

    @ExceptionHandler(Exception)
    def handle_unexpected(self, exc: Exception) -> ApiResponse:
        logger.exception("未处理的请求异常")
        return ApiResponse.error(code=500, message="服务器内部错误")
'''

_CONTROLLERS_INIT = '''"""HTTP 控制器。"""
from .hello_controller import HelloController

__all__ = ["HelloController"]
'''

_HELLO_CONTROLLER = '''"""可直接调用的 Web 示例。"""
from __future__ import annotations

from springbootai.annotations import GetMapping, RequestMapping, RestController

from __PACKAGE__.common import ApiResponse
from __PACKAGE__.common.exceptions import BusinessException


@RestController
@RequestMapping("/api")
class HelloController:
    @GetMapping("/hello")
    def hello(self) -> ApiResponse:
        return ApiResponse.success({"message": "Hello from __PROJECT_NAME__!"})

    @GetMapping("/hello/{name}")
    def hello_name(self, name: str) -> ApiResponse:
        return ApiResponse.success({"message": f"Hello, {name}!"})

    @GetMapping("/echo")
    def echo(self, message: str = "hello") -> ApiResponse:
        return ApiResponse.success({"message": message})

    @GetMapping("/demo-error")
    def demo_error(self) -> ApiResponse:
        raise BusinessException("这是一个示例业务错误", code=422)
'''

_SERVICES_INIT = '''"""业务服务。"""
'''
_MODELS_INIT = '''"""数据模型。"""
'''
_REPOSITORIES_INIT = '''"""数据访问层。"""
'''

_CRUD_MODEL = '''"""示例用户模型（Pydantic，保证无外部数据库也能运行）。"""
from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    email: str = Field(min_length=3, max_length=120)


class User(UserCreate):
    id: int
'''

_CRUD_REPOSITORY = '''"""稳定的内存仓储。

需要 MyBatis 时只替换这个文件为 @Mapper/XML 实现，服务和控制器接口可以保持不变。
"""
from __future__ import annotations

from threading import Lock

from springbootai.annotations import Repository

from __PACKAGE__.models.user import User, UserCreate


@Repository
class UserRepository:
    def __init__(self):
        self._lock = Lock()
        self._next_id = 1
        self._items: dict[int, User] = {}

    def list(self) -> list[User]:
        with self._lock:
            return list(self._items.values())

    def get(self, user_id: int) -> User | None:
        with self._lock:
            return self._items.get(user_id)

    def create(self, data: UserCreate) -> User:
        with self._lock:
            user = User(id=self._next_id, **data.model_dump())
            self._items[user.id] = user
            self._next_id += 1
            return user

    def delete(self, user_id: int) -> bool:
        with self._lock:
            return self._items.pop(user_id, None) is not None
'''

_CRUD_SERVICE = '''"""示例业务服务。"""
from springbootai.annotations import Autowired, Service

from __PACKAGE__.common.exceptions import ResourceNotFoundException
from __PACKAGE__.models.user import UserCreate
from __PACKAGE__.repositories.user_repository import UserRepository


@Service
class UserService:
    @Autowired
    def __init__(self, repository: UserRepository):
        self.repository = repository

    def list(self):
        return [item.model_dump() for item in self.repository.list()]

    def create(self, payload: dict):
        user = self.repository.create(UserCreate.model_validate(payload))
        return user.model_dump()

    def get(self, user_id: int):
        user = self.repository.get(user_id)
        if user is None:
            raise ResourceNotFoundException(f"用户 {user_id} 不存在")
        return user.model_dump()

    def delete(self, user_id: int):
        if not self.repository.delete(user_id):
            raise ResourceNotFoundException(f"用户 {user_id} 不存在")
        return {"deleted": True, "id": user_id}
'''

_CRUD_CONTROLLER = '''"""示例 CRUD 控制器。"""
from springbootai.annotations import Autowired, DeleteMapping, GetMapping, PostMapping, RequestMapping, RestController

from __PACKAGE__.common import ApiResponse
from __PACKAGE__.services.user_service import UserService


@RestController
@RequestMapping("/api/users")
class UserController:
    @Autowired
    def __init__(self, service: UserService):
        self.service = service

    @GetMapping("")
    def list_users(self) -> ApiResponse:
        return ApiResponse.success(self.service.list())

    @GetMapping("/{user_id}")
    def get_user(self, user_id: int) -> ApiResponse:
        return ApiResponse.success(self.service.get(user_id))

    @PostMapping("")
    def create_user(self, payload: dict) -> ApiResponse:
        return ApiResponse.success(self.service.create(payload), message="创建成功")

    @DeleteMapping("/{user_id}")
    def delete_user(self, user_id: int) -> ApiResponse:
        return ApiResponse.success(self.service.delete(user_id), message="删除成功")
'''

_APPLICATION_YML_TEMPLATE = '''# __PROJECT_NAME__ 的 SpringBootAI 配置文件
# 版本：__VERSION__
#
# 配置约定：${ENV_NAME:默认值} 会优先读取环境变量；未设置时使用默认值。
# 默认关闭外部服务，保证 python Application.py 在干净机器上也能启动。
# 生产环境请替换密钥、收紧 CORS，并根据部署要求调整 startup.fail_fast。

server:
  port: __PORT__                         # 可用 SERVER_PORT 覆盖
  host: "${SERVER_HOST:0.0.0.0}"         # 容器中通常使用 0.0.0.0
  debug: false
  shutdown: graceful
  request-id:
    header: "${REQUEST_ID_HEADER:X-Request-ID}"
  compression:
    enabled: false
    min_response_size: 1024
  cors:
    allow_origins: ["http://localhost:3000"]
    allow_credentials: false
    allow_methods: [GET, POST, PUT, PATCH, DELETE, OPTIONS]
    allow_headers: [Content-Type, Authorization, X-Request-ID]
    max_age: 600
  csrf:
    enabled: false                       # Cookie 会话需要时再开启
    token_length: 32
    token_ttl: 3600
    cookie_name: XSRF-TOKEN
    header_name: X-XSRF-TOKEN
    secure_cookie: false                 # HTTPS 生产环境改为 true
    same_site: lax
  thread_pool:
    max_workers: 40
    max_queue: 100
    queue_timeout: 0.1

spring:
  application:
    name: "__PROJECT_NAME__"
  profiles:
    active: "${SPRING_PROFILES_ACTIVE:default}"
  main:
    allow_circular_references: false
  # AI 配置骨架。没有密钥时不会自动调用模型。
  ai:
    enabled: __AI_ENABLED__
    default_provider: "${AI_PROVIDER:openai}"       # openai/ollama/deepseek/moonshot/zhipu
    max_retries: "${AI_MAX_RETRIES:3}"
    retry_delay_ms: "${AI_RETRY_DELAY_MS:500}"
    request_timeout_seconds: "${AI_REQUEST_TIMEOUT_SECONDS:60}"
    max_output_tokens: "${AI_MAX_OUTPUT_TOKENS:4096}"
    max_total_tokens: "${AI_MAX_TOTAL_TOKENS:100000}"
    max_tool_iterations: "${AI_MAX_TOOL_ITERATIONS:5}"
    openai:
      api_key: "${OPENAI_API_KEY:}"
      base_url: "${OPENAI_BASE_URL:https://api.openai.com/v1}"
      chat:
        model: "${OPENAI_CHAT_MODEL:gpt-4o-mini}"
        temperature: "${OPENAI_TEMPERATURE:0.7}"
      embedding:
        model: "${OPENAI_EMBEDDING_MODEL:text-embedding-3-small}"
    ollama:
      base_url: "${OLLAMA_BASE_URL:http://localhost:11434}"
      chat_model: "${OLLAMA_CHAT_MODEL:qwen2.5:7b}"
      embedding_model: "${OLLAMA_EMBEDDING_MODEL:nomic-embed-text}"
    vector_store:
      type: "${AI_VECTOR_STORE:inmemory}"            # inmemory/redis
      collection: "${AI_VECTOR_COLLECTION:default}"
    memory:
      store: "${AI_MEMORY_STORE:inmemory}"           # inmemory/redis
      max_messages: "${AI_MEMORY_MAX:20}"
  # Cloud/Nacos 配置骨架，默认关闭。
  cloud:
    nacos:
      discovery:
        enabled: false
        server_addr: "${NACOS_SERVER_ADDR:127.0.0.1:8848}"
        namespace: "${NACOS_NAMESPACE:}"
        group: "${NACOS_GROUP:DEFAULT_GROUP}"
        username: "${NACOS_USERNAME:nacos}"
        password: "${NACOS_PASSWORD:nacos}"
      config:
        enabled: false
        server_addr: "${NACOS_SERVER_ADDR:127.0.0.1:8848}"
        file_extension: yaml
    config:
      enabled: false
      uri: "${SPRING_CONFIG_URI:http://localhost:8888}"
      profile: "${SPRING_PROFILES_ACTIVE:default}"
      timeout: "${SPRING_CONFIG_TIMEOUT:5000}"
      max-response-size: "${SPRING_CONFIG_MAX_RESPONSE_SIZE:5242880}"
    bus:
      enabled: false
      destination: springCloudBus
  security:
    oauth2:
      enabled: false
      issuer: "${OAUTH2_ISSUER:}"
      jwks_uri: "${OAUTH2_JWKS_URI:}"
      algorithms: [RS256]
  # Kafka 未启用时请保持 enabled=false。
  kafka:
    enabled: false
    bootstrap_servers: "${KAFKA_BOOTSTRAP_SERVERS:localhost:9092}"
    consumer:
      group_id: "${KAFKA_GROUP_ID:__PACKAGE__}"
      auto_offset_reset: earliest
    producer:
      acks: all

startup:
  fail_fast: false                       # 生产可改为 true

app:
  name: "__PROJECT_NAME__"
  version: 1.0.0
  show_error_details: "${APP_SHOW_ERROR_DETAILS:false}"

# 数据库配置：ORM 模块默认使用本地 SQLite；MySQL/PostgreSQL 请填写账号密码。
database:
  enabled: __DB_ENABLED__
  orm: mybatis                            # mybatis/sqlalchemy/both
  driver: __DB_DRIVER__
  host: "${DB_HOST:localhost}"
  port: "${DB_PORT:__DB_PORT__}"
  database: "${DB_NAME:__DB_NAME__}"
  username: "${DB_USERNAME:}"
  password: "${DB_PASSWORD:}"
  url: "${DATABASE_URL:}"
  echo: false
  min_size: 1
  max_size: 5
  max_idle: 3600
  wait_timeout: 30
  validation_interval: 300
  leak_detection_enabled: false
  leak_timeout: 300
  mapper_locations:
    - __PACKAGE__.mappers
  ddl-auto:
    mode: none                           # none/update/create/validate/create-drop
    entity_packages:
      - __PACKAGE__.models
  security:
    block_ddl: true
    sql_injection_detection: false
    sensitive_data_masking: true
  cache:
    enabled: false
    type: lru
    size: 1024
    ttl: 3600

# 兼容旧版 Spring 风格的提示字段。框架实际数据库入口是上面的 database。
# datasource.url / jpa 只作为迁移提示保留，不要与 database 配置混用。
# datasource:
#   url: sqlite:///data/app.db
# jpa:
#   ddl-auto: update

# Redis 默认关闭；timeout 单位为毫秒。
redis:
  enabled: __REDIS_ENABLED__
  host: "${REDIS_HOST:localhost}"
  port: "${REDIS_PORT:6379}"
  db: "${REDIS_DB:0}"
  password: "${REDIS_PASSWORD:}"
  timeout: "${REDIS_TIMEOUT:1000}"
  ssl: false

# JWT 开发环境会在未配置密钥时使用进程级随机密钥；生产必须设置固定密钥。
jwt:
  enabled: true
  secret_key: "${JWT_SECRET_KEY:}"
  algorithm: "${JWT_ALGORITHM:HS256}"
  expiration: "${JWT_EXPIRATION:3600}"
  refresh_expiration: "${JWT_REFRESH_EXPIRATION:604800}"
  issuer: "${JWT_ISSUER:__PROJECT_NAME__}"

# Nacos 服务发现（默认关闭）。开启前安装 nacos-sdk-python 并启动 Nacos。
discovery:
  enabled: false
  server_addr: "${NACOS_SERVER_ADDR:127.0.0.1:8848}"
  namespace: "${NACOS_NAMESPACE:}"
  group: "${NACOS_GROUP:DEFAULT_GROUP}"
  username: "${NACOS_USERNAME:nacos}"
  password: "${NACOS_PASSWORD:nacos}"
  timeout: "${NACOS_TIMEOUT:3}"
  metadata: {}

# RabbitMQ 默认关闭；开启后安装 pika。
rabbitmq:
  enabled: false
  host: "${RABBITMQ_HOST:localhost}"
  port: "${RABBITMQ_PORT:5672}"
  username: "${RABBITMQ_USERNAME:guest}"
  password: "${RABBITMQ_PASSWORD:guest}"
  virtual_host: "${RABBITMQ_VIRTUAL_HOST:/}"
  connection_timeout: "${RABBITMQ_CONNECTION_TIMEOUT:5}"
  socket_timeout: "${RABBITMQ_SOCKET_TIMEOUT:5}"
  stack_timeout: "${RABBITMQ_STACK_TIMEOUT:5}"
  connection_attempts: "${RABBITMQ_CONNECTION_ATTEMPTS:1}"
  retry_delay: "${RABBITMQ_RETRY_DELAY:0}"
  blocked_connection_timeout: "${RABBITMQ_BLOCKED_CONNECTION_TIMEOUT:300}"
  exchange: "${RABBITMQ_EXCHANGE:app.events}"
  queue: "${RABBITMQ_QUEUE:__PROJECT_NAME__.events}"

# Prometheus 默认关闭；开启后安装 prometheus-client。
prometheus:
  enabled: false
  namespace: spring
  subsystem: __PACKAGE__
  port: 9090

# 日志默认写入 logs/，可用 LOG_DIR 指定绝对路径。
logging:
  level: "${LOG_LEVEL:INFO}"
  log_dir: "${LOG_DIR:logs}"
  retention: "${LOG_RETENTION:30 days}"
  rotation: "${LOG_ROTATION:100 MB}"
  diagnose: "${LOG_DIAGNOSE:false}"

# 其他常用配置保留在这里，后续启用对应模块时无需重新查文档。
cache:
  enabled: false
  ttl: 300
  max_size: 1000
retry:
  enabled: true
  default_max_retries: 3
  default_delay: 0.2
tracing:
  enabled: false
  service_name: __PROJECT_NAME__
management:
  endpoints:
    enabled: true
    include: [health, info, metrics, beans, mappings]
'''

_README_TEMPLATE = '''# __PROJECT_NAME__

基于 SpringBootAI __VERSION__ 生成的可运行后端模板。默认不会要求 Redis、MySQL、Nacos
或 AI 服务，先启动接口再按需接入基础设施。

## 快速启动

```bash
python -m venv .venv
# Windows PowerShell
.venv\\Scripts\\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python Application.py
```

常用地址：

* `GET http://127.0.0.1:__PORT__/api/hello`：示例接口
* `GET http://127.0.0.1:__PORT__/actuator/health`：健康检查
* `GET http://127.0.0.1:__PORT__/docs`：OpenAPI 文档
* `GET http://127.0.0.1:__PORT__/api/demo-error`：统一异常示例

统一响应格式：

```json
{"code": 200, "message": "操作成功", "data": {}}
```

## 已选择模块

| 模块 | 作用 |
| --- | --- |
__MODULE_TABLE__

数据库：__DATABASE_NOTE__

## 配置和安全

所有常用配置都在 `config/application.yml`，每个配置项都有中文说明、默认值和环境变量名。
优先通过环境变量覆盖密码、Token 和外部服务地址，不要把真实密钥提交到 Git。
开发环境可以使用 `startup.fail_fast=false`；生产环境建议检查依赖后改为 `true`。

* 数据库文件默认位于 `data/app.db`，可以删除后重新生成。
* Redis、Nacos、RabbitMQ、Kafka、Prometheus 默认关闭，开启前先安装对应依赖。
* AI 只生成配置骨架，调用模型前设置 `OPENAI_API_KEY` 或配置 Ollama。

## Docker

如果生成了 Docker 文件：

```bash
docker compose up --build
docker compose --profile infra up --build
```

基础设施使用 `infra` profile，不会在普通 `docker compose up` 时强行启动。

## 目录结构

```text
__PROJECT_NAME__/
├── Application.py
├── config/application.yml
├── requirements.txt
├── .env.example
├── Dockerfile / docker-compose.yml
├── docs/启动指南.md
├── tests/test_smoke.py
└── src/__PACKAGE__/
    ├── common/
    ├── controllers/
    ├── services/
    ├── repositories/
    └── models/
```

## 下一步

1. 复制 `.env.example` 为 `.env`，只填写当前环境需要的变量。
2. 在 `controllers` 增加路由，在 `services` 编写业务逻辑。
3. 数据库项目优先替换 `repositories` 的内存示例，并添加 Mapper/XML 和迁移脚本。
4. 运行 `python -m pytest` 验证业务代码。
'''

_SMOKE_TEST = '''"""生成项目的最小回归测试。"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def test_generated_layout():
    assert (ROOT / "Application.py").exists()
    assert (ROOT / "config" / "application.yml").exists()


def test_common_components_import():
    from __PACKAGE__.common import ApiResponse
    response = ApiResponse.success({"ok": True})
    assert response.code == 200
    assert response.data == {"ok": True}
'''

_ENV_EXAMPLE = '''# 复制为 .env 后按需填写。不要提交真实密钥。
SERVER_PORT=__PORT__
JWT_SECRET_KEY=请替换为至少32位随机字符串
# DB_HOST=localhost
# DB_USERNAME=root
# DB_PASSWORD=change-me
# REDIS_PASSWORD=
# OPENAI_API_KEY=
# NACOS_USERNAME=nacos
# NACOS_PASSWORD=nacos
'''

_GITIGNORE = '''.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.env
logs/*
!logs/.gitkeep
data/*.db
data/*.sqlite*
dist/
build/
*.egg-info/
'''

_DOCKERIGNORE = '''.git/
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.env
logs/
data/*.db
data/*.sqlite*
dist/
build/
*.egg-info/
'''

_DOCKERFILE = '''# syntax=docker/dockerfile:1
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1 \\
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --upgrade pip && python -m pip install -r requirements.txt
COPY . .
RUN mkdir -p data logs
EXPOSE __PORT__
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=5 \\
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:__PORT__/actuator/health')"
CMD ["python", "Application.py"]
'''

_COMPOSE = '''services:
  app:
    build: .
    restart: unless-stopped
    ports:
      - "__PORT__:__PORT__"
    environment:
      SERVER_HOST: 0.0.0.0
      SERVER_PORT: __PORT__
      # 默认使用容器内 SQLite；启用 infra profile 后按需取消注释。
      # REDIS_ENABLED: "true"
      # REDIS_HOST: redis
      # DB_HOST: mysql
      # DB_USERNAME: app
      # DB_PASSWORD: change-me
      # NACOS_SERVER_ADDR: nacos:8848
      # RABBITMQ_HOST: rabbitmq
    volumes:
      - app-data:/app/data
      - app-logs:/app/logs

  redis:
    image: redis:7-alpine
    profiles: [infra]
    restart: unless-stopped
    ports: ["6379:6379"]
  mysql:
    image: mysql:8.4
    profiles: [infra]
    restart: unless-stopped
    environment:
      MYSQL_DATABASE: app
      MYSQL_USER: app
      MYSQL_PASSWORD: change-me
      MYSQL_ROOT_PASSWORD: root-change-me
    ports: ["3306:3306"]
    volumes:
      - mysql-data:/var/lib/mysql
  nacos:
    image: nacos/nacos-server:v2.3.0
    profiles: [infra]
    environment:
      MODE: standalone
    ports: ["8848:8848"]
  rabbitmq:
    image: rabbitmq:3-management-alpine
    profiles: [infra]
    environment:
      RABBITMQ_DEFAULT_USER: app
      RABBITMQ_DEFAULT_PASS: change-me
    ports: ["5672:5672", "15672:15672"]

volumes:
  app-data:
  app-logs:
  mysql-data:
'''

_START_GUIDE = '''# 启动指南

## 本地启动

1. `python -m venv .venv`
2. `python -m pip install -r requirements.txt`
3. 复制 `.env.example` 为 `.env` 并按需填写
4. `python Application.py`

默认端口为 __PORT__，Redis、MySQL、Nacos、RabbitMQ、Kafka 和 AI 均关闭，
因此不需要先启动 Docker 就能验证 Web 接口。

## Docker

```bash
docker compose up --build
docker compose --profile infra up --build
```

开启组件前请同时安装 Python 依赖、修改 `enabled`、填写地址和凭据。外部服务不可用时，
开发环境可保留 `startup.fail_fast=false`；生产环境建议改为 `true`。

## 验证

```bash
python -m pytest
curl http://127.0.0.1:__PORT__/api/hello
curl http://127.0.0.1:__PORT__/actuator/health
```

## 生产检查

* 设置 JWT、数据库、Redis、AI 等真实密钥，不使用示例值。
* 收紧 `server.cors.allow_origins`，HTTPS 下设置 `secure_cookie=true`。
* 根据部署平台设置主机、端口、日志目录和健康检查。
* 确认迁移策略后再改 `database.ddl-auto.mode`。
'''


def _application_yml(options: ProjectOptions, project_name: str) -> str:
    modules = set(_normalise_modules(options.modules))
    enabled = options.database != "none"
    driver = options.database if enabled else "sqlite"
    db_name = "data/app.db" if driver == "sqlite" else "springbootai"
    db_port = 3306 if driver == "mysql" else 5432 if driver == "postgresql" else 0
    values = {
        "PROJECT_NAME": project_name,
        "VERSION": _version(),
        "PACKAGE": options.package,
        "PORT": options.port,
        "AI_ENABLED": str(options.ai or "ai" in modules).lower(),
        "DB_ENABLED": str(enabled).lower(),
        "DB_DRIVER": driver,
        "DB_PORT": db_port,
        "DB_NAME": db_name,
        "REDIS_ENABLED": str(options.redis or "redis" in modules).lower(),
    }
    return _replace(_APPLICATION_YML_TEMPLATE, **values)


def _requirements(options: ProjectOptions, project_name: str) -> str:
    lines = [
        f"# {project_name} 依赖（由 SpringBootAI 脚手架生成）",
        "# 安装：python -m pip install -r requirements.txt",
        f"springbootAI=={_version()}",
        "",
        "# 已选择模块的直接依赖：",
    ]
    modules = set(_normalise_modules(options.modules))
    if options.database == "mysql":
        lines.append("PyMySQL==1.2.0                 # MySQL 驱动")
    elif options.database == "postgresql":
        lines.append("psycopg2-binary==2.9.12       # PostgreSQL 驱动")
    if options.redis or "redis" in modules:
        lines.append("redis==8.1.0                   # Redis 客户端")
    if options.ai or "ai" in modules:
        lines.extend([
            "langchain-openai==1.4.2       # AI OpenAI 适配器（按需）",
            "langchain-core==1.5.4        # AI 核心类型（按需）",
        ])
    if options.cloud or "cloud" in modules:
        lines.extend([
            "redis==8.1.0                   # Cloud/缓存按需使用",
            "nacos-sdk-python==2.0.11      # Nacos 客户端（开启 discovery 时需要）",
            "pika==1.4.4                   # RabbitMQ（开启 rabbitmq 时需要）",
        ])
    lines.extend([
        "",
        "# 未启用的可选依赖（需要时取消注释）：",
        "# sqlalchemy==2.0.40",
        "# PyMySQL==1.2.0",
        "# psycopg2-binary==2.9.12",
        "# redis==8.1.0",
        "# nacos-sdk-python==2.0.11",
        "# pika==1.4.4",
        "# kafka-python==2.0.2",
        "# prometheus-client==0.26.0",
        "# loguru==0.7.3",
        "",
    ])
    return "\n".join(lines)


def _readme(options: ProjectOptions, project_name: str) -> str:
    rows = "\n".join(
        f"| `{item}` | {_MODULE_DESCRIPTIONS[item]} |"
        for item in _normalise_modules(options.modules)
    )
    database_note = (
        f"已生成可直接运行的 `{options.database}` 配置。"
        if options.database != "none"
        else "默认不连接数据库；需要数据库时选择 orm 或修改 database.enabled。"
    )
    return _replace(
        _README_TEMPLATE,
        PROJECT_NAME=project_name,
        VERSION=_version(),
        PACKAGE=options.package,
        PORT=options.port,
        MODULE_TABLE=rows,
        DATABASE_NOTE=database_note,
    )


def _safe_print(message: str, *, file=None) -> None:
    """在 Windows 非 UTF-8 控制台也能输出，不因中文/符号导致脚手架失败。"""
    stream = file or sys.stdout
    try:
        print(message, file=stream)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        fallback = message.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(fallback, file=stream)
        if "项目已创建" in message:
            print("Project created", file=stream)


def _write_project(options: ProjectOptions) -> Path:
    project_dir = Path(options.project_path).expanduser().resolve()
    project_name = project_dir.name
    package = options.package or _derive_package_name(project_name)
    modules = set(_normalise_modules(options.modules))
    web_enabled = "web" in modules

    directories = [
        project_dir / "config", project_dir / "src", project_dir / "src" / package,
        project_dir / "src" / package / "common", project_dir / "src" / package / "services",
        project_dir / "src" / package / "models", project_dir / "src" / package / "repositories",
        project_dir / "src" / package / "mappers", project_dir / "tests", project_dir / "docs",
        project_dir / "data", project_dir / "logs",
    ]
    if web_enabled or options.sample_crud:
        directories.extend([
            project_dir / "src" / package / "controllers",
        ])
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

    application = _replace(_APPLICATION_TEMPLATE, PROJECT_NAME=project_name, PACKAGE=package)
    if not web_enabled:
        # 非 Web 项目不应导入不存在的 controllers 包。
        import_start = application.find(f"try:\n    from {package}.controllers import *")
        import_end = application.find("from springbootai.annotations", import_start)
        if import_start >= 0 and import_end >= 0:
            application = application[:import_start] + application[import_end:]
    files: Dict[Path, str] = {
        project_dir / "Application.py": application,
        project_dir / "config" / "application.yml": _application_yml(options, project_name),
        project_dir / "requirements.txt": _requirements(options, project_name),
        project_dir / "README.md": _readme(options, project_name),
        project_dir / "docs" / "启动指南.md": _replace(_START_GUIDE, PORT=options.port),
        project_dir / ".env.example": _replace(_ENV_EXAMPLE, PORT=options.port),
        project_dir / ".gitignore": _GITIGNORE,
        project_dir / "src" / "__init__.py": "",
        project_dir / "src" / package / "__init__.py": _replace(_INIT_TEMPLATE, PROJECT_NAME=project_name),
        project_dir / "src" / package / "common" / "__init__.py": _COMMON_INIT,
        project_dir / "src" / package / "common" / "response.py": _RESPONSE_TEMPLATE,
        project_dir / "src" / package / "common" / "exceptions.py": _EXCEPTIONS_TEMPLATE,
        project_dir / "src" / package / "common" / "handlers.py": _replace(_HANDLERS_TEMPLATE, PACKAGE=package),
        project_dir / "src" / package / "services" / "__init__.py": _SERVICES_INIT,
        project_dir / "src" / package / "models" / "__init__.py": _MODELS_INIT,
        project_dir / "src" / package / "repositories" / "__init__.py": _REPOSITORIES_INIT,
        project_dir / "src" / package / "mappers" / "__init__.py": '"""MyBatis Mapper 放置目录。"""\n',
        project_dir / "tests" / "__init__.py": "",
        project_dir / "tests" / "test_smoke.py": _replace(_SMOKE_TEST, PACKAGE=package),
        project_dir / "data" / ".gitkeep": "",
        project_dir / "logs" / ".gitkeep": "",
    }
    if web_enabled or options.sample_crud:
        files[project_dir / "src" / package / "controllers" / "__init__.py"] = _CONTROLLERS_INIT
        files[project_dir / "src" / package / "controllers" / "hello_controller.py"] = _replace(
            _HELLO_CONTROLLER, PACKAGE=package, PROJECT_NAME=project_name
        )
    if options.sample_crud:
        files[project_dir / "src" / package / "models" / "user.py"] = _CRUD_MODEL
        files[project_dir / "src" / package / "repositories" / "user_repository.py"] = _replace(
            _CRUD_REPOSITORY, PACKAGE=package
        )
        files[project_dir / "src" / package / "services" / "user_service.py"] = _replace(
            _CRUD_SERVICE, PACKAGE=package
        )
        files[project_dir / "src" / package / "controllers" / "user_controller.py"] = _replace(
            _CRUD_CONTROLLER, PACKAGE=package
        )
        files[project_dir / "src" / package / "controllers" / "__init__.py"] = (
            _CONTROLLERS_INIT
            + "from .user_controller import UserController\n\n"
            + "__all__ = [\"HelloController\", \"UserController\"]\n"
        )
    if options.docker:
        files[project_dir / ".dockerignore"] = _DOCKERIGNORE
        files[project_dir / "Dockerfile"] = _replace(_DOCKERFILE, PORT=options.port)
        files[project_dir / "docker-compose.yml"] = _replace(_COMPOSE, PORT=options.port)
    if options.ai or "ai" in modules:
        files[project_dir / "docs" / "AI配置说明.md"] = (
            "# AI 配置说明\n\n"
            "脚手架只生成配置骨架，不会在启动时调用模型。设置 OPENAI_API_KEY 后，\n"
            "在业务服务中按需导入 springbootai.ai；也可以配置本地 Ollama。\n"
        )
    if options.cloud or "cloud" in modules:
        files[project_dir / "docs" / "Cloud配置说明.md"] = (
            "# Cloud 配置说明\n\n"
            "Nacos、配置中心和消息总线默认关闭。启动 Docker 基础设施后，修改\n"
            "application.yml 的 enabled 和地址，再重启应用。\n"
        )
    for path, content in files.items():
        _atomic_write_text(path, content)
    return project_dir


def create_project(
    project_path: str,
    package: Optional[str] = None,
    modules: str = "web",
    port: int = 8000,
    *,
    database: Optional[str] = None,
    redis: Optional[bool] = None,
    ai: Optional[bool] = None,
    cloud: Optional[bool] = None,
    docker: bool = True,
    sample_crud: Optional[bool] = None,
) -> Path:
    """创建项目。

    旧版四个位置参数保持不变；新增参数均为关键字参数。默认项目只生成 Web
    组件，选择 ``orm`` 时自动使用本地 SQLite，外部服务仍需显式开启。
    """
    module_values = _normalise_modules(modules)
    raw = ProjectOptions(
        project_path=project_path,
        package=package,
        modules=modules,
        port=port,
        database=database or ("sqlite" if "orm" in module_values else "none"),
        redis=bool(redis) if redis is not None else "redis" in module_values,
        ai=bool(ai) if ai is not None else "ai" in module_values,
        cloud=bool(cloud) if cloud is not None else "cloud" in module_values,
        docker=docker,
        # 没有 web 时不默认生成 CRUD，避免改变 ``modules=orm`` 的语义。
        sample_crud=(sample_crud if sample_crud is not None else ("orm" in module_values and "web" in module_values)),
    )
    options = _validate_options(raw)
    project_dir = Path(options.project_path).expanduser().resolve()
    if project_dir.exists() and any(project_dir.iterdir()):
        raise FileExistsError(
            f"目录 '{project_dir}' 已存在且非空（directory is not empty），为避免覆盖用户文件已停止"
        )
    # 所有参数都已校验后才创建目录，非法输入不会留下半成品。
    project_dir.mkdir(parents=True, exist_ok=True)
    result = _write_project(options)
    _safe_print(f"项目已创建：{result}")
    _safe_print(f"  包名：{options.package}")
    _safe_print(f"  模块：{', '.join(_normalise_modules(options.modules))}")
    _safe_print(f"  端口：{options.port}")
    _safe_print(f"  数据库：{options.database}")
    _safe_print("\n下一步：")
    _safe_print(f"  1. cd {result}")
    _safe_print("  2. python -m pip install -r requirements.txt")
    _safe_print("  3. python Application.py")
    return result


def _interactive_terminal() -> bool:
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, OSError):
        return False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="springbootai init",
        description="初始化可直接运行的 SpringBootAI 项目（中文交互向导）",
    )
    parser.add_argument("project", nargs="?", help="项目名称或目录；交互模式可留空")
    parser.add_argument("--package", "-p", default=None, help="Python 包名，默认从项目名推导")
    parser.add_argument("--modules", "-m", default=None, help="模块：web,orm,ai,cloud,redis")
    parser.add_argument("--port", type=int, default=None, help="HTTP 端口，默认 8000")
    parser.add_argument("--database", choices=_DATABASE_TYPES, default=None, help="数据库类型")
    parser.add_argument("--redis", dest="redis", action="store_true", default=None, help="启用 Redis")
    parser.add_argument("--no-redis", dest="redis", action="store_false", help="关闭 Redis")
    parser.add_argument("--ai", dest="ai", action="store_true", default=None, help="启用 AI 配置")
    parser.add_argument("--no-ai", dest="ai", action="store_false", help="关闭 AI 配置")
    parser.add_argument("--cloud", dest="cloud", action="store_true", default=None, help="启用 Cloud 配置")
    parser.add_argument("--no-cloud", dest="cloud", action="store_false", help="关闭 Cloud 配置")
    parser.add_argument("--docker", dest="docker", action="store_true", default=None, help="生成 Docker 文件")
    parser.add_argument("--no-docker", dest="docker", action="store_false", help="不生成 Docker 文件")
    parser.add_argument("--sample-crud", dest="sample_crud", action="store_true", default=None, help="生成 CRUD 示例")
    parser.add_argument("--no-sample-crud", dest="sample_crud", action="store_false", help="不生成 CRUD 示例")
    parser.add_argument("--interactive", action="store_true", help="强制进入中文问答")
    parser.add_argument("--non-interactive", action="store_true", help="禁用问答，适合 CI")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """脚手架命令入口，返回 0/1 方便 console script 和测试调用。"""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.interactive and args.non_interactive:
        parser.error("--interactive 和 --non-interactive 不能同时使用")
    # 留空项目名时自动进入向导；提供项目路径的脚本调用保持非交互，
    # 需要问答时显式加 --interactive，避免 CI/IDE 误读输入流而卡住。
    should_interactive = bool(args.interactive or (not args.non_interactive and args.project is None))
    try:
        if should_interactive:
            options = collect_project_options(
                args.project,
                package=args.package,
                modules=args.modules,
                port=args.port,
                database=args.database,
                redis=args.redis,
                ai=args.ai,
                cloud=args.cloud,
                docker=args.docker,
                sample_crud=args.sample_crud,
            )
            create_project(
                options.project_path, package=options.package, modules=options.modules,
                port=options.port, database=options.database, redis=options.redis,
                ai=options.ai, cloud=options.cloud, docker=options.docker,
                sample_crud=options.sample_crud,
            )
        else:
            if not args.project:
                parser.error("非交互模式必须提供 project 参数")
            kwargs = {
                "project_path": args.project,
                "package": args.package,
                "modules": args.modules or "web",
                "port": args.port or 8000,
            }
            # 只有用户显式提供新选项时才传入，保持旧版 monkeypatch/API 的四参数契约。
            if args.database is not None:
                kwargs["database"] = args.database
            if args.redis is not None:
                kwargs["redis"] = args.redis
            if args.ai is not None:
                kwargs["ai"] = args.ai
            if args.cloud is not None:
                kwargs["cloud"] = args.cloud
            if args.docker is not None:
                kwargs["docker"] = args.docker
            if args.sample_crud is not None:
                kwargs["sample_crud"] = args.sample_crud
            create_project(**kwargs)
        return 0
    except (ValueError, FileExistsError) as exc:
        _safe_print(f"创建项目失败：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - 最后一层 CLI 保护
        _safe_print(f"创建项目时发生未预期错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
