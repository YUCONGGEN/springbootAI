"""共享类型工具 —— 规范化类型注解，消除 Python 版本差异。

背景：``typing.get_type_hints`` 在 Python 3.10 上会把带 ``None`` 默认值的参数注解
自动包装为 ``Optional[X]``（即 ``Union[X, None]``）；自 Python 3.11 起该自动包装
行为被移除，注解原样返回。这导致同一份代码在 3.10 与 3.11/3.12 上得到不同的
``py_type``，进而影响 SQL 类型映射、CSV 转换器选择等下游推断。

本模块统一把 ``Optional[X]`` / ``Union[X, None]`` 解包为 ``X``，使下游类型推断与
Python 版本无关。对齐 Spring ``org.springframework.core.ResolvableType`` 的职责
（提供统一的类型解析语义），仅做最小必要的可空解包。
"""
import typing

# NoneType 的单例，用于在 Union 参数中识别并剔除 ``None``
_NONE_TYPE = type(None)


def unwrap_optional_type(tp):
    """把 ``Optional[X]`` / ``Union[X, None]`` 解包为 ``X``；其他类型原样返回。

    用于从 ``get_type_hints`` 得到的类型中取出“承载类型”，供 SQL 类型映射、
    转换器选择等只关心实际承载类型、忽略可空性的场景。可空性由 ``nullable``
    等列元数据单独表达，不应混入类型映射。

    - ``Optional[int]`` / ``Union[int, None]`` -> ``int``
    - ``int`` -> ``int``（原样返回）
    - ``Union[int, str, None]`` -> 原样返回（多元素 Union 无单一承载类型，不解包）
    - ``None`` -> ``None``

    Examples:
        >>> import typing
        >>> unwrap_optional_type(typing.Optional[int]) is int
        True
        >>> unwrap_optional_type(int) is int
        True
        >>> unwrap_optional_type(None) is None
        True
    """
    if tp is None:
        return tp
    # Optional[X] 在运行期等价于 Union[X, None]，其 origin 为 typing.Union
    if typing.get_origin(tp) is typing.Union:
        args = [a for a in typing.get_args(tp) if a is not _NONE_TYPE]
        # 仅当剔除 None 后剩单一承载类型时才解包；多元素 Union 保持原样
        if len(args) == 1:
            return args[0]
    return tp


__all__ = ["unwrap_optional_type"]
