"""SQLite contract tests for the embedded PyMyBatis implementation."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional
import unittest

from spring.orm.pymybatis import build_session_factory
from spring.orm.pymybatis.annotations import Insert, Select, SelectProvider
from spring.orm.pymybatis.dynamic_sql import DynamicSQLProcessor
from spring.orm.pymybatis.mapper import MapperProxy
from spring.orm.pymybatis.xml_parser import XmlParser
from spring.orm.pymybatis.interceptor import Interceptor


@dataclass
class Task:
    name: str
    created_at: datetime
    id: Optional[int] = None


class TaskMapper:
    @Insert(
        "INSERT INTO tasks(name, created_at) VALUES (#{task.name}, #{task.created_at})",
        use_generated_keys=True,
        key_property="id",
    )
    def insert(self, task: Task) -> int:
        pass

    @Select("SELECT id, name, created_at FROM tasks WHERE id = #{task_id}")
    def find_by_id(self, task_id: int) -> Optional[Task]:
        pass

    @Select("SELECT id, name, created_at FROM tasks ORDER BY id")
    def find_all(self) -> List[Task]:
        pass


class ProviderSql:
    @staticmethod
    def by_name(params):
        return "SELECT name FROM tasks WHERE name = #{name}"


class ProviderMapper:
    @SelectProvider(ProviderSql, method="by_name")
    def find_name(self, name: str) -> str:
        pass


class RecordingInterceptor(Interceptor):
    def __init__(self):
        self.calls = []

    def intercept(self, invocation):
        self.calls.append((
            invocation.get_method(), invocation.get_args(), invocation.get_kwargs(),
        ))
        return invocation.proceed()


class PyMyBatisContractTests(unittest.TestCase):
    def setUp(self):
        self.factory = build_session_factory({
            "datasource": {"driver": "sqlite", "database": ":memory:"},
            "pool": {"min_size": 1, "max_size": 1},
            "security": {
                "block_ddl": False,
                "sql_injection_detection": False,
                "sensitive_data_masking": False,
            },
        })
        self.session = self.factory.open_session()
        connection = self.session.get_connection()
        connection.execute(
            "CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "name TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        connection.commit()

    def tearDown(self):
        self.session.close()
        self.factory.close()

    def test_dynamic_sql_bind_and_foreach_keep_parameter_order(self):
        processor = DynamicSQLProcessor(placeholder="?")
        sql, values = processor.process(
            """
            SELECT * FROM tasks
            <bind name="pattern" value="'%' + keyword + '%'" />
            <where>
              <if test="keyword != null">AND name LIKE #{pattern}</if>
            </where>
            AND (code, label) IN
            <foreach collection="items" item="value" index="key" open="(" separator="," close=")">
              (#{value.code}, #{key})
            </foreach>
            """,
            {
                "keyword": "spring",
                "items": {"one": {"code": "A"}, "two": {"code": "B"}},
            },
        )

        self.assertEqual(
            "SELECT * FROM tasks WHERE name LIKE ? AND (code, label) IN ((?, ?),(?, ?))",
            sql,
        )
        self.assertEqual(["%spring%", "A", "one", "B", "two"], values)

    def test_xml_statement_options_and_include_properties(self):
        xml = """
        <mapper namespace="tests.TaskMapper">
          <sql id="taskColumns">${prefix}id, ${prefix}name</sql>
          <select id="findNames" resultType="str" fetchSize="20" timeout="3"
                  useCache="false" flushCache="true">
            SELECT <include refid="taskColumns"><property value="t." name="prefix" /></include>
            FROM tasks t
          </select>
          <insert id="insertTask" useGeneratedKeys="true" keyProperty="task.id"
                  keyColumn="id" timeout="5">
            INSERT INTO tasks(name, created_at) VALUES (#{task.name}, #{task.created_at})
          </insert>
        </mapper>
        """
        parser = XmlParser()
        parser.parse_string(xml)

        select = parser.get_mapped_statement("tests.TaskMapper.findNames")
        insert = parser.get_mapped_statement("tests.TaskMapper.insertTask")

        self.assertIn("SELECT t.id, t.name", select.sql)
        self.assertEqual(20, select.fetch_size)
        self.assertEqual(3, select.timeout)
        self.assertFalse(select.use_cache)
        self.assertTrue(select.flush_cache)
        self.assertTrue(insert.use_generated_keys)
        self.assertEqual("task.id", insert.key_property)
        self.assertEqual("id", insert.key_column)

    def test_xml_statement_options_are_applied_by_session(self):
        self.session.insert(
            "INSERT INTO tasks(name, created_at) VALUES (#{name}, #{created_at})",
            {"name": "xml", "created_at": "2026-08-07 12:00:00"},
        )
        self.session.select("SELECT id, name FROM tasks")
        self.assertEqual(1, self.session.sql_cache.size())

        with TemporaryDirectory() as directory:
            mapper_path = Path(directory) / "TaskMapper.xml"
            mapper_path.write_text(
                """
                <mapper namespace="tests.TaskMapper">
                  <select id="names" resultType="str" fetchSize="10" timeout="2"
                          useCache="false" flushCache="true">
                    SELECT name FROM tasks ORDER BY id
                  </select>
                  <update id="renameWithoutFlush" flushCache="false">
                    UPDATE tasks SET name = #{name} WHERE id = #{id}
                  </update>
                </mapper>
                """,
                encoding="utf-8",
            )
            self.session.configuration.mapper_locations = [str(mapper_path)]
            names = self.session.select("tests.TaskMapper.names")

        self.assertEqual(["xml"], names)
        self.assertEqual(0, self.session.sql_cache.size())

        self.session.select("SELECT id, name FROM tasks")
        self.assertEqual(1, self.session.sql_cache.size())
        self.session.update(
            "tests.TaskMapper.renameWithoutFlush", {"id": 1, "name": "renamed"}
        )
        self.assertEqual(1, self.session.sql_cache.size())

    def test_mapper_return_annotations_and_type_handlers(self):
        mapper = MapperProxy(TaskMapper, self.session)
        task = Task(name="first", created_at=datetime(2026, 8, 7, 10, 30, 0))

        generated_id = mapper.insert(task)
        loaded = mapper.find_by_id(generated_id)
        tasks = mapper.find_all()

        self.assertEqual(generated_id, task.id)
        self.assertIsInstance(loaded, Task)
        self.assertEqual("first", loaded.name)
        self.assertEqual(["first"], [item.name for item in tasks])
        raw = self.session.select_one(
            "SELECT created_at FROM tasks WHERE id = #{id}", {"id": generated_id}
        )
        self.assertEqual("2026-08-07 10:30:00", raw)

    def test_cached_rows_are_not_mutable_by_the_caller(self):
        self.session.insert(
            "INSERT INTO tasks(name, created_at) VALUES (#{name}, #{created_at})",
            {"name": "cached", "created_at": datetime(2026, 8, 7, 12, 0, 0)},
        )

        first = self.session.select("SELECT id, name FROM tasks")
        first[0]["name"] = "changed-by-caller"
        second = self.session.select("SELECT id, name FROM tasks")

        self.assertEqual("cached", second[0]["name"])

    def test_nested_transaction_rolls_back_only_to_savepoint(self):
        with self.session.transaction():
            self.session.insert(
                "INSERT INTO tasks(name, created_at) VALUES (#{name}, #{created_at})",
                {"name": "outer-before", "created_at": "2026-08-07 12:00:00"},
            )
            try:
                with self.session.transaction(propagation="NESTED"):
                    self.session.insert(
                        "INSERT INTO tasks(name, created_at) VALUES (#{name}, #{created_at})",
                        {"name": "nested", "created_at": "2026-08-07 12:01:00"},
                    )
                    raise RuntimeError("force nested rollback")
            except RuntimeError:
                pass
            self.session.insert(
                "INSERT INTO tasks(name, created_at) VALUES (#{name}, #{created_at})",
                {"name": "outer-after", "created_at": "2026-08-07 12:02:00"},
            )

        rows = self.session.select("SELECT name FROM tasks ORDER BY id")
        self.assertEqual(["outer-before", "outer-after"], [row["name"] for row in rows])

    def test_all_transaction_propagations(self):
        # An on-disk database is required because REQUIRES_NEW obtains a
        # separate physical connection, unlike SQLite's per-connection :memory:.
        self.session.close()
        self.factory.close()
        with TemporaryDirectory() as directory:
            database = str(Path(directory) / "transactions.sqlite")
            factory = build_session_factory({
                "datasource": {"driver": "sqlite", "database": database},
                "pool": {"min_size": 1, "max_size": 2, "wait_timeout": 1},
                "security": {
                    "block_ddl": False,
                    "sql_injection_detection": False,
                    "sensitive_data_masking": False,
                },
            })
            session = factory.open_session()
            connection = session.get_connection()
            connection.execute("CREATE TABLE entries (name TEXT NOT NULL)")
            connection.commit()

            with self.assertRaisesRegex(RuntimeError, "MANDATORY"):
                with session.transaction(propagation="MANDATORY"):
                    pass
            with session.transaction(propagation="SUPPORTS"):
                session.insert("INSERT INTO entries(name) VALUES (#{name})", {"name": "supports"})

            with session.transaction():
                with self.assertRaisesRegex(RuntimeError, "NEVER"):
                    with session.transaction(propagation="NEVER"):
                        pass
                # Keep the outer SQLite transaction deferred until both
                # independently committed branches finish.
                with session.transaction(propagation="REQUIRES_NEW"):
                    session.insert("INSERT INTO entries(name) VALUES (#{name})", {"name": "new"})
                with session.transaction(propagation="NOT_SUPPORTED"):
                    session.insert("INSERT INTO entries(name) VALUES (#{name})", {"name": "not-supported"})
                with session.transaction(propagation="REQUIRED"):
                    session.insert("INSERT INTO entries(name) VALUES (#{name})", {"name": "required"})
                with session.transaction(propagation="MANDATORY"):
                    session.insert("INSERT INTO entries(name) VALUES (#{name})", {"name": "mandatory"})
                with session.transaction(propagation="SUPPORTS"):
                    session.insert("INSERT INTO entries(name) VALUES (#{name})", {"name": "joined"})
                try:
                    with session.transaction(propagation="NESTED"):
                        session.insert("INSERT INTO entries(name) VALUES (#{name})", {"name": "nested"})
                        raise RuntimeError("nested failure")
                except RuntimeError:
                    pass
                session.insert("INSERT INTO entries(name) VALUES (#{name})", {"name": "outer"})

            rows = session.select("SELECT name FROM entries ORDER BY name")
            self.assertEqual(
                ["joined", "mandatory", "new", "not-supported", "outer", "required", "supports"],
                [row["name"] for row in rows],
            )
            session.close()
            factory.close()

    def test_xml_nested_mappings_select_key_and_database_id(self):
        xml = """
        <mapper namespace="tests.AdvancedMapper">
          <resultMap id="author" type="dict">
            <id column="author_id" property="id" />
            <result column="author_name" property="name" />
          </resultMap>
          <resultMap id="book" type="dict">
            <id column="book_id" property="id" />
            <result column="book_title" property="title" />
            <association property="author" resultMap="author" />
          </resultMap>
          <select id="findBook" resultMap="book">
            SELECT 7 AS book_id, 'SpringBootAI' AS book_title,
                   3 AS author_id, 'Ada' AS author_name
          </select>
          <insert id="insertWithSelectKey" keyProperty="id">
            <selectKey keyProperty="id" resultType="int" order="BEFORE">SELECT 99</selectKey>
            INSERT INTO generated_tasks(id, name) VALUES (#{id}, #{name})
          </insert>
          <select id="vendorName" databaseId="sqlite" resultType="str">SELECT 'sqlite'</select>
          <select id="vendorName" databaseId="mysql" resultType="str">SELECT 'mysql'</select>
        </mapper>
        """
        with TemporaryDirectory() as directory:
            mapper_path = Path(directory) / "AdvancedMapper.xml"
            mapper_path.write_text(xml, encoding="utf-8")
            self.session.configuration.mapper_locations = [str(mapper_path)]
            connection = self.session.get_connection()
            connection.execute("CREATE TABLE generated_tasks (id INTEGER PRIMARY KEY, name TEXT)")
            connection.commit()

            mapped = self.session.select("tests.AdvancedMapper.findBook")
            params = {"name": "select-key"}
            self.session.insert("tests.AdvancedMapper.insertWithSelectKey", params)

            self.assertEqual("SpringBootAI", mapped[0]["title"])
            self.assertEqual("Ada", mapped[0]["author"]["name"])
            self.assertEqual(99, params["id"])
            self.assertEqual("select-key", self.session.select_one("SELECT name FROM generated_tasks WHERE id = 99"))
            self.assertEqual(["sqlite"], self.session.select("tests.AdvancedMapper.vendorName"))

    def test_sql_provider_annotation_executes_generated_sql(self):
        self.session.insert(
            "INSERT INTO tasks(name, created_at) VALUES (#{name}, #{created_at})",
            {"name": "provided", "created_at": "2026-08-07 12:00:00"},
        )
        mapper = MapperProxy(ProviderMapper, self.session)
        self.assertEqual("provided", mapper.find_name("provided"))

    def test_configured_interceptors_wrap_sql_session_calls(self):
        interceptor = RecordingInterceptor()
        self.session.interceptor_chain.add_interceptor(interceptor)
        self.session.insert(
            "INSERT INTO tasks(name, created_at) VALUES (#{name}, #{created_at})",
            {"name": "intercepted", "created_at": "2026-08-07 12:00:00"},
            use_generated_keys=True,
        )
        rows = self.session.select(
            "SELECT name FROM tasks WHERE name = #{name}",
            {"name": "intercepted"},
            use_cache=False,
        )

        self.assertEqual(["intercepted"], [row["name"] for row in rows])
        self.assertEqual(["insert", "select"], [call[0] for call in interceptor.calls])
        self.assertTrue(interceptor.calls[0][2]["use_generated_keys"])
        self.assertFalse(interceptor.calls[1][2]["use_cache"])


if __name__ == "__main__":
    unittest.main()
