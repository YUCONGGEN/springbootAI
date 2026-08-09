"""A deterministic SpringPy application used by the k6 load profiles."""

import asyncio
import hashlib
import io
import os
import sqlite3
import threading
import time

from spring import create_app
from spring.annotations import (
    ApplicationEvent,
    Autowired,
    CacheEvict,
    CachePut,
    Cacheable,
    Conditional,
    ConditionalOnBean,
    ConditionalOnClass,
    ConditionalOnMissingBean,
    ConditionalOnProperty,
    ConfigurationProperties,
    GetMapping,
    PostMapping,
    RequestBody,
    RequestMapping,
    RestController,
    Service,
    SpringBootApplication,
    Validated,
)
from spring.cloud.gateway import GatewayRouter
from spring.config.binding import (
    ConfigurationPropertiesBinder,
    NestedConfigurationProperties,
    validate_configuration_properties,
)
from spring.context.application_context import ApplicationContext
from spring.annotations.conditional import all_conditions_match
from spring.csv import CsvIgnore, CsvProperty, EasyCsv, csv_file
from spring.data import (
    DataRepository,
    Order,
    Pageable,
    PagingAndSortingRepository,
    Sort,
    Specifications,
)
from spring.datasource import DS, Master, Slave, DynamicRoutingDataSource
from spring.datasource.context import DataSourceContextHolder
from spring.i18n import Locale, StaticMessageSource
from spring.orm import Column, Id, OptimisticLockExecutor, Transient, Version, entity
from spring.tx import (
    TransactionPhase,
    TransactionSynchronizationManager,
    TransactionalEventListener,
    transaction_sync_scope,
)
from spring.validation import BeanValidate, Email, Min, NotBlank, Size
from spring.websocket import (
    MessageEndpoint,
    MessageMapping,
    SendTo,
    SendToUser,
    ServerEndpoint,
    SubscribeMapping,
    WebSocketRouter,
)
from spring.web.swagger import (
    ApiResponse,
    Operation,
    Parameter,
    SecurityRequirement,
    SecurityScheme,
    Tag,
)


_sync_lock = threading.Lock()
_active_sync = 0
_max_active_sync = 0


class ValidationPayload:
    name = NotBlank(message="name must not be blank")
    age = Min(0, message="age must be non-negative")
    email = Email(message="email must be valid")
    password = Size(min=8, max=64, message="password length must be between 8 and 64")

    def __init__(self, name=None, age=None, email=None, password=None):
        self.name = name
        self.age = age
        self.email = email
        self.password = password


@csv_file("benchmark-records")
class CsvBenchmarkRecord:
    record_id = CsvProperty("ID", order=1)
    name = CsvProperty("Name", order=2)
    score = CsvProperty("Score", order=3)
    active = CsvProperty("Active", order=4)
    internal_note = CsvIgnore()

    def __init__(
        self,
        record_id: int = None,
        name: str = None,
        score: float = None,
        active: bool = None,
        internal_note: str = None,
    ):
        self.record_id = record_id
        self.name = name
        self.score = score
        self.active = active
        self.internal_note = internal_note


@entity("benchmark_versioned_record")
class VersionedBenchmarkRecord:
    record_id = Id(name="id")
    name = Column(name="record_name", nullable=False, length=100)
    version = Version()
    request_note = Transient()

    def __init__(self, record_id=None, name=None, version=0, request_note=None):
        self.record_id = record_id
        self.name = name
        self.version = version
        self.request_note = request_note


@entity("benchmark_data_record")
class DataBenchmarkRecord:
    record_id = Id(name="id")
    name = Column(name="record_name", nullable=False, length=100)
    score = Column()
    category = Column()
    request_note = Transient()

    def __init__(
        self,
        record_id=None,
        name=None,
        score=None,
        category=None,
        request_note=None,
    ):
        self.record_id = record_id
        self.name = name
        self.score = score
        self.category = category
        self.request_note = request_note


@DataRepository(DataBenchmarkRecord)
class DataBenchmarkRepository(PagingAndSortingRepository):
    pass


@NestedConfigurationProperties
class BenchmarkDatabaseProperties:
    url: str = ""
    pool_size: int = 0


@Validated
@ConfigurationProperties("benchmark.binding")
class BenchmarkBindingProperties:
    name: str = NotBlank(message="name must not be blank")
    replicas: int = Min(1, message="replicas must be positive")
    database: BenchmarkDatabaseProperties = None


