"""@SelectPage 分页查询注解测试"""
import sqlite3
import pytest
from springbootai.orm.pymybatis import build_session_factory
from springbootai.orm.pymybatis.annotations import SelectPage
from springbootai.orm.pymybatis.mapper.mapper import MapperProxy


@pytest.fixture
def session_factory(tmp_path):
    """文件 SQLite + 25 条测试数据"""
    db_path = str(tmp_path / "test_page.db")
    # 用原生 sqlite3 建表 + 插入数据
    conn = sqlite3.connect(db_path)
    conn.execute('CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, age INTEGER)')
    for i in range(1, 26):
        conn.execute('INSERT INTO users(name, age) VALUES (?, ?)', (f'user{i}', 20 + i))
    conn.commit()
    conn.close()

    factory = build_session_factory({
        'datasource': {'driver': 'sqlite', 'database': db_path},
        'pool': {'min_size': 1, 'max_size': 2},
    })
    yield factory
    factory.close()


class UserMapper:
    """测试用 Mapper"""

    @SelectPage('SELECT id, name, age FROM users WHERE age > #{min_age}')
    def find_page(self, min_age: int, page_num: int, page_size: int):
        pass

    @SelectPage('SELECT id, name, age FROM users')
    def find_all_page(self, page_num: int, page_size: int):
        pass


def _make_proxy(factory):
    session = factory.open_session()
    return MapperProxy(UserMapper, session)


def test_page_with_condition_first_page(session_factory):
    """带条件分页：第1页"""
    proxy = _make_proxy(session_factory)
    result = proxy.find_page(min_age=22, page_num=1, page_size=5)

    assert result['total'] == 23  # age > 22: 23~45 -> 23 条
    assert result['page_num'] == 1
    assert result['page_size'] == 5
    assert len(result['data']) == 5


def test_page_with_condition_second_page(session_factory):
    """带条件分页：第2页"""
    proxy = _make_proxy(session_factory)
    result = proxy.find_page(min_age=22, page_num=2, page_size=5)

    assert result['total'] == 23
    assert len(result['data']) == 5


def test_page_without_condition_first_page(session_factory):
    """无条件分页：第1页"""
    proxy = _make_proxy(session_factory)
    result = proxy.find_all_page(page_num=1, page_size=10)

    assert result['total'] == 25
    assert len(result['data']) == 10


def test_page_without_condition_last_page(session_factory):
    """无条件分页：第3页（只有5条）"""
    proxy = _make_proxy(session_factory)
    result = proxy.find_all_page(page_num=3, page_size=10)

    assert result['total'] == 25
    assert len(result['data']) == 5  # 25 - 2*10 = 5


def test_page_data_content(session_factory):
    """验证返回数据内容正确"""
    proxy = _make_proxy(session_factory)
    result = proxy.find_page(min_age=40, page_num=1, page_size=10)

    # age > 40: 41~45 -> 5 条
    assert result['total'] == 5
    assert len(result['data']) == 5
    for row in result['data']:
        assert row['age'] > 40
