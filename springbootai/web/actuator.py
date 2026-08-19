"""Spring Boot Actuator 风格运维端点（扩展既有 ``/actuator/health``）。

在既有 health 端点（``springbootai.web.health``）基础上补齐标准 Actuator 端点：
``/actuator``（端点目录）、``/env``、``/loggers``、``/metrics``、``/beans``、
``/configprops``、``/mappings``、``/threaddump``。

设计：
- **纯函数 + 薄端点**：核心逻辑为接收 ``context`` 的纯函数，便于单测；路由函数仅做 HTTP 包装。
- **复用现有上下文**：与 ``health.py`` 共享 ``_application_context`` 全局（``configure_actuator`` 设置）。
- **脱敏**：``/env`` 自动屏蔽 password/secret/key/token/credential 等敏感键值（对齐 Spring Boot）。
- **loggers 动态调整**：GET 列出，POST ``/loggers/{name}`` 实时修改日志级别。

与 Java 差异：
- Python ``logging`` 无全局 logger 注册表，``/loggers`` 仅列出 root + ``Logger.manager.loggerDict`` 已实例化的 logger。
- ``/metrics`` 返回 JSON 指标名列表（Prometheus 文本格式仍由 ``/actuator/prometheus`` 提供）。
"""
import json
import logging
import threading
import traceback
from collections.abc import Mapping
from html import escape
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, HTMLResponse, Response

actuator_router = APIRouter()
_application_context = None

# 敏感键关键词（命中即脱敏，对齐 Spring Boot env 脱敏）
# 注意：必须同时包含 api_key（下划线）和 api-key（连字符），因为 YAML/JSON 中两种风格都常见
_SENSITIVE_KEYS = (
    "password", "secret", "token", "credential", "passwd",
    "api_key", "apikey", "api-key",  # 覆盖下划线、无分隔、连字符三种命名风格
    "private_key", "access_key", "secret_key",
)

# 需要鉴权的敏感端点（health/info 保留开放，供 K8s/Docker 探针使用）
# prometheus/sysmetrics 暴露进程级指标（RSS/CPU/线程/FD/python_gc 等），列入敏感端点
# admin 端点仅返回静态 HTML（无敏感数据），保持开放但页面内 JS 调用的端点受鉴权保护
_SENSITIVE_ENDPOINTS = frozenset({
    "env", "loggers", "metrics", "beans", "configprops", "mappings", "threaddump",
    "heapdump", "prometheus", "sysmetrics", "request-metrics", "alert", "alerts",
})

# Actuator 鉴权开关（由 configure_actuator 从配置读取）
_actuator_secured = True
_actuator_admin_roles = frozenset({"ADMIN", "ACTUATOR"})

# 运维敏感端点默认关闭。测试或嵌入式调用若未执行 configure_actuator，保留
# 兼容行为；正式应用启动时 configure_actuator 会根据最终配置重新计算此表。
_OPTIONAL_ACTUATOR_ENDPOINTS = (
    "env", "loggers", "metrics", "beans", "configprops", "mappings",
    "threaddump", "heapdump", "prometheus", "sysmetrics", "request-metrics",
    "alert", "alerts",
)
_actuator_endpoint_enabled = {name: True for name in _OPTIONAL_ACTUATOR_ENDPOINTS}
_actuator_configured = False

# 内置 Admin 面板默认值。应用只需在 application.yml 中覆盖需要调整的字段；
# 未配置、空值或非法值都会回退到这些默认值，确保升级框架后页面仍可直接使用。
_ADMIN_DASHBOARD_DEFAULTS = {
    "title": "SpringBootAI Admin Dashboard",
    "subtitle": "Actuator 可视化面板 | Prometheus 指标 | 实时监控",
    "refresh_interval_seconds": 30,
    "page_size": 10,
    # 业务请求监控不是框架必选能力；enabled=false 时不创建表、不拦截请求。
    "request_metrics_enabled": False,
    "request_metrics_url": "/actuator/request-metrics",
    "request_metrics_title": "业务请求监控",
}
_admin_dashboard_config = dict(_ADMIN_DASHBOARD_DEFAULTS)

# 告警历史缓存（内存，最多 100 条，由 /actuator/alert POST 写入，/actuator/alerts GET 读取）
_alert_history: List[Dict[str, Any]] = []


def _resolve_actuator_endpoint_flags(config: Any) -> Dict[str, bool]:
    """解析可选运维端点开关；未配置时全部关闭，避免 Admin 无 token 轮询。"""
    flags = {name: False for name in _OPTIONAL_ACTUATOR_ENDPOINTS}
    if not isinstance(config, Mapping):
        return flags
    management = config.get("management", {})
    management = management if isinstance(management, Mapping) else {}
    endpoints = management.get("endpoints", {})
    endpoints = endpoints if isinstance(endpoints, Mapping) else {}
    web = endpoints.get("web", {})
    web = web if isinstance(web, Mapping) else {}
    exposure = web.get("exposure", {})
    exposure = exposure if isinstance(exposure, Mapping) else {}

    def names(value: Any) -> set[str]:
        if isinstance(value, str):
            value = value.split(",")
        if not isinstance(value, (list, tuple, set)):
            return set()
        return {str(item).strip().lower() for item in value if str(item).strip()}

    included = names(exposure.get("include"))
    excluded = names(exposure.get("exclude"))
    if "*" in included:
        for name in flags:
            flags[name] = True
    else:
        for name in flags:
            flags[name] = name in included

    # Spring 风格的 management.endpoints.<name>.enabled 优先级高于 exposure。
    for name in flags:
        section = endpoints.get(name, {})
        if isinstance(section, Mapping) and "enabled" in section:
            raw = section.get("enabled")
            flags[name] = raw if isinstance(raw, bool) else str(raw).strip().lower() in {
                "1", "true", "yes", "on"
            }
        if name in excluded:
            flags[name] = False

    admin = management.get("admin", {})
    admin = admin if isinstance(admin, Mapping) else {}
    for name in flags:
        section = admin.get(name, {})
        if isinstance(section, Mapping) and "enabled" in section:
            raw = section.get("enabled")
            flags[name] = raw if isinstance(raw, bool) else str(raw).strip().lower() in {
                "1", "true", "yes", "on"
            }
    # 兼容历史 prometheus.enabled 配置；request-metrics 使用同一路径配置。
    prometheus = config.get("prometheus", {})
    if isinstance(prometheus, Mapping) and "enabled" in prometheus:
        raw = prometheus.get("enabled")
        flags["prometheus"] = raw if isinstance(raw, bool) else str(raw).strip().lower() in {
            "1", "true", "yes", "on"
        }
    request_metrics = admin.get("request-metrics", admin.get("request_metrics", {}))
    if isinstance(request_metrics, Mapping):
        raw = request_metrics.get("enabled", False)
        flags["request-metrics"] = raw if isinstance(raw, bool) else str(raw).strip().lower() in {
            "1", "true", "yes", "on"
        }
    return flags


