"""
Spring Cloud AOP 切面实现（企业级版本）
使用真实的分布式组件：Seata事务、Nacos服务发现、Sentinel限流熔断等
"""
from typing import Any, Callable, Dict, List, Optional, Type
import asyncio
import time
import functools
import threading
import inspect
import logging
from spring.annotations.cloud import (
    SentinelResource,
    GlobalTransactional,
    RefreshScope,
    LoadBalanced,
    Valid,
    Validated,
)
from spring.cloud.seata import seata_manager
from spring.cloud.load_balancer import load_balancer
from spring.cloud.sentinel import sentinel_engine, BlockException
from spring.utils.redis_client import redis_client

logger = logging.getLogger("Spring.Cloud.AOP")

# ==================== 全局存储 ====================
_refresh_scope_cache: Dict[str, dict] = {}  # 刷新作用域缓存
_refresh_lock = threading.Lock()  # 刷新锁


# ==================== SentinelResource 熔断限流切面（使用真实Sentinel引擎） ====================
def sentinel_resource_decorator(annotation: SentinelResource):
    """
    Sentinel资源保护注解实现（内嵌Sentinel引擎）
    - block_handler: 处理限流、熔断、系统保护等阻断异常
    - fallback: 处理业务异常、远程调用异常
    - hotkey: 热点参数限流
    """
    def decorator(func: Callable) -> Callable:
        resource_key = annotation.value or f"{func.__module__}.{func.__name__}"
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            entry = None
            try:
                entry = sentinel_engine.entry(resource_key, args=args, kwargs=kwargs)
                start = time.monotonic()
                result = func(*args, **kwargs)
                rt_ms = (time.monotonic() - start) * 1000
                entry.success()
                # 记录到Redis（可选统计）
                _record_to_redis(resource_key, rt_ms, False)
                return result
            except BlockException as e:
                # 限流/熔断阻断 -> block_handler
                logger.warning(f"[Sentinel] Blocked {resource_key}: {e.rule_type}")
                _record_to_redis(resource_key, 0, True, blocked=True)
                handler_name = annotation.block_handler
                if handler_name:
                    handler_func = _find_handler(args, handler_name)
                    if handler_func:
                        return handler_func(*args[1:], **kwargs)
                raise
            except Exception as e:
                # 业务异常 -> fallback
                if entry:
                    entry.error()
                # 检查异常忽略列表
                if annotation.exceptions_to_ignore:
                    if any(isinstance(e, exc_type) for exc_type in annotation.exceptions_to_ignore):
                        raise
                _record_to_redis(resource_key, 0, True)
                fallback_name = annotation.fallback
                if fallback_name:
                    fallback_func = _find_handler(args, fallback_name)
                    if fallback_func:
                        logger.warning(f"[Sentinel] Fallback triggered for {resource_key}: {e}")
                        return fallback_func(*args[1:], **kwargs)
                raise
        return wrapper
    return decorator


def _find_handler(args: tuple, handler_name: str) -> Optional[Callable]:
    """查找实例方法作为handler"""
    if args and hasattr(args[0], handler_name):
        handler = getattr(args[0], handler_name, None)
        if callable(handler):
            return handler
    return None


def _record_to_redis(resource_key: str, rt_ms: float, is_error: bool, blocked: bool = False):
    """将统计数据记录到Redis（可选，用于集群模式）"""
    redis = redis_client.get_client()
    if redis is None:
        return
    try:
        pipe = redis.pipeline()
        pipe.hincrby(f"sentinel_stats:{resource_key}", "total", 1)
        if blocked:
            pipe.hincrby(f"sentinel_stats:{resource_key}", "blocked", 1)
        if is_error and not blocked:
            pipe.hincrby(f"sentinel_stats:{resource_key}", "error", 1)
        if rt_ms > 0:
            pipe.hincrbyfloat(f"sentinel_stats:{resource_key}", "rt_total", rt_ms)
            pipe.hincrby(f"sentinel_stats:{resource_key}", "success", 1)
        pipe.hset(f"sentinel_stats:{resource_key}", "last_access", str(time.time()))
        pipe.expire(f"sentinel_stats:{resource_key}", 3600)
        pipe.execute()
    except Exception:
        pass


