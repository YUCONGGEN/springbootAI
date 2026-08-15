"""
example_all 应用入口
测试 SpringBootAI 框架的全部注解和功能组合
"""
import sys
import os

# 移动到 examples/ 后需同时加入项目根（导入 spring）和 examples/（导入 example_all 包）
_HERE = os.path.dirname(os.path.abspath(__file__))
_EXAMPLES_DIR = os.path.dirname(_HERE)
_PROJECT_ROOT = os.path.dirname(_EXAMPLES_DIR)
for _p in (_PROJECT_ROOT, _EXAMPLES_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from spring import SpringBootApplication
from spring.orm import MapperScan


@SpringBootApplication(scan_base_packages=["example_all"])
@MapperScan(base_packages=["example_all.mappers"])
class Application:
    """全注解示例应用启动类"""


if __name__ == "__main__":
    from spring import run
    run(Application, port=8080)