def configure_actuator(application_context) -> None:
    """注入应用上下文 + 读取 Actuator 鉴权配置。

    从 ``management.endpoints.web.security`` 读取：
    - ``enabled``: 是否对敏感端点启用鉴权（生产环境默认 True）
    - ``roles``: 允许访问的角色列表（默认 ADMIN/ACTUATOR）
    """
    global _application_context, _actuator_secured, _actuator_admin_roles
    global _admin_dashboard_config, _actuator_endpoint_enabled, _actuator_configured
    _application_context = application_context
    # 每次配置都先恢复安全默认值，避免测试、热刷新或上下文重建沿用上一次的全局状态。
    _actuator_secured = True
    _actuator_admin_roles = frozenset({"ADMIN", "ACTUATOR"})
    _actuator_configured = True
    _actuator_endpoint_enabled = {name: False for name in _OPTIONAL_ACTUATOR_ENDPOINTS}
    _admin_dashboard_config = dict(_ADMIN_DASHBOARD_DEFAULTS)
    try:
        config = application_context.get_config()
        root = dict(config) if isinstance(config, Mapping) else {}
        management = root.get('management', {})
        management = management if isinstance(management, Mapping) else {}
        endpoints = management.get('endpoints', {})
        endpoints = endpoints if isinstance(endpoints, Mapping) else {}
        web = endpoints.get('web', {})
        web = web if isinstance(web, Mapping) else {}
        mgmt = web.get('security', {})
        mgmt = mgmt if isinstance(mgmt, Mapping) else {}
        raw_secured = mgmt.get('enabled', True)
        _actuator_secured = raw_secured if isinstance(raw_secured, bool) else (
            str(raw_secured).strip().lower() in {"1", "true", "yes", "on"}
        )
        roles = mgmt.get('roles')
        if isinstance(roles, str):
            roles = roles.split(',')
        if isinstance(roles, (list, tuple, set)):
            normalized_roles = frozenset(
                str(role).strip().upper() for role in roles if str(role).strip()
            )
            if normalized_roles:
                _actuator_admin_roles = normalized_roles
        _admin_dashboard_config = _resolve_admin_dashboard_config(config)
        _actuator_endpoint_enabled = _resolve_actuator_endpoint_flags(config)
        # 开发者显式关闭 Actuator 鉴权时，保留历史的本地调试体验；生产默认
        # 鉴权开启时则严格遵守 exposure/endpoint.enabled 的显式开关。
        if not _actuator_secured:
            _actuator_endpoint_enabled.update({
                name: True for name in _OPTIONAL_ACTUATOR_ENDPOINTS
                if name != "request-metrics"
            })
        _admin_dashboard_config.update({
            f"endpoint_{name.replace('-', '_')}_enabled": enabled
            for name, enabled in _actuator_endpoint_enabled.items()
        })
    except Exception:
        # 配置读取失败时不让运维页失效，回退到框架内置默认配置。
        _admin_dashboard_config = dict(_ADMIN_DASHBOARD_DEFAULTS)
        _actuator_endpoint_enabled = {name: False for name in _OPTIONAL_ACTUATOR_ENDPOINTS}


def _is_actuator_endpoint_enabled(endpoint_name: str) -> bool:
    return bool(_actuator_endpoint_enabled.get(endpoint_name, True))


def _resolve_admin_dashboard_config(config: Any) -> Dict[str, Any]:
    """解析 ``management.admin``，以框架默认值补齐缺失或非法配置。

    支持 YAML 常用的连字符写法（``page-size``、``refresh-interval-seconds``）
    和 Python 风格下划线写法，方便通过不同配置源覆盖。
    """
    resolved = dict(_ADMIN_DASHBOARD_DEFAULTS)
    if not isinstance(config, Mapping):
        return resolved

    management = config.get("management", {})
    admin = management.get("admin", {}) if isinstance(management, Mapping) else {}
    if not isinstance(admin, Mapping):
        return resolved

    for key in ("title", "subtitle"):
        value = admin.get(key)
        if isinstance(value, str) and value.strip():
            resolved[key] = value.strip()

    def positive_int(*keys: str, default: int, maximum: int) -> int:
        for key in keys:
            value = admin.get(key)
            if isinstance(value, bool):
                continue
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= number <= maximum:
                return number
        return default

    resolved["refresh_interval_seconds"] = positive_int(
        "refresh-interval-seconds", "refresh_interval_seconds",
        default=resolved["refresh_interval_seconds"], maximum=3600,
    )
    resolved["page_size"] = positive_int(
        "page-size", "page_size", default=resolved["page_size"], maximum=100,
    )

    # 框架内置端点；项目只声明是否开启与显示标题，不需提供业务路由。
    request_metrics = admin.get("request-metrics", admin.get("request_metrics", {}))
    if isinstance(request_metrics, Mapping):
        raw_enabled = request_metrics.get("enabled", False)
        resolved["request_metrics_enabled"] = (
            raw_enabled if isinstance(raw_enabled, bool)
            else str(raw_enabled).strip().lower() in {"1", "true", "yes", "on"}
        )
        title = request_metrics.get("title")
        if isinstance(title, str) and title.strip():
            resolved["request_metrics_title"] = title.strip()
    return resolved


def _create_actuator_dependency(endpoint_name: str):
    """为指定端点创建鉴权依赖函数。

    敏感端点（env/loggers/threaddump 等）要求 JWT + ADMIN 角色；
    非敏感端点（health/info）无鉴权。
    """
    if endpoint_name not in _SENSITIVE_ENDPOINTS:
        # 非敏感端点（health/info），不鉴权
        return None

    def _auth_dependency(request: Request) -> None:
        """验证 Actuator 敏感端点访问权限。"""
        if not _actuator_secured:
            return  # 鉴权关闭（开发环境）

        auth_header = request.headers.get('Authorization', '')
        if not auth_header.lower().startswith('bearer '):
            raise HTTPException(status_code=401, detail="Bearer token required for actuator access")

        token = auth_header[7:].strip()
        try:
            from springbootai.security.jwt_utils import jwt_utils
            payload = jwt_utils.decode_token(token)
        except Exception as exc:
            raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

        # 验证 token_type 必须是 access（refresh token 不能访问 actuator）
        if payload.get('token_type') != 'access':
            raise HTTPException(
                status_code=401,
                detail="Access token required (refresh tokens are not allowed)"
            )

        # 验证角色
        roles = [r.upper() for r in payload.get('roles', [])]
        if not any(r in _actuator_admin_roles for r in roles):
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient role. Required: {sorted(_actuator_admin_roles)}, got: {roles}"
            )

    return _auth_dependency


def _get_context():
    return _application_context


# ==================== 端点目录 ====================

def get_endpoint_directory() -> dict:
    """列出所有可用的 Actuator 端点（对齐 ``/actuator`` 根端点）。"""
    endpoints = {
        "health": {"href": "/actuator/health", "methods": ["GET"]},
        "health-liveness": {"href": "/actuator/health/liveness", "methods": ["GET"]},
        "health-readiness": {"href": "/actuator/health/readiness", "methods": ["GET"]},
        "info": {"href": "/actuator/info", "methods": ["GET"]},
        "env": {"href": "/actuator/env", "methods": ["GET"]},
        "loggers": {"href": "/actuator/loggers", "methods": ["GET", "POST"]},
        "metrics": {"href": "/actuator/metrics", "methods": ["GET"]},
        "beans": {"href": "/actuator/beans", "methods": ["GET"]},
        "configprops": {"href": "/actuator/configprops", "methods": ["GET"]},
        "mappings": {"href": "/actuator/mappings", "methods": ["GET"]},
        "threaddump": {"href": "/actuator/threaddump", "methods": ["GET"]},
        "heapdump": {"href": "/actuator/heapdump", "methods": ["GET"]},
        "prometheus": {"href": "/actuator/prometheus", "methods": ["GET"]},
        "sysmetrics": {"href": "/actuator/sysmetrics", "methods": ["GET"]},
        "request-metrics": {"href": "/actuator/request-metrics", "methods": ["GET"]},
        "alert": {"href": "/actuator/alert", "methods": ["POST"]},
        "alerts": {"href": "/actuator/alerts", "methods": ["GET"]},
        "admin": {"href": "/actuator/admin", "methods": ["GET"]},
    }
    # 目录保持稳定，便于监控客户端缓存链接；未启用端点不会由内置 Admin 自动轮询。
    return {"_links": endpoints}


# ==================== /env 环境配置 ====================

