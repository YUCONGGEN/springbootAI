"""
Spring AOP 切面实现（企业级版本）
使用 Redis 持久化存储，支持真正的分布式锁、限流、熔断等功能
"""
from typing import Any, Callable, Dict, List
import asyncio
import time
import functools
import threading
import hashlib
import secrets
import re
import logging
import inspect
from spring.annotations.core import (
    RateLimit,
    CircuitBreaker,
    Idempotent,
    AuditLog,
    FeatureToggle,
    Lock,
    Metrics,
    Synchronized,
    Validate,
    Trace,
    Retryable,
)
from spring.utils.redis_client import redis_client

# Bean Validation 方法级切面（@BeanValidate）—— 纯标准库模块，无可选依赖
from spring.validation.aop import (
    BeanValidate as _BeanValidate,
    bean_validate_decorator as _bean_validate_decorator,
)

logger = logging.getLogger("Spring.AOP")

# ==================== 本地缓存（读写分离，提升性能） ====================
_rate_limit_local_cache: Dict[str, List[float]] = {}
_circuit_breaker_local_cache: Dict[str, dict] = {}
_idempotent_local_cache: Dict[str, Any] = {}
_idempotent_expire_times: Dict[str, float] = {}
_metrics_local_cache: Dict[str, dict] = {}
_trace_context = threading.local()

# 本地缓存刷新间隔（秒）
_LOCAL_CACHE_TTL = 5

# 分段锁，按 key 的哈希值分片，减少锁竞争
_NUM_SEGMENTS = 32
_segment_locks = [threading.Lock() for _ in range(_NUM_SEGMENTS)]


def _get_segment_lock(key: str) -> threading.Lock:
    """根据 key 获取对应的分段锁"""
    if isinstance(key, str):
        return _segment_locks[hash(key) % _NUM_SEGMENTS]
    return _segment_locks[0]


def _resolve_dynamic_key(key_template: str, func: Callable, args: tuple, kwargs: dict) -> str:
    """解析动态键模板，如 "user_id" 或 "stock_{product_id}" """
    if not key_template:
        return key_template
    
    # 获取函数签名，将位置参数转换为命名参数
    sig = inspect.signature(func)
    try:
        bound_args = sig.bind(*args, **kwargs)
        bound_args.apply_defaults()
        all_params = bound_args.arguments
    except (ValueError, TypeError):
        all_params = kwargs
    
    # 方式1：{param_name} 格式的占位符
    if '{' in key_template and '}' in key_template:
        try:
            return key_template.format(**all_params)
        except (KeyError, IndexError):
            pass
    
    # 方式2：直接是参数名
    if key_template in all_params:
        return str(all_params[key_template])
    
    # 都不匹配，返回原始模板
    return key_template


# ==================== RateLimit 限流切面（Redis持久化） ====================
def rate_limit_decorator(annotation: RateLimit):
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            base_key = annotation.key or f"{func.__module__}.{func.__name__}"
            # 解析动态key
            key = _resolve_dynamic_key(base_key, func, args, kwargs)
            if key == base_key and annotation.key:
                key = f"rate_limit:{annotation.key}:{key}"
            else:
                key = f"rate_limit:{key}"
            
            now = time.time()
            time_window = annotation.time_window
            max_requests = annotation.max_requests
            
            # 尝试使用 Redis 进行限流
            redis = redis_client.get_client()
            if redis is not None:
                try:
                    # 使用 Redis sorted set 实现滑动窗口限流
                    # 移除过期的请求记录
                    redis.zremrangebyscore(key, 0, now - time_window)
                    # 获取当前窗口内的请求数
                    current_count = redis.zcard(key)
                    
                    if current_count >= max_requests:
                        raise Exception(f"Rate limit exceeded: {max_requests} requests per {time_window}s")
                    
                    # 添加当前请求时间戳
                    redis.zadd(key, {str(now): now})
                    # 设置过期时间，避免内存泄漏
                    redis.expire(key, time_window)
                except Exception as e:
                    logger.warning(f"Redis rate limit failed, falling back to local: {e}")
                    # Redis 失败时回退到本地缓存
                    return _rate_limit_local(func, args, kwargs, key, now, time_window, max_requests)
            else:
                # Redis 不可用时使用本地缓存
                return _rate_limit_local(func, args, kwargs, key, now, time_window, max_requests)
            
            return func(*args, **kwargs)
        
        def _rate_limit_local(func, args, kwargs, key, now, time_window, max_requests):
            """本地限流实现（回退方案）"""
            with _get_segment_lock(key):
                if key not in _rate_limit_local_cache:
                    _rate_limit_local_cache[key] = []
                
                # 清理过期的请求记录
                _rate_limit_local_cache[key] = [
                    t for t in _rate_limit_local_cache[key] 
                    if now - t < time_window
                ]
                
                current_count = len(_rate_limit_local_cache[key])
                
                if current_count >= max_requests:
                    raise Exception(f"Rate limit exceeded: {max_requests} requests per {time_window}s")
                
                _rate_limit_local_cache[key].append(now)
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


