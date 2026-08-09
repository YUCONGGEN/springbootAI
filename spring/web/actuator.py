"""Spring Boot Actuator 风格运维端点（扩展既有 ``/actuator/health``）。

在既有 health 端点（``spring.web.health``）基础上补齐标准 Actuator 端点：
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
import logging
import threading
import time
import traceback
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

actuator_router = APIRouter()
_application_context = None

# 敏感键关键词（命中即脱敏，对齐 Spring Boot env 脱敏）
_SENSITIVE_KEYS = ("password", "secret", "token", "credential", "passwd", "api_key", "apikey")


def configure_actuator(application_context) -> None:
    """注入应用上下文（与 ``health.configure_health_checks`` 平行调用）。"""
    global _application_context
    _application_context = application_context


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
        "prometheus": {"href": "/actuator/prometheus", "methods": ["GET"]},
    }
    return {"_links": {k: v for k, v in endpoints.items()}}


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
    """动态修改 logger 级别。``name=root`` 修改 root logger。"""
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
        from spring.monitoring.prometheus import prometheus_metrics
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


# ==================== HTTP 端点（薄包装） ====================

@actuator_router.get('')
@actuator_router.get('/')
def actuator_root():
    return JSONResponse(content=get_endpoint_directory(), status_code=200)


@actuator_router.get('/env')
def env_endpoint():
    return JSONResponse(content=get_env_info(_get_context()), status_code=200)


@actuator_router.get('/loggers')
def loggers_endpoint():
    return JSONResponse(content=get_loggers(), status_code=200)


@actuator_router.get('/loggers/{name}')
def logger_detail(name: str):
    return JSONResponse(content=get_logger_level(name), status_code=200)


@actuator_router.post('/loggers/{name}')
def logger_update(name: str, body: dict = Body(default={})):
    """请求体 ``{"configuredLevel": "DEBUG"}`` 动态修改级别。"""
    level = (body or {}).get("configuredLevel", "INFO")
    try:
        result = set_logger_level(name, level)
        return JSONResponse(content=result, status_code=200)
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=400)


@actuator_router.get('/metrics')
def metrics_endpoint():
    return JSONResponse(content=get_metrics(), status_code=200)


@actuator_router.get('/beans')
def beans_endpoint():
    return JSONResponse(content=get_beans(_get_context()), status_code=200)


@actuator_router.get('/configprops')
def configprops_endpoint():
    return JSONResponse(content=get_configprops(_get_context()), status_code=200)


@actuator_router.get('/mappings')
def mappings_endpoint():
    app = None
    ctx = _get_context()
    if ctx is not None and hasattr(ctx, "web_context"):
        app = ctx.web_context.get_app()
    return JSONResponse(content=get_mappings(app), status_code=200)


@actuator_router.get('/threaddump')
def threaddump_endpoint():
    return JSONResponse(content=get_threaddump(), status_code=200)
