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
import traceback
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse

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
_SENSITIVE_ENDPOINTS = frozenset({
    "env", "loggers", "metrics", "beans", "configprops", "mappings", "threaddump"
})

# Actuator 鉴权开关（由 configure_actuator 从配置读取）
_actuator_secured = True
_actuator_admin_roles = frozenset({"ADMIN", "ACTUATOR"})


def configure_actuator(application_context) -> None:
    """注入应用上下文 + 读取 Actuator 鉴权配置。

    从 ``management.endpoints.web.security`` 读取：
    - ``enabled``: 是否对敏感端点启用鉴权（生产环境默认 True）
    - ``roles``: 允许访问的角色列表（默认 ADMIN/ACTUATOR）
    """
    global _application_context, _actuator_secured, _actuator_admin_roles
    _application_context = application_context
    try:
        config = application_context.get_config()
        mgmt = config.get('management', {}).get('endpoints', {}).get('web', {}).get('security', {})
        _actuator_secured = mgmt.get('enabled', True)
        roles = mgmt.get('roles')
        if roles:
            _actuator_admin_roles = frozenset(r.upper() for r in roles)
    except Exception:
        pass  # 配置读取失败时保持默认（secured=True）


def _check_actuator_auth():
    """FastAPI 依赖：对敏感端点验证 JWT token + 角色权限。

    - ``_actuator_secured=False`` 时跳过鉴权（开发环境）
    - ``_actuator_secured=True`` 时要求 Bearer JWT 且 roles 包含 ADMIN/ACTUATOR
    """
    if not _actuator_secured:
        return  # 鉴权关闭，放行

    from fastapi import HTTPException

    # FastAPI 依赖注入需要 Request 对象；此函数被 endpoints 直接调用时使用全局 request
    # 通过 inspect 获取 request 参数（兼容 FastAPI 依赖系统）
    raise HTTPException(status_code=401, detail="Actuator authentication required")


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
            from spring.security.jwt_utils import jwt_utils
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
        "prometheus": {"href": "/actuator/prometheus", "methods": ["GET"]},
        "sysmetrics": {"href": "/actuator/sysmetrics", "methods": ["GET"]},
        "admin": {"href": "/actuator/admin", "methods": ["GET"]},
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


# ==================== HTTP 端点（薄包装 + 鉴权） ====================

# 敏感端点鉴权依赖（闭包捕获 endpoint_name）
_env_auth = _create_actuator_dependency("env")
_loggers_auth = _create_actuator_dependency("loggers")
_metrics_auth = _create_actuator_dependency("metrics")
_beans_auth = _create_actuator_dependency("beans")
_configprops_auth = _create_actuator_dependency("configprops")
_mappings_auth = _create_actuator_dependency("mappings")
_threaddump_auth = _create_actuator_dependency("threaddump")


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


# ==================== /prometheus Prometheus 指标端点 ====================