def _sanitize(obj: Any) -> Any:
    """递归脱敏：键名命中敏感关键词的值替换为 ``******``。"""
    if isinstance(obj, dict):
        return {
            k: ("******" if any(s in k.lower() for s in _SENSITIVE_KEYS) else _sanitize(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_sanitize(item) for item in obj]
    return obj


def get_env_info(context) -> dict:
    """返回环境配置快照（脱敏）+ active profile。

    对齐 Spring ``/actuator/env``：展示 property sources 与 active profile。
    """
    result: Dict[str, Any] = {"activeProfiles": [], "propertySources": []}
    if context is None:
        return result
    try:
        active = context.config_loader.get_active_profile() if hasattr(context, "config_loader") else None
        if active:
            result["activeProfiles"] = [active]
    except Exception:
        pass
    try:
        config = context.get_config() if hasattr(context, "get_config") else {}
        result["propertySources"].append({
            "name": "applicationConfig",
            "properties": _sanitize(config) if isinstance(config, dict) else {},
        })
    except Exception:
        pass
    return result


# ==================== /loggers 日志级别 ====================

_LEVEL_NAMES = {
    logging.DEBUG: "DEBUG", logging.INFO: "INFO", logging.WARNING: "WARNING",
    logging.ERROR: "ERROR", logging.CRITICAL: "CRITICAL", logging.NOTSET: "NOTSET",
}


def get_loggers() -> dict:
    """列出 root + 已实例化的 logger 及其有效级别。"""
    loggers: Dict[str, str] = {"ROOT": _LEVEL_NAMES.get(logging.getLogger().getEffectiveLevel(), "NOTSET")}
    manager_dict = logging.Logger.manager.loggerDict
    for name, logger in manager_dict.items():
        if isinstance(logger, logging.Logger):
            loggers[name] = _LEVEL_NAMES.get(logger.getEffectiveLevel(), "NOTSET")
    return {"levels": ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "FATAL", "OFF"],
            "loggers": loggers}


def get_logger_level(name: str) -> Optional[dict]:
    logger = logging.getLogger(name)
    return {"configuredLevel": _LEVEL_NAMES.get(logger.level, "NOTSET") if logger.level else None,
            "effectiveLevel": _LEVEL_NAMES.get(logger.getEffectiveLevel(), "NOTSET")}


def set_logger_level(name: str, level: str) -> dict:
    """动态修改 logger 级别。`
ame=root`` 修改 root logger。"""
    target_name = "" if name.lower() == "root" else name
    logger = logging.getLogger(target_name)
    level_value = getattr(logging, level.upper(), None)
    if level_value is None and level.upper() != "OFF":
        raise ValueError(f"不支持的日志级别: {level}")
    if level.upper() == "OFF":
        logger.setLevel(logging.CRITICAL + 100)
    else:
        logger.setLevel(level_value)
    return {"configuredLevel": level.upper()}


# ==================== /metrics 指标列表 ====================

def get_metrics() -> dict:
    """返回可用指标名列表（JSON 视图；Prometheus 文本格式见 /actuator/prometheus）。"""
    names: List[str] = []
    try:
        from springbootai.monitoring.prometheus import prometheus_metrics
        metrics_map = prometheus_metrics.get_metrics()
        names = list(metrics_map.keys())
    except Exception:
        pass
    return {"names": names}


# ==================== /beans Bean 列表 ====================

def get_beans(context) -> dict:
    """列出 IoC 容器中所有 Bean 的元信息。"""
    beans: Dict[str, Any] = {}
    if context is not None:
        try:
            factory = context.bean_factory
        except AttributeError:
            factory = None
        if factory is not None:
            for name in factory.get_bean_names():
                definition = factory.get_bean_definition(name)
                if definition is None:
                    beans[name] = {"type": "unknown", "scope": "unknown"}
                    continue
                bean_class = definition.bean_class
                type_name = getattr(bean_class, "__name__", str(bean_class)) if bean_class else "unknown"
                beans[name] = {
                    "type": type_name,
                    "scope": getattr(definition, "scope", "singleton"),
                    "singleton": getattr(definition, "is_singleton", True),
                }
    return {"contexts": {"application": {"beans": beans}}}


# ==================== /configprops 配置属性绑定 ====================

def get_configprops(context) -> dict:
    """列出 ``@ConfigurationProperties`` 绑定的配置前缀与值（脱敏）。"""
    result: Dict[str, Any] = {}
    if context is None:
        return result
    try:
        factory = context.bean_factory
    except AttributeError:
        return result
    for name in factory.get_bean_names():
        definition = factory.get_bean_definition(name)
        if definition is None:
            continue
        props = definition.annotations.get("properties", []) if hasattr(definition, "annotations") else []
        if not props:
            continue
        for prop_ann in props:
            prefix = getattr(prop_ann, "prefix", None)
            if not prefix:
                continue
            try:
                config = context.get_config()
                bound = context.config_loader.get_prefix_config(prefix) if hasattr(context, "config_loader") else {}
            except Exception:
                bound = {}
            result[prefix] = {"prefix": prefix, "properties": _sanitize(bound)}
    return {"contexts": {"application": {"beans": result}}}


# ==================== /mappings 路由映射 ====================

def get_mappings(app) -> dict:
    """列出 FastAPI 应用的 HTTP 路由映射。"""
    mappings: List[Dict[str, Any]] = []
    if app is None:
        return {"contexts": {"application": {"mappings": {"dispatcherServlets": {"dispatcherServlet": mappings}}}}}
    for route in getattr(app, "routes", []):
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path is None:
            continue
        mappings.append({
            "path": path,
            "methods": sorted(list(methods)) if methods else ["GET"],
            "name": getattr(route, "name", ""),
        })
    return {"contexts": {"application": {"mappings": {"dispatcherServlets": {"dispatcherServlet": mappings}}}}}


# ==================== /threaddump 线程转储 ====================

def get_threaddump() -> dict:
    """返回当前进程所有线程的转储（id/name/alive/daemon/stack）。"""
    import sys
    frames_map = sys._current_frames()
    threads = []
    for thread in threading.enumerate():
        frames = []
        frame = frames_map.get(thread.ident)
        if frame is not None:
            try:
                for filename, lineno, name, _line in traceback.extract_stack(frame):
                    frames.append({"file": filename, "line": lineno, "method": name})
            except Exception:
                pass
        threads.append({
            "threadId": thread.ident,
            "threadName": thread.name,
            "threadState": "RUNNABLE" if thread.is_alive() else "TERMINATED",
            "daemon": thread.daemon,
            "stack": frames,
        })
    return {"threads": threads}


# ==================== /heapdump 内存快照 ====================

def get_heapdump(limit: int = 50) -> dict:
    """返回 Python 进程内存分配快照（对齐 Spring Boot /actuator/heapdump）。

    使用 ``tracemalloc`` 模块获取内存分配统计，返回 JSON 格式。

    与 Java heapdump 的差异：
    - Java dump 整个 JVM 堆（HPROF 二进制格式），可用 MAT/jhat 分析
    - Python 返回 tracemalloc 统计快照（JSON），展示按文件/行号聚合的内存分配 Top-N

    安全说明：仅返回文件路径和行号，不返回变量值，避免敏感数据泄露。
    """
    import os
    import sys

    result: Dict[str, Any] = {
        "pid": os.getpid(),
        "python": sys.version,
        "tracemalloc_active": False,
        "top_allocations": [],
        "gc_stats": {},
    }

    # tracemalloc 内存分配快照
    try:
        import tracemalloc
        if not tracemalloc.is_tracing():
            # 如果没启动，临时启动并立即取样（开销极小）
            tracemalloc.start(1)
            result["tracemalloc_active"] = False
            result["_note"] = "tracemalloc was not active; started temporarily with frames=1"
        else:
            result["tracemalloc_active"] = True

        snapshot = tracemalloc.take_snapshot()
        stats = snapshot.statistics("lineno")
        top = []
        for stat in stats[:limit]:
            frame = stat.traceback[0]
            top.append({
                "file": frame.filename,
                "line": frame.lineno,
                "size_bytes": stat.size,
                "size_mb": round(stat.size / 1024 / 1024, 2),
                "count": stat.count,
            })
        result["top_allocations"] = top
        result["total_allocated_bytes"] = sum(s.size for s in stats)
        result["total_allocated_mb"] = round(sum(s.size for s in stats) / 1024 / 1024, 2)

        # 如果是临时启动的，停止
        if not result["tracemalloc_active"]:
            tracemalloc.stop()
    except Exception as e:
        result["tracemalloc_error"] = str(e)

    # GC 统计
    try:
        import gc
        gc_stats = gc.get_stats()  # [{collections, collected, uncollectable}, ...]
        result["gc_stats"] = {
            "generations": [
                {"collections": s["collections"], "collected": s["collected"], "uncollectable": s["uncollectable"]}
                for s in gc_stats
            ],
            "garbage_count": len(gc.garbage),
            "thresholds": list(gc.get_threshold()),
        }
        result["gc_stats"]["object_count"] = len(gc.get_objects())
    except Exception as e:
        result["gc_stats"]["error"] = str(e)

    return result


# ==================== HTTP 端点（薄包装） ====================

@actuator_router.get('')
@actuator_router.get('/')
def actuator_root():
    return JSONResponse(content=get_endpoint_directory(), status_code=200)


# ==================== HTTP 端点（薄包装 + 鉴权） ====================

# 敏感端点鉴权依赖（闭包捕获 endpoint_name）
_env_auth = _create_actuator_dependency("env")
_loggers_auth = _create_actuator_dependency("loggers")
_metrics_auth = _create_actuator_dependency("metrics")
_beans_auth = _create_actuator_dependency("beans")
_configprops_auth = _create_actuator_dependency("configprops")
_mappings_auth = _create_actuator_dependency("mappings")
_threaddump_auth = _create_actuator_dependency("threaddump")
_heapdump_auth = _create_actuator_dependency("heapdump")
_prometheus_auth = _create_actuator_dependency("prometheus")
_sysmetrics_auth = _create_actuator_dependency("sysmetrics")
_request_metrics_auth = _create_actuator_dependency("request-metrics")
_alert_auth = _create_actuator_dependency("alert")
_alerts_auth = _create_actuator_dependency("alerts")


@actuator_router.get('/env')
def env_endpoint(_: None = Depends(_env_auth)):
    return JSONResponse(content=get_env_info(_get_context()), status_code=200)


@actuator_router.get('/loggers')
def loggers_endpoint(_: None = Depends(_loggers_auth)):
    return JSONResponse(content=get_loggers(), status_code=200)


@actuator_router.get('/loggers/{name}')
def logger_detail(name: str, _: None = Depends(_loggers_auth)):
    return JSONResponse(content=get_logger_level(name), status_code=200)


@actuator_router.post('/loggers/{name}')
def logger_update(name: str, body: dict = Body(default={}), _: None = Depends(_loggers_auth)):
    """请求体 ``{"configuredLevel": "DEBUG"}`` 动态修改级别。"""
    level = (body or {}).get("configuredLevel", "INFO")
    try:
        result = set_logger_level(name, level)
        return JSONResponse(content=result, status_code=200)
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=400)


