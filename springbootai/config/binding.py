"""配置属性松散绑定与校验（对齐 Spring Boot ``@ConfigurationProperties`` 松散绑定 +
``@NestedConfigurationProperties`` + ``@Validated``）。

能力：
- **松散绑定**：``kebab-case`` / ``camelCase`` / ``snake_case`` / ``SCREAMING_SNAKE`` 等命名
  规范化后等价匹配（对齐 Spring ``RelaxedNames``）。如 ``max-connections``、``maxConnections``、
  ``max_connections`` 均绑定到属性 ``max_connections``。
- **嵌套绑定**：属性类型标注为 ``@NestedConfigurationProperties`` 类时，递归绑定子字典到该类实例。
- **类型强转**：标量值按属性类型注解强转（``int``/``float``/``bool``/``str``），避免 YAML 字符串误绑。
- **校验**：类上标注 ``@Validated`` 时，绑定后调用 ``BeanValidator.validate_or_raise``，
  违反约束抛 ``ValidationError``（对齐 Spring ``@Validated`` + Hibernate Validator）。

设计：
- **复用既有范式**：``@NestedConfigurationProperties`` 继承 ``SpringAnnotation``；校验复用
  ``springbootai.validation.BeanValidator``，不重复造轮子。
- **独立可测**：``ConfigurationPropertiesBinder.bind`` 为静态方法，无需 IoC 容器即可使用。
- **集成点**：``ApplicationContext._apply_configuration_properties`` 调用本绑定器替代原扁平绑定。

与 Java 的差异：
- Spring 用 ``Binder`` + ``BeanBinder``；本实现用反射 + ``get_type_hints``，简化但覆盖常见场景。
- 不支持 ``Duration``/``DataSize`` 等专用转换器（可按需扩展 ``_coerce``）。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, get_type_hints

from springbootai.annotations.core import SpringAnnotation, Validated

logger = logging.getLogger("Spring.Config.Binding")


class NestedConfigurationProperties(SpringAnnotation):
    """``@NestedConfigurationProperties`` 标记一个类可作为嵌套配置属性持有者。

    标注后，父 ``@ConfigurationProperties`` 绑定时遇到该类型的属性会递归绑定子字典。
    """

    _annotation_type = "nested_properties"

    def __init__(self, prefix: str = ""):
        super().__init__(prefix=prefix)


# 匹配非字母数字字符（kebab/camel/snake 分隔符）用于规范化
_NON_ALNUM = re.compile(r'[^0-9a-zA-Z]+')


def _normalize(name: str) -> str:
    """规范化命名：去除分隔符并小写，用于松散匹配。

    ``max-connections`` / ``maxConnections`` / ``max_connections`` / ``MAX_CONNECTIONS``
    → ``maxconnections``。
    """
    if not isinstance(name, str):
        return str(name).lower()
    return _NON_ALNUM.sub('', name).lower()


def _is_nested_config_class(cls: Optional[type]) -> bool:
    """判断类是否标注 ``@NestedConfigurationProperties``。"""
    if cls is None or not isinstance(cls, type):
        return False
    annotations = getattr(cls, '__spring_annotations__', [])
    return any(isinstance(a, NestedConfigurationProperties) for a in annotations)


def _coerce(value: Any, target_type: Optional[type]) -> Any:
    """按目标类型强转标量值；无法强转则原样返回（交由校验器报错）。"""
    if target_type is None or value is None:
        return value
    # 已经是目标类型，直接返回
    if isinstance(value, target_type):
        return value
    try:
        if target_type is bool:
            # YAML 已把 true/false 解析为 bool；字符串场景兜底
            if isinstance(value, str):
                return value.strip().lower() in ('true', '1', 'yes', 'on')
            return bool(value)
        if target_type is int:
            return int(value)
        if target_type is float:
            return float(value)
        if target_type is str:
            return str(value)
    except (ValueError, TypeError):
        return value  # 强转失败保留原值，由校验器/使用方处理
    return value


class ConfigurationPropertiesBinder:
    """配置属性松散绑定器（静态方法风格，无状态）。"""

    @staticmethod
    def _resolve_attr_name(instance: Any, config_key: str, candidates: Dict[str, str]) -> Optional[str]:
        """松散匹配：把 config_key 规范化后在属性候选表中查找。

        ``candidates`` 为 ``{normalized_attr_name: actual_attr_name}``。
        """
        normalized = _normalize(config_key)
        return candidates.get(normalized)

    @staticmethod
    def _attr_candidates(instance: Any) -> Dict[str, str]:
        """构造属性候选表：``{规范化属性名: 实际属性名}``。

        综合三类来源，确保 ``__init__`` 赋值的实例属性、类级注解属性、继承属性均可命中：
        1. 类级类型注解（``get_type_hints``，最可靠，含继承）
        2. 实例 ``__dict__``（``__init__`` 赋值的属性）
        3. ``dir(cls)`` 类属性兜底
        """
        candidates: Dict[str, str] = {}
        cls = type(instance)
        # 1. 类型注解（含继承，最可靠的属性名来源）
        try:
            for attr in get_type_hints(cls):
                if not attr.startswith('_'):
                    candidates[_normalize(attr)] = attr
        except Exception:
            pass
        # 2. 实例属性（__init__ 赋值）
        for attr in vars(instance):
            if not attr.startswith('_'):
                candidates[_normalize(attr)] = attr
        # 3. 类属性兜底
        for attr in dir(cls):
            if attr.startswith('_'):
                continue
            candidates.setdefault(_normalize(attr), attr)
        return candidates

    @staticmethod
    def bind(instance: Any, config: Dict[str, Any]) -> Any:
        """递归松散绑定 ``config`` 字典到 ``instance`` 的属性。

        - 嵌套字典 + 属性类型为 ``@NestedConfigurationProperties`` 类 → 递归绑定。
        - 标量按属性类型注解强转。
        - 未匹配的键跳过（不报错，对齐 Spring 宽松绑定）。
        """
        if not isinstance(config, dict):
            return instance
        try:
            type_hints = get_type_hints(type(instance))
        except Exception:
            type_hints = {}
        candidates = ConfigurationPropertiesBinder._attr_candidates(instance)

        for key, value in config.items():
            attr_name = ConfigurationPropertiesBinder._resolve_attr_name(
                instance, key, candidates
            )
            if attr_name is None:
                logger.debug("配置键 '%s' 未匹配到属性，跳过", key)
                continue
            attr_type = type_hints.get(attr_name)
            # 嵌套配置：值是字典且属性类型为 @NestedConfigurationProperties 类
            if isinstance(value, dict) and _is_nested_config_class(attr_type):
                nested_instance = ConfigurationPropertiesBinder._build_nested(attr_type)
                if nested_instance is not None:
                    ConfigurationPropertiesBinder.bind(nested_instance, value)
                    setattr(instance, attr_name, nested_instance)
                    continue
            # 嵌套字典但属性类型非嵌套注解类：若属性类型是普通类，尝试递归绑定（容错）
            if isinstance(value, dict) and isinstance(attr_type, type) and attr_type not in (dict,):
                nested_instance = ConfigurationPropertiesBinder._build_nested(attr_type)
                if nested_instance is not None and _is_nested_config_class(attr_type):
                    ConfigurationPropertiesBinder.bind(nested_instance, value)
                    setattr(instance, attr_name, nested_instance)
                    continue
            # 标量/列表/字典：按类型强转后赋值
            setattr(instance, attr_name, _coerce(value, attr_type))
        return instance

    @staticmethod
    def _build_nested(cls: type) -> Optional[Any]:
        """构造嵌套配置类实例；构造失败返回 None。"""
        try:
            return cls()
        except Exception as exc:
            logger.warning(
                "构造嵌套配置类 %s 失败 error_type=%s",
                cls.__name__, type(exc).__name__)
            return None


def validate_configuration_properties(instance: Any) -> None:
    """若 ``instance`` 类标注了 ``@Validated``，运行 BeanValidator 校验，违反则抛错。

    复用 ``springbootai.validation.BeanValidator``，未启用 validation 模块时静默跳过。
    """
    annotations = getattr(type(instance), '__spring_annotations__', [])
    if not any(isinstance(a, Validated) for a in annotations):
        return
    try:
        from springbootai.validation import BeanValidator
    except ImportError:  # pragma: no cover - validation 为内置模块
        logger.debug("springbootai.validation 未安装，跳过配置属性校验")
        return
    BeanValidator.validate_or_raise(instance)


__all__ = [
    "NestedConfigurationProperties",
    "ConfigurationPropertiesBinder",
    "validate_configuration_properties",
]
