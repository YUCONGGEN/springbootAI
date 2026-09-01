"""
PyMyBatis访问控制模块

实现防止越权查询的访问控制机制
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Any, Callable, Mapping, Union
from abc import ABC, abstractmethod


@dataclass(frozen=True)
class AccessCondition:
    """Parameterized row-level predicate.

    ``sql`` must use MyBatis ``#{name}`` placeholders. Values are merged into
    the statement parameter mapping under private names by ``SqlSession`` so
    user/tenant claims never become SQL text.
    """

    sql: str
    params: Mapping[str, Any] = field(default_factory=dict)


AccessConditionValue = Union[
    AccessCondition,
    tuple[str, Mapping[str, Any]],
    str,
    bool,
]


class AccessControlRule:
    """
    访问控制规则

    定义对特定表/字段的访问权限
    """

    def __init__(self, table: str, action: str, condition: Optional[Callable] = None, fields: Optional[list] = None):
        """
        初始化访问控制规则

        Args:
            table: 表名
            action: 操作类型（SELECT/INSERT/UPDATE/DELETE）
            condition: 访问条件函数，返回额外的WHERE条件
            fields: 允许访问的字段列表，None表示全部允许
        """
        self.table = table
        self.action = action.upper()
        self.condition = condition
        self.fields = fields or []

    def check_access(self, user_context: Dict[str, Any], params: Dict[str, Any]) -> bool:
        """
        检查访问权限

        Args:
            user_context: 用户上下文（包含用户ID、角色等）
            params: 查询参数

        Returns:
            是否允许访问
        """
        if self.condition is None:
            return True

        result = self.condition(user_context, params)
        if isinstance(result, bool):
            return result
        if isinstance(result, AccessCondition):
            return bool(result.sql.strip())
        if (isinstance(result, tuple) and len(result) == 2
                and isinstance(result[0], str)
                and isinstance(result[1], Mapping)):
            return bool(result[0].strip())
        return isinstance(result, str) and bool(result.strip())

    def get_access_condition(
        self,
        user_context: Dict[str, Any],
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[AccessConditionValue]:
        """
        获取访问条件

        Args:
            user_context: 用户上下文

        Returns:
            WHERE条件字符串，无条件返回None
        """
        if self.condition is None:
            return None

        return self.condition(user_context, params or {})

    def check_fields(self, fields: list) -> list:
        """
        检查字段访问权限

        Args:
            fields: 请求访问的字段列表

        Returns:
            允许访问的字段列表
        """
        if not self.fields:
            return fields

        return [f for f in fields if f in self.fields]


class AccessControl(ABC):
    """
    访问控制抽象基类

    定义访问控制的核心接口
    """

    @abstractmethod
    def check_access(self, table: str, action: str, user_context: Dict[str, Any], params: Dict[str, Any]) -> bool:
        """
        检查访问权限

        Args:
            table: 表名
            action: 操作类型
            user_context: 用户上下文
            params: 查询参数

        Returns:
            是否允许访问
        """
        pass

    @abstractmethod
    def get_access_condition(
        self,
        table: str,
        action: str,
        user_context: Dict[str, Any],
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[AccessConditionValue]:
        """
        获取访问条件

        Args:
            table: 表名
            action: 操作类型
            user_context: 用户上下文

        Returns:
            WHERE条件字符串
        """
        pass

    @abstractmethod
    def check_fields(self, table: str, action: str, fields: list,
                     user_context: Optional[Dict[str, Any]] = None) -> list:
        """
        检查字段访问权限

        Args:
            table: 表名
            action: 操作类型
            fields: 请求访问的字段列表

        Returns:
            允许访问的字段列表
        """
        pass


class RoleBasedAccessControl(AccessControl):
    """
    基于角色的访问控制（RBAC）

    根据用户角色控制对表和字段的访问权限
    """

    def __init__(self, enabled: bool = False):
        """
        初始化RBAC控制器

        Args:
            enabled: 是否启用访问控制
        """
        self.enabled = enabled
        self.rules: Dict[str, Dict[str, AccessControlRule]] = {}
        self.default_rules: Dict[str, AccessControlRule] = {}

    @staticmethod
    def _rule_key(table: str, action: str) -> str:
        return f"{str(table).strip().lower()}_{str(action).strip().upper()}"

    def add_rule(self, role: str, table: str, action: str, condition: Optional[Callable] = None, fields: Optional[list] = None) -> None:
        """
        添加角色访问规则

        Args:
            role: 角色名称
            table: 表名
            action: 操作类型
            condition: 访问条件
            fields: 允许访问的字段
        """
        if role not in self.rules:
            self.rules[role] = {}

        key = self._rule_key(table, action)
        self.rules[role][key] = AccessControlRule(table, action, condition, fields)

    def set_default_rule(self, table: str, action: str, condition: Optional[Callable] = None, fields: Optional[list] = None) -> None:
        """
        设置默认规则（当没有匹配的角色规则时使用）

        Args:
            table: 表名
            action: 操作类型
            condition: 访问条件
            fields: 允许访问的字段
        """
        key = self._rule_key(table, action)
        self.default_rules[key] = AccessControlRule(table, action, condition, fields)

    def _get_rule(self, role: str, table: str, action: str) -> Optional[AccessControlRule]:
        """
        获取匹配的规则

        Args:
            role: 角色名称
            table: 表名
            action: 操作类型

        Returns:
            匹配的规则，无匹配返回None
        """
        if not self.enabled:
            return None

        key = self._rule_key(table, action)

        # 先查找角色特定规则
        if role in self.rules and key in self.rules[role]:
            return self.rules[role][key]

        # 再查找默认规则
        if key in self.default_rules:
            return self.default_rules[key]

        return None

    def check_access(self, table: str, action: str, user_context: Dict[str, Any], params: Dict[str, Any]) -> bool:
        """
        检查访问权限

        Args:
            table: 表名
            action: 操作类型
            user_context: 用户上下文（包含user_id、role等）
            params: 查询参数

        Returns:
            是否允许访问
        """
        if not self.enabled:
            return True

        role = user_context.get('role', 'guest')
        rule = self._get_rule(role, table, action)

        if rule is None:
            # 默认拒绝访问（安全优先）
            return False

        return rule.check_access(user_context, params)

    def get_access_condition(
        self,
        table: str,
        action: str,
        user_context: Dict[str, Any],
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[AccessConditionValue]:
        """
        获取访问条件

        Args:
            table: 表名
            action: 操作类型
            user_context: 用户上下文

        Returns:
            WHERE条件字符串
        """
        if not self.enabled:
            return None

        role = user_context.get('role', 'guest')
        rule = self._get_rule(role, table, action)

        if rule is None:
            return None

        return rule.get_access_condition(user_context, params)

    def check_fields(self, table: str, action: str, fields: list,
                     user_context: Optional[Dict[str, Any]] = None) -> list:
        """
        检查字段访问权限

        Args:
            table: 表名
            action: 操作类型
            fields: 请求访问的字段列表

        Returns:
            允许访问的字段列表
        """
        if not self.enabled:
            return fields

        # Field authorization is principal-specific.  Without a user context
        # there is no safe role to infer, so fail closed.
        if user_context is None:
            return []
        role = user_context.get('role', 'guest')
        rule = self._get_rule(role, table, action)
        if rule is None:
            return []
        return rule.check_fields(fields)


class RowLevelAccessControl(AccessControl):
    """
    行级访问控制

    根据用户上下文限制只能访问特定行的数据
    """

    def __init__(self, enabled: bool = False):
        """
        初始化行级访问控制器

        Args:
            enabled: 是否启用访问控制
        """
        self.enabled = enabled
        self.row_filters: Dict[str, Callable] = {}

    def set_row_filter(self, table: str, filter_func: Callable) -> None:
        """
        设置行过滤函数

        Args:
            table: 表名
            filter_func: 过滤函数，接收用户上下文返回WHERE条件
        """
        self.row_filters[str(table).strip().lower()] = filter_func

    def check_access(self, table: str, action: str, user_context: Dict[str, Any], params: Dict[str, Any]) -> bool:
        """
        检查访问权限

        Args:
            table: 表名
            action: 操作类型
            user_context: 用户上下文
            params: 查询参数

        Returns:
            是否允许访问
        """
        if not self.enabled:
            return True

        key = str(table).strip().lower()
        if key not in self.row_filters:
            return False
        try:
            condition = self.row_filters[key](user_context)
        except Exception:
            return False
        if isinstance(condition, AccessCondition):
            return bool(condition.sql.strip())
        if (isinstance(condition, tuple) and len(condition) == 2
                and isinstance(condition[0], str)
                and isinstance(condition[1], Mapping)):
            return bool(condition[0].strip())
        return isinstance(condition, str) and bool(condition.strip())

    def get_access_condition(
        self,
        table: str,
        action: str,
        user_context: Dict[str, Any],
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[AccessConditionValue]:
        """
        获取访问条件

        Args:
            table: 表名
            action: 操作类型
            user_context: 用户上下文

        Returns:
            WHERE条件字符串
        """
        if not self.enabled:
            return None

        key = str(table).strip().lower()
        if key in self.row_filters:
            condition = self.row_filters[key](user_context)
            if isinstance(condition, AccessCondition) and condition.sql.strip():
                return condition
            if (isinstance(condition, tuple) and len(condition) == 2
                    and isinstance(condition[0], str)
                    and isinstance(condition[1], Mapping)
                    and condition[0].strip()):
                return condition
            if isinstance(condition, str) and condition.strip():
                return condition

        return None

    def check_fields(self, table: str, action: str, fields: list,
                     user_context: Optional[Dict[str, Any]] = None) -> list:
        """
        检查字段访问权限

        Args:
            table: 表名
            action: 操作类型
            fields: 请求访问的字段列表

        Returns:
            允许访问的字段列表
        """
        if not self.enabled:
            return fields

        # 行级访问控制不限制字段
        return fields


# 全局默认访问控制器
DEFAULT_ACCESS_CONTROL = RoleBasedAccessControl()


def check_table_access(table: str, action: str, user_context: Dict[str, Any], params: Dict[str, Any]) -> bool:
    """
    便捷函数：检查表访问权限

    Args:
        table: 表名
        action: 操作类型
        user_context: 用户上下文
        params: 查询参数

    Returns:
        是否允许访问
    """
    return DEFAULT_ACCESS_CONTROL.check_access(table, action, user_context, params)


def get_row_level_condition(
    table: str,
    action: str,
    user_context: Dict[str, Any],
    params: Optional[Dict[str, Any]] = None,
) -> Optional[AccessConditionValue]:
    """
    便捷函数：获取行级访问条件

    Args:
        table: 表名
        action: 操作类型
        user_context: 用户上下文

    Returns:
        WHERE条件字符串
    """
    return DEFAULT_ACCESS_CONTROL.get_access_condition(
        table, action, user_context, params)
