"""
ORM DDL 自动建表/更新 (JPA hibernate.ddl-auto 风格)

支持从 Python 实体类（dataclass / 带类型注解的类）自动生成 DDL 语句，
并根据配置执行建表/更新/验证。

支持的 ddl-auto 模式：
- none: 不做任何操作（默认）
- validate: 验证表结构是否与实体匹配，不匹配时报错
- update: 增量更新表结构（添加新列、新索引）
- create: 每次启动都删除并重新创建表
- create-drop: 启动时创建，关闭时删除（测试用）

支持 MySQL/PostgreSQL/SQLite
"""

import ast
import logging
import inspect
import threading
from typing import Dict, List, Optional, Any, Type, get_type_hints
from dataclasses import is_dataclass, fields as dataclass_fields
from enum import Enum

from springbootai.core.typing_utils import unwrap_optional_type

logger = logging.getLogger("Spring.ORM.DDL")


class DdlAutoMode(Enum):
    NONE = "none"
    VALIDATE = "validate"
    UPDATE = "update"
    CREATE = "create"
    CREATE_DROP = "create-drop"


# 类型映射: Python type -> (MySQL type, PostgreSQL type, SQLite type)
_TYPE_MAP = {
    int:        ("BIGINT",      "BIGINT",       "INTEGER"),
    str:        ("VARCHAR(255)", "VARCHAR(255)", "TEXT"),
    float:      ("DOUBLE",      "DOUBLE PRECISION", "REAL"),
    bool:       ("TINYINT(1)",  "BOOLEAN",      "INTEGER"),
    bytes:      ("BLOB",        "BYTEA",        "BLOB"),
}


def _get_sql_type(py_type: Any, dialect: str, column_info: dict = None) -> str:
    """将Python类型映射到SQL类型"""
    column_info = column_info or {}
    # 自定义长度
    length = column_info.get('length')
    if py_type is str and length:
        if dialect == 'mysql':
            return f"VARCHAR({length})"
        elif dialect == 'postgresql':
            return f"VARCHAR({length})"
        else:
            return "TEXT"
    # 显式指定 columnDefinition
    col_def = column_info.get('column_definition')
    if col_def:
        return col_def
    mapped = _TYPE_MAP.get(py_type)
    if mapped:
        if dialect == 'mysql':
            return mapped[0]
        elif dialect == 'postgresql':
            return mapped[1]
        else:
            return mapped[2]
    # datetime / date
    type_name = getattr(py_type, '__name__', str(py_type))
    if 'datetime' in type_name.lower() or 'date' in type_name.lower():
        if dialect == 'mysql':
            return "DATETIME"
        elif dialect == 'postgresql':
            return "TIMESTAMP"
        else:
            return "TEXT"
    if 'decimal' in type_name.lower():
        precision = column_info.get('precision', 10)
        scale = column_info.get('scale', 2)
        if dialect in ('mysql', 'postgresql'):
            return f"DECIMAL({precision},{scale})"
        return "REAL"
    # 默认：TEXT
    return "TEXT" if dialect == 'sqlite' else ("VARCHAR(255)" if dialect in ('mysql', 'postgresql') else "TEXT")


class Column:
    """列定义注解/描述符。

    支持组合式字段级注解：通过 ``constraints`` 参数内联挂载 Bean Validation
    约束列表（``NotNull`` / ``NotBlank`` / ``Size`` 等），使同一字段同时具备
    ORM 列定义 + 参数校验能力，无需额外的 Constraint 描述符（与类属性单值性兼容）。

    用法::

        class User:
            name = Column("name", default="", nullable=False,
                          constraints=[NotBlank(message="姓名不能为空"),
                                       Size(max=50, message="姓名不超过 50 字")])
            age  = Column("age", default=0,
                          constraints=[Min(0, message="年龄不能为负"), Max(150)])
    """
    def __init__(self, name: str = "", nullable: bool = True, unique: bool = False,
                 length: int = 0, primary_key: bool = False, auto_increment: bool = False,
                 default: Any = None, column_definition: str = "", comment: str = "",
                 precision: int = 0, scale: int = 0, constraints: list = None):
        self.name = name
        self.nullable = nullable
        self.unique = unique
        self.length = length
        self.primary_key = primary_key
        self.auto_increment = auto_increment
        self.default = default
        self.column_definition = column_definition
        self.comment = comment
        self.precision = precision
        self.scale = scale
        # Bean Validation 约束列表（组合式注解通道）
        self.constraints = constraints or []


class Required(Column):
    """Concise Column variant for mandatory entity fields.

    Required(length=80, default="value") is equivalent to
    Column(nullable=False, length=80, default="value"). It keeps the
    database constraint visible without repeating nullable=False throughout
    domain entities.
    """

    def __init__(self, name: str = "", **kwargs):
        kwargs.pop("nullable", None)
        super().__init__(name=name, nullable=False, **kwargs)


class Text(Column):
    """TEXT column with an optional domain-level required flag.

    Use Text() for optional long content and Text(required=True) for
    mandatory long content. The helper preserves normal Column options,
    including default and comment.
    """

    def __init__(self, name: str = "", required: bool = False, **kwargs):
        kwargs.setdefault("column_definition", "TEXT")
        if required:
            kwargs["nullable"] = False
        else:
            kwargs.setdefault("nullable", True)
        super().__init__(name=name, **kwargs)

class Id(Column):
    """主键列"""
    def __init__(self, name: str = "", auto_increment: bool = True, **kwargs):
        kwargs.pop('primary_key', None)
        super().__init__(name=name, primary_key=True, auto_increment=auto_increment,
                         nullable=False, **kwargs)


class Version(Column):
    """``@Version`` 乐观锁字段（对齐 JPA ``javax.persistence.Version``）。

    标记该字段为乐观锁版本号：DDL 生成 ``INTEGER NOT NULL DEFAULT 0``；
    更新时配合 ``OptimisticLockExecutor`` 在 WHERE 子句追加 ``version = ?`` 并自增。

    用法（两种形式，与 ``Column``/``Id`` 一致）::

        @entity("sys_user")
        class User:
            id = Id()
            version = Version()           # 类属性描述符形式
            def __init__(self, id=None, version=0): ...

        # 或函数装饰器形式
        @version_column()
        def version(self): ...

    与 JPA 的差异（已标注）：
    - JPA/Hibernate 由 ORM 自动在 UPDATE 时追加 version 检查并自增；
      本框架内嵌 PyMyBatis 不自动注入 version 子句，需通过 ``OptimisticLockExecutor``
      显式执行乐观锁更新（见本文件末尾），或在 XML/注解 SQL 中手写 version 条件。
    """
    def __init__(self, name: str = "", **kwargs):
        kwargs.pop('primary_key', None)
        kwargs.pop('auto_increment', None)
        # 版本字段非空、默认 0
        kwargs.setdefault('nullable', False)
        kwargs.setdefault('default', 0)
        super().__init__(name=name, primary_key=False, auto_increment=False, **kwargs)
        # 版本标记，供 _build_column_meta 识别
        self.version = True


class CreateTime(Column):
    """``@CreateTime`` 自动填充创建时间（对齐 JPA/Hibernate ``@CreationTimestamp``）。

    标记该字段为创建时间：DDL 生成 ``DATETIME DEFAULT CURRENT_TIMESTAMP``（SQLite 为
    ``DEFAULT (datetime('now','localtime'))``）；配合 ``AuditTimeExecutor.fill_on_insert``
    在 INSERT 前自动写入当前时间。

    用法（与 ``Column``/``Id``/``Version`` 一致的两种形式）::

        @entity("sys_user")
        class User:
            id = Id()
            created_at = CreateTime()        # 类属性描述符形式
            def __init__(self, id=None, created_at=None): ...

        # 或函数装饰器形式
        @create_time_column()
        def created_at(self): ...

    说明：``@CreateTime`` 仅在插入时填充；``@UpdateTime`` 在插入与更新时都会刷新。
    """
    def __init__(self, name: str = "", **kwargs):
        kwargs.pop('primary_key', None)
        kwargs.pop('auto_increment', None)
        # 创建时间非空
        kwargs.setdefault('nullable', False)
        super().__init__(name=name, primary_key=False, auto_increment=False, **kwargs)
        # 标记，供 _build_column_meta 识别
        self.create_time = True


