"""
健康检查模块
提供Actuator风格的健康检查端点
"""
import atexit
import time
import logging
import concurrent.futures
import platform
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Mapping
from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from springbootai.utils.redis_client import redis_client
from springbootai.cloud.discovery import nacos_client

try:
    from springbootai.orm.database import db_manager
except ImportError:
    db_manager = None

logger = logging.getLogger("Spring.Web.Health")

health_router = APIRouter()
_application_context = None
_HEALTH_CONTEXT_ATTRIBUTE = "springbootai_health_context"


def configure_health_checks(application_context) -> None:
    global _application_context
    _application_context = application_context
    try:
        web_context = getattr(application_context, "web_context", None)
        app = web_context.get_app() if web_context is not None else None
        if app is not None:
            setattr(app.state, _HEALTH_CONTEXT_ATTRIBUTE, application_context)
    except Exception:
        logger.debug("Unable to bind per-application health context", exc_info=True)


def _context_for_request(request: Optional[Request] = None):
    if request is not None:
        try:
            return getattr(request.app.state, _HEALTH_CONTEXT_ATTRIBUTE)
        except (AttributeError, RuntimeError):
            pass
    return _application_context


def _config_section(name: str, context=None) -> dict:
    """Read a config section defensively for health probes.

    Health endpoints must remain available while configuration is incomplete or
    malformed.  Treat missing/null/scalar sections as empty mappings instead of
    letting an incidental ``AttributeError`` turn the probe itself into 500.
    """
    try:
        active_context = context if context is not None else _application_context
        config = active_context.get_config() if active_context is not None else {}
    except Exception:
        return {}
    if not isinstance(config, Mapping):
        return {}
    section = config.get(name, {})
    return dict(section) if isinstance(section, Mapping) else {}

# 单个组件健康检查的最大耗时（秒）。
# 避免某个组件（如 Nacos/RabbitMQ 未配置但尝试连接默认地址）卡死整个 /actuator/health 端点，
# 进而拖垮 Docker HEALTHCHECK 与运维监控。
_CHECK_TIMEOUT_SECONDS = 2.0

_COMPONENT_CHECKS = {
    'redis': lambda context=None: _check_redis(context),
    'database': lambda context=None: _check_database(context),
    'nacos': lambda context=None: _check_nacos(context),
    'rabbitmq': lambda context=None: _check_rabbitmq(context),
    'seata': lambda context=None: _check_seata(context),
}

# 模块级有界线程池：限制健康检查的总线程数，防止组件卡死时线程无限增长。
#
# 修复线程泄漏（P1）：
# 旧版本每次 /actuator/health 调用都为每个组件创建新的 daemon 线程，
# 组件永久卡住时线程不会终止，频繁探针（如 Docker HEALTHCHECK 每 5s）
# 会不断积累后台线程，最终耗尽内存。
#
# 新版本使用模块级有界线程池：
# - max_workers 限制总线程数（组件数 × 2，留出并发余量）
# - 卡住的 worker 占用槽位但不会新增线程
# - concurrent.futures.wait 使用一个共享截止时间，避免组件超时串行累加
# - 超时的 future 调用 cancel() 清理队列中的待运行任务
# - 进程退出时 atexit 注册 shutdown(wait=False) 不等待卡住的任务
_HEALTH_CHECK_WORKERS = max(len(_COMPONENT_CHECKS) * 2, 10)
_HEALTH_CHECK_POOL = ThreadPoolExecutor(
    max_workers=_HEALTH_CHECK_WORKERS,
    thread_name_prefix="health-check",
)
atexit.register(_HEALTH_CHECK_POOL.shutdown, wait=False)


def _run_with_timeout(func, timeout: float = _CHECK_TIMEOUT_SECONDS):
    """
    在共享有界线程池中执行健康检查，超时返回 DOWN。

    修复线程泄漏：旧版本每次调用创建新的 daemon 线程，组件永久卡死时
    线程不会终止，频繁探针会不断积累后台线程。改用模块级
    ``_HEALTH_CHECK_POOL``，max_workers 限制总线程数，卡住的 worker
    占用有界槽位但不会新增。

    Args:
        func: 无参的可调用对象，返回状态字典
        timeout: 最大等待秒数

    Returns:
        检查结果字典；若超时则返回 DOWN + reason
    """
    future = _HEALTH_CHECK_POOL.submit(func)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        # 超时：尝试取消任务（仅当任务还在队列中未开始时生效；
        # 已运行的无法强制终止，但占用的是有界槽位，不会新增线程）
        future.cancel()
        return {
            'status': 'DOWN',
            'enabled': True,
            'reason': f'health check timeout after {timeout}s'
        }
    except Exception as exc:
        return _failed_health_result("component", exc)


