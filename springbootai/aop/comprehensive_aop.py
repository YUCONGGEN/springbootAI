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
import json
import contextvars
import weakref
from springbootai.annotations.core import (
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
from springbootai.utils.redis_client import redis_client

# Bean Validation 方法级切面（@BeanValidate）—— 纯标准库模块，无可选依赖
from springbootai.validation.aop import (
    BeanValidate as _BeanValidate,
    bean_validate_decorator as _bean_validate_decorator,
)

logger = logging.getLogger("Spring.AOP")


class DistributedGuardError(RuntimeError):
    """分布式保护组件不可用或状态不一致。"""


class RateLimitExceeded(DistributedGuardError):
    """请求超过限流阈值。"""


class CircuitBreakerOpenError(DistributedGuardError):
    """熔断器处于打开状态。"""


class IdempotencyInProgressError(DistributedGuardError):
    """相同幂等键对应的操作仍在执行。"""


class DistributedLockUnavailable(DistributedGuardError):
    """无法获取分布式锁。"""

# ==================== 本地缓存（读写分离，提升性能） ====================
_rate_limit_local_cache: Dict[str, List[float]] = {}
_circuit_breaker_local_cache: Dict[str, dict] = {}
_idempotent_local_cache: Dict[str, Any] = {}
_idempotent_expire_times: Dict[str, float] = {}
_IDEMPOTENT_PROCESSING = object()
_metrics_local_cache: Dict[str, dict] = {}
_trace_id_context: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "springbootai_trace_id", default=None
)

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


def _get_distributed_guard_client():
    """Get Redis without silently crossing a configured distributed boundary."""
    client = redis_client.get_client()
    if client is None and getattr(redis_client, "distributed_required", False):
        raise DistributedGuardError("Configured Redis guard is unavailable")
    return client


