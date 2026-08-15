from typing import Type, Optional
import socket
import sys
import asyncio
from spring.context.application_context import ApplicationContext
from spring.web.web_context import WebApplicationContext
from spring.utils.banner import BannerPrinter
from spring.utils.logger import SpringLogger
from spring.logging.loguru_logger import init_logging, LoggingConfigError
from spring.orm.mybatis_integration import init_mybatis
from spring.annotations.cloud import EnableDiscoveryClient
from spring.annotations.security import EnableOAuth2, EnableCsrf
from spring.annotations.enterprise import (
    EnableDevTools,
    EnableConfigServer,
    EnableBus,
    EnableBatchProcessing,
    EnableDataRest,
)
from spring.annotations.data import RepositoryRestResource


class ComponentInitError(RuntimeError):
    """组件初始化失败（配置错误/依赖缺失/连接失败等）。

    携带已格式化的明确错误信息（含组件名/配置内容/错误原因/修复建议），
    由 ``run()`` 捕获后干净退出，不输出框架 traceback。
    """
    pass


# 配置中需要脱敏的敏感字段名（小写匹配）
_SENSITIVE_CONFIG_KEYS = frozenset({
    'password', 'secret_key', 'secret', 'token', 'api_key', 'apikey',
    'access_key', 'secret_access_key', 'private_key',
})