class UpdateTime(Column):
    """``@UpdateTime`` 自动填充更新时间（对齐 JPA/Hibernate ``@UpdateTimestamp``）。

    标记该字段为更新时间：DDL 生成 ``DATETIME DEFAULT CURRENT_TIMESTAMP``（SQLite 为
    ``DEFAULT (datetime('now','localtime'))``）；配合 ``AuditTimeExecutor`` 在 INSERT 和
    UPDATE 时都刷新为当前时间。

    用法（两种形式，与 ``CreateTime`` 一致）::

        @entity("sys_user")
        class User:
            id = Id()
            updated_at = UpdateTime()        # 类属性描述符形式
            def __init__(self, id=None, updated_at=None): ...

        # 或函数装饰器形式
        @update_time_column()
        def updated_at(self): ...
    """
    def __init__(self, name: str = "", **kwargs):
        kwargs.pop('primary_key', None)
        kwargs.pop('auto_increment', None)
        # 更新时间非空
        kwargs.setdefault('nullable', False)
        super().__init__(name=name, primary_key=False, auto_increment=False, **kwargs)
        # 标记，供 _build_column_meta 识别
        self.update_time = True


class Transient:
    """``@Transient`` 瞬态字段标记（对齐 JPA ``javax.persistence.Transient``）。

    标记该字段**不持久化**：DDL 自动建表与实体解析均跳过该字段。

    用法（两种形式，与 ``ExcelIgnore`` 一致）::

        @entity("sys_user")
        class User:
            id = Id()
            display_name = Transient()    # 类属性描述符形式：不落库
            def __init__(self, id=None, display_name=None): ...

        # 或函数装饰器形式
        @transient_field()
        def display_name(self): ...

    实现为独立标记类（非 ``Column`` 子类），因为瞬态字段根本不是列。
    """
    def __init__(self, default: Any = None):
        self.default = default
        self.attr_name: str = ""

    def __set_name__(self, owner: type, name: str) -> None:
        """类属性描述符形式时，Python 自动回填字段名（镜像 ``ExcelIgnore``）。"""
        self.attr_name = name

    def __call__(self, target):
        """函数装饰器形式：``@Transient()``，把 ``__transient__`` 标记挂到目标。"""
        setattr(target, '__transient__', True)
        self.attr_name = getattr(target, '__name__', '')
        return target


class Table:
    """``@Table`` 表注解（对齐 JPA ``javax.persistence.Table``）。

    既可作为元数据类使用（内部 ``EntityTable`` 解析），也可直接作为类装饰器使用。
    作为装饰器时等价于 JPA 的 ``@Table``，与 ``@Entity`` 组合使用::

        @Entity
        @Table(name="sys_user", indexes=[Index("idx_name", ["name"])], comment="用户表")
        class User:
            id: int = Id()
            name: str = Column(length=50)

    也可单独使用（隐含 ``@Entity`` 语义，与 ``@Entity("sys_user")`` 等价）::

        @Table(name="sys_user", comment="用户表")
        class User:
            id: int = Id()
    """
    def __init__(self, name: str = "", indexes: List['Index'] = None, comment: str = ""):
        self.name = name
        self.indexes = indexes or []
        self.comment = comment

    def __call__(self, cls):
        """装饰器形式：将表元数据挂载到类上并标记为实体，返回类本身。

        装饰器应用顺序（Python 底向上）::

            @Entity          # 外层，后执行
            @Table(...)      # 内层，先执行
            class User: ...

        ``@Table`` 先设置 ``__table__`` 与 ``__entity__``，随后 ``@Entity``
        检测到已有 ``__table__`` 则不覆盖。
        """
        if not self.name:
            self.name = _camel_to_snake(cls.__name__)
        setattr(cls, '__table__', self)
        setattr(cls, '__entity__', True)
        _auto_generate_init(cls)
        return cls


class Index:
    """索引定义"""
    def __init__(self, name: str, columns: List[str], unique: bool = False):
        self.name = name
        self.columns = columns
        self.unique = unique


def column(**kwargs):
    """字段列装饰器/描述符，用于标注实体字段"""
    col = Column(**kwargs)
    def decorator(f):
        setattr(f, '__column__', col)
        return f
    if len(kwargs) == 1 and 'name' in kwargs and callable(kwargs.get('name')):
        # used as @column without parens
        f = kwargs['name']
        setattr(f, '__column__', Column())
        return f
    return decorator


def id_column(auto_increment: bool = True, **kwargs):
    """主键列装饰器"""
    col = Id(auto_increment=auto_increment, **kwargs)
    def decorator(f):
        setattr(f, '__column__', col)
        return f
    return decorator


def version_column(**kwargs):
    """``@Version`` 函数装饰器形式（镜像 ``column()`` / ``id_column()``）。

    用法::

        @entity("sys_user")
        class User:
            id = Id()
            @version_column()
            def version(self): ...
    """
    col = Version(**kwargs)
    def decorator(f):
        setattr(f, '__column__', col)
        return f
    return decorator


def create_time_column(**kwargs):
    """``@CreateTime`` 函数装饰器形式（镜像 ``column()`` / ``version_column()``）。

    用法::

        @entity("sys_user")
        class User:
            id = Id()
            @create_time_column()
            def created_at(self): ...
    """
    col = CreateTime(**kwargs)
    def decorator(f):
        setattr(f, '__column__', col)
        return f
    return decorator


def update_time_column(**kwargs):
    """``@UpdateTime`` 函数装饰器形式（镜像 ``column()`` / ``version_column()``）。

    用法::

        @entity("sys_user")
        class User:
            id = Id()
            @update_time_column()
            def updated_at(self): ...
    """
    col = UpdateTime(**kwargs)
    def decorator(f):
        setattr(f, '__column__', col)
        return f
    return decorator


def transient_field():
    """``@Transient`` 函数装饰器形式（镜像 ``ExcelIgnore.__call__``）。

    用法::

        @entity("sys_user")
        class User:
            id = Id()
            @transient_field()
            def display_name(self): ...
    """
    def decorator(f):
        setattr(f, '__transient__', True)
        return f
    return decorator


def _camel_to_snake(name: str) -> str:
    """驼峰转下划线"""
    import re
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


def _is_transient_field(cls: Type, attr_name: str) -> bool:
    """检查字段是否标记为 ``@Transient``（对齐 Excel ``_has_explicit_properties`` 反射范式）。

    判定规则（取 MRO 中最近声明）：
      1. 类属性为 ``Transient`` 实例（描述符形式）。
      2. 类属性带 ``__transient__`` 标记（``@transient_field()`` 函数装饰器形式）。
    """
    for cls_base in cls.__mro__:
        if attr_name in cls_base.__dict__:
            cval = cls_base.__dict__[attr_name]
            if isinstance(cval, Transient):
                return True
            if getattr(cval, '__transient__', False) is True:
                return True
            return False  # 最近声明非瞬态，子类覆盖
    return False


class EntityTable:
    """从实体类解析出的表元数据"""
    __slots__ = ('table_name', 'columns', 'indexes', 'comment', 'entity_class')

    def __init__(self, table_name: str, columns: List[dict], indexes: List[Index],
                 comment: str, entity_class: type):
        self.table_name = table_name
        self.columns = columns
        self.indexes = indexes
        self.comment = comment
        self.entity_class = entity_class