@actuator_router.get('/metrics')
def metrics_endpoint(_: None = Depends(_metrics_auth)):
    return JSONResponse(content=get_metrics(), status_code=200)


@actuator_router.get('/beans')
def beans_endpoint(_: None = Depends(_beans_auth)):
    return JSONResponse(content=get_beans(_get_context()), status_code=200)


@actuator_router.get('/configprops')
def configprops_endpoint(_: None = Depends(_configprops_auth)):
    return JSONResponse(content=get_configprops(_get_context()), status_code=200)


@actuator_router.get('/mappings')
def mappings_endpoint(_: None = Depends(_mappings_auth)):
    app = None
    ctx = _get_context()
    if ctx is not None and hasattr(ctx, "web_context"):
        app = ctx.web_context.get_app()
    return JSONResponse(content=get_mappings(app), status_code=200)


@actuator_router.get('/threaddump')
def threaddump_endpoint(_: None = Depends(_threaddump_auth)):
    return JSONResponse(content=get_threaddump(), status_code=200)


@actuator_router.get('/heapdump')
def heapdump_endpoint(limit: int = 50, _: None = Depends(_heapdump_auth)):
    """内存快照端点（对齐 Spring Boot /actuator/heapdump）。

    返回 tracemalloc 内存分配统计 + GC 统计的 JSON。
    可选 query 参数 ``?limit=100`` 控制返回的 Top-N 行数（默认 50）。
    """
    return JSONResponse(content=get_heapdump(limit=limit), status_code=200)


# ==================== /prometheus Prometheus 指标端点 ====================

@actuator_router.get('/prometheus')
def prometheus_endpoint(_: None = Depends(_prometheus_auth)):
    """暴露 Prometheus 文本格式指标，供 Prometheus Server 抓取。

    对齐 Spring Boot ``/actuator/prometheus``：
    - 响应 Content-Type: ``text/plain; version=0.0.4; charset=utf-8``
    - 返回 ``prometheus_client.generate_latest()`` 格式数据
    """
    try:
        from springbootai.monitoring.prometheus import CONTENT_TYPE_LATEST, prometheus_metrics
        data = prometheus_metrics.generate_metrics_data()
        return Response(
            content=data,
            headers={'Content-Type': CONTENT_TYPE_LATEST},
        )
    except ImportError:
        return Response(
            content="# prometheus_client not installed\n",
            media_type='text/plain',
            status_code=503,
        )
    except Exception as e:
        return Response(
            content=f"# error: {e}\n",
            media_type='text/plain',
            status_code=500,
        )


# ==================== /sysmetrics 进程系统指标 ====================

def get_sysmetrics() -> dict:
    """返回进程级系统指标（内存/CPU/线程/文件描述符）。

    使用 ``psutil`` 获取进程信息，对齐 Spring Boot ``/actuator/metrics/{name}``。
    """
    try:
        import psutil
        import os
        process = psutil.Process(os.getpid())
        mem = process.memory_info()
        return {
            "rss_mb": round(mem.rss / 1024 / 1024, 1),
            "vms_mb": round(mem.vms / 1024 / 1024, 1),
            "cpu_percent": process.cpu_percent(interval=0.1),
            "num_threads": process.num_threads(),
            "num_fds": process.num_fds() if hasattr(process, 'num_fds') else 0,
            "create_time": process.create_time(),
        }
    except ImportError:
        return {"error": "psutil not installed"}
    except Exception as e:
        return {"error": str(e)}


@actuator_router.get('/sysmetrics')
def sysmetrics_endpoint(_: None = Depends(_sysmetrics_auth)):
    """进程系统指标端点（供 Admin 面板 JS 调用）。"""
    return JSONResponse(content=get_sysmetrics(), status_code=200)


@actuator_router.get('/request-metrics')
def request_metrics_endpoint(_: None = Depends(_request_metrics_auth)):
    """框架内置请求持久化监控；未开启时返回 disabled 状态。"""
    from springbootai.web.request_metrics import get_request_metrics
    return JSONResponse(content=get_request_metrics(), status_code=200)


# ==================== /alert Alertmanager Webhook 接收端点 ====================

def get_alert_history() -> List[Dict[str, Any]]:
    """获取已接收的告警历史记录（内存缓存，最多 100 条）。"""
    return list(_alert_history)


def add_alert_record(alert: Dict[str, Any]) -> None:
    """添加一条告警记录到历史缓存。"""
    _alert_history.append(alert)
    # 保留最近 100 条
    if len(_alert_history) > 100:
        _alert_history.pop(0)


