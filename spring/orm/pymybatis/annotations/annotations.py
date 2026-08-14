"""
PyMyBatis注解模块

定义SQL注解：@Select、@Insert、@Update、@Delete、@ResultMap、@Result
"""

from typing import Optional, List, Any, Callable


def _attach(target: Callable, name: str, value: Any) -> Callable:
    setattr(target, name, value)
    return target


class SelectAnnotation:
    """
    SELECT查询注解数据对象
    """

    def __init__(self, value: str, result_map: Optional[str] = None,
                 result_type: Optional[str] = None, fetch_size: Optional[int] = None,
                 timeout: Optional[int] = None, cache: bool = True):
        self.value = value
        self.result_map = result_map
        self.result_type = result_type
        self.fetch_size = fetch_size
        self.timeout = timeout
        self.cache = cache


def Select(value: str, result_map: Optional[str] = None,
           result_type: Optional[str] = None, fetch_size: Optional[int] = None,
           timeout: Optional[int] = None, cache: bool = True) -> Callable:
    """
    SELECT查询注解装饰器

    用于标注Mapper接口方法，表示该方法执行SELECT查询

    Args:
        value: SQL语句
        result_map: 结果映射ID
        result_type: 结果类型
        fetch_size: 抓取大小
        timeout: 超时时间（秒）
        cache: 是否启用缓存

    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        annotation = SelectAnnotation(value, result_map, result_type,
                                      fetch_size, timeout, cache)
        setattr(func, 'select', annotation)
        return func
    return decorator


class SelectPageAnnotation:
    """
    分页查询注解数据对象

    用于标注Mapper方法，自动执行分页查询（COUNT + LIMIT/OFFSET）。
    方法参数中名为 ``page_num`` 和 ``page_size`` 的参数会自动提取为分页参数，
    其余参数作为SQL绑定参数。
    """

    def __init__(self, value: str, count_sql: Optional[str] = None,
                 result_map: Optional[str] = None,
                 result_type: Optional[str] = None,
                 fetch_size: Optional[int] = None,
                 timeout: Optional[int] = None):
        self.value = value
        self.count_sql = count_sql
        self.result_map = result_map
        self.result_type = result_type
        self.fetch_size = fetch_size
        self.timeout = timeout


def SelectPage(value: str, count_sql: Optional[str] = None,
               result_map: Optional[str] = None,
               result_type: Optional[str] = None,
               fetch_size: Optional[int] = None,
               timeout: Optional[int] = None) -> Callable:
    """
    分页查询注解装饰器

    用于标注Mapper接口方法，自动执行分页查询。
    框架会从方法参数中提取 ``page_num`` 和 ``page_size``（按参数名匹配），
    其余参数作为SQL绑定参数。

    Args:
        value: 查询SQL语句（不含LIMIT/OFFSET，框架自动追加）
        count_sql: 自定义COUNT语句，为空时框架自动包裹生成
        result_map: 结果映射ID
        result_type: 结果类型
        fetch_size: 抓取大小
        timeout: 超时时间（秒）

    Returns:
        装饰器函数

    用法::

        @SelectPage("SELECT id, name FROM users WHERE age > #{age}")
        def find_page(self, age: int, page_num: int, page_size: int):
            pass

        # 返回: {"total": 100, "page_num": 1, "page_size": 10, "data": [...]}
    """
    def decorator(func: Callable) -> Callable:
        annotation = SelectPageAnnotation(value, count_sql, result_map,
                                          result_type, fetch_size, timeout)
        setattr(func, 'select_page', annotation)
        return func
    return decorator


class InsertAnnotation:
    """
    INSERT插入注解数据对象
    """

    def __init__(self, value: str, parameter_type: Optional[str] = None,
                 key_property: Optional[str] = None, key_column: Optional[str] = None,
                 use_generated_keys: bool = False):
        self.value = value
        self.parameter_type = parameter_type
        self.key_property = key_property
        self.key_column = key_column
        self.use_generated_keys = use_generated_keys


def Insert(value: str, parameter_type: Optional[str] = None,
           key_property: Optional[str] = None, key_column: Optional[str] = None,
           use_generated_keys: bool = False) -> Callable:
    """
    INSERT插入注解装饰器

    用于标注Mapper接口方法，表示该方法执行INSERT操作

    Args:
        value: SQL语句
        parameter_type: 参数类型
        key_property: 主键属性名
        key_column: 主键列名
        use_generated_keys: 是否使用自增主键

    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        annotation = InsertAnnotation(value, parameter_type, key_property,
                                      key_column, use_generated_keys)
        setattr(func, 'insert', annotation)
        return func
    return decorator


class UpdateAnnotation:
    """
    UPDATE更新注解数据对象
    """

    def __init__(self, value: str, parameter_type: Optional[str] = None,
                 timeout: Optional[int] = None):
        self.value = value
        self.parameter_type = parameter_type
        self.timeout = timeout


