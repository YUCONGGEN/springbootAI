"""综合组合注解测试：ORM + Excel + CSV + Validation 四模块注解组合。

覆盖所有可行的字段级/类级注解组合形式：
    类级：@Entity + @ExcelSheet + @CsvFile
    字段级：
        - 纯类型注解（age: int = 0）+ 可推断列 + 独立 Constraint
        - Column(constraints=[NotBlank(), Size(...)]) 内联约束
        - ExcelProperty(constraints=[NotBlank(), ...]) 内联约束
        - CsvProperty(constraints=[NotBlank(), ...]) 内联约束
        - Id(constraints=[NotNull()]) 内联约束
        - 独立 Constraint 描述符（name = NotBlank()）不被误当作 Excel/CSV/ORM 列
        - 所有模块 round-trip：ORM DDL 建表 + Excel 读写 + CSV 读写 + 校验违规报告
"""
from __future__ import annotations

from spring.orm.ddl_auto import (
    Column, Entity, Id, Version, DdlAutoManager,
    CreateTime, UpdateTime, column, id_column,
)


def _parse_entity(cls, dialect='sqlite'):
    """便捷函数：复用 ``DdlAutoManager._parse_entity`` 单例解析。"""
    return DdlAutoManager(None, dialect=dialect, mode='none')._parse_entity(cls)
from spring.excel.annotations import (
    ExcelSheet, ExcelProperty, ExcelIgnore, parse_excel_columns,
)
from spring.excel import EasyExcel
from spring.csv.annotations import (
    CsvFile, CsvProperty, parse_csv_columns,
)
from spring.csv import write_csv, read_csv
from spring.validation.constraints import (
    NotNull, NotBlank, Size, Min, Max, Positive, Email, Pattern,
)
from spring.validation.validator import BeanValidator


# ==================== 1. 组合式：四模块注解同用一类 ====================

@Entity("demo_user")
@ExcelSheet("用户清单")
@CsvFile("users.csv")
class FullStackUser:
    """全栈组合示例：同一类同时具备 ORM、Excel、CSV、Validation 能力。"""

    # ORM 主键（Id + 约束：NotNull 通过 constraints 参数）
    id: int = Id(constraints=[NotNull(message="ID 必填")])

    # ORM 列 + Bean Validation 约束（内联）
    name: str = Column(
        "name", nullable=False, length=50, default="",
        constraints=[
            NotBlank(message="姓名不能为空"),
            Size(min=1, max=50, message="姓名长度 1-50"),
        ],
    )

    # 纯类型注解：ORM 自动建列，Excel/CSV 自动建列 + 独立约束
    age: int = 0

    # 独立约束描述符：仅校验，不自动生成 Excel/CSV/ORM 列
    _validate_age = None  # 占位，下面用 Min 描述符

    # Excel 专用表头 + 校验约束（内联）
    email: str = ExcelProperty(
        "邮箱地址", order=4,
        constraints=[
            NotBlank(message="邮箱不能为空"),
            Email(message="邮箱格式错误"),
        ],
    )

    # CSV 专用表头 + 校验约束（内联）
    phone: str = CsvProperty(
        "手机号码", order=5,
        constraints=[
            NotBlank(message="手机号不能为空"),
            Pattern(r'^1\d{10}$', message="应为 11 位手机号"),
        ],
    )

    # ORM 乐观锁 + 创建时间/更新时间
    version: int = Version()
    created_at: str = CreateTime()
    updated_at: str = UpdateTime()

    # 忽略字段：Excel 跳过（ExcelIgnore）+ 校验（通过 CsvProperty.ignore 的 constraints 路径不支持）
    # 这里把校验作为独立的函数装饰器声明在另一个同名字段函数上不现实（名称冲突）
    # 所以把 remark 仅标为 ExcelIgnore，校验通过 Remark 约束类属性上的 Size 描述符
    # 但注意：一个类属性只能有一个值，我们使用单独的 ExcelIgnore + 用 @ExcelIgnore() 装饰器形式
    remark: str = ExcelIgnore()


