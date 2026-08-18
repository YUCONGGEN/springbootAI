import sys
import os

# 移动到 examples/ 后需同时加入项目根（导入 spring）和 examples/（导入 test_cloud_app 包）
_HERE = os.path.dirname(os.path.abspath(__file__))
_EXAMPLES_DIR = os.path.dirname(_HERE)
_PROJECT_ROOT = os.path.dirname(_EXAMPLES_DIR)
for _p in (_PROJECT_ROOT, _EXAMPLES_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from springbootai import SpringBootApplication


@SpringBootApplication(scan_base_packages=["testapp"])
class Application:
    """测试应用启动类"""
    pass


if __name__ == "__main__":
    from springbootai import run
    run(Application, port=8080)