# ==================== CircuitBreaker 熔断切面（Redis持久化） ====================
def circuit_breaker_decorator(annotation: CircuitBreaker):
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = f"circuit_breaker:{func.__module__}.{func.__name__}"
            
            # 尝试使用 Redis 获取熔断状态
            redis = redis_client.get_client()
            if redis is not None:
                try:
                    return _circuit_breaker_redis(func, args, kwargs, key, annotation, redis)
                except Exception as e:
                    logger.warning(f"Redis circuit breaker failed, falling back to local: {e}")
                    return _circuit_breaker_local(func, args, kwargs, key, annotation)
            else:
                return _circuit_breaker_local(func, args, kwargs, key, annotation)
        
        def _circuit_breaker_redis(func, args, kwargs, key, annotation, redis):
            """Redis 熔断实现"""
            # 获取熔断状态
            state_data = redis.hgetall(key)
            
            if not state_data:
                # 初始化状态
                state_data = {
                    "failures": "0",
                    "last_failure": "0",
                    "state": "CLOSED",
                }
                redis.hset(key, mapping=state_data)
            
            state = state_data.get("state", "CLOSED")
            failures = int(state_data.get("failures", "0"))
            last_failure = float(state_data.get("last_failure", "0"))
            now = time.time()
            
            # 判断是否需要熔断
            if state == "OPEN":
                if now - last_failure > annotation.recovery_timeout:
                    # 进入半开状态
                    redis.hset(key, "state", "HALF_OPEN", "failures", "0")
                else:
                    # 熔断中，直接返回
                    if annotation.fallback_method:
                        fallback = getattr(args[0], annotation.fallback_method, None) if args else None
                        if fallback and callable(fallback):
                            return fallback(*args[1:], **kwargs)
                    raise Exception(f"Circuit breaker is open for {key}")
            
            try:
                result = func(*args, **kwargs)
                
                # 成功，重置状态
                redis.hset(key, "failures", "0", "state", "CLOSED")
                
                return result
            except Exception as e:
                # 失败，增加失败计数
                new_failures = failures + 1
                redis.hset(key, "failures", str(new_failures), "last_failure", str(time.time()))
                
                if new_failures >= annotation.failure_threshold:
                    redis.hset(key, "state", "OPEN")
                    logger.warning(f"Circuit breaker opened for {key}")
                
                raise
        
        def _circuit_breaker_local(func, args, kwargs, key, annotation):
            """本地熔断实现（回退方案）"""
            with _get_segment_lock(key):
                if key not in _circuit_breaker_local_cache:
                    _circuit_breaker_local_cache[key] = {
                        "failures": 0,
                        "last_failure": 0,
                        "state": "CLOSED",
                    }
                
                state = _circuit_breaker_local_cache[key]["state"]
                failures = _circuit_breaker_local_cache[key]["failures"]
                last_failure = _circuit_breaker_local_cache[key]["last_failure"]
                now = time.time()
                
                if state == "OPEN":
                    if now - last_failure > annotation.recovery_timeout:
                        _circuit_breaker_local_cache[key]["state"] = "HALF_OPEN"
                        _circuit_breaker_local_cache[key]["failures"] = 0
                    else:
                        if annotation.fallback_method:
                            fallback = getattr(args[0], annotation.fallback_method, None) if args else None
                            if fallback and callable(fallback):
                                return fallback(*args[1:], **kwargs)
                        raise Exception(f"Circuit breaker is open for {key}")
            
            try:
                result = func(*args, **kwargs)
                
                with _get_segment_lock(key):
                    if key in _circuit_breaker_local_cache:
                        _circuit_breaker_local_cache[key]["failures"] = 0
                        _circuit_breaker_local_cache[key]["state"] = "CLOSED"
                
                return result
            except Exception as e:
                with _get_segment_lock(key):
                    if key in _circuit_breaker_local_cache:
                        _circuit_breaker_local_cache[key]["failures"] += 1
                        _circuit_breaker_local_cache[key]["last_failure"] = time.time()
                        
                        if _circuit_breaker_local_cache[key]["failures"] >= annotation.failure_threshold:
                            _circuit_breaker_local_cache[key]["state"] = "OPEN"
                            logger.warning(f"Circuit breaker opened for {key}")
                
                raise
        
        return wrapper
    return decorator