def _failed_health_result(component: str, exc: BaseException) -> dict:
    """Return a stable public failure without exposing credentials/topology."""
    logger.warning(
        "%s health check failed error_type=%s",
        component, type(exc).__name__,
    )
    return {
        'status': 'DOWN',
        'enabled': True,
        'reason': f'{component} health check failed ({type(exc).__name__})',
    }


def _collect_component_health(context=None) -> dict:
    """并发执行各组件检查，复用模块级有界线程池，探针耗时接近单个检查的最大超时。

    修复线程泄漏：旧版本每次调用创建新的 ``ThreadPoolExecutor``（with 块退出时
    ``shutdown(wait=True)`` 阻塞等待卡住任务，反而让超时失效），并在每个
    ``_run_with_timeout`` 内再创建 daemon 线程，导致线程数 = 组件数 × 2 每次调用。
    新版本直接提交到共享有界池，并以一个共享截止时间等待全部组件。
    """
    futures = {
        name: (
            _HEALTH_CHECK_POOL.submit(check, context)
            if context is not None else
            _HEALTH_CHECK_POOL.submit(check)
        )
        for name, check in _COMPONENT_CHECKS.items()
    }
    # 所有组件共享同一截止时间，避免线程池饱和时逐个 future 的 timeout
    # 累加为 ``组件数 × timeout``。
    done, _ = concurrent.futures.wait(
        futures.values(), timeout=_CHECK_TIMEOUT_SECONDS,
    )
    results = {}
    for name, future in futures.items():
        if future not in done:
            future.cancel()
            results[name] = {
                'status': 'DOWN',
                'enabled': True,
                'reason': f'health check timeout after {_CHECK_TIMEOUT_SECONDS}s'
            }
            continue
        try:
            results[name] = future.result()
        except Exception as exc:
            results[name] = _failed_health_result(name, exc)
    return results


def _enabled_down_components(components: dict) -> list:
    return [
        name for name, status in components.items()
        if isinstance(status, Mapping)
        and status.get('enabled', False)
        and status.get('status') == 'DOWN'
    ]


@health_router.get('/health')
def health_check(request: Request = None):
    """
    健康检查端点
    返回所有组件的健康状态
    
    Returns:
        JSON格式的健康状态信息
    """
    health_status = {
        'status': 'UP',
        'timestamp': time.time(),
        'components': {}
    }
    
    if request is None:
        health_status['components'] = _collect_component_health()
    else:
        health_status['components'] = _collect_component_health(
            _context_for_request(request))
    if _enabled_down_components(health_status['components']):
        health_status['status'] = 'DEGRADED'
    
    status_code = 200 if health_status['status'] == 'UP' else 503
    return JSONResponse(content=health_status, status_code=status_code)


@health_router.get('/health/liveness')
def liveness_check():
    """
    存活检查端点
    检查应用是否正在运行
    
    Returns:
        JSON格式的存活状态
    """
    return JSONResponse(content={
        'status': 'UP',
        'timestamp': time.time()
    }, status_code=200)


@health_router.get('/health/readiness')
def readiness_check(request: Request = None):
    """
    就绪检查端点
    检查应用是否准备好处理请求
    
    Returns:
        JSON格式的就绪状态
    """
    components = (
        _collect_component_health()
        if request is None else
        _collect_component_health(_context_for_request(request))
    )
    unavailable = _enabled_down_components(components)
    if unavailable:
        return JSONResponse(content={
            'status': 'NOT_READY',
            'timestamp': time.time(),
            'reason': f"Required components unavailable: {', '.join(unavailable)}",
            'components': components,
        }, status_code=503)
    
    return JSONResponse(content={
        'status': 'READY',
        'timestamp': time.time(),
        'components': components,
    }, status_code=200)


@health_router.get('/info')
def info_check(request: Request = None):
    """返回不包含密钥和连接凭据的应用基本信息。"""
    spring_config = _config_section(
        'spring', _context_for_request(request))
    application_config = (
        dict(spring_config.get('application', {}))
        if isinstance(spring_config.get('application', {}), Mapping) else {}
    )
    profile_config = (
        dict(spring_config.get('profiles', {}))
        if isinstance(spring_config.get('profiles', {}), Mapping) else {}
    )
    try:
        from springbootai import __version__ as spring_version
    except ImportError:
        spring_version = 'unknown'

    return JSONResponse(content={
        'application': {
            'name': application_config.get('name', 'springpy-application'),
            'profile': profile_config.get('active', 'default'),
        },
        'framework': {
            'name': 'SpringBootAI',
            'version': spring_version,
            'python': platform.python_version(),
        },
    }, status_code=200)