class DdlAutoManager:
    """
    DDL 自动管理器

    Usage:
        ddl = DdlAutoManager(connection_pool, dialect="mysql", mode="update")
        ddl.register_entity(User)
        ddl.register_entity(Order)
        ddl.execute()  # 根据mode执行
    """

    def __init__(self, connection_pool, dialect: str = "mysql",
                 mode: str = "none", entity_packages: List[str] = None):
        self.pool = connection_pool
        self.dialect = dialect.lower()
        try:
            self.mode = DdlAutoMode(mode.lower())
        except ValueError:
            logger.warning(f"Unknown ddl-auto mode: {mode}, using 'none'")
            self.mode = DdlAutoMode.NONE
        self._entities: List[Type] = []
        self._parsed: List[EntityTable] = []
        self._executed_sql: List[str] = []
        self._lock = threading.Lock()
        if entity_packages:
            self._scan_packages(entity_packages)

    def register_entity(self, entity_class: Type):
        """注册实体类"""
        if entity_class not in self._entities:
            self._entities.append(entity_class)

    def register_entities(self, entity_classes: List[Type]):
        """批量注册实体类"""
        for cls in entity_classes:
            self.register_entity(cls)

    def _scan_packages(self, packages: List[str]):
        """扫描包下所有实体类（简单实现：要求实体类使用@entity/@Table装饰器或继承基类）"""
        import importlib
        import pkgutil
        for pkg_name in packages:
            try:
                pkg = importlib.import_module(pkg_name)
                for importer, modname, ispkg in pkgutil.walk_packages(pkg.__path__, pkg_name + '.'):
                    try:
                        mod = importlib.import_module(modname)
                        for name, obj in inspect.getmembers(mod, inspect.isclass):
                            # 支持 @entity 装饰器标记
                            is_entity = getattr(obj, '__entity__', False)
                            has_table = hasattr(obj, '__table__')
                            has_tablename = hasattr(obj, '__tablename__') and not name.startswith('_')
                            if (is_entity or has_table or has_tablename) and obj.__module__ == modname:
                                self.register_entity(obj)
                    except Exception as e:
                        logger.debug(f"Failed to scan module {modname}: {e}")
            except Exception as e:
                logger.warning(f"Failed to scan package {pkg_name}: {e}")

    def _parse_entity(self, cls: Type) -> EntityTable:
        """解析实体类，提取表元数据"""
        # 表名
        table_meta = getattr(cls, '__table__', None)
        table_name = ""
        table_comment = ""
        indexes = []
        if isinstance(table_meta, Table):
            table_name = table_meta.name
            table_comment = table_meta.comment
            indexes = list(table_meta.indexes)
        if not table_name:
            table_name = getattr(cls, '__tablename__', "")
        if not table_name:
            table_name = _camel_to_snake(cls.__name__)

        columns = []

        # 处理 dataclass
        if is_dataclass(cls):
            for df in dataclass_fields(cls):
                # @Transient 字段不持久化，跳过（与普通类分支一致）
                if _is_transient_field(cls, df.name):
                    continue
                # dataclass 字段默认值若直接是 Transient 实例，也跳过
                if isinstance(df.default, Transient):
                    continue
                col_meta = self._get_field_meta(df)
                columns.append(col_meta)
        else:
            # 普通实体同时支持显式 self.xxx 赋值、类型注解和类级 Column 描述符。
            # 只依赖源码中的 self.xxx 会漏掉循环赋值或动态赋值的实体。
            init_fields = self._extract_init_fields(cls)
            init_hints = {}
            try:
                init_hints = get_type_hints(cls.__init__)
            except Exception:
                pass
            try:
                cls_annotations = get_type_hints(cls)
            except Exception:
                cls_annotations = getattr(cls, '__annotations__', {})

            descriptor_fields = {}
            for cls_base in reversed(cls.__mro__):
                for attr_name, value in cls_base.__dict__.items():
                    if isinstance(value, (Column, Transient)) or hasattr(value, '__column__'):
                        descriptor_fields[attr_name] = value

            field_names = dict(init_fields)
            for attr_name in cls_annotations:
                field_names.setdefault(attr_name, None)
            for attr_name in descriptor_fields:
                field_names.setdefault(attr_name, None)

            for attr_name, default_val in field_names.items():
                # @Transient 字段不持久化，跳过
                if _is_transient_field(cls, attr_name):
                    continue
                # 私有字段（以 _ 开头）不持久化，跳过
                if attr_name.startswith('_'):
                    continue
                py_type = init_hints.get(attr_name) or cls_annotations.get(attr_name)
                # 解包 Optional[X]：Python 3.10 的 get_type_hints 会把带 None 默认值的
                # 参数注解自动包装为 Optional[X]，3.11+ 不再包装。此处统一解包为承载类型，
                # 否则 _get_sql_type 在 3.10 上识别失败回退到 TEXT，导致数值列被当字符串存储。
                py_type = unwrap_optional_type(py_type)
                descriptor = descriptor_fields.get(attr_name)
                if py_type is None and isinstance(descriptor, Id):
                    py_type = int
                elif py_type is None and isinstance(descriptor, (CreateTime, UpdateTime)):
                    py_type = str
                elif py_type is None and isinstance(descriptor, Column) \
                        and descriptor.default is not None:
                    py_type = type(descriptor.default)
                if py_type is None:
                    py_type = type(default_val) if default_val is not None and default_val != "" else str
                col_info = descriptor
                if not isinstance(col_info, Column) and hasattr(col_info, '__column__'):
                    col_info = getattr(col_info, '__column__')
                col_meta = self._build_column_meta(attr_name, py_type, col_info)
                columns.append(col_meta)

        # 检查是否已有主键标记，没有的话检查id字段并标记为PK
        has_pk = any(c['primary_key'] for c in columns)
        id_col = None
        for c in columns:
            if c['py_name'] == 'id' or c['name'] == 'id':
                id_col = c
                break
        
        if not has_pk and id_col is not None:
            # 将现有id字段标记为主键和自增
            id_col['primary_key'] = True
            id_col['auto_increment'] = True
            id_col['nullable'] = False
            if self.dialect == 'sqlite':
                id_col['sql_type'] = 'INTEGER'
            elif self.dialect == 'mysql':
                id_col['sql_type'] = _get_sql_type(int, self.dialect)
            elif self.dialect == 'postgresql':
                id_col['sql_type'] = 'BIGSERIAL' if 'BIGINT' in id_col['sql_type'] else 'SERIAL'
        elif not has_pk:
            # 没有id字段，自动添加id主键
            pk_col = {
                'name': 'id',
                'py_name': 'id',
                'py_type': int,
                'sql_type': _get_sql_type(int, self.dialect),
                'nullable': False,
                'unique': False,
                'primary_key': True,
                'auto_increment': True,
                'default': None,
                'comment': 'Primary key',
            }
            if self.dialect == 'sqlite':
                pk_col['sql_type'] = 'INTEGER'
            columns.insert(0, pk_col)

        return EntityTable(table_name, columns, indexes, table_comment, cls)

    def _extract_init_fields(self, cls: Type) -> Dict[str, Any]:
        """从__init__方法中提取 self.xxx[: type] = default 字段"""
        import textwrap
        fields = {}
        try:
            source = inspect.getsource(cls.__init__)
            source = textwrap.dedent(source)
            import re
            # 支持类型注解：self.xxx: type = value 或 self.xxx = value
            for match in re.finditer(r'self\.(\w+)(?::\s*[\w\[\], .]+)?\s*=\s*([^\n#]+)', source):
                fname = match.group(1)
                val_expr = match.group(2).strip()
                if fname.startswith('_'):
                    continue
                val_expr = val_expr.rstrip(',').strip()
                # 推断默认值
                default = None
                if val_expr in ('None',):
                    default = None
                elif val_expr in ('""', "''", '""""""', "''''''"):
                    default = ""
                elif val_expr in ('[]', 'list()'):
                    default = []
                elif val_expr in ('{}', 'dict()'):
                    default = {}
                elif val_expr == '0':
                    default = 0
                elif val_expr in ('0.0', '0.'):
                    default = 0.0
                elif val_expr == 'False':
                    default = False
                elif val_expr == 'True':
                    default = True
                else:
                    # self.param = param 模式 (参数赋值)
                    param_match = re.match(r'^(\w+)$', val_expr)
                    if param_match and param_match.group(1) == fname:
                        default = None
                    else:
                        try:
                            default = ast.literal_eval(val_expr)
                        except (ValueError, SyntaxError):
                            default = None
                fields[fname] = default if default is not None else ""
        except Exception:
            pass
        return fields

    def _get_field_meta(self, df) -> dict:
        """从dataclass字段提取列元数据"""
        col_info = getattr(df.default, '__column__', None) if df.default is not inspect.Parameter.empty else None
        if col_info is None and isinstance(df.default, Column):
            col_info = df.default
        return self._build_column_meta(df.name, df.type, col_info)

    def _build_column_meta(self, attr_name: str, py_type: Any, col_info: Optional[Column]) -> dict:
        """构建列元数据字典"""
        info = {
            'name': attr_name,
            'py_name': attr_name,
            'py_type': py_type,
            'nullable': True,
            'unique': False,
            'primary_key': False,
            'auto_increment': False,
            'default': None,
            'comment': '',
            'length': 0,
            'precision': 0,
            'scale': 0,
            'column_definition': '',
            'version': False,      # @Version 乐观锁标记
            'create_time': False,  # @CreateTime 创建时间标记
            'update_time': False,  # @UpdateTime 更新时间标记
        }
        if col_info and isinstance(col_info, Column):
            if col_info.name:
                info['name'] = col_info.name
            else:
                info['name'] = _camel_to_snake(attr_name)
            info['nullable'] = col_info.nullable
            info['unique'] = col_info.unique
            info['primary_key'] = col_info.primary_key
            info['auto_increment'] = col_info.auto_increment
            info['default'] = col_info.default
            info['comment'] = col_info.comment
            info['length'] = col_info.length
            info['precision'] = col_info.precision
            info['scale'] = col_info.scale
            info['column_definition'] = col_info.column_definition
            # @Version 乐观锁字段：标记并强制 INTEGER 类型 + 默认 0
            if isinstance(col_info, Version) or getattr(col_info, 'version', False):
                info['version'] = True
                info['nullable'] = False
                if info['default'] is None:
                    info['default'] = 0
                # 版本号统一用整型（与 JPA Version 语义一致）
                if self.dialect == 'sqlite':
                    info['sql_type'] = 'INTEGER'
                else:
                    info['sql_type'] = 'INTEGER'
                return info
            # @CreateTime 创建时间字段：标记并强制日期时间类型 + 非空
            if isinstance(col_info, CreateTime) or getattr(col_info, 'create_time', False):
                info['create_time'] = True
                info['nullable'] = False
                info['sql_type'] = self._datetime_sql_type()
                return info
            # @UpdateTime 更新时间字段：标记并强制日期时间类型 + 非空
            if isinstance(col_info, UpdateTime) or getattr(col_info, 'update_time', False):
                info['update_time'] = True
                info['nullable'] = False
                info['sql_type'] = self._datetime_sql_type()
                return info
        else:
            info['name'] = _camel_to_snake(attr_name)

        info['sql_type'] = _get_sql_type(py_type, self.dialect, info)
        return info

    def _datetime_sql_type(self) -> str:
        """``@CreateTime``/``@UpdateTime`` 字段在各方言下的日期时间 SQL 类型。"""
        if self.dialect == 'mysql':
            return 'DATETIME'
        elif self.dialect == 'postgresql':
            return 'TIMESTAMP'
        return 'TEXT'  # sqlite 无真正的日期时间类型，用 TEXT 存储

    def _quote(self, identifier: str) -> str:
        """引用标识符（表名/列名）"""
        if self.dialect == 'mysql':
            return f"`{str(identifier).replace('`', '``')}`"
        return f'"{str(identifier).replace(chr(34), chr(34) * 2)}"'

    def _build_create_table_sql(self, et: EntityTable) -> str:
        """生成 CREATE TABLE 语句"""
        cols_sql = []
        primary_keys = []
        unique_cols = []

        for col in et.columns:
            parts = [self._quote(col['name'])]
            sql_type = col['sql_type']
            is_pk = col['primary_key']
            is_auto = col['auto_increment']

            # SQLite: AUTOINCREMENT must be "INTEGER PRIMARY KEY AUTOINCREMENT" inline
            if self.dialect == 'sqlite' and is_pk and is_auto:
                parts = [self._quote(col['name']), "INTEGER", "PRIMARY KEY", "AUTOINCREMENT"]
                primary_keys.append(col['name'])
            else:
                parts = [self._quote(col['name']), sql_type]
                if is_pk:
                    if is_auto:
                        if self.dialect == 'mysql':
                            parts.append("AUTO_INCREMENT")
                        elif self.dialect == 'postgresql':
                            if 'BIGINT' in sql_type:
                                parts[1] = "BIGSERIAL"
                            elif 'INT' in sql_type:
                                parts[1] = "SERIAL"
                    parts.append("NOT NULL")
                    primary_keys.append(col['name'])
                else:
                    if not col['nullable']:
                        parts.append("NOT NULL")
                    if col['unique']:
                        unique_cols.append(col['name'])
                    if col.get('create_time') or col.get('update_time'):
                        # 自动时间字段：由数据库默认值兜底，ORM 未填充时仍能写入当前时间
                        if self.dialect == 'sqlite':
                            parts.append("DEFAULT (datetime('now', 'localtime'))")
                        else:
                            parts.append("DEFAULT CURRENT_TIMESTAMP")
                    elif col['default'] is not None:
                        if isinstance(col['default'], str):
                            parts.append(f"DEFAULT '{col['default']}'")
                        elif isinstance(col['default'], bool):
                            parts.append(f"DEFAULT {1 if col['default'] else 0}")
                        else:
                            parts.append(f"DEFAULT {col['default']}")
            cols_sql.append(" ".join(parts))

        # 对于非SQLite或复合主键，显式声明PRIMARY KEY
        if primary_keys and not (self.dialect == 'sqlite' and len(primary_keys) == 1
                                  and any(c['auto_increment'] for c in et.columns if c['name'] == primary_keys[0])):
            cols_sql.append(f"PRIMARY KEY ({', '.join(self._quote(c) for c in primary_keys)})")
        for uc in unique_cols:
            cols_sql.append(f"UNIQUE ({self._quote(uc)})")

        # 索引（MySQL不能在CREATE TABLE中声明INDEX，单独CREATE INDEX）
        table_sql = f"CREATE TABLE {self._quote(et.table_name)} (\n  "
        table_sql += ",\n  ".join(cols_sql)
        table_sql += "\n)"

        if self.dialect == 'mysql':
            table_sql += " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
            if et.comment:
                table_sql += f" COMMENT='{et.comment}'"
        elif self.dialect == 'postgresql' and et.comment:
            table_sql += f"; COMMENT ON TABLE {self._quote(et.table_name)} IS '{et.comment}'"

        return table_sql

    def _get_existing_columns(self, table_name: str) -> Dict[str, dict]:
        """查询现有表的列信息"""
        conn = None
        columns = {}
        try:
            pooled = self.pool.get_connection()
            conn = pooled.connection
            cursor = conn.cursor()
            if self.dialect == 'mysql':
                cursor.execute(f"SHOW COLUMNS FROM {self._quote(table_name)}")
                for row in cursor.fetchall():
                    col_name = row[0] if not isinstance(row, dict) else row['Field']
                    col_type = row[1] if not isinstance(row, dict) else row['Type']
                    is_null = (row[2] == 'YES') if not isinstance(row, dict) else (row['Null'] == 'YES')
                    is_pk = False
                    key = row[3] if not isinstance(row, dict) else row.get('Key', '')
                    if key == 'PRI':
                        is_pk = True
                    columns[col_name] = {
                        'name': col_name, 'type': col_type, 'nullable': is_null, 'primary_key': is_pk
                    }
            elif self.dialect == 'postgresql':
                cursor.execute("""
                    SELECT column_name, data_type, is_nullable, 
                           (SELECT COUNT(*) FROM information_schema.table_constraints tc
                            JOIN information_schema.key_column_usage kcu 
                              ON tc.constraint_name = kcu.constraint_name
                            WHERE tc.table_name = %s AND tc.constraint_type = 'PRIMARY KEY'
                              AND kcu.column_name = columns.column_name) > 0 as is_pk
                    FROM information_schema.columns 
                    WHERE table_name = %s
                """, (table_name, table_name))
                for row in cursor.fetchall():
                    col_name, col_type, is_null, is_pk = row[0], row[1], row[2] == 'YES', row[3]
                    columns[col_name] = {'name': col_name, 'type': col_type, 'nullable': is_null, 'primary_key': is_pk}
            elif self.dialect == 'sqlite':
                cursor.execute(f"PRAGMA table_info({self._quote(table_name)})")
                for row in cursor.fetchall():
                    col_name = row[1]
                    col_type = row[2]
                    # SQLite PRAGMA table_info: row[3] = notnull (1=NOT NULL, 0=nullable)
                    # row[5] = pk (1=primary key)
                    is_pk = bool(row[5])
                    notnull = bool(row[3]) or is_pk  # 主键隐式为NOT NULL
                    is_null = not notnull
                    columns[col_name] = {'name': col_name, 'type': col_type, 'nullable': is_null, 'primary_key': is_pk}
            cursor.close()
            self.pool.return_connection(pooled)
        except Exception as e:
            logger.debug(f"Failed to get columns for {table_name}: {e}")
        return columns

    def _table_exists(self, table_name: str) -> bool:
        """检查表是否存在"""
        conn = None
        try:
            pooled = self.pool.get_connection()
            conn = pooled.connection
            cursor = conn.cursor()
            if self.dialect == 'mysql':
                cursor.execute("SHOW TABLES LIKE %s", (table_name,))
            elif self.dialect == 'postgresql':
                cursor.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = %s)", (table_name,))
            else:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            exists = cursor.fetchone() is not None
            cursor.close()
            self.pool.return_connection(pooled)
            return exists
        except Exception:
            return False

    def _get_existing_indexes(self, table_name: str) -> Dict[str, List[str]]:
        """查询现有表的索引"""
        indexes = {}
        conn = None
        try:
            pooled = self.pool.get_connection()
            conn = pooled.connection
            cursor = conn.cursor()
            if self.dialect == 'mysql':
                cursor.execute(f"SHOW INDEX FROM {self._quote(table_name)}")
                for row in cursor.fetchall():
                    idx_name = row[2] if not isinstance(row, dict) else row['Key_name']
                    col_name = row[4] if not isinstance(row, dict) else row['Column_name']
                    if idx_name == 'PRIMARY':
                        continue
                    if idx_name not in indexes:
                        indexes[idx_name] = []
                    indexes[idx_name].append(col_name)
            elif self.dialect == 'sqlite':
                cursor.execute(f"PRAGMA index_list({self._quote(table_name)})")
                for row in cursor.fetchall():
                    idx_name = row[1]
                    if idx_name.startswith('sqlite_'):
                        continue
                    cursor2 = conn.cursor()
                    cursor2.execute(f"PRAGMA index_info({self._quote(idx_name)})")
                    cols = [r[2] for r in cursor2.fetchall()]
                    cursor2.close()
                    indexes[idx_name] = cols
            cursor.close()
            self.pool.return_connection(pooled)
        except Exception as e:
            logger.debug(f"Failed to get indexes for {table_name}: {e}")
        return indexes

    def _execute_sql(self, sql: str):
        """执行单条SQL"""
        conn = None
        try:
            pooled = self.pool.get_connection()
            conn = pooled.connection
            cursor = conn.cursor()
            logger.debug(f"[DDL] Executing: {sql[:200]}")
            cursor.execute(sql)
            conn.commit()
            cursor.close()
            self.pool.return_connection(pooled)
            self._executed_sql.append(sql)
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.error(f"[DDL] SQL execution failed: {e}\nSQL: {sql[:300]}")
            raise

    def execute(self) -> List[str]:
        """根据 ddl-auto 模式执行 DDL 操作"""
        if self.mode == DdlAutoMode.NONE:
            logger.info("[DDL] ddl-auto=none, skipping DDL execution")
            return []

        self._parsed = [self._parse_entity(cls) for cls in self._entities]
        if not self._parsed:
            logger.info("[DDL] No entities registered, nothing to do")
            return []

        logger.info(f"[DDL] ddl-auto={self.mode.value}, processing {len(self._parsed)} table(s)")
        self._executed_sql = []

        try:
            if self.mode == DdlAutoMode.CREATE:
                self._execute_create()
            elif self.mode == DdlAutoMode.CREATE_DROP:
                self._execute_create()
                # Note: drop will happen on shutdown if registered
            elif self.mode == DdlAutoMode.UPDATE:
                self._execute_update()
            elif self.mode == DdlAutoMode.VALIDATE:
                self._execute_validate()
        except Exception as e:
            logger.error(f"[DDL] Execution failed: {e}")
            raise

        logger.info(f"[DDL] Completed. Executed {len(self._executed_sql)} statement(s)")
        return list(self._executed_sql)

    def _execute_create(self):
        """create 模式: DROP + CREATE"""
        for et in self._parsed:
            if self._table_exists(et.table_name):
                drop_sql = f"DROP TABLE {self._quote(et.table_name)}"
                if self.dialect == 'mysql':
                    drop_sql = f"DROP TABLE IF EXISTS {self._quote(et.table_name)}"
                elif self.dialect == 'postgresql':
                    drop_sql = f"DROP TABLE IF EXISTS {self._quote(et.table_name)} CASCADE"
                else:
                    drop_sql = f"DROP TABLE IF EXISTS {self._quote(et.table_name)}"
                self._execute_sql(drop_sql)
                logger.info(f"[DDL] Dropped table {et.table_name}")
            create_sql = self._build_create_table_sql(et)
            self._execute_sql(create_sql)
            logger.info(f"[DDL] Created table {et.table_name} ({len(et.columns)} columns)")

    def _execute_update(self):
        """update 模式: 创建不存在的表，为已存在的表添加新列、创建缺失索引"""
        for et in self._parsed:
            if not self._table_exists(et.table_name):
                create_sql = self._build_create_table_sql(et)
                self._execute_sql(create_sql)
                logger.info(f"[DDL] Created new table {et.table_name}")
                # 创建表后创建索引
                for idx in et.indexes:
                    self._create_index(et.table_name, idx)
                continue
            # 增量更新：添加新列
            existing = self._get_existing_columns(et.table_name)
            for col in et.columns:
                if col['name'] not in existing:
                    parts = [f"ALTER TABLE {self._quote(et.table_name)} ADD COLUMN",
                             self._quote(col['name']), col['sql_type']]
                    if not col['nullable']:
                        parts.append("NOT NULL")
                    if col.get('create_time') or col.get('update_time'):
                        if self.dialect == 'sqlite':
                            parts.append("DEFAULT (datetime('now', 'localtime'))")
                        else:
                            parts.append("DEFAULT CURRENT_TIMESTAMP")
                    elif col['default'] is not None:
                        if isinstance(col['default'], str):
                            parts.append(f"DEFAULT '{col['default']}'")
                        else:
                            parts.append(f"DEFAULT {col['default']}")
                    alter_sql = " ".join(parts)
                    self._execute_sql(alter_sql)
                    logger.info(f"[DDL] Added column {col['name']} to {et.table_name}")
            # 创建缺失索引
            existing_indexes = self._get_existing_indexes(et.table_name)
            for idx in et.indexes:
                if idx.name not in existing_indexes:
                    self._create_index(et.table_name, idx)

    def _create_index(self, table_name: str, idx: Index):
        """创建索引"""
        unique = "UNIQUE" if idx.unique else ""
        cols = ", ".join(self._quote(c) for c in idx.columns)
        sql = f"CREATE {unique} INDEX {self._quote(idx.name)} ON {self._quote(table_name)} ({cols})"
        self._execute_sql(sql)
        logger.info(f"[DDL] Created index {idx.name} on {table_name}")

    def _execute_validate(self):
        """validate 模式: 验证表结构匹配"""
        errors = []
        for et in self._parsed:
            if not self._table_exists(et.table_name):
                errors.append(f"Table '{et.table_name}' does not exist")
                continue
            existing = self._get_existing_columns(et.table_name)
            for col in et.columns:
                if col['name'] not in existing:
                    errors.append(f"Column '{et.table_name}.{col['name']}' is missing")
                else:
                    ex = existing[col['name']]
                    if col['primary_key'] != ex['primary_key']:
                        errors.append(f"Column '{et.table_name}.{col['name']}' primary key mismatch")
                    if not col['nullable'] and ex['nullable']:
                        errors.append(f"Column '{et.table_name}.{col['name']}' should be NOT NULL")
        if errors:
            error_msg = "Schema validation failed:\n  " + "\n  ".join(errors)
            logger.error(f"[DDL] {error_msg}")
            raise Exception(error_msg)
        logger.info("[DDL] Schema validation passed")

    def drop_all(self):
        """create-drop 模式关闭时调用：删除所有注册实体对应的表"""
        for et in reversed(self._parsed):
            if self._table_exists(et.table_name):
                drop_sql = f"DROP TABLE IF EXISTS {self._quote(et.table_name)}"
                if self.dialect == 'postgresql':
                    drop_sql += " CASCADE"
                self._execute_sql(drop_sql)
                logger.info(f"[DDL] Dropped table {et.table_name}")

    def get_generated_sql(self) -> List[str]:
        """获取生成但不一定执行的SQL（用于预览）"""
        # 如果还没解析，先解析实体
        if not self._parsed:
            self._parsed = [self._parse_entity(cls) for cls in self._entities]
        result = []
        for et in self._parsed:
            result.append(self._build_create_table_sql(et))
        return result

    def get_executed_sql(self) -> List[str]:
        """获取已执行的SQL"""
        return list(self._executed_sql)


