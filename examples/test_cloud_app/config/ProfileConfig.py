from spring.annotations.core import Configuration, Bean, Profile, Primary


@Configuration
class ProfileConfig:
    """Profile 和 Primary 测试配置类"""
    
    @Bean
    @Primary
    def default_service(self) -> str:
        """默认服务 - 测试 @Primary"""
        return "Default Service"
    
    @Bean
    def alternative_service(self) -> str:
        """备选服务"""
        return "Alternative Service"
    
    @Bean
    @Profile("dev")
    def dev_config(self) -> dict:
        """开发环境配置 - 测试 @Profile"""
        return {"env": "development", "debug": True}
    
    @Bean
    @Profile("prod")
    def prod_config(self) -> dict:
        """生产环境配置 - 测试 @Profile"""
        return {"env": "production", "debug": False}
    
    @Bean
    @Profile(["test", "qa"])
    def test_config(self) -> dict:
        """测试环境配置 - 测试多 Profile"""
        return {"env": "test", "debug": True}