class BenchmarkConnection:
    def __init__(self, pool_name):
        self.pool_name = pool_name


class BenchmarkPool:
    def __init__(self, name):
        self.name = name
        self.borrowed = 0
        self.returned = 0
        self._lock = threading.Lock()

    def get_connection(self):
        with self._lock:
            self.borrowed += 1
        return BenchmarkConnection(self.name)

    def return_connection(self, _connection):
        with self._lock:
            self.returned += 1

    def get_pool_stats(self):
        with self._lock:
            return {
                "name": self.name,
                "borrowed": self.borrowed,
                "returned": self.returned,
            }


class BenchmarkTransactionEvent(ApplicationEvent):
    def __init__(self, source):
        super().__init__(source)
        self.phases = []


_message_source = StaticMessageSource()
_message_source.add_message("benchmark.greeting", Locale("en", "US"), "Hello, {0}!")
_message_source.add_message("benchmark.greeting", Locale("zh", "CN"), "Hello CN, {0}!")
_message_source.add_message("benchmark.greeting", Locale(""), "Hello default, {0}!")


@Service
class BenchmarkFeatureService:
    def __init__(self):
        self._source = {}
        self._source_lock = threading.Lock()
        self._loads = 0
        self._loads_by_item = {}

    @BeanValidate("payload")
    def validate_payload(self, payload: ValidationPayload):
        return {
            "valid": True,
            "fields": 4,
            "name": payload.name,
        }

    @Cacheable(value="benchmark-items", key="{item_id}")
    def get_item(self, item_id: int):
        with self._source_lock:
            self._loads += 1
            self._loads_by_item[item_id] = self._loads_by_item.get(item_id, 0) + 1
            return self._source.get(item_id, {"id": item_id, "value": "missing"})

    @CachePut(value="benchmark-items", key="{item_id}")
    def put_item(self, item_id: int, value: str):
        result = {"id": item_id, "value": value}
        with self._source_lock:
            self._source[item_id] = result
        return result

    @CacheEvict(value="benchmark-items", key="{item_id}")
    def evict_item(self, item_id: int):
        return item_id

    def exercise_cache(self, item_id: int, value: str):
        with self._source_lock:
            before_loads = self._loads_by_item.get(item_id, 0)
        try:
            updated = self.put_item(item_id, value)
            cached = self.get_item(item_id)
            self.evict_item(item_id)
            reloaded = self.get_item(item_id)
            with self._source_lock:
                item_loads = self._loads_by_item.get(item_id, 0)
                total_loads = self._loads
            return {
                "consistent": updated == cached == reloaded,
                "cache_hit": item_loads == before_loads + 1,
                "loads": total_loads,
            }
        finally:
            self.evict_item(item_id)
            with self._source_lock:
                self._source.pop(item_id, None)
                self._loads_by_item.pop(item_id, None)


@Conditional(lambda context: context is not None)
@ConditionalOnProperty("benchmark.features.conditional", having_value="enabled")
@ConditionalOnBean(bean_name="application_event_publisher")
@ConditionalOnMissingBean(bean_name="benchmark_disabled_marker")
@ConditionalOnClass(name="spring.context.application_context.ApplicationContext")
@Service
class ConditionalBenchmarkService:
    def __init__(self):
        self._context = ApplicationContext.get_instance()

    def evaluate(self, evaluations: int):
        context = self._context
        matched = sum(
            1 for _ in range(evaluations)
            if all_conditions_match(self.__class__, context)
        )
        return {"matched": matched, "evaluations": evaluations}


@Service
class BenchmarkRoutingService:
    def __init__(self):
        master = BenchmarkPool("master")
        slave_1 = BenchmarkPool("slave_1")
        slave_2 = BenchmarkPool("slave_2")
        report = BenchmarkPool("report")
        self.router = DynamicRoutingDataSource(
            target_data_sources={
                "master": master,
                "slave_1": slave_1,
                "slave_2": slave_2,
                "report": report,
            },
            default_target_data_source=master,
            slave_keys=["slave_1", "slave_2"],
        )

    def _borrow_and_return(self):
        connection = self.router.get_connection()
        try:
            pool_name = connection.pool_name
        finally:
            self.router.return_connection(connection)
        return pool_name, not hasattr(connection, "__spring_ds_source__")

    @Master
    def from_master(self):
        return self._borrow_and_return()

    @Slave
    def from_slave(self):
        return self._borrow_and_return()

    @DS("report")
    def from_report(self):
        return self._borrow_and_return()