# ==================== 装饰器API（便捷使用） ====================

def _auto_infer_columns(cls):
    """扫描类型注解，为未显式赋 ``Column`` 描述符的字段自动创建 ``Column`` 实例。

    对齐 Java JPA：实体类中所有非 ``@Transient`` 字段自动映射为数据库列，
    无需显式 ``= Column(...)`` 赋值。

    推断规则：
      - ``name: str``               → ``Column()``（无默认值，仅记录类型）
      - ``name: str = ""``          → ``Column(default="")``（赋值即为默认值）
      - ``name: int = 0``           → ``Column(default=0)``
      - ``name: str = Column(...)`` → 保留原 Column，不覆盖
      - ``name: int = Id()``        → 保留原 Id，不覆盖
      - 以 ``_`` 开头的字段         → 跳过（私有/内部字段）
      - ``@Transient`` 标记字段      → 跳过
    """
    # 收集 MRO 中所有类型注解
    all_annotations = {}
    for cls_base in reversed(cls.__mro__):
        base_anns = getattr(cls_base, '__annotations__', {})
        all_annotations.update(base_anns)

    for attr_name in all_annotations:
        # 跳过私有字段
        if attr_name.startswith('_'):
            continue
        # 跳过 @Transient 字段
        if _is_transient_field(cls, attr_name):
            continue

        # 查找 MRO 中最近的类属性值
        existing = None
        for cls_base in cls.__mro__:
            if attr_name in cls_base.__dict__:
                existing = cls_base.__dict__[attr_name]
                break

        # 已有 Column/Id/Version/CreateTime/UpdateTime 描述符，不覆盖
        if isinstance(existing, Column):
            continue
        # 已有 @column 装饰器标记
        if hasattr(existing, '__column__'):
            continue
        # 已有 Transient 标记
        if isinstance(existing, Transient):
            continue
        # 识别 Bean Validation Constraint 描述符（仅标记，不跳过自动建列）
        # 因为 name: str = NotBlank() 也应该自动建列，只是 default=None
        is_constraint_only = (
            isinstance(existing, type) is False and existing is not None
            and hasattr(existing, 'constraint_name') and hasattr(existing, 'validate')
        )
        # 已有其他模块描述符（ExcelProperty/CsvProperty 等），不覆盖
        if hasattr(existing, '__set_name__') and not isinstance(existing, (Column, Transient)) \
                and not is_constraint_only:
            continue

        # 只有显式赋值才给默认值；无赋值则仅创建 Column() 记录类型
        # Constraint 描述符视为无默认值（不要把 NotBlank 对象作为 default）
        if not is_constraint_only and existing is not None and not callable(existing) \
                and not isinstance(existing, (classmethod, staticmethod)):
            col = Column(default=existing)
        else:
            col = Column()

        # 组合式：替换前把原描述符上的约束迁移到 Column.constraints
        # （1）独立 Constraint 描述符：如 name: str = NotBlank() → NotBlank 是个 Constraint 实例
        if is_constraint_only:
            # 必须延迟 import 避免循环依赖
            _Constraint_base = type(existing).__mro__
            # 直接 isinstance 检查有循环依赖风险，通过 attr 特征 + 不是已有描述符方式判断
            # 既然 is_constraint_only=True，existing 本身就是一个 Constraint 实例，直接加
            col.constraints.append(existing)
        # （2）其他描述符带 constraints 属性：如 ExcelProperty(constraints=[...])
        elif hasattr(existing, 'constraints') and isinstance(getattr(existing, 'constraints', None), list):
            for c in existing.constraints:
                if hasattr(c, 'constraint_name') and hasattr(c, 'validate'):
                    col.constraints.append(c)

        setattr(cls, attr_name, col)


