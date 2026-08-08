"""
example_all 应用入口
测试 SpringBoot 框架的全部注解和功能组合
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spring import SpringBootApplication
from spring.orm import MapperScan


@SpringBootApplication(scan_base_packages=["example_all"])
@MapperScan(base_packages=["example_all.mappers"])
class Application:
    """全注解示例应用启动类"""


if __name__ == "__main__":
    from spring import run
    run(Application, port=8080)