@Service
class BenchmarkTransactionListener:
    @TransactionalEventListener(
        phase=TransactionPhase.BEFORE_COMMIT,
        event_type=BenchmarkTransactionEvent,
    )
    def before_commit(self, event):
        event.phases.append("before_commit")

    @TransactionalEventListener(
        phase=TransactionPhase.AFTER_COMMIT,
        event_type=BenchmarkTransactionEvent,
    )
    def after_commit(self, event):
        event.phases.append("after_commit")

    @TransactionalEventListener(
        phase=TransactionPhase.AFTER_ROLLBACK,
        event_type=BenchmarkTransactionEvent,
    )
    def after_rollback(self, event):
        event.phases.append("after_rollback")

    @TransactionalEventListener(
        phase=TransactionPhase.AFTER_COMPLETION,
        event_type=BenchmarkTransactionEvent,
    )
    def after_completion(self, event):
        event.phases.append("after_completion")


@ServerEndpoint("/ws/benchmark-echo")
class BenchmarkWebSocketEndpoint:
    async def on_open(self, session):
        await session.send_text("ready")

    async def on_message(self, session, message):
        await session.send_text(f"echo:{message}")


@MessageEndpoint
class BenchmarkMessageEndpoint:
    @SubscribeMapping("/topic/bootstrap")
    def bootstrap(self, _payload):
        return {"ready": True}

    @MessageMapping("/echo")
    @SendToUser()
    def echo(self, payload):
        return {"echo": payload}

    @MessageMapping("/broadcast")
    @SendTo("/topic/benchmark")
    def broadcast(self, payload):
        return {"broadcast": payload}