def _auto_generate_init(cls):
    """为描述符风格实体类自动生成 ``__init__``（若类未显式声明）。

    先调用 ``_auto_infer_columns`` 补全类型注解对应的 ``Column`` 描述符，
    再扫描 MRO 中所有 ``Column`` 实例属性，生成关键字构造器。
    若类已显式声明 ``__init__`` 则跳过，保持兼容。
    """
    # 无论是否有自定义 __init__，都先补全 Column 描述符（DDL 解析依赖）
    _auto_infer_columns(cls)

    if '__init__' in cls.__dict__:
        return
    fields = {}
    for cls_base in reversed(cls.__mro__):
        for name, value in cls_base.__dict__.items():
            if isinstance(value, Column):
                fields[name] = value

    def __init__(self, **values):
        unknown = set(values) - set(fields)
        if unknown:
            names = ', '.join(sorted(unknown))
            raise TypeError(f"Unexpected entity field(s): {names}")
        for name, column in fields.items():
            setattr(self, name, values.get(name, column.default))

    cls.__init__ = __init__


def Entity(table_name: str = "", indexes: List[Index] = None, comment: str = ""):
    """``@Entity`` 装饰器，标注一个类为 JPA 风格的实体类。

    三种用法（均向后兼容）：

    1. **Java JPA 风格**（``@Entity`` + ``@Table`` 分离，推荐）::

        @Entity
        @Table(name="sys_user", indexes=[Index("idx_name", ["name"])], comment="用户表")
        class User:
            id: int = Id()
            name: str = Column(length=50)

    2. **简化风格**（仅 ``@Entity``，表名自动推导为类名 snake_case）::

        @Entity
        class User:
            id: int = Id()
            name: str = Column(length=50)
        # 表名自动推导为 "user"

    3. **一体化风格**（当前写法，完全兼容）::

        @Entity("sys_user", indexes=[...], comment="用户表")
        class User:
            id: int = Id()
            name: str = Column(length=50)
    """
    # 支持 @Entity 无括号形式：直接接收类
    if inspect.isclass(table_name):
        cls = table_name
        setattr(cls, '__entity__', True)
        # 未显式指定表信息时，不覆盖已有 @Table 设置的 __table__
        existing = getattr(cls, '__table__', None)
        if not isinstance(existing, Table):
            setattr(cls, '__table__', Table(name=_camel_to_snake(cls.__name__)))
        _auto_generate_init(cls)
        return cls

    # @Entity("table_name", ...) 或 @Entity() 形式
    has_explicit_meta = bool(table_name or indexes or comment)
    t = Table(name=table_name, indexes=indexes, comment=comment) if has_explicit_meta else None

    def decorator(cls):
        setattr(cls, '__entity__', True)
        if t is not None:
            if not t.name:
                t.name = _camel_to_snake(cls.__name__)
            setattr(cls, '__table__', t)
        else:
            # 无显式表信息：不覆盖已有 @Table 设置
            existing = getattr(cls, '__table__', None)
            if not isinstance(existing, Table):
                setattr(cls, '__table__', Table(name=_camel_to_snake(cls.__name__)))
        _auto_generate_init(cls)
        return cls
    return decorator


