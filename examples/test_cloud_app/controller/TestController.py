from springbootai.annotations.core import (
    RestController, RequestMapping, GetMapping, PostMapping, PutMapping, DeleteMapping,
    Autowired,
)
from springbootai.web.result import Result


@RestController
@RequestMapping("/api")
class TestController:
    """测试控制器 - 测试所有请求映射和参数绑定注解"""
    
    @Autowired
    def __init__(self, test_service):
        self.test_service = test_service
    
    @GetMapping("/hello")
    def hello(self):
        """测试 @GetMapping"""
        return Result.success(data="Hello, Spring-Python!")
    
    @PostMapping("/user")
    def create_user(self, user_id: int, name: str):
        """测试 @PostMapping 和 @RequestParam"""
        user = self.test_service.create_user(user_id, name)
        return Result.success(data=user)
    
    @GetMapping("/user/{user_id}")
    def get_user(self, user_id: int):
        """测试 @GetMapping 和 @PathVariable"""
        user = self.test_service.get_user(user_id)
        return Result.success(data=user)
    
    @PutMapping("/user/{user_id}")
    def update_user(self, user_id: int, user_data: dict):
        """测试 @PutMapping 和 @RequestBody"""
        name = user_data.get("name", "Unknown")
        user = self.test_service.create_user(user_id, name)
        return Result.success(data=user)
    
    @DeleteMapping("/user/{user_id}")
    def delete_user(self, user_id: int):
        """测试 @DeleteMapping"""
        from springbootai.context.application_context import ApplicationContext
        ctx = ApplicationContext(None)
        user_repo = ctx.get_bean_by_type(type(self.test_service.user_repository))
        success = user_repo.delete(user_id)
        if success:
            return Result.success(data={"deleted": user_id})
        return Result.not_found(message="User not found")
    
    @GetMapping("/header")
    def test_header(self, x_test_header: str):
        """测试 @RequestHeader"""
        return Result.success(data={"header_value": x_test_header})
    
    @GetMapping("/cookie")
    def test_cookie(self, session_id: str):
        """测试 @CookieValue"""
        return Result.success(data={"session_id": session_id})
    
    @GetMapping("/params")
    def test_params(self, name: str = "Guest", age: int = 18):
        """测试带默认值的 @RequestParam"""
        return Result.success(data={"name": name, "age": age})
    
    @GetMapping("/async-task")
    def test_async(self, task_id: int):
        """测试异步任务"""
        result = self.test_service.async_task(task_id)
        return Result.success(data={"task_id": task_id, "status": "started"})
    
    @GetMapping("/retry")
    def test_retry(self, fail: bool = False):
        """测试重试机制"""
        try:
            result = self.test_service.flaky_operation(fail)
            return Result.success(data={"result": result})
        except Exception as e:
            return Result.error(message=str(e), code=500)
    
    @GetMapping("/transaction")
    def test_transaction(self, rollback: bool = False):
        """测试事务"""
        try:
            result = self.test_service.transaction_with_rollback(rollback)
            return Result.success(data={"result": result})
        except Exception as e:
            return Result.error(message=str(e), code=500)
    
    @GetMapping("/counter")
    def test_counter(self):
        """测试计数器"""
        count = self.test_service.increment_counter()
        return Result.success(data={"count": count})


@RestController
@RequestMapping("/config")
class ConfigController:
    """配置控制器 - 测试配置注入"""
    
    @Autowired
    def __init__(self, app_info, custom_message, database_config, cache_config):
        self.app_info = app_info
        self.custom_message = custom_message
        self.database_config = database_config
        self.cache_config = cache_config
    
    @GetMapping("/info")
    def get_app_info(self):
        """获取应用信息"""
        return Result.success(data=self.app_info)
    
    @GetMapping("/message")
    def get_message(self):
        """获取自定义消息"""
        return Result.success(data={"message": self.custom_message})
    
    @GetMapping("/database")
    def get_database_config(self):
        """获取数据库配置"""
        return Result.success(data={
            "url": self.database_config.url,
            "username": self.database_config.username,
            "pool_size": self.database_config.pool_size
        })
    
    @GetMapping("/cache")
    def get_cache_config(self):
        """获取缓存配置"""
        return Result.success(data={
            "max_size": self.cache_config.max_size,
            "ttl": self.cache_config.ttl
        })
