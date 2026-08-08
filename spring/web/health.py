"""
健康检查模块
提供Actuator风格的健康检查端点
"""
import time
import logging
import threading
import queue
import platform
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from spring.utils.redis_client import redis_client
from spring.cloud.discovery import nacos_client

try:
    from spring.orm.database import db_manager
except ImportError:
    db_manager = None

logger = logging.getLogger("Spring.Web.Health")

health_router = APIRouter()
_application_context = None


def configure_health_checks(application_context) -> None:
    global _application_context
    _application_context = application_context

# 单个组件健康检查的最大耗时（秒）。
# 避免某个组件（如 Nacos/RabbitMQ 未配置但尝试连接默认地址）卡死整个 /actuator/health 端点，
# 进而拖垮 Docker HEALTHCHECK 与运维监控。
_CHECK_TIMEOUT_SECONDS = 2.0


def _run_with_timeout(func, timeout: float = _CHECK_TIMEOUT_SECONDS):
    """
    在独立 daemon 线程中执行健康检查，超时则立即返回 DOWN，不阻塞主请求。

    使用 daemon 线程而非 concurrent.futures.ThreadPoolExecutor，
    因为后者在 with 块退出时会 shutdown(wait=True) 阻塞等待卡住的任务完成，
    反而会让超时机制失效。daemon 线程超时后主线程立即返回，
    卡住的线程在后台继续运行但不影响响应，进程退出时自动清理。

    Args:
        func: 无参的可调用对象，返回状态字典
        timeout: 最大等待秒数

    Returns:
        检查结果字典；若超时则返回 DOWN + reason
    """
    result_q: "queue.Queue" = queue.Queue()

    def _worker():
        try:
            result_q.put(('ok', func()))
        except Exception as e:
            result_q.put(('err', e))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        # 超时：daemon 线程继续在后台跑，主线程立即返回
        return {
            'status': 'DOWN',
            'enabled': True,
            'reason': f'health check timeout after {timeout}s'
        }

    try:
        kind, val = result_q.get_nowait()
        if kind == 'ok':
            return val
        return {'status': 'DOWN', 'enabled': True, 'reason': str(val)}
    except queue.Empty:
        return {'status': 'DOWN', 'enabled': True, 'reason': 'health check returned no result'}


@health_router.get('/health')
def health_check():
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
    
    # 检查Redis
    redis_status = _run_with_timeout(_check_redis)
    health_status['components']['redis'] = redis_status
    if redis_status['status'] == 'DOWN':
        health_status['status'] = 'DEGRADED'

    # 检查数据库
    db_status = _run_with_timeout(_check_database)
    health_status['components']['database'] = db_status
    if db_status['status'] == 'DOWN':
        health_status['status'] = 'DEGRADED'

    # 检查Nacos
    nacos_status = _run_with_timeout(_check_nacos)
    health_status['components']['nacos'] = nacos_status

    # 检查RabbitMQ
    rabbitmq_status = _run_with_timeout(_check_rabbitmq)
    health_status['components']['rabbitmq'] = rabbitmq_status

    # 检查Seata
    seata_status = _run_with_timeout(_check_seata)
    health_status['components']['seata'] = seata_status
    
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
def readiness_check():
    """
    就绪检查端点
    检查应用是否准备好处理请求
    
    Returns:
        JSON格式的就绪状态
    """
    # 检查核心组件
    redis_status = _run_with_timeout(_check_redis)
    
    # 如果Redis不可用（且启用了），应用可能未就绪
    if redis_status['status'] == 'DOWN' and redis_status.get('enabled', False):
        return JSONResponse(content={
            'status': 'NOT_READY',
            'timestamp': time.time(),
            'reason': 'Redis is unavailable'
        }, status_code=503)
    
    return JSONResponse(content={
        'status': 'READY',
        'timestamp': time.time()
    }, status_code=200)


@health_router.get('/info')
def info_check():
    """返回不包含密钥和连接凭据的应用基本信息。"""
    config = _application_context.get_config() if _application_context is not None else {}
    spring_config = config.get('spring', {}) or {}
    application_config = spring_config.get('application', {}) or {}
    profile_config = spring_config.get('profiles', {}) or {}
    try:
        from spring import __version__ as spring_version
    except ImportError:
        spring_version = 'unknown'

    return JSONResponse(content={
        'application': {
            'name': application_config.get('name', 'springpy-application'),
            'profile': profile_config.get('active', 'default'),
        },
        'framework': {
            'name': 'SpringPy',
            'version': spring_version,
            'python': platform.python_version(),
        },
    }, status_code=200)