# Backward-compatible alias. New code should use the Spring-style @Entity name.
entity = Entity


def table(name: str = "", indexes: List[Index] = None, comment: str = ""):
    """@Table 装饰器，标注实体类对应的表（与@entity功能相同，别名）"""
    return Entity(name, indexes, comment)


# ==================== 全局集成 ====================

# 全局DDL自动管理器实例
_global_ddl_manager: Optional[DdlAutoManager] = None


def init_ddl_auto(connection_pool, config: dict = None) -> Optional[DdlAutoManager]:
    """
    从配置初始化DDL自动建表管理器并执行
    
    Args:
        connection_pool: 数据库连接池实例
        config: 配置字典，应包含 ddl-auto 配置段
        
    Returns:
        DdlAutoManager实例或None
    """
    global _global_ddl_manager
    config = config or {}
    ddl_config = config.get('ddl-auto', config.get('jpa', {}).get('hibernate', {}))
    mode = str(ddl_config.get('mode', ddl_config.get('ddl-auto', 'none'))).lower()
    
    if mode == 'none' or not mode:
        logger.info("[DDL] ddl-auto=none, skipping auto DDL")
        return None
    
    # 判断方言
    driver = str(config.get('driver', 'sqlite')).lower()
    if 'mysql' in driver:
        dialect = 'mysql'
    elif 'postgresql' in driver or 'pg' in driver:
        dialect = 'postgresql'
    else:
        dialect = 'sqlite'
    
    # 创建管理器
    manager = DdlAutoManager(connection_pool, dialect=dialect, mode=mode)
    
    # 扫描实体包
    entity_packages = ddl_config.get('entity_packages', ddl_config.get('packages-to-scan', []))
    if isinstance(entity_packages, str):
        entity_packages = [p.strip() for p in entity_packages.split(',') if p.strip()]
    
    if entity_packages:
        manager._scan_packages(entity_packages)
        logger.info(f"[DDL] Scanned entity packages: {entity_packages}, found {len(manager._entities)} entities")
    
    # 执行DDL
    if manager._entities:
        manager.execute()
    
    _global_ddl_manager = manager
    return manager


