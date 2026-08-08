"""
重试切面实现
"""
import time
import random
import logging
import functools
from typing import Callable, Tuple, Type

logger = logging.getLogger("Spring.Retry")


def retryable_decorator(annotation):
    """
    @Retryable注解切面实现
    
    支持：
    - 指定重试的异常类型
    - 指定不重试的异常类型
    - 最大重试次数
    - 退避策略（固定延迟/指数退避）
    - 随机因子
    - 恢复方法（recover）
    """
    def decorator(func: Callable) -> Callable:
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
                    delay = _calculate_backoff(backoff, retry_count)
                    
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


def _calculate_backoff(backoff, attempt: int) -> float:
    """
    计算退避时间
    
    参数：
        backoff: 退避配置
        attempt: 当前重试次数（从1开始）
    
    返回：
        退避时间（毫秒）
    """
    # 指数退避：delay * (multiplier ^ (attempt - 1))
    delay = backoff.delay * (backoff.multiplier ** (attempt - 1))
    
    # 应用随机因子
    if backoff.random_factor > 0:
        random_delta = delay * backoff.random_factor
        delay = delay + random.uniform(-random_delta, random_delta)
    
    # 确保不超过最大延迟
    delay = min(delay, backoff.max_delay)
    
    # 确保不小于0
    delay = max(delay, 0)
    
    return delay


def retry(
    max_retries: int = 3,
    delay: int = 1000,
    max_delay: int = 10000,
    multiplier: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
) -> Callable:
    """
    便捷的重试装饰器
    
    参数：
        max_retries: 最大重试次数
        delay: 初始延迟（毫秒）
        max_delay: 最大延迟（毫秒）
        multiplier: 延迟倍增因子
        exceptions: 需要重试的异常类型
    
    使用示例：
        @retry(max_retries=5, delay=500)
        def fetch_data():
            pass
    """
    from spring.retry.retry_annotations import Retryable, Backoff
    
    annotation = Retryable(
        value=exceptions,
        max_retries=max_retries,
        backoff=Backoff(delay=delay, max_delay=max_delay, multiplier=multiplier)
    )
    
    return retryable_decorator(annotation)
