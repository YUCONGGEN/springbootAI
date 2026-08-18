"""
Web全注解控制器 — 测试所有 Web 请求映射和参数绑定注解
- @RestController, @Controller
- @RequestMapping, @GetMapping, @PostMapping, @PutMapping, @DeleteMapping
- @RequestParam, @PathVariable, @RequestBody, @RequestHeader, @CookieValue
- @CrossOrigin, @ResponseStatus
"""
from springbootai.annotations.core import (
    RestController, Controller,
    RequestMapping, GetMapping, PostMapping, PutMapping, DeleteMapping,
    CrossOrigin, Autowired, Slf4j, ResponseStatus,
)
from springbootai.web.result import Result
from example_all.service.AllAnnotationService import AllAnnotationService


@RestController
@RequestMapping("/api/web")
@CrossOrigin(origins=["*"], methods=["GET", "POST", "PUT", "DELETE"])
@Slf4j
class AllWebController:
    """Web 全注解控制器 — 覆盖所有 HTTP 方法和参数绑定方式"""

    @Autowired
    def __init__(self, all_annotation_service: AllAnnotationService):
        self.service = all_annotation_service

    # ==================== @GetMapping 测试 ====================

    @GetMapping("/hello")
    def hello(self):
        """最简单的 @GetMapping"""
        return Result.success(data={"message": "Hello from example_all!"})

    @GetMapping("/hello/{name}")
    def hello_name(self, name: str):
        """@GetMapping + @PathVariable 隐式绑定（参数名匹配）"""
        return Result.success(data={"message": f"Hello, {name}!"})

    @GetMapping("/user/{user_id}")
    def get_user_detail(self, user_id: int):
        """@GetMapping + 路径参数 + 服务调用"""
        user = self.service.get_user_with_config(user_id, "web_controller")
        return Result.success(data=user)

    @GetMapping("/search")
    def search(self, keyword: str = "", page: int = 1, size: int = 10):
        """@GetMapping + @RequestParam 绑定查询参数含默认值"""
        return Result.success(data={"keyword": keyword, "page": page, "size": size})

    @GetMapping("/header")
    def test_header(self, x_request_id: str, authorization: str = ""):
        """@GetMapping + @RequestHeader"""
        return Result.success(data={
            "x_request_id": x_request_id,
            "auth_length": len(authorization),
        })

    @GetMapping("/cookie")
    def test_cookie(self, session_id: str = ""):
        """@GetMapping + @CookieValue"""
        return Result.success(data={"session_id": session_id or "not_set"})

    @GetMapping("/config/info")
    def get_config_info(self):
        """@GetMapping + 获取配置信息"""
        return Result.success(data=self.service.get_app_info())

    # ==================== @PostMapping 测试 ====================

    @PostMapping("/user")
    def create_user(self, user_data: dict):
        """@PostMapping + @RequestBody 自动绑定"""
        result = self.service.create_user(user_data)
        return Result.success(data=result)

    @PostMapping("/user/form")
    def create_user_form(self, username: str, email: str, phone: str = ""):
        """@PostMapping + @RequestParam（表单参数）"""
        return Result.success(data={
            "username": username, "email": email, "phone": phone,
            "created": True,
        })

    # ==================== @PutMapping 测试 ====================

    @PutMapping("/user/{user_id}")
    def update_user(self, user_id: int, user_data: dict):
        """@PutMapping + @PathVariable + @RequestBody 组合"""
        user_data["id"] = user_id
        return Result.success(data=self.service.update_user(user_id, user_data))

    # ==================== @DeleteMapping 测试 ====================

    @DeleteMapping("/user/{user_id}")
    def delete_user(self, user_id: int):
        """@DeleteMapping + @PathVariable"""
        success = self.service.delete_user(user_id)
        return Result.success(data={"deleted": success, "user_id": user_id})

    # ==================== 组合测试 ====================

    @GetMapping("/combined/{id}")
    @ResponseStatus(200)
    def combined(self, id: int, name: str = "default", x_trace_id: str = ""):
        """@GetMapping + @PathVariable + @RequestParam + @RequestHeader + @ResponseStatus"""
        return Result.success(data={
            "id": id, "name": name, "trace_header": x_trace_id,
        })

    @PostMapping("/batch")
    def batch_operations(self, operations: list):
        """@PostMapping + @RequestBody（数组）"""
        return Result.success(data={"count": len(operations), "processed": operations})


# ==================== @Controller 用法（非 REST） ====================

@Controller
@RequestMapping("/api/view")
class ViewController:
    """@Controller 非 REST 用法 — 测试 @Controller 注解"""

    @Autowired
    def __init__(self, all_annotation_service: AllAnnotationService):
        self.service = all_annotation_service

    @GetMapping("/info")
    def view_info(self):
        """@Controller + @GetMapping 返回 dict"""
        return {"view": "info", "data": self.service.get_app_info()}

    @GetMapping("/status")
    def view_status(self):
        return {"status": "running", "service": "example_all"}
