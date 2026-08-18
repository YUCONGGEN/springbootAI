"""
配置类集合 — 测试 @Configuration, @Bean, @Value, @ConfigurationProperties, @Profile, @Primary, @Lazy, @Autowired
"""
from springbootai.annotations.core import (
    Configuration, Bean, Value, ConfigurationProperties,
    Autowired, Profile, Primary, Lazy, Slf4j, PostConstruct, PreDestroy,
)


# ==================== 基础配置类 ====================

@Configuration
@Slf4j
class AppConfig:
    """应用基本配置 — @Configuration, @Bean, @Value, @PostConstruct, @PreDestroy"""

    @Value("app.name")
    def __init__(self, app_name: str = "example_all"):
        self.app_name = app_name

    @PostConstruct
    def init(self):
        self.logger.info(f"AppConfig 初始化完成: app_name={self.app_name}")

    @PreDestroy
    def cleanup(self):
        self.logger.info("AppConfig 销毁")

    @Bean
    def app_info(self) -> dict:
        """@Bean 基本用法"""
        return {
            "name": self.app_name,
            "version": "1.0.0",
            "description": "example_all — SpringBootAI全注解用例"
        }

    @Bean(name="customGreeting")
    def greeting_bean(self) -> str:
        """@Bean 指定 name"""
        return f"Hello from {self.app_name}!"

    @Bean(scope="singleton")
    def shared_counter(self) -> dict:
        """@Bean scope=singleton"""
        return {"count": 0}


# ==================== @ConfigurationProperties 配置绑定 ====================

@Configuration
@ConfigurationProperties(prefix="app")
class AppProperties:
    """@ConfigurationProperties 属性绑定"""
    def __init__(self):
        self.name: str = ""
        self.version: str = ""
        self.greeting: str = ""
        self.greeting_dev: str = ""
        self.admin_users: list = []


# ==================== @Profile 环境配置 ====================

@Configuration
@Profile("default")
class DefaultProfileConfig:
    """默认环境 Bean"""

    @Bean(name="profileMessage")
    def profile_message(self) -> str:
        return "Running in default profile"


@Configuration
@Profile("dev")
class DevProfileConfig:
    """开发环境 Bean"""

    @Bean(name="profileMessage")
    @Primary
    def dev_profile_message(self) -> str:
        return "Running in DEV profile"


# ==================== @Primary 和 @Lazy 用法 ====================

@Configuration
class PrimaryLazyConfig:

    @Bean(name="primaryService")
    @Primary
    def primary_bean(self) -> dict:
        """@Primary 优先注入"""
        return {"type": "primary", "data": "I am the primary bean"}

    @Bean(name="secondaryService")
    def secondary_bean(self) -> dict:
        return {"type": "secondary", "data": "I am the secondary bean"}

    @Bean
    @Lazy
    def lazy_bean(self) -> dict:
        """@Lazy 懒加载 Bean"""
        return {"type": "lazy", "initialized": True}


# ==================== @Autowired 注入配置值 ====================

@Configuration
class InjectConfig:
    """测试 @Autowired 在 @Configuration 中注入其他 Bean"""

    @Autowired
    def __init__(self, app_info: dict, customGreeting: str):
        self.app_info = app_info
        self.customGreeting = customGreeting

    @Bean(name="composedMessage")
    def composed_message(self) -> str:
        return f"[{self.app_info['name']}] {self.customGreeting}"
