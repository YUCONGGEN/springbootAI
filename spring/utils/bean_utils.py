"""
BeanUtils - 属性复制工具（对齐 Spring org.springframework.beans.BeanUtils）

提供对象间属性复制、属性读写、属性描述符等功能，命名与方法语义对齐 Spring BeanUtils，
并补充 Apache Commons BeanUtils 常用方法（getProperty/setProperty/populate/describe）。

== 与 Java Spring BeanUtils 的差异 ==
1. Python 动态类型，属性复制不做类型转换（Java 通过 PropertyEditor/ConversionService 转换）；
   若同名属性类型不兼容，直接原样赋值，由目标对象自行决定是否接受。
2. 基于 ``__dict__`` / ``getattr`` / ``setattr`` 实现，支持普通类、dataclass、Pydantic v2 Model、ORM entity。
3. 默认浅拷贝（嵌套对象复制引用），需要深拷贝请用 ``copy_deep=True`` 或 ``BeanUtils.clone(source, deep=True)``。
4. 不支持 Java 的 PropertyChangeListener / VetoableChangeListener 等监听机制。
5. 双下划线开头（``__``）的特殊属性与方法（callable）自动排除；单下划线（``_``）约定的私有属性默认参与复制，
   如需排除请通过 ``ignore`` 显式指定。

== 方法对齐速查 ==
- Spring BeanUtils: copy_properties / copy_property / get_property_descriptors / get_property_descriptor / clone
- Apache Commons BeanUtils: get_property / set_property / get_simple_property / populate / describe
"""
from __future__ import annotations

import copy as _copy_module
from typing import Any, Dict, Iterable, Mapping, Optional


__all__ = ["BeanUtils"]


def _is_copyable_attr(name: str, value: Any) -> bool:
    """判断属性是否可参与复制：排除双下划线特殊属性与可调用对象（方法）。"""
    if name.startswith("__"):
        return False
    if callable(value):
        return False
    return True


def _get_readable_properties(source: Any) -> Dict[str, Any]:
    """
    收集源对象所有可读属性（实例属性 + 类上定义的 property）。

    优先取实例 ``__dict__``，再补充类层 property（dataclass/普通类均覆盖）。
    property 的 getter 抛异常时跳过该属性，避免复制中断。
    """
    props: Dict[str, Any] = {}
    source_dict = getattr(source, "__dict__", None)
    if isinstance(source_dict, dict):
        for name, value in source_dict.items():
            if _is_copyable_attr(name, value):
                props[name] = value

    # 补充类层 property（不含实例 __dict__ 已收集的）
    for klass in type(source).__mro__:
        try:
            klass_vars = vars(klass)
        except TypeError:
            continue
        for name, attr in klass_vars.items():
            if name in props:
                continue
            if name.startswith("__"):
                # 提前跳过 dunder，避免触发 Pydantic 等内部 property 的弃用 getter
                continue
            if isinstance(attr, property) and attr.fget is not None:
                try:
                    value = attr.fget(source)
                except Exception:
                    continue
                if _is_copyable_attr(name, value):
                    props[name] = value
    return props


def _is_writable(target: Any, name: str) -> bool:
    """判断目标对象是否能写入该属性：只读 property 返回 False。"""
    for klass in type(target).__mro__:
        try:
            klass_vars = vars(klass)
        except TypeError:
            continue
        if name in klass_vars:
            attr = klass_vars[name]
            if isinstance(attr, property):
                return attr.fset is not None
            # dataclass field / 普通类属性 -> 可写
            return True
    # 实例 __dict__ 可动态扩展的普通对象 -> 可写
    return hasattr(target, "__dict__") or hasattr(target, "__slots__")