def _check_redis() -> dict:
    """检查Redis健康状态"""
    try:
        # 尊重 application.yml 的 redis.enabled 配置：
        # 未启用时不尝试连接，直接返回 DISABLED，避免拖累整体健康状态
        try:
            redis_cfg = (
                _application_context.get_config().get('redis', {})
                if _application_context is not None else {}
            ) or {}
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
            info = client.info()
            return {
                'status': 'UP',
                'enabled': True,
                'version': info.get('redis_version', 'unknown'),
                'used_memory': info.get('used_memory_human', 'unknown')
            }
        else:
            return {
                'status': 'DISABLED',
                'enabled': False,
                'reason': 'Redis not configured'
            }
    except Exception as e:
        return {
            'status': 'DOWN',
            'enabled': True,
            'reason': str(e)
        }


def _check_database() -> dict:
    """检查数据库健康状态"""
    try:
        if _application_context is not None:
            database_config = (
                _application_context.get_config().get('database', {}) or {}
            )
            if not database_config.get('enabled', False):
                return {
                    'status': 'DISABLED',
                    'enabled': False,
                    'reason': 'Database not configured (database.enabled=false)',
                }

        if _application_context is not None and _application_context.contains_bean(
            'sqlSessionFactory'
        ):
            factory = _application_context.get_bean('sqlSessionFactory')
            pooled_connection = factory.connection_pool.get_connection()
            factory.connection_pool.return_connection(pooled_connection)
            return {
                'status': 'UP',
                'enabled': True,
                'type': 'mybatis',
                'pool': factory.connection_pool.get_pool_stats(),
            }

        engine = db_manager.get_engine() if db_manager is not None else None
        if engine:
            connection = engine.connect()
            connection.close()
            return {
                'status': 'UP',
                'enabled': True,
                'url': db_manager.db_url
            }
        else:
            return {
                'status': 'DISABLED',
                'enabled': False,
                'reason': 'Database not configured'
            }
    except Exception as e:
        return {
            'status': 'DOWN',
            'enabled': True,
            'reason': str(e)
        }


def _check_nacos() -> dict:
    """检查Nacos健康状态"""
    try:
        if nacos_client.is_healthy():
            services = nacos_client.get_services()
            return {
                'status': 'UP',
                'enabled': True,
                'server_addr': nacos_client.server_addr,
                'service_count': len(services) if services else 0
            }
        if nacos_client._client is None:
            return {
                'status': 'DISABLED',
                'enabled': False,
                'reason': 'Nacos not configured'
            }
        return {
            'status': 'DOWN',
            'enabled': True,
            'server_addr': nacos_client.server_addr,
            'reason': 'Nacos liveness check failed'
        }
    except Exception as e:
        return {
            'status': 'DOWN',
            'enabled': True,
            'reason': str(e)
        }


def _check_rabbitmq() -> dict:
    """检查RabbitMQ健康状态"""
    try:
        from spring.messaging.rabbitmq import rabbitmq_client
        channel = rabbitmq_client._channel
        if channel:
            # 尝试声明一个临时队列
            result = channel.queue_declare(queue='', exclusive=True)
            channel.queue_delete(queue=result.method.queue)
            return {
                'status': 'UP',
                'enabled': True,
                'host': rabbitmq_client.host,
                'port': rabbitmq_client.port
            }
        else:
            return {
                'status': 'DISABLED',
                'enabled': False,
                'reason': 'RabbitMQ not configured'
            }
    except ImportError:
        return {
            'status': 'DISABLED',
            'enabled': False,
            'reason': 'RabbitMQ not available (pika not installed)'
        }
    except Exception as e:
        return {
            'status': 'DOWN',
            'enabled': True,
            'reason': str(e)
        }


def _check_seata() -> dict:
    """检查Seata健康状态"""
    from spring.cloud.seata import seata_manager
    try:
        if seata_manager._seata_client_initialized:
            return {
                'status': 'UP',
                'enabled': True,
                'server_addr': seata_manager.server_addr,
                'application_id': seata_manager.application_id,
                'transaction_group': seata_manager.transaction_group
            }
        else:
            return {
                'status': 'DISABLED',
                'enabled': False,
                'reason': 'Seata not configured or Seata SDK not available'
            }
    except Exception as e:
        return {
            'status': 'DOWN',
            'enabled': True,
            'reason': str(e)
        }
