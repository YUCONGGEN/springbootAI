"""
PyMyBatis访问控制模块

实现防止越权查询的访问控制机制
"""

from typing import Dict, Optional, Any, Callable
from abc import ABC, abstractmethod


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

        return self.condition(user_context, params)

    def get_access_condition(self, user_context: Dict[str, Any]) -> Optional[str]:
        """
        获取访问条件

        Args:
            user_context: 用户上下文

        Returns:
            WHERE条件字符串，无条件返回None
        """
        if self.condition is None:
            return None

        return self.condition(user_context, {})

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
    def get_access_condition(self, table: str, action: str, user_context: Dict[str, Any]) -> Optional[str]:
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
    def check_fields(self, table: str, action: str, fields: list) -> list:
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

        key = f"{table}_{action}"
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
        key = f"{table}_{action}"
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

        key = f"{table}_{action}"

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

    def get_access_condition(self, table: str, action: str, user_context: Dict[str, Any]) -> Optional[str]:
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

        return rule.get_access_condition(user_context)

    def check_fields(self, table: str, action: str, fields: list) -> list:
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

        # 对于SELECT操作，检查字段访问权限
        if action.upper() != 'SELECT':
            return fields

        # 获取用户角色
        # 这里需要从上下文中获取角色，但在字段检查时可能没有用户上下文
        # 因此默认检查所有规则中对该表的字段限制
        allowed_fields = set(fields)

        for role_rules in self.rules.values():
            key = f"{table}_{action}"
            if key in role_rules:
                rule = role_rules[key]
                if rule.fields:
                    allowed_fields = allowed_fields.intersection(set(rule.fields))

        # 检查默认规则
        key = f"{table}_{action}"
        if key in self.default_rules:
            rule = self.default_rules[key]
            if rule.fields:
                allowed_fields = allowed_fields.intersection(set(rule.fields))

        return list(allowed_fields)


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
        self.row_filters[table] = filter_func

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

        # 行级访问控制主要通过条件过滤实现，这里默认允许
        return True

    def get_access_condition(self, table: str, action: str, user_context: Dict[str, Any]) -> Optional[str]:
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

        if table in self.row_filters:
            return self.row_filters[table](user_context)

        return None

    def check_fields(self, table: str, action: str, fields: list) -> list:
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


def get_row_level_condition(table: str, action: str, user_context: Dict[str, Any]) -> Optional[str]:
    """
    便捷函数：获取行级访问条件

    Args:
        table: 表名
        action: 操作类型
        user_context: 用户上下文

    Returns:
        WHERE条件字符串
    """
    return DEFAULT_ACCESS_CONTROL.get_access_condition(table, action, user_context)