def get_ddl_manager() -> Optional[DdlAutoManager]:
    """获取全局DDL管理器"""
    return _global_ddl_manager


# ==================== JPA @Version 乐观锁执行器 ====================

class OptimisticLockError(Exception):
    """乐观锁冲突异常：UPDATE 影响行数为 0，说明版本号已变更或记录不存在。"""


def _find_version_column(entity_class: Type) -> Optional[dict]:
    """解析实体类，返回 ``@Version`` 列元数据 dict（无则 None）。

    复用 ``DdlAutoManager._parse_entity`` 解析逻辑，避免重复实现字段扫描。
    """
    # 用一个临时 manager 仅做解析（不执行 DDL）
    tmp = DdlAutoManager.__new__(DdlAutoManager)
    tmp.dialect = 'sqlite'
    tmp.mode = DdlAutoMode.NONE
    try:
        et = tmp._parse_entity(entity_class)
    except Exception:
        return None
    for col in et.columns:
        if col.get('version'):
            return col
    return None


class OptimisticLockExecutor:
    """``@Version`` 乐观锁更新执行器（对齐 JPA/Hibernate 乐观锁语义）。

    本框架内嵌 PyMyBatis **不自动**在 UPDATE 时注入 version 检查子句（与 JPA/Hibernate
    的差异，已在 ``Version`` 注解文档标注）。本执行器提供等价的显式乐观锁更新：
    生成 ``UPDATE table SET ... , version = version + 1 WHERE <pk> = ? AND version = ?``，
    根据影响行数判断是否冲突。

    用法::

        from springbootai.orm import OptimisticLockExecutor, Version, Id, entity

        @entity("sys_user")
        class User:
            id = Id()
            version = Version()
            def __init__(self, id=None, name=None, version=0):
                self.id = id; self.name = name; self.version = version

        executor = OptimisticLockExecutor(connection_pool, dialect="mysql")
        # 冲突时抛 OptimisticLockError
        executor.update(entity_class=User, entity=user_obj,
                        set_fields={"name": "new_name"})
        # 或探测式（不抛错，返回是否成功）
        ok = executor.try_update(entity_class=User, entity=user_obj,
                                 set_fields={"name": "new_name"})

    Args:
        connection_pool: 数据库连接池（需支持 ``connection()`` 上下文管理器）。
        dialect:         SQL 方言（mysql/postgresql/sqlite），影响标识符引用。
    """

    def __init__(self, connection_pool: Any, dialect: str = "mysql"):
        self.pool = connection_pool
        self.dialect = dialect.lower()

    def _quote(self, identifier: str) -> str:
        if self.dialect == 'mysql':
            return f"`{str(identifier).replace('`', '``')}`"
        return f'"{str(identifier).replace(chr(34), chr(34) * 2)}"'

    def _find_pk(self, entity_class: Type) -> Optional[dict]:
        """返回主键列元数据。"""
        for col in self._parse_columns(entity_class):
            if col.get('primary_key'):
                return col
        return None

    def _parse_columns(self, entity_class: Type) -> List[dict]:
        """解析实体类的全部列元数据（复用 ``DdlAutoManager._parse_entity``）。

        列元数据含 ``py_name``（Python 属性名）与 ``name``（SQL 列名），供
        ``set_fields`` 的属性名 -> 列名翻译使用，避免 ``Column(name=...)`` 自定义列名时
        生成错误 SQL（与 JPA 实体元数据语义一致）。
        """
        tmp = DdlAutoManager.__new__(DdlAutoManager)
        tmp.dialect = self.dialect
        tmp.mode = DdlAutoMode.NONE
        try:
            et = tmp._parse_entity(entity_class)
        except Exception:
            return []
        return list(et.columns)

    def _column_py_to_sql_map(self, entity_class: Type) -> Dict[str, str]:
        """构造 ``{py_name: sql_column_name}`` 映射，用于 ``set_fields`` 翻译。"""
        mapping: Dict[str, str] = {}
        for col in self._parse_columns(entity_class):
            py = col.get('py_name') or col.get('name')
            mapping[py] = col.get('name') or py
        return mapping

    def update(
        self,
        entity_class: Type,
        entity: Any,
        set_fields: Dict[str, Any],
    ) -> int:
        """乐观锁更新：冲突时抛 ``OptimisticLockError``。

        Args:
            entity_class: 实体类（带 ``@Version`` 与主键）。
            entity:       实体实例（提供主键值与当前 version）。
            set_fields:   要更新的字段 -> 值映射（不含 version，version 自动 +1）。
        Returns:
            新版本号（旧 version + 1）。
        """
        version_col = _find_version_column(entity_class)
        if version_col is None:
            raise ValueError(
                f"{entity_class.__name__} 未声明 @Version 字段，无法乐观锁更新"
            )
        # 注意：必须在 try_update 之前捕获 old_version——try_update 成功后会回写
        # entity.version = old_version + 1，事后再读会得到已自增的值。
        old_version = getattr(entity, version_col['py_name'], 0) or 0
        ok = self.try_update(entity_class, entity, set_fields)
        if not ok:
            raise OptimisticLockError(
                f"乐观锁更新失败：{entity_class.__name__} 版本已变更或记录不存在"
            )
        return old_version + 1

    def try_update(
        self,
        entity_class: Type,
        entity: Any,
        set_fields: Dict[str, Any],
    ) -> bool:
        """乐观锁更新（探测式）：成功返回 True，冲突/记录不存在返回 False。"""
        version_col = _find_version_column(entity_class)
        if version_col is None:
            raise ValueError(f"{entity_class.__name__} 未声明 @Version 字段，无法乐观锁更新")
        pk_col = self._find_pk(entity_class)
        if pk_col is None:
            raise ValueError(f"{entity_class.__name__} 未找到主键字段")

        table_name = self._resolve_table_name(entity_class)
        old_version = getattr(entity, version_col['py_name'], 0) or 0
        pk_value = getattr(entity, pk_col['py_name'], None)
        if pk_value is None:
            raise ValueError("实体主键值为空，无法乐观锁更新")

        # 构造 UPDATE ... SET ..., version = version + 1 WHERE pk = ? AND version = ?
        # set_fields 的键为 Python 属性名，需按实体元数据翻译为真实 SQL 列名
        col_map = self._column_py_to_sql_map(entity_class)
        set_parts = [f"{self._quote(self._col_sql_name(f, col_map))} = ?" for f in set_fields]
        set_parts.append(f"{self._quote(version_col['name'])} = {self._quote(version_col['name'])} + 1")
        sql = (
            f"UPDATE {self._quote(table_name)} SET {', '.join(set_parts)} "  # nosec B608 - quoted metadata
            f"WHERE {self._quote(pk_col['name'])} = ? AND {self._quote(version_col['name'])} = ?"
        )
        params = list(set_fields.values()) + [pk_value, old_version]

        affected = self._execute_dml(sql, params)
        # 同步回写实体上的新版本号，便于后续操作
        if affected > 0:
            try:
                setattr(entity, version_col['py_name'], old_version + 1)
            except Exception:
                pass
        return affected > 0

    def _col_sql_name(self, field_name: str, col_map: Dict[str, str]) -> str:
        """Python 属性名 -> SQL 列名。

        优先查实体元数据映射（``Column(name=...)`` 自定义列名）；未命中时回退 snake_case，
        兼容未声明 ``Column`` 的简单字段。
        """
        if field_name in col_map:
            return col_map[field_name]
        return _camel_to_snake(field_name)

    def _resolve_table_name(self, entity_class: Type) -> str:
        table_meta = getattr(entity_class, '__table__', None)
        if isinstance(table_meta, Table) and table_meta.name:
            return table_meta.name
        tn = getattr(entity_class, '__tablename__', "")
        return tn or _camel_to_snake(entity_class.__name__)

    def _execute_dml(self, sql: str, params: list) -> int:
        """执行 DML，返回影响行数。兼容 DBUtils 连接池与原生 connection。"""
        conn = None
        cursor = None
        try:
            if hasattr(self.pool, 'connection'):
                conn = self.pool.connection()
            else:
                conn = self.pool
            cursor = conn.cursor()
            affected = cursor.execute(sql, params)
            conn.commit()
            # 不同驱动返回语义不一：
            # - DBUtils/MySQLdb: execute 返回 rowcount (int)
            # - sqlite3: execute 返回 cursor 自身（非 int）
            # - psycopg2: execute 返回 None
            if not isinstance(affected, int):
                affected = getattr(cursor, 'rowcount', 0)
            return int(affected or 0)
        except Exception:
            try:
                if conn is not None:
                    conn.rollback()
            except Exception:
                pass
            raise
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    pass
            if conn is not None and hasattr(self.pool, 'connection'):
                try:
                    conn.close()
                except Exception:
                    pass


