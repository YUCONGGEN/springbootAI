"""
PyMyBatis熔断降级模块

实现数据库连接熔断机制，防止数据库故障导致的级联失败
"""

from .circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerState,
    CircuitBreakerError,
    DatabaseCircuitBreaker,
    with_circuit_breaker
)

__all__ = [
    'CircuitBreaker',
    'CircuitBreakerState',
    'CircuitBreakerError',
    'DatabaseCircuitBreaker',
    'with_circuit_breaker'
]