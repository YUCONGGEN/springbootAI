"""新注解驱动功能测试

覆盖以下注解：
- @EnableOAuth2：启用 OAuth2 资源服务器
- @EnableCsrf：启用 CSRF 防护
- @EnableDevTools：启用 DevTools 热重载
- @EnableConfigServer：启用配置中心客户端
- @EnableBus：启用事件总线
- @EnableBatchProcessing：启用批处理
- @EnableDataRest：启用 Data REST
- @BatchJob / @BatchStep：批处理作业/步骤定义
- @RepositoryRestResource：Repository REST 资源标记
"""
import pytest

from spring.annotations import (
    EnableOAuth2,
    EnableCsrf,
    EnableDevTools,
    EnableConfigServer,
    EnableBus,
    EnableBatchProcessing,
    EnableDataRest,
    BatchJob,
    BatchStep,
    RepositoryRestResource,
)
from spring.annotations.core import SpringAnnotation, get_spring_annotations


# ==================== @EnableOAuth2 测试 ====================

class TestEnableOAuth2Annotation:
    """@EnableOAuth2 注解测试"""

    def test_annotation_is_spring_annotation(self):
        assert issubclass(EnableOAuth2, SpringAnnotation)

    def test_annotation_with_defaults(self):
        @EnableOAuth2()
        class App:
            pass

        annotations = get_spring_annotations(App)
        assert len(annotations) == 1
        ann = annotations[0]
        assert isinstance(ann, EnableOAuth2)
        assert ann.algorithms == ['HS256']
        assert ann.audiences == []
        assert ann.issuer is None
        assert ann.jwks_uri is None

    def test_annotation_with_params(self):
        @EnableOAuth2(
            issuer="https://auth.example.com",
            audiences=["my-api"],
            algorithms=["RS256"],
            jwks_uri="https://auth.example.com/.well-known/jwks.json",
        )
        class App:
            pass

        ann = get_spring_annotations(App)[0]
        assert ann.issuer == "https://auth.example.com"
        assert ann.audiences == ["my-api"]
        assert ann.algorithms == ["RS256"]
        assert ann.jwks_uri == "https://auth.example.com/.well-known/jwks.json"

    def test_annotation_type(self):
        assert EnableOAuth2._annotation_type == "security_oauth2"


# ==================== @EnableCsrf 测试 ====================

class TestEnableCsrfAnnotation:
    """@EnableCsrf 注解测试"""

    def test_annotation_with_defaults(self):
        @EnableCsrf
        class App:
            pass

        ann = get_spring_annotations(App)[0]
        assert isinstance(ann, EnableCsrf)
        assert ann.token_length == 32
        assert ann.token_ttl == 3600
        assert ann.cookie_name == 'XSRF-TOKEN'
        assert ann.header_name == 'X-XSRF-TOKEN'
        assert ann.secure_cookie is False

    def test_annotation_with_custom_params(self):
        @EnableCsrf(token_ttl=7200, secure_cookie=True, same_site='Strict')
        class App:
            pass

        ann = get_spring_annotations(App)[0]
        assert ann.token_ttl == 7200
        assert ann.secure_cookie is True
        assert ann.same_site == 'Strict'

    def test_annotation_type(self):
        assert EnableCsrf._annotation_type == "security_csrf"


# ==================== @EnableDevTools 测试 ====================

class TestEnableDevToolsAnnotation:
    """@EnableDevTools 注解测试"""

    def test_annotation_with_defaults(self):
        @EnableDevTools
        class App:
            pass

        ann = get_spring_annotations(App)[0]
        assert isinstance(ann, EnableDevTools)
        assert ann.watch_dirs == ['.']
        assert ann.poll_interval == 1.0

    def test_annotation_with_params(self):
        @EnableDevTools(watch_dirs=["src", "config"], poll_interval=0.5)
        class App:
            pass

        ann = get_spring_annotations(App)[0]
        assert ann.watch_dirs == ["src", "config"]
        assert ann.poll_interval == 0.5

    def test_annotation_type(self):
        assert EnableDevTools._annotation_type == "devtools"


# ==================== @EnableConfigServer 测试 ====================

