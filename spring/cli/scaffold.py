"""
SpringBootAI 项目脚手架

对齐 Java Spring Initializr，通过 ``springbootai init <project>`` 命令创建新项目。

使用示例::

    # 命令行
    springbootai init my-project --modules web,orm --port 9000

    # Python 代码
    from spring.cli.scaffold import main
    main(['my-project', '--modules', 'web,orm', '--port', '9000'])

生成的项目结构::

    my-project/
    ├── Application.py          # 启动类（含 @SpringBootApplication）
    ├── config/
    │   └── application.yml     # 配置文件
    ├── requirements.txt        # 依赖清单
    ├── README.md               # 项目说明
    └── src/
        └── my_project/         # Python 包（从项目名派生，连字符转下划线）
            ├── __init__.py
            └── models/         # orm 模块时生成
"""
import argparse
import os
import re
import sys
from pathlib import Path
from typing import List, Optional


# ==================== 模板 ====================

_APPLICATION_TEMPLATE = '''"""
{project_name} 启动类

自动生成于 SpringBootAI {version} 脚手架。
运行：python Application.py
"""
import sys
import os

# 将 src/ 目录加入 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from spring.annotations import SpringBootApplication
from {package}.controllers import *  # noqa: F401, F403


@SpringBootApplication
class Application:
    """应用启动入口"""

    @staticmethod
    def main():
        from spring.main import SpringApplication
        app = SpringApplication(Application)
        app.run()


if __name__ == '__main__':
    Application.main()
'''

_APPLICATION_YML_TEMPLATE = '''# {project_name} 配置文件
# SpringBootAI {version}

server:
  port: {port}
  host: 0.0.0.0

spring:
  application:
    name: {project_name}

{orm_config}{ai_config}{cloud_config}# 日志配置
logging:
  level:
    root: INFO
    spring: DEBUG
'''

_ORM_CONFIG = '''# ORM 配置
spring:
  datasource:
    url: sqlite:///app.db
    driver: sqlite
  jpa:
    ddl-auto:
      mode: update
    entity-packages:
      - {package}.models

'''

_AI_CONFIG = '''# AI 配置
spring:
  ai:
    model: gpt-4o-mini
    api-key: ${OPENAI_API_KEY}

'''

_CLOUD_CONFIG = '''# Cloud 配置
spring:
  cloud:
    nacos:
      discovery:
        server-addr: localhost:8848

'''

_REQUIREMENTS_TEMPLATE = '''# {project_name} 依赖
# SpringBootAI {version}
springbootAI=={version}
{extras}
'''

_README_TEMPLATE = '''# {project_name}

> 基于 SpringBootAI {version} 创建的项目

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动应用
python Application.py
```

## 项目结构

```
{project_name}/
├── Application.py          # 启动类
├── config/
│   └── application.yml     # 配置文件
├── requirements.txt        # 依赖清单
└── src/
    └── {package}/          # Python 包
        ├── __init__.py
        ├── controllers/    # 控制器
        └── models/         # 实体类（orm 模块）
```

## 模块说明

{modules_desc}

## 相关文档

- [SpringBootAI 文档](https://github.com/YUCONGGEN/springbootAI)
'''


# ==================== 核心逻辑 ====================

def _derive_package_name(project_name: str) -> str:
    """从项目名派生 Python 包名（连字符转下划线，小写）。"""
    # 替换连字符和空格为下划线
    pkg = re.sub(r'[-\s]+', '_', project_name)
    # 移除非法字符
    pkg = re.sub(r'[^a-zA-Z0-9_]', '', pkg)
    # 确保不以数字开头
    if pkg and pkg[0].isdigit():
        pkg = '_' + pkg
    return pkg.lower() or 'app'


def _validate_package_name(package: str) -> bool:
    """校验包名是否合法（Python 标识符）。"""
    return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', package))


