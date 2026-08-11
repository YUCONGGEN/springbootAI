"""P1-6 测试切片测试。

覆盖 ``spring.test`` 模块：
- ``SpringBootTest``：全量上下文装配 + Bean 获取 + 事件发布 + 配置注入
- ``WebMvcTest``：仅 Controller 切片，依赖 Mock 注入，FastAPI TestClient 路由可达
- ``DataJpaTest``：内存 SQLite 建表 + Repository 工厂 CRUD
- 上下文管理器 ``close()`` 清理

复用既有 ``ApplicationContext``/``WebApplicationContext``/``DdlAutoManager``/``PagingAndSortingRepository``。
"""
import pytest

from spring.annotations.core import (
    SpringBootApplication, Component, Service,
    RestController, RequestMapping, GetMapping, PostMapping, EventListener, ApplicationEvent,
)
from spring.orm.ddl_auto import entity, Id, Column
from spring.test import SpringBootTest, WebMvcTest, DataJpaTest


# ==================== 测试组件定义 ====================

@SpringBootApplication(scan_base_packages=[])
class _MinimalApp:
    pass


class GreetingEvent(ApplicationEvent):
    def __init__(self, message, source=None):
        super().__init__(source=source)
        self.message = message


@Service
class GreetingService:
    def hello(self, name):
        return f"hello {name}"


@Component
class GreetingListener:
    def __init__(self):
        self.received = []

    @EventListener
    def on_greeting(self, event: GreetingEvent):
        self.received.append(event.message)


@RestController
@RequestMapping("/api")
class GreetingController:
    def __init__(self, greeting_service: GreetingService = None):
        self.greeting_service = greeting_service

    @GetMapping("/hello")
    def hello(self, name: str = "world"):
        if self.greeting_service is not None:
            return {"msg": self.greeting_service.hello(name)}
        return {"msg": f"hello {name}"}

    @GetMapping("/items/{item_id}")
    def get_item(self, item_id: int):
        return {"id": item_id}

    @PostMapping("/echo")
    def echo(self, body: dict = None):
        return body or {}


@entity("slice_user")
class SliceUser:
    id = Id()
    name = Column("user_name")
    age = Column()

    def __init__(self, id: int = None, name: str = None, age: int = None):
        self.id = id
        self.name = name
        self.age = age


# ==================== SpringBootTest ====================

class TestSpringBootTest:
    def test_full_context_boots_and_resolves_beans(self):
        # 手动注册组件到上下文（避免依赖包扫描路径）
        from spring.context.bean_definition import BeanDefinition
        with SpringBootTest(_MinimalApp, config={"app": {"name": "demo"}}) as ctx:
            ctx.get_context().bean_factory.register_bean_definition(
                "greeting_service",
                BeanDefinition(bean_class=GreetingService, bean_name="greeting_service"),
            )
            ctx.get_context().bean_factory.register_instance(
                "greeting_service", GreetingService()
            )
            svc = ctx.get_bean("greeting_service")
            assert svc.hello("tom") == "hello tom"

    def test_config_loaded_from_dict(self):
        with SpringBootTest(_MinimalApp, config={"app": {"name": "demo"}}) as ctx:
            assert ctx.get_context().get_value("app.name") == "demo"

    def test_event_publishing(self):
        from spring.context.bean_definition import BeanDefinition
        with SpringBootTest(_MinimalApp) as ctx:
            listener = GreetingListener()
            ctx.get_context().bean_factory.register_bean_definition(
                "greeting_listener",
                BeanDefinition(bean_class=GreetingListener, bean_name="greeting_listener"),
            )
            ctx.get_context().bean_factory.register_instance(
                "greeting_listener", listener
            )
            ctx.get_context()._register_event_listeners()
            ctx.publish_event(GreetingEvent("hi"))
            assert listener.received == ["hi"]

    def test_context_manager_closes(self):
        ctx = SpringBootTest(_MinimalApp, config={})
        ctx.close()
        # 重复 close 不报错
        ctx.close()


# ==================== WebMvcTest ====================