# ==================== JPA @CreateTime / @UpdateTime 自动填充执行器 ====================

def _find_audit_time_column(entity_class: Type, flag: str) -> Optional[dict]:
    """解析实体类，返回 ``@CreateTime``/``@UpdateTime`` 列元数据 dict（无则 None）。

    ``flag`` 为 ``'create_time'`` 或 ``'update_time'``（对应列元数据里的布尔标记）。
    复用 ``DdlAutoManager._parse_entity`` 解析逻辑，避免重复实现字段扫描。
    """
    tmp = DdlAutoManager.__new__(DdlAutoManager)
    tmp.dialect = 'sqlite'
    tmp.mode = DdlAutoMode.NONE
    try:
        et = tmp._parse_entity(entity_class)
    except Exception:
        return None
    for col in et.columns:
        if col.get(flag):
            return col
    return None


class AuditTimeExecutor:
    """``@CreateTime``/``@UpdateTime`` 自动时间填充执行器（对齐 JPA/Hibernate 审计时间戳）。

    在 INSERT / UPDATE 前调用 ``fill_on_insert`` / ``fill_on_update``，把当前时间写入实体上
    标记了 ``@CreateTime`` / ``@UpdateTime`` 的字段，之后再把实体传给 Mapper 的 ``@Insert`` /
    ``@Update`` 即可自动带上时间。同时 DDL 自动建表会给这些列加 ``DEFAULT CURRENT_TIMESTAMP``
    作为兜底，即使漏调填充方法，数据库也会写入当前时间。

    用法::

        from springbootai.orm import AuditTimeExecutor, CreateTime, UpdateTime, Id, entity

        @entity("sys_user")
        class User:
            id = Id()
            created_at = CreateTime()
            updated_at = UpdateTime()
            def __init__(self, id=None, name=None, created_at=None, updated_at=None):
                self.id = id; self.name = name
                self.created_at = created_at; self.updated_at = updated_at

        executor = AuditTimeExecutor()
        user = User(name="John")
        executor.fill_on_insert(User, user)   # 写入 created_at 与 updated_at
        user_mapper.insert(user)              # 执行 INSERT

        executor.fill_on_update(User, user)   # 仅刷新 updated_at
        user_mapper.update(user)              # 执行 UPDATE

    Args:
        now: 可选，注入固定时间字符串（默认取系统当前时间），用于测试与幂等场景。
    """

    def __init__(self, now: Optional[str] = None):
        self._now = now

    def _current_time(self) -> str:
        """返回待写入的时间字符串。"""
        if self._now is not None:
            return self._now
        from datetime import datetime
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def fill_on_insert(self, entity_class: Type, entity: Any) -> Any:
        """INSERT 前自动填充：``@CreateTime`` 与 ``@UpdateTime`` 都写入当前时间。

        若字段已有值则保留（便于业务自定义时间），否则写入当前时间。
        返回原实体对象。
        """
        now = self._current_time()
        for flag in ('create_time', 'update_time'):
            col = _find_audit_time_column(entity_class, flag)
            if col is None:
                continue
            py_name = col['py_name'] or col['name']
            if getattr(entity, py_name, None) in (None, ''):
                setattr(entity, py_name, now)
        return entity

    def fill_on_update(self, entity_class: Type, entity: Any) -> Any:
        """UPDATE 前自动填充：仅刷新 ``@UpdateTime`` 为当前时间（``@CreateTime`` 保持不变）。"""
        col = _find_audit_time_column(entity_class, 'update_time')
        if col is not None:
            py_name = col['py_name'] or col['name']
            setattr(entity, py_name, self._current_time())
        return entity