class BeanUtils:
    """属性复制工具类（对齐 Spring BeanUtils + Apache Commons BeanUtils）。"""

    # ------------------------------------------------------------------
    # Spring BeanUtils 对齐
    # ------------------------------------------------------------------
    @staticmethod
    def copy_properties(
        source: Any,
        target: Any,
        ignore: Optional[Iterable[str]] = None,
        copy_deep: bool = False,
    ) -> None:
        """
        复制源对象同名属性到目标对象（对齐 Spring ``BeanUtils.copyProperties``）。

        Args:
            source: 源对象（``None`` 时直接返回）。
            target: 目标对象（``None`` 时直接返回）。
            ignore: 忽略的属性名集合（对齐 Java ``ignoreProperties`` 变长参数）。
            copy_deep: 是否对每个属性值做深拷贝。默认 False（浅拷贝，与 Spring 一致）。

        规则：
            - 仅复制源对象存在且可读的属性；目标对象不可写（如只读 property）时跳过。
            - 双下划线属性与方法自动排除；私有属性（单下划线）默认复制。
            - 目标对象 setattr 失败（如 Pydantic frozen / slots 限制）时跳过，不抛异常。
        """
        if source is None or target is None:
            return
        ignore_set: set = set(ignore) if ignore else set()
        for name, value in _get_readable_properties(source).items():
            if name in ignore_set:
                continue
            if not _is_writable(target, name):
                continue
            try:
                setattr(target, name, _copy_module.deepcopy(value) if copy_deep else value)
            except (AttributeError, TypeError, ValueError):
                # 目标对象校验失败或不可写：跳过，保持 Spring 的"尽力复制"语义
                continue

    @staticmethod
    def copy_property(source: Any, target: Any, property_name: str) -> bool:
        """
        复制单个属性（对齐 Spring ``BeanUtils.copyProperty``）。

        Returns:
            是否复制成功（源无此属性或目标不可写返回 False）。
        """
        if source is None or target is None:
            return False
        if not hasattr(source, property_name):
            return False
        try:
            value = getattr(source, property_name)
        except Exception:
            return False
        if not _is_copyable_attr(property_name, value):
            return False
        if not _is_writable(target, property_name):
            return False
        try:
            setattr(target, property_name, value)
            return True
        except (AttributeError, TypeError, ValueError):
            return False

    @staticmethod
    def clone(source: Any, deep: bool = False) -> Any:
        """
        克隆对象（对齐 Spring ``BeanUtils.cloneBean``，Apache Commons 风格）。

        Args:
            source: 源对象。
            deep: True 做深拷贝；False 仅复制顶层（嵌套对象共享引用）。

        Returns:
            与源同类型的新对象，属性已复制。
        """
        if source is None:
            return None
        target = type(source).__new__(type(source))
        BeanUtils.copy_properties(source, target, copy_deep=deep)
        return target

    @staticmethod
    def get_property_descriptors(obj: Any) -> Dict[str, Optional[type]]:
        """
        获取属性描述符（对齐 Spring ``BeanUtils.getPropertyDescriptors``）。

        Returns:
            属性名 -> 属性值类型的映射（无法推断类型时为 None）。
        """
        descriptors: Dict[str, Optional[type]] = {}
        for name, value in _get_readable_properties(obj).items():
            descriptors[name] = type(value) if value is not None else None
        return descriptors

    @staticmethod
    def get_property_descriptor(obj: Any, name: str) -> Optional[type]:
        """获取单个属性的描述符（对齐 Spring ``BeanUtils.getPropertyDescriptor``）。"""
        if obj is None or not hasattr(obj, name):
            return None
        try:
            value = getattr(obj, name)
        except Exception:
            return None
        return type(value) if value is not None else None

    # ------------------------------------------------------------------
    # Apache Commons BeanUtils 对齐
    # ------------------------------------------------------------------
    @staticmethod
    def get_property(obj: Any, name: str, default: Any = None) -> Any:
        """
        获取属性值，支持嵌套路径（对齐 Apache Commons ``BeanUtils.getProperty``）。

        Args:
            name: 属性名，支持点号嵌套，如 ``"user.address.city"``。
            default: 路径中断或取值异常时返回的默认值。

        Returns:
            属性值；路径中断或异常返回 ``default``。
        """
        if obj is None or not name:
            return default
        current: Any = obj
        for part in name.split("."):
            if current is None:
                return default
            if isinstance(current, Mapping) and part in current:
                current = current[part]
            elif hasattr(current, part):
                try:
                    current = getattr(current, part)
                except Exception:
                    return default
            else:
                return default
        return current if current is not None else default

    @staticmethod
    def set_property(obj: Any, name: str, value: Any) -> bool:
        """
        设置属性值，支持嵌套路径（对齐 Apache Commons ``BeanUtils.setProperty``）。

        Args:
            name: 属性名，支持点号嵌套；嵌套中间节点为 None 时创建失败返回 False。

        Returns:
            是否设置成功。
        """
        if obj is None or not name:
            return False
        parts = name.split(".")
        current: Any = obj
        for part in parts[:-1]:
            if current is None:
                return False
            if isinstance(current, Mapping):
                if part not in current or current[part] is None:
                    return False
                current = current[part]
            elif hasattr(current, part):
                try:
                    nxt = getattr(current, part)
                except Exception:
                    return False
                if nxt is None:
                    return False
                current = nxt
            else:
                return False
        leaf = parts[-1]
        try:
            if isinstance(current, Mapping):
                current[leaf] = value
            else:
                setattr(current, leaf, value)
            return True
        except (AttributeError, TypeError, ValueError, KeyError):
            return False

    @staticmethod
    def get_simple_property(obj: Any, name: str, default: Any = None) -> Any:
        """获取简单属性（不支持嵌套，对齐 Apache Commons ``getSimpleProperty``）。"""
        if obj is None or not name or not hasattr(obj, name):
            return default
        try:
            value = getattr(obj, name)
        except Exception:
            return default
        return value if value is not None else default

    @staticmethod
    def populate(obj: Any, properties: Mapping[str, Any]) -> None:
        """
        用字典批量设置属性（对齐 Apache Commons ``BeanUtils.populate``）。

        Args:
            obj: 目标对象。
            properties: 属性名 -> 值的映射；不可写的属性自动跳过。
        """
        if obj is None or not properties:
            return
        for name, value in properties.items():
            if not _is_writable(obj, name):
                continue
            try:
                setattr(obj, name, value)
            except (AttributeError, TypeError, ValueError):
                continue

    @staticmethod
    def describe(obj: Any) -> Dict[str, Any]:
        """
        将对象可读属性导出为字典（对齐 Apache Commons ``BeanUtils.describe``）。

        Returns:
            属性名 -> 值的映射（仅可读属性，排除方法与双下划线属性）。
        """
        if obj is None:
            return {}
        return _get_readable_properties(obj)