class TestWebMvcTest:
    def test_controller_routes_registered(self):
        with WebMvcTest(controllers=[GreetingController]) as mvc:
            # 依赖被 Mock：配置 Mock 返回可序列化字符串，避免 Result 包装时 JSON 编码失败
            ctrl = mvc.get_controller(GreetingController)
            ctrl.greeting_service.hello.return_value = "hi tom"
            client = mvc.get_client()
            resp = client.get("/api/hello?name=tom")
            assert resp.status_code == 200
            # WebApplicationContext 统一用 Result 包装响应：{code, message, data}
            body = resp.json()
            assert body["code"] == 200
            assert body["data"]["msg"] == "hi tom"

    def test_path_variable(self):
        with WebMvcTest(controllers=[GreetingController]) as mvc:
            resp = mvc.get_client().get("/api/items/42")
            assert resp.status_code == 200
            # Result 包装：业务数据在 data 字段
            assert resp.json()["data"] == {"id": 42}

    def test_post_body(self):
        with WebMvcTest(controllers=[GreetingController]) as mvc:
            resp = mvc.get_client().post("/api/echo", json={"k": "v"})
            assert resp.status_code == 200
            assert resp.json()["data"] == {"k": "v"}

    def test_mock_dependencies_injected(self):
        with WebMvcTest(controllers=[GreetingController], mock_dependencies=True) as mvc:
            ctrl = mvc.get_controller(GreetingController)
            # 构造函数依赖被注入 MagicMock
            assert ctrl.greeting_service is not None

    def test_no_mock_dependencies(self):
        with WebMvcTest(controllers=[GreetingController], mock_dependencies=False) as mvc:
            ctrl = mvc.get_controller(GreetingController)
            # 不 Mock：greeting_service 为 None（构造函数默认值）
            assert ctrl.greeting_service is None
            resp = mvc.get_client().get("/api/hello?name=amy")
            assert resp.json()["data"] == {"msg": "hello amy"}

    def test_empty_controllers_raises(self):
        with pytest.raises(ValueError):
            WebMvcTest(controllers=[])

    def test_get_app_returns_fastapi(self):
        from fastapi import FastAPI
        with WebMvcTest(controllers=[GreetingController]) as mvc:
            assert isinstance(mvc.get_app(), FastAPI)

    def test_context_manager_closes(self):
        mvc = WebMvcTest(controllers=[GreetingController])
        mvc.close()
        mvc.close()  # 重复 close 不报错


# ==================== DataJpaTest ====================

class TestDataJpaTest:
    def test_table_created_and_repository_crud(self):
        with DataJpaTest(entities=[SliceUser]) as jpa:
            repo = jpa.repository_for(SliceUser)
            saved = repo.save(SliceUser(name="tom", age=20))
            assert saved.id is not None
            found = repo.find_by_id(saved.id)
            assert found is not None
            assert found.name == "tom"
            assert found.age == 20

    def test_repository_query_all(self):
        with DataJpaTest(entities=[SliceUser]) as jpa:
            repo = jpa.repository_for(SliceUser)
            repo.save(SliceUser(name="a", age=1))
            repo.save(SliceUser(name="b", age=2))
            all_users = repo.find_all()
            assert len(all_users) == 2

    def test_pool_and_connection_access(self):
        with DataJpaTest(entities=[SliceUser]) as jpa:
            assert jpa.get_pool() is not None
            conn = jpa.get_connection()
            # 直接用原生连接验证表存在
            cur = conn.execute("SELECT count(*) FROM slice_user")
            assert cur.fetchone()[0] == 0

    def test_get_entities(self):
        with DataJpaTest(entities=[SliceUser]) as jpa:
            assert jpa.get_entities() == [SliceUser]

    def test_empty_entities_raises(self):
        with pytest.raises(ValueError):
            DataJpaTest(entities=[])

    def test_context_manager_closes(self):
        jpa = DataJpaTest(entities=[SliceUser])
        jpa.close()
        jpa.close()  # 重复 close 不报错

    def test_multiple_entities(self):
        @entity("slice_product")
        class SliceProduct:
            id = Id()
            title = Column()

            def __init__(self, id=None, title=None):
                self.id = id
                self.title = title

        with DataJpaTest(entities=[SliceUser, SliceProduct]) as jpa:
            user_repo = jpa.repository_for(SliceUser)
            prod_repo = jpa.repository_for(SliceProduct)
            user_repo.save(SliceUser(name="u", age=1))
            prod_repo.save(SliceProduct(title="p"))
            assert len(user_repo.find_all()) == 1
            assert len(prod_repo.find_all()) == 1