# ==================== GlobalTransactional 分布式事务切面（Seata集成） ====================
def global_transactional_decorator(annotation: GlobalTransactional):
    """
    Seata全局事务注解实现（真实Seata集成）
    - 仅事务发起入口方法添加
    - 不支持嵌套事务
    - 使用Seata事务管理器进行事务管理
    """
    def decorator(func: Callable) -> Callable:
        def begin_transaction():
            return seata_manager.begin_transaction(
                timeout=annotation.timeout,
                name=annotation.name or func.__name__,
            )

        def commit_transaction(tx_id: str, duration: float) -> None:
            if duration * 1000 > annotation.timeout:
                raise TimeoutError(f"Transaction timeout after {duration:.2f}s")
            if not seata_manager.commit_transaction(tx_id):
                raise RuntimeError(f"Global transaction commit failed: {tx_id}")

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                if seata_manager.is_in_transaction():
                    logger.warning("[GlobalTransactional] Nested transaction detected, skipping")
                    return await func(*args, **kwargs)
                mode = seata_manager.get_mode()
                if mode in {"http", "distributed"}:
                    tx_id = await asyncio.to_thread(begin_transaction)
                    if mode == "http":
                        transaction_context = await asyncio.to_thread(
                            seata_manager.get_transaction_context, tx_id
                        )
                        if transaction_context is None:
                            seata_manager._cleanup_context()
                            raise RuntimeError(
                                f"Unable to bind durable HTTP transaction context: {tx_id}"
                            )
                    else:
                        transaction_context = {
                            'in_transaction': True,
                            'tx_id': tx_id,
                            'status': 'Begin',
                            'timeout': annotation.timeout,
                            'start_time': time.time(),
                            'name': annotation.name or func.__name__,
                        }
                    seata_manager.bind_transaction_context(transaction_context)
                else:
                    tx_id = begin_transaction()
                start_time = time.monotonic()
                try:
                    result = await func(*args, **kwargs)
                except Exception:
                    if seata_manager.is_in_transaction():
                        try:
                            await asyncio.to_thread(
                                seata_manager.rollback_transaction, tx_id
                            )
                        finally:
                            # Context changes in to_thread stay in its copied
                            # context, so clear the event-loop task explicitly.
                            seata_manager._cleanup_context()
                    raise

                try:
                    await asyncio.to_thread(
                        commit_transaction,
                        tx_id,
                        time.monotonic() - start_time,
                    )
                    return result
                finally:
                    seata_manager._cleanup_context()

            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 检查是否已经在事务中
            if seata_manager.is_in_transaction():
                logger.warning("[GlobalTransactional] Nested transaction detected, skipping")
                return func(*args, **kwargs)
            
            # 开启分布式事务
            tx_id = begin_transaction()
            
            logger.info(f"[GlobalTransactional] Begin transaction: {tx_id}")
            
            start_time = time.monotonic()
            
            try:
                result = func(*args, **kwargs)
                
                # 检查执行时间是否超时
                duration = time.monotonic() - start_time
                commit_transaction(tx_id, duration)
                logger.info(f"[GlobalTransactional] Commit transaction: {tx_id}, duration={duration:.4f}s")
                
                return result
            
            except Exception as e:
                # 异常触发回滚
                if seata_manager.is_in_transaction():
                    seata_manager.rollback_transaction(tx_id)
                logger.error(f"[GlobalTransactional] Rollback transaction: {tx_id}, error={str(e)}")
                raise
        return wrapper
    return decorator


# ==================== RefreshScope 配置刷新切面 ====================
def refresh_scope_decorator(annotation: RefreshScope):
    """
    配置刷新作用域注解实现
    - 仅加了该注解的类，配置变更才会自动刷新
    - 会创建代理类，存在循环依赖的Bean会启动直接报错
    """
    def decorator(cls: type) -> type:
        original_attrs = cls.__dict__.copy()
        
        class RefreshProxy(cls):
            _refresh_key = f"refresh_scope:{cls.__module__}.{cls.__name__}"
            
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                with _refresh_lock:
                    if self._refresh_key not in _refresh_scope_cache:
                        _refresh_scope_cache[self._refresh_key] = {
                            "last_refresh": time.time(),
                            "config_version": 0,
                            "instance": self,
                        }
            
            def _refresh_config(self):
                """手动触发配置刷新"""
                with _refresh_lock:
                    cache_entry = _refresh_scope_cache.get(self._refresh_key)
                    if cache_entry:
                        cache_entry["last_refresh"] = time.time()
                        cache_entry["config_version"] += 1
                        logger.info(f"[RefreshScope] Config refreshed for {self._refresh_key}, version={cache_entry['config_version']}")
        
        for key, value in original_attrs.items():
            if key not in ('__dict__', '__weakref__', '__class__', '__module__', '__name__'):
                setattr(RefreshProxy, key, value)
        
        return RefreshProxy
    return decorator


