"""SpringBootAI 缓存增强注解 —— 对齐 Spring Cache 抽象的完整操作族。

本模块在既有 ``@Cacheable``（``spring.annotations.core.Cacheable``）基础上补齐 Spring Cache
剩余四个核心注解，复用同一 ``SpringAnnotation`` 元数据范式：

- ``@CachePut``：方法**总是执行**，把返回值写入缓存（更新缓存）。
- ``@CacheEvict``：方法执行后（或前）失效缓存（按 key 或 all_entries）。
- ``@CacheConfig``：类级注解，为类内方法提供默认 cache name / key 生成器。
- ``@Caching``：组合多个缓存操作（cacheable/put/evict）。

与 Spring 的一致点：
- 操作语义（put/evict/condition/all_entries/before_invocation）对齐 Spring Cache。
- ``@CacheConfig`` 作为类级默认值，方法注解显式指定时覆盖。

与 Spring 的差异（已标注）：
- Spring 的 ``@CacheConfig``/``@Caching`` 依赖 ``CacheManager`` + ``KeyGenerator`` 抽象；
  本框架复用 ``BeanFactory`` 内置的进程内缓存（``_cache`` / ``_cache_metadata``，与
  ``@Cacheable`` 同一存储），由 ``bean_factory._apply_aop_proxy`` 统一包装切面。
- ``condition`` 仅支持参数名（或 ``!参数名`` 取反）与 callable，不支持 SpEL 表达式
  （与既有 ``@Cacheable.condition`` 保持一致，避免引入 SpEL 引擎）。
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple, Type, Union

from spring.annotations.core import SpringAnnotation


class CachePut(SpringAnnotation):
    """``@CachePut``：方法总是执行，把返回值写入缓存（对齐 Spring ``@CachePut``）。

    与 ``@Cacheable`` 的区别：``@Cacheable`` 命中缓存时跳过方法；``@CachePut`` **总是**
    执行方法并把结果写入缓存（用于强制刷新缓存）。

    Args:
        value:      缓存名（命名空间）。为空时回退到类级 ``@CacheConfig`` 默认。
        key:        缓存 key。支持 ``{param}`` 模板或纯参数名；为空时按全部参数聚合。
        condition:  条件表达式。仅当为真时才写入。支持参数名/``!参数名``/callable。
    """

    _annotation_type = "aop"

    def __init__(
        self,
        value: str = "",
        key: Optional[str] = None,
        condition: Optional[Union[str, Any]] = None,
    ):
        super().__init__(value=value, key=key, condition=condition)


class CacheEvict(SpringAnnotation):
    """``@CacheEvict``：失效缓存（对齐 Spring ``@CacheEvict``）。

    Args:
        value:             缓存名（命名空间）。为空时回退到类级 ``@CacheConfig`` 默认。
        key:               缓存 key。支持 ``{param}`` 模板或纯参数名；为空且
                           ``all_entries=False`` 时按全部参数聚合。
        condition:         条件表达式。仅当为真时才失效。
        all_entries:       是否清空整个缓存命名空间（所有 ``value:*`` 条目）。默认 False。
        before_invocation: 是否在方法**调用前**失效（默认 False=调用成功后失效）。
                           调用前失效无论方法成功与否都执行；调用后失效仅在方法成功时执行。
    """

    _annotation_type = "aop"

    def __init__(
        self,
        value: str = "",
        key: Optional[str] = None,
        condition: Optional[Union[str, Any]] = None,
        all_entries: bool = False,
        before_invocation: bool = False,
    ):
        super().__init__(
            value=value, key=key, condition=condition,
            all_entries=all_entries, before_invocation=before_invocation,
        )


class CacheConfig(SpringAnnotation):
    """``@CacheConfig``：类级缓存配置，为类内方法提供默认值（对齐 Spring ``@CacheConfig``）。

    Args:
        cache_names:    默认缓存名列表（方法注解未指定 ``value`` 时取第一个）。
        key_generator:  key 生成器名（保留字段，当前未实现自定义生成器，仅元数据）。
    """

    _annotation_type = "aop"

    def __init__(
        self,
        cache_names: Optional[List[str]] = None,
        key_generator: Optional[str] = None,
    ):
        super().__init__(
            cache_names=list(cache_names) if cache_names else [],
            key_generator=key_generator,
        )


class Caching(SpringAnnotation):
    """``@Caching``：组合多个缓存操作（对齐 Spring ``@Caching``）。

    Args:
        cacheable: 组合的 ``@Cacheable`` 操作列表。
        put:       组合的 ``@CachePut`` 操作列表。
        evict:     组合的 ``@CacheEvict`` 操作列表。
    """

    _annotation_type = "aop"

    def __init__(
        self,
        cacheable: Optional[List[Any]] = None,
        put: Optional[List[Any]] = None,
        evict: Optional[List[Any]] = None,
    ):
        super().__init__(
            cacheable=list(cacheable) if cacheable else [],
            put=list(put) if put else [],
            evict=list(evict) if evict else [],
        )


__all__ = ["CachePut", "CacheEvict", "CacheConfig", "Caching"]