@actuator_router.post('/alert')
def alert_webhook(payload: Dict[str, Any] = Body(...), _: None = Depends(_alert_auth)):
    """接收 Alertmanager 推送的告警通知。

    Alertmanager 配置 webhook_configs 后，告警会以 JSON 格式 POST 到此端点。
    payload 格式参考：https://prometheus.io/docs/alerting/latest/configuration/#webhook_config

    收到的告警存入内存历史缓存（最近 100 条），供 /actuator/admin 面板展示。
    生产环境建议对接钉钉/企业微信/邮件等通知渠道。
    """
    import logging
    _logger = logging.getLogger("Spring.Web.Actuator.Alert")

    alerts = payload.get('alerts', [])
    for alert in alerts:
        status = alert.get('status', 'unknown')
        labels = alert.get('labels', {})
        annotations = alert.get('annotations', {})
        alert_name = labels.get('alertname', 'Unknown')
        severity = labels.get('severity', 'info')
        instance = labels.get('instance', '')

        record = {
            'alertname': alert_name,
            'status': status,
            'severity': severity,
            'instance': instance,
            'summary': annotations.get('summary', ''),
            'description': annotations.get('description', ''),
            'starts_at': alert.get('startsAt', ''),
            'ends_at': alert.get('endsAt', ''),
        }
        add_alert_record(record)

        if status == 'firing':
            _logger.warning(
                "[Alert] %s [%s] %s — %s (instance=%s)",
                alert_name, severity,
                annotations.get('summary', ''),
                annotations.get('description', ''),
                instance,
            )
        else:
            _logger.info("[Alert] %s RESOLVED (instance=%s)", alert_name, instance)

    return JSONResponse(
        content={'status': 'ok', 'received': len(alerts)},
        status_code=200,
    )


@actuator_router.get('/alerts')
def alerts_history(_: None = Depends(_alerts_auth)):
    """获取告警历史记录（供 Admin 面板展示）。"""
    return JSONResponse(content=get_alert_history(), status_code=200)


# ==================== /admin Spring Boot Admin 可视化面板 ====================

