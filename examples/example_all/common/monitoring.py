"""全局请求监控：实体、Mapper、拦截器和查询 Controller 集中定义。

本模块充分使用 SpringBootAI 的生命周期和 ORM 资源：

* ``@Entity`` 配合 DDL 自动建表创建 ``request_metrics``；
* ``@Mapper``、``@Select``、``@Insert``、``@Update`` 负责持久化计数；
* ``@Component`` 使拦截器由框架自动接入每个 HTTP 请求；
* ``@RestController`` 提供只读查询接口；
* ``@Slf4j`` 统一使用框架注入的日志对象。

接口代码不需要显式调用监控逻辑。应用重启后，统计数据从数据库继续累加。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from typing import Any

from springbootai.annotations import (
    Autowired,
    Component,
    GetMapping,
    RequestMapping,
    RestController,
    Slf4j,
)
from springbootai.orm import (
    CreateTime,
    Entity,
    Id,
    Index,
    Insert,
    Mapper,
    Required,
    Select,
    Table,
    Update,
)
from springbootai.web import HandlerInterceptor, Result

from .constants import REQUEST_ID_HEADER
from .context import reset_request_id, set_request_id


@Entity("request_metrics")
@Table(
    name="request_metrics",
    indexes=[Index("idx_request_metrics_path", ["path"], unique=True)],
    comment="example_all 全局请求监控计数",
)
class RequestMetric:
    """按请求路径保存的持久化监控计数。"""

    id: int = Id()
    path: str = Required(length=255)
    request_count: int = Required(default=0)
    error_count: int = Required(default=0)
    total_ms: float = Required(default=0.0)
    last_status: int = Required(default=200)
    last_request_at: str = CreateTime()


@Mapper
class RequestMetricMapper:
    """使用框架 Mapper 注解读写 ``request_metrics`` 表。"""

    @Select(
        "SELECT path, request_count, error_count, total_ms, last_status "
        "FROM request_metrics WHERE path = #{path}"
    )
    def find_by_path(self, path: str) -> Mapping[str, Any] | None:
        pass

    @Select(
        "SELECT path, request_count, error_count, total_ms, last_status "
        "FROM request_metrics ORDER BY request_count DESC"
    )
    def find_all(self) -> list[Mapping[str, Any]]:
        pass

    @Insert(
        "INSERT INTO request_metrics "
        "(path, request_count, error_count, total_ms, last_status) "
        "VALUES (#{path}, #{request_count}, #{error_count}, #{total_ms}, #{last_status})"
    )
    def insert(self, path: str, request_count: int, error_count: int, total_ms: float, last_status: int) -> int:
        pass

    @Update(
        "UPDATE request_metrics SET request_count = request_count + 1, "
        "error_count = error_count + #{error_count}, total_ms = total_ms + #{total_ms}, "
        "last_status = #{last_status}, last_request_at = CURRENT_TIMESTAMP "
        "WHERE path = #{path}"
    )
    def increment(self, path: str, error_count: int, total_ms: float, last_status: int) -> int:
        pass


def _path(request: Any) -> str:
    url = getattr(request, "url", None)
    return str(getattr(url, "path", "") or getattr(request, "path", "unknown"))


@Component
@Slf4j
class RequestMonitoringInterceptor(HandlerInterceptor):
    """框架自动执行的全局请求监控拦截器。"""

    @Autowired
    def __init__(self, request_metric_mapper: RequestMetricMapper):
        self.request_metric_mapper = request_metric_mapper
        self._write_lock = threading.Lock()

    def pre_handle(self, request: Any, handler: Any) -> bool:
        request.state.common_monitor_started = time.perf_counter()
        request.state.common_request_token = set_request_id(
            request.headers.get(REQUEST_ID_HEADER, "")
        )
        return True

    def post_handle(self, request: Any, response: Any, handler: Any) -> None:
        self._finish(request, getattr(response, "status_code", 200))

    def after_completion(
        self, request: Any, response: Any, handler: Any, exception: Exception | None = None
    ) -> None:
        if exception is not None:
            self._finish(request, 500, error=True)
        token = getattr(request.state, "common_request_token", None)
        if token is not None:
            reset_request_id(token)

    def _finish(self, request: Any, status: int, *, error: bool = False) -> None:
        if getattr(request.state, "common_monitor_recorded", False):
            return
        started = getattr(request.state, "common_monitor_started", None)
        if started is None:
            return
        request.state.common_monitor_recorded = True
        elapsed_ms = (time.perf_counter() - started) * 1000
        path = _path(request)
        try:
            # Mapper 写入是同步数据库操作；锁避免同一路径的首次插入竞争。
            with self._write_lock:
                existing = self.request_metric_mapper.find_by_path(path)
                if existing:
                    self.request_metric_mapper.increment(
                        path, int(error or status >= 500), elapsed_ms, status
                    )
                else:
                    self.request_metric_mapper.insert(
                        path, 1, int(error or status >= 500), elapsed_ms, status
                    )
            self.logger.info("%s %s -> %s (%.1fms)", getattr(request, "method", "GET"), path, status, elapsed_ms)
        except Exception as exc:
            # 监控写入失败不能影响业务请求，但必须留下框架日志。
            self.logger.warning("请求监控写入失败 path=%s error=%s", path, exc)


@RestController
@RequestMapping("/api/common")
@Slf4j
class MonitoringController:
    """查询数据库中的持久化监控统计。"""

    @Autowired
    def __init__(self, request_metric_mapper: RequestMetricMapper):
        self.request_metric_mapper = request_metric_mapper

    @GetMapping("/monitoring")
    def monitoring(self) -> Result[dict[str, Any]]:
        rows = [dict(row) for row in (self.request_metric_mapper.find_all() or [])]
        for row in rows:
            count = int(row.get("request_count", 0) or 0)
            row["average_ms"] = round(float(row.get("total_ms", 0) or 0) / count, 3) if count else 0.0
        return Result.success(data={"persistent": True, "items": rows})


__all__ = ["MonitoringController", "RequestMetric", "RequestMetricMapper", "RequestMonitoringInterceptor"]