def create_project(
    project_path: str,
    package: Optional[str] = None,
    modules: str = 'web',
    port: int = 8000,
) -> Path:
    """创建新项目。

    Args:
        project_path: 项目目录路径
        package: Python 包名（可选，默认从项目名派生）
        modules: 模块列表（逗号分隔，支持 web/orm/ai/cloud）
        port: 服务端口

    Returns:
        项目目录的 Path 对象

    Raises:
        ValueError: 参数校验失败
        FileExistsError: 项目目录已存在且非空
    """
    # 获取版本号
    try:
        from spring import __version__ as version
    except ImportError:
        version = '2.3.0'

    project_dir = Path(project_path).resolve()
    project_name = project_dir.name

    # 派生包名
    if not package:
        package = _derive_package_name(project_name)
    if not _validate_package_name(package):
        raise ValueError(
            f"Invalid package name: '{package}'. "
            f"Package name must be a valid Python identifier."
        )

    # 安全检查：拒绝覆盖已有非空目录
    if project_dir.exists() and any(project_dir.iterdir()):
        raise FileExistsError(
            f"Directory '{project_dir}' already exists and is not empty. "
            f"Refusing to overwrite."
        )

    # 解析模块列表
    module_list = [m.strip() for m in modules.split(',') if m.strip()]
    valid_modules = {'web', 'orm', 'ai', 'cloud'}
    for m in module_list:
        if m not in valid_modules:
            raise ValueError(
                f"Invalid module: '{m}'. Supported modules: {valid_modules}"
            )

    # 创建目录结构
    project_dir.mkdir(parents=True, exist_ok=True)
    config_dir = project_dir / 'config'
    config_dir.mkdir(exist_ok=True)

    src_dir = project_dir / 'src'
    pkg_dir = src_dir / package
    pkg_dir.mkdir(parents=True, exist_ok=True)

    # 生成 __init__.py
    (pkg_dir / '__init__.py').write_text(
        f'"""{project_name} package"""\n', encoding='utf-8'
    )

    # 生成 controllers 目录（web 模块需要）
    if 'web' in module_list:
        controllers_dir = pkg_dir / 'controllers'
        controllers_dir.mkdir(exist_ok=True)
        (controllers_dir / '__init__.py').write_text(
            f'"""{project_name} controllers"""\n\n'
            f'from spring.annotations import RestController, GetMapping\n\n'
            f'@RestController\n'
            f'class HelloController:\n'
            f'    """示例控制器"""\n\n'
            f'    @GetMapping("/hello")\n'
            f'    def hello(self):\n'
            f'        return {{"message": "Hello from {project_name}!"}}\n',
            encoding='utf-8'
        )

    # 生成 models 目录（orm 模块需要）
    if 'orm' in module_list:
        models_dir = pkg_dir / 'models'
        models_dir.mkdir(exist_ok=True)
        (models_dir / '__init__.py').write_text(
            f'"""{project_name} entity models"""\n', encoding='utf-8'
        )

    # 生成配置段
    orm_config = _ORM_CONFIG.format(package=package) if 'orm' in module_list else ''
    ai_config = _AI_CONFIG if 'ai' in module_list else ''
    cloud_config = _CLOUD_CONFIG if 'cloud' in module_list else ''

    # 生成 Application.py
    (project_dir / 'Application.py').write_text(
        _APPLICATION_TEMPLATE.format(
            project_name=project_name,
            package=package,
            version=version,
        ),
        encoding='utf-8'
    )

    # 生成 application.yml
    (config_dir / 'application.yml').write_text(
        _APPLICATION_YML_TEMPLATE.format(
            project_name=project_name,
            version=version,
            port=port,
            orm_config=orm_config,
            ai_config=ai_config,
            cloud_config=cloud_config,
        ),
        encoding='utf-8'
    )

    # 生成 requirements.txt
    extras_lines = []
    if 'orm' in module_list:
        extras_lines.append('PyMySQL==1.2.0  # MySQL 驱动')
    if 'ai' in module_list:
        extras_lines.append('langchain-openai==1.4.2  # LangChain')
    if 'cloud' in module_list:
        extras_lines.append('redis==8.1.0  # Redis')
    extras_str = '\n'.join(extras_lines) if extras_lines else ''

    (project_dir / 'requirements.txt').write_text(
        _REQUIREMENTS_TEMPLATE.format(
            project_name=project_name,
            version=version,
            extras=extras_str,
        ),
        encoding='utf-8'
    )

    # 生成 README.md
    modules_desc = '\n'.join(f'- **{m}**: {m} 模块' for m in module_list)
    (project_dir / 'README.md').write_text(
        _README_TEMPLATE.format(
            project_name=project_name,
            version=version,
            package=package,
            modules_desc=modules_desc,
        ),
        encoding='utf-8'
    )

    print(f"✅ Project '{project_name}' created at: {project_dir}")
    print(f"   Package: {package}")
    print(f"   Modules: {', '.join(module_list)}")
    print(f"   Port: {port}")
    print(f"\n   Next steps:")
    print(f"   1. cd {project_name}")
    print(f"   2. pip install -r requirements.txt")
    print(f"   3. python Application.py")

    return project_dir


def main(argv: Optional[List[str]] = None) -> int:
    """脚手架命令行入口。

    Args:
        argv: 命令行参数列表（不含脚本名）。如果为 None，从 sys.argv 读取。

    Returns:
        退出码（0=成功，1=失败）
    """
    parser = argparse.ArgumentParser(
        prog='springbootai init',
        description='Create a new SpringBootAI project (like Spring Initializr)',
    )
    parser.add_argument(
        'project',
        help='Project name or path (e.g., my-project or ./my-project)',
    )
    parser.add_argument(
        '--package', '-p',
        default=None,
        help='Python package name (default: derived from project name)',
    )
    parser.add_argument(
        '--modules', '-m',
        default='web',
        help='Comma-separated modules: web,orm,ai,cloud (default: web)',
    )
    parser.add_argument(
        '--port',
        type=int,
        default=8000,
        help='Server port (default: 8000)',
    )

    args = parser.parse_args(argv)

    try:
        create_project(
            project_path=args.project,
            package=args.package,
            modules=args.modules,
            port=args.port,
        )
        return 0
    except (ValueError, FileExistsError) as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
