from typing import Type, Optional
import socket
from spring.context.application_context import ApplicationContext
from spring.web.web_context import WebApplicationContext
from spring.utils.banner import BannerPrinter
from spring.utils.logger import SpringLogger
from spring.logging.loguru_logger import init_logging
from spring.orm.mybatis_integration import init_mybatis
from spring.annotations.cloud import EnableDiscoveryClient


class SpringApplication:
    def __init__(self, main_class: Type):
        self.main_class = main_class
        self.application_context: Optional[ApplicationContext] = None
        self.web_context: Optional[WebApplicationContext] = None
        self.logger = SpringLogger()
        self._discovery_registered = False

    def run(self, **kwargs) -> None:
        banner = BannerPrinter()
        banner.print_banner()

        try:
            self._prepare_context()
            self._start_web_server(**kwargs)
        except Exception as e:
            self.logger.error(f"Application failed to start: {str(e)}")
            raise

    def _init_enterprise_components(self) -> None:
        """初始化企业级组件"""
        self.logger.info("Initializing enterprise components...")
        
        # 从配置文件和环境变量加载配置
        config = self.application_context.get_config()
        fail_fast = self._should_fail_fast(config)
        
        # 初始化日志
        init_logging(config.get('logging', {}))
        
        # 初始化Redis（延迟导入）
        if config.get('redis', {}).get('enabled', True):
            try:
                from spring.utils.redis_client import init_redis
                init_redis(config.get('redis', {}))
                self.logger.info("Redis initialized")
            except ImportError:
                if fail_fast:
                    raise RuntimeError("Redis已启用但redis依赖未安装")
                self.logger.warning("Redis not available (redis package not installed)")
            except Exception as e:
                if fail_fast:
                    raise RuntimeError("Redis初始化失败") from e
                self.logger.warning(f"Failed to initialize Redis: {e}")
        
        # 初始化JWT（延迟导入）
        try:
            from spring.security.jwt_utils import init_jwt
            init_jwt(config.get('jwt', {}))
            self.logger.info("JWT initialized")
        except ImportError:
            raise RuntimeError("JWT核心依赖pyjwt未安装")
        
        # 初始化数据库（延迟导入）
        database_config = config.get('database', {})
        orm_mode = str(database_config.get('orm', 'mybatis')).lower()
        if database_config.get('enabled', False) and orm_mode in {'sqlalchemy', 'both'}:
            try:
                from spring.orm.database import init_database
                init_database(config.get('database', {}))
                self.logger.info("Database initialized")
            except ImportError:
                if fail_fast:
                    raise RuntimeError("SQLAlchemy已启用但依赖未安装")
                self.logger.warning("Database not available (sqlalchemy not installed)")
            except Exception as e:
                if fail_fast:
                    raise RuntimeError("SQLAlchemy数据库初始化失败") from e
                self.logger.warning(f"Failed to initialize Database: {e}")
        
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
            except ImportError:
                if fail_fast:
                    raise RuntimeError("服务发现已启用但Nacos依赖未安装")
                self.logger.warning("Service discovery not available (nacos-sdk-python not installed)")
            except Exception as e:
                if fail_fast:
                    raise RuntimeError("服务发现初始化失败") from e
                self.logger.warning(f"Failed to initialize Service Discovery: {e}")
        
        # 初始化Seata分布式事务（延迟导入）
        if config.get('seata', {}).get('enabled', False):
            try:
                from spring.cloud.seata import init_seata
                init_seata(config.get('seata', {}))
                self.logger.info("Seata distributed transaction initialized")
            except ImportError:
                if fail_fast:
                    raise RuntimeError("Seata已启用但依赖未安装")
                self.logger.warning("Seata not available")
            except Exception as e:
                if fail_fast:
                    raise RuntimeError("Seata初始化失败") from e
                self.logger.warning(f"Failed to initialize Seata: {e}")
        
        # 初始化RabbitMQ（延迟导入）
        if config.get('rabbitmq', {}).get('enabled', False):
            try:
                from spring.messaging.rabbitmq import init_rabbitmq
                init_rabbitmq(config.get('rabbitmq', {}))
                self.logger.info("RabbitMQ initialized")
            except ImportError:
                if fail_fast:
                    raise RuntimeError("RabbitMQ已启用但pika依赖未安装")
                self.logger.warning("RabbitMQ not available (pika not installed)")
            except Exception as e:
                if fail_fast:
                    raise RuntimeError("RabbitMQ初始化失败") from e
                self.logger.warning(f"Failed to initialize RabbitMQ: {e}")
        
        # 初始化Prometheus监控（延迟导入）
        if config.get('prometheus', {}).get('enabled', False):
            try:
                from spring.monitoring.prometheus import init_prometheus
                init_prometheus(config.get('prometheus', {}))
                self.logger.info("Prometheus monitoring initialized")
            except ImportError:
                if fail_fast:
                    raise RuntimeError("Prometheus已启用但依赖未安装")
                self.logger.warning("Prometheus not available (prometheus-client not installed)")
            except Exception as e:
                if fail_fast:
                    raise RuntimeError("Prometheus初始化失败") from e
                self.logger.warning(f"Failed to initialize Prometheus: {e}")
        
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
            if fail_fast:
                raise RuntimeError("MyBatis初始化失败") from e
            self.logger.warning(f"Failed to initialize MyBatis integration: {e}")
        
        self.application_context.refresh()

        if config.get('rabbitmq', {}).get('enabled', False):
            try:
                from spring.messaging.rabbitmq import rabbitmq_client
                rabbitmq_client.start_consuming_background()
            except Exception as e:
                if fail_fast:
                    raise RuntimeError("RabbitMQ消费者启动失败") from e
                self.logger.warning(f"Failed to start RabbitMQ consumers: {e}")
        
        self.logger.info(f"Registered {self.application_context.bean_factory.get_bean_count()} beans")

    @staticmethod
    def _should_fail_fast(config: dict) -> bool:
        startup_config = config.get('startup', {})
        if 'fail_fast' in startup_config:
            return bool(startup_config['fail_fast'])
        profile = str(config.get('spring', {}).get('profiles', {}).get('active', 'default')).lower()
        return profile in {'prod', 'production'}

    def _start_web_server(self, **kwargs) -> None:
        self.logger.info("Initializing web context...")
        self.web_context = WebApplicationContext(self.application_context)
        self.web_context.init()
        self.web_context.fastapi_app.router.add_event_handler(
            'shutdown', self._deregister_discovery_service
        )

        # 从配置获取端口和主机
        config = self.application_context.get_config()
        server_config = config.get('server', {})
        
        port = kwargs.get('port', server_config.get('port', 8080))
        host = kwargs.get('host', server_config.get('host', '0.0.0.0'))

        banner = BannerPrinter()
        banner.print_startup_info(port)

        self._register_discovery_service(port)

        self.web_context.run(host=host, port=port)

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
            if not ip or ip in {'0.0.0.0', '::'}:
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
    config = application.application_context.get_config()
    application._register_discovery_service(config.get('server', {}).get('port', 8080))
    application.web_context.fastapi_app.router.add_event_handler(
        'shutdown', application._deregister_discovery_service
    )
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
    parser.add_argument('--host', default='0.0.0.0', help='Server host')
    
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