def _build_admin_dashboard_html() -> str:
    """构建 Spring Boot Admin 风格的可视化面板 HTML。

    面板通过 JS fetch 异步调用各 Actuator 端点获取数据，
    展示：健康状态、系统信息、内存、线程、日志级别、Prometheus 指标摘要。
    """
    html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SpringBootAI Admin</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: #050b18; color: #e7efff; }
        .header { background: #071225; padding: 22px 30px; border-bottom: 1px solid #1d3154; }
        .header h1 { font-size: 22px; color: #39d7ff; }
        .header .subtitle { font-size: 13px; color: #888; margin-top: 4px; }
        .container { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 14px; padding: 18px; max-width: 1600px; margin: auto; }
        .card { background: #0a1427; border-radius: 6px; padding: 18px; border: 1px solid #1d3154; }
        .card { grid-column: span 6; } .card-full { grid-column: 1 / -1; } .card-wide { grid-column: span 8; }
        .card h2 { font-size: 16px; color: #39d7ff; margin-bottom: 12px;
                   border-bottom: 1px solid #0f3460; padding-bottom: 8px; }
        .status-up { color: #00d68f; }
        .status-down { color: #ff5252; }
        .metric-row { display: flex; justify-content: space-between; padding: 6px 0;
                      border-bottom: 1px solid #0f3460; font-size: 13px; }
        .metric-label { color: #aaa; }
        .metric-value { color: #e0e0e0; font-weight: 600; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th { text-align: left; padding: 8px; color: #39d7ff; border-bottom: 1px solid #0f3460; }
        td { padding: 6px 8px; border-bottom: 1px solid #0f3460; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
        .badge-up { background: #00d68f33; color: #00d68f; }
        .badge-down { background: #ff525233; color: #ff5252; }
        .badge-warn { background: #ffb54733; color: #ffb547; }
        .badge-off { background: #69738633; color: #aab7cf; }
        .log-level { cursor: pointer; }
        .log-level:hover { background: #0f3460; }
        .tabs { display: flex; gap: 4px; margin-bottom: 12px; }
        .tab { padding: 6px 16px; border-radius: 4px 4px 0 0; cursor: pointer;
               background: #0f3460; font-size: 13px; color: #aaa; }
        .tab.active { background: #e94560; color: #fff; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        pre { background: #0d1117; padding: 12px; border-radius: 6px; overflow-x: auto;
              font-size: 12px; color: #c9d1d9; max-height: 400px; }
        .refresh-btn { background: #0f3460; border: none; color: #39d7ff; padding: 6px 16px;
                       border-radius: 4px; cursor: pointer; font-size: 12px; float: right; }
        .refresh-btn:hover { background: #1a1a3e; }
        .auth-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 14px; }
        .auth-bar label, .auth-state { color: #aaa; font-size: 12px; }
        .auth-bar input { width: min(440px, 100%); padding: 7px 9px; border: 1px solid #1d3154;
                          border-radius: 4px; background: #0a1427; color: #e7efff; }
        .auth-bar button { padding: 7px 10px; border: 1px solid #1d3154; border-radius: 4px;
                           background: #0f3460; color: #39d7ff; cursor: pointer; }
        .pagination { display: flex; justify-content: flex-end; align-items: center; gap: 8px;
                      margin-top: 10px; color: #aab7cf; font-size: 12px; }
        .pagination button { padding: 5px 9px; border: 1px solid #1d3154; border-radius: 4px;
                             background: #0f3460; color: #39d7ff; cursor: pointer; }
        .pagination button:disabled { cursor: not-allowed; opacity: .45; }
        .pagination label { display: flex; align-items: center; gap: 5px; }
        .pagination input { width: 54px; padding: 4px 6px; border: 1px solid #1d3154;
                            border-radius: 4px; background: #071225; color: #e7efff; }
        .spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid #0f3460;
                   border-top: 2px solid #e94560; border-radius: 50%; animation: spin 1s linear infinite; }
        @keyframes spin { 100% { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <div class="header">
        <h1>__ADMIN_TITLE__</h1>
        <div class="subtitle">__ADMIN_SUBTITLE__</div>
        <button id="refresh-dashboard" class="refresh-btn" type="button">刷新</button>
        <div class="auth-bar">
            <label for="actuator-token">管理员 Access Token</label>
            <input id="actuator-token" type="password" autocomplete="off" placeholder="登录后自动读取，或在此粘贴 JWT">
            <button id="apply-actuator-token" type="button">应用 Token</button>
            <button id="clear-actuator-token" type="button">清除面板 Token</button>
            <span id="auth-state" class="auth-state"></span>
        </div>
    </div>
    <div class="container">
        <!-- 健康状态 -->
        <div class="card">
            <h2>健康状态</h2>
            <div id="health"><span class="spinner"></span> 加载中...</div>
        </div>
        __ALERTS_CARD__
        <!-- 系统信息 -->
        <div class="card">
            <h2>系统信息</h2>
            <div id="info"><span class="spinner"></span> 加载中...</div>
        </div>
        __SYSTEM_METRICS_CARD__
        __THREADS_CARD__
        __REQUEST_METRICS_CARD__
        __LOGGERS_CARD__
        __PROMETHEUS_CARD__
        __BEANS_CARD__
    </div>
    <script>
    const ACTUATOR_TOKEN_KEY = 'springbootai_actuator_token';
    const ACTUATOR_ENDPOINTS = __ACTUATOR_ENDPOINTS__;
    // 只有 management.admin.request-metrics.enabled=true 才启用。
    const REQUEST_METRICS_URL = __REQUEST_METRICS_URL__;

    function normalizeToken(token) {
        return (token || '').replace(/^Bearer\\s+/i, '').trim();
    }

    function getDashboardToken() {
        return normalizeToken(sessionStorage.getItem(ACTUATOR_TOKEN_KEY) ||
            localStorage.getItem(ACTUATOR_TOKEN_KEY));
    }

    function getApplicationToken() {
        // These keys belong to the application's login flow.  The dashboard may
        // reuse them for authenticated requests but must never delete them.
        return normalizeToken(localStorage.getItem('welding_token') ||
            localStorage.getItem('access_token') || localStorage.getItem('token'));
    }

    function getActuatorToken() {
        const stored = getDashboardToken() || getApplicationToken();
        return stored;
    }

    function actuatorFetch(url, options) {
        const requestOptions = options || {};
        const headers = new Headers(requestOptions.headers || {});
        const token = getActuatorToken();
        if (token && !headers.has('Authorization')) {
            headers.set('Authorization', 'Bearer ' + token);
        }
        return fetch(url, Object.assign({}, requestOptions, {headers: headers}));
    }

    function updateAuthState(message) {
        const dashboardToken = getDashboardToken();
        const applicationToken = getApplicationToken();
        const input = document.getElementById('actuator-token');
        // Do not copy an application-login token into this input.  Otherwise a
        // cleared dashboard token appears to come back and looks undeletable.
        if (input && dashboardToken && !input.value) input.value = dashboardToken;
        document.getElementById('auth-state').textContent = message ||
            (dashboardToken ? '已保存面板 Access Token' :
                (applicationToken ? '当前使用应用登录 Token（由登录页管理）' :
                    '未配置 Token：仅显示公开端点'));
    }

    function saveActuatorToken() {
        const input = document.getElementById('actuator-token');
        const token = (input && input.value || '').replace(/^Bearer\\s+/i, '').trim();
        if (!token) {
            updateAuthState('请输入 Access Token 后再应用');
            return;
        }
        sessionStorage.setItem(ACTUATOR_TOKEN_KEY, token);
        // Also keep the value in local storage so a new tab can reuse it.
        localStorage.setItem(ACTUATOR_TOKEN_KEY, token);
        updateAuthState('Access Token 已保存，刷新后的请求会自动携带它');
        loadAll();
    }

    function clearActuatorToken() {
        sessionStorage.removeItem(ACTUATOR_TOKEN_KEY);
        localStorage.removeItem(ACTUATOR_TOKEN_KEY);
        const input = document.getElementById('actuator-token');
        if (input) input.value = '';
        updateAuthState(getApplicationToken() ?
            '面板 Token 已清除；当前仍使用应用登录 Token' : '面板 Access Token 已清除');
        loadAll();
    }

    function fetchJSON(url) {
        return actuatorFetch(url).then(r => r.ok ? r.json() : {error: r.status});
    }
    function escapeHtml(value) {
        var node = document.createElement('span');
        node.textContent = value === null || value === undefined ? '' : String(value);
        return node.innerHTML;
    }
    function loadHealth() {
        fetchJSON('/actuator/health').then(d => {
            var el = document.getElementById('health');
            if (d.error) { el.innerHTML = '<span class="status-down">无法获取</span>'; return; }
            var status = d.status || 'UNKNOWN';
            var cls = status === 'UP' ? 'badge-up' : (status === 'DOWN' ? 'badge-down' : 'badge-warn');
            var html = '<div class="metric-row"><span class="metric-label">状态</span>' +
                '<span class="badge ' + cls + '">' + status + '</span></div>';
            if (d.components) {
                Object.keys(d.components).forEach(function(k) {
                    var component = d.components[k] || {};
                    var s = component.status || 'N/A';
                    // 未配置/未启用的基础设施不是故障，也不应占用业务运维面板。
                    // Health JSON 仍保留它们，便于 API 或诊断工具需要完整检查结果时使用。
                    if (component.enabled === false || s === 'DISABLED') return;
                    var c = s === 'UP' ? 'badge-up' : 'badge-down';
                    var label = s;
                    html += '<div class="metric-row"><span class="metric-label">' + k +
                        '</span><span class="badge ' + c + '">' + label + '</span></div>';
                });
            }
            el.innerHTML = html;
        });
    }
    function loadInfo() {
        fetchJSON('/actuator/info').then(d => {
            var el = document.getElementById('info');
            if (d.error) { el.innerHTML = '无法获取'; return; }
            var html = '';
            // /actuator/info follows the Spring Boot shape: application + framework.
            // Keep the old app/python/os shape as a compatibility fallback.
            var app = d.application || d.app || {};
            var framework = d.framework || {};
            if (app && Object.keys(app).length) {
                html += '<div class="metric-row"><span class="metric-label">应用</span>' +
                    '<span class="metric-value">' + (app.name || '-') + '</span></div>';
                html += '<div class="metric-row"><span class="metric-label">版本</span>' +
                    '<span class="metric-value">' + (app.version || '-') + '</span></div>';
                if (app.profile) {
                    html += '<div class="metric-row"><span class="metric-label">环境</span>' +
                        '<span class="metric-value">' + app.profile + '</span></div>';
                }
            }
            var python = d.python || {};
            var pythonVersion = framework.python || python.version || d.python_version;
            if (pythonVersion) {
                html += '<div class="metric-row"><span class="metric-label">Python</span>' +
                    '<span class="metric-value">' + pythonVersion + '</span></div>';
            }
            if (framework.name || framework.version) {
                html += '<div class="metric-row"><span class="metric-label">框架</span>' +
                    '<span class="metric-value">' + (framework.name || 'SpringBootAI') +
                    (framework.version ? ' ' + framework.version : '') + '</span></div>';
            }
            if (d.os) {
                html += '<div class="metric-row"><span class="metric-label">系统</span>' +
                    '<span class="metric-value">' + d.os.name + '</span></div>';
            }
            el.innerHTML = html || '<span class="metric-label">无信息</span>';
        });
    }
    function loadSystemMetrics() {
        if (!ACTUATOR_ENDPOINTS.sysmetrics) return;
        fetchJSON('/actuator/sysmetrics').then(d => {
            var el = document.getElementById('metrics-system');
            if (d.error) { el.innerHTML = '<span class="status-down">' + d.error + '</span>'; return; }
            var html = '';
            html += '<div class="metric-row"><span class="metric-label">RSS 内存</span>' +
                '<span class="metric-value">' + d.rss_mb + ' MB</span></div>';
            html += '<div class="metric-row"><span class="metric-label">虚拟内存</span>' +
                '<span class="metric-value">' + d.vms_mb + ' MB</span></div>';
            html += '<div class="metric-row"><span class="metric-label">CPU 使用率</span>' +
                '<span class="metric-value">' + d.cpu_percent + '%</span></div>';
            html += '<div class="metric-row"><span class="metric-label">线程数</span>' +
                '<span class="metric-value">' + d.num_threads + '</span></div>';
            html += '<div class="metric-row"><span class="metric-label">FD 数</span>' +
                '<span class="metric-value">' + d.num_fds + '</span></div>';
            el.innerHTML = html;
        });
    }
    function loadThreads() {
        if (!ACTUATOR_ENDPOINTS.threaddump) return;
        fetchJSON('/actuator/threaddump').then(d => {
            var el = document.getElementById('threads-summary');
            if (d.error || !d.threads) { el.innerHTML = '无法获取'; return; }
            var alive = d.threads.filter(function(t) { return t.threadState === 'RUNNABLE'; }).length;
            var daemon = d.threads.filter(function(t) { return t.daemon; }).length;
            var html = '<div class="metric-row"><span class="metric-label">总线程</span>' +
                '<span class="metric-value">' + d.threads.length + '</span></div>';
            html += '<div class="metric-row"><span class="metric-label">活动</span>' +
                '<span class="metric-value">' + alive + '</span></div>';
            html += '<div class="metric-row"><span class="metric-label">守护</span>' +
                '<span class="metric-value">' + daemon + '</span></div>';
            el.innerHTML = html;
        });
    }
    var loggerEntries = [];
    var loggerPage = 1;
    var loggerPageSize = __ADMIN_PAGE_SIZE__;

    function renderPagination(page, pageSize, total) {
        var pages = Math.max(1, Math.ceil(total / pageSize));
        page = Math.min(Math.max(page, 1), pages);
        return '<div class="pagination">' +
            '<button type="button" data-page-step="-1"' + (page <= 1 ? ' disabled' : '') + '>上一页</button>' +
            '<span>第 ' + page + ' / ' + pages + ' 页，共 ' + total + ' 条</span>' +
            '<label>跳转 <input class="page-input" type="number" min="1" max="' + pages + '" value="' + page + '" aria-label="跳转页码"></label>' +
            '<button type="button" data-page-jump>跳转</button>' +
            '<button type="button" data-page-step="1"' + (page >= pages ? ' disabled' : '') + '>下一页</button>' +
            '</div>';
    }

    function bindPagination(container, page, pageSize, total, onPageChange) {
        var pages = Math.max(1, Math.ceil(total / pageSize));
        var input = container.querySelector('.page-input');
        function jump(value) {
            var target = Number.parseInt(value, 10);
            if (!Number.isFinite(target)) target = page;
            onPageChange(Math.min(Math.max(target, 1), pages));
        }
        container.querySelectorAll('[data-page-step]').forEach(function(button) {
            button.addEventListener('click', function() { jump(page + Number(button.dataset.pageStep)); });
        });
        container.querySelector('[data-page-jump]').addEventListener('click', function() { jump(input.value); });
        input.addEventListener('keydown', function(event) {
            if (event.key === 'Enter') jump(input.value);
        });
    }
    function loadRequestMetrics() {
        if (!REQUEST_METRICS_URL) return;
        fetchJSON(REQUEST_METRICS_URL).then(d => {
            var el = document.getElementById('request-metrics');
            if (!el) return;
            if (d.error || d.code && d.code !== 200) {
                el.innerHTML = '<span class="status-down">无法获取请求统计' +
                    (d.error ? '（HTTP ' + escapeHtml(d.error) + '）' : '') + '</span>';
                return;
            }
            // 兼容框架 Result 包装（{code, data}）和直接返回数据的业务端点。
            var payload = d.data || d || {};
            var items = Array.isArray(payload.items) ? payload.items : [];
            var requests = 0, errors = 0, totalMs = 0;
            items.forEach(function(item) {
                requests += Number(item.request_count || 0);
                errors += Number(item.error_count || 0);
                totalMs += Number(item.total_ms || 0);
            });
            var html = '<div class="metric-row"><span class="metric-label">统计方式</span>' +
                '<span class="metric-value">' + (payload.persistent ? '数据库持久化' : '接口返回') + '</span></div>';
            html += '<div class="metric-row"><span class="metric-label">请求总数</span>' +
                '<span class="metric-value">' + requests + '</span></div>';
            html += '<div class="metric-row"><span class="metric-label">错误总数</span>' +
                '<span class="metric-value">' + errors + '</span></div>';
            html += '<div class="metric-row"><span class="metric-label">平均耗时</span>' +
                '<span class="metric-value">' + (requests ? (totalMs / requests).toFixed(2) : '0.00') + ' ms</span></div>';
            if (items.length) {
                html += '<div class="metric-row"><span class="metric-label">最常访问</span>' +
                    '<span class="metric-value">' + escapeHtml(items[0].path || '-') + '</span></div>';
            }
            el.innerHTML = html;
        }).catch(function() {
            var el = document.getElementById('request-metrics');
            if (el) el.innerHTML = '<span class="status-down">请求统计加载失败</span>';
        });
    }

    function renderLoggers() {
        var el = document.getElementById('loggers');
        var pages = Math.max(1, Math.ceil(loggerEntries.length / loggerPageSize));
        loggerPage = Math.min(Math.max(loggerPage, 1), pages);
        var start = (loggerPage - 1) * loggerPageSize;
        var pageEntries = loggerEntries.slice(start, start + loggerPageSize);
        var html = '<table><thead><tr><th>Logger</th><th>级别</th></tr></thead><tbody>';
        pageEntries.forEach(function(e) {
            var cls = e[1] === 'ERROR' ? 'badge-down' :
                e[1] === 'WARNING' ? 'badge-warn' : 'badge-up';
            html += '<tr class="log-level" data-logger="' + encodeURIComponent(e[0]) + '">' +
                '<td>' + e[0] + '</td><td><span class="badge ' + cls + '">' + e[1] + '</span></td></tr>';
        });
        html += '</tbody></table>';
        html += renderPagination(loggerPage, loggerPageSize, loggerEntries.length);
        el.innerHTML = html;
        el.querySelectorAll('[data-logger]').forEach(function(row) {
            row.addEventListener('click', function() {
                cycleLogLevel(decodeURIComponent(row.getAttribute('data-logger')));
            });
        });
        bindPagination(el, loggerPage, loggerPageSize, loggerEntries.length, function(page) {
            loggerPage = page;
            renderLoggers();
        });
    }

    function changeLoggerPage(delta) {
        loggerPage += delta;
        renderLoggers();
    }

    function loadLoggers() {
        if (!ACTUATOR_ENDPOINTS.loggers) return;
        fetchJSON('/actuator/loggers').then(d => {
            var el = document.getElementById('loggers');
            if (d.error || !d.loggers) { el.innerHTML = '无法获取'; return; }
            loggerEntries = Object.entries(d.loggers).sort(function(a, b) {
                return a[0].localeCompare(b[0]);
            });
            renderLoggers();
        });
    }
    function cycleLogLevel(name) {
        var levels = ['DEBUG','INFO','WARNING','ERROR'];
        fetchJSON('/actuator/loggers/' + name).then(function(d) {
            var current = d.effectiveLevel || 'INFO';
            var idx = levels.indexOf(current);
            var next = levels[(idx + 1) % levels.length];
            actuatorFetch('/actuator/loggers/' + name, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({configuredLevel: next})
            }).then(function() { loadLoggers(); });
        });
    }
    function loadPrometheus() {
        if (!ACTUATOR_ENDPOINTS.prometheus) return;
        actuatorFetch('/actuator/prometheus').then(function(r) {
            return r.ok ? r.text() : '# error: ' + r.status;
        }).then(function(text) {
            document.getElementById('prom-raw-text').textContent = text;
            // 解析摘要
            var lines = text.split('\\n');
            var metrics = {};
            lines.forEach(function(line) {
                if (line.startsWith('# TYPE ')) {
                    var parts = line.split(' ');
                    if (parts.length >= 4) {
                        metrics[parts[2]] = {type: parts[3], value: '-'};
                    }
                } else if (line && !line.startsWith('#')) {
                    var spaceIdx = line.indexOf(' ');
                    if (spaceIdx > 0) {
                        var name = line.substring(0, spaceIdx).split('{')[0];
                        var val = line.substring(spaceIdx + 1);
                        if (metrics[name]) { metrics[name].value = val; }
                    }
                }
            });
            var html = '';
            Object.entries(metrics).forEach(function(e) {
                var typeCls = e[1].type === 'counter' ? 'badge-up' : 'badge-warn';
                html += '<tr><td>' + e[0] + '</td><td><span class="badge ' + typeCls +
                    '">' + e[1].type + '</span></td><td>' + e[1].value + '</td></tr>';
            });
            document.getElementById('prom-summary-body').innerHTML = html ||
                '<tr><td colspan=3>无指标</td></tr>';
        });
    }
    var beanEntries = [];
    var beanPage = 1;
    var beanPageSize = __ADMIN_PAGE_SIZE__;

    function renderBeans() {
        var el = document.getElementById('beans');
        var pages = Math.max(1, Math.ceil(beanEntries.length / beanPageSize));
        beanPage = Math.min(Math.max(beanPage, 1), pages);
        var start = (beanPage - 1) * beanPageSize;
        var pageEntries = beanEntries.slice(start, start + beanPageSize);
        var html = '<table><thead><tr><th>Bean 名</th><th>类型</th><th>Scope</th></tr></thead><tbody>';
        pageEntries.forEach(function(e) {
            html += '<tr><td>' + e[0] + '</td><td>' + (e[1].type || '-') +
                '</td><td>' + (e[1].scope || '-') + '</td></tr>';
        });
        html += '</tbody></table>';
        html += renderPagination(beanPage, beanPageSize, beanEntries.length);
        el.innerHTML = html;
        bindPagination(el, beanPage, beanPageSize, beanEntries.length, function(page) {
            beanPage = page;
            renderBeans();
        });
    }

    function changeBeanPage(delta) {
        beanPage += delta;
        renderBeans();
    }

    function loadBeans() {
        if (!ACTUATOR_ENDPOINTS.beans) return;
        fetchJSON('/actuator/beans').then(d => {
            var el = document.getElementById('beans');
            if (d.error || !d.contexts || !d.contexts.application) { el.innerHTML = '无法获取'; return; }
            var beans = d.contexts.application.beans || {};
            beanEntries = Object.entries(beans).sort(function(a, b) {
                return a[0].localeCompare(b[0]);
            });
            renderBeans();
        });
    }
    function switchTab(el, contentId) {
        document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
        el.classList.add('active');
        document.querySelectorAll('.tab-content').forEach(function(c) { c.classList.remove('active'); });
        document.getElementById(contentId).classList.add('active');
    }
    function loadAlerts() {
        if (!ACTUATOR_ENDPOINTS.alerts) return;
        actuatorFetch('/actuator/alerts')
            .then(r => r.ok ? r.json() : [])
            .then(alerts => {
                if (!alerts || alerts.length === 0) {
                    document.getElementById('alerts').innerHTML =
                        '<span style="color: #4ade80;">✓ 无活跃告警</span>';
                    return;
                }
                let html = '<table class="data-table"><tr><th>告警</th><th>级别</th><th>状态</th><th>实例</th><th>摘要</th><th>时间</th></tr>';
                alerts.slice().reverse().forEach(a => {
                    const sevColor = a.severity === 'critical' ? '#ef4444' :
                                     a.severity === 'warning' ? '#f59e0b' : '#3b82f6';
                    const statusColor = a.status === 'firing' ? '#ef4444' : '#4ade80';
                    const time = a.starts_at ? new Date(a.starts_at).toLocaleString() : '-';
                    html += `<tr>
                        <td>${a.alertname}</td>
                        <td style="color:${sevColor};font-weight:bold;">${a.severity}</td>
                        <td style="color:${statusColor};font-weight:bold;">${a.status}</td>
                        <td>${a.instance || '-'}</td>
                        <td>${a.summary || ''}</td>
                        <td>${time}</td>
                    </tr>`;
                });
                html += '</table>';
                document.getElementById('alerts').innerHTML = html;
            })
            .catch(() => {
                document.getElementById('alerts').innerHTML = '<span style="color:#6b7280;">告警加载失败（需鉴权）</span>';
            });
    }
    function loadAll() {
        loadHealth(); loadInfo();
        loadAlerts(); loadSystemMetrics(); loadThreads(); loadRequestMetrics();
        loadLoggers(); loadPrometheus(); loadBeans();
    }
    // Inline handlers are intentionally avoided for the token and refresh buttons.
    // Explicitly exporting the remaining functions keeps compatibility with older
    // browsers and with the dynamically generated pagination controls.
    function bindDashboardEvents() {
        document.getElementById('refresh-dashboard').addEventListener('click', loadAll);
        document.getElementById('apply-actuator-token').addEventListener('click', saveActuatorToken);
        document.getElementById('clear-actuator-token').addEventListener('click', clearActuatorToken);
    }
    window.loadAll = loadAll;
    window.cycleLogLevel = cycleLogLevel;
    window.changeLoggerPage = changeLoggerPage;
    window.changeBeanPage = changeBeanPage;
    window.switchTab = switchTab;
    window.saveActuatorToken = saveActuatorToken;
    window.clearActuatorToken = clearActuatorToken;
    bindDashboardEvents();
    updateAuthState();
    loadAll();
    setInterval(loadAll, __ADMIN_REFRESH_MS__);  // YAML 配置的自动刷新间隔
    </script>
</body>
</html>'''
    request_metrics_url = (
        _admin_dashboard_config["request_metrics_url"]
        if _admin_dashboard_config["request_metrics_enabled"] else ""
    )
    request_metrics_card = ""
    if request_metrics_url:
        request_metrics_card = (
            '        <!-- 应用请求持久化监控（由 management.admin.request-metrics 配置） -->\n'
            '        <div class="card">\n'
            f'            <h2>{escape(_admin_dashboard_config["request_metrics_title"])}</h2>\n'
            '            <div id="request-metrics"><span class="spinner"></span> 加载中...</div>\n'
            '        </div>'
        )
    endpoint_flags = (
        dict(_actuator_endpoint_enabled)
        if _actuator_configured else
        {name: True for name in _OPTIONAL_ACTUATOR_ENDPOINTS}
    )
    def card(enabled: bool, title: str, body_id: str, *, full: bool = False) -> str:
        cls = ' class="card card-full"' if full else ' class="card"'
        body = (
            '<span class="spinner"></span> 加载中...' if enabled
            else '<span class="metric-label">未启用（请在 management.endpoints.web.exposure 或 management.admin 中配置）</span>'
        )
        return (
            f'        <div{cls}>\n'
            f'            <h2>{escape(title)}</h2>\n'
            f'            <div id="{body_id}">{body}</div>\n'
            '        </div>'
        )
    alerts_card = card(endpoint_flags["alerts"], "告警通知", "alerts")
    system_metrics_card = card(endpoint_flags["sysmetrics"], "内存 & CPU", "metrics-system")
    threads_card = card(endpoint_flags["threaddump"], "线程概览", "threads-summary")
    loggers_card = card(endpoint_flags["loggers"], "日志级别管理（点击切换）", "loggers", full=True)
    beans_card = card(endpoint_flags["beans"], "Bean 列表", "beans", full=True)
    prometheus_state = (
        '<div class="tabs">'
        '<div class="tab active" onclick="switchTab(this,\'prom-raw\')">原始数据</div>'
        '<div class="tab" onclick="switchTab(this,\'prom-summary\')">指标摘要</div></div>'
        '<div id="prom-summary" class="tab-content"><table><thead><tr><th>指标名</th><th>类型</th><th>值</th></tr></thead><tbody id="prom-summary-body"></tbody></table></div>'
        '<div id="prom-raw" class="tab-content active"><pre id="prom-raw-text"><span class="spinner"></span> 加载中...</pre></div>'
        if endpoint_flags["prometheus"] else
        '<div class="metric-label">未启用（请在 management.endpoints.web.exposure 或 prometheus.enabled 中配置）</div>'
    )
    prometheus_card = (
        '        <div class="card card-full">\n'
        '            <h2>Prometheus 指标</h2>\n'
        f'            {prometheus_state}\n'
        '        </div>'
    )
    # 文本进入 HTML/JavaScript 前均转义；数值已经在配置解析阶段限制为正整数。
    return (html
            .replace("__ADMIN_TITLE__", escape(_admin_dashboard_config["title"]))
            .replace("__ADMIN_SUBTITLE__", escape(_admin_dashboard_config["subtitle"]))
            .replace("__ADMIN_PAGE_SIZE__", str(_admin_dashboard_config["page_size"]))
            .replace("__REQUEST_METRICS_CARD__", request_metrics_card)
            .replace("__ALERTS_CARD__", alerts_card)
            .replace("__SYSTEM_METRICS_CARD__", system_metrics_card)
            .replace("__THREADS_CARD__", threads_card)
            .replace("__LOGGERS_CARD__", loggers_card)
            .replace("__PROMETHEUS_CARD__", prometheus_card)
            .replace("__BEANS_CARD__", beans_card)
            .replace("__REQUEST_METRICS_URL__", json.dumps(request_metrics_url))
            .replace("__ACTUATOR_ENDPOINTS__", json.dumps(endpoint_flags))
            .replace(
                "__ADMIN_REFRESH_MS__",
                str(_admin_dashboard_config["refresh_interval_seconds"] * 1000),
            ))


@actuator_router.get('/admin', response_class=HTMLResponse)
@actuator_router.get('/admin/', response_class=HTMLResponse)
def admin_dashboard():
    """Spring Boot Admin 风格可视化面板。

    访问 ``/actuator/admin`` 即可打开 HTML 仪表盘，展示：
    - 健康状态（含组件细分）
    - 系统信息（应用名/版本/Python版本/OS）
    - 内存 & CPU（进程 RSS、CPU 使用率、线程数）
    - 线程概览（总线程/活动/守护线程数）
    - 日志级别管理（点击表格行动态切换级别）
    - Prometheus 指标（原始数据 + 摘要表格）
    - Bean 列表（IoC 容器中所有 Bean）

    面板每 30 秒自动刷新，也可手动点击"刷新"按钮。
    """
    return HTMLResponse(content=_build_admin_dashboard_html(), status_code=200)
