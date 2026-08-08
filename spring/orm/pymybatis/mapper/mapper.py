"""
PyMyBatis映射器模块

实现Mapper接口的动态代理，支持XML和注解两种SQL定义方式
"""

import importlib
import inspect
import types
from dataclasses import asdict, is_dataclass
from collections.abc import Mapping
from typing import Any, Dict, Type, Optional, Annotated, Union, get_args, get_origin, get_type_hints

from ..annotations import Param

_UNION_ORIGINS = {Union}
if getattr(types, 'UnionType', None) is not None:
    _UNION_ORIGINS.add(types.UnionType)


class Mapper:
    """
    Mapper基类

    所有Mapper接口都应继承此类
    """
    pass


class MapperProxy:
    """
    Mapper代理类

    实现动态代理，将Mapper接口方法调用转换为SQL执行
    """

    def __init__(self, mapper_class: Type, sql_session: Any):
        """
        初始化Mapper代理

        Args:
            mapper_class: Mapper类
            sql_session: SqlSession实例
        """
        self.mapper_class = mapper_class
        self.sql_session = sql_session
        self._register_result_maps()

    def _register_result_maps(self) -> None:
        namespace = f"{self.mapper_class.__module__}.{self.mapper_class.__name__}"
        for result_map in getattr(self.mapper_class, '__result_maps__', []):
            self.sql_session.result_maps[result_map.id] = result_map
            self.sql_session.result_maps[f"{namespace}.{result_map.id}"] = result_map

    def __getattr__(self, name: str):
        """
        获取属性

        Args:
            name: 属性名

        Returns:
            方法执行结果
        """
        method = getattr(self.mapper_class, name, None)

        if method is None or not callable(method):
            raise AttributeError(f"Mapper {self.mapper_class.__name__} 没有方法: {name}")

        def wrapper(*args, **kwargs):
            return self._execute_method(method, *args, **kwargs)

        return wrapper

    def _execute_method(self, method, *args, **kwargs):
        """
        执行方法

        Args:
            method: 方法对象
            args: 位置参数
            kwargs: 关键字参数

        Returns:
            执行结果
        """
        # 获取被装饰的原始方法
        wrapped_method = getattr(method, '__func__', method)
        
        # 获取方法注解（通过装饰器附加的属性）
        select_annotation = getattr(wrapped_method, 'select', None)
        insert_annotation = getattr(wrapped_method, 'insert', None)
        update_annotation = getattr(wrapped_method, 'update', None)
        delete_annotation = getattr(wrapped_method, 'delete', None)
        select_provider = getattr(wrapped_method, 'select_provider', None)
        insert_provider = getattr(wrapped_method, 'insert_provider', None)
        update_provider = getattr(wrapped_method, 'update_provider', None)
        delete_provider = getattr(wrapped_method, 'delete_provider', None)
        options = getattr(wrapped_method, 'options', None)
        transaction = getattr(
            wrapped_method,
            'transactional',
            getattr(self.mapper_class, 'transactional', None),
        )

        # 解析参数
        params = self._parse_params(method, args, kwargs)

        def execute():
            if options and options.flush_cache:
                self.sql_session.sql_cache.clear()

            if select_annotation or select_provider:
                provider_options = select_provider.options if select_provider else {}
                select_sql = (
                    self._call_sql_provider(select_provider, params)
                    if select_provider else select_annotation.value
                )
                result_map = self._resolve_result_map(
                    provider_options.get('result_map') if select_provider
                    else select_annotation.result_map
                )
                fetch_size = (
                    options.fetch_size if options and options.fetch_size is not None
                    else provider_options.get('fetch_size') if select_provider
                    else select_annotation.fetch_size
                )
                timeout = (
                    options.timeout if options and options.timeout is not None
                    else provider_options.get('timeout') if select_provider
                    else select_annotation.timeout
                )
                use_cache = (
                    options.use_cache if options else provider_options.get('cache', True)
                    if select_provider else select_annotation.cache
                )
                result_type = (
                    (provider_options.get('result_type') or
                     self._result_type_from_return_annotation(method))
                    if select_provider else
                    (select_annotation.result_type or
                     self._result_type_from_return_annotation(method))
                )
                single = self._returns_single(method)
                if single:
                    result = self.sql_session.select_one(
                        select_sql,
                        params,
                        result_map=result_map,
                        use_cache=use_cache,
                        fetch_size=fetch_size,
                        timeout=timeout,
                    )
                else:
                    result = self.sql_session.select(
                        select_sql,
                        params,
                        result_map=result_map,
                        use_cache=use_cache,
                        fetch_size=fetch_size,
                        timeout=timeout,
                    )
                return self._apply_result_type(result, result_type)

            timeout = options.timeout if options else None
            if insert_annotation or insert_provider:
                provider_options = insert_provider.options if insert_provider else {}
                insert_sql = (
                    self._call_sql_provider(insert_provider, params)
                    if insert_provider else insert_annotation.value
                )
                use_generated_keys = (
                    insert_annotation.use_generated_keys if insert_annotation else False
                ) or bool(options and options.use_generated_keys) or bool(
                    provider_options.get('use_generated_keys', False)
                )
                key_property = (
                    insert_annotation.key_property if insert_annotation else None
                ) or (options.key_property if options else None) or provider_options.get('key_property')
                result = self.sql_session.insert(
                    insert_sql,
                    params,
                    use_generated_keys=use_generated_keys,
                    timeout=timeout,
                )
                if use_generated_keys and key_property:
                    self._assign_generated_key(
                        args, kwargs, key_property, result
                    )
                return result
            if update_annotation or update_provider:
                provider_options = update_provider.options if update_provider else {}
                update_sql = (
                    self._call_sql_provider(update_provider, params)
                    if update_provider else update_annotation.value
                )
                return self.sql_session.update(
                    update_sql,
                    params,
                    timeout=timeout or (
                        provider_options.get('timeout') if update_provider
                        else update_annotation.timeout
                    ),
                )
            if delete_annotation or delete_provider:
                provider_options = delete_provider.options if delete_provider else {}
                delete_sql = (
                    self._call_sql_provider(delete_provider, params)
                    if delete_provider else delete_annotation.value
                )
                return self.sql_session.delete(
                    delete_sql,
                    params,
                    timeout=timeout or (
                        provider_options.get('timeout') if delete_provider
                        else delete_annotation.timeout
                    ),
                )

            namespace = self.mapper_class.__module__ + '.' + self.mapper_class.__name__
            statement_id = f"{namespace}.{method.__name__}"
            statement = self.sql_session.get_mapped_statement(statement_id)
            if statement is not None and statement.sql_type == 'SELECT':
                if self._returns_single(method):
                    result = self.sql_session.select_one(statement_id, params)
                else:
                    result = self.sql_session.select(statement_id, params)
                return self._apply_result_type(
                    result, self._result_type_from_return_annotation(method)
                )

            result = self.sql_session.execute(statement_id, params)
            if (
                statement is not None
                and statement.sql_type == 'INSERT'
                and statement.use_generated_keys
                and statement.key_property
            ):
                self._assign_generated_key(args, kwargs, statement.key_property, result)
            return result

        if transaction is None:
            return execute()
        normalized_propagation = str(transaction.propagation).upper()

        deferred = None
        deferred_traceback = None
        with self.sql_session.transaction(
            isolation_level=transaction.isolation,
            propagation=normalized_propagation,
        ):
            try:
                return execute()
            except Exception as exc:
                if not transaction.rollback_for or any(
                    isinstance(exc, exc_type) for exc_type in transaction.rollback_for
                ):
                    raise
                deferred = exc
                deferred_traceback = exc.__traceback__
        raise deferred.with_traceback(deferred_traceback)

    @staticmethod
    def _call_sql_provider(provider: Any, params: Dict[str, Any]) -> str:
        """Resolve and invoke a provider, accepting Java- and Python-style APIs."""
        if provider is None or provider.provider_type is None:
            raise ValueError("Provider 注解必须提供 provider_type/type/value")
        target = provider.provider_type
        if isinstance(target, str):
            module_name, _, member_name = target.rpartition('.')
            if not module_name:
                raise ImportError(f"Provider 类型必须是可导入的全限定名称: {target}")
            target = getattr(importlib.import_module(module_name), member_name)

        method_name = provider.method
        if method_name:
            method = getattr(target, method_name, None)
            if method is None and inspect.isclass(target):
                method = getattr(target(), method_name, None)
        elif callable(target):
            method = target
        else:
            method = getattr(target, 'provide_sql', None) or getattr(target, 'sql', None)
        if not callable(method):
            raise TypeError("Provider 必须是可调用对象，或包含指定方法/provide_sql 方法")

        try:
            signature = inspect.signature(method)
            positional = [p for p in signature.parameters.values()
                          if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
            accepts_kwargs = any(p.kind == p.VAR_KEYWORD for p in signature.parameters.values())
            if accepts_kwargs or (not positional and signature.parameters):
                result = method(**params)
            elif positional:
                result = method(params)
            else:
                result = method()
        except (TypeError, ValueError):
            # C-extension callables may not expose signatures; the dict form
            # is the least surprising provider contract.
            result = method(params)
        if not isinstance(result, str) or not result.strip():
            raise ValueError("SQL Provider 必须返回非空 SQL 字符串")
        return result

    def _resolve_result_map(self, result_map: Any) -> Optional[str]:
        if result_map is None:
            return None
        if not isinstance(result_map, str):
            self.sql_session.result_maps[result_map.id] = result_map
            return result_map.id
        if result_map in self.sql_session.result_maps:
            return result_map
        namespaced = f"{self.mapper_class.__module__}.{self.mapper_class.__name__}.{result_map}"
        return namespaced if namespaced in self.sql_session.result_maps else result_map

    def _apply_result_type(self, result: Any, result_type: Any) -> Any:
        target_type = self._resolve_result_type(result_type)
        if target_type is None or result is None:
            return result
        if isinstance(result, list):
            return [self._construct_result(target_type, item) for item in result]
        return self._construct_result(target_type, result)

    def _resolve_result_type(self, result_type: Any) -> Optional[Type]:
        if result_type is None or result_type in ('dict', 'builtins.dict'):
            return None
        if isinstance(result_type, type):
            return result_type
        if not isinstance(result_type, str):
            raise TypeError("result_type 必须是类型或可导入的类型名称")
        if '.' in result_type:
            module_name, type_name = result_type.rsplit('.', 1)
            return getattr(importlib.import_module(module_name), type_name)
        module = importlib.import_module(self.mapper_class.__module__)
        return getattr(module, result_type)

    @staticmethod
    def _return_annotation(method) -> Any:
        try:
            return get_type_hints(method, include_extras=True).get('return')
        except (NameError, TypeError):
            return inspect.signature(method).return_annotation

    def _returns_single(self, method) -> bool:
        annotation = self._return_annotation(method)
        if annotation is not inspect.Signature.empty:
            origin = get_origin(annotation)
            if origin in {list, tuple, set, dict}:
                return False
            if origin in _UNION_ORIGINS:
                candidates = [value for value in get_args(annotation) if value is not type(None)]
                return len(candidates) == 1 and not self._is_collection_type(candidates[0])
            return not self._is_collection_type(annotation)

        method_name = method.__name__
        return (
            method_name.startswith('find_by_')
            or method_name.startswith('get_by_')
            or method_name == 'find_one'
        )

    @staticmethod
    def _is_collection_type(annotation: Any) -> bool:
        return get_origin(annotation) in {list, tuple, set, dict} or annotation in {
            list, tuple, set, dict
        }

    def _result_type_from_return_annotation(self, method) -> Optional[Type]:
        annotation = self._return_annotation(method)
        if annotation is inspect.Signature.empty:
            return None
        origin = get_origin(annotation)
        if origin in {list, tuple, set}:
            args = get_args(annotation)
            return args[0] if args else None
        if origin is dict:
            return None
        if origin in _UNION_ORIGINS:
            candidates = [value for value in get_args(annotation) if value is not type(None)]
            return candidates[0] if len(candidates) == 1 else None
        return annotation if isinstance(annotation, type) else None

    @staticmethod
    def _construct_result(target_type: Type, value: Any) -> Any:
        if isinstance(value, target_type):
            return value
        if not isinstance(value, Mapping):
            return target_type(value)
        try:
            return target_type(**value)
        except TypeError:
            instance = target_type()
            for key, item in value.items():
                setattr(instance, key, item)
            return instance

    @staticmethod
    def _assign_generated_key(args, kwargs, property_name: str, value: Any) -> None:
        for candidate in list(args) + list(kwargs.values()):
            if isinstance(candidate, dict):
                candidate[property_name] = value
                return
            if hasattr(candidate, '__dict__'):
                setattr(candidate, property_name, value)
                return

    def _parse_params(self, method, args, kwargs) -> Dict[str, Any]:
        """
        解析方法参数

        Args:
            method: 方法对象
            args: 位置参数
            kwargs: 关键字参数

        Returns:
            参数字典
        """
        params = {}

        # 获取方法签名
        sig = inspect.signature(method)
        parameters = list(sig.parameters.values())
        try:
            type_hints = get_type_hints(method, include_extras=True)
        except (NameError, TypeError):
            type_hints = {}

        # 处理位置参数，跳过第一个参数self（MapperProxy调用时不传递self）
        for i, arg in enumerate(args):
            param_index = i + 1  # 跳过self
            if param_index < len(parameters):
                parameter = parameters[param_index]
                annotation = type_hints.get(parameter.name, parameter.annotation)
                alias = self._parameter_alias(annotation, parameter.name)
                self._add_param(params, alias, arg)
                if alias != parameter.name:
                    params.setdefault(parameter.name, arg)

        # 处理关键字参数
        for key, value in kwargs.items():
            parameter = sig.parameters.get(key)
            annotation = type_hints.get(key, parameter.annotation) if parameter else None
            alias = self._parameter_alias(annotation, key)
            self._add_param(params, alias, value)
            if alias != key:
                params.setdefault(key, value)

        return params

    @staticmethod
    def _parameter_alias(annotation: Any, default: str) -> str:
        if isinstance(annotation, Param):
            return annotation.value
        if get_origin(annotation) is Annotated:
            for metadata in get_args(annotation)[1:]:
                if isinstance(metadata, Param):
                    return metadata.value
        return default

    @staticmethod
    def _add_param(params: Dict[str, Any], name: str, value: Any) -> None:
        """保留命名参数，同时为单对象参数提供可预测的字段展开。"""
        params[name] = value

        expanded = None
        if isinstance(value, Mapping):
            expanded = value
        elif is_dataclass(value) and not isinstance(value, type):
            expanded = asdict(value)
        elif hasattr(value, 'to_dict') and callable(value.to_dict):
            candidate = value.to_dict()
            if isinstance(candidate, Mapping):
                expanded = candidate
        elif hasattr(value, '__dict__'):
            expanded = {
                key: item for key, item in vars(value).items()
                if not key.startswith('_')
            }

        if expanded:
            for key, item in expanded.items():
                params.setdefault(str(key), item)


class MapperRegistry:
    """
    Mapper注册中心

    管理所有Mapper接口，支持懒加载
    """

    def __init__(self):
        """初始化Mapper注册中心"""
        self.mappers: Dict[str, Type] = {}

    def add_mapper(self, mapper_class: Type) -> None:
        """
        添加Mapper

        Args:
            mapper_class: Mapper类
        """
        key = f"{mapper_class.__module__}.{mapper_class.__name__}"
        self.mappers[key] = mapper_class

    def get_mapper(self, mapper_class: Type) -> Optional[Type]:
        """
        获取Mapper类

        Args:
            mapper_class: Mapper类

        Returns:
            Mapper类，未找到返回None
        """
        key = f"{mapper_class.__module__}.{mapper_class.__name__}"
        return self.mappers.get(key)

    def has_mapper(self, mapper_class: Type) -> bool:
        """
        检查Mapper是否已注册

        Args:
            mapper_class: Mapper类

        Returns:
            是否已注册
        """
        key = f"{mapper_class.__module__}.{mapper_class.__name__}"
        return key in self.mappers

    def get_all_mappers(self) -> Dict[str, Type]:
        """获取所有Mapper"""
        return self.mappers

    def clear(self) -> None:
        """清空所有Mapper"""
        self.mappers.clear()
