"""
PyMyBatis SQL注入检测模块

实现SQL注入攻击的主动检测和防御机制，核心安全特性：
- 参数值注入检测（正则 + AST双重验证）
- SQL语句注入检测
- DDL语句禁用（DROP/ALTER/CREATE/TRUNCATE等）
- ${}参数白名单检查（支持表名/字段名白名单）
- AST解析验证（基于sqlglot，可选）
"""

import re
import logging
from typing import Optional, Any, Dict, Set
from enum import Enum

logger = logging.getLogger(__name__)


class SQLInjectionLevel(Enum):
    """SQL注入风险级别"""
    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3


class SQLInjectionPattern:
    """SQL注入模式定义"""

    def __init__(self, pattern: str, level: SQLInjectionLevel, description: str):
        self.pattern = re.compile(pattern, re.IGNORECASE)
        self.level = level
        self.description = description


class SQLInjectionDetector:
    """
    SQL注入检测器

    核心功能：
    1. 参数值注入检测（正则 + AST双重验证）
    2. SQL语句注入检测
    3. DDL语句检测与禁用
    4. ${}参数安全检查
    5. 返回风险等级和建议
    """

    # SQL注入模式列表
    INJECTION_PATTERNS = [
        # 基于注释的注入
        SQLInjectionPattern(
            r'(--(?:\s|$)|(?:^|\s)#|/\*).*',
            SQLInjectionLevel.HIGH,
            '注释注入',
        ),

        # UNION注入
        SQLInjectionPattern(r'\bUNION\b.*\bSELECT\b', SQLInjectionLevel.HIGH, 'UNION注入'),

        # 布尔盲注
        SQLInjectionPattern(r'\b(AND|OR)\b.*\d+\s*(=|<|>)\s*\d+', SQLInjectionLevel.HIGH, '布尔盲注'),

        # 简单字符串注入 (如 ' OR '1'='1)
        SQLInjectionPattern(r"'.*\s*(OR|AND)\s*'.*'.*='.*'", SQLInjectionLevel.HIGH, '字符串注入'),
        SQLInjectionPattern(r"'.*\s*(OR|AND)\s*\d+\s*=\s*\d+", SQLInjectionLevel.HIGH, '数字条件注入'),
        SQLInjectionPattern(r"'.*\s*(OR|AND)\s*1\s*=\s*1", SQLInjectionLevel.HIGH, '恒真条件注入'),
        SQLInjectionPattern(r"1'\s*OR\s*'1'\s*=\s*'1", SQLInjectionLevel.HIGH, '经典字符串注入'),
        SQLInjectionPattern(r"'.*\s*(OR|AND)\s*\d+\s*=\s*\d+.*'", SQLInjectionLevel.HIGH, '闭合注入'),

        # 时间盲注
        SQLInjectionPattern(r'\b(SLEEP|BENCHMARK|WAITFOR)\b', SQLInjectionLevel.HIGH, '时间盲注'),

        # 基于函数的注入
        SQLInjectionPattern(
            r'\b(CONCAT|GROUP_CONCAT|VERSION|DATABASE|USER)\s*\(',
            SQLInjectionLevel.MEDIUM,
            '信息收集函数',
        ),

        # 危险关键字
        SQLInjectionPattern(r'\b(DROP|DELETE|UPDATE|INSERT|TRUNCATE|ALTER|CREATE|GRANT|REVOKE)\b',
                            SQLInjectionLevel.HIGH, '危险SQL关键字'),

        # 基于子查询的注入
        SQLInjectionPattern(r'\(\s*SELECT\s+', SQLInjectionLevel.MEDIUM, '子查询注入'),

        # 基于编码的注入
        SQLInjectionPattern(r'(0x[0-9a-f]+|char\(|ascii\()', SQLInjectionLevel.MEDIUM, '编码注入'),

        # 换行符注入
        SQLInjectionPattern(r'[\r\n]+\s*(SELECT|INSERT|UPDATE|DELETE|DROP)', SQLInjectionLevel.HIGH, '换行注入'),

        # 多个连续空格（可能是绕过尝试）
        SQLInjectionPattern(r'\s{3,}', SQLInjectionLevel.LOW, '异常空格'),

        # 字符串拼接
        SQLInjectionPattern(r"('.*')\s*(\|\||\+)\s*('.*')", SQLInjectionLevel.MEDIUM, '字符串拼接'),

        # 条件注释
        SQLInjectionPattern(r'/\*\s*!\d+\s*', SQLInjectionLevel.HIGH, 'MySQL条件注释'),

        # 执行命令
        SQLInjectionPattern(r'\b(EXEC|EXECUTE|XP_CMDSHELL|SYSTEM|SHELL)\b', SQLInjectionLevel.HIGH, '命令执行'),

        # 堆叠查询
        SQLInjectionPattern(r';\s*(SELECT|INSERT|UPDATE|DELETE|DROP)', SQLInjectionLevel.HIGH, '堆叠查询'),

        # 回显注入
        SQLInjectionPattern(r'\b(CAST|CONVERT)\b.*\b(VARCHAR|CHAR)\b', SQLInjectionLevel.MEDIUM, '类型转换'),

        # 正则注入
        SQLInjectionPattern(r'\bREGEXP\b.*\'.*\'', SQLInjectionLevel.MEDIUM, '正则注入'),
    ]

    # DDL语句模式（生产环境默认禁用）
    DDL_PATTERNS = [
        SQLInjectionPattern(r'^\s*DROP\s+', SQLInjectionLevel.HIGH, 'DROP语句'),
        SQLInjectionPattern(r'^\s*ALTER\s+', SQLInjectionLevel.HIGH, 'ALTER语句'),
        SQLInjectionPattern(r'^\s*CREATE\s+(TABLE|INDEX|VIEW|FUNCTION|PROCEDURE)', SQLInjectionLevel.HIGH, 'CREATE语句'),
        SQLInjectionPattern(r'^\s*TRUNCATE\s+', SQLInjectionLevel.HIGH, 'TRUNCATE语句'),
        SQLInjectionPattern(r'^\s*RENAME\s+', SQLInjectionLevel.HIGH, 'RENAME语句'),
        SQLInjectionPattern(r'^\s*GRANT\s+', SQLInjectionLevel.HIGH, 'GRANT语句'),
        SQLInjectionPattern(r'^\s*REVOKE\s+', SQLInjectionLevel.HIGH, 'REVOKE语句'),
        SQLInjectionPattern(r'^\s*COMMIT\s+', SQLInjectionLevel.MEDIUM, 'COMMIT语句'),
        SQLInjectionPattern(r'^\s*ROLLBACK\s+', SQLInjectionLevel.MEDIUM, 'ROLLBACK语句'),
    ]

    # ${}参数白名单（表名、字段名等）
    RAW_PARAM_WHITELIST_PATTERNS = [
        re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$'),  # 表名/字段名
        re.compile(r'^(ASC|DESC)$'),              # 排序方向
        re.compile(r'^[a-zA-Z_][a-zA-Z0-9_.]*$'),  # 带schema的表名
    ]

    def __init__(self, enabled: bool = True,
                 max_risk_level: SQLInjectionLevel = SQLInjectionLevel.LOW,
                 block_ddl: bool = True,
                 allow_raw_params: bool = False,
                 raw_param_whitelist: Optional[Set[str]] = None,
                 allowed_tables: Optional[Set[str]] = None,
                 allowed_columns: Optional[Set[str]] = None,
                 enable_ast_validation: bool = False):
        """
        初始化SQL注入检测器

        Args:
            enabled: 是否启用检测
            max_risk_level: 允许的最大风险级别，超过此级别会阻止执行
            block_ddl: 是否阻止DDL语句
            allow_raw_params: 是否允许${}参数
            raw_param_whitelist: ${}参数名白名单
            allowed_tables: 允许的表名白名单
            allowed_columns: 允许的字段名白名单
            enable_ast_validation: 是否启用AST验证（需要sqlglot库）
        """
        self.enabled = enabled
        self.max_risk_level = max_risk_level
        self.block_ddl = block_ddl
        self.allow_raw_params = allow_raw_params
        self.raw_param_whitelist = raw_param_whitelist or set()
        self.allowed_tables = allowed_tables or set()
        self.allowed_columns = allowed_columns or set()
        self.enable_ast_validation = enable_ast_validation

        # 延迟加载sqlglot
        self._sqlglot = None

    def _load_sqlglot(self):
        """延迟加载sqlglot库"""
        if self._sqlglot is None:
            try:
                import sqlglot
                self._sqlglot = sqlglot
            except ImportError:
                logger.warning("sqlglot库未安装，AST验证功能将不可用。安装方法: pip install sqlglot")
                self.enable_ast_validation = False
        return self._sqlglot

    def detect(self, value: Any) -> SQLInjectionLevel:
        """
        检测单个值是否包含SQL注入风险

        Args:
            value: 待检测的值

        Returns:
            风险等级
        """
        if not self.enabled:
            return SQLInjectionLevel.NONE

        if value is None:
            return SQLInjectionLevel.NONE

        # 转换为字符串进行检测
        if not isinstance(value, str):
            value = str(value)

        # 首先使用正则检测
        max_level = self._detect_by_regex(value)

        # 如果正则检测到风险或启用了AST验证，进行AST验证
        if max_level != SQLInjectionLevel.NONE or self.enable_ast_validation:
            ast_level = self._detect_by_ast(value)
            if ast_level.value > max_level.value:
                max_level = ast_level

        return max_level

    def _detect_by_regex(self, value: str) -> SQLInjectionLevel:
        """
        使用正则表达式检测SQL注入风险

        Args:
            value: 待检测的字符串

        Returns:
            风险等级
        """
        max_level = SQLInjectionLevel.NONE

        for pattern in self.INJECTION_PATTERNS:
            if pattern.pattern.search(value):
                if pattern.level.value > max_level.value:
                    max_level = pattern.level
                # 一旦检测到最高级别，立即返回
                if max_level == SQLInjectionLevel.HIGH:
                    return max_level

        return max_level

    def _detect_by_ast(self, value: str) -> SQLInjectionLevel:
        """
        使用AST解析检测SQL注入风险

        Args:
            value: 待检测的字符串

        Returns:
            风险等级
        """
        if not self.enable_ast_validation:
            return SQLInjectionLevel.NONE

        sqlglot = self._load_sqlglot()
        if sqlglot is None:
            return SQLInjectionLevel.NONE

        try:
            # 尝试解析为SQL表达式
            parsed = sqlglot.parse_one(value)

            # 检查AST结构中的危险模式
            return self._analyze_ast(parsed)
        except Exception as e:
            # 解析失败，可能是恶意输入
            logger.debug(f"AST解析失败，可能存在注入风险: {e}")
            return SQLInjectionLevel.MEDIUM

    def _analyze_ast(self, parsed) -> SQLInjectionLevel:
        """
        分析AST结构，检测危险模式

        Args:
            parsed: sqlglot解析后的AST节点

        Returns:
            风险等级
        """
        sqlglot = self._sqlglot
        if sqlglot is None:
            return SQLInjectionLevel.NONE

        max_level = SQLInjectionLevel.NONE

        # 遍历AST节点
        for node in parsed.walk():
            node_type = type(node).__name__

            # 检测UNION注入
            if node_type == 'Union':
                return SQLInjectionLevel.HIGH

            # 检测子查询
            if node_type == 'Subquery':
                max_level = SQLInjectionLevel.MEDIUM

            # 检测危险函数
            if node_type == 'Func':
                func_name = node.this.this.lower() if hasattr(node.this, 'this') else ''
                dangerous_functions = ['sleep', 'benchmark', 'waitfor', 'version', 'database', 'user', 'system']
                if func_name in dangerous_functions:
                    return SQLInjectionLevel.HIGH

            # 检测DDL语句
            if node_type in ['Drop', 'Truncate', 'Alter', 'Create']:
                return SQLInjectionLevel.HIGH

        return max_level

    def detect_ddl(self, sql: str) -> bool:
        """
        检测SQL语句是否为DDL语句（结合正则和AST）

        Args:
            sql: SQL语句

        Returns:
            是否为DDL语句
        """
        if not self.block_ddl:
            return False

        if sql is None:
            return False

        if not isinstance(sql, str):
            sql = str(sql)

        # 首先使用正则检测
        for pattern in self.DDL_PATTERNS:
            if pattern.pattern.search(sql.strip()):
                logger.warning(f"检测到DDL语句: {sql}")
                return True

        # 如果启用了AST验证，进行二次验证
        if self.enable_ast_validation:
            sqlglot = self._load_sqlglot()
            if sqlglot is not None:
                try:
                    parsed = sqlglot.parse_one(sql)
                    for node in parsed.walk():
                        node_type = type(node).__name__
                        if node_type in ['Drop', 'Truncate', 'Alter', 'Create', 'Grant', 'Revoke']:
                            logger.warning(f"AST检测到DDL语句: {sql}")
                            return True
                except Exception:
                    pass

        return False

    def is_ddl_blocked(self, sql: str) -> bool:
        """
        判断DDL语句是否被阻止

        Args:
            sql: SQL语句

        Returns:
            是否被阻止
        """
        return self.block_ddl and self.detect_ddl(sql)

    def detect_raw_param(self, param_name: str, param_value: Any, param_type: Optional[str] = None) -> bool:
        """
        检测${}参数是否安全（增强版：支持表名/字段名白名单）

        Args:
            param_name: 参数名
            param_value: 参数值
            param_type: 参数类型（'table'/'column'/'sort'）

        Returns:
            是否安全
        """
        # 如果不允许${}，直接不安全
        if not self.allow_raw_params:
            return False

        # 检查参数名白名单
        if param_name in self.raw_param_whitelist:
            return True

        # 检查参数值模式
        if param_value is None:
            return False

        if not isinstance(param_value, str):
            param_value = str(param_value)

        # 检查白名单模式
        for pattern in self.RAW_PARAM_WHITELIST_PATTERNS:
            if pattern.match(param_value):
                # 如果指定了参数类型，进行额外验证
                if param_type == 'table' and self.allowed_tables:
                    if param_value.lower() in [t.lower() for t in self.allowed_tables]:
                        return True
                    logger.warning(f"${{{param_name}}} 参数值不在允许的表名单中: {param_value}")
                    return False
                if param_type == 'column' and self.allowed_columns:
                    if param_value.lower() in [c.lower() for c in self.allowed_columns]:
                        return True
                    logger.warning(f"${{{param_name}}} 参数值不在允许的字段名单中: {param_value}")
                    return False
                return True

        logger.warning(f"${{{param_name}}} 参数值不在白名单中: {param_value}")
        return False

    def validate_table_name(self, table_name: str) -> bool:
        """
        验证表名是否在允许的白名单中

        Args:
            table_name: 表名

        Returns:
            是否允许
        """
        if not self.allowed_tables:
            return True

        return table_name.lower() in [t.lower() for t in self.allowed_tables]

    def validate_column_name(self, column_name: str) -> bool:
        """
        验证字段名是否在允许的白名单中

        Args:
            column_name: 字段名

        Returns:
            是否允许
        """
        if not self.allowed_columns:
            return True

        return column_name.lower() in [c.lower() for c in self.allowed_columns]

    def detect_batch(self, params: Dict[str, Any]) -> Dict[str, SQLInjectionLevel]:
        """
        批量检测多个参数

        Args:
            params: 参数字典

        Returns:
            参数名到风险等级的映射
        """
        results = {}
        for key, value in params.items():
            results[key] = self.detect(value)
        return results

    def is_blocked(self, value: Any) -> bool:
        """
        判断值是否会被阻止（风险级别超过允许的最大值）

        Args:
            value: 待检测的值

        Returns:
            是否被阻止
        """
        level = self.detect(value)
        return level.value > self.max_risk_level.value

    def is_safe(self, value: Any) -> bool:
        """
        判断值是否安全

        Args:
            value: 待检测的值

        Returns:
            是否安全
        """
        return not self.is_blocked(value)

    def sanitize(self, value: Any) -> Any:
        """
        清理值，移除可能的注入内容（修复版：只移除注释和特殊字符，不移除关键字）

        Args:
            value: 待清理的值

        Returns:
            清理后的值
        """
        if not self.enabled:
            return value

        if value is None:
            return None

        if not isinstance(value, str):
            return value

        # 移除SQL注释（防止注释绕过）
        value = re.sub(r'--.*$', '', value, flags=re.MULTILINE)
        value = re.sub(r'#.*$', '', value, flags=re.MULTILINE)
        value = re.sub(r'/\*.*?\*/', '', value, flags=re.DOTALL)

        # 移除多余的分号（防止堆叠查询）
        value = value.replace(';;', ';')

        return value.strip()

    def sanitize_sql(self, sql: str) -> str:
        """
        清理SQL语句，移除危险内容

        Args:
            sql: 待清理的SQL

        Returns:
            清理后的SQL
        """
        if not self.enabled:
            return sql

        if sql is None:
            return ''

        if not isinstance(sql, str):
            sql = str(sql)

        # 移除SQL注释
        sql = re.sub(r'--.*$', '', sql, flags=re.MULTILINE)
        sql = re.sub(r'#.*$', '', sql, flags=re.MULTILINE)
        sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)

        # 移除多余分号（防止堆叠查询）
        sql = re.sub(r';+\s*$', ';', sql.strip())

        return sql

    def get_detection_details(self, value: Any) -> Dict[str, Any]:
        """
        获取检测详情

        Args:
            value: 待检测的值

        Returns:
            检测详情字典
        """
        if not self.enabled:
            return {'level': SQLInjectionLevel.NONE, 'patterns': [], 'ast_analysis': 'disabled'}

        if value is None:
            return {'level': SQLInjectionLevel.NONE, 'patterns': [], 'ast_analysis': 'disabled'}

        if not isinstance(value, str):
            value = str(value)

        matched_patterns = []
        max_level = SQLInjectionLevel.NONE

        for pattern in self.INJECTION_PATTERNS:
            match = pattern.pattern.search(value)
            if match:
                matched_patterns.append({
                    'pattern': pattern.pattern.pattern,
                    'description': pattern.description,
                    'level': pattern.level.name,
                    'match': match.group(0)
                })
                if pattern.level.value > max_level.value:
                    max_level = pattern.level

        # AST分析结果
        ast_analysis = 'disabled'
        if self.enable_ast_validation:
            try:
                sqlglot = self._load_sqlglot()
                if sqlglot is not None:
                    parsed = sqlglot.parse_one(value)
                    ast_analysis = 'valid'
                else:
                    ast_analysis = 'sqlglot_not_available'
            except Exception as e:
                ast_analysis = f'parse_error: {str(e)[:50]}'

        return {
            'level': max_level.name,
            'patterns': matched_patterns,
            'is_blocked': max_level.value > self.max_risk_level.value,
            'ast_analysis': ast_analysis
        }

    def validate_sql(self, sql: str) -> Dict[str, Any]:
        """
        完整验证SQL语句（结合正则和AST）

        Args:
            sql: SQL语句

        Returns:
            验证结果
        """
        result = {
            'is_valid': True,
            'errors': [],
            'warnings': [],
            'ast_valid': None
        }

        if self.detect_ddl(sql):
            result['is_valid'] = False
            result['errors'].append('DDL语句被阻止')

        injection_result = self.get_detection_details(sql)
        if injection_result['is_blocked']:
            result['is_valid'] = False
            result['errors'].append(f"SQL注入风险: {injection_result['level']}")

        if injection_result['level'] != SQLInjectionLevel.NONE:
            result['warnings'].append(f"检测到潜在风险: {injection_result['level']}")

        result['ast_valid'] = injection_result.get('ast_analysis', None)

        return result


# 全局默认检测器实例（生产环境严格模式）
DEFAULT_DETECTOR = SQLInjectionDetector(
    enabled=True,
    max_risk_level=SQLInjectionLevel.LOW,
    block_ddl=True,
    allow_raw_params=False
)


def check_sql_injection(value: Any) -> bool:
    """
    便捷函数：检查值是否安全

    Args:
        value: 待检查的值

    Returns:
        是否安全
    """
    return DEFAULT_DETECTOR.is_safe(value)


def sanitize_sql_value(value: Any) -> Any:
    """
    便捷函数：清理SQL值

    Args:
        value: 待清理的值

    Returns:
        清理后的值
    """
    return DEFAULT_DETECTOR.sanitize(value)


def is_ddl_blocked(sql: str) -> bool:
    """
    便捷函数：检查DDL语句是否被阻止

    Args:
        sql: SQL语句

    Returns:
        是否被阻止
    """
    return DEFAULT_DETECTOR.is_ddl_blocked(sql)


def validate_sql(sql: str) -> Dict[str, Any]:
    """
    便捷函数：验证SQL语句

    Args:
        sql: SQL语句

    Returns:
        验证结果
    """
    return DEFAULT_DETECTOR.validate_sql(sql)
