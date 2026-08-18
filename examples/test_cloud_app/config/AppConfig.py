from springbootai.annotations.core import Configuration, Bean, Value, ConfigurationProperties


@Configuration
class AppConfig:
    """应用配置类"""
    
    @Value("app.name")
    def __init__(self):
        self.app_name: str = ""
        self.app_version: str = ""
    
    @Bean
    def app_info(self) -> dict:
        """创建应用信息 Bean"""
        return {
            "name": self.app_name,
            "version": self.app_version,
            "description": "Spring-Python Test Application"
        }
    
    @Bean(name="custom_message")
    def create_custom_message(self) -> str:
        """创建自定义消息 Bean"""
        return f"Welcome to {self.app_name} v{self.app_version}"
    
    @Bean(scope="singleton")
    def counter(self) -> dict:
        """创建计数器 Bean"""
        return {"count": 0}


@ConfigurationProperties(prefix="database")
class DatabaseConfig:
    """数据库配置类"""
    
    def __init__(self):
        self.url: str = ""
        self.username: str = ""
        self.password: str = ""
        self.pool_size: int = 0


@ConfigurationProperties(prefix="app.cache")
class CacheConfig:
    """缓存配置类"""
    
    def __init__(self):
        self.max_size: int = 1000
        self.ttl: int = 300