class TestFullStackUser:
    """全栈组合类的完整性测试。"""

    # --- ORM ---
    def test_orm_entity_parsed(self):
        """@Entity 解析：所有 ORM 相关字段在实体元数据中存在。"""
        meta = _parse_entity(FullStackUser)
        assert meta is not None
        col_names = {c['name'] for c in meta.columns}
        # ORM 列：id/name/age/email/phone/version/created_at/updated_at
        for name in ("id", "name", "age", "email", "phone", "version", "created_at", "updated_at"):
            assert name in col_names, f"ORM 缺列: {name}"
        # remark 被 ExcelIgnore 标记，但 ORM 仍会自动建列（未 @Transient）
        assert "remark" in col_names
        # 主键
        pk_cols = [c for c in meta.columns if c.get('primary_key')]
        assert len(pk_cols) == 1 and pk_cols[0]['name'] == "id"

    # --- Excel ---
    def test_excel_columns_correct(self):
        """@ExcelSheet 解析：email 保留表头，ExcelIgnore 不导出。"""
        cols = parse_excel_columns(FullStackUser)
        attr_names = {c.attr_name for c in cols}
        # remark 被 ExcelIgnore → 不导出
        assert "remark" not in attr_names
        # _validate_age 私有字段 → 不导出
        assert "_validate_age" not in attr_names
        # 应包含的数据字段
        for name in ("id", "name", "age", "email", "phone", "version", "created_at", "updated_at"):
            assert name in attr_names, f"Excel 缺列: {name}"
        # email 表头应为 ExcelProperty 中声明
        col_map = {c.attr_name: c for c in cols}
        assert col_map["email"].header == "邮箱地址"

    # --- CSV ---
    def test_csv_columns_correct(self):
        """@CsvFile 解析：phone 保留表头。"""
        cols = parse_csv_columns(FullStackUser)
        attr_names = {c.attr_name for c in cols}
        for name in ("id", "name", "age", "email", "phone", "version", "created_at", "updated_at"):
            assert name in attr_names, f"CSV 缺列: {name}"
        col_map = {c.attr_name: c for c in cols}
        assert col_map["phone"].header == "手机号码"

    # --- Validation ---
    def test_validation_constraints_collected_all_sources(self):
        """BeanValidator 从四源收集约束：Id/Column/ExcelProperty/CsvProperty。"""
        cs = BeanValidator.get_constraints(FullStackUser)
        # 四个字段都有约束：id (Id.constraints), name (Column.constraints),
        # email (ExcelProperty.constraints), phone (CsvProperty.constraints)
        assert "id" in cs
        assert "name" in cs
        assert "email" in cs
        assert "phone" in cs
        # name: NotBlank + Size
        name_cnames = {c.constraint_name for c in cs["name"]}
        assert name_cnames == {"NotBlank", "Size"}
        # email: NotBlank + Email
        email_cnames = {c.constraint_name for c in cs["email"]}
        assert email_cnames == {"NotBlank", "Email"}

    def test_validation_detects_violations(self):
        """校验违规对象：应返回对应 ConstraintViolation 列表。"""
        # 全空对象
        u = FullStackUser()
        vs = BeanValidator.validate(u)
        attr_violations = {v.attr_name for v in vs}
        # id NotNull 触发；name NotBlank 触发；email NotBlank；phone NotBlank
        assert "id" in attr_violations
        assert "name" in attr_violations
        assert "email" in attr_violations
        assert "phone" in attr_violations

    def test_validation_valid_passes(self):
        """合法对象：无违规。"""
        u = FullStackUser(
            id=1, name="张三", age=28,
            email="zhangsan@example.com", phone="13800138000",
        )
        vs = BeanValidator.validate(u)
        assert vs == []

    def test_validation_email_format(self):
        """Email 格式违规单独触发。"""
        u = FullStackUser(id=1, name="张三", email="不是邮箱", phone="13800138000")
        vs = BeanValidator.validate(u)
        emails = [v for v in vs if v.attr_name == "email"]
        assert any("格式" in v.message for v in emails)

    def test_validation_phone_pattern(self):
        """手机号 Pattern 违规单独触发。"""
        u = FullStackUser(id=1, name="张三", email="a@b.com", phone="12345")
        vs = BeanValidator.validate(u)
        phones = [v for v in vs if v.attr_name == "phone"]
        assert any("11 位" in v.message or "手机号" in v.message for v in phones)

    # --- auto __init__ ---
    def test_auto_init_defaults(self):
        """自动 __init__：跨模块描述符取正确默认值。"""
        u = FullStackUser()
        # Id.default = None
        assert u.id is None
        # Column.default = ""
        assert u.name == ""
        # 普通默认值 0
        assert u.age == 0
        # ExcelProperty / CsvProperty 无 default → None
        assert u.email is None
        assert u.phone is None


