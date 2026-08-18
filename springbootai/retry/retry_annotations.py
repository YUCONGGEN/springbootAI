"""
重试注解定义
"""
from typing import Type, Tuple, Optional


class Backoff:
    """
    退避策略配置
    
    参数：
        delay: 初始延迟时间（毫秒），默认1000
        max_delay: 最大延迟时间（毫秒），默认10000
        multiplier: 延迟倍增因子，默认2.0（指数退避）
        random_factor: 随机因子（0.0-1.0），默认0.1
    """
    
    def __init__(
        self,
        delay: int = 1000,
        max_delay: int = 10000,
        multiplier: float = 2.0,
        random_factor: float = 0.1
    ):
        self.delay = delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.random_factor = random_factor


class Retryable:
    """
    重试注解
    
    参数：
        value: 要重试的异常类型（或异常类型元组）
        max_retries: 最大重试次数，默认3（包含首次调用）
        backoff: 退避策略配置
        exclude: 不重试的异常类型（或异常类型元组）
        recover: 恢复方法名（当重试失败时调用）
    """
    
    def __init__(
        self,
        value: Optional[Tuple[Type[Exception], ...]] = None,
        max_retries: int = 3,
        backoff: Optional[object] = None,
        exclude: Optional[Tuple[Type[Exception], ...]] = None,
        recover: str = "",
        max_attempts: Optional[int] = None,
    ):
        if max_attempts is not None:
            if max_retries != 3 and max_retries != max_attempts:
                raise ValueError("max_retries 与 max_attempts 不能设置为不同值")
            max_retries = max_attempts
        if max_retries <= 0:
            raise ValueError("max_retries 必须大于0")
        if isinstance(backoff, (int, float)):
            if backoff < 0:
                raise ValueError("backoff 延迟不能小于0")
            backoff = Backoff(
                delay=int(backoff),
                max_delay=int(backoff),
                multiplier=1.0,
                random_factor=0.0,
            )
        self.value = value or (Exception,)
        self.max_retries = max_retries
        self.backoff = backoff or Backoff()
        self.exclude = exclude or ()
        self.recover = recover