def _check_redis(context=None) -> dict:
    """检查Redis健康状态"""
    try:
        # 尊重 application.yml 的 redis.enabled 配置：
        # 未启用时不尝试连接，直接返回 DISABLED，避免拖累整体健康状态
        try:
            redis_cfg = _config_section('redis', context)
            if not redis_cfg.get('enabled', False):
                return {
                    'status': 'DISABLED',
                    'enabled': False,
                    'reason': 'Redis not configured (redis.enabled=false)'
                }
        except Exception:
            # 配置读取失败时回退到原有行为（尝试连接）
            pass

        client = redis_client.get_client()
        if client:
            client.ping()
            return {
                'status': 'UP',
                'enabled': True,
            }
        else:
            return {
                'status': 'DISABLED',
                'enabled': False,
                'reason': 'Redis not configured'
            }
    except Exception as exc:
        return _failed_health_result("redis", exc)


def _check_database(context=None) -> dict:
    """检查数据库健康状态"""
    try:
        active_context = context if context is not None else _application_context
        if active_context is not None:
            database_config = _config_section('database', active_context)
            if not database_config.get('enabled', False):
                return {
                    'status': 'DISABLED',
                    'enabled': False,
                    'reason': 'Database not configured (database.enabled=false)',
                }

        if active_context is not None and active_context.contains_bean(
            'sqlSessionFactory'
        ):
            factory = active_context.get_bean('sqlSessionFactory')
            pooled_connection = factory.connection_pool.get_connection()
            factory.connection_pool.return_connection(pooled_connection)
            return {
                'status': 'UP',
                'enabled': True,
                'type': 'mybatis',
            }

        engine = db_manager.get_engine() if db_manager is not None else None
        if engine:
            connection = engine.connect()
            connection.close()
            return {
                'status': 'UP',
                'enabled': True,
                'type': 'sqlalchemy',
            }
        else:
            return {
                'status': 'DISABLED',
                'enabled': False,
                'reason': 'Database not configured'
            }
    except Exception as exc:
        return _failed_health_result("database", exc)


def _check_nacos(context=None) -> dict:
    """检查Nacos健康状态"""
    try:
        if not _config_section('discovery', context).get('enabled', False):
            return {'status': 'DISABLED', 'enabled': False, 'reason': 'Nacos not configured'}
        if nacos_client.is_healthy():
            return {
                'status': 'UP',
                'enabled': True,
            }
        return {
            'status': 'DOWN',
            'enabled': True,
            'reason': 'Nacos liveness check failed'
        }
    except Exception as exc:
        return _failed_health_result("nacos", exc)


def _check_rabbitmq(context=None) -> dict:
    """检查RabbitMQ健康状态"""
    try:
        if not _config_section('rabbitmq', context).get('enabled', False):
            return {'status': 'DISABLED', 'enabled': False, 'reason': 'RabbitMQ not configured'}
        from springbootai.messaging.rabbitmq import rabbitmq_client
        channel = rabbitmq_client._channel
        if channel:
            # 尝试声明一个临时队列
            result = channel.queue_declare(queue='', exclusive=True)
            channel.queue_delete(queue=result.method.queue)
            return {
                'status': 'UP',
                'enabled': True,
            }
        return {'status': 'DOWN', 'enabled': True, 'reason': 'RabbitMQ channel is unavailable'}
    except ImportError:
        return {
            'status': 'DISABLED',
            'enabled': False,
            'reason': 'RabbitMQ not available (pika not installed)'
        }
    except Exception as exc:
        return _failed_health_result("rabbitmq", exc)


def _check_seata(context=None) -> dict:
    """检查Seata健康状态"""
    from springbootai.cloud.seata import seata_manager
    try:
        seata_config = _config_section('seata', context)
        if not seata_config.get('enabled', False):
            return {'status': 'DISABLED', 'enabled': False, 'reason': 'Seata not configured'}
        mode = str(seata_config.get('mode', 'local')).lower()
        if mode == 'http':
            if seata_manager.get_mode() != 'http':
                return {
                    'status': 'DOWN', 'enabled': True,
                    'reason': 'HTTP compensation coordinator is not initialized',
                }
            return {
                'status': 'UP', 'enabled': True,
                'mode': 'http-compensation',
                'warning': 'Persistent compensation only; no Seata AT consistency',
            }
        if mode == 'local':
            return {
                'status': 'DOWN', 'enabled': True,
                'reason': 'Local mode does not provide distributed transaction guarantees',
            }
        health = seata_manager.check_health()
        status = health.get('status', 'DOWN') if isinstance(health, Mapping) else 'DOWN'
        result = {
            'status': status,
            'enabled': True,
            'mode': 'distributed',
        }
        if status != 'UP':
            result['reason'] = 'Seata bridge health check failed'
        return result
    except Exception as exc:
        return _failed_health_result("seata", exc)