# ==================== Idempotent 幂等性切面（Redis持久化） ====================
def idempotent_decorator(annotation: Idempotent):
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 生成幂等键
            if annotation.key:
                param_value = _resolve_dynamic_key(annotation.key, func, args, kwargs)
                key = f"idempotent:{annotation.prefix}:{param_value}"
            else:
                params_hash = hashlib.sha256(f"{args}{kwargs}".encode()).hexdigest()
                key = f"idempotent:{annotation.prefix}:{params_hash}"
            
            now = time.time()
            
            # 尝试使用 Redis 实现幂等性
            redis = redis_client.get_client()
            if redis is not None:
                try:
                    return _idempotent_redis(func, args, kwargs, key, annotation, now, redis)
                except Exception as e:
                    logger.warning(f"Redis idempotent failed, falling back to local: {e}")
                    return _idempotent_local(func, args, kwargs, key, annotation, now)
            else:
                return _idempotent_local(func, args, kwargs, key, annotation, now)
        
        def _idempotent_redis(func, args, kwargs, key, annotation, now, redis):
            """Redis 幂等性实现"""
            # 使用 Lua 脚本保证原子性
            script = """
            local key = KEYS[1]
            local result_key = key .. ":result"
            local expire_key = key .. ":expire"
            
            -- 检查是否已有缓存结果
            local stored_result = redis.call("get", result_key)
            local expire_time = tonumber(redis.call("get", expire_key) or "0")
            
            if stored_result and expire_time > tonumber(ARGV[1]) then
                return stored_result
            end
            
            -- 标记正在处理（设置一个短暂的锁）
            local lock_set = redis.call("set", key .. ":processing", "1", "nx", "ex", 5)
            if not lock_set then
                -- 正在处理中，等待一小会儿
                return "PROCESSING"
            end
            
            -- 返回 nil 表示需要执行
            return nil
            """
            
            result = redis.eval(script, 1, key, now)
            
            if result == "PROCESSING":
                # 正在处理中，等待结果
                wait_end = time.time() + 5
                while time.time() < wait_end:
                    stored_result = redis.get(f"{key}:result")
                    expire_time = float(redis.get(f"{key}:expire") or "0")
                    if stored_result and expire_time > time.time():
                        try:
                            import json
                            return json.loads(stored_result)
                        except:
                            return stored_result
                    time.sleep(0.05)
                raise Exception("Idempotent operation timeout")
            
            if result is not None:
                # 有缓存结果，直接返回
                try:
                    import json
                    return json.loads(result)
                except:
                    return result
            
            # 需要执行
            try:
                result = func(*args, **kwargs)
                
                # 缓存结果
                try:
                    import json
                    result_str = json.dumps(result)
                except:
                    result_str = str(result)
                
                redis.set(f"{key}:result", result_str, ex=annotation.expire)
                redis.set(f"{key}:expire", time.time() + annotation.expire, ex=annotation.expire)
                
                return result
            except:
                # 清理处理标记
                redis.delete(f"{key}:processing")
                raise
        
        def _idempotent_local(func, args, kwargs, key, annotation, now):
            """本地幂等性实现（回退方案）"""
            with _get_segment_lock(key):
                # 清理过期条目
                expired_keys = [k for k, t in _idempotent_expire_times.items() if now > t]
                for k in expired_keys:
                    _idempotent_local_cache.pop(k, None)
                    _idempotent_expire_times.pop(k, None)
                
                if key in _idempotent_local_cache:
                    stored_value = _idempotent_local_cache[key]
                    expire_time = _idempotent_expire_times.get(key, 0)
                    
                    if stored_value is not None and expire_time > now:
                        return stored_value
                
                # 标记正在处理
                _idempotent_local_cache[key] = None
                _idempotent_expire_times[key] = now + annotation.expire
            
            try:
                result = func(*args, **kwargs)
                
                with _get_segment_lock(key):
                    _idempotent_local_cache[key] = result
                    _idempotent_expire_times[key] = time.time() + annotation.expire
                
                return result
            except:
                with _get_segment_lock(key):
                    _idempotent_local_cache.pop(key, None)
                    _idempotent_expire_times.pop(key, None)
                raise
        
        return wrapper
    return decorator


