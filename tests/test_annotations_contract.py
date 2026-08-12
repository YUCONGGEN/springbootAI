"""Contract coverage for SpringBootAI, Cloud and PyMyBatis annotations."""

import asyncio
import sys
import types
import unittest
from unittest.mock import Mock, patch

from spring.annotations import *  # noqa: F401,F403 - this test audits public exports
from spring.annotations import __all__ as annotation_exports
from spring.annotations import cloud as cloud_annotations
from spring.annotations import core as core_annotations
from spring.annotations import messaging as messaging_annotations
from spring.annotations.core import ApplicationEvent, get_spring_annotations
from spring.event import ApplicationEventPublisher
from spring.orm import Mapper, MapperScan
from spring.orm.pymybatis.annotations import (
    CacheNamespace,
    DataSource,
    Delete,
    DeleteProvider,
    Insert,
    InsertProvider,
    Options,
    Param,
    Result,
    ResultMap,
    Select,
    SelectProvider,
    Transactional as MapperTransactional,
    Update,
    UpdateProvider,
)


class DemoEvent(ApplicationEvent):
    pass


class AnnotationContractTests(unittest.TestCase):
    def _assert_decorator(self, annotation):
        def target():
            return "ok"

        decorated = annotation(target)
        self.assertTrue(callable(decorated))
        attached = get_spring_annotations(decorated)
        self.assertIn(annotation, attached)
        return decorated, annotation

    def test_every_core_annotation_constructs_and_decorates(self):
        factories = {
            "EventListener": lambda: EventListener(DemoEvent, order=2),
            "SpringBootApplication": lambda: SpringBootApplication(["demo"]),
            "ComponentScan": lambda: ComponentScan(["demo.service"]),
            "RestController": lambda: RestController("api"),
            "Controller": lambda: Controller("web"),
            "RequestMapping": lambda: RequestMapping(
                value=["/items"], method=["get", "post"], consumes="application/json",
                produces="application/json",
            ),
            "GetMapping": lambda: GetMapping(value="/items"),
            "PostMapping": lambda: PostMapping("/items"),
            "PutMapping": lambda: PutMapping("/items/{id}"),
            "PatchMapping": lambda: PatchMapping("/items/{id}"),
            "DeleteMapping": lambda: DeleteMapping("/items/{id}"),
            "Service": lambda: Service("itemService"),
            "Component": lambda: Component("itemComponent"),
            "Aspect": lambda: Aspect("auditAspect"),
            "Pointcut": lambda: Pointcut("execution(* *.Service.*(..))"),
            "Before": lambda: Before("execution(* *.Service.*(..))"),
            "After": lambda: After("execution(* *.Service.*(..))"),
            "Around": lambda: Around("execution(* *.Service.*(..))"),
            "AfterReturning": lambda: AfterReturning(
                "execution(* *.Service.*(..))", returning="result"
            ),
            "AfterThrowing": lambda: AfterThrowing(
                "execution(* *.Service.*(..))", throwing="exception"
            ),
            "Repository": lambda: Repository("itemRepository"),
            "Autowired": lambda: Autowired(required=False),
            "Qualifier": lambda: Qualifier("primaryItem"),
            "Configuration": lambda: Configuration(proxy_bean_methods=False),
            "Scope": lambda: Scope("prototype"),
            "Bean": lambda: Bean("itemBean", scope="prototype", init_method="init"),
            "Value": lambda: Value("items.timeout", default=3),
            "ConfigurationProperties": lambda: ConfigurationProperties("items"),
            "Valid": lambda: Valid([DemoEvent]),
            "Validated": lambda: Validated([DemoEvent]),
            "CrossOrigin": lambda: CrossOrigin(
                origins=["https://example.test"], methods=["GET"],
                allowed_headers=["X-Trace"], allow_credentials=True, max_age=30,
            ),
            "ControllerAdvice": lambda: ControllerAdvice(),
            "ExceptionHandler": lambda: ExceptionHandler(ValueError),
            "Slf4j": lambda: Slf4j("demo"),
            "LogExecutionTime": lambda: LogExecutionTime("debug"),
            "PostConstruct": lambda: PostConstruct(),
            "PreDestroy": lambda: PreDestroy(),
            "Primary": lambda: Primary(),
            "Profile": lambda: Profile(["dev", "test"]),
            "Lazy": lambda: Lazy(),
            "ResponseStatus": lambda: ResponseStatus(201, "created"),
            "Transactional": lambda: Transactional(
                propagation="REQUIRES_NEW", rollback_for=[ValueError],
                no_rollback_for=[KeyError],
            ),
            "Cacheable": lambda: Cacheable("items", key="#id", condition="id > 0"),
            "Retryable": lambda: Retryable(value=(ValueError,), max_retries=2),
            "Recover": lambda: Recover(ValueError),
            "Async": lambda: Async(),
            "Scheduled": lambda: Scheduled(fixed_rate=1000, initial_delay=5),
            "AsyncResult": lambda: AsyncResult("done"),
            "RateLimit": lambda: RateLimit(max_requests=5, time_window=10, key="user"),
            "CircuitBreaker": lambda: CircuitBreaker(
                failure_threshold=2, recovery_timeout=4, fallback_method="fallback",
            ),
            "Idempotent": lambda: Idempotent(key="#request_id", expire=60),
            "AuditLog": lambda: AuditLog(action="create", target="item", level="WARN"),
            "FeatureToggle": lambda: FeatureToggle("new-items", default=True),
            "Lock": lambda: Lock(key="#item_id", expire=8, wait_timeout=2),
            "Metrics": lambda: Metrics(name="items.created", tags=["region"]),
            "Synchronized": lambda: Synchronized("items-lock"),
            "Validate": lambda: Validate(field="name", min_length=2, max_length=30),
            "Trace": lambda: Trace(trace_id_key="X-Request-ID", span_name="items"),
            "PreAuthorize": lambda: PreAuthorize("hasRole('ROLE_ADMIN')"),
            "PostAuthorize": lambda: PostAuthorize("returnObject != null"),
            "Secured": lambda: Secured(["ROLE_ADMIN", "ROLE_EDITOR"]),
            "Authenticate": lambda: Authenticate(),
        }
        expected = {
            name for name, value in vars(core_annotations).items()
            if isinstance(value, type)
            and issubclass(value, core_annotations.SpringAnnotation)
            and value not in {core_annotations.SpringAnnotation}
        }
        self.assertEqual(expected, set(factories))
        for name, factory in factories.items():
            with self.subTest(annotation=name):
                self._assert_decorator(factory())

    def test_core_mapping_and_parameter_aliases(self):
        request = RequestMapping(path="/items", method="get")
        self.assertEqual("/items", request.path)
        self.assertEqual(["GET"], request.method)
        self.assertEqual("items", RequestParam(value="items").name)
        self.assertEqual("id", PathVariable(value="id").name)
        self.assertFalse(RequestBody(value=False).required)
        self.assertEqual("X-Trace", RequestHeader(value="X-Trace").name)
        self.assertEqual("sid", CookieValue(value="sid").name)
        with self.assertRaises(TypeError):
            RequestMapping(path="/a", value="/b")
        with self.assertRaises(TypeError):
            GetMapping(path="/a", value="/b")

    def test_annotation_validation_rejects_invalid_configuration(self):
        with self.assertRaises(ValueError):
            Scope("request")
        with self.assertRaises(ValueError):
            Scheduled(fixed_rate=1, fixed_delay=1)
        with self.assertRaises(ValueError):
            Scheduled(fixed_rate=0)
        with self.assertRaises(ValueError):
            Retryable(max_retries=0)
        with self.assertRaises(ValueError):
            Retryable(max_retries=2, max_attempts=3)

    def test_log_execution_time_sync_and_async_preserve_results(self):
        @LogExecutionTime("info")
        def sync(value):
            return value + 1

        @LogExecutionTime("info")
        async def asynchronous(value):
            return value + 2

        self.assertEqual(2, sync(1))
        self.assertEqual(4, asyncio.run(asynchronous(2)))
        self.assertEqual("sync", sync.__name__)
        self.assertEqual("asynchronous", asynchronous.__name__)

    def test_event_listener_annotation_and_publisher_dispatch(self):
        publisher = ApplicationEventPublisher()
        received = []

        @EventListener(DemoEvent, order=1)
        def listener(event):
            received.append(event.source)

        annotation = get_spring_annotations(listener)[0]
        self.assertIsInstance(annotation, EventListener)
        self.assertEqual(DemoEvent, annotation.event_type)
        publisher.add_listener(listener, annotation.event_type, annotation.order)
        event = publisher.publish_event(DemoEvent("source"))
        self.assertEqual("source", event.source)
        self.assertEqual(["source"], received)

    def test_cloud_annotations_cover_all_public_cloud_types(self):
        factories = {
            "EnableDiscoveryClient": lambda: EnableDiscoveryClient("nacos"),
            "NacosValue": lambda: NacosValue("items.name", auto_refreshed=True),
            "RefreshScope": lambda: RefreshScope(),
            "EnableFeignClients": lambda: EnableFeignClients(["demo.clients"]),
            "FeignClient": lambda: FeignClient("inventory", path="/api", url="http://inventory"),
            "SentinelResource": lambda: SentinelResource(
                "items", block_handler="blocked", fallback="fallback", hotkey="id",
            ),
            "EnableGateway": lambda: EnableGateway(),
            "LoadBalanced": lambda: LoadBalanced("random"),
            "GlobalTransactional": lambda: GlobalTransactional(
                timeout=5000, name="create-item", rollback_for=[ValueError],
            ),
        }
        expected = {
            name for name, value in vars(cloud_annotations).items()
            if isinstance(value, type)
            and issubclass(value, core_annotations.SpringAnnotation)
            and value.__module__ == cloud_annotations.__name__
        }
        self.assertEqual(expected, set(factories))
        for name, factory in factories.items():
            with self.subTest(annotation=name):
                _, annotation = self._assert_decorator(factory())
                self.assertTrue(annotation._annotation_type)

        self.assertIs(Valid, cloud_annotations.Valid)
        self.assertIs(Validated, cloud_annotations.Validated)

    def test_rabbit_annotation_and_template_paths(self):
        annotation = RabbitListener(
            queue="orders", exchange="events", routing_key="orders.created",
            auto_ack=True, prefetch_count=10,
        )
        self.assertEqual("orders", annotation.queue)
        self.assertEqual("orders.created", annotation.routing_key)
        self.assertEqual("messaging", annotation._annotation_type)

        events = []
        decorated = messaging_annotations.rabbit_listener_decorator(annotation)(
            lambda body: events.append(body)
        )
        decorated("body")
        self.assertEqual(["body"], events)

        fake_client = Mock()
        fake_rabbitmq = types.ModuleType("spring.messaging.rabbitmq")
        fake_rabbitmq.rabbitmq_client = fake_client
        with patch.dict(sys.modules, {"spring.messaging.rabbitmq": fake_rabbitmq}):
            messaging_annotations.register_rabbit_listener(annotation, decorated)
            RabbitTemplate().send("orders", {"id": 1})
            RabbitTemplate().send(
                "orders", {"id": 2}, exchange="events", routing_key="orders.updated",
                persistent=False,
            )
        fake_client.declare_queue.assert_called_once_with("orders")
        self.assertEqual(1, fake_client.publish_to_queue.call_count)
        fake_client.publish.assert_called_once_with(
            exchange_name="events", routing_key="orders.updated",
            body={"id": 2}, persistent=False,
        )

    def test_pymybatis_annotation_metadata_and_exports(self):
        class Provider:
            @staticmethod
            def sql(params):
                return "SELECT 1"

        class MapperContract:
            @Select("SELECT * FROM items", result_map="itemMap", result_type="dict", timeout=2)
            @Options(fetch_size=20, use_cache=False)
            def find(self):
                pass

            @Insert("INSERT INTO items(name) VALUES (#{name})", key_property="id", use_generated_keys=True)
            def insert(self, name):
                pass

            @Update("UPDATE items SET name = #{name}", timeout=3)
            def update(self, name):
                pass

            @Delete("DELETE FROM items WHERE id = #{id}")
            def delete(self, id):
                pass

            @SelectProvider(Provider, method="sql", result_type="int")
            def provided(self):
                pass

            @InsertProvider(Provider, method="sql", use_generated_keys=True, key_property="id")
            def provided_insert(self):
                pass

            @UpdateProvider(Provider, method="sql", timeout=4)
            def provided_update(self):
                pass

            @DeleteProvider(Provider, method="sql", timeout=5)
            def provided_delete(self):
                pass

        select = MapperContract.find.select
        self.assertEqual("itemMap", select.result_map)
        self.assertEqual(2, select.timeout)
        self.assertFalse(MapperContract.find.options.use_cache)
        self.assertTrue(MapperContract.insert.insert.use_generated_keys)
        self.assertEqual("id", MapperContract.insert.insert.key_property)
        self.assertEqual(Provider, MapperContract.provided.select_provider.provider_type)
        self.assertEqual(Provider, MapperContract.provided_insert.insert_provider.provider_type)
        self.assertEqual(4, MapperContract.provided_update.update_provider.options["timeout"])
        self.assertEqual(5, MapperContract.provided_delete.delete_provider.options["timeout"])

        result_map = ResultMap(
            "itemMap", "dict", [Result(column="item_id", property="id")]
        )

        @result_map
        class AnnotatedMapper:
            pass

        self.assertEqual("id", result_map.get_property("item_id"))
        self.assertIs(AnnotatedMapper.__result_maps__[0], result_map)
        cache_namespace = CacheNamespace(
            eviction="FIFO", flush_interval=60, size=10, read_write=False,
        )
        datasource = DataSource("items")
        mapper_transaction = MapperTransactional(propagation="REQUIRES_NEW")

        @cache_namespace
        @datasource
        @mapper_transaction
        def configured_method():
            pass

        self.assertIs(cache_namespace, configured_method.cache_namespace)
        self.assertIs(datasource, configured_method.data_source)
        self.assertIs(mapper_transaction, configured_method.transactional)
        self.assertEqual("FIFO", cache_namespace.eviction)
        self.assertEqual(60, cache_namespace.flush_interval)
        self.assertFalse(cache_namespace.read_write)
        self.assertEqual("items", datasource.value)
        self.assertEqual("id", Param("id").value)
        self.assertEqual(20, Options(fetch_size=20).fetch_size)
        self.assertEqual("REQUIRES_NEW", mapper_transaction.propagation)

        @Mapper
        class SpringMapper:
            pass

        @MapperScan(base_packages=["demo.mappers"])
        class ScanConfiguration:
            pass

        self.assertTrue(get_spring_annotations(SpringMapper))
        self.assertEqual(["demo.mappers"], get_spring_annotations(ScanConfiguration)[0].base_packages)

    def test_annotation_exports_are_importable(self):
        for name in annotation_exports:
            with self.subTest(name=name):
                self.assertTrue(hasattr(__import__("spring.annotations", fromlist=[name]), name))

    def test_repeatable_audit_and_metrics_decorators_stack(self):
        """同一方法叠加多个 AOP 注解应均能被 get_spring_annotations 收集。"""
        @Metrics(name="orders.created", tags=["region"])
        @AuditLog(action="create", target="order", level="INFO")
        def create_order(user_id):
            return {"order_id": user_id}

        attached = get_spring_annotations(create_order)
        kinds = {type(a) for a in attached}
        self.assertIn(AuditLog, kinds)
        self.assertIn(Metrics, kinds)
        # 装饰器自底向上应用：AuditLog 先附加，Metrics 后附加
        self.assertIsInstance(attached[0], AuditLog)
        self.assertIsInstance(attached[1], Metrics)
        self.assertEqual("orders.created", attached[1].name)

    def test_value_and_configuration_properties_defaults(self):
        """@Value 带 default，@ConfigurationProperties 绑定前缀，元数据正确。"""
        value_ann = Value("app.timeout", default=15)
        self.assertEqual("app.timeout", value_ann.value)
        self.assertEqual(15, value_ann.default)

        props_ann = ConfigurationProperties("app.orders")
        self.assertEqual("app.orders", props_ann.prefix)

        @props_ann
        class OrderProps:
            pass

        attached = get_spring_annotations(OrderProps)
        self.assertEqual(1, len(attached))
        self.assertIs(props_ann, attached[0])


if __name__ == "__main__":
    unittest.main()