class TestEnableConfigServerAnnotation:
    """@EnableConfigServer 注解测试"""

    def test_annotation_with_defaults(self):
        @EnableConfigServer
        class App:
            pass

        ann = get_spring_annotations(App)[0]
        assert isinstance(ann, EnableConfigServer)
        assert ann.uri == 'http://localhost:8888'
        assert ann.label == 'master'
        assert ann.fail_fast is False
        assert ann.backend == 'http'

    def test_annotation_with_params(self):
        @EnableConfigServer(
            uri="http://config:8888",
            profile="prod",
            fail_fast=True,
            backend="file",
        )
        class App:
            pass

        ann = get_spring_annotations(App)[0]
        assert ann.uri == "http://config:8888"
        assert ann.profile == "prod"
        assert ann.fail_fast is True
        assert ann.backend == "file"

    def test_annotation_type(self):
        assert EnableConfigServer._annotation_type == "config_center"


# ==================== @EnableBus 测试 ====================

class TestEnableBusAnnotation:
    """@EnableBus 注解测试"""

    def test_annotation_with_defaults(self):
        @EnableBus
        class App:
            pass

        ann = get_spring_annotations(App)[0]
        assert isinstance(ann, EnableBus)
        assert ann.destination == 'springCloudBus'
        assert ann.backend == 'local'

    def test_annotation_with_params(self):
        @EnableBus(destination="myBus", backend="rabbitmq")
        class App:
            pass

        ann = get_spring_annotations(App)[0]
        assert ann.destination == "myBus"
        assert ann.backend == "rabbitmq"

    def test_annotation_type(self):
        assert EnableBus._annotation_type == "bus"


# ==================== @EnableBatchProcessing 测试 ====================

class TestEnableBatchProcessingAnnotation:
    """@EnableBatchProcessing 注解测试"""

    def test_annotation_with_defaults(self):
        @EnableBatchProcessing
        class App:
            pass

        ann = get_spring_annotations(App)[0]
        assert isinstance(ann, EnableBatchProcessing)
        assert ann.job_names == []
        assert ann.auto_run is False

    def test_annotation_with_auto_run(self):
        @EnableBatchProcessing(job_names=["importUsers", "exportReport"], auto_run=True)
        class App:
            pass

        ann = get_spring_annotations(App)[0]
        assert ann.job_names == ["importUsers", "exportReport"]
        assert ann.auto_run is True

    def test_annotation_type(self):
        assert EnableBatchProcessing._annotation_type == "batch"


# ==================== @EnableDataRest 测试 ====================

class TestEnableDataRestAnnotation:
    """@EnableDataRest 注解测试"""

    def test_annotation_with_defaults(self):
        @EnableDataRest
        class App:
            pass

        ann = get_spring_annotations(App)[0]
        assert isinstance(ann, EnableDataRest)
        assert ann.base_path == ''
        assert ann.default_page_size == 20
        assert ann.max_page_size == 1000

    def test_annotation_with_params(self):
        @EnableDataRest(base_path="/api/v1", default_page_size=50, max_page_size=500)
        class App:
            pass

        ann = get_spring_annotations(App)[0]
        assert ann.base_path == "/api/v1"
        assert ann.default_page_size == 50
        assert ann.max_page_size == 500

    def test_annotation_type(self):
        assert EnableDataRest._annotation_type == "data_rest"


# ==================== @BatchJob / @BatchStep 测试 ====================

class TestBatchJobAnnotation:
    """@BatchJob 注解测试"""

    def test_annotation_basic(self):
        @BatchJob(name="importUsers")
        class ImportUserJob:
            pass

        ann = get_spring_annotations(ImportUserJob)[0]
        assert isinstance(ann, BatchJob)
        assert ann.name == "importUsers"
        assert ann.description == ''
        assert ann.restartable is True

    def test_annotation_with_description(self):
        @BatchJob(name="exportReport", description="导出月度报表", restartable=False)
        class ExportJob:
            pass

        ann = get_spring_annotations(ExportJob)[0]
        assert ann.description == "导出月度报表"
        assert ann.restartable is False

    def test_annotation_type(self):
        assert BatchJob._annotation_type == "batch_job"


