"""SpringBootAI 测试切片模块（对齐 Spring Boot ``@SpringBootTest``/``@WebMvcTest``/``@DataJpaTest``）。

模块组成（``springbootai.test.slicing``）：
- ``SpringBootTest``：全量应用上下文，对齐 ``@SpringBootTest``。
- ``WebMvcTest``：仅 Web 切片（指定 Controller + Mock 依赖 + FastAPI ``TestClient``）。
- ``DataJpaTest``：仅数据切片（内存 SQLite + 建表 + ``PagingAndSortingRepository`` 工厂）。
- ``TestPool``：内存连接池，供数据切片复用。

典型用法（pytest）::

    from springbootai.test import SpringBootTest, WebMvcTest, DataJpaTest

    def test_full_context():
        with SpringBootTest(App, config={"app": {"name": "demo"}}) as ctx:
            svc = ctx.get_bean("user_service")
            ...

    def test_web_layer():
        with WebMvcTest(controllers=[UserController]) as mvc:
            resp = mvc.get_client().get("/users")
            assert resp.status_code == 200

    def test_data_layer():
        with DataJpaTest(entities=[User]) as jpa:
            repo = jpa.repository_for(User)
            repo.save(User(name="tom"))

设计原则：复用既有 ``ApplicationContext``/``WebApplicationContext``/``DdlAutoManager``/
``PagingAndSortingRepository``，不重复造轮子；切片提供 ``close()`` 与上下文管理器语义。

与 Java 的差异：
- Spring Boot 切片用自动配置裁剪；本实现手动注册指定 Bean + Mock 依赖，更轻量直接。
- ``@WebMvcTest`` 自动 Mock ``@Service``/``@Repository``；本实现 Mock 构造函数依赖。
"""
from .slicing import TestPool, SpringBootTest, WebMvcTest, DataJpaTest

__version__ = "2.3.11"

__all__ = [
    "TestPool",
    "SpringBootTest",
    "WebMvcTest",
    "DataJpaTest",
    "__version__",
]
