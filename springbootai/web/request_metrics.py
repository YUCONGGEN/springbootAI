"""框架内置的可选请求持久化监控。

默认关闭，不会增加任何请求开销。开启
``management.admin.request-metrics.enabled`` 后，框架自动创建
``springbootai_request_metrics`` 表、记录每个请求，并由 Actuator Admin
面板读取 ``/actuator/request-metrics`` 展示摘要。业务项目无需编写实体、Mapper、
拦截器或 Controller。
"""
from __future__ import annotations

import fnmatch
import logging
import threading
import time
from collections.abc import Mapping
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import create_engine, text

from .interceptor import HandlerInterceptor

logger = logging.getLogger("Spring.Web.RequestMetrics")


# 运维端点、接口文档和静态图标不属于项目业务访问。框架即使没有配置白名单，
# 也始终不会把它们写入业务请求统计表，避免 Admin 自身轮询污染数据。
DEFAULT_EXCLUDE_PATHS = (
    "/actuator/**",
    "/docs/**",
    "/doc/**",
    "/redoc/**",
    "/openapi.json",
    "/favicon.ico",
)


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _mapping(value: Any) -> Dict[str, Any]:
    """将配置源的映射安全转换为普通字典。

    ConfigLoader 的最终配置可能来自本地文件、Nacos、环境变量或命令行。这里不假设
    具体配置来源，也不让空值、列表、标量等错误配置破坏 HTTP 请求处理。
    """
    return dict(value) if isinstance(value, Mapping) else {}


def _paths(value: Any) -> list[str]:
    """将 YAML 列表或逗号分隔字符串规范化为路径模式列表。"""
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _matches(path: str, pattern: str) -> bool:
    """匹配 Spring 风格 ``/**`` 路径和普通 glob 路径。"""
    if pattern in {"/**", "**", "*"}:
        return True
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        return path == prefix or path.startswith(prefix + "/")
    return fnmatch.fnmatchcase(path, pattern) or path.startswith(pattern.rstrip("/") + "/")


def resolve_request_metrics_config(config: Any) -> Dict[str, Any]:
    """解析框架配置；兼容连字符和下划线写法。"""
    root = _mapping(config)
    management = _mapping(root.get("management"))
    admin = _mapping(management.get("admin"))
    section = admin.get("request-metrics", admin.get("request_metrics", {}))
    section = _mapping(section)
    return {
        "enabled": _bool(section.get("enabled", False)),
        "table": str(section.get("table", "springbootai_request_metrics")).strip()
        or "springbootai_request_metrics",
        # 空白名单代表“采集所有非运维路径”，从而兼容不以 /api 开头的项目。
        # 项目可显式配置 ["/api/**"]，严格限定为自己的业务 API。
        "include_paths": _paths(section.get("include-paths", section.get("include_paths", []))),
        "exclude_paths": list(DEFAULT_EXCLUDE_PATHS) + _paths(
            section.get("exclude-paths", section.get("exclude_paths", []))
        ),
    }


def _database_url(config: Any) -> str:
    database = _mapping(_mapping(config).get("database"))
    if database.get("url"):
        return str(database["url"])
    driver = str(database.get("driver", "sqlite")).lower()
    if driver == "sqlite":
        path = database.get("database", "./runtime/springbootai.db")
        return "sqlite:///" + str(path).replace("\\", "/")
    # 非 SQLite 项目应提供标准 SQLAlchemy URL；无法推断时使用独立 SQLite，
    # 监控故障不会影响业务数据库。
    return "sqlite:///./runtime/springbootai_metrics.db"


class RequestMetricsStore:
    """线程安全的 SQLAlchemy 轻量存储，独立于业务 Mapper。"""

    def __init__(self, config: Dict[str, Any], table: str):
        self._lock = threading.Lock()
        self.table = table if table.replace("_", "").isalnum() else "springbootai_request_metrics"
        self.engine = create_engine(_database_url(config), future=True)
        self._ensure_table()

    def _ensure_table(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {self.table} (
                    path VARCHAR(255) PRIMARY KEY,
                    request_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    total_ms FLOAT NOT NULL DEFAULT 0,
                    last_status INTEGER NOT NULL DEFAULT 200,
                    last_request_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))

    def record(self, path: str, status: int, elapsed_ms: float) -> None:
        error_count = 1 if status >= 500 else 0
        with self._lock, self.engine.begin() as conn:
            result = conn.execute(text(
                f"UPDATE {self.table} SET request_count=request_count+1, "
                "error_count=error_count+:errors, total_ms=total_ms+:elapsed, "
                "last_status=:status, last_request_at=CURRENT_TIMESTAMP WHERE path=:path"
            ), {"errors": error_count, "elapsed": elapsed_ms, "status": status, "path": path})
            if result.rowcount == 0:
                conn.execute(text(
                    f"INSERT INTO {self.table} "
                    "(path, request_count, error_count, total_ms, last_status) "
                    "VALUES (:path, 1, :errors, :elapsed, :status)"
                ), {"path": path, "errors": error_count, "elapsed": elapsed_ms, "status": status})

    def snapshot(self) -> list[Dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(text(
                f"SELECT path, request_count, error_count, total_ms, last_status "
                f"FROM {self.table} ORDER BY request_count DESC"
            )).mappings().all()
        return [dict(row) for row in rows]

    def purge_paths_not_matching(self, include_paths: Iterable[str], exclude_paths: Iterable[str]) -> int:
        """删除旧版本已写入的非业务历史记录，防止历史运维访问继续污染面板。"""
        include_paths = tuple(include_paths)
        exclude_paths = tuple(exclude_paths)
        paths = [row["path"] for row in self.snapshot()]
        discarded = [
            path for path in paths
            if not _should_collect_path(path, include_paths, exclude_paths)
        ]
        if not discarded:
            return 0
        with self._lock, self.engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {self.table} WHERE path = :path"),
                [{"path": path} for path in discarded],
            )
        return len(discarded)