# ==================== AuditLog 审计日志切面 ====================
def audit_log_decorator(annotation: AuditLog):
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            result = None
            exception = None
            
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                exception = e
                raise
            finally:
                end_time = time.time()
                execution_time = end_time - start_time
                
                # 格式化详情（支持位置参数和命名参数）
                detail = annotation.detail
                if detail:
                    try:
                        sig = inspect.signature(func)
                        bound_args = sig.bind(*args, **kwargs)
                        bound_args.apply_defaults()
                        all_params = dict(bound_args.arguments)
                        all_params.pop('self', None)
                        detail = detail.format(**all_params)
                    except:
                        pass
                
                log_msg = (
                    f"[AuditLog] Action={annotation.action}, "
                    f"Target={annotation.target}, "
                    f"Detail={detail}, "
                    f"Method={func.__name__}, "
                    f"Status={'SUCCESS' if exception is None else 'FAILED'}, "
                    f"Duration={execution_time:.4f}s"
                )
                
                log_level = getattr(logger, annotation.level.lower(), logger.info)
                log_level(log_msg)
        return wrapper
    return decorator


# ==================== FeatureToggle 功能开关注解 ====================
def feature_toggle_decorator(annotation: FeatureToggle):
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import os
            
            # 优先从 Redis 获取开关状态
            redis = redis_client.get_client()
            toggle_value = None
            
            if redis is not None:
                try:
                    toggle_value = redis.get(f"feature:{annotation.name}")
                except:
                    pass
            
            # 如果 Redis 没有，从环境变量获取
            if toggle_value is None:
                toggle_value = os.getenv(f"FEATURE_{annotation.name.upper()}", str(annotation.default))
            
            enabled = toggle_value.lower() in ('true', '1', 'yes', 'enabled')
            
            if not enabled:
                raise Exception(f"Feature '{annotation.name}' is not enabled")
            
            return func(*args, **kwargs)
        return wrapper
    return decorator


# ==================== Lock 分布式锁切面（Redis实现） ====================
def lock_decorator(annotation: Lock):
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 生成锁键
            if annotation.key:
                resolved_key = _resolve_dynamic_key(annotation.key, func, args, kwargs)
                lock_key = f"{annotation.prefix}:{resolved_key}"
            else:
                lock_key = f"{annotation.prefix}:{func.__module__}.{func.__name__}"
            
            # 尝试使用 Redis 分布式锁
            redis = redis_client.get_client()
            if redis is not None:
                try:
                    return _lock_redis(func, args, kwargs, lock_key, annotation, redis)
                except Exception as e:
                    logger.warning(f"Redis lock failed, falling back to local: {e}")
                    return _lock_local(func, args, kwargs, lock_key, annotation)
            else:
                return _lock_local(func, args, kwargs, lock_key, annotation)
        
        def _lock_redis(func, args, kwargs, lock_key, annotation, redis):
            """Redis 分布式锁实现"""
            lock_id = redis_client.acquire_lock(lock_key, timeout=annotation.expire, wait_timeout=annotation.wait_timeout)
            
            if lock_id is None:
                raise Exception(f"Could not acquire lock for {lock_key}")
            
            try:
                return func(*args, **kwargs)
            finally:
                redis_client.release_lock(lock_key, lock_id)
        
        def _lock_local(func, args, kwargs, lock_key, annotation):
            """本地锁实现（回退方案）"""
            # 使用分段锁
            with _get_segment_lock(lock_key):
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


