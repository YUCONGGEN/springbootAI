"""
PyMyBatis敏感数据脱敏模块

实现对敏感数据（密码、身份证、手机号等）的脱敏处理
"""

import re
from typing import Any, Dict, Optional, Callable
from enum import Enum


class SensitiveDataType(Enum):
    """敏感数据类型"""
    PASSWORD = 'password'
    ID_CARD = 'id_card'
    PHONE = 'phone'
    EMAIL = 'email'
    BANK_CARD = 'bank_card'
    ADDRESS = 'address'
    NAME = 'name'
    CREDIT_CARD = 'credit_card'


class MaskStrategy:
    """脱敏策略"""

    def __init__(self, pattern: str, replacer: Callable[[str], str], description: str):
        self.pattern = re.compile(pattern)
        self.replacer = replacer
        self.description = description


class SensitiveDataMasker:
    """
    敏感数据脱敏器

    核心功能：
    1. 自动识别敏感数据类型
    2. 按类型进行脱敏处理
    3. 支持自定义脱敏规则
    4. 支持日志脱敏
    """

    # 默认脱敏策略
    DEFAULT_STRATEGIES = {
        SensitiveDataType.PASSWORD: MaskStrategy(
            pattern=r'.+',
            replacer=lambda x: '******',
            description='密码全脱敏'
        ),
        SensitiveDataType.ID_CARD: MaskStrategy(
            pattern=r'(\d{4})\d{10}(\d{4})',
            replacer=lambda x: x.group(1) + '**********' + x.group(2),
            description='身份证号保留前4后4'
        ),
        SensitiveDataType.PHONE: MaskStrategy(
            pattern=r'(\d{3})\d{4}(\d{4})',
            replacer=lambda x: x.group(1) + '****' + x.group(2),
            description='手机号保留前3后4'
        ),
        SensitiveDataType.EMAIL: MaskStrategy(
            pattern=r'([a-zA-Z0-9._%+-]{3})([a-zA-Z0-9._%+-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
            replacer=lambda x: x.group(1) + '***@' + x.group(3),
            description='邮箱用户名保留前3位'
        ),
        SensitiveDataType.BANK_CARD: MaskStrategy(
            pattern=r'(\d{4})\d{8,12}(\d{4})',
            replacer=lambda x: x.group(1) + '********' + x.group(2),
            description='银行卡号保留前4后4'
        ),
        SensitiveDataType.ADDRESS: MaskStrategy(
            pattern=r'(.{3}).+(.{2})',
            replacer=lambda x: x.group(1) + '***' + x.group(2),
            description='地址保留前3后2'
        ),
        SensitiveDataType.NAME: MaskStrategy(
            pattern=r'([\u4e00-\u9fa5])([\u4e00-\u9fa5]+)',
            replacer=lambda x: x.group(1) + '*' * len(x.group(2)),
            description='姓名保留第一个字'
        ),
        SensitiveDataType.CREDIT_CARD: MaskStrategy(
            pattern=r'(\d{4})\d{12}(\d{4})',
            replacer=lambda x: x.group(1) + '************' + x.group(2),
            description='信用卡号保留前4后4'
        ),
    }

    # 自动检测模式
    DETECTION_PATTERNS = {
        SensitiveDataType.ID_CARD: re.compile(r'^\d{17}[\dXx]$'),
        SensitiveDataType.PHONE: re.compile(r'^1[3-9]\d{9}$'),
        SensitiveDataType.EMAIL: re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'),
        SensitiveDataType.BANK_CARD: re.compile(r'^\d{16,19}$'),
        SensitiveDataType.CREDIT_CARD: re.compile(r'^\d{16}$'),
    }

    def __init__(self, enabled: bool = True):
        """
        初始化脱敏器

        Args:
            enabled: 是否启用脱敏
        """
        self.enabled = enabled
        self.strategies = self.DEFAULT_STRATEGIES.copy()

    def detect_type(self, value: Any) -> Optional[SensitiveDataType]:
        """
        自动检测数据类型

        Args:
            value: 待检测的值

        Returns:
            检测到的数据类型，未检测到返回None
        """
        if value is None:
            return None

        if not isinstance(value, str):
            value = str(value)

        for data_type, pattern in self.DETECTION_PATTERNS.items():
            if pattern.match(value):
                return data_type

        return None

    def mask(self, value: Any, data_type: Optional[SensitiveDataType] = None) -> Any:
        """
        脱敏处理

        Args:
            value: 待脱敏的值（支持单个值或字典）
            data_type: 指定数据类型，不指定则自动检测

        Returns:
            脱敏后的值
        """
        # 如果是字典，调用mask_dict
        if isinstance(value, dict):
            return self.mask_dict(value)

        if not self.enabled:
            return value

        if value is None:
            return None

        # 如果未指定类型，自动检测
        if data_type is None:
            data_type = self.detect_type(value)

        if data_type is None:
            return value

        # 获取对应的脱敏策略
        strategy = self.strategies.get(data_type)
        if strategy is None:
            return value

        # 转换为字符串进行脱敏
        if not isinstance(value, str):
            value = str(value)

        # 执行正则匹配
        match_result = strategy.pattern.match(value)
        if match_result:
            return strategy.replacer(match_result)
        # 如果匹配失败，使用替换策略或返回原值
        if strategy.pattern.pattern == r'.+':
            return strategy.replacer(None)
        return value

    def mask_dict(self, data: Dict[str, Any], field_types: Optional[Dict[str, SensitiveDataType]] = None) -> Dict[str, Any]:
        """
        批量脱敏字典中的敏感字段

        Args:
            data: 待脱敏的字典
            field_types: 字段名到数据类型的映射

        Returns:
            脱敏后的字典
        """
        if not self.enabled:
            return data

        result = {}
        field_types = field_types or {}

        for key, value in data.items():
            # 检查字段名是否包含敏感关键字
            lower_key = key.lower()
            if lower_key in ['password', 'pwd']:
                data_type = SensitiveDataType.PASSWORD
            elif lower_key in ['idcard', 'id_card', 'id', 'identity']:
                data_type = SensitiveDataType.ID_CARD
            elif lower_key in ['phone', 'mobile', 'tel']:
                data_type = SensitiveDataType.PHONE
                # 处理短手机号（少于11位）
                if isinstance(value, str) and len(value) < 11:
                    result[key] = value[:3] + '****'
                    continue
            elif lower_key in ['email', 'mail']:
                data_type = SensitiveDataType.EMAIL
            elif lower_key in ['bank_card', 'bankcard', 'card_no']:
                data_type = SensitiveDataType.BANK_CARD
            else:
                data_type = field_types.get(key)

            result[key] = self.mask(value, data_type)

        return result

    def mask_list(self, data_list: list, field_types: Optional[Dict[str, SensitiveDataType]] = None) -> list:
        """
        批量脱敏列表中的字典

        Args:
            data_list: 待脱敏的列表
            field_types: 字段名到数据类型的映射

        Returns:
            脱敏后的列表
        """
        if not self.enabled:
            return data_list

        return [self.mask_dict(item, field_types) for item in data_list]

    def mask_log(self, log_message: str) -> str:
        """
        脱敏日志消息中的敏感数据

        Args:
            log_message: 日志消息

        Returns:
            脱敏后的日志消息
        """
        return self.mask_message(log_message)

    def mask_message(self, log_message: str) -> str:
        """
        脱敏日志消息中的敏感数据（mask_log的别名）

        Args:
            log_message: 日志消息

        Returns:
            脱敏后的日志消息
        """
        if not self.enabled:
            return log_message

        if not isinstance(log_message, str):
            return log_message

        # 使用简单的正则表达式直接匹配日志中的敏感数据
        # 手机号
        log_message = re.sub(r'1[3-9]\d{9}', lambda x: x.group()[:3] + '****' + x.group()[-4:], log_message)
        # 身份证号
        log_message = re.sub(r'\d{17}[\dXx]', lambda x: x.group()[:3] + '***' + x.group()[-4:], log_message)
        # 邮箱
        log_message = re.sub(
            r'([a-zA-Z0-9._%+-])([a-zA-Z0-9._%+-]*)([a-zA-Z0-9._%+-])@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', 
            lambda x: x.group(1) + '**' + x.group(3) + '@' + x.group(4), log_message)
        # 银行卡号（16-19位）
        log_message = re.sub(r'\d{16,19}', lambda x: x.group()[:4] + '********' + x.group()[-4:], log_message)
        # 密码字段
        log_message = re.sub(r'(password|pwd)\s*=\s*[^, \n]+', r'\1=********', log_message, flags=re.IGNORECASE)

        return log_message

    def add_strategy(self, data_type: SensitiveDataType, pattern: str, replacer: Callable[[str], str], description: str) -> None:
        """
        添加自定义脱敏策略

        Args:
            data_type: 数据类型
            pattern: 正则表达式模式
            replacer: 替换函数
            description: 策略描述
        """
        self.strategies[data_type] = MaskStrategy(pattern, replacer, description)

    def remove_strategy(self, data_type: SensitiveDataType) -> None:
        """
        移除脱敏策略

        Args:
            data_type: 数据类型
        """
        self.strategies.pop(data_type, None)


# 全局默认脱敏器实例
DEFAULT_MASKER = SensitiveDataMasker()


def mask_sensitive_data(value: Any, data_type: Optional[SensitiveDataType] = None) -> Any:
    """
    便捷函数：脱敏敏感数据

    Args:
        value: 待脱敏的值
        data_type: 数据类型

    Returns:
        脱敏后的值
    """
    return DEFAULT_MASKER.mask(value, data_type)


def mask_log_message(log_message: str) -> str:
    """
    便捷函数：脱敏日志消息

    Args:
        log_message: 日志消息

    Returns:
        脱敏后的日志消息
    """
    return DEFAULT_MASKER.mask_log(log_message)