class TestBatchStepAnnotation:
    """@BatchStep 注解测试"""

    def test_annotation_basic(self):
        class Job:
            @BatchStep(name="extract")
            def extract_step(self):
                pass

        # @BatchStep 作用在方法上
        anns = get_spring_annotations(Job.extract_step)
        assert len(anns) == 1
        ann = anns[0]
        assert isinstance(ann, BatchStep)
        assert ann.name == "extract"
        assert ann.chunk_size == 10

    def test_annotation_with_params(self):
        class Job:
            @BatchStep(name="transform", chunk_size=100, retry_limit=3, skip_limit=5)
            def transform_step(self):
                pass

        ann = get_spring_annotations(Job.transform_step)[0]
        assert ann.chunk_size == 100
        assert ann.retry_limit == 3
        assert ann.skip_limit == 5

    def test_annotation_type(self):
        assert BatchStep._annotation_type == "batch_step"


# ==================== @RepositoryRestResource 测试 ====================

class TestRepositoryRestResourceAnnotation:
    """@RepositoryRestResource 注解测试"""

    def test_annotation_basic(self):
        class User:
            pass

        @RepositoryRestResource(path="users", entity_class=User)
        class UserRepo:
            pass

        ann = get_spring_annotations(UserRepo)[0]
        assert isinstance(ann, RepositoryRestResource)
        assert ann.path == "users"
        assert ann.entity_class is User
        assert ann.id_type is int
        assert ann.exported is True

    def test_annotation_not_exported(self):
        class Order:
            pass

        @RepositoryRestResource(path="orders", entity_class=Order, exported=False)
        class OrderRepo:
            pass

        ann = get_spring_annotations(OrderRepo)[0]
        assert ann.exported is False

    def test_annotation_custom_id_type(self):
        class Product:
            pass

        @RepositoryRestResource(path="products", entity_class=Product, id_type=str)
        class ProductRepo:
            pass

        ann = get_spring_annotations(ProductRepo)[0]
        assert ann.id_type is str

    def test_annotation_type(self):
        assert RepositoryRestResource._annotation_type == "repository_rest"


# ==================== 多注解组合测试 ====================

class TestMultipleAnnotations:
    """多注解组合使用测试"""

    def test_multiple_enable_annotations(self):
        """主类上同时使用多个 @EnableXxx 注解"""
        @EnableOAuth2(issuer="https://auth.example.com")
        @EnableCsrf
        @EnableDevTools
        class Application:
            pass

        annotations = get_spring_annotations(Application)
        assert len(annotations) == 3

        types = {type(ann) for ann in annotations}
        assert EnableOAuth2 in types
        assert EnableCsrf in types
        assert EnableDevTools in types

    def test_enable_annotations_with_spring_boot_application(self):
        """与 @SpringBootApplication 组合使用"""
        from spring.annotations import SpringBootApplication

        @SpringBootApplication
        @EnableOAuth2
        @EnableBus(backend="rabbitmq")
        class Application:
            pass

        annotations = get_spring_annotations(Application)
        assert len(annotations) == 3  # SpringBootApplication + EnableOAuth2 + EnableBus

        # 验证能找到各类型注解
        oauth2_ann = None
        bus_ann = None
        for ann in annotations:
            if isinstance(ann, EnableOAuth2):
                oauth2_ann = ann
            elif isinstance(ann, EnableBus):
                bus_ann = ann

        assert oauth2_ann is not None
        assert bus_ann is not None
        assert bus_ann.backend == "rabbitmq"


# ==================== SpringApplication._find_annotation 测试 ====================

class TestFindAnnotation:
    """SpringApplication._find_annotation 方法测试"""

    def test_find_annotation_returns_match(self):
        from spring.main import SpringApplication

        @EnableOAuth2(issuer="https://test.com")
        @EnableCsrf
        class App:
            pass

        app = SpringApplication(App)
        ann = app._find_annotation(EnableOAuth2)
        assert ann is not None
        assert ann.issuer == "https://test.com"

    def test_find_annotation_returns_none_when_absent(self):
        from spring.main import SpringApplication

        class App:
            pass

        app = SpringApplication(App)
        ann = app._find_annotation(EnableOAuth2)
        assert ann is None

    def test_find_annotation_with_multiple_types(self):
        from spring.main import SpringApplication

        @EnableBus
        @EnableDevTools
        class App:
            pass

        app = SpringApplication(App)
        bus_ann = app._find_annotation(EnableBus)
        devtools_ann = app._find_annotation(EnableDevTools)
        csrf_ann = app._find_annotation(EnableCsrf)

        assert bus_ann is not None
        assert devtools_ann is not None
        assert csrf_ann is None