# ==================== Metrics 指标监控切面（Redis持久化） ====================
def metrics_decorator(annotation: Metrics):
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            name = annotation.name or f"{func.__module__}.{func.__name__}"
            key = f"metrics:{name}"
            
            start_time = time.time()
            result = None
            has_error = False
            
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                has_error = True
                raise
            finally:
                duration = time.time() - start_time
                
                # 更新本地缓存
                with _get_segment_lock(key):
                    if name not in _metrics_local_cache:
                        _metrics_local_cache[name] = {
                            "count": 0,
                            "total_time": 0,
                            "errors": 0,
                            "min_time": float('inf'),
                            "max_time": float('-inf'),
                        }
                    
                    _metrics_local_cache[name]["count"] += 1
                    _metrics_local_cache[name]["total_time"] += duration
                    if has_error:
                        _metrics_local_cache[name]["errors"] += 1
                    _metrics_local_cache[name]["min_time"] = min(_metrics_local_cache[name]["min_time"], duration)
                    _metrics_local_cache[name]["max_time"] = max(_metrics_local_cache[name]["max_time"], duration)
                
                # 每 100 次调用同步到 Redis
                with _get_segment_lock(key):
                    if _metrics_local_cache[name]["count"] % 100 == 0:
                        avg_time = _metrics_local_cache[name]["total_time"] / _metrics_local_cache[name]["count"]
                        logger.info(
                            f"[Metrics] {name} - "
                            f"Count={_metrics_local_cache[name]['count']}, "
                            f"AvgTime={avg_time:.4f}s, "
                            f"Min={_metrics_local_cache[name]['min_time']:.4f}s, "
                            f"Max={_metrics_local_cache[name]['max_time']:.4f}s, "
                            f"Errors={_metrics_local_cache[name]['errors']}"
                        )
                
                # 同步到 Redis
                redis = redis_client.get_client()
                if redis is not None:
                    try:
                        # 使用 Hash 存储指标
                        metrics_data = {
                            "count": str(_metrics_local_cache[name]["count"]),
                            "total_time": str(_metrics_local_cache[name]["total_time"]),
                            "errors": str(_metrics_local_cache[name]["errors"]),
                            "min_time": str(_metrics_local_cache[name]["min_time"]),
                            "max_time": str(_metrics_local_cache[name]["max_time"]),
                            "last_update": str(time.time()),
                        }
                        redis.hset(key, mapping=metrics_data)
                    except Exception as e:
                        logger.warning(f"Redis metrics sync failed: {e}")
        
        return wrapper
    return decorator


# ==================== Synchronized 方法同步切面 ====================
def synchronized_decorator(annotation: Synchronized):
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            lock_name = annotation.lock_name or f"{func.__module__}.{func.__name__}"
            
            # 使用分段锁
            with _get_segment_lock(lock_name):
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


# ==================== Validate 参数校验切面 ====================
def validate_decorator(annotation: Validate):
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
                
                if annotation.field is not None and param_name != annotation.field:
                    continue
                
                if annotation.min_length is not None and len(str(value)) < annotation.min_length:
                    errors.append(f"{param_name} length must be at least {annotation.min_length}")
                
                if annotation.max_length is not None and len(str(value)) > annotation.max_length:
                    errors.append(f"{param_name} length must be at most {annotation.max_length}")
                
                try:
                    num_value = float(value)
                    if annotation.min is not None and num_value < annotation.min:
                        errors.append(f"{param_name} must be at least {annotation.min}")
                    if annotation.max is not None and num_value > annotation.max:
                        errors.append(f"{param_name} must be at most {annotation.max}")
                except (ValueError, TypeError):
                    pass
                
                if annotation.regex is not None:
                    if not re.match(annotation.regex, str(value)):
                        errors.append(f"{param_name} does not match pattern")
            
            if errors:
                message = annotation.message or "; ".join(errors)
                raise Exception(message)
            
            return func(*args, **kwargs)
        return wrapper
    return decorator


# ==================== Trace 分布式追踪切面 ====================
def trace_decorator(annotation: Trace):
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 获取或生成 trace_id
            trace_id = getattr(_trace_context, 'trace_id', None)
            if not trace_id:
                trace_id = secrets.token_hex(16)
            
            _trace_context.trace_id = trace_id
            
            span_name = annotation.span_name or func.__name__
            
            logger.info(f"[Trace] Start span={span_name}, trace_id={trace_id}")
            
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                logger.info(f"[Trace] End span={span_name}, trace_id={trace_id}, duration={duration:.4f}s")
                return result
            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"[Trace] Error span={span_name}, trace_id={trace_id}, duration={duration:.4f}s, error={str(e)}")
                raise
        return wrapper
    return decorator


