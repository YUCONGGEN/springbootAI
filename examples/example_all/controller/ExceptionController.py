"""用于测试 ``common.advice`` 的异常触发接口。"""

from springbootai.annotations import GetMapping, RestController


@RestController
class ErrorTriggerController:
    """主动抛出异常，以验证全局 Advice。"""

    @GetMapping("/api/errors/value")
    def trigger_value_error(self):
        raise ValueError("This is a test ValueError")

    @GetMapping("/api/errors/type")
    def trigger_type_error(self):
        raise TypeError("This is a test TypeError")

    @GetMapping("/api/errors/runtime")
    def trigger_runtime_error(self):
        raise RuntimeError("This is a test RuntimeError")

    @GetMapping("/api/errors/custom")
    def trigger_custom(self, error_type: str = "value"):
        if error_type == "value":
            raise ValueError("Triggered ValueError")
        if error_type == "permission":
            raise PermissionError("Triggered PermissionError")
        if error_type == "key":
            raise KeyError("Triggered KeyError")
        raise RuntimeError("Triggered RuntimeError")