def _canonical_call_key(func: Callable, args: tuple, kwargs: dict) -> str:
    """Create a stable idempotency key without object repr or process addresses."""
    try:
        bound = inspect.signature(func).bind(*args, **kwargs)
        bound.apply_defaults()
        arguments = dict(bound.arguments)
        arguments.pop("self", None)
        arguments.pop("cls", None)
        payload = json.dumps(
            arguments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DistributedGuardError(
            f"@Idempotent on {func.__qualname__} requires an explicit key "
            "for non-JSON arguments"
        ) from exc
    identity = f"{func.__module__}.{func.__qualname__}\n{payload}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


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
        def build_key(args, kwargs):
            base_key = annotation.key or f"{func.__module__}.{func.__name__}"
            resolved = _resolve_dynamic_key(base_key, func, args, kwargs)
            if resolved == base_key and annotation.key:
                return f"rate_limit:{annotation.key}:{resolved}"
            return f"rate_limit:{resolved}"

        def reserve(args, kwargs):
            key = build_key(args, kwargs)
            now = time.time()
            redis = _get_distributed_guard_client()
            if redis is None:
                with _get_segment_lock(key):
                    entries = [
                        value for value in _rate_limit_local_cache.get(key, [])
                        if now - value < annotation.time_window
                    ]
                    if len(entries) >= annotation.max_requests:
                        raise RateLimitExceeded(
                            f"Rate limit exceeded: {annotation.max_requests} "
                            f"requests per {annotation.time_window}s"
                        )
                    entries.append(now)
                    _rate_limit_local_cache[key] = entries
                return

            # 清理、计数和占位必须是一个原子操作，否则并发请求会共同越过阈值。
            script = """
            redis.call('zremrangebyscore', KEYS[1], 0, ARGV[1] - ARGV[2])
            if redis.call('zcard', KEYS[1]) >= tonumber(ARGV[3]) then
                return 0
            end
            redis.call('zadd', KEYS[1], ARGV[1], ARGV[4])
            redis.call('expire', KEYS[1], math.max(1, math.ceil(ARGV[2])))
            return 1
            """
            try:
                allowed = redis.eval(
                    script,
                    1,
                    key,
                    now,
                    annotation.time_window,
                    annotation.max_requests,
                    f"{now}:{secrets.token_hex(8)}",
                )
            except Exception as exc:
                raise DistributedGuardError(
                    f"Redis rate limiter unavailable for {key}"
                ) from exc
            if int(allowed or 0) != 1:
                raise RateLimitExceeded(
                    f"Rate limit exceeded: {annotation.max_requests} "
                    f"requests per {annotation.time_window}s"
                )

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                await asyncio.to_thread(reserve, args, kwargs)
                return await func(*args, **kwargs)
            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            reserve(args, kwargs)
            return func(*args, **kwargs)
        return wrapper
    return decorator


# ==================== CircuitBreaker 熔断切面（Redis持久化） ====================
def circuit_breaker_decorator(annotation: CircuitBreaker):
    def decorator(func: Callable) -> Callable:
        key = f"circuit_breaker:{func.__module__}.{func.__name__}"

        def read_value(mapping, name, default):
            return mapping.get(name, mapping.get(name.encode(), default))

        def before_call(redis):
            if redis is None:
                with _get_segment_lock(key):
                    state_data = _circuit_breaker_local_cache.setdefault(
                        key,
                        {"failures": 0, "last_failure": 0, "state": "CLOSED"},
                    )
                    state = state_data["state"]
                    if state == "OPEN":
                        if time.time() - state_data["last_failure"] > annotation.recovery_timeout:
                            state_data["state"] = "HALF_OPEN"
                            state_data["failures"] = 0
                        else:
                            return False, state_data["failures"]
                    return True, state_data["failures"]

            try:
                state_data = redis.hgetall(key)
                if not state_data:
                    state_data = {"failures": "0", "last_failure": "0", "state": "CLOSED"}
                    redis.hset(key, mapping=state_data)
                state = read_value(state_data, "state", "CLOSED")
                if isinstance(state, bytes):
                    state = state.decode()
                failures = int(read_value(state_data, "failures", "0"))
                last_failure = float(read_value(state_data, "last_failure", "0"))
                if state == "OPEN":
                    if time.time() - last_failure > annotation.recovery_timeout:
                        redis.hset(key, mapping={"state": "HALF_OPEN", "failures": "0"})
                        failures = 0
                    else:
                        return False, failures
                return True, failures
            except Exception as exc:
                raise DistributedGuardError(
                    f"Redis circuit breaker unavailable for {key}"
                ) from exc

        def record_success(redis):
            try:
                if redis is None:
                    with _get_segment_lock(key):
                        state_data = _circuit_breaker_local_cache.get(key)
                        if state_data:
                            state_data.update(failures=0, state="CLOSED")
                else:
                    redis.hset(key, mapping={"failures": "0", "state": "CLOSED"})
            except Exception:
                # 业务已经成功；此时抛出基础设施异常会诱导调用方重试并重复业务。
                logger.exception("Failed to reset circuit breaker state for %s", key)

        def record_failure(redis, previous_failures):
            try:
                new_failures = previous_failures + 1
                if redis is None:
                    with _get_segment_lock(key):
                        state_data = _circuit_breaker_local_cache.setdefault(
                            key,
                            {"failures": 0, "last_failure": 0, "state": "CLOSED"},
                        )
                        state_data["failures"] += 1
                        state_data["last_failure"] = time.time()
                        if state_data["failures"] >= annotation.failure_threshold:
                            state_data["state"] = "OPEN"
                else:
                    values = {
                        "failures": str(new_failures),
                        "last_failure": str(time.time()),
                    }
                    if new_failures >= annotation.failure_threshold:
                        values["state"] = "OPEN"
                    redis.hset(key, mapping=values)
                if new_failures >= annotation.failure_threshold:
                    logger.warning("Circuit breaker opened for %s", key)
            except Exception:
                # 保留并重新抛出原始业务异常，绝不能转去第二次调用业务。
                logger.exception("Failed to record circuit breaker failure for %s", key)

        def fallback(args, kwargs):
            method = getattr(args[0], annotation.fallback_method, None) if args else None
            if method and callable(method):
                return method(*args[1:], **kwargs)
            raise CircuitBreakerOpenError(f"Circuit breaker is open for {key}")

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                redis = _get_distributed_guard_client()
                allowed, failures = await asyncio.to_thread(before_call, redis)
                if not allowed:
                    value = fallback(args, kwargs) if annotation.fallback_method else None
                    if annotation.fallback_method:
                        return await value if inspect.isawaitable(value) else value
                    raise CircuitBreakerOpenError(f"Circuit breaker is open for {key}")
                try:
                    result = await func(*args, **kwargs)
                except Exception:
                    await asyncio.to_thread(record_failure, redis, failures)
                    raise
                await asyncio.to_thread(record_success, redis)
                return result
            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            redis = _get_distributed_guard_client()
            allowed, failures = before_call(redis)
            if not allowed:
                return fallback(args, kwargs) if annotation.fallback_method else fallback(args, kwargs)
            try:
                result = func(*args, **kwargs)
            except Exception:
                record_failure(redis, failures)
                raise
            record_success(redis)
            return result
        return wrapper
    return decorator


# ==================== Idempotent 幂等性切面（Redis持久化） ====================
def idempotent_decorator(annotation: Idempotent):
    def decorator(func: Callable) -> Callable:
        def build_key(args, kwargs):
            if annotation.key:
                value = _resolve_dynamic_key(annotation.key, func, args, kwargs)
                return f"idempotent:{annotation.prefix}:{value}"
            params_hash = _canonical_call_key(func, args, kwargs)
            return f"idempotent:{annotation.prefix}:{params_hash}"

        def deserialize(value):
            try:
                decoded = json.loads(value)
                if isinstance(decoded, dict) and decoded.get("__springbootai_idempotent__") == 1:
                    return decoded.get("value")
                return decoded
            except (json.JSONDecodeError, TypeError):
                return value

        def claim(key):
            now = time.time()
            redis = _get_distributed_guard_client()
            if redis is None:
                with _get_segment_lock(key):
                    if _idempotent_expire_times.get(key, 0) <= now:
                        _idempotent_local_cache.pop(key, None)
                        _idempotent_expire_times.pop(key, None)
                    if key in _idempotent_local_cache:
                        value = _idempotent_local_cache[key]
                        if value is _IDEMPOTENT_PROCESSING:
                            raise IdempotencyInProgressError(
                                f"Idempotent operation already in progress for {key}"
                            )
                        return redis, None, True, value
                    _idempotent_local_cache[key] = _IDEMPOTENT_PROCESSING
                    _idempotent_expire_times[key] = now + annotation.expire
                return redis, None, False, None

            owner = secrets.token_hex(16)
            result_key = f"{key}:result"
            processing_key = f"{key}:processing"
            script = """
            local result = redis.call('get', KEYS[1])
            if result then
                return {'CACHED', result}
            end
            local acquired = redis.call('set', KEYS[2], ARGV[1], 'nx', 'ex', ARGV[2])
            if acquired then
                return {'ACQUIRED'}
            end
            return {'PROCESSING'}
            """
            try:
                response = redis.eval(
                    script,
                    2,
                    result_key,
                    processing_key,
                    owner,
                    max(1, int(annotation.expire)),
                )
                if not isinstance(response, (list, tuple)) or not response:
                    raise DistributedGuardError("Invalid Redis idempotency response")
                status = response[0].decode() if isinstance(response[0], bytes) else response[0]
                if status == "CACHED" and len(response) == 2:
                    return redis, owner, True, deserialize(response[1])
                if status == "PROCESSING":
                    raise IdempotencyInProgressError(
                        f"Idempotent operation already in progress for {key}"
                    )
                if status == "ACQUIRED":
                    return redis, owner, False, None
                raise DistributedGuardError("Unknown Redis idempotency response")
            except IdempotencyInProgressError:
                raise
            except DistributedGuardError:
                raise
            except Exception as exc:
                raise DistributedGuardError(
                    f"Redis idempotency guard unavailable for {key}"
                ) from exc

        def release_claim(redis, key, owner):
            if redis is None:
                with _get_segment_lock(key):
                    _idempotent_local_cache.pop(key, None)
                    _idempotent_expire_times.pop(key, None)
                return
            script = """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('del', KEYS[1])
            end
            return 0
            """
            try:
                redis.eval(script, 1, f"{key}:processing", owner)
            except Exception:
                logger.exception("Failed to release idempotency claim for %s", key)

        def store_result(redis, key, owner, result):
            if redis is None:
                with _get_segment_lock(key):
                    _idempotent_local_cache[key] = result
                    _idempotent_expire_times[key] = time.time() + annotation.expire
                return
            try:
                payload = json.dumps(
                    {"__springbootai_idempotent__": 1, "value": result},
                    ensure_ascii=False,
                )
            except (TypeError, ValueError):
                # 保留 processing 标记到期，避免成功业务在无法安全缓存时立即被重放。
                logger.exception("Idempotent result for %s is not JSON serializable", key)
                return
            script = """
            if redis.call('get', KEYS[1]) ~= ARGV[1] then
                return 0
            end
            redis.call('set', KEYS[2], ARGV[2], 'ex', ARGV[3])
            redis.call('del', KEYS[1])
            return 1
            """
            try:
                stored = redis.eval(
                    script,
                    2,
                    f"{key}:processing",
                    f"{key}:result",
                    owner,
                    payload,
                    max(1, int(annotation.expire)),
                )
                if int(stored or 0) != 1:
                    logger.error("Idempotency claim expired before result was stored for %s", key)
            except Exception:
                # 业务已经成功；不能抛出并诱导上游重试。processing 标记仍会阻止即时重放。
                logger.exception("Failed to store idempotent result for %s", key)

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                key = build_key(args, kwargs)
                redis, owner, cached, value = await asyncio.to_thread(claim, key)
                if cached:
                    return value
                try:
                    result = await func(*args, **kwargs)
                except Exception:
                    await asyncio.to_thread(release_claim, redis, key, owner)
                    raise
                await asyncio.to_thread(store_result, redis, key, owner, result)
                return result
            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = build_key(args, kwargs)
            redis, owner, cached, value = claim(key)
            if cached:
                return value
            try:
                result = func(*args, **kwargs)
            except Exception:
                release_claim(redis, key, owner)
                raise
            store_result(redis, key, owner, result)
            return result
        return wrapper
    return decorator


# ==================== AuditLog 审计日志切面 ====================
_SENSITIVE_AUDIT_NAME = re.compile(
    r"password|passwd|secret|token|authorization|cookie|api[_-]?key|credential",
    re.IGNORECASE,
)


def _safe_log_text(value: Any, maximum: int = 256) -> str:
    text = str(value).replace("\r", "\\r").replace("\n", "\\n")
    return text if len(text) <= maximum else text[:maximum] + "…"


def _audit_detail(annotation: AuditLog, func: Callable, args: tuple, kwargs: dict) -> str:
    detail = _safe_log_text(annotation.detail or "")
    if not detail:
        return detail
    try:
        bound = inspect.signature(func).bind(*args, **kwargs)
        bound.apply_defaults()
        safe_params = {}
        for name, value in bound.arguments.items():
            if name in {"self", "cls"}:
                continue
            if _SENSITIVE_AUDIT_NAME.search(name):
                safe_params[name] = "***"
            elif isinstance(value, (str, int, float, bool, type(None))):
                safe_params[name] = _safe_log_text(value, 128)
            else:
                safe_params[name] = f"<{type(value).__name__}>"
        return _safe_log_text(detail.format(**safe_params))
    except (KeyError, IndexError, ValueError, TypeError):
        return detail


def audit_log_decorator(annotation: AuditLog):
    def decorator(func: Callable) -> Callable:
        def record(args, kwargs, started, failed):
            log_level = {
                "debug": logger.debug,
                "info": logger.info,
                "warning": logger.warning,
                "error": logger.error,
                "critical": logger.critical,
            }.get(str(annotation.level).lower(), logger.info)
            log_level(
                "[AuditLog] Action=%s, Target=%s, Detail=%s, Method=%s, "
                "Status=%s, Duration=%.4fs",
                _safe_log_text(annotation.action),
                _safe_log_text(annotation.target),
                _audit_detail(annotation, func, args, kwargs),
                func.__name__,
                "FAILED" if failed else "SUCCESS",
                time.monotonic() - started,
            )

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                started = time.monotonic()
                failed = False
                try:
                    return await func(*args, **kwargs)
                except BaseException:
                    failed = True
                    raise
                finally:
                    record(args, kwargs, started, failed)
            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            started = time.monotonic()
            failed = False
            try:
                return func(*args, **kwargs)
            except BaseException:
                failed = True
                raise
            finally:
                record(args, kwargs, started, failed)
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
        def build_key(args, kwargs):
            if annotation.key:
                resolved_key = _resolve_dynamic_key(annotation.key, func, args, kwargs)
                return f"{annotation.prefix}:{resolved_key}"
            return f"{annotation.prefix}:{func.__module__}.{func.__name__}"

        def acquire(lock_key):
            redis = _get_distributed_guard_client()
            if redis is None:
                lock = _get_segment_lock(lock_key)
                lock.acquire()
                return None, lock
            try:
                lock_id = redis_client.acquire_lock(
                    lock_key,
                    timeout=annotation.expire,
                    wait_timeout=annotation.wait_timeout,
                )
            except Exception as exc:
                raise DistributedGuardError(
                    f"Redis distributed lock unavailable for {lock_key}"
                ) from exc
            if lock_id is None:
                raise DistributedLockUnavailable(f"Could not acquire lock for {lock_key}")
            return lock_id, None

        def release(lock_key, lock_id, local_lock):
            if local_lock is not None:
                local_lock.release()
                return
            if not redis_client.release_lock(lock_key, lock_id):
                logger.error("Failed to release distributed lock for %s", lock_key)

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                lock_key = build_key(args, kwargs)
                lock_id, local_lock = await asyncio.to_thread(acquire, lock_key)
                try:
                    return await func(*args, **kwargs)
                finally:
                    await asyncio.to_thread(release, lock_key, lock_id, local_lock)
            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            lock_key = build_key(args, kwargs)
            lock_id, local_lock = acquire(lock_key)
            try:
                return func(*args, **kwargs)
            finally:
                release(lock_key, lock_id, local_lock)
        return wrapper
    return decorator


# ==================== Metrics 指标监控切面（Redis持久化） ====================
def metrics_decorator(annotation: Metrics):
    def decorator(func: Callable) -> Callable:
        name = annotation.name or f"{func.__module__}.{func.__name__}"
        key = f"metrics:{name}"

        def record(duration: float, has_error: bool) -> None:
            with _get_segment_lock(key):
                metrics = _metrics_local_cache.setdefault(name, {
                    "count": 0,
                    "total_time": 0,
                    "errors": 0,
                    "min_time": float('inf'),
                    "max_time": float('-inf'),
                })
                metrics["count"] += 1
                metrics["total_time"] += duration
                if has_error:
                    metrics["errors"] += 1
                metrics["min_time"] = min(metrics["min_time"], duration)
                metrics["max_time"] = max(metrics["max_time"], duration)
                snapshot = dict(metrics)

            if snapshot["count"] % 100 == 0:
                logger.info(
                    "[Metrics] %s - Count=%d, AvgTime=%.4fs, Min=%.4fs, "
                    "Max=%.4fs, Errors=%d",
                    name,
                    snapshot["count"],
                    snapshot["total_time"] / snapshot["count"],
                    snapshot["min_time"],
                    snapshot["max_time"],
                    snapshot["errors"],
                )
            redis = redis_client.get_client()
            if redis is not None:
                try:
                    redis.hset(key, mapping={
                        "count": str(snapshot["count"]),
                        "total_time": str(snapshot["total_time"]),
                        "errors": str(snapshot["errors"]),
                        "min_time": str(snapshot["min_time"]),
                        "max_time": str(snapshot["max_time"]),
                        "last_update": str(time.time()),
                    })
                except Exception as exc:
                    logger.warning(
                        "Redis metrics sync failed (%s)", type(exc).__name__
                    )

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                started = time.monotonic()
                has_error = False
                try:
                    return await func(*args, **kwargs)
                except BaseException:
                    has_error = True
                    raise
                finally:
                    await asyncio.to_thread(
                        record, time.monotonic() - started, has_error
                    )
            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            started = time.monotonic()
            has_error = False
            try:
                return func(*args, **kwargs)
            except BaseException:
                has_error = True
                raise
            finally:
                record(time.monotonic() - started, has_error)
        return wrapper
    return decorator


# ==================== Synchronized 方法同步切面 ====================
def synchronized_decorator(annotation: Synchronized):
    def decorator(func: Callable) -> Callable:
        lock_name = annotation.lock_name or f"{func.__module__}.{func.__name__}"
        if inspect.iscoroutinefunction(func):
            # asyncio locks become bound to the event loop that first contends
            # on them.  Keep one weakly-held lock per loop so test runners,
            # reloaders and multi-loop embeddings can reuse the decorated bean.
            async_lock_refs = weakref.WeakKeyDictionary()
            async_lock_guard = threading.Lock()

            def get_async_lock():
                loop = asyncio.get_running_loop()
                with async_lock_guard:
                    lock_ref = async_lock_refs.get(loop)
                    lock = lock_ref() if lock_ref is not None else None
                    if lock is None:
                        lock = asyncio.Lock()
                        async_lock_refs[loop] = weakref.ref(lock)
                    return lock

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                async with get_async_lock():
                    return await func(*args, **kwargs)
            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
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
        span_name = _safe_log_text(annotation.span_name or func.__name__, 128)

        def start_span():
            trace_id = _trace_id_context.get()
            token = None
            if not trace_id:
                trace_id = secrets.token_hex(16)
                token = _trace_id_context.set(trace_id)
            logger.info("[Trace] Start span=%s, trace_id=%s", span_name, trace_id)
            return trace_id, token, time.monotonic()

        def finish_span(trace_id, token, started, error=None):
            duration = time.monotonic() - started
            if error is None:
                logger.info(
                    "[Trace] End span=%s, trace_id=%s, duration=%.4fs",
                    span_name, trace_id, duration,
                )
            else:
                logger.error(
                    "[Trace] Error span=%s, trace_id=%s, duration=%.4fs, "
                    "error_type=%s",
                    span_name, trace_id, duration, type(error).__name__,
                )
            if token is not None:
                _trace_id_context.reset(token)

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                trace_id, token, started = start_span()
                try:
                    result = await func(*args, **kwargs)
                except BaseException as exc:
                    finish_span(trace_id, token, started, exc)
                    raise
                finish_span(trace_id, token, started)
                return result
            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            trace_id, token, started = start_span()
            try:
                result = func(*args, **kwargs)
            except BaseException as exc:
                finish_span(trace_id, token, started, exc)
                raise
            finish_span(trace_id, token, started)
            return result
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

                if last_exception and args:
                    from springbootai.retry.recovery import (
                        invoke_recovery,
                        resolve_recovery_method,
                    )
                    recovery = resolve_recovery_method(
                        args[0], annotation, last_exception, args[1:], kwargs
                    )
                    if recovery is not None:
                        result = invoke_recovery(
                            recovery, last_exception, args[1:], kwargs
                        )
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
                        logger.warning(
                            "[Retry] Max retries (%d) exceeded for %s "
                            "error_type=%s",
                            max_retries, func.__name__, type(e).__name__,
                        )
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
            if last_exception and args:
                from springbootai.retry.recovery import (
                    invoke_recovery,
                    resolve_recovery_method,
                )
                recovery = resolve_recovery_method(
                    args[0], annotation, last_exception, args[1:], kwargs
                )
                if recovery is not None:
                    return invoke_recovery(
                        recovery, last_exception, args[1:], kwargs
                    )
            
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
            result = {}
            for index, key in enumerate(
                redis.scan_iter(match="metrics:*", count=200), start=1
            ):
                if index > 10_000:
                    logger.warning("Metrics key scan truncated at 10000 entries")
                    break
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
    # Values are copied as well so callers cannot mutate live counters.
    return {name: dict(values) for name, values in _metrics_local_cache.items()}


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