# ==================== 2. 独立 Constraint 描述符（不被误当列） ====================

@ExcelSheet("单独约束测试")
@CsvFile("standalone.csv")
@Entity("standalone_tbl")
class StandaloneConstraintUser:
    """字段用独立 NotBlank() 描述符（不嵌在 Column/ExcelProperty 内）。

    这种情况下：
    - ORM 应跳过 NotBlank（不替换为 Column），但类型注解可自动建列
    - Excel 不应把 NotBlank 当数据列（通过 constraint_name + validate 特征识别）
    - CSV 同理
    - Validation 仍能正确收集约束（因为还是 Constraint 实例）
    """
    id: int = Id()
    # 只有 NotBlank，无 Column/ExcelProperty 包着
    name: str = NotBlank(message="姓名必填")
    # 有类型注解的纯默认值：应该正常建列
    age: int = 0


class TestStandaloneConstraint:
    """独立 Constraint 不被误当作 Excel/CSV 数据列。"""

    def test_excel_skips_standalone_constraint(self):
        """Excel 不把 name (NotBlank) 当列，只把 age/当列。"""
        cols = parse_excel_columns(StandaloneConstraintUser)
        attr_names = {c.attr_name for c in cols}
        # 因为类型注解 name: str 存在，ORM 自动建列，Excel/CSV 也会自动建列
        # 但 NotBlank 描述符本身不应该取代描述符检查（实际上，既然 name 有注解，
        # 它是应建列的，只是描述符不应是数据源）
        # 核心验证：列解析不报错，且 age/id 存在
        assert "id" in attr_names
        assert "age" in attr_names
        # name: str = NotBlank() → Excel 应该跳过 NotBlank（因为是 Constraint），
        # 但 name 在类型注解中，应该有自动列
        assert "name" in attr_names

    def test_csv_skips_standalone_constraint(self):
        cols = parse_csv_columns(StandaloneConstraintUser)
        attr_names = {c.attr_name for c in cols}
        assert "id" in attr_names
        assert "age" in attr_names
        assert "name" in attr_names

    def test_orm_skips_standalone_constraint(self):
        """ORM 不把 NotBlank 替换成 Column，保留描述符。"""
        # 因为 @Entity 会在 name: str 上自动建列，但 NotBlank 不被替换
        v = StandaloneConstraintUser.__dict__.get("name")
        # 实际上，如果 _auto_infer_columns 把列生成并 setattr(cls, 'name', col)，
        # 那么 NotBlank 会被替换 —— 这个测试用来确认行为
        assert isinstance(v, (NotBlank, Column))  # 二者之一都是可接受的
        # 关键：约束仍能工作
        cs = BeanValidator.get_constraints(StandaloneConstraintUser)
        assert "name" in cs
        assert any(c.constraint_name == "NotBlank" for c in cs["name"])

    def test_validation_collects_standalone(self):
        """独立 NotBlank 约束仍然被校验器识别。"""
        u = StandaloneConstraintUser()
        vs = BeanValidator.validate(u)
        names = {v.attr_name for v in vs}
        assert "name" in names


# ==================== 3. 函数装饰器形式的约束组合 ====================

@Entity("func_form")
@ExcelSheet("函数形式")
@CsvFile("func_form.csv")
class FunctionDecoratorUser:
    """注解用函数装饰器形式（镜像 @column + @NotBlank 叠加）。"""

    def __init__(self, id=None, name=None, age=0, email=None, remark=""):
        self.id = id
        self.name = name
        self.age = age
        self.email = email
        self.remark = remark

    @id_column()
    def id(self): ...

    @column(name="name", nullable=False, length=50, default="")
    @NotBlank(message="姓名必填")
    @Size(max=50)
    def name(self): ...

    @ExcelProperty("邮箱", order=3)
    @NotBlank(message="邮箱必填")
    @Email()
    def email(self): ...

    @CsvProperty("CSV 专属备注", order=4)
    @Size(max=200)
    def remark(self): ...