@actuator_router.get('/prometheus')
def prometheus_endpoint():
    """暴露 Prometheus 文本格式指标，供 Prometheus Server 抓取。

    对齐 Spring Boot ``/actuator/prometheus``：
    - 响应 Content-Type: ``text/plain; version=0.0.4; charset=utf-8``
    - 返回 ``prometheus_client.generate_latest()`` 格式数据
    """
    try:
        from spring.monitoring.prometheus import prometheus_metrics
        data = prometheus_metrics.generate_metrics_data()
        return PlainTextResponse(
            content=data.decode('utf-8') if isinstance(data, bytes) else str(data),
            media_type='text/plain; version=0.0.4; charset=utf-8',
        )
    except ImportError:
        return PlainTextResponse(
            content="# prometheus_client not installed\n",
            media_type='text/plain; version=0.0.4; charset=utf-8',
            status_code=503,
        )
    except Exception as e:
        return PlainTextResponse(
            content=f"# error: {e}\n",
            media_type='text/plain; version=0.0.4; charset=utf-8',
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
def sysmetrics_endpoint():
    """进程系统指标端点（供 Admin 面板 JS 调用）。"""
    return JSONResponse(content=get_sysmetrics(), status_code=200)


# ==================== /admin Spring Boot Admin 可视化面板 ====================

def _build_admin_dashboard_html() -> str:
    """构建 Spring Boot Admin 风格的可视化面板 HTML。

    面板通过 JS fetch 异步调用各 Actuator 端点获取数据，
    展示：健康状态、系统信息、内存、线程、日志级别、Prometheus 指标摘要。
    """
    return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SpringBootAI Admin</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: #1a1a2e; color: #e0e0e0; }
        .header { background: #16213e; padding: 20px 30px; border-bottom: 2px solid #0f3460; }
        .header h1 { font-size: 22px; color: #e94560; }
        .header .subtitle { font-size: 13px; color: #888; margin-top: 4px; }
        .container { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; padding: 20px; }
        .card { background: #16213e; border-radius: 8px; padding: 20px; border: 1px solid #0f3460; }
        .card-full { grid-column: 1 / -1; }
        .card h2 { font-size: 16px; color: #e94560; margin-bottom: 12px;
                   border-bottom: 1px solid #0f3460; padding-bottom: 8px; }
        .status-up { color: #00d68f; }
        .status-down { color: #ff5252; }
        .metric-row { display: flex; justify-content: space-between; padding: 6px 0;
                      border-bottom: 1px solid #0f3460; font-size: 13px; }
        .metric-label { color: #aaa; }
        .metric-value { color: #e0e0e0; font-weight: 600; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th { text-align: left; padding: 8px; color: #e94560; border-bottom: 1px solid #0f3460; }
        td { padding: 6px 8px; border-bottom: 1px solid #0f3460; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
        .badge-up { background: #00d68f33; color: #00d68f; }
        .badge-down { background: #ff525233; color: #ff5252; }
        .badge-warn { background: #ffb54733; color: #ffb547; }
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
        .refresh-btn { background: #0f3460; border: none; color: #e94560; padding: 6px 16px;
                       border-radius: 4px; cursor: pointer; font-size: 12px; float: right; }
        .refresh-btn:hover { background: #1a1a3e; }
        .spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid #0f3460;
                   border-top: 2px solid #e94560; border-radius: 50%; animation: spin 1s linear infinite; }
        @keyframes spin { 100% { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <div class="header">
        <h1>SpringBootAI Admin Dashboard</h1>
        <div class="subtitle">Actuator 可视化面板 | Prometheus 指标 | 实时监控</div>
        <button class="refresh-btn" onclick="loadAll()">刷新</button>
    </div>
    <div class="container">
        <!-- 健康状态 -->
        <div class="card">
            <h2>健康状态</h2>
            <div id="health"><span class="spinner"></span> 加载中...</div>
        </div>
        <!-- 系统信息 -->
        <div class="card">
            <h2>系统信息</h2>
            <div id="info"><span class="spinner"></span> 加载中...</div>
        </div>
        <!-- 内存 & CPU -->
        <div class="card">
            <h2>内存 & CPU</h2>
            <div id="metrics-system"><span class="spinner"></span> 加载中...</div>
        </div>
        <!-- 线程概览 -->
        <div class="card">
            <h2>线程概览</h2>
            <div id="threads-summary"><span class="spinner"></span> 加载中...</div>
        </div>
        <!-- 日志级别管理 -->
        <div class="card card-full">
            <h2>日志级别管理（点击切换）</h2>
            <div id="loggers"><span class="spinner"></span> 加载中...</div>
        </div>
        <!-- Prometheus 指标 -->
        <div class="card card-full">
            <h2>Prometheus 指标</h2>
            <div class="tabs">
                <div class="tab active" onclick="switchTab(this,'prom-raw')">原始数据</div>
                <div class="tab" onclick="switchTab(this,'prom-summary')">指标摘要</div>
            </div>
            <div id="prom-summary" class="tab-content">
                <table><thead><tr><th>指标名</th><th>类型</th><th>值</th></tr></thead>
                <tbody id="prom-summary-body"></tbody></table>
            </div>
            <div id="prom-raw" class="tab-content active">
                <pre id="prom-raw-text"><span class="spinner"></span> 加载中...</pre>
            </div>
        </div>
        <!-- Bean 列表 -->
        <div class="card card-full">
            <h2>Bean 列表</h2>
            <div id="beans"><span class="spinner"></span> 加载中...</div>
        </div>
    </div>
    <script>
    function fetchJSON(url) {
        return fetch(url).then(r => r.ok ? r.json() : {error: r.status});
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
                    var s = d.components[k].status || 'N/A';
                    var c = s === 'UP' ? 'badge-up' : 'badge-down';
                    html += '<div class="metric-row"><span class="metric-label">' + k +
                        '</span><span class="badge ' + c + '">' + s + '</span></div>';
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
            if (d.app) {
                html += '<div class="metric-row"><span class="metric-label">应用</span>' +
                    '<span class="metric-value">' + (d.app.name || '-') + '</span></div>';
                html += '<div class="metric-row"><span class="metric-label">版本</span>' +
                    '<span class="metric-value">' + (d.app.version || '-') + '</span></div>';
            }
            if (d.python) {
                html += '<div class="metric-row"><span class="metric-label">Python</span>' +
                    '<span class="metric-value">' + d.python.version + '</span></div>';
            }
            if (d.os) {
                html += '<div class="metric-row"><span class="metric-label">系统</span>' +
                    '<span class="metric-value">' + d.os.name + '</span></div>';
            }
            el.innerHTML = html || '<span class="metric-label">无信息</span>';
        });
    }
    function loadSystemMetrics() {
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
    function loadLoggers() {
        fetchJSON('/actuator/loggers').then(d => {
            var el = document.getElementById('loggers');
            if (d.error || !d.loggers) { el.innerHTML = '无法获取'; return; }
            var html = '<table><thead><tr><th>Logger</th><th>级别</th></tr></thead><tbody>';
            var entries = Object.entries(d.loggers).sort(function(a, b) {
                var order = ['ERROR','WARNING','INFO','DEBUG','NOTSET'];
                return order.indexOf(a[1]) - order.indexOf(b[1]);
            });
            entries.forEach(function(e) {
                var cls = e[1] === 'ERROR' ? 'badge-down' :
                    e[1] === 'WARNING' ? 'badge-warn' : 'badge-up';
                html += '<tr class="log-level" onclick="cycleLogLevel(\\''+e[0]+'\\')">' +
                    '<td>' + e[0] + '</td><td><span class="badge ' + cls + '">' + e[1] + '</span></td></tr>';
            });
            html += '</tbody></table>';
            el.innerHTML = html;
        });
    }
    function cycleLogLevel(name) {
        var levels = ['DEBUG','INFO','WARNING','ERROR'];
        fetchJSON('/actuator/loggers/' + name).then(function(d) {
            var current = d.effectiveLevel || 'INFO';
            var idx = levels.indexOf(current);
            var next = levels[(idx + 1) % levels.length];
            fetch('/actuator/loggers/' + name, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({configuredLevel: next})
            }).then(function() { loadLoggers(); });
        });
    }
    function loadPrometheus() {
        fetch('/actuator/prometheus').then(function(r) {
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
    function loadBeans() {
        fetchJSON('/actuator/beans').then(d => {
            var el = document.getElementById('beans');
            if (d.error || !d.contexts) { el.innerHTML = '无法获取'; return; }
            var beans = d.contexts.application.beans;
            var html = '<table><thead><tr><th>Bean 名</th><th>类型</th><th>Scope</th></tr></thead><tbody>';
            Object.entries(beans).forEach(function(e) {
                html += '<tr><td>' + e[0] + '</td><td>' + (e[1].type || '-') +
                    '</td><td>' + (e[1].scope || '-') + '</td></tr>';
            });
            html += '</tbody></table>';
            el.innerHTML = html;
        });
    }
    function switchTab(el, contentId) {
        document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
        el.classList.add('active');
        document.querySelectorAll('.tab-content').forEach(function(c) { c.classList.remove('active'); });
        document.getElementById(contentId).classList.add('active');
    }
    function loadAll() {
        loadHealth(); loadInfo(); loadSystemMetrics(); loadThreads();
        loadLoggers(); loadPrometheus(); loadBeans();
    }
    loadAll();
    setInterval(loadAll, 30000);  // 30秒自动刷新
    </script>
</body>
</html>'''


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
