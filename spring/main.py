from typing import Type, Optional
import socket
import sys
from spring.context.application_context import ApplicationContext
from spring.web.web_context import WebApplicationContext
from spring.utils.banner import BannerPrinter
from spring.utils.logger import SpringLogger
from spring.logging.loguru_logger import init_logging, LoggingConfigError
from spring.orm.mybatis_integration import init_mybatis
from spring.annotations.cloud import EnableDiscoveryClient


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

    def run(self, **kwargs) -> None:
        banner = BannerPrinter()
        banner.print_banner()

        try:
            self._prepare_context()
            self._start_web_server(**kwargs)
        except LoggingConfigError as e:
            # 日志配置错误：错误信息已格式化（含配置项/值/原因/建议），
            # 干净退出不输出框架 traceback，让用户一眼定位问题
            print(f"\n应用启动失败（日志配置错误）:\n{e}\n", file=sys.stderr)
            sys.exit(1)
        except ComponentInitError as e:
            # 组件初始化失败：错误信息已格式化（含组件名/配置/原因/建议），
            # 干净退出不输出框架 traceback
            print(f"\n应用启动失败（组件初始化失败）:\n{e}\n", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
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
        init_logging(config.get('logging', {}))

        # 初始化Redis（延迟导入）
        if config.get('redis', {}).get('enabled', True):
            try:
                from spring.utils.redis_client import init_redis
                init_redis(config.get('redis', {}))
                self.logger.info("Redis initialized")
            except Exception as e:
                self._handle_init_error('Redis', config.get('redis', {}), e, fail_fast)

        # 初始化JWT（延迟导入，JWT 为核心依赖，不区分 enabled）
        try:
            from spring.security.jwt_utils import init_jwt
            init_jwt(config.get('jwt', {}))
            self.logger.info("JWT initialized")
        except Exception as e:
            self._handle_init_error('JWT', config.get('jwt', {}), e, fail_fast)

        # 初始化数据库（延迟导入）
        database_config = config.get('database', {})
        orm_mode = str(database_config.get('orm', 'mybatis')).lower()
        if database_config.get('enabled', False) and orm_mode in {'sqlalchemy', 'both'}:
            try:
                from spring.orm.database import init_database
                init_database(config.get('database', {}))
                self.logger.info("Database initialized")
            except Exception as e:
                self._handle_init_error('Database', config.get('database', {}), e, fail_fast)

        # 初始化Nacos服务发现（延迟导入）
        discovery_enabled = config.get('discovery', {}).get('enabled', False) or any(
            isinstance(item, EnableDiscoveryClient)
            for item in getattr(self.main_class, '__spring_annotations__', [])
        )
        if discovery_enabled:
            try:
                from spring.cloud.discovery import init_discovery
                init_discovery(config.get('discovery', {}))
                self.logger.info("Service discovery initialized")
            except Exception as e:
                self._handle_init_error('Discovery', config.get('discovery', {}), e, fail_fast)

        # 初始化Seata分布式事务（延迟导入）
        if config.get('seata', {}).get('enabled', False):
            try:
                from spring.cloud.seata import init_seata
                init_seata(config.get('seata', {}))
                self.logger.info("Seata distributed transaction initialized")
            except Exception as e:
                self._handle_init_error('Seata', config.get('seata', {}), e, fail_fast)

        # 初始化RabbitMQ（延迟导入）
        if config.get('rabbitmq', {}).get('enabled', False):
            try:
                from spring.messaging.rabbitmq import init_rabbitmq
                init_rabbitmq(config.get('rabbitmq', {}))
                self.logger.info("RabbitMQ initialized")
            except Exception as e:
                self._handle_init_error('RabbitMQ', config.get('rabbitmq', {}), e, fail_fast)

        # 初始化Prometheus监控（延迟导入）
        if config.get('prometheus', {}).get('enabled', False):
            try:
                from spring.monitoring.prometheus import init_prometheus
                init_prometheus(config.get('prometheus', {}))
                self.logger.info("Prometheus monitoring initialized")
            except Exception as e:
                self._handle_init_error('Prometheus', config.get('prometheus', {}), e, fail_fast)

        self.logger.info("Enterprise components initialization completed")

    def _prepare_context(self) -> None:
        self.logger.info("Preparing application context...")
        self.application_context = ApplicationContext(self.main_class)
        self._init_enterprise_components()
        config = self.application_context.get_config()
        fail_fast = self._should_fail_fast(config)

        # 在refresh之前先初始化MyBatis，确保Mapper在组件扫描时可用
        try:
            init_mybatis(self.application_context)
            self.logger.info("MyBatis integration initialized")
        except Exception as e:
            self._handle_init_error('MyBatis', config.get('database', {}), e, fail_fast)

        self.application_context.refresh()

        self.logger.info(f"Registered {self.application_context.bean_factory.get_bean_count()} beans")

    def _on_app_startup(self) -> None:
        """在 ASGI worker 已启动后创建后台线程并注册服务。"""
        if self._background_started:
            return
        config = self.application_context.get_config()
        fail_fast = self._should_fail_fast(config)
        if config.get('seata', {}).get('enabled', False) and str(
            config.get('seata', {}).get('mode', 'local')
        ).lower() == 'http':
            try:
                from spring.cloud.seata import seata_manager
                seata_manager.start_recovery_worker()
            except Exception as exc:
                self._handle_init_error('Seata HTTP Recovery', config.get('seata', {}), exc, fail_fast)
        if config.get('rabbitmq', {}).get('enabled', False):
            try:
                from spring.messaging.rabbitmq import rabbitmq_client
                rabbitmq_client.start_consuming_background()
            except Exception as exc:
                self._handle_init_error('RabbitMQ Consumer', config.get('rabbitmq', {}), exc, fail_fast)
        port = config.get('server', {}).get('port', 8080)
        self._register_discovery_service(port)
        self._background_started = True

    def _configure_web_lifecycle(self) -> None:
        app = self.web_context.fastapi_app
        app.router.add_event_handler('startup', self._on_app_startup)
        app.router.add_event_handler('shutdown', self._deregister_discovery_service)
        app.router.add_event_handler('shutdown', self._on_app_shutdown)

    @staticmethod
    def _should_fail_fast(config: dict) -> bool:
        startup_config = config.get('startup', {}) or {}
        if 'fail_fast' in startup_config:
            value = startup_config['fail_fast']
            if isinstance(value, str):
                return value.strip().lower() in {'true', '1', 'yes', 'on'}
            return bool(value)
        spring_config = config.get('spring', {}) or {}
        profile_config = spring_config.get('profiles', {}) or {}
        profile = str(profile_config.get('active', 'default')).lower()
        return profile in {'prod', 'production'}

    def _production_security_check(self, config: dict) -> None:
        """生产环境安全检查"""
        warnings = []
        # 检查JWT密钥是否为默认值
        jwt_config = config.get('jwt', {})
        jwt_secret = jwt_config.get('secret_key', '')
        if jwt_secret in ('', 'your-secret-key', 'secret', 'changeme', 'springpy-secret'):
            warnings.append("JWT secret_key is default/empty, MUST set strong secret in production")

        # 检查数据库是否无密码
        db_config = config.get('database', {})
        if db_config.get('enabled', False) and not db_config.get('password'):
            warnings.append("Database password is empty, MUST set password in production")

        # 检查CORS是否全开
        server_config = config.get('server', {}) or {}
        cors_config = server_config.get('cors', config.get('cors', {})) or {}
        allow_origins = cors_config.get('allow_origins', [])
        if '*' in (allow_origins if isinstance(allow_origins, list) else [allow_origins]):
            warnings.append("CORS allows all origins (*), restrict to specific domains in production")

        # 检查是否启用了debug模式
        if config.get('debug', False) or config.get('server', {}).get('debug', False):
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

        # 注册优雅退出信号处理
        try:
            from spring.core.graceful_shutdown import shutdown_handler
            shutdown_handler.register_signals()
            # 注册资源关闭钩子
            shutdown_handler.register_hook("discovery_deregister", self._deregister_discovery_service, order=10)
        except Exception:
            pass

        # 从配置获取端口和主机
        config = self.application_context.get_config()
        server_config = config.get('server', {})
        
        port = kwargs.get('port', server_config.get('port', 8080))
        host = kwargs.get('host', server_config.get('host', '0.0.0.0'))  # nosec B104 - server bind is operator controlled

        banner = BannerPrinter()
        banner.print_startup_info(port)

        self.web_context.run(host=host, port=port)

    def _on_app_shutdown(self):
        """ASGI应用关闭事件回调"""
        try:
            from spring.cloud.seata import seata_manager
            seata_manager.stop_recovery_worker()
        except Exception:
            pass
        try:
            from spring.core.graceful_shutdown import shutdown_handler
            if not shutdown_handler._signal_received:
                # 如果是ASGI服务器直接关闭（非信号触发），执行关闭钩子
                shutdown_handler.initiate_shutdown()
        except Exception:
            pass

    def _register_discovery_service(self, port: int) -> None:
        """Register the running application after its HTTP port is known."""
        annotations = getattr(self.main_class, '__spring_annotations__', [])
        enabled = any(isinstance(item, EnableDiscoveryClient) for item in annotations)
        config = self.application_context.get_config()
        discovery_config = config.get('discovery', {})
        if not enabled and not discovery_config.get('enabled', False):
            return
        service_name = (
            config.get('spring', {}).get('application', {}).get('name')
            or config.get('application', {}).get('name')
        )
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
    application._prepare_context()
    application.web_context = WebApplicationContext(application.application_context)
    application.web_context.init()
    application._configure_web_lifecycle()
    asgi_app = application.web_context.get_app()
    asgi_app.state.spring_application = application
    return asgi_app


def run_cli():
    """CLI entry point for springboot-python"""
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