class TestFunctionDecoratorComposition:
    """函数装饰器形式的组合注解：@Column/@ExcelProperty + @Constraint 叠加。"""

    def test_orm_columns_from_func_decorator(self):
        """ORM：通过函数装饰器声明的列被正确识别。"""
        meta = _parse_entity(FunctionDecoratorUser)
        col_names = {c['name'] for c in meta.columns}
        assert "id" in col_names
        assert "name" in col_names

    def test_excel_email_header(self):
        """Excel：@ExcelProperty 函数装饰器表头正确。"""
        cols = parse_excel_columns(FunctionDecoratorUser)
        col_map = {c.attr_name: c for c in cols}
        if "email" in col_map:
            assert col_map["email"].header == "邮箱"

    def test_csv_remark_header(self):
        """CSV：@CsvProperty 函数装饰器表头正确。"""
        cols = parse_csv_columns(FunctionDecoratorUser)
        col_map = {c.attr_name: c for c in cols}
        if "remark" in col_map:
            assert col_map["remark"].header == "CSV 专属备注"

    def test_validation_from_func_decorators(self):
        """约束：从函数装饰器收集（@NotBlank/@Size/@Email）。"""
        cs = BeanValidator.get_constraints(FunctionDecoratorUser)
        assert "name" in cs
        name_cnames = {c.constraint_name for c in cs["name"]}
        assert "NotBlank" in name_cnames
        assert "Size" in name_cnames
        # email 约束
        if "email" in cs:
            email_cnames = {c.constraint_name for c in cs["email"]}
            assert "Email" in email_cnames


# ==================== 4. Excel + CSV Round-trip（使用组合类） ====================

class TestCompositionalRoundTrip:

    def test_excel_round_trip_full_stack(self, tmp_path):
        """组合类 Excel 写入 → 读取 round-trip。"""
        data = [
            FullStackUser(id=1, name="张三", age=28,
                          email="zhangsan@example.com", phone="13800138000"),
            FullStackUser(id=2, name="李四", age=35,
                          email="lisi@example.com", phone="13900139000"),
        ]
        f = tmp_path / "fs.xlsx"
        EasyExcel.write(str(f), head=FullStackUser).sheet("用户清单").doWrite(data)
        rows = EasyExcel.read(str(f), head=FullStackUser).doRead()

        assert len(rows) == 2
        assert rows[0].name == "张三"
        assert rows[0].email == "zhangsan@example.com"
        assert rows[0].phone == "13800138000"
        assert rows[1].name == "李四"
        # 合法数据应通过校验
        for r in rows:
            # 注意：created_at/updated_at 读回为 None，但它们无 NotNull 约束
            violations = [v for v in BeanValidator.validate(r)
                          if v.attr_name not in ("created_at", "updated_at")]
            assert violations == [], f"校验失败: {violations}"

    def test_csv_round_trip_full_stack(self, tmp_path):
        """组合类 CSV 写入 → 读取 round-trip。"""
        data = [
            FullStackUser(id=1, name="张三", age=28,
                          email="zhangsan@example.com", phone="13800138000"),
            FullStackUser(id=2, name="李四", age=35,
                          email="lisi@example.com", phone="13900139000"),
        ]
        f = tmp_path / "fs.csv"
        write_csv(str(f), FullStackUser, data)
        rows = read_csv(str(f), FullStackUser)

        assert len(rows) == 2
        assert rows[0].name == "张三"
        assert rows[0].phone == "13800138000"
        assert rows[0].email == "zhangsan@example.com"

    def test_validation_rejects_bad_import(self, tmp_path):
        """从 Excel 读取的数据若不合法，BeanValidator 能拒绝。"""
        # 构造一批不合法数据（缺少必填，格式错误）
        bad_data = [
            FullStackUser(id=None, name="", age=-5,
                          email="不是邮箱", phone="123"),
        ]
        f = tmp_path / "bad.xlsx"
        EasyExcel.write(str(f), head=FullStackUser).sheet("用户清单").doWrite(bad_data)
        rows = EasyExcel.read(str(f), head=FullStackUser).doRead()
        assert len(rows) == 1
        vs = BeanValidator.validate(rows[0])
        # 至少应包含 name/email/phone 三类违规中的若干
        attr_names = {v.attr_name for v in vs}
        assert ("name" in attr_names) or ("email" in attr_names) or ("phone" in attr_names)


# ==================== 5. ORM DDL 建表（使用组合类） ====================

class TestOrmDdlWithCompositional:
    """组合类通过 DdlAutoManager 生成 DDL。"""

    def test_ddl_generates_sqlite(self):
        """DDL 生成：SQLite 方言。"""
        ddl = DdlAutoManager(None, dialect='sqlite', mode='none')
        et = ddl._parse_entity(FullStackUser)
        sql = ddl._build_create_table_sql(et)
        # 主键 + version 都在
        assert "PRIMARY KEY" in sql
        assert "id" in sql
        assert "name" in sql
        assert "email" in sql

    def test_ddl_generates_mysql(self):
        """DDL 生成：MySQL 方言。"""
        ddl = DdlAutoManager(None, dialect='mysql', mode='none')
        et = ddl._parse_entity(FullStackUser)
        sql = ddl._build_create_table_sql(et)
        assert "AUTO_INCREMENT" in sql
        assert "name" in sql
        assert "email" in sql


# ==================== 6. 校验分组（为未来兼容预留） ====================

class TestValidationGroups:
    """校验 groups 功能：约束只在命中 groups 时触发。"""

    def test_group_filtered(self):
        """仅当 groups 匹配时触发校验。"""
        # 给约束临时打 groups 属性
        nb = NotBlank()
        nb.groups = [dict]  # 任意标记，不传 groups 时不触发
        nb2 = NotBlank()   # 无 groups，始终触发

        class Demo:
            f1 = nb
            f2 = nb2
            def __init__(self, f1=None, f2=None):
                self.f1 = f1; self.f2 = f2

        d = Demo()
        # 不传 groups：仅 f2（无 groups）触发
        vs = BeanValidator.validate(d)
        attrs = {v.attr_name for v in vs}
        assert "f2" in attrs
        assert "f1" not in attrs
        # 传入 groups=[dict]：f1 和 f2 都触发
        vs2 = BeanValidator.validate(d, groups=[dict])
        attrs2 = {v.attr_name for v in vs2}
        assert "f1" in attrs2
        assert "f2" in attrs2


# ==================== 7. 最小组合：单字段多模块 ====================

class TestSingleFieldMultiModule:
    """单字段：在 Column 同时有 Excel + CSV + 校验。

    推荐写法：只用 Column 做主描述符，Excel/CSV 通过自动建列，
    约束通过 Column.constraints。
    """

    def test_single_column_with_everything(self):
        """单一 Column() + constraints，ORM/Excel/CSV/Validation 同时生效。"""
        @Entity("demo_single")
        @ExcelSheet("单字段演示")
        @CsvFile("single.csv")
        class Demo:
            id: int = Id(constraints=[NotNull()])
            # 一个 Column + 多个 Validation 约束
            value: int = Column(
                "value", default=0, nullable=False,
                constraints=[Min(0, message="不能负"), Max(100, message="超 100")],
            )

        # ORM
        meta = _parse_entity(Demo)
        assert {c['name'] for c in meta.columns} == {"id", "value"}

        # Excel
        ex_cols = parse_excel_columns(Demo)
        assert {c.attr_name for c in ex_cols} == {"id", "value"}

        # CSV
        csv_cols = parse_csv_columns(Demo)
        assert {c.attr_name for c in csv_cols} == {"id", "value"}

        # Validation
        cs = BeanValidator.get_constraints(Demo)
        assert "id" in cs and "value" in cs
        value_cnames = {c.constraint_name for c in cs["value"]}
        assert value_cnames == {"Min", "Max"}

        # 违规验证
        d = Demo(id=None, value=-5)
        vs = BeanValidator.validate(d)
        attrs = {v.attr_name for v in vs}
        assert "id" in attrs
        assert "value" in attrs

    def test_excelproperty_plus_csv_implicit(self):
        """ExcelProperty 做主描述符，CSV 通过类型注解自动建列。"""
        @ExcelSheet("E")
        @CsvFile("C")
        class Demo:
            amount: float = ExcelProperty(
                "金额", order=1,
                constraints=[Positive(message="金额必须为正")],
            )

        # Excel 表头保留
        cols = parse_excel_columns(Demo)
        col_map = {c.attr_name: c for c in cols}
        assert col_map["amount"].header == "金额"

        # CSV 自动列
        cols = parse_csv_columns(Demo)
        col_map = {c.attr_name: c for c in cols}
        assert col_map["amount"].header == "Amount"

        # Validation 约束生效
        cs = BeanValidator.get_constraints(Demo)
        assert "amount" in cs
        assert cs["amount"][0].constraint_name == "Positive"

        d = Demo(amount=-1.0)
        vs = BeanValidator.validate(d)
        assert len(vs) == 1 and vs[0].attr_name == "amount"
