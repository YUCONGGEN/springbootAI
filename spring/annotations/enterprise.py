"""
企业级模块启用型注解

提供 DevTools 热重载、配置中心、事件总线、批处理、Data REST 的注解驱动启用方式。
标记在 SpringBootApplication 主类上，替代 application.yml 配置。

使用示例::

    @SpringBootApplication
    @EnableDevTools       # 开发环境热重载
    @EnableConfigServer   # 配置中心客户端
    @EnableBus            # 事件总线
    @EnableBatchProcessing  # 批处理
    @EnableDataRest       # Repository 自动 REST API
    class Application:
        pass

与配置文件的等价关系：
- @EnableDevTools          等价于 spring.devtools.restart.enabled: true
- @EnableConfigServer      等价于 spring.cloud.config.enabled: true
- @EnableBus               等价于 spring.cloud.bus.enabled: true
- @EnableBatchProcessing   等价于 spring.batch.enabled: true
- @EnableDataRest          等价于 spring.data.rest.enabled: true
"""
from typing import List, Optional

from .core import SpringAnnotation


class EnableDevTools(SpringAnnotation):
    """启用 DevTools 热重载

    标记在主类上，开发环境下文件变更时自动重启应用。

    Attributes:
        watch_dirs: 监视目录列表（默认监视当前工作目录）
        poll_interval: 轮询间隔（秒，默认 1.0）
        exclude_dirs: 排除目录集合

    使用示例::

        @SpringBootApplication
        @EnableDevTools(
            watch_dirs=["src", "config"],
            poll_interval=0.5,
        )
        class Application:
            pass

    对齐 Java Spring Boot DevTools：
    - Java 通过 spring-boot-devtools 依赖自动启用
    - Python 版本通过 @EnableDevTools 注解显式启用
    - 两者都仅建议在开发环境使用，生产环境应移除
    """

    _annotation_type = "devtools"

    def __init__(
        self,
        watch_dirs: Optional[List[str]] = None,
        poll_interval: float = 1.0,
        exclude_dirs: Optional[List[str]] = None,
    ):
        super().__init__(
            watch_dirs=watch_dirs or ['.'],
            poll_interval=poll_interval,
            exclude_dirs=exclude_dirs,
        )


class EnableConfigServer(SpringAnnotation):
    """启用 Spring Cloud Config 配置中心客户端

    标记在主类上，应用启动时从配置中心拉取远程配置。

    Attributes:
        uri: 配置中心地址（如 http://config-server:8888）
        profile: 环境名（如 dev/prod，默认读取 spring.profiles.active）
        label: 分支/标签（默认 master）
        fail_fast: 拉取失败是否快速失败（默认 False）
        backend: 后端类型（'http' 或 'file'）

    使用示例::

        @SpringBootApplication
        @EnableConfigServer(
            uri="http://config-server:8888",
            profile="prod",
            fail_fast=True,
        )
        class Application:
            pass

    对齐 Java Spring Cloud Config：
    - Java 通过 @EnableConfigServer（服务端）或 spring-cloud-starter-config（客户端）启用
    - Python 版本通过 @EnableConfigServer 注解启用客户端功能
    """

    _annotation_type = "config_center"

    def __init__(
        self,
        uri: str = 'http://localhost:8888',
        profile: Optional[str] = None,
        label: str = 'master',
        fail_fast: bool = False,
        backend: str = 'http',
    ):
        super().__init__(
            uri=uri,
            profile=profile,
            label=label,
            fail_fast=fail_fast,
            backend=backend,
        )


class EnableBus(SpringAnnotation):
    """启用 Spring Cloud Bus 事件总线

    标记在主类上，应用启动时初始化事件总线，支持配置刷新广播。

    Attributes:
        destination: 消息目标（topic/exchange 名，默认 'springCloudBus'）
        backend: 后端类型（'local'/'rabbitmq'/'kafka'，默认 'local'）

    使用示例::

        @SpringBootApplication
        @EnableBus(backend="rabbitmq", destination="myBus")
        class Application:
            pass

    对齐 Java Spring Cloud Bus：
    - Java 通过 spring-cloud-starter-bus-amqp 依赖自动启用
    - Python 版本通过 @EnableBus 注解启用
    """

    _annotation_type = "bus"

    def __init__(
        self,
        destination: str = 'springCloudBus',
        backend: str = 'local',
    ):
        super().__init__(
            destination=destination,
            backend=backend,
        )


class EnableBatchProcessing(SpringAnnotation):
    """启用 Spring Batch 批处理

    标记在主类上，应用启动时初始化批处理框架。

    Attributes:
        job_names: 启动时自动执行的 Job 名称列表（可选）
        auto_run: 是否在应用启动时自动执行 job_names 中的 Job（默认 False）

    使用示例::

        @SpringBootApplication
        @EnableBatchProcessing
        class Application:
            pass

        # 或指定启动时自动执行的 Job
        @EnableBatchProcessing(job_names=["importUsers"], auto_run=True)

    对齐 Java Spring Batch：
    - Java 通过 @EnableBatchProcessing 注解启用
    - Python 版本同样通过 @EnableBatchProcessing 注解启用
    """

    _annotation_type = "batch"

    def __init__(
        self,
        job_names: Optional[List[str]] = None,
        auto_run: bool = False,
    ):
        super().__init__(
            job_names=job_names or [],
            auto_run=auto_run,
        )


class EnableDataRest(SpringAnnotation):
    """启用 Spring Data REST

    标记在主类上，自动将标记了 @RepositoryRestResource 的 Repository 暴露为 REST API。

    Attributes:
        base_path: 所有 Repository REST 端点的基础路径（默认 '/api'）
        default_page_size: 默认分页大小（默认 20）
        max_page_size: 最大分页大小（默认 1000）

    使用示例::

        @SpringBootApplication
        @EnableDataRest(base_path="/api/v1", default_page_size=50)
        class Application:
            pass

    对齐 Java Spring Data REST：
    - Java 通过 @RepositoryRestResource 注解 + 自动配置启用
    - Python 版本通过 @EnableDataRest + @RepositoryRestResource 注解启用
    """

    _annotation_type = "data_rest"

    def __init__(
        self,
        base_path: str = '',
        default_page_size: int = 20,
        max_page_size: int = 1000,
    ):
        super().__init__(
            base_path=base_path,
            default_page_size=default_page_size,
            max_page_size=max_page_size,
        )