def Update(value: str, parameter_type: Optional[str] = None,
           timeout: Optional[int] = None) -> Callable:
    """
    UPDATE更新注解装饰器

    用于标注Mapper接口方法，表示该方法执行UPDATE操作

    Args:
        value: SQL语句
        parameter_type: 参数类型
        timeout: 超时时间（秒）

    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        annotation = UpdateAnnotation(value, parameter_type, timeout)
        setattr(func, 'update', annotation)
        return func
    return decorator


class DeleteAnnotation:
    """
    DELETE删除注解数据对象
    """

    def __init__(self, value: str, parameter_type: Optional[str] = None,
                 timeout: Optional[int] = None):
        self.value = value
        self.parameter_type = parameter_type
        self.timeout = timeout


def Delete(value: str, parameter_type: Optional[str] = None,
           timeout: Optional[int] = None) -> Callable:
    """
    DELETE删除注解装饰器

    用于标注Mapper接口方法，表示该方法执行DELETE操作

    Args:
        value: SQL语句
        parameter_type: 参数类型
        timeout: 超时时间（秒）

    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        annotation = DeleteAnnotation(value, parameter_type, timeout)
        setattr(func, 'delete', annotation)
        return func
    return decorator


class ProviderAnnotation:
    """Annotation metadata for Java MyBatis-style SQL providers."""

    def __init__(self, provider_type: Any, method: Optional[str] = None, **kwargs):
        self.provider_type = provider_type
        self.method = method
        self.options = kwargs


def _provider_decorator(attribute: str, provider_type: Any,
                        method: Optional[str] = None, **kwargs) -> Callable:
    def decorator(func: Callable) -> Callable:
        return _attach(func, attribute, ProviderAnnotation(provider_type, method, **kwargs))
    return decorator


def SelectProvider(provider_type: Any = None, method: Optional[str] = None,
                   type: Any = None, value: Any = None, **kwargs) -> Callable:
    """Build SELECT SQL by calling a provider function or class method."""
    provider = provider_type if provider_type is not None else (type if type is not None else value)
    return _provider_decorator('select_provider', provider, method, **kwargs)


def InsertProvider(provider_type: Any = None, method: Optional[str] = None,
                   type: Any = None, value: Any = None, **kwargs) -> Callable:
    provider = provider_type if provider_type is not None else (type if type is not None else value)
    return _provider_decorator('insert_provider', provider, method, **kwargs)


def UpdateProvider(provider_type: Any = None, method: Optional[str] = None,
                   type: Any = None, value: Any = None, **kwargs) -> Callable:
    provider = provider_type if provider_type is not None else (type if type is not None else value)
    return _provider_decorator('update_provider', provider, method, **kwargs)


def DeleteProvider(provider_type: Any = None, method: Optional[str] = None,
                   type: Any = None, value: Any = None, **kwargs) -> Callable:
    provider = provider_type if provider_type is not None else (type if type is not None else value)
    return _provider_decorator('delete_provider', provider, method, **kwargs)


class Result:
    """
    结果映射注解

    用于定义单个字段的映射关系
    """

    def __init__(self, column: Optional[str] = None, property: Optional[str] = None,
                 java_type: Optional[str] = None, jdbc_type: Optional[str] = None):
        self.column = column
        self.property = property
        self.java_type = java_type
        self.jdbc_type = jdbc_type


class ResultMap:
    """
    结果映射注解

    用于定义完整的结果映射
    """

    def __init__(self, id: str, type: str, results: Optional[List[Result]] = None):
        self.id = id
        self.type = type
        self.results = results or []
        self.mappings = {
            result.column: result.property
            for result in self.results
            if result.column and result.property
        }

    def __call__(self, target: Callable) -> Callable:
        result_maps = list(getattr(target, '__result_maps__', []))
        result_maps.append(self)
        setattr(target, '__result_maps__', result_maps)
        return target

    def get_property(self, column: str) -> Optional[str]:
        return self.mappings.get(column)


class Options:
    """
    选项注解

    用于配置SQL执行的额外选项
    """

    def __init__(self, fetch_size: Optional[int] = None, timeout: Optional[int] = None,
                 use_cache: bool = True, flush_cache: bool = False,
                 use_generated_keys: bool = False,
                 key_property: Optional[str] = None,
                 key_column: Optional[str] = None):
        self.fetch_size = fetch_size
        self.timeout = timeout
        self.use_cache = use_cache
        self.flush_cache = flush_cache
        self.use_generated_keys = use_generated_keys
        self.key_property = key_property
        self.key_column = key_column

    def __call__(self, target: Callable) -> Callable:
        return _attach(target, 'options', self)


class Param:
    """
    参数命名注解

    用于指定方法参数的名称
    """

    def __init__(self, value: str):
        self.value = value


class CacheNamespace:
    """
    缓存命名空间注解

    用于配置Mapper的缓存策略
    """

    def __init__(self, eviction: str = 'LRU', flush_interval: int = 0,
                 size: int = 1024, read_write: bool = True, blocking: bool = False):
        self.eviction = eviction
        self.flush_interval = flush_interval
        self.size = size
        self.read_write = read_write
        self.blocking = blocking

    def __call__(self, target: Callable) -> Callable:
        return _attach(target, 'cache_namespace', self)


class DataSource:
    """
    数据源注解

    用于指定Mapper使用的数据源
    """

    def __init__(self, value: str):
        self.value = value

    def __call__(self, target: Callable) -> Callable:
        return _attach(target, 'data_source', self)


class Transactional:
    """
    事务注解

    用于标注方法需要在事务中执行
    """

    def __init__(self, isolation: str = 'READ_COMMITTED',
                 propagation: str = 'REQUIRED', rollback_for: Optional[List[type]] = None):
        self.isolation = isolation
        self.propagation = propagation
        self.rollback_for = rollback_for or []

    def __call__(self, target: Callable) -> Callable:
        return _attach(target, 'transactional', self)