@SecurityScheme(
    name="BenchmarkBearer",
    scheme="bearer",
    bearer_format="JWT",
    description="Benchmark-only authentication scheme",
)
@Tag(name="SpringPy Benchmark", description="Framework feature performance paths")
@RequestMapping("/benchmark")
@RestController
class BenchmarkController:
    @Autowired
    def __init__(
        self,
        feature_service: BenchmarkFeatureService,
        conditional_service: ConditionalBenchmarkService,
        routing_service: BenchmarkRoutingService,
    ):
        self.feature_service = feature_service
        self.conditional_service = conditional_service
        self.routing_service = routing_service

    @GetMapping("/async")
    async def async_endpoint(self, delay_ms: int = 0):
        delay_ms = min(max(delay_ms, 0), 5000)
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000)
        return {"kind": "async", "pid": os.getpid(), "delay_ms": delay_ms}

    @GetMapping("/sync")
    def sync_endpoint(self, delay_ms: int = 20):
        global _active_sync, _max_active_sync

        delay_ms = min(max(delay_ms, 0), 5000)
        with _sync_lock:
            _active_sync += 1
            _max_active_sync = max(_max_active_sync, _active_sync)
            active = _active_sync
        try:
            if delay_ms:
                time.sleep(delay_ms / 1000)
            return {
                "kind": "sync",
                "pid": os.getpid(),
                "thread": threading.get_ident(),
                "delay_ms": delay_ms,
                "active_sync": active,
            }
        finally:
            with _sync_lock:
                _active_sync -= 1

    @GetMapping("/cpu")
    def cpu_endpoint(self, iterations: int = 1000):
        iterations = min(max(iterations, 1), 100000)
        digest = b"springpy"
        for _ in range(iterations):
            digest = hashlib.sha256(digest).digest()
        return {
            "kind": "cpu",
            "pid": os.getpid(),
            "iterations": iterations,
            "digest": digest.hex()[:16],
        }

    @PostMapping("/echo")
    async def echo_endpoint(self, payload: dict = RequestBody()):
        return {
            "kind": "echo",
            "pid": os.getpid(),
            "size": len(str(payload)),
            "payload": payload,
        }

    @PostMapping("/validation")
    def validation_endpoint(self, payload: dict = RequestBody()):
        dto = ValidationPayload(
            name=payload.get("name"),
            age=payload.get("age"),
            email=payload.get("email"),
            password=payload.get("password"),
        )
        result = self.feature_service.validate_payload(dto)
        return {"kind": "validation", **result}

    @PostMapping("/cache")
    def cache_endpoint(self, payload: dict = RequestBody()):
        item_id = int(payload.get("id", 0))
        value = str(payload.get("value", "springpy"))
        result = self.feature_service.exercise_cache(item_id, value)
        return {"kind": "cache", "id": item_id, **result}

    @GetMapping("/csv")
    def csv_endpoint(self, rows: int = 50):
        rows = min(max(rows, 1), 2000)
        source = [
            CsvBenchmarkRecord(
                record_id=index,
                name=f"record-{index}",
                score=index / 10,
                active=index % 2 == 0,
                internal_note="not-persisted",
            )
            for index in range(rows)
        ]
        buffer = io.StringIO()
        EasyCsv.write(buffer, head=CsvBenchmarkRecord).doWrite(source)
        csv_size = len(buffer.getvalue().encode("utf-8"))
        buffer.seek(0)
        restored = EasyCsv.read(buffer, head=CsvBenchmarkRecord).doRead()
        round_trip = (
            len(restored) == rows
            and restored[-1].record_id == rows - 1
            and restored[-1].internal_note is None
        )
        return {
            "kind": "csv",
            "rows": rows,
            "bytes": csv_size,
            "round_trip": round_trip,
        }

    @GetMapping("/jpa")
    def jpa_endpoint(self):
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute(
                "CREATE TABLE benchmark_versioned_record "
                "(id INTEGER PRIMARY KEY, record_name TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0)"
            )
            connection.execute(
                "INSERT INTO benchmark_versioned_record (id, record_name, version) VALUES (1, 'before', 0)"
            )
            connection.commit()

            executor = OptimisticLockExecutor(connection, dialect="sqlite")
            current = VersionedBenchmarkRecord(
                record_id=1,
                name="before",
                version=0,
                request_note="not-mapped",
            )
            updated = executor.try_update(
                VersionedBenchmarkRecord,
                current,
                set_fields={"name": "after"},
            )
            stale_conflict = not executor.try_update(
                VersionedBenchmarkRecord,
                VersionedBenchmarkRecord(record_id=1, version=0),
                set_fields={"name": "stale"},
            )
            mapped_fields = {
                column["py_name"] for column in executor._parse_columns(VersionedBenchmarkRecord)
            }
            return {
                "kind": "jpa",
                "updated": updated,
                "conflict_detected": stale_conflict,
                "version": current.version,
                "transient_mapped": "request_note" in mapped_fields,
            }
        finally:
            connection.close()

    @GetMapping("/conditional")
    def conditional_endpoint(self, evaluations: int = 100):
        evaluations = min(max(evaluations, 1), 10000)
        result = self.conditional_service.evaluate(evaluations)
        return {"kind": "conditional", **result}

    @Operation(
        summary="Page benchmark data",
        description="Exercises Spring Data paging, sorting, specifications, and transient fields.",
        operation_id="benchmarkData",
    )
    @ApiResponse(code=200, description="Paged benchmark data")
    @Parameter(
        name="rows",
        description="Number of in-memory rows to generate before paging",
        example=100,
    )
    @SecurityRequirement(name="BenchmarkBearer")
    @GetMapping("/data")
    def data_endpoint(self, rows: int = 100):
        rows = min(max(rows, 20), 2000)
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute(
                "CREATE TABLE benchmark_data_record "
                "(id INTEGER PRIMARY KEY, record_name TEXT NOT NULL, score INTEGER, category TEXT)"
            )
            connection.executemany(
                "INSERT INTO benchmark_data_record "
                "(id, record_name, score, category) VALUES (?, ?, ?, ?)",
                [
                    (index, f"record-{index}", index, "even" if index % 2 == 0 else "odd")
                    for index in range(rows)
                ],
            )
            connection.commit()
            repository = DataBenchmarkRepository(
                connection,
                DataBenchmarkRecord,
                dialect="sqlite",
            )
            specification = Specifications.and_(
                Specifications.greater_equal("score", rows // 2),
                Specifications.equal("category", "even"),
            )
            page = repository.find_all(
                specification=specification,
                pageable=Pageable.of(0, 10, Sort(Order.desc("score"))),
            )
            scores = [record.score for record in page.content]
            expected_total = sum(
                1 for index in range(rows)
                if index >= rows // 2 and index % 2 == 0
            )
            return {
                "kind": "data",
                "rows": rows,
                "total": page.total,
                "page_size": page.number_of_elements,
                "sorted": scores == sorted(scores, reverse=True),
                "expected_total": expected_total,
                "repository_entity": DataBenchmarkRepository.__data_repository__.entity_class.__name__,
                "transient_mapped": "request_note" in repository._col_map,
            }
        finally:
            connection.close()

    @GetMapping("/datasource")
    def datasource_endpoint(self):
        routed = [
            self.routing_service.from_master(),
            self.routing_service.from_slave(),
            self.routing_service.from_slave(),
            self.routing_service.from_report(),
        ]
        selected = [entry[0] for entry in routed]
        self.routing_service.router.get_pool_stats()
        return {
            "kind": "datasource",
            "selected": selected,
            "routed_to_slaves": all(
                pool_name in {"slave_1", "slave_2"}
                for pool_name in selected[1:3]
            ),
            "returned": all(entry[1] for entry in routed),
            "context_cleared": DataSourceContextHolder.get() is None,
        }

    @GetMapping("/tx-event")
    def transaction_event_endpoint(self):
        publisher = benchmark_context.tx_event_publisher
        committed = BenchmarkTransactionEvent("commit")
        with transaction_sync_scope() as synchronization:
            publisher.publish_event(committed)
            synchronization.trigger_before_commit()
            synchronization.trigger_after_commit()
            synchronization.trigger_after_completion("commit")

        rolled_back = BenchmarkTransactionEvent("rollback")
        with transaction_sync_scope() as synchronization:
            publisher.publish_event(rolled_back)
            synchronization.trigger_after_rollback()
            synchronization.trigger_after_completion("rollback")

        return {
            "kind": "tx_event",
            "commit_phases": committed.phases,
            "rollback_phases": rolled_back.phases,
            "context_cleared": not TransactionSynchronizationManager.is_synchronization_active(),
        }

    @GetMapping("/config-binding")
    def config_binding_endpoint(self, bindings: int = 25):
        bindings = min(max(bindings, 1), 1000)
        last = None
        for index in range(bindings):
            properties = BenchmarkBindingProperties()
            ConfigurationPropertiesBinder.bind(
                properties,
                {
                    "name": f"benchmark-{index}",
                    "replicas": "3",
                    "database": {
                        "url": "sqlite:///:memory:",
                        "pool-size": "8",
                    },
                },
            )
            validate_configuration_properties(properties)
            last = properties
        return {
            "kind": "config_binding",
            "bindings": bindings,
            "valid": (
                last is not None
                and last.replicas == 3
                and isinstance(last.database, BenchmarkDatabaseProperties)
                and last.database.pool_size == 8
            ),
        }

    @GetMapping("/i18n")
    def i18n_endpoint(self, messages: int = 100):
        messages = min(max(messages, 1), 10000)
        resolved = []
        locales = (Locale("en", "US"), Locale("zh", "CN"), Locale("fr", "FR"))
        for index in range(messages):
            resolved.append(
                _message_source.getMessage(
                    "benchmark.greeting",
                    [index],
                    locales[index % len(locales)],
                )
            )
        return {
            "kind": "i18n",
            "messages": messages,
            "resolved": len(resolved),
            "fallback": any(message.startswith("Hello default") for message in resolved),
        }

    @GetMapping("/upstream")
    async def upstream_endpoint(self):
        await asyncio.sleep(0.005)
        return {"kind": "upstream", "pid": os.getpid()}

    @GetMapping("/stats")
    async def stats_endpoint(self):
        with _sync_lock:
            active = _active_sync
            maximum = _max_active_sync
        return {
            "pid": os.getpid(),
            "active_sync": active,
            "max_active_sync": maximum,
        }


@SpringBootApplication(scan_base_packages=["tests_performance"])
class BenchmarkApplication:
    pass


app = create_app(BenchmarkApplication)
benchmark_context = app.state.spring_application.application_context

gateway = GatewayRouter(
    default_filters=[],
    timeout=float(os.getenv("GATEWAY_TIMEOUT", "2")),
    max_body_size=1024 * 1024,
)
gateway.route(
    "/gateway/**",
    uri=os.getenv("GATEWAY_UPSTREAM", "http://127.0.0.1:8080"),
    strip_prefix=True,
    route_id="benchmark-loopback",
)
gateway.install(app, "/gateway/{path:path}")

websocket_router = WebSocketRouter()
websocket_router.add_endpoint("/ws/benchmark-echo", BenchmarkWebSocketEndpoint)
websocket_router.add_message_endpoint("/ws/benchmark-app", BenchmarkMessageEndpoint)
websocket_router.install(app)


@app.middleware("http")
async def expose_worker_pid(request, call_next):
    response = await call_next(request)
    response.headers["X-Worker-Pid"] = str(os.getpid())
    return response
