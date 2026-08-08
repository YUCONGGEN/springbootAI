"""
Spring Cloud AOP 切面实现（企业级版本）
使用真实的分布式组件：Seata事务、Nacos服务发现、负载均衡等
"""
from typing import Any, Callable, Dict, List, Optional, Type
import time
import functools
import threading
import hashlib
import logging
import inspect
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
from spring.utils.redis_client import redis_client

logger = logging.getLogger("Spring.Cloud.AOP")

# ==================== 全局存储 ====================
_sentinel_storage: Dict[str, dict] = {}  # Sentinel资源状态（本地缓存）
_refresh_scope_cache: Dict[str, dict] = {}  # 刷新作用域缓存
_refresh_lock = threading.Lock()  # 刷新锁

# 分段锁，减少锁竞争
_NUM_SEGMENTS = 32
_segment_locks = [threading.Lock() for _ in range(_NUM_SEGMENTS)]


def _get_segment_lock(key: str) -> threading.Lock:
    """根据 key 获取对应的分段锁"""
    if isinstance(key, str):
        return _segment_locks[hash(key) % _NUM_SEGMENTS]
    return _segment_locks[0]


# ==================== SentinelResource 熔断限流切面 ====================
def sentinel_resource_decorator(annotation: SentinelResource):
    """
    Sentinel资源保护注解实现（Redis持久化）
    - block_handler: 处理限流、黑名单、系统保护等阻断异常
    - fallback: 处理业务异常、远程调用异常
    - hotkey: 热点参数限流
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            resource_key = annotation.value or f"{func.__module__}.{func.__name__}"
            
            # 更新访问时间和请求计数（优先使用Redis）
            redis = redis_client.get_client()
            if redis is not None:
                try:
                    # 使用Hash存储统计信息
                    redis.hset(f"sentinel:{resource_key}", mapping={
                        "last_access": str(time.time()),
                        "total_requests": str(redis.hincrby(f"sentinel:{resource_key}", "total_requests", 1)),
                    })
                    
                    # 热点参数统计
                    if annotation.hotkey and annotation.hotkey in kwargs:
                        hotkey_value = kwargs[annotation.hotkey]
                        redis.hincrby(f"sentinel:{resource_key}:hotkey", str(hotkey_value), 1)
                except Exception as e:
                    logger.warning(f"Redis sentinel stats failed: {e}")
                    # 回退到本地存储
                    _update_local_sentinel_stats(resource_key, annotation, kwargs)
            else:
                _update_local_sentinel_stats(resource_key, annotation, kwargs)
            
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                # 判断是否是阻断异常
                is_block_exception = "block" in str(e).lower() or "rate limit" in str(e).lower()
                
                # block_handler 处理阻断异常
                if is_block_exception and annotation.block_handler:
                    block_handler_func = getattr(args[0], annotation.block_handler, None) if args else None
                    if block_handler_func and callable(block_handler_func):
                        logger.warning(f"[Sentinel] Block handler triggered for {resource_key}: {str(e)}")
                        _update_block_count(resource_key)
                        return block_handler_func(*args[1:], **kwargs)
                
                # fallback 处理业务异常
                if annotation.fallback:
                    fallback_func = getattr(args[0], annotation.fallback, None) if args else None
                    if fallback_func and callable(fallback_func):
                        if annotation.exceptions_to_ignore:
                            if any(isinstance(e, exc_type) for exc_type in annotation.exceptions_to_ignore):
                                raise
                        logger.warning(f"[Sentinel] Fallback triggered for {resource_key}: {str(e)}")
                        _update_error_count(resource_key)
                        return fallback_func(*args[1:], **kwargs)
                
                # 统计错误
                _update_error_count(resource_key)
                raise
        return wrapper
    return decorator


def _update_local_sentinel_stats(resource_key: str, annotation: SentinelResource, kwargs: dict):
    """更新本地Sentinel统计信息"""
    with _get_segment_lock(resource_key):
        if resource_key not in _sentinel_storage:
            _sentinel_storage[resource_key] = {
                "block_count": 0,
                "error_count": 0,
                "last_access": 0,
                "hotkey_stats": {},
                "total_requests": 0,
            }
        
        _sentinel_storage[resource_key]["total_requests"] += 1
        if annotation.hotkey and annotation.hotkey in kwargs:
            hotkey_value = kwargs[annotation.hotkey]
            stats = _sentinel_storage[resource_key]["hotkey_stats"]
            stats[hotkey_value] = stats.get(hotkey_value, 0) + 1
        _sentinel_storage[resource_key]["last_access"] = time.time()


def _update_block_count(resource_key: str):
    """更新阻断计数"""
    redis = redis_client.get_client()
    if redis is not None:
        try:
            redis.hincrby(f"sentinel:{resource_key}", "block_count", 1)
        except:
            pass
    
    with _get_segment_lock(resource_key):
        if resource_key in _sentinel_storage:
            _sentinel_storage[resource_key]["block_count"] += 1


def _update_error_count(resource_key: str):
    """更新错误计数"""
    redis = redis_client.get_client()
    if redis is not None:
        try:
            redis.hincrby(f"sentinel:{resource_key}", "error_count", 1)
        except:
            pass
    
    with _get_segment_lock(resource_key):
        if resource_key in _sentinel_storage:
            _sentinel_storage[resource_key]["error_count"] += 1


# ==================== GlobalTransactional 分布式事务切面（Seata集成） ====================
def global_transactional_decorator(annotation: GlobalTransactional):
    """
    Seata全局事务注解实现（真实Seata集成）
    - 仅事务发起入口方法添加
    - 不支持嵌套事务
    - 使用Seata事务管理器进行事务管理
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 检查是否已经在事务中
            if seata_manager.is_in_transaction():
                logger.warning("[GlobalTransactional] Nested transaction detected, skipping")
                return func(*args, **kwargs)
            
            # 开启分布式事务
            tx_id = seata_manager.begin_transaction(
                timeout=annotation.timeout,
                name=annotation.name or func.__name__
            )
            
            logger.info(f"[GlobalTransactional] Begin transaction: {tx_id}")
            
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                
                # 检查执行时间是否超时
                duration = time.time() - start_time
                if duration * 1000 > annotation.timeout:
                    raise Exception(f"Transaction timeout after {duration:.2f}s")
                
                # 提交事务
                seata_manager.commit_transaction(tx_id)
                logger.info(f"[GlobalTransactional] Commit transaction: {tx_id}, duration={duration:.4f}s")
                
                return result
            
            except Exception as e:
                # 异常触发回滚
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
    """获取Sentinel统计数据（优先从Redis获取）"""
    redis = redis_client.get_client()
    
    if redis is not None and resource_key:
        try:
            data = redis.hgetall(f"sentinel:{resource_key}")
            if data:
                return {resource_key: {
                    "block_count": int(data.get("block_count", "0")),
                    "error_count": int(data.get("error_count", "0")),
                    "last_access": float(data.get("last_access", "0")),
                    "total_requests": int(data.get("total_requests", "0")),
                }}
        except:
            pass
    
    if resource_key:
        return {resource_key: _sentinel_storage.get(resource_key, {})}
    return dict(_sentinel_storage)


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