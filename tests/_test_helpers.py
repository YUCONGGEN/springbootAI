"""
测试辅助工具：安全导入 spring 子模块而不触发整个包初始化
通过在导入前设置必要的 mock 来避免缺失依赖错误

重要：仅当可选依赖缺失（被替换为 _MockModule stub）时才注入 mock 属性；
若真实模块已安装则保持原样，避免污染需要真实 fastapi/starlette/pydantic/yaml
的集成测试（如 tests_runtime/、test_test_slicing、test_i18n_module）。
"""

import sys
import types
from unittest.mock import MagicMock


class _MockModule(types.ModuleType):
    """可以自动返回MagicMock属性的mock模块"""

    def __init__(self, name):
        super().__init__(name)
        self.__path__ = []
        self.__package__ = name
        self.__file__ = f'<mock {name}>'
        self.__all__ = []

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        mod = _MockModule(f"{self.__name__}.{name}")
        setattr(self, name, mod)
        sys.modules[mod.__name__] = mod
        return mod

    def __call__(self, *args, **kwargs):
        return MagicMock()


def _is_stub(mod) -> bool:
    """判断模块是否为 _MockModule stub（而非真实已安装模块）。"""
    return isinstance(mod, _MockModule)


def _install_module_mocks():
    """安装必要的模块mock，防止因可选依赖缺失导致导入失败。

    仅对缺失依赖（stub）注入 mock 属性；真实已安装模块保持原样。
    """

    def _make_stub_module(name):
        mod = _MockModule(name)
        sys.modules[name] = mod
        return mod

    _mock_module_names = [
        'fastapi',
        'fastapi.routing',
        'fastapi.responses',
        'fastapi.exceptions',
        'fastapi.middleware',
        'fastapi.middleware.cors',
        'fastapi.staticfiles',
        'uvicorn',
        'redis',
        'redis.asyncio',
        'redis.exceptions',
        'pika',
        'pika.exceptions',
        'nacos',
        'nacos_sdk_python',
        'prometheus_client',
        'loguru',
        'pydantic',
        'requests',
        'requests.exceptions',
        'sqlalchemy',
        'sqlalchemy.orm',
        'sqlalchemy.engine',
        'sqlalchemy.engine.url',
        'sqlalchemy.schema',
        'sqlalchemy.sql',
        'sqlalchemy.sql.expression',
        'sqlalchemy.ext',
        'sqlalchemy.ext.declarative',
        'sqlalchemy.ext.asyncio',
        'sqlalchemy.dialects',
        'sqlalchemy.dialects.mysql',
        'sqlalchemy.dialects.postgresql',
        'sqlalchemy.dialects.sqlite',
        'sqlalchemy.event',
        'sqlalchemy.pool',
        'sqlalchemy.types',
        'sqlalchemy.exc',
        'psycopg2',
        'pymysql',
        'pymysql.cursors',
        'pymysql.err',
        'pymysql.constants',
        'DBUtils',
        'DBUtils.PooledDB',
        'DBUtils.PersistentDB',
        'DBUtils.SimplePooledDB',
        'sqlglot',
        'sqlglot.errors',
        'yaml',
        'dotenv',
        'pybreaker',
        'starlette',
        'starlette.requests',
        'starlette.responses',
        'starlette.middleware',
        'starlette.exceptions',
        'starlette.routing',
        'anyio',
        'httpx',
    ]

    for name in _mock_module_names:
        if name not in sys.modules:
            try:
                __import__(name)
            except ImportError:
                _make_stub_module(name)

    # ---- fastapi：仅 stub 时注入 mock 属性 ----
    fastapi = sys.modules['fastapi']
    if _is_stub(fastapi):
        fastapi.FastAPI = MagicMock
        fastapi.Request = MagicMock
        fastapi.Response = MagicMock
        fastapi.APIRouter = MagicMock
        fastapi.HTTPException = type('HTTPException', (Exception,), {'__init__': lambda self, *a, **kw: Exception.__init__(self)})
        fastapi.Depends = lambda *a, **kw: MagicMock()
        fastapi.Header = lambda *a, **kw: MagicMock()
        fastapi.Query = lambda *a, **kw: MagicMock()
        fastapi.Body = lambda *a, **kw: MagicMock()
        fastapi.Path = lambda *a, **kw: MagicMock()
        fastapi.File = lambda *a, **kw: MagicMock()
        fastapi.UploadFile = MagicMock
        fastapi.status = MagicMock()
        fastapi.status.HTTP_200_OK = 200
        fastapi.status.HTTP_201_CREATED = 201
        fastapi.status.HTTP_400_BAD_REQUEST = 400
        fastapi.status.HTTP_401_UNAUTHORIZED = 401
        fastapi.status.HTTP_403_FORBIDDEN = 403
        fastapi.status.HTTP_404_NOT_FOUND = 404
        fastapi.status.HTTP_500_INTERNAL_SERVER_ERROR = 500

    # ---- pydantic：仅 stub 时注入 mock 属性 ----
    pydantic = sys.modules['pydantic']
    if _is_stub(pydantic):
        class _BaseModel:
            """mock pydantic BaseModel"""
            def __init__(self, **data):
                for k, v in data.items():
                    setattr(self, k, v)

            def model_dump(self, *a, **kw):
                return self.__dict__.copy()

            def dict(self, *a, **kw):
                return self.__dict__.copy()

            @classmethod
            def model_validate(cls, data, *a, **kw):
                return cls(**data) if isinstance(data, dict) else cls()

            @classmethod
            def parse_obj(cls, data):
                return cls(**data) if isinstance(data, dict) else cls()

        pydantic.BaseModel = _BaseModel
        pydantic.Field = lambda *a, **kw: None
        pydantic.ValidationError = type('ValidationError', (ValueError,), {})
        pydantic.validator = lambda *a, **kw: (lambda f: f)
        pydantic.field_validator = lambda *a, **kw: (lambda f: f)

    # ---- pymysql：仅 stub 时注入 mock 属性 ----
    pymysql = sys.modules['pymysql']
    if _is_stub(pymysql):
        pymysql_cursors = sys.modules['pymysql.cursors']
        pymysql_cursors.DictCursor = MagicMock
        pymysql_cursors.Cursor = MagicMock
        pymysql.connect = MagicMock()
        pymysql.err = sys.modules['pymysql.err']
        pymysql.err.OperationalError = type('OperationalError', (Exception,), {})
        pymysql.err.IntegrityError = type('IntegrityError', (Exception,), {})
        pymysql.err.ProgrammingError = type('ProgrammingError', (Exception,), {})

    # ---- psycopg2：仅 stub 时注入 mock 属性 ----
    psycopg2 = sys.modules['psycopg2']
    if _is_stub(psycopg2):
        psycopg2.connect = MagicMock()

    # ---- yaml：仅 stub 时注入 mock 属性 ----
    yaml_mod = sys.modules['yaml']
    if _is_stub(yaml_mod):
        yaml_mod.safe_load = MagicMock(return_value={})
        yaml_mod.load = MagicMock(return_value={})
        yaml_mod.dump = MagicMock(return_value='')
        yaml_mod.YAMLError = type('YAMLError', (Exception,), {})

    # ---- dotenv：仅 stub 时注入 mock 属性 ----
    dotenv_mod = sys.modules['dotenv']
    if _is_stub(dotenv_mod):
        dotenv_mod.load_dotenv = MagicMock(return_value=True)

    # ---- prometheus_client：仅 stub 时注入 mock 属性 ----
    prom = sys.modules['prometheus_client']
    if _is_stub(prom):
        prom.Counter = MagicMock
        prom.Histogram = MagicMock
        prom.Gauge = MagicMock
        prom.Summary = MagicMock
        prom.generate_latest = MagicMock(return_value=b'')
        prom.CONTENT_TYPE_LATEST = 'text/plain'
        prom.make_wsgi_app = MagicMock()
        prom.make_asgi_app = MagicMock()

    # ---- sqlalchemy：仅 stub 时注入 mock 属性 ----
    sa = sys.modules['sqlalchemy']
    if _is_stub(sa):
        sa_orm = sys.modules['sqlalchemy.orm']

        _sa_base = type('Base', (), {})

        def _declarative_base(*a, **kw):
            return _sa_base

        sa_orm.declarative_base = _declarative_base
        sa_orm.sessionmaker = MagicMock
        sa_orm.Session = MagicMock
        sa_orm.relationship = MagicMock()
        sa_orm.Mapped = MagicMock()
        sa_orm.mapped_column = MagicMock()
        sa_orm.column_property = MagicMock()
        sa_orm.Query = MagicMock

        sa_ext_decl = sys.modules['sqlalchemy.ext.declarative']
        sa_ext_decl.declarative_base = _declarative_base

        sa.create_engine = MagicMock()
        sa.Column = MagicMock()
        sa.Integer = MagicMock()
        sa.String = MagicMock()
        sa.Text = MagicMock()
        sa.Boolean = MagicMock()
        sa.DateTime = MagicMock()
        sa.Float = MagicMock()
        sa.Numeric = MagicMock()
        sa.ForeignKey = MagicMock()
        sa.Table = MagicMock()
        sa.MetaData = MagicMock()
        sa.Index = MagicMock()
        sa.UniqueConstraint = MagicMock()
        sa.ForeignKeyConstraint = MagicMock()
        sa.PrimaryKeyConstraint = MagicMock()
        sa.CheckConstraint = MagicMock()
        sa.select = MagicMock()
        sa.insert = MagicMock()
        sa.update = MagicMock()
        sa.delete = MagicMock()
        sa.text = lambda s: s
        sa.and_ = lambda *a: a
        sa.or_ = lambda *a: a
        sa.not_ = lambda x: x
        sa.case = MagicMock()
        sa.cast = MagicMock()
        sa.func = MagicMock()
        sa.func.count = MagicMock()
        sa.func.now = MagicMock()
        sa.exists = MagicMock()
        sa.bindparam = MagicMock()
        sa.outparam = MagicMock()
        sa.engine = sys.modules['sqlalchemy.engine']
        sa.engine.create_engine = MagicMock()
        sa.engine.URL = MagicMock()
        sa.event = sys.modules['sqlalchemy.event']
        sa.event.listen = MagicMock()
        sa.pool = sys.modules['sqlalchemy.pool']
        sa.pool.QueuePool = MagicMock
        sa.pool.NullPool = MagicMock
        sa.pool.StaticPool = MagicMock
        sa.types = sys.modules['sqlalchemy.types']
        sa.exc = sys.modules['sqlalchemy.exc']
        sa.exc.SQLAlchemyError = type('SQLAlchemyError', (Exception,), {})
        sa.exc.IntegrityError = type('IntegrityError', (Exception,), {})
        sa.exc.OperationalError = type('OperationalError', (Exception,), {})
        sa.exc.NoResultFound = type('NoResultFound', (Exception,), {})

    # ---- redis：仅 stub 时注入 mock 属性 ----
    redis_mod = sys.modules['redis']
    if _is_stub(redis_mod):
        redis_mod.Redis = MagicMock
        redis_mod.ConnectionPool = MagicMock
        redis_mod.StrictRedis = MagicMock
        redis_mod.asyncio = sys.modules['redis.asyncio']
        redis_mod.asyncio.Redis = MagicMock
        redis_mod.exceptions = sys.modules['redis.exceptions']
        redis_mod.exceptions.ConnectionError = type('ConnectionError', (Exception,), {})
        redis_mod.exceptions.TimeoutError = type('TimeoutError', (Exception,), {})

    # ---- uvicorn：仅 stub 时注入 mock 属性 ----
    uvicorn_mod = sys.modules['uvicorn']
    if _is_stub(uvicorn_mod):
        uvicorn_mod.run = MagicMock()
        uvicorn_mod.Config = MagicMock
        uvicorn_mod.Server = MagicMock

    # ---- loguru：仅 stub 时注入 mock 属性 ----
    loguru_mod = sys.modules['loguru']
    if _is_stub(loguru_mod):
        loguru_mod.logger = MagicMock()

    # ---- requests：仅 stub 时注入 mock 属性 ----
    requests_mod = sys.modules['requests']
    if _is_stub(requests_mod):
        requests_mod.get = MagicMock()
        requests_mod.post = MagicMock()
        requests_mod.put = MagicMock()
        requests_mod.delete = MagicMock()
        requests_mod.patch = MagicMock()
        requests_mod.Session = MagicMock
        requests_mod.Response = MagicMock
        requests_mod.exceptions = sys.modules['requests.exceptions']
        requests_mod.exceptions.RequestException = type('RequestException', (Exception,), {})
        requests_mod.exceptions.ConnectionError = type('ConnectionError', (Exception,), {})
        requests_mod.exceptions.Timeout = type('Timeout', (Exception,), {})

    # ---- pika：仅 stub 时注入 mock 属性 ----
    pika_mod = sys.modules['pika']
    if _is_stub(pika_mod):
        pika_mod.BlockingConnection = MagicMock
        pika_mod.ConnectionParameters = MagicMock
        pika_mod.PlainCredentials = MagicMock
        pika_mod.BasicProperties = MagicMock
        pika_mod.exceptions = sys.modules['pika.exceptions']
        pika_mod.exceptions.ConnectionClosed = type('ConnectionClosed', (Exception,), {})
        pika_mod.exceptions.ChannelClosed = type('ChannelClosed', (Exception,), {})

    # ---- nacos：仅 stub 时注入 mock 属性 ----
    nacos_mod = sys.modules['nacos']
    if _is_stub(nacos_mod):
        nacos_sdk_mod = sys.modules['nacos_sdk_python']
        nacos_sdk_mod.NacosClient = MagicMock

    # ---- DBUtils：仅 stub 时注入 mock 属性 ----
    dbutils_mod = sys.modules['DBUtils']
    if _is_stub(dbutils_mod):
        dbutils_pool = sys.modules['DBUtils.PooledDB']
        dbutils_pool.PooledDB = MagicMock
        dbutils_mod.PooledDB = dbutils_pool.PooledDB
        dbutils_persist = sys.modules['DBUtils.PersistentDB']
        dbutils_persist.PersistentDB = MagicMock
        dbutils_mod.PersistentDB = dbutils_persist.PersistentDB

    # ---- sqlglot：仅 stub 时注入 mock 属性 ----
    sqlglot_mod = sys.modules['sqlglot']
    if _is_stub(sqlglot_mod):
        sqlglot_errors = sys.modules['sqlglot.errors']
        sqlglot_errors.ParseError = type('ParseError', (Exception,), {})

        def _parse_one(*a, **kw):
            raise ImportError("mock sqlglot - AST validation disabled")
        sqlglot_mod.parse_one = _parse_one
        sqlglot_mod.transpile = MagicMock()

    # ---- pybreaker：仅 stub 时注入 mock 属性 ----
    pybreaker_mod = sys.modules.get('pybreaker')
    if pybreaker_mod is None or _is_stub(pybreaker_mod):
        pybreaker_mod = _MockModule('pybreaker')
        pybreaker_mod.CircuitBreaker = MagicMock
        pybreaker_mod.CircuitBreakerError = type('CircuitBreakerError', (Exception,), {})
        sys.modules['pybreaker'] = pybreaker_mod

    # ---- starlette：仅 stub 时注入 mock 属性 ----
    for starlette_name in ['starlette', 'starlette.requests', 'starlette.responses',
                           'starlette.middleware', 'starlette.exceptions', 'starlette.routing']:
        if starlette_name in sys.modules:
            mod = sys.modules[starlette_name]
            if not _is_stub(mod):
                continue
            if starlette_name == 'starlette.requests':
                mod.Request = MagicMock
            elif starlette_name == 'starlette.responses':
                mod.JSONResponse = MagicMock
                mod.Response = MagicMock
                mod.HTMLResponse = MagicMock
                mod.PlainTextResponse = MagicMock
            elif starlette_name == 'starlette.exceptions':
                mod.HTTPException = fastapi.HTTPException if _is_stub(fastapi) else type(
                    'HTTPException', (Exception,), {}
                )


_install_module_mocks()