# ==================== Retryable 重试切面 ====================
def _retryable_decorator(annotation: Retryable):
    """
    @Retryable重试切面实现（与Spring Annotation兼容）
    
    支持：
    - 指定重试的异常类型
    - 指定不重试的异常类型
    - 最大重试次数
    - 退避策略（固定延迟/指数退避）
    - 随机因子
    - 恢复方法（recover）
    """
    def decorator(func: Callable) -> Callable:
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                last_exception = None

                for retry_count in range(1, annotation.max_retries + 1):
                    try:
                        return await func(*args, **kwargs)
                    except Exception as exc:
                        last_exception = exc
                        if isinstance(exc, annotation.exclude):
                            raise
                        if not isinstance(exc, annotation.value):
                            raise
                        if retry_count >= annotation.max_retries:
                            break

                        delay = _calculate_retry_backoff(
                            annotation.backoff, retry_count
                        )
                        logger.info(
                            f"[Retry] Retrying {func.__name__} "
                            f"(attempt {retry_count}/{annotation.max_retries - 1}), "
                            f"exception: {type(exc).__name__}, delay: {delay:.2f}ms"
                        )
                        await asyncio.sleep(delay / 1000.0)

                if last_exception and annotation.recover and args:
                    recover_func = getattr(args[0], annotation.recover, None)
                    if recover_func and callable(recover_func):
                        result = recover_func(*args[1:], **kwargs)
                        if inspect.isawaitable(result):
                            return await result
                        return result

                if last_exception:
                    raise last_exception

            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            max_retries = annotation.max_retries
            exceptions_to_retry = annotation.value
            exceptions_to_exclude = annotation.exclude
            backoff = annotation.backoff
            recover_method = annotation.recover
            
            last_exception = None
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    retry_count += 1
                    
                    # 检查是否是需要排除的异常
                    if isinstance(e, exceptions_to_exclude):
                        logger.info(f"[Retry] Exception {type(e).__name__} excluded from retry, re-raising")
                        raise
                    
                    # 检查是否是需要重试的异常
                    if not isinstance(e, exceptions_to_retry):
                        logger.info(f"[Retry] Exception {type(e).__name__} not in retry list, re-raising")
                        raise
                    
                    # 判断是否需要继续重试
                    if retry_count >= max_retries:
                        logger.warning(f"[Retry] Max retries ({max_retries}) exceeded for {func.__name__}: {str(e)}")
                        break
                    
                    # 计算退避时间
                    delay = _calculate_retry_backoff(backoff, retry_count)
                    
                    logger.info(
                        f"[Retry] Retrying {func.__name__} (attempt {retry_count}/{max_retries-1}), "
                        f"exception: {type(e).__name__}, delay: {delay:.2f}ms"
                    )
                    
                    # 等待
                    time.sleep(delay / 1000.0)
            
            # 重试失败，尝试调用恢复方法
            if last_exception and recover_method:
                logger.info(f"[Retry] Calling recover method '{recover_method}' for {func.__name__}")
                try:
                    # 尝试从实例中获取恢复方法
                    if args:
                        recover_func = getattr(args[0], recover_method, None)
                    else:
                        recover_func = None
                    
                    if recover_func and callable(recover_func):
                        # 移除self参数（如果存在）
                        if args:
                            return recover_func(*args[1:], **kwargs)
                        else:
                            return recover_func(**kwargs)
                except Exception as recover_e:
                    logger.error(f"[Retry] Recover method '{recover_method}' failed: {recover_e}")
            
            # 所有重试都失败，抛出最后一个异常
            if last_exception:
                raise last_exception
        
        return wrapper
    return decorator


def _calculate_retry_backoff(backoff, attempt: int) -> float:
    """
    计算退避时间
    
    参数：
        backoff: 退避配置
        attempt: 当前重试次数（从1开始）
    
    返回：
        退避时间（毫秒）
    """
    import random
    
    if backoff is None:
        return 1000.0
    
    # 获取退避参数
    delay = getattr(backoff, 'delay', 1000)
    max_delay = getattr(backoff, 'max_delay', 10000)
    multiplier = getattr(backoff, 'multiplier', 2.0)
    random_factor = getattr(backoff, 'random_factor', 0.1)
    
    # 指数退避：delay * (multiplier ^ (attempt - 1))
    calculated_delay = delay * (multiplier ** (attempt - 1))
    
    # 应用随机因子
    if random_factor > 0:
        random_delta = calculated_delay * random_factor
        calculated_delay = calculated_delay + random.uniform(-random_delta, random_delta)
    
    # 确保不超过最大延迟
    calculated_delay = min(calculated_delay, max_delay)
    
    # 确保不小于0
    calculated_delay = max(calculated_delay, 0)
    
    return calculated_delay


