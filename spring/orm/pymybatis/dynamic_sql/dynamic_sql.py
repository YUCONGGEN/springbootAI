"""
PyMyBatis动态SQL处理模块

实现MyBatis风格的动态SQL标签，核心安全特性：
- 严格区分 #{} 预编译占位符 和 ${} 字符串直接拼接
- ${} 默认拦截，仅允许白名单内的表名、字段名等常量
- 所有参数强制使用数据库驱动预编译语句
- 使用AST解析表达式，避免eval()安全漏洞
"""

import re
import ast
import logging
from collections.abc import Mapping, Sequence
from typing import Dict, Any, List, Set, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class SqlParameterType(Enum):
    """SQL参数类型"""
    PREPARED = 'prepared'  # #{} 预编译占位符
    RAW = 'raw'            # ${} 字符串直接拼接


class DynamicSQLProcessor:
    """
    动态SQL处理器

    将包含MyBatis风格标签的SQL模板转换为可执行的SQL语句

    安全特性：
    1. #{param} -> ? 预编译参数，安全
    2. ${param} -> 直接拼接，默认拦截，需配置白名单
    """

    # 参数占位符正则（支持嵌套属性如 #{user.username}）
    PREPARED_PARAM_PATTERN = re.compile(r'#\{([^}]+)\}')
    RAW_PARAM_PATTERN = re.compile(r'\$\{([^}]+)\}')

    def __init__(self, placeholder: str = '%s'):
        """初始化动态SQL处理器

        Args:
            placeholder: 参数占位符，'%s' 用于 MySQL/PostgreSQL，'?' 用于 SQLite/Oracle
        """
        self.tag_handlers = {
            'if': self._handle_if,
            'where': self._handle_where,
            'foreach': self._handle_foreach,
            'choose': self._handle_choose,
            'when': self._handle_when,
            'otherwise': self._handle_otherwise,
            'set': self._handle_set,
            'trim': self._handle_trim,
        }

        # ${}白名单配置
        self.raw_param_whitelist: Set[str] = set()
        self.raw_param_allowed_patterns: List[re.Pattern] = []

        # 启用${}的场景（表名、字段名等）
        self.allow_raw_params = False

        # 参数占位符
        self.placeholder = placeholder

    def set_raw_param_whitelist(self, whitelist: Set[str]) -> None:
        """
        设置${}参数白名单

        Args:
            whitelist: 允许使用${}的参数名集合
        """
        self.raw_param_whitelist = whitelist

    def add_raw_param_pattern(self, pattern: str) -> None:
        """
        添加${}参数允许的正则模式

        Args:
            pattern: 正则表达式模式
        """
        self.raw_param_allowed_patterns.append(re.compile(pattern))

    def enable_raw_params(self, enabled: bool = True) -> None:
        """
        启用/禁用${}参数

        Args:
            enabled: 是否启用
        """
        self.allow_raw_params = enabled

    def _is_raw_param_allowed(self, param_name: str, param_value: Any) -> bool:
        """
        检查${}参数是否允许使用

        Args:
            param_name: 参数名
            param_value: 参数值

        Returns:
            是否允许
        """
        # 检查参数名白名单（优先级最高）
        if param_name in self.raw_param_whitelist:
            return True

        # 如果未启用${}，直接拒绝
        if not self.allow_raw_params:
            return False

        # 检查参数值模式
        if isinstance(param_value, str):
            for pattern in self.raw_param_allowed_patterns:
                if pattern.match(param_value):
                    return True

        # 如果没有配置允许模式，只允许字母数字下划线的参数值（表名、字段名等）
        if not self.raw_param_allowed_patterns:
            if isinstance(param_value, str) and re.fullmatch(
                r'[a-zA-Z_][a-zA-Z0-9_]*', param_value
            ):
                return True

        # 不在白名单且不匹配任何允许模式，拒绝使用
        return False

    def _get_nested_value(self, params: Dict[str, Any], param_name: str) -> Any:
        """
        获取嵌套属性值

        Args:
            params: 参数字典
            param_name: 参数名，支持嵌套如 'user.username'

        Returns:
            参数值

        Raises:
            ValueError: 参数不存在
        """
        if '.' not in param_name:
            if param_name in params:
                return params[param_name]
            raise ValueError(f"参数不存在: {param_name}")
        
        # 处理嵌套属性
        parts = param_name.split('.')
        value = params
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            elif hasattr(value, part):
                value = getattr(value, part)
            else:
                raise ValueError(f"参数不存在: {param_name}")
        return value

    @staticmethod
    def _get_value(value: Any, path: str) -> Any:
        """Resolve a dotted property from a mapping or a regular Python object."""
        for part in path.split('.'):
            if isinstance(value, Mapping):
                if part not in value:
                    raise ValueError(f"参数不存在: {path}")
                value = value[part]
            elif hasattr(value, part):
                value = getattr(value, part)
            else:
                raise ValueError(f"参数不存在: {path}")
        return value

    def _process_prepared_params(
        self,
        sql: str,
        params: Dict[str, Any],
        foreach_values: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        """
        处理#{param}预编译占位符

        Args:
            sql: SQL模板
            params: 参数字典

        Returns:
            (处理后的SQL, 参数列表)
        """
        param_order = []
        foreach_values = foreach_values or {}
        marker_pattern = '|'.join(re.escape(key) for key in foreach_values)
        combined_pattern = re.compile(
            rf'#\{{([^}}]+)\}}|({marker_pattern})' if marker_pattern
            else r'#\{([^}]+)\}'
        )

        def replace_param(match):
            marker = match.group(2) if marker_pattern else None
            if marker:
                param_order.append(foreach_values[marker])
                return self.placeholder
            param_name = match.group(1)
            value = self._get_nested_value(params, param_name)
            param_order.append(value)
            return self.placeholder

        processed_sql = combined_pattern.sub(replace_param, sql)
        return processed_sql, param_order

    def _process_raw_params(self, sql: str, params: Dict[str, Any]) -> str:
        """
        处理${param}字符串拼接

        Args:
            sql: SQL模板
            params: 参数字典

        Returns:
            处理后的SQL

        Raises:
            SecurityError: ${}参数不在白名单中
        """
        def replace_raw(match):
            param_name = match.group(1)
            if param_name not in params:
                raise ValueError(f"参数不存在: {param_name}")

            param_value = params[param_name]

            # 安全检查：${}必须在白名单中
            if not self._is_raw_param_allowed(param_name, param_value):
                raise SecurityError(
                    f"${{{param_name}}} 不在白名单中，禁止使用字符串拼接。"
                    f"允许的参数: {self.raw_param_whitelist}"
                )

            # 对${}参数值进行安全过滤
            return self._sanitize_raw_param(param_value)

        return self.RAW_PARAM_PATTERN.sub(replace_raw, sql)

    def _sanitize_raw_param(self, value: Any) -> str:
        """
        清理${}参数值，防止注入

        Args:
            value: 参数值

        Returns:
            清理后的字符串
        """
        if value is None:
            return ''

        if not isinstance(value, str):
            value = str(value)

        # 移除危险字符（保留单引号用于表名/字段名，由调用方负责安全）
        dangerous_chars = [';', '--', '/*', '*/', '\x00']
        for char in dangerous_chars:
            value = value.replace(char, '')

        # 移除换行符和制表符（防止堆叠查询）
        value = value.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')

        # 移除连续空格
        value = re.sub(r'\s+', ' ', value)

        return value.strip()

    def process(self, sql: str, params: Dict[str, Any]) -> tuple:
        """
        处理动态SQL模板

        Args:
            sql: 包含动态SQL标签的SQL模板
            params: 参数值字典

        Returns:
            (处理后的SQL语句, 参数列表)
        """
        # <bind> must not mutate the caller-owned parameter mapping. This also
        # makes a mapper call safe to reuse in retry and cache paths.
        params = dict(params or {})

        # ``foreach`` markers are bound together with normal ``#{}`` tokens at
        # the end, preserving the exact left-to-right parameter order.
        foreach_values = {}
        foreach_index = 0

        # Process MyBatis <bind/> declarations before structural tags. They
        # only add derived values to the current execution's parameter scope.
        processed_sql = self._process_bind_tags(sql, params)

        # 循环处理直到没有标签
        while True:
            # 查找最内层的标签
            tag_match = re.search(r'<(\w+)([^>]*)>(.*?)</\1>', processed_sql, re.DOTALL)
            if not tag_match:
                break

            tag_name = tag_match.group(1)
            tag_attrs = tag_match.group(2)
            tag_content = tag_match.group(3)

            if tag_name in self.tag_handlers:
                # 处理标签
                result = self.tag_handlers[tag_name](tag_attrs, tag_content, params)
                if isinstance(result, tuple):
                    # foreach返回元组 (sql, params)
                    result_sql, collected_params = result
                    for value in collected_params:
                        marker = f"__PYMB_FOREACH_{foreach_index}__"
                        foreach_index += 1
                        foreach_values[marker] = value
                        result_sql = result_sql.replace(self.placeholder, marker, 1)
                    processed_sql = processed_sql.replace(tag_match.group(0), result_sql)
                else:
                    processed_sql = processed_sql.replace(tag_match.group(0), result)
            else:
                raise ValueError(f"不支持的动态 SQL 标签: <{tag_name}>")

        # 处理${}参数（字符串拼接）
        processed_sql = self._process_raw_params(processed_sql, params)

        # 处理#{}参数（预编译占位符）- 收集非foreach参数
        processed_sql, param_order = self._process_prepared_params(
            processed_sql,
            params,
            foreach_values,
        )

        # 清理多余的空格和逗号
        processed_sql = self._clean_sql(processed_sql)

        logger.debug(f"处理后的SQL: {processed_sql}, 参数: {param_order}")

        return processed_sql, param_order

    def _process_bind_tags(self, sql: str, params: Dict[str, Any]) -> str:
        bind_pattern = re.compile(r'<bind\s+([^>]*?)/\s*>', flags=re.DOTALL)

        def replace_bind(match: re.Match) -> str:
            attrs = self._parse_attributes(match.group(1))
            name = attrs.get('name')
            expression = attrs.get('value')
            if not name or expression is None:
                raise ValueError("<bind> 必须同时设置 name 和 value")
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
                raise ValueError(f"<bind> 参数名无效: {name}")
            params[name] = self._evaluate_value_expression(expression, params)
            return ''

        return bind_pattern.sub(replace_bind, sql)

    def _parse_attributes(self, attrs_str: str) -> Dict[str, str]:
        """
        解析标签属性

        Args:
            attrs_str: 属性字符串

        Returns:
            属性字典
        """
        attrs = {}
        # Keep the quote delimiter paired so a double-quoted attribute can
        # contain the single quotes commonly used by OGNL <bind> expressions.
        pattern = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')')
        for name, double_quoted, single_quoted in pattern.findall(attrs_str):
            attrs[name] = double_quoted if double_quoted != '' else single_quoted
        return attrs

    def _evaluate_expression(self, expression: str, params: Dict[str, Any]) -> bool:
        """
        评估OGNL表达式（使用AST安全解析，避免eval()安全漏洞）

        Args:
            expression: OGNL表达式
            params: 参数值字典

        Returns:
            表达式结果（布尔值）
        """
        try:
            return bool(self._evaluate_value_expression(expression, params))
        except Exception:
            return False

    def _evaluate_value_expression(self, expression: str, params: Dict[str, Any]) -> Any:
        """Evaluate the restricted OGNL subset used by ``<if>`` and ``<bind>``.

        The execution namespace only contains mapper parameters and no Python
        builtins. AST validation is deliberately performed before compilation;
        this is not a general expression evaluator.
        """
        safe_expr = self._translate_ognl_to_python(expression)
        tree = ast.parse(safe_expr, mode='eval')
        self._validate_ast(tree)
        code = compile(tree, '<expression>', 'eval')
        return eval(code, {'__builtins__': {}}, dict(params))

    def _translate_ognl_to_python(self, expression: str) -> str:
        """
        将OGNL表达式转换为安全的Python表达式

        Args:
            expression: OGNL表达式

        Returns:
            安全的Python表达式
        """
        expr = expression.strip()
        
        # 将OGNL的null转换为Python的None
        expr = expr.replace('null', 'None')
        
        # 将OGNL方法调用转换为Python表达式
        # isEmpty(value) -> not value
        expr = re.sub(r'isEmpty\(([^)]+)\)', r'(not (\1))', expr)
        # isNotEmpty(value) -> bool(value)
        expr = re.sub(r'isNotEmpty\(([^)]+)\)', r'bool(\1)', expr)
        
        # 将OGNL操作符转换为Python操作符（使用正则确保只替换独立单词）
        expr = re.sub(r'\beq\b', '==', expr)
        expr = re.sub(r'\bne\b', '!=', expr)
        expr = re.sub(r'\blt\b', '<', expr)
        expr = re.sub(r'\bgt\b', '>', expr)
        expr = re.sub(r'\ble\b', '<=', expr)
        expr = re.sub(r'\bge\b', '>=', expr)
        
        return expr

    def _validate_ast(self, tree: ast.AST) -> None:
        """
        验证AST节点，确保没有危险操作
        
        只允许：
        - 变量访问（参数）
        - 常量（字符串、数字、None）
        - 比较运算符（==, !=, <, >, <=, >=）
        - 逻辑运算符（and, or, not）
        - 属性访问（.）
        - 索引访问（[]）

        Args:
            tree: AST节点

        Raises:
            SecurityError: 如果发现危险操作
        """
        allowed_nodes = (
            ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare,
            ast.Name, ast.Load, ast.Constant, ast.Attribute, ast.Subscript,
            ast.List, ast.Tuple, ast.Dict, ast.And, ast.Or, ast.Not,
            ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In,
            ast.NotIn, ast.Is, ast.IsNot, ast.Add, ast.Sub, ast.Mult,
            ast.Div, ast.FloorDiv, ast.Mod, ast.USub, ast.UAdd, ast.Call,
        )
        for node in ast.walk(tree):
            if not isinstance(node, allowed_nodes):
                raise SecurityError(f"表达式包含不允许的语法: {ast.dump(node)}")
            if isinstance(node, ast.Name) and node.id.startswith('__'):
                raise SecurityError("表达式不能访问 dunder 名称")
            if isinstance(node, ast.Attribute) and node.attr.startswith('__'):
                raise SecurityError("表达式不能访问 dunder 属性")
            # 禁止函数调用（除了内置的bool）
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == 'bool':
                    continue
                raise SecurityError(f"表达式中禁止函数调用: {ast.dump(node)}")
            
            # 禁止导入
            if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
                raise SecurityError(f"表达式中禁止导入: {ast.dump(node)}")
            
            # 禁止赋值
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                raise SecurityError(f"表达式中禁止赋值: {ast.dump(node)}")
            
            # 禁止删除
            if isinstance(node, ast.Delete):
                raise SecurityError(f"表达式中禁止删除操作: {ast.dump(node)}")
            
            # 禁止执行语句
            if isinstance(node, ast.Expr):
                # ast.Exec 在Python 3.8+已移除，Expr用于语句模式，eval模式中不应该出现
                raise SecurityError(f"表达式中禁止执行语句: {ast.dump(node)}")
            
            # 禁止生成器表达式
            if isinstance(node, ast.GeneratorExp):
                raise SecurityError(f"表达式中禁止生成器: {ast.dump(node)}")
            
            # 禁止lambda
            if isinstance(node, ast.Lambda):
                raise SecurityError(f"表达式中禁止lambda: {ast.dump(node)}")
            
            # 禁止切片（防止复杂操作）
            if isinstance(node, ast.Slice):
                raise SecurityError(f"表达式中禁止切片: {ast.dump(node)}")

    def _handle_if(self, attrs: str, content: str, params: Dict[str, Any]) -> str:
        """
        处理<if>标签

        Args:
            attrs: 属性字符串
            content: 标签内容
            params: 参数值字典

        Returns:
            处理后的内容或空字符串
        """
        attrs_dict = self._parse_attributes(attrs)
        test_expr = attrs_dict.get('test', '')

        if self._evaluate_expression(test_expr, params):
            # 保留#{}占位符，由主process方法统一处理
            return content.strip()
        return ''

    def _handle_where(self, attrs: str, content: str, params: Dict[str, Any]) -> str:
        """
        处理<where>标签

        Args:
            attrs: 属性字符串
            content: 标签内容
            params: 参数值字典

        Returns:
            处理后的WHERE子句
        """
        # 处理内容中的标签（保留#{}占位符）
        temp_content = content
        
        # 处理嵌套的if标签
        while True:
            if_match = re.search(r'<if([^>]*)>(.*?)</if>', temp_content, re.DOTALL)
            if not if_match:
                break
            if_attrs = if_match.group(1)
            if_content = if_match.group(2)
            if_result = self._handle_if(if_attrs, if_content, params)
            temp_content = temp_content.replace(if_match.group(0), if_result)

        if not temp_content.strip():
            return ''

        # 移除开头的AND/OR
        temp_content = re.sub(r'^\s*(AND|OR)\s+', '', temp_content.strip(), flags=re.IGNORECASE)

        # 移除结尾的AND/OR
        temp_content = re.sub(r'\s*(AND|OR)\s*$', '', temp_content.strip(), flags=re.IGNORECASE)

        if temp_content:
            return f'WHERE {temp_content}'
        return ''

    def _handle_foreach(self, attrs: str, content: str, params: Dict[str, Any]) -> tuple:
        """
        处理<foreach>标签

        Args:
            attrs: 属性字符串
            content: 标签内容
            params: 参数值字典

        Returns:
            (处理后的内容, 收集的参数值列表)
        """
        attrs_dict = self._parse_attributes(attrs)
        collection = attrs_dict.get('collection', '')
        item = attrs_dict.get('item', 'item')
        index = attrs_dict.get('index', 'index')
        open_tag = attrs_dict.get('open', '')
        close_tag = attrs_dict.get('close', '')
        separator = attrs_dict.get('separator', ',')

        # 获取集合值
        if collection not in params:
            return '', []

        collection_value = params[collection]
        if isinstance(collection_value, Mapping):
            entries = list(collection_value.items())
        elif isinstance(collection_value, Sequence) and not isinstance(collection_value, (str, bytes, bytearray)):
            entries = list(enumerate(collection_value))
        elif isinstance(collection_value, (set, frozenset)):
            entries = list(enumerate(collection_value))
        else:
            raise ValueError(f"foreach collection 必须是序列、集合或映射: {collection}")

        if len(entries) == 0:
            return '', []

        # 检查foreach数量限制（防止全表操作）
        max_foreach_size = 1000
        if len(entries) > max_foreach_size:
            raise SecurityError(
                f"foreach集合大小({len(entries)})超过限制({max_foreach_size})，"
                "请分批处理"
            )

        # 收集参数值
        collected_params = []

        # 生成结果（展开#{}为占位符并收集参数）
        results = []
        for index_value, val in entries:
            iteration_params = {**params, item: val, index: index_value}
            item_content = self._render_foreach_conditions(content, iteration_params)

            def replace_token(match: re.Match) -> str:
                token_type, expression = match.group(1), match.group(2)
                if expression == item:
                    value = val
                    name = item
                elif expression.startswith(item + '.'):
                    value = self._get_value(val, expression[len(item) + 1:])
                    name = item
                elif expression == index:
                    value = index_value
                    name = index
                else:
                    return match.group(0)

                if token_type == '#':
                    collected_params.append(value)
                    return self.placeholder
                if not self._is_raw_param_allowed(name, value):
                    raise SecurityError(f"${{{expression}}} 不在白名单中")
                return self._sanitize_raw_param(value)

            item_content = re.sub(r'([#$])\{([^}]+)\}', replace_token, item_content)
            results.append(item_content.strip())

        return f'{open_tag}{separator.join(results)}{close_tag}', collected_params

    def _render_foreach_conditions(self, content: str, params: Dict[str, Any]) -> str:
        """Resolve conditional tags inside one foreach iteration before binding."""
        rendered = content
        while True:
            if_match = re.search(r'<if([^>]*)>(.*?)</if>', rendered, re.DOTALL)
            if not if_match:
                break
            replacement = self._handle_if(if_match.group(1), if_match.group(2), params)
            rendered = rendered.replace(if_match.group(0), replacement, 1)
        while True:
            choose_match = re.search(r'<choose([^>]*)>(.*?)</choose>', rendered, re.DOTALL)
            if not choose_match:
                break
            replacement = self._handle_choose(
                choose_match.group(1), choose_match.group(2), params
            )
            rendered = rendered.replace(choose_match.group(0), replacement, 1)
        return rendered

    def _handle_choose(self, attrs: str, content: str, params: Dict[str, Any]) -> str:
        """
        处理<choose>标签

        Args:
            attrs: 属性字符串
            content: 标签内容
            params: 参数值字典

        Returns:
            处理后的内容
        """
        # 处理when标签
        when_pattern = re.compile(r'<when([^>]*)>(.*?)</when>', re.DOTALL)
        when_matches = when_pattern.findall(content)

        for when_attrs, when_content in when_matches:
            when_attrs_dict = self._parse_attributes(when_attrs)
            test_expr = when_attrs_dict.get('test', '')

            if self._evaluate_expression(test_expr, params):
                # Leave #{} placeholders for the outer binding pass so the
                # selected branch contributes values in final SQL order.
                return when_content.strip()

        # 处理otherwise标签
        otherwise_pattern = re.compile(r'<otherwise>(.*?)</otherwise>', re.DOTALL)
        otherwise_match = otherwise_pattern.search(content)
        if otherwise_match:
            return otherwise_match.group(1).strip()

        return ''

    def _handle_when(self, attrs: str, content: str, params: Dict[str, Any]) -> str:
        """
        处理<when>标签（由choose标签调用）

        Args:
            attrs: 属性字符串
            content: 标签内容
            params: 参数值字典

        Returns:
            处理后的内容
        """
        return content

    def _handle_otherwise(self, attrs: str, content: str, params: Dict[str, Any]) -> str:
        """
        处理<otherwise>标签（由choose标签调用）

        Args:
            attrs: 属性字符串
            content: 标签内容
            params: 参数值字典

        Returns:
            处理后的内容
        """
        return content

    def _handle_set(self, attrs: str, content: str, params: Dict[str, Any]) -> str:
        """
        处理<set>标签

        Args:
            attrs: 属性字符串
            content: 标签内容
            params: 参数值字典

        Returns:
            处理后的SET子句
        """
        # 处理内容中的标签（不收集参数）
        temp_content = content
        
        # 处理嵌套的if标签
        while True:
            if_match = re.search(r'<if([^>]*)>(.*?)</if>', temp_content, re.DOTALL)
            if not if_match:
                break
            if_attrs = if_match.group(1)
            if_content = if_match.group(2)
            if_result = self._handle_if(if_attrs, if_content, params)
            temp_content = temp_content.replace(if_match.group(0), if_result)
        
        if not temp_content.strip():
            return ''

        # 移除结尾的逗号
        temp_content = re.sub(r',\s*$', '', temp_content.strip())

        if temp_content:
            return f'SET {temp_content}'
        return ''

    def _handle_trim(self, attrs: str, content: str, params: Dict[str, Any]) -> str:
        """
        处理<trim>标签

        Args:
            attrs: 属性字符串
            content: 标签内容
            params: 参数值字典

        Returns:
            处理后的内容
        """
        attrs_dict = self._parse_attributes(attrs)
        prefix = attrs_dict.get('prefix', '')
        suffix = attrs_dict.get('suffix', '')
        prefix_overrides = attrs_dict.get('prefixOverrides', '')
        suffix_overrides = attrs_dict.get('suffixOverrides', '')

        processed_content = content
        # The main loop encounters outer trim before its child if tags. Resolve
        # those conditions here, but leave #{} untouched for ordered binding.
        while True:
            if_match = re.search(r'<if([^>]*)>(.*?)</if>', processed_content, re.DOTALL)
            if not if_match:
                break
            if_result = self._handle_if(
                if_match.group(1), if_match.group(2), params
            )
            processed_content = processed_content.replace(
                if_match.group(0), if_result
            )

        if not processed_content.strip():
            return ''

        # 移除前缀覆盖
        if prefix_overrides:
            for override in prefix_overrides.split('|'):
                token = override.strip()
                if token:
                    processed_content = re.sub(
                        r'^\s*' + re.escape(token) + r'(?=\s|$)',
                        '',
                        processed_content,
                        count=1,
                        flags=re.IGNORECASE,
                    )

        # 移除后缀覆盖
        if suffix_overrides:
            for override in suffix_overrides.split('|'):
                token = override.strip()
                if token:
                    processed_content = re.sub(
                        re.escape(token) + r'\s*$',
                        '',
                        processed_content,
                        count=1,
                        flags=re.IGNORECASE,
                    )

        result = processed_content.strip()
        if prefix:
            prefix = prefix.strip()
            separator = '' if prefix.endswith(('(', '[', '{')) else ' '
            result = f'{prefix}{separator}{result}'
        if suffix:
            suffix = suffix.strip()
            separator = '' if suffix.startswith((')', ']', '}', ',', ';')) else ' '
            result = f'{result}{separator}{suffix}'
        return result

    def _clean_sql(self, sql: str) -> str:
        """
        清理SQL语句

        Args:
            sql: SQL语句

        Returns:
            清理后的SQL语句
        """
        # 移除多余的空格
        sql = re.sub(r'\s+', ' ', sql)

        # 移除多余的逗号
        sql = re.sub(r',\s*,', ',', sql)

        # 移除WHERE/HAVING子句中多余的AND/OR
        sql = re.sub(r'(WHERE|HAVING)\s+(AND|OR)\s+', r'\1 ', sql, flags=re.IGNORECASE)

        # 转义 % 字符以兼容 pymysql 的 % 格式化
        # pymysql 使用 Python % 操作符进行参数绑定，SQL 字面量中的 % 必须转义为 %%
        sql = self._escape_mysql_percent(sql)

        return sql.strip()

    def _escape_mysql_percent(self, sql: str) -> str:
        """将 SQL 字面量中的 % 转义为 %% 以兼容 pymysql 的 % 格式化。

        pymysql cursor.execute() 内部使用 Python 的 % 格式化，
        如果 SQL 中包含字面量 %（如 LIKE '%%keyword%%'、CONCAT('%%', ...)），
        会引发 ValueError。此方法将 #{} 占位符替换生成的 %s 保留不动，
        其他所有 % 替换为 %%。

        Args:
            sql: 处理后的 SQL（已包含 %s 占位符）

        Returns:
            转义后的 SQL
        """
        if self.placeholder != '%s':
            return sql
        # 用唯一标记替换所有 %s 占位符 → 转义剩余 % → 恢复 %s
        marker = '\x00PYM_PH\x00'
        sql = sql.replace('%s', marker)
        sql = sql.replace('%', '%%')
        sql = sql.replace(marker, '%s')
        return sql


class SecurityError(Exception):
    """安全异常"""
    pass


# 全局默认处理器实例
DEFAULT_PROCESSOR = DynamicSQLProcessor()


def process_dynamic_sql(sql: str, params: Dict[str, Any]) -> tuple:
    """
    便捷函数：处理动态SQL

    Args:
        sql: 包含动态SQL标签的SQL模板
        params: 参数值字典

    Returns:
        (处理后的SQL语句, 参数列表)
    """
    return DEFAULT_PROCESSOR.process(sql, params)
