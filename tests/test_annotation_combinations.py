"""组合注解测试 - 验证多个注解叠加在同一类/方法上的元数据收集、顺序保持、继承隔离与跨层组合。

覆盖：类级组合、方法级组合、AOP 四合一、@Retryable+@Cacheable、重复 @Validate、
安全+Web、Cloud+Cloud、事务+缓存、异步+结果包装、ControllerAdvice+ExceptionHandler、
声明顺序保持、继承隔离、同类多注解计数等。
"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import tests._test_helpers  # noqa: F401  安装模块mock

from spring.annotations.core import (
    RestController, Controller, RequestMapping, GetMapping, PostMapping,
    Service, Component, Repository, Configuration, Bean, Scope,
    Autowired, Slf4j, LogExecutionTime, PostConstruct, PreDestroy,
    Primary, Profile, Lazy, Value, ConfigurationProperties,
    CrossOrigin, ControllerAdvice, ExceptionHandler, ResponseStatus,
    Transactional, Cacheable, Retryable, Async, AsyncResult, Scheduled,
    RateLimit, CircuitBreaker, Idempotent, AuditLog, FeatureToggle,
    Lock, Metrics, Synchronized, Validate, Trace,
    PreAuthorize, Secured, Authenticate, Valid, Validated,
    get_spring_annotations,
)
from spring.retry.retry_annotations import Backoff
from spring.annotations.cloud import (
    EnableDiscoveryClient, NacosValue, RefreshScope, EnableFeignClients,
    FeignClient, SentinelResource, EnableGateway, LoadBalanced,
    GlobalTransactional,
)


# ==================== 类级组合 ====================

class TestClassLevelCombinations:
    def test_rest_controller_with_mapping_and_logger(self):
        """@RestController + @RequestMapping + @Slf4j 三合一类级组合"""
        @RestController
        @RequestMapping("/api/users")
        @Slf4j("userLogger")
        class UserController:
            pass

        anns = get_spring_annotations(UserController)
        assert len(anns) == 3
        # 装饰器自底向上应用：Slf4j 先附加，RequestMapping 次，RestController 最后
        assert isinstance(anns[0], Slf4j)
        assert isinstance(anns[1], RequestMapping)
        assert isinstance(anns[2], RestController)
        assert anns[1].path == "/api/users"
        assert anns[0].logger_name == "userLogger"

    def test_service_with_logger_post_construct_pre_destroy(self):
        """@Service + @Slf4j + @PostConstruct + @PreDestroy 生命周期组合"""
        @PreDestroy
        @PostConstruct
        @Slf4j
        @Service("orderService")
        class OrderService:
            pass

        anns = get_spring_annotations(OrderService)
        types = [type(a) for a in anns]
        assert types == [Service, Slf4j, PostConstruct, PreDestroy]
        assert anns[0].value == "orderService"

    def test_configuration_with_primary_profile_lazy(self):
        """@Configuration + @Primary + @Profile + @Lazy Bean 元信息组合"""
        @Lazy
        @Profile(["prod"])
        @Primary
        @Configuration(proxy_bean_methods=False)
        class ProdConfig:
            pass

        anns = get_spring_annotations(ProdConfig)
        assert len(anns) == 4
        assert isinstance(anns[0], Configuration)
        assert isinstance(anns[1], Primary)
        assert isinstance(anns[2], Profile)
        assert isinstance(anns[3], Lazy)
        assert anns[0].proxyBeanMethods is False
        assert anns[2].value == ["prod"]
        assert anns[3].value is True

    def test_repository_with_configuration_properties(self):
        """@Repository + @ConfigurationProperties + @Value 数据访问层组合"""
        @ConfigurationProperties("repo.cache")
        @Repository("userRepo")
        class UserRepo:
            pass

        anns = get_spring_annotations(UserRepo)
        assert len(anns) == 2
        assert isinstance(anns[0], Repository)
        assert isinstance(anns[1], ConfigurationProperties)
        assert anns[0].value == "userRepo"
        assert anns[1].prefix == "repo.cache"

    def test_controller_advice_with_response_status(self):
        """@ControllerAdvice + @ResponseStatus + @CrossOrigin 全局处理组合"""
        @CrossOrigin(origins=["https://app.test"])
        @ResponseStatus(500, "server-error")
        @ControllerAdvice
        class GlobalAdvice:
            pass

        anns = get_spring_annotations(GlobalAdvice)
        assert len(anns) == 3
        assert isinstance(anns[0], ControllerAdvice)
        assert isinstance(anns[1], ResponseStatus)
        assert isinstance(anns[2], CrossOrigin)
        assert anns[1].code == 500


# ==================== 方法级 AOP 组合 ====================

class TestMethodLevelAopCombinations:
    def test_four_aop_combo_rate_limit_audit_metrics_trace(self):
        """@RateLimit + @AuditLog + @Metrics + @Trace 四合一方法组合"""
        @RateLimit(max_requests=20, time_window=30)
        @AuditLog(action="combo", target="combo_target")
        @Metrics(name="combo.op", tags=["env"])
        @Trace(span_name="combo_span")
        def combo_op(param: str):
            return param

        anns = get_spring_annotations(combo_op)
        types = [type(a) for a in anns]
        assert types == [Trace, Metrics, AuditLog, RateLimit]
        assert anns[3].max_requests == 20
        assert anns[2].action == "combo"
        assert anns[1].name == "combo.op"
        assert anns[0].span_name == "combo_span"

    def test_retryable_with_cacheable(self):
        """@Retryable + @Cacheable 缓存重试组合"""
        @Retryable(max_attempts=3, backoff=500)
        @Cacheable(value="external_data", key="#key")
        def fetch(key: str):
            return key

        anns = get_spring_annotations(fetch)
        assert len(anns) == 2
        assert isinstance(anns[0], Cacheable)
        assert isinstance(anns[1], Retryable)
        assert anns[0].value == "external_data"
        assert anns[1].max_retries == 3
        assert isinstance(anns[1].backoff, Backoff)

    def test_transactional_with_cacheable_and_metrics(self):
        """@Transactional + @Cacheable + @Metrics 事务+缓存+监控组合"""
        @Transactional(propagation="REQUIRES_NEW")
        @Cacheable(value="orders", condition="#id > 0")
        @Metrics(name="orders.update")
        def update_order(id: int):
            return id

        anns = get_spring_annotations(update_order)
        types = [type(a) for a in anns]
        assert types == [Metrics, Cacheable, Transactional]
        assert anns[2].propagation == "REQUIRES_NEW"
        assert anns[1].condition == "#id > 0"
        assert anns[0].name == "orders.update"

    def test_rate_limit_with_idempotent_and_lock(self):
        """@RateLimit + @Idempotent + @Lock 并发安全三合一组合"""
        @RateLimit(max_requests=10, time_window=60)
        @Idempotent(key="#req_id", expire=120)
        @Lock(key="#resource", expire=30, wait_timeout=3)
        def pay(req_id: str, resource: str):
            return {"req_id": req_id}

        anns = get_spring_annotations(pay)
        types = [type(a) for a in anns]
        assert types == [Lock, Idempotent, RateLimit]
        assert anns[2].max_requests == 10
        assert anns[1].key == "#req_id"
        assert anns[0].wait_timeout == 3

    def test_audit_log_with_metrics_and_log_execution_time(self):
        """@AuditLog + @Metrics + @LogExecutionTime 审计+监控+计时组合"""
        @AuditLog(action="export", target="report")
        @Metrics(name="report.export")
        @LogExecutionTime("debug")
        def export_report(name: str):
            return name

        anns = get_spring_annotations(export_report)
        types = [type(a) for a in anns]
        assert types == [LogExecutionTime, Metrics, AuditLog]
        assert anns[2].action == "export"
        assert anns[1].name == "report.export"
        assert anns[0].log_level == "debug"


# ==================== 重复注解 ====================

class TestRepeatableCombinations:
    def test_multiple_validate_on_same_method(self):
        """同一方法叠加多个 @Validate（重复注解）"""
        @Validate(field="email", regex=r'^[\w]+@[\w]+\.\w+$', message="bad email")
        @Validate(field="username", min_length=3, max_length=50, message="bad username")
        @Validate(field="age", min=18, max=120, message="bad age")
        def register(email, username, age):
            return (email, username, age)

        anns = get_spring_annotations(register)
        assert len(anns) == 3
        # 自底向上：age Validate 先附加，username 次，email 最后
        assert all(isinstance(a, Validate) for a in anns)
        assert anns[2].field == "email"
        assert anns[1].field == "username"
        assert anns[0].field == "age"
        # 每个注解元数据独立保持
        assert anns[2].regex is not None
        assert anns[1].min_length == 3
        assert anns[0].min == 18

    def test_multiple_value_with_configuration_properties(self):
        """@Value + @Value + @ConfigurationProperties 多配置绑定组合"""
        @ConfigurationProperties("app.feature")
        @Value("app.timeout", default=30)
        @Value("app.name")
        class FeatureConfig:
            pass

        anns = get_spring_annotations(FeatureConfig)
        # 两个 @Value + 一个 @ConfigurationProperties
        values = [a for a in anns if isinstance(a, Value)]
        props = [a for a in anns if isinstance(a, ConfigurationProperties)]
        assert len(values) == 2
        assert len(props) == 1
        # 顺序：app.name 先附加，app.timeout 次，prefix 最后
        assert values[0].value == "app.name"
        assert values[1].value == "app.timeout"
        assert values[1].default == 30
        assert props[0].prefix == "app.feature"


# ==================== 安全 + Web 跨层组合 ====================

class TestSecurityAndWebCombinations:
    def test_pre_authorize_with_get_mapping(self):
        """@PreAuthorize + @GetMapping 安全+Web 跨层组合"""
        @PreAuthorize("hasRole('ROLE_ADMIN')")
        @GetMapping("/admin/users")
        def list_admin_users():
            return []

        anns = get_spring_annotations(list_admin_users)
        types = [type(a) for a in anns]
        assert types == [GetMapping, PreAuthorize]
        assert anns[0].path == "/admin/users"
        assert anns[1].value == "hasRole('ROLE_ADMIN')"

    def test_secured_with_post_mapping_and_audit_log(self):
        """@Secured + @PostMapping + @AuditLog 安全+Web+审计三跨层组合"""
        @Secured(["ROLE_ADMIN", "ROLE_EDITOR"])
        @PostMapping("/posts")
        @AuditLog(action="create_post", target="post")
        def create_post():
            return {"id": 1}

        anns = get_spring_annotations(create_post)
        types = [type(a) for a in anns]
        assert types == [AuditLog, PostMapping, Secured]
        assert anns[2].value == ["ROLE_ADMIN", "ROLE_EDITOR"]
        assert anns[1].path == "/posts"
        assert anns[0].action == "create_post"

    def test_authenticate_with_trace_and_metrics(self):
        """@Authenticate + @Trace + @Metrics 认证+追踪+监控组合"""
        @Authenticate
        @Trace(span_name="secure_op")
        @Metrics(name="secure.op")
        def secure_op():
            return "ok"

        anns = get_spring_annotations(secure_op)
        types = [type(a) for a in anns]
        assert types == [Metrics, Trace, Authenticate]
        # Authenticate 无额外属性，仅验证类型
        assert isinstance(anns[2], Authenticate)
        assert anns[1].span_name == "secure_op"
        assert anns[0].name == "secure.op"


# ==================== Cloud 组合 ====================

class TestCloudCombinations:
    def test_feign_client_class_with_sentinel_method(self):
        """@FeignClient(类) + @SentinelResource(方法) 远程调用+熔断组合"""
        @FeignClient("inventory", path="/api", url="http://inv")
        class InventoryClient:
            @SentinelResource("getStock", block_handler="blocked",
                              fallback="fallback")
            def get_stock(self, sku: str):
                return sku

        class_anns = get_spring_annotations(InventoryClient)
        method_anns = get_spring_annotations(InventoryClient.get_stock)

        assert len(class_anns) == 1
        assert isinstance(class_anns[0], FeignClient)
        assert class_anns[0].value == "inventory"
        assert class_anns[0].path == "/api"

        assert len(method_anns) == 1
        assert isinstance(method_anns[0], SentinelResource)
        assert method_anns[0].value == "getStock"
        assert method_anns[0].fallback == "fallback"

    def test_global_transactional_with_transactional(self):
        """@GlobalTransactional + @Transactional 分布式事务+本地事务组合"""
        @GlobalTransactional(timeout=5000, name="create_order")
        @Transactional(propagation="REQUIRES_NEW", rollback_for=[ValueError])
        def create_order():
            return {"ok": True}

        anns = get_spring_annotations(create_order)
        types = [type(a) for a in anns]
        assert types == [Transactional, GlobalTransactional]
        assert anns[1].timeout == 5000
        assert anns[1].name == "create_order"
        assert anns[0].propagation == "REQUIRES_NEW"
        assert ValueError in anns[0].rollback_for

    def test_enable_discovery_with_refresh_scope_and_nacos_value(self):
        """@EnableDiscoveryClient + @RefreshScope + @NacosValue 注册+刷新组合"""
        @RefreshScope
        @EnableDiscoveryClient("nacos")
        class CloudService:
            pass

        anns = get_spring_annotations(CloudService)
        types = [type(a) for a in anns]
        assert types == [EnableDiscoveryClient, RefreshScope]
        assert anns[0].client_type == "nacos"

        # @NacosValue 通常用于属性，这里验证其可独立构造并附加
        @NacosValue("app.name", auto_refreshed=True)
        def name_holder():
            return "x"

        nv_anns = get_spring_annotations(name_holder)
        assert len(nv_anns) == 1
        assert isinstance(nv_anns[0], NacosValue)
        assert nv_anns[0].auto_refreshed is True

    def test_enable_gateway_with_load_balanced_bean(self):
        """@EnableGateway(类) + @LoadBalanced(Bean 方法) 网关+负载均衡组合"""
        @EnableGateway
        class GatewayApp:
            @LoadBalanced("random")
            def rest_client(self):
                return "client"

        class_anns = get_spring_annotations(GatewayApp)
        method_anns = get_spring_annotations(GatewayApp.rest_client)

        assert len(class_anns) == 1
        assert isinstance(class_anns[0], EnableGateway)
        assert len(method_anns) == 1
        assert isinstance(method_anns[0], LoadBalanced)
        assert method_anns[0].strategy == "random"

    def test_sentinel_with_circuit_breaker_and_retryable(self):
        """@SentinelResource + @CircuitBreaker + @Retryable 限流+熔断+重试组合"""
        @SentinelResource("resilient_call", fallback="fallback")
        @CircuitBreaker(failure_threshold=3, recovery_timeout=10,
                        fallback_method="cb_fallback")
        @Retryable(max_attempts=3, backoff=200)
        def resilient_call():
            return "ok"

        anns = get_spring_annotations(resilient_call)
        types = [type(a) for a in anns]
        assert types == [Retryable, CircuitBreaker, SentinelResource]
        assert anns[2].value == "resilient_call"
        assert anns[1].failure_threshold == 3
        assert anns[0].max_retries == 3


# ==================== 异步 + 调度组合 ====================

class TestAsyncAndSchedulingCombinations:
    def test_async_with_async_result(self):
        """@Async + @AsyncResult 异步执行+结果包装组合"""
        @Async
        @AsyncResult("done")
        def async_task():
            return "done"

        anns = get_spring_annotations(async_task)
        types = [type(a) for a in anns]
        assert types == [AsyncResult, Async]
        assert anns[0].value == "done"

    def test_scheduled_with_metrics(self):
        """@Scheduled + @Metrics 定时任务+监控组合"""
        @Scheduled(fixed_rate=1000, initial_delay=5)
        @Metrics(name="cron.heartbeat")
        def heartbeat():
            return "beat"

        anns = get_spring_annotations(heartbeat)
        types = [type(a) for a in anns]
        assert types == [Metrics, Scheduled]
        assert anns[1].fixed_rate == 1000
        assert anns[1].initial_delay == 5
        assert anns[0].name == "cron.heartbeat"


# ==================== 顺序与继承隔离 ====================

class TestOrderingAndInheritance:
    def test_combination_declaration_order_preserved(self):
        """多注解叠加时声明顺序（自底向上附加）严格保持"""
        @Trace(span_name="t")
        @Metrics(name="m")
        @AuditLog(action="a")
        @RateLimit(max_requests=5)
        def ordered():
            pass

        anns = get_spring_annotations(ordered)
        # 最内层（@RateLimit）先附加，最外层（@Trace）最后附加
        types = [type(a) for a in anns]
        assert types == [RateLimit, AuditLog, Metrics, Trace]

    def test_inheritance_isolation_in_combinations(self):
        """子类组合注解不影响父类元数据"""
        @RestController
        @RequestMapping("/api/base")
        class BaseController:
            pass

        @Slf4j
        @Service("child")
        class ChildService(BaseController):
            pass

        parent_anns = get_spring_annotations(BaseController)
        child_anns = get_spring_annotations(ChildService)

        # 父类仅保留自身 2 个注解
        assert len(parent_anns) == 2
        assert {type(a) for a in parent_anns} == {RestController, RequestMapping}
        # 子类仅保留自身 2 个注解，不继承父类
        assert len(child_anns) == 2
        assert {type(a) for a in child_anns} == {Service, Slf4j}

    def test_six_annotation_stack_count_and_types(self):
        """六注解叠加：计数与类型完整保持"""
        @Trace(span_name="s")
        @Metrics(name="n")
        @AuditLog(action="a")
        @RateLimit(max_requests=1)
        @Idempotent(key="#k", expire=10)
        @Lock(key="#k", expire=5)
        def six(k: str):
            return k

        anns = get_spring_annotations(six)
        assert len(anns) == 6
        expected = [Lock, Idempotent, RateLimit, AuditLog, Metrics, Trace]
        assert [type(a) for a in anns] == expected

    def test_each_annotation_metadata_independent_in_combo(self):
        """组合中每个注解元数据互不干扰"""
        @RateLimit(max_requests=7, time_window=14, key="user")
        @CircuitBreaker(failure_threshold=4, recovery_timeout=8,
                        fallback_method="fb")
        @Retryable(max_attempts=2, backoff=100)
        def combo():
            pass

        anns = get_spring_annotations(combo)
        rl, cb, rt = anns[2], anns[1], anns[0]
        # RateLimit 元数据
        assert rl.max_requests == 7
        assert rl.time_window == 14
        assert rl.key == "user"
        # CircuitBreaker 元数据
        assert cb.failure_threshold == 4
        assert cb.recovery_timeout == 8
        assert cb.fallback_method == "fb"
        # Retryable 元数据
        assert rt.max_retries == 2
        assert isinstance(rt.backoff, Backoff)
        assert rt.backoff.delay == 100


# ==================== Configuration + Bean 方法组合 ====================

class TestConfigurationBeanCombinations:
    def test_configuration_class_with_multiple_bean_methods(self):
        """@Configuration 类 + 多个 @Bean 方法（不同 scope/init/destroy）"""
        @Configuration
        class AppConfig:
            @Bean(name="dataSource", scope="singleton",
                  init_method="init", destroy_method="close")
            def data_source(self):
                return "ds"

            @Bean(name="cache", scope="prototype")
            def cache(self):
                return "cache"

        class_anns = get_spring_annotations(AppConfig)
        ds_anns = get_spring_annotations(AppConfig.data_source)
        cache_anns = get_spring_annotations(AppConfig.cache)

        assert len(class_anns) == 1
        assert isinstance(class_anns[0], Configuration)

        assert len(ds_anns) == 1
        assert isinstance(ds_anns[0], Bean)
        assert ds_anns[0].name == "dataSource"
        assert ds_anns[0].scope == "singleton"
        assert ds_anns[0].init_method == "init"
        assert ds_anns[0].destroy_method == "close"

        assert len(cache_anns) == 1
        assert isinstance(cache_anns[0], Bean)
        assert cache_anns[0].name == "cache"
        assert cache_anns[0].scope == "prototype"
        assert cache_anns[0].init_method is None

    def test_controller_with_autowired_constructor_and_mapping_methods(self):
        """@Controller 类 + @Autowired 构造器 + 多 @GetMapping 方法"""
        @Controller
        @RequestMapping("/web")
        class WebController:
            @Autowired
            def __init__(self, svc):
                self.svc = svc

            @GetMapping("/home")
            def home(self):
                return "home"

            @GetMapping("/about")
            def about(self):
                return "about"

        class_anns = get_spring_annotations(WebController)
        init_anns = get_spring_annotations(WebController.__init__)
        home_anns = get_spring_annotations(WebController.home)
        about_anns = get_spring_annotations(WebController.about)

        # 类级：Controller + RequestMapping
        assert len(class_anns) == 2
        assert {type(a) for a in class_anns} == {Controller, RequestMapping}
        # 构造器：Autowired
        assert len(init_anns) == 1
        assert isinstance(init_anns[0], Autowired)
        # 各方法独立保持自己的 @GetMapping
        assert len(home_anns) == 1
        assert isinstance(home_anns[0], GetMapping)
        assert home_anns[0].path == "/home"
        assert len(about_anns) == 1
        assert isinstance(about_anns[0], GetMapping)
        assert about_anns[0].path == "/about"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