# ==================== 注解处理映射 ====================
ANNOTATION_DECORATORS = {
    RateLimit: rate_limit_decorator,
    CircuitBreaker: circuit_breaker_decorator,
    Idempotent: idempotent_decorator,
    AuditLog: audit_log_decorator,
    FeatureToggle: feature_toggle_decorator,
    Lock: lock_decorator,
    Metrics: metrics_decorator,
    Synchronized: synchronized_decorator,
    Validate: validate_decorator,
    Trace: trace_decorator,
    Retryable: _retryable_decorator,
    # Bean Validation 方法级切面：受管 Bean 方法调用前校验参数对象
    _BeanValidate: _bean_validate_decorator,
}


def apply_annotations(target: Any, method: Callable) -> Callable:
    """应用所有自定义注解"""
    annotations = getattr(method, '__spring_annotations__', [])
    
    wrapped = method
    remaining_annotations = []
    
    for annotation in annotations:
        decorator_func = ANNOTATION_DECORATORS.get(type(annotation))
        if decorator_func:
            wrapped = decorator_func(annotation)(wrapped)
        else:
            remaining_annotations.append(annotation)
    
    if remaining_annotations:
        setattr(wrapped, '__spring_annotations__', remaining_annotations)
    
    return wrapped


def get_metrics() -> Dict[str, dict]:
    """获取所有指标数据"""
    # 优先从 Redis 获取
    redis = redis_client.get_client()
    if redis is not None:
        try:
            # 扫描所有 metrics 键
            keys = redis.keys("metrics:*")
            result = {}
            for key in keys:
                data = redis.hgetall(key)
                if data:
                    name = key.replace("metrics:", "")
                    result[name] = {
                        "count": int(data.get("count", "0")),
                        "total_time": float(data.get("total_time", "0")),
                        "errors": int(data.get("errors", "0")),
                        "min_time": float(data.get("min_time", float('inf'))),
                        "max_time": float(data.get("max_time", float('-inf'))),
                    }
            return result
        except:
            pass
    
    # 回退到本地缓存
    return dict(_metrics_local_cache)


def reset_circuit_breaker(key: str) -> None:
    """重置熔断器状态"""
    # 重置 Redis 中的状态
    redis = redis_client.get_client()
    if redis is not None:
        try:
            redis_key = f"circuit_breaker:{key}" if not key.startswith("circuit_breaker:") else key
            redis.hset(redis_key, mapping={
                "failures": "0",
                "last_failure": "0",
                "state": "CLOSED",
            })
        except:
            pass
    
    # 重置本地缓存
    local_key = f"circuit_breaker:{key}" if not key.startswith("circuit_breaker:") else key
    if local_key in _circuit_breaker_local_cache:
        _circuit_breaker_local_cache[local_key] = {
            "failures": 0,
            "last_failure": 0,
            "state": "CLOSED",
        }


def clear_idempotent_cache(key: str = None) -> None:
    """清理幂等性缓存"""
    redis = redis_client.get_client()
    
    if key:
        # 清理指定键
        if redis is not None:
            try:
                redis_key = f"idempotent:{key}" if not key.startswith("idempotent:") else key
                redis.delete(redis_key)
                redis.delete(f"{redis_key}:result")
                redis.delete(f"{redis_key}:expire")
                redis.delete(f"{redis_key}:processing")
            except:
                pass
        
        local_key = f"idempotent:{key}" if not key.startswith("idempotent:") else key
        _idempotent_local_cache.pop(local_key, None)
        _idempotent_expire_times.pop(local_key, None)
    else:
        # 清理所有键
        if redis is not None:
            try:
                keys = redis.keys("idempotent:*")
                if keys:
                    redis.delete(*keys)
            except:
                pass
        
        _idempotent_local_cache.clear()
        _idempotent_expire_times.clear()


def enable_feature(name: str) -> None:
    """启用功能"""
    import os
    os.environ[f"FEATURE_{name.upper()}"] = "true"
    
    # 同步到 Redis
    redis = redis_client.get_client()
    if redis is not None:
        try:
            redis.set(f"feature:{name}", "true")
        except:
            pass


def disable_feature(name: str) -> None:
    """禁用功能"""
    import os
    os.environ[f"FEATURE_{name.upper()}"] = "false"
    
    # 同步到 Redis
    redis = redis_client.get_client()
    if redis is not None:
        try:
            redis.set(f"feature:{name}", "false")
        except:
            pass