# ==================== LoadBalanced 负载均衡切面（真实负载均衡） ====================
def load_balanced_decorator(annotation: LoadBalanced):
    """
    负载均衡注解实现（真实负载均衡算法）
    - 仅作用于@Bean修饰的RestTemplate
    - 使用全局负载均衡器进行实例选择
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 创建RestTemplate实例
            rest_template = func(*args, **kwargs)
            
            # 添加负载均衡能力
            if isinstance(rest_template, dict):
                rest_template['load_balanced'] = True
                rest_template['strategy'] = annotation.strategy
            elif hasattr(rest_template, '__dict__'):
                rest_template.__dict__['load_balanced'] = True
                rest_template.__dict__['strategy'] = annotation.strategy
            
            # 设置负载均衡策略
            load_balancer.set_strategy(annotation.strategy)
            
            logger.info(f"[LoadBalanced] RestTemplate created with load balancing enabled, strategy={annotation.strategy}")
            return rest_template
        return wrapper
    return decorator


# ==================== Valid 参数校验切面 ====================
def valid_decorator(annotation: Valid):
    """
    参数校验注解实现
    - 实体类参数校验必须配合@RequestBody使用
    - 嵌套实体校验，内部实体必须添加@Valid
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            errors = []
            
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()
            
            for param_name, value in bound_args.arguments.items():
                if param_name == 'self' or value is None:
                    continue
                
                if value == "":
                    errors.append(f"{param_name} cannot be empty")
                
                if hasattr(value, '__dict__'):
                    for nested_key, nested_value in value.__dict__.items():
                        if nested_value is None:
                            errors.append(f"{param_name}.{nested_key} cannot be null")
            
            if errors:
                raise Exception("Validation failed: " + "; ".join(errors))
            
            return func(*args, **kwargs)
        return wrapper
    return decorator


# ==================== Validated 参数校验切面（分组校验） ====================
def validated_decorator(annotation: Validated):
    """
    参数校验注解实现（分组校验）
    - 和@Valid区别：@Validated支持分组校验
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            errors = []
            
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()
            
            for param_name, value in bound_args.arguments.items():
                if param_name == 'self' or value is None:
                    continue
                
                if isinstance(value, int) or isinstance(value, float):
                    if value < 0:
                        errors.append(f"{param_name} must be non-negative")
                
                if isinstance(value, str):
                    if len(value.strip()) == 0:
                        errors.append(f"{param_name} cannot be blank")
            
            if errors:
                raise Exception("Validation failed: " + "; ".join(errors))
            
            return func(*args, **kwargs)
        return wrapper
    return decorator


# ==================== 注解处理映射 ====================
CLOUD_ANNOTATION_DECORATORS = {
    SentinelResource: sentinel_resource_decorator,
    GlobalTransactional: global_transactional_decorator,
    RefreshScope: refresh_scope_decorator,
    LoadBalanced: load_balanced_decorator,
    Valid: valid_decorator,
    Validated: validated_decorator,
}


def apply_cloud_annotations(target: Any, method: Callable = None) -> Any:
    """应用所有 Cloud 注解"""
    if method is None:
        # 类级别注解
        annotations = getattr(target, '__spring_annotations__', [])
        for annotation in annotations:
            decorator_func = CLOUD_ANNOTATION_DECORATORS.get(type(annotation))
            if decorator_func:
                target = decorator_func(annotation)(target)
        return target
    else:
        # 方法级别注解
        annotations = getattr(method, '__spring_annotations__', [])
        wrapped = method
        for annotation in annotations:
            decorator_func = CLOUD_ANNOTATION_DECORATORS.get(type(annotation))
            if decorator_func:
                wrapped = decorator_func(annotation)(wrapped)
        
        return wrapped


def get_sentinel_stats(resource_key: str = None) -> Dict[str, dict]:
    """获取Sentinel统计数据（从内嵌引擎获取，Redis作为补充）"""
    result = sentinel_engine.get_resource_stats(resource_key)
    redis = redis_client.get_client()
    if redis is not None and resource_key:
        try:
            data = redis.hgetall(f"sentinel_stats:{resource_key}")
            if data:
                result.setdefault(resource_key, {})
                result[resource_key]['redis'] = {
                    "total": int(data.get("total", 0)),
                    "blocked": int(data.get("blocked", 0)),
                    "error": int(data.get("error", 0)),
                    "success": int(data.get("success", 0)),
                    "last_access": float(data.get("last_access", 0)),
                }
        except Exception:
            pass
    return result


def get_transaction_context() -> dict:
    """获取当前事务上下文（从Seata管理器获取）"""
    return {
        'in_transaction': seata_manager.is_in_transaction(),
        'tx_id': seata_manager.get_current_tx_id(),
        'status': seata_manager.get_transaction_status(),
    }


def trigger_config_refresh() -> None:
    """触发全局配置刷新"""
    with _refresh_lock:
        for key, entry in _refresh_scope_cache.items():
            entry["last_refresh"] = time.time()
            entry["config_version"] += 1
            logger.info(f"[RefreshScope] Config refreshed for {key}, version={entry['config_version']}")


def get_refresh_scope_cache() -> Dict[str, dict]:
    """获取刷新作用域缓存"""
    return dict(_refresh_scope_cache)