def _should_collect_path(path: str, include_paths: Iterable[str], exclude_paths: Iterable[str]) -> bool:
    """确定路径是否属于需要持久化统计的业务请求。"""
    if any(_matches(path, pattern) for pattern in exclude_paths):
        return False
    return not tuple(include_paths) or any(_matches(path, pattern) for pattern in include_paths)


class RequestMetricsInterceptor(HandlerInterceptor):
    """框架自动记录请求，不参与鉴权和业务处理。"""

    def __init__(
        self,
        store: RequestMetricsStore,
        include_paths: Iterable[str] = (),
        exclude_paths: Iterable[str] = DEFAULT_EXCLUDE_PATHS,
    ):
        self.store = store
        self.include_paths = tuple(include_paths)
        self.exclude_paths = tuple(exclude_paths)

    def pre_handle(self, request: Any, handler: Any) -> bool:
        # 必须在 pre_handle 标记，后续 post/after 阶段才不会意外记录已排除的请求。
        request.state.springbootai_metrics_collect = _should_collect_path(
            request.url.path, self.include_paths, self.exclude_paths
        )
        if not request.state.springbootai_metrics_collect:
            return True
        request.state.springbootai_metrics_started = time.perf_counter()
        return True

    def post_handle(self, request: Any, response: Any, handler: Any) -> None:
        self._finish(request, _safe_status_code(getattr(response, "status_code", 200)))

    def after_completion(self, request: Any, response: Any, handler: Any, exception: Exception | None = None) -> None:
        if exception is not None:
            self._finish(request, 500)

    def _finish(self, request: Any, status: int) -> None:
        if not getattr(request.state, "springbootai_metrics_collect", False):
            return
        if getattr(request.state, "springbootai_metrics_recorded", False):
            return
        request.state.springbootai_metrics_recorded = True
        started = getattr(request.state, "springbootai_metrics_started", None)
        if started is None:
            return
        try:
            self.store.record(request.url.path, status, (time.perf_counter() - started) * 1000)
        except Exception as exc:
            # 监控是可选能力，写入失败绝不能影响用户的业务响应。
            logger.warning("请求监控写入失败，已跳过本次记录: %s", exc)


def _safe_status_code(value: Any) -> int:
    """将异常响应对象中的状态码安全归一化，避免监控代码反向导致接口失败。"""
    try:
        status = int(value or 200)
    except (TypeError, ValueError):
        return 200
    return status if 100 <= status <= 599 else 200


_store: Optional[RequestMetricsStore] = None
_metrics_enabled = False
_metrics_error: Optional[str] = None


def configure_request_metrics(config: Any) -> Optional[RequestMetricsInterceptor]:
    """按配置初始化存储；关闭时返回 ``None``。"""
    global _store, _metrics_enabled, _metrics_error
    options = resolve_request_metrics_config(config)
    _metrics_enabled = options["enabled"]
    _metrics_error = None
    if not options["enabled"]:
        _store = None
        return None
    try:
        store = RequestMetricsStore(config, options["table"])
        removed = store.purge_paths_not_matching(options["include_paths"], options["exclude_paths"])
        if removed:
            logger.info("已清理 %s 条非业务请求监控历史记录", removed)
        _store = store
        return RequestMetricsInterceptor(
            store,
            include_paths=options["include_paths"],
            exclude_paths=options["exclude_paths"],
        )
    except Exception as exc:
        # 数据库不可用、URL 拼写错误等不能阻断应用启动；Admin 页面会得到明确状态。
        _store = None
        _metrics_error = "监控存储不可用"
        logger.warning("内置请求监控未启用存储，将继续启动应用: %s", exc)
        return None


def get_request_metrics() -> Dict[str, Any]:
    if _store is None:
        if not _metrics_enabled:
            return {"enabled": False, "items": []}
        result: Dict[str, Any] = {"enabled": _metrics_enabled, "persistent": False, "items": []}
        if _metrics_error:
            result["error"] = _metrics_error
        return result
    try:
        return {"enabled": True, "persistent": True, "items": _store.snapshot()}
    except Exception as exc:
        # 运行时数据库暂时不可用时，Actuator 本身仍应返回可读 JSON 而不是 500。
        logger.warning("读取请求监控失败: %s", exc)
        return {
            "enabled": True,
            "persistent": False,
            "items": [],
            "error": "监控存储暂时不可用",
        }