class SpringApplication:
    def __init__(self, main_class: Type):
        self.main_class = main_class
        self.application_context: Optional[ApplicationContext] = None
        self.web_context: Optional[WebApplicationContext] = None
        self.logger = SpringLogger()
        self._discovery_registered = False
        self._background_started = False

    @staticmethod
    def _section(value: object) -> dict:
        """Return a config section as a dictionary for defensive reads."""
        return value if isinstance(value, dict) else {}

    def _cleanup_after_start_failure(self) -> None:
        """Release context-owned resources when web startup aborts."""
        context = self.application_context
        if context is None:
            return
        try:
            context.destroy()
        except Exception as cleanup_error:
            logger = getattr(self, 'logger', None)
            if logger is not None:
                try:
                    logger.warning(
                        f"Failed to clean up application context after startup error: {cleanup_error}"
                    )
                except Exception:
                    pass

    def run(self, **kwargs) -> None:
        banner = BannerPrinter()
        banner.print_banner()

        try:
            self._prepare_context()
            self._start_web_server(**kwargs)
        except LoggingConfigError as e:
            # 日志配置错误：错误信息已格式化（含配置项/值/原因/建议），
            # 干净退出不输出框架 traceback，让用户一眼定位问题
            self._cleanup_after_start_failure()
            print(f"\n应用启动失败（日志配置错误）:\n{e}\n", file=sys.stderr)
            sys.exit(1)
        except ComponentInitError as e:
            # 组件初始化失败：错误信息已格式化（含组件名/配置/原因/建议），
            # 干净退出不输出框架 traceback
            self._cleanup_after_start_failure()
            print(f"\n应用启动失败（组件初始化失败）:\n{e}\n", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            self._cleanup_after_start_failure()
            self.logger.error(f"Application failed to start: {str(e)}")
            raise

    # ------------------------------------------------------------------
    # 统一的组件初始化异常处理
    # ------------------------------------------------------------------

    @staticmethod
    def _mask_sensitive(config: dict) -> dict:
        """脱敏配置中的敏感字段（密码/密钥等），用于错误输出。"""
        if not config:
            return {}
        if not isinstance(config, dict):
            # Error reporting must remain safe even when a malformed optional
            # section (for example ``rabbitmq: []``) reaches this boundary.
            return {'value': config}
        masked = {}
        for k, v in config.items():
            if k.lower() in _SENSITIVE_CONFIG_KEYS:
                masked[k] = '***' if v else '(空)'
            else:
                masked[k] = v
        return masked

    @staticmethod
    def _format_component_error(component: str, config: dict, exc: Exception) -> str:
        """格式化组件初始化失败的明确错误信息。

        输出格式统一为：组件名 + 配置内容（脱敏）+ 错误原因 + 修复建议，
        让用户一眼定位是哪个组件、什么配置、为什么失败、怎么修。
        """
        masked = SpringApplication._mask_sensitive(config)
        config_str = (
            ', '.join(f'{k}={v!r}' for k, v in masked.items())
            if masked else '(无配置)'
        )
        is_import_error = isinstance(exc, ImportError)
        if is_import_error:
            reason = f"依赖未安装（{type(exc).__name__}: {exc}）"
            suggestions = [
                f"安装 {component} 所需的 pip 依赖（查看文档确认包名）",
                f"或设置 {component.lower()}.enabled=false 暂时禁用该组件",
            ]
        else:
            reason = f"{type(exc).__name__}: {exc}"
            suggestions = [
                f"检查 {component} 相关配置项是否正确（上方「配置内容」）",
                "确认依赖服务（如 Redis/MySQL/Nacos/RabbitMQ）已启动且网络可访问",
                "确认所需 pip 依赖已安装且版本兼容",
                f"或设置 startup.fail_fast=false 容忍 {component} 失败继续启动",
            ]
        lines = [
            "=" * 64,
            f"[组件初始化失败] {component}",
            "-" * 64,
            f"  配置内容: {config_str}",
            f"  错误原因: {reason}",
            "  修复建议:",
        ]
        for i, s in enumerate(suggestions, 1):
            lines.append(f"    {i}. {s}")
        lines.append("=" * 64)
        return "\n".join(lines)

    def _handle_init_error(self, component: str, config: dict, exc: Exception,
                           fail_fast: bool) -> None:
        """统一处理组件初始化异常。

        - fail_fast=true：抛出 ``ComponentInitError``（携带格式化错误信息），
          由 ``run()`` 捕获后干净退出。
        - fail_fast=false：输出醒目的 ``[组件初始化失败]`` 警告到 stderr（不再静默），
          然后继续启动（该组件功能可能不可用）。

        Args:
            component: 组件名（如 'Redis'、'JWT'、'Database'）
            config: 该组件的配置字典（用于错误输出，敏感字段自动脱敏）
            exc: 捕获的异常
            fail_fast: 是否快速失败模式
        """
        msg = self._format_component_error(component, config, exc)
        if fail_fast:
            # 抛出 ComponentInitError，run() 会捕获并干净退出
            raise ComponentInitError(msg) from exc
        # 非 fail_fast：输出醒目警告到 stderr，继续启动
        print(
            f"\n[警告] {component} 初始化失败（fail_fast=false，继续启动，"
            f"该组件功能可能不可用）:\n{msg}\n",
            file=sys.stderr,
        )

    def _find_annotation(self, annotation_class):
        """在主类上查找指定类型的注解。

        扫描 ``self.main_class`` 上的 ``__spring_annotations__`` 列表，
        返回第一个匹配类型的注解实例，没有则返回 None。

        Args:
            annotation_class: 注解类（如 EnableOAuth2）

        Returns:
            注解实例或 None
        """
        annotations = getattr(self.main_class, '__spring_annotations__', [])
        for item in annotations:
            if isinstance(item, annotation_class):
                return item
        return None

    def _register_repository_rest_resources(self, base_path: str) -> None:
        """扫描 IoC 容器中标记了 @RepositoryRestResource 的 Bean，
        自动注册 CRUD REST 端点。

        Args:
            base_path: REST 端点基础路径（如 '/api'）
        """
        if not self.application_context:
            return
        from spring.data.rest import RepositoryRestController
        registry = self.application_context.bean_registry
        if not registry:
            return
        registered = 0
        for bean_name, bean_instance in registry.beans.items():
            bean_class = type(bean_instance)
            rest_annotations = [
                ann for ann in getattr(bean_class, '__spring_annotations__', [])
                if isinstance(ann, RepositoryRestResource) and ann.exported
            ]
            for ann in rest_annotations:
                entity_class = ann.entity_class
                if entity_class is None:
                    # 尝试从 Bean 类的 entity_class 属性获取
                    entity_class = getattr(bean_class, 'entity_class', None)
                if entity_class is None:
                    self.logger.warning(
                        f"Repository '{bean_name}' has @RepositoryRestResource but no entity_class"
                    )
                    continue
                path = ann.path
                if base_path and not path.startswith('/'):
                    path = f'{base_path}/{path}'
                controller = RepositoryRestController(
                    repository=bean_instance,
                    path=path,
                    entity_class=entity_class,
                    id_type=ann.id_type,
                )
                # 注册到 FastAPI app（延迟到 web_context 初始化后）
                self._pending_rest_controllers = getattr(self, '_pending_rest_controllers', [])
                self._pending_rest_controllers.append(controller)
                registered += 1
                self.logger.info(
                    f"Registered REST resource: {path} -> {bean_name} ({entity_class.__name__})"
                )
        if registered:
            self.logger.info(f"Registered {registered} Repository REST resources")

    def _init_enterprise_components(self) -> None:
        """初始化企业级组件

        所有 init_* 调用统一通过 ``_handle_init_error`` 处理异常：
        - ImportError（依赖缺失）和 Exception（配置错误/连接失败）统一捕获
        - fail_fast=true 时抛 ``ComponentInitError``（携带格式化错误信息）→ run() 干净退出
        - fail_fast=false 时输出醒目的 ``[组件初始化失败]`` 警告到 stderr → 继续启动
        不再有静默吞掉异常的情况，所有错误都输出明确的配置项/值/原因/建议。
        """
        self.logger.info("Initializing enterprise components...")

        # 从配置文件和环境变量加载配置
        config = self.application_context.get_config()
        fail_fast = self._should_fail_fast(config)

        # 生产环境安全检查
        if fail_fast:
            self._production_security_check(config)

        # 解析配置中的密钥引用 (${secret:xxx})
        try:
            from spring.security.secret_manager import resolve_secret_config
            resolved = resolve_secret_config(config)
            config.update(resolved)
            self.application_context._config = resolved
        except Exception as e:
            self.logger.debug(f"Secret resolution skipped: {e}")

        # 初始化日志（init_logging 内部已通过 strict 校验抛 LoggingConfigError，
        # 由 run() 专门捕获，此处不再包裹 try/except）
        init_logging(self._section(config.get('logging')))

        # 初始化Redis（延迟导入）
        redis_config = self._section(config.get('redis'))
        if redis_config.get('enabled', True):
            try:
                from spring.utils.redis_client import init_redis
                init_redis(redis_config)
                self.logger.info("Redis initialized")
            except Exception as e:
                self._handle_init_error('Redis', redis_config, e, fail_fast)

        # 初始化JWT（延迟导入，JWT 为核心依赖，不区分 enabled）
        try:
            from spring.security.jwt_utils import init_jwt
            init_jwt(self._section(config.get('jwt')))
            self.logger.info("JWT initialized")
        except Exception as e:
            self._handle_init_error('JWT', self._section(config.get('jwt')), e, fail_fast)

        # 初始化数据库（延迟导入）
        database_config = self._section(config.get('database'))
        orm_mode = str(database_config.get('orm', 'mybatis')).lower()
        if database_config.get('enabled', False) and orm_mode in {'sqlalchemy', 'both'}:
            try:
                from spring.orm.database import init_database
                init_database(database_config)
                self.logger.info("Database initialized")
            except Exception as e:
                self._handle_init_error('Database', database_config, e, fail_fast)

        # 初始化Nacos服务发现（延迟导入）
        discovery_config = self._section(config.get('discovery'))
        discovery_enabled = discovery_config.get('enabled', False) or any(
            isinstance(item, EnableDiscoveryClient)
            for item in getattr(self.main_class, '__spring_annotations__', [])
        )
        if discovery_enabled:
            try:
                from spring.cloud.discovery import init_discovery
                init_discovery(discovery_config)
                self.logger.info("Service discovery initialized")
            except Exception as e:
                self._handle_init_error('Discovery', discovery_config, e, fail_fast)

        # 初始化Seata分布式事务（延迟导入）
        seata_config = self._section(config.get('seata'))
        if seata_config.get('enabled', False):
            try:
                from spring.cloud.seata import init_seata
                init_seata(seata_config)
                self.logger.info("Seata distributed transaction initialized")
            except Exception as e:
                self._handle_init_error('Seata', seata_config, e, fail_fast)

        # 初始化Spring Cloud Config配置中心（延迟导入）
        # 支持两种启用方式：配置文件 spring.cloud.config.enabled=true 或 @EnableConfigServer 注解
        spring_config = self._section(config.get('spring'))
        cloud_config = self._section(spring_config.get('cloud'))
        config_center_cfg = self._section(cloud_config.get('config'))
        config_center_annotation = self._find_annotation(EnableConfigServer)
        config_center_enabled = config_center_cfg.get('enabled', False) or config_center_annotation is not None
        if config_center_enabled:
            try:
                # 注解参数覆盖配置
                if config_center_annotation:
                    merged_config = dict(config)
                    spring_cfg = merged_config.setdefault('spring', {}).setdefault('cloud', {}).setdefault('config', {})
                    spring_cfg['enabled'] = True
                    if config_center_annotation.uri:
                        spring_cfg['uri'] = config_center_annotation.uri
                    if config_center_annotation.profile:
                        spring_cfg.setdefault('profile', config_center_annotation.profile)
                    if config_center_annotation.backend:
                        spring_cfg.setdefault('backend', config_center_annotation.backend)
                    spring_cfg.setdefault('fail-fast', config_center_annotation.fail_fast)
                    from spring.cloud.config_center import init_config_center
                    init_config_center(merged_config)
                else:
                    from spring.cloud.config_center import init_config_center
                    init_config_center(config)
                self.logger.info("Spring Cloud Config center initialized")
            except Exception as e:
                self._handle_init_error('ConfigCenter', config_center_cfg, e, fail_fast)

        # 初始化Spring Cloud Bus事件总线（延迟导入）
        # 支持两种启用方式：配置文件 spring.cloud.bus.enabled=true 或 @EnableBus 注解
        bus_cfg = self._section(cloud_config.get('bus'))
        bus_annotation = self._find_annotation(EnableBus)
        bus_enabled = bus_cfg.get('enabled', False) or bus_annotation is not None
        if bus_enabled:
            try:
                if bus_annotation:
                    merged_config = dict(config)
                    bus_merged = merged_config.setdefault('spring', {}).setdefault('cloud', {}).setdefault('bus', {})
                    bus_merged['enabled'] = True
                    bus_merged.setdefault('destination', bus_annotation.destination)
                    bus_merged.setdefault('backend', bus_annotation.backend)
                    from spring.cloud.bus import init_bus
                    init_bus(merged_config)
                else:
                    from spring.cloud.bus import init_bus
                    init_bus(config)
                self.logger.info("Spring Cloud Bus event bus initialized")
            except Exception as e:
                self._handle_init_error('CloudBus', bus_cfg, e, fail_fast)

        # 初始化RabbitMQ（延迟导入）
        rabbitmq_config = self._section(config.get('rabbitmq'))
        if rabbitmq_config.get('enabled', False):
            try:
                from spring.messaging.rabbitmq import init_rabbitmq
                init_rabbitmq(rabbitmq_config)
                self.logger.info("RabbitMQ initialized")
            except Exception as e:
                self._handle_init_error('RabbitMQ', rabbitmq_config, e, fail_fast)

        # 初始化Kafka（延迟导入，配置 key 为 spring.kafka）
        kafka_config = self._section(spring_config.get('kafka'))
        if kafka_config.get('enabled', False):
            try:
                from spring.messaging.kafka import init_kafka
                init_kafka(config)
                self.logger.info("Kafka initialized")
            except Exception as e:
                self._handle_init_error('Kafka', kafka_config, e, fail_fast)

        # 初始化OAuth2资源服务器（延迟导入）
        # 支持两种启用方式：配置文件 spring.security.oauth2.* 或 @EnableOAuth2 注解
        security_config = self._section(spring_config.get('security'))
        oauth2_config = self._section(security_config.get('oauth2'))
        oauth2_annotation = self._find_annotation(EnableOAuth2)
        oauth2_enabled = bool(oauth2_config.get('enabled', False)) or oauth2_annotation is not None
        if oauth2_enabled:
            try:
                if oauth2_annotation:
                    merged_config = dict(config)
                    oauth2_merged = merged_config.setdefault('spring', {}).setdefault('security', {}).setdefault('oauth2', {})
                    oauth2_merged['enabled'] = True
                    if oauth2_annotation.issuer:
                        oauth2_merged['issuer'] = oauth2_annotation.issuer
                    if oauth2_annotation.audiences:
                        oauth2_merged['audiences'] = oauth2_annotation.audiences
                    if oauth2_annotation.jwks_uri:
                        oauth2_merged['jwks_uri'] = oauth2_annotation.jwks_uri
                    if oauth2_annotation.algorithms:
                        oauth2_merged['algorithms'] = oauth2_annotation.algorithms
                    if oauth2_annotation.secret_key:
                        oauth2_merged['secret-key'] = oauth2_annotation.secret_key
                    from spring.security.oauth2 import init_oauth2
                    init_oauth2(merged_config)
                else:
                    from spring.security.oauth2 import init_oauth2
                    init_oauth2(config)
                self.logger.info("OAuth2 resource server initialized")
            except Exception as e:
                self._handle_init_error('OAuth2', oauth2_config, e, fail_fast)

        # 初始化CSRF防护（延迟导入）
        # 支持两种启用方式：配置文件 server.csrf.enabled=true 或 @EnableCsrf 注解
        server_config = self._section(config.get('server'))
        csrf_config = self._section(server_config.get('csrf'))
        csrf_annotation = self._find_annotation(EnableCsrf)
        csrf_enabled = csrf_config.get('enabled', False) or csrf_annotation is not None
        if csrf_enabled:
            try:
                if csrf_annotation:
                    merged_config = dict(config)
                    csrf_merged = merged_config.setdefault('server', {}).setdefault('csrf', {})
                    csrf_merged['enabled'] = True
                    csrf_merged.setdefault('token_length', csrf_annotation.token_length)
                    csrf_merged.setdefault('token_ttl', csrf_annotation.token_ttl)
                    csrf_merged.setdefault('cookie_name', csrf_annotation.cookie_name)
                    csrf_merged.setdefault('header_name', csrf_annotation.header_name)
                    csrf_merged.setdefault('secure_cookie', csrf_annotation.secure_cookie)
                    csrf_merged.setdefault('same_site', csrf_annotation.same_site)
                    from spring.web.csrf import init_csrf
                    init_csrf(merged_config)
                else:
                    from spring.web.csrf import init_csrf
                    init_csrf(config)
                self.logger.info("CSRF protection initialized")
            except Exception as e:
                self._handle_init_error('CSRF', csrf_config, e, fail_fast)

        # 初始化Prometheus监控（延迟导入）
        prometheus_config = self._section(config.get('prometheus'))
        if prometheus_config.get('enabled', False):
            try:
                from spring.monitoring.prometheus import init_prometheus
                init_prometheus(prometheus_config)
                self.logger.info("Prometheus monitoring initialized")
            except Exception as e:
                self._handle_init_error('Prometheus', prometheus_config, e, fail_fast)

        # 初始化DevTools热重载（仅开发环境）
        # 支持两种启用方式：配置文件 spring.devtools.restart.enabled=true 或 @EnableDevTools 注解
        devtools_config = self._section(self._section(spring_config.get('devtools')).get('restart'))
        devtools_annotation = self._find_annotation(EnableDevTools)
        devtools_enabled = devtools_config.get('enabled', False) or devtools_annotation is not None
        if devtools_enabled:
            try:
                if devtools_annotation:
                    merged_config = dict(config)
                    dt_merged = merged_config.setdefault('spring', {}).setdefault('devtools', {}).setdefault('restart', {})
                    dt_merged['enabled'] = True
                    if devtools_annotation.watch_dirs:
                        dt_merged['watch_dirs'] = devtools_annotation.watch_dirs
                    dt_merged['poll_interval'] = devtools_annotation.poll_interval
                    if devtools_annotation.exclude_dirs:
                        dt_merged['exclude_dirs'] = devtools_annotation.exclude_dirs
                    config_for_devtools = merged_config
                else:
                    config_for_devtools = config
                from spring.devtools import create_devtools_watcher
                watcher = create_devtools_watcher(
                    config_for_devtools,
                    restart_callback=lambda changed: self.logger.info(
                        f"DevTools detected file changes: {changed}"
                    ),
                )
                if watcher is not None:
                    self.logger.info("DevTools hot reload enabled")
            except Exception as e:
                self._handle_init_error('DevTools', devtools_config, e, fail_fast)

        # 初始化Spring Data REST（扫描 @RepositoryRestResource 标记的 Repository）
        # 支持两种启用方式：配置文件 spring.data.rest.enabled=true 或 @EnableDataRest 注解
        data_rest_cfg = self._section(self._section(spring_config.get('data')).get('rest'))
        data_rest_annotation = self._find_annotation(EnableDataRest)
        data_rest_enabled = data_rest_cfg.get('enabled', False) or data_rest_annotation is not None
        if data_rest_enabled:
            try:
                base_path = (data_rest_annotation.base_path if data_rest_annotation else data_rest_cfg.get('base_path', '')) or ''
                self._register_repository_rest_resources(base_path)
                self.logger.info(f"Spring Data REST enabled (base_path={base_path or '/api'})")
            except Exception as e:
                self._handle_init_error('DataRest', data_rest_cfg, e, fail_fast)

        self.logger.info("Enterprise components initialization completed")

    def _prepare_context(self) -> None:
        self.logger.info("Preparing application context...")
        self.application_context = ApplicationContext(self.main_class)
        try:
            self._init_enterprise_components()
            config = self.application_context.get_config()
            fail_fast = self._should_fail_fast(config)

            # 在refresh之前先初始化MyBatis，确保Mapper在组件扫描时可用
            try:
                init_mybatis(self.application_context)
                self.logger.info("MyBatis integration initialized")
            except Exception as e:
                self._handle_init_error('MyBatis', self._section(config.get('database')), e, fail_fast)

            self.application_context.refresh()

            self.logger.info(f"Registered {self.application_context.bean_factory.get_bean_count()} beans")
        except Exception:
            # MyBatis is initialized before refresh so mapper dependencies are
            # available during component construction.  If a later startup
            # phase fails, the normal refresh rollback cannot see or destroy
            # that pre-existing factory.  Tear down the whole context here so
            # failed starts do not retain SQLite/MySQL handles or background
            # resources (especially important for reloaders and Windows).
            context = self.application_context
            if context is not None:
                try:
                    context.destroy()
                except Exception as cleanup_error:
                    self.logger.warning(
                        f"Failed to clean up application context after startup error: {cleanup_error}"
                    )
            raise

    def _on_app_startup(self) -> None:
        """在 ASGI worker 已启动后创建后台线程并注册服务。"""
        if self._background_started:
            return
        config = self.application_context.get_config()
        fail_fast = self._should_fail_fast(config)
        seata_config = self._section(config.get('seata'))
        if seata_config.get('enabled', False) and str(
            seata_config.get('mode', 'local')
        ).lower() == 'http':
            try:
                from spring.cloud.seata import seata_manager
                seata_manager.start_recovery_worker()
            except Exception as exc:
                self._handle_init_error('Seata HTTP Recovery', seata_config, exc, fail_fast)
        rabbitmq_config = self._section(config.get('rabbitmq'))
        if rabbitmq_config.get('enabled', False):
            try:
                from spring.messaging.rabbitmq import rabbitmq_client
                rabbitmq_client.start_consuming_background()
            except Exception as exc:
                self._handle_init_error('RabbitMQ Consumer', rabbitmq_config, exc, fail_fast)
        # 启动 Kafka 消费者后台线程（延迟导入）
        spring_config = self._section(config.get('spring'))
        kafka_config = self._section(spring_config.get('kafka'))
        if kafka_config.get('enabled', False):
            try:
                from spring.messaging.kafka import kafka_client
                kafka_client.start_consuming()
            except Exception as exc:
                self._handle_init_error('Kafka Consumer', kafka_config, exc, fail_fast)
        port = self._section(config.get('server')).get('port', 8080)
        self._register_discovery_service(port)
        self._background_started = True

    def _configure_web_lifecycle(self) -> None:
        app = self.web_context.fastapi_app
        app.router.add_event_handler('startup', self._on_app_startup)
        app.router.add_event_handler('shutdown', self._deregister_discovery_service)
        app.router.add_event_handler('shutdown', self._on_app_shutdown)

    @staticmethod
    def _should_fail_fast(config: dict) -> bool:
        if not isinstance(config, dict):
            return False
        startup_config = config.get('startup', {})
        startup_config = startup_config if isinstance(startup_config, dict) else {}
        if 'fail_fast' in startup_config:
            value = startup_config['fail_fast']
            if isinstance(value, str):
                return value.strip().lower() in {'true', '1', 'yes', 'on'}
            return bool(value)
        spring_config = config.get('spring', {})
        spring_config = spring_config if isinstance(spring_config, dict) else {}
        profile_config = spring_config.get('profiles', {})
        profile_config = profile_config if isinstance(profile_config, dict) else {}
        profile = str(profile_config.get('active', 'default')).lower()
        return profile in {'prod', 'production'}

    def _production_security_check(self, config: dict) -> None:
        """生产环境安全检查"""
        if not isinstance(config, dict):
            config = {}
        warnings = []
        # 检查JWT密钥是否为默认值
        jwt_config = self._section(config.get('jwt'))
        jwt_secret = jwt_config.get('secret_key', '')
        if jwt_secret in ('', 'your-secret-key', 'secret', 'changeme', 'springpy-secret'):
            warnings.append("JWT secret_key is default/empty, MUST set strong secret in production")

        # 检查数据库是否无密码
        db_config = self._section(config.get('database'))
        if db_config.get('enabled', False) and not db_config.get('password'):
            warnings.append("Database password is empty, MUST set password in production")

        # 检查CORS是否全开
        server_config = self._section(config.get('server'))
        cors_config = self._section(server_config.get('cors', config.get('cors', {})))
        allow_origins = cors_config.get('allow_origins', [])
        if '*' in (allow_origins if isinstance(allow_origins, list) else [allow_origins]):
            warnings.append("CORS allows all origins (*), restrict to specific domains in production")

        # 检查是否启用了debug模式
        if config.get('debug', False) or server_config.get('debug', False):
            warnings.append("Debug mode is enabled, MUST disable in production")

        # 检查Docker IP自动检测
        import os
        if not os.getenv('SPRING_DISABLE_DOCKER_IP_DETECT'):
            warnings.append("SPRING_DISABLE_DOCKER_IP_DETECT not set, should be 1 in production")

        if warnings:
            for w in warnings:
                self.logger.warning(f"[PROD-SECURITY] {w}")

    def _start_web_server(self, **kwargs) -> None:
        self.logger.info("Initializing web context...")
        self.web_context = WebApplicationContext(self.application_context)
        self.web_context.init()
        self._configure_web_lifecycle()

        # 注册 CSRF 中间件（如已通过 init_csrf 启用）
        try:
            from spring.web.csrf import get_csrf_token_manager, CSRFMiddleware
            token_manager = get_csrf_token_manager()
            if token_manager is not None:
                self.web_context.fastapi_app.add_middleware(
                    CSRFMiddleware, token_manager=token_manager
                )
                self.logger.info("CSRF middleware registered")
        except Exception:
            self.logger.debug("Non-critical operation skipped")

        # 注册 @RepositoryRestResource 标记的 Repository REST 端点
        pending_controllers = getattr(self, '_pending_rest_controllers', [])
        if pending_controllers:
            for controller in pending_controllers:
                try:
                    controller.register(self.web_context.fastapi_app)
                except Exception as e:
                    self.logger.warning(f"Failed to register REST controller: {e}")
            self._pending_rest_controllers = []

        # 注册优雅退出信号处理
        try:
            from spring.core.graceful_shutdown import shutdown_handler
            shutdown_handler.register_signals()
            # 注册资源关闭钩子
            shutdown_handler.register_hook("discovery_deregister", self._deregister_discovery_service, order=10)
        except Exception:
            self.logger.debug("Non-critical operation skipped")

        # 从配置获取端口和主机
        config = self.application_context.get_config()
        server_config = self._section(config.get('server'))
        
        port = kwargs.get('port', server_config.get('port', 8080))
        host = kwargs.get('host', server_config.get('host', '0.0.0.0'))  # nosec B104 - server bind is operator controlled

        banner = BannerPrinter()
        banner.print_startup_info(port)

        self.web_context.run(host=host, port=port)

    async def _on_app_shutdown(self):
        """ASGI应用关闭事件回调"""
        try:
            from spring.cloud.seata import seata_manager
            seata_manager.stop_recovery_worker()
        except Exception:
            self.logger.debug("Non-critical operation skipped")
        # 停止 Kafka 消费者线程
        try:
            from spring.messaging.kafka import kafka_client
            kafka_client.stop_consuming()
        except Exception:
            self.logger.debug("Non-critical operation skipped")
        try:
            from spring.core.graceful_shutdown import shutdown_handler
            if not shutdown_handler._signal_received:
                # 如果是ASGI服务器直接关闭（非信号触发），执行关闭钩子
                # Run the synchronous drain/hook coordinator off the ASGI
                # event-loop thread.  Async hooks bound to this loop can then
                # make progress while ``GracefulShutdown`` waits for them.
                await asyncio.to_thread(shutdown_handler.initiate_shutdown)
        except Exception:
            self.logger.debug("Non-critical operation skipped")

    def _register_discovery_service(self, port: int) -> None:
        """Register the running application after its HTTP port is known."""
        annotations = getattr(self.main_class, '__spring_annotations__', [])
        enabled = any(isinstance(item, EnableDiscoveryClient) for item in annotations)
        config = self.application_context.get_config()
        discovery_config = self._section(config.get('discovery'))
        if not enabled and not discovery_config.get('enabled', False):
            return
        spring_config = self._section(config.get('spring'))
        application_config = self._section(spring_config.get('application'))
        root_application_config = self._section(config.get('application'))
        service_name = application_config.get('name') or root_application_config.get('name')
        if not service_name:
            self.logger.warning("Discovery enabled but spring.application.name is missing")
            return
        try:
            from spring.cloud import discovery
            ip = discovery_config.get('ip') or discovery_config.get('host')
            if not ip or ip in {'0.0.0.0', '::'}:  # nosec B104 - comparison, not a socket bind
                ip = '127.0.0.1'
                try:
                    ip = socket.gethostbyname(socket.gethostname())
                except OSError:
                    pass
            if discovery.nacos_client.register_service(
                service_name,
                ip,
                int(port),
                metadata=discovery_config.get('metadata', {}),
            ):
                self._discovery_registered = True
        except Exception as exc:
            self.logger.warning(f"Service discovery registration failed: {exc}")

    def _deregister_discovery_service(self) -> None:
        if not self._discovery_registered or self.application_context is None:
            return
        try:
            from spring.cloud import discovery
            service_name = self.application_context.get_value('spring.application.name')
            if service_name:
                discovery.nacos_client.deregister_service(
                    service_name,
                    discovery.nacos_client._ip,
                    discovery.nacos_client._port,
                )
        except Exception as exc:
            self.logger.warning(f"Service discovery deregistration failed: {exc}")
        finally:
            self._discovery_registered = False


def run(main_class: Type, **kwargs) -> None:
    app = SpringApplication(main_class)
    app.run(**kwargs)


def create_app(main_class: Type):
    """构建ASGI应用，供Uvicorn/Gunicorn等生产进程管理器加载。"""
    application = SpringApplication(main_class)
    try:
        application._prepare_context()
        application.web_context = WebApplicationContext(application.application_context)
        application.web_context.init()
        application._configure_web_lifecycle()
        asgi_app = application.web_context.get_app()
        asgi_app.state.spring_application = application
        return asgi_app
    except Exception:
        application._cleanup_after_start_failure()
        raise


def run_cli():
    """CLI entry point for springboot-python

    支持两种模式：
    1. 子命令模式：springbootai version / info / list / init / docs
    2. 传统启动模式：springbootai myapp.Application --port 8080

    自动检测第一个参数：如果是已知子命令则走子命令分发，否则走传统启动。
    """
    import sys

    # 已知的 CLI 子命令
    _KNOWN_SUBCOMMANDS = {'version', 'info', 'list', 'init', 'run', 'docs', '--help', '-h'}

    if len(sys.argv) > 1 and sys.argv[1] in _KNOWN_SUBCOMMANDS:
        # 子命令模式：委托给 spring.cli.main
        from spring.cli.main import main as cli_main
        return cli_main()

    # 传统启动模式：springbootai myapp.Application --port 8080
    import argparse
    import importlib

    parser = argparse.ArgumentParser(description="SpringBoot-Python CLI")
    parser.add_argument('module', help='Application module path (e.g., myapp.Application)')
    parser.add_argument('--port', type=int, default=8080, help='Server port')
    parser.add_argument('--host', default='0.0.0.0', help='Server host')  # nosec B104 - CLI server bind

    args = parser.parse_args()

    # Split module path
    if '.' in args.module:
        module_name, class_name = args.module.rsplit('.', 1)
    else:
        module_name = args.module
        class_name = 'Application'

    # Import module and get class
    module = importlib.import_module(module_name)
    main_class = getattr(module, class_name)

    # Run application
    run(main_class, port=args.port, host=args.host)
    return 0
