import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spring import SpringBootApplication


@SpringBootApplication(scan_base_packages=["testapp"])
class Application:
    """测试应用启动类"""
    pass


if __name__ == "__main__":
    from spring import run
    run(Application, port=8080)
