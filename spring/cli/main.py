"""Spring CLI 命令行工具（对齐 Spring Boot CLI）

提供统一的 ``springbootai`` 命令入口，支持多个子命令：

- ``springbootai init <project>``  初始化新项目（复用 scaffold）
- ``springbootai version``         显示框架版本信息
- ``springbootai info``            显示运行环境信息
- ``springbootai list modules``    列出可用模块
- ``springbootai list annotations`` 列出可用注解
- ``springbootai run``             运行应用
- ``springbootai docs``            生成 API 文档（Sphinx）

用法示例::

    springbootai version
    springbootai init my-project --modules web,orm
    springbootai list modules
    springbootai list annotations
    springbootai run Application.py
    springbootai docs --output docs/_build

与 Java Spring Boot CLI 的差异：
- Java CLI 支持 Groovy 脚本直接运行，Python 版本仅支持 .py 文件
- Java CLI 集成 Spring Initializr，Python 版本通过 scaffold 子命令实现
- Java CLI 支持依赖管理，Python 版本通过 pip extras 实现
"""
from __future__ import annotations

import argparse
import importlib
import os
import platform
import runpy
import sys
from pathlib import Path
from typing import List


def _get_framework_version() -> str:
    """获取框架版本号。"""
    try:
        import spring
        return spring.__version__
    except Exception:
        return 'unknown'


def _cmd_version(args: argparse.Namespace) -> None:
    """显示框架版本信息。"""
    version = _get_framework_version()
    print(f"SpringBootAI v{version}")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Platform: {platform.platform()}")
    print(f"  Installation: {Path(__file__).parent.parent.parent.resolve()}")


def _cmd_info(args: argparse.Namespace) -> None:
    """显示运行环境详细信息。"""
    version = _get_framework_version()
    print("=" * 60)
    print("SpringBootAI 运行环境信息")
    print("=" * 60)
    print(f"框架版本: {version}")
    print(f"Python 版本: {sys.version}")
    print(f"Python 路径: {sys.executable}")
    print(f"操作系统: {platform.platform()}")
    print(f"处理器: {platform.processor() or 'unknown'}")
    print(f"工作目录: {os.getcwd()}")
    print()

    # 已安装的可选依赖
    print("已安装的依赖:")
    optional_deps = [
        ('fastapi', 'Web'),
        ('uvicorn', 'ASGI Server'),
        ('pydantic', 'Validation'),
        ('pymysql', 'MySQL Driver'),
        ('redis', 'Redis'),
        ('pika', 'RabbitMQ'),
        ('kafka', 'Kafka'),
        ('nacos', 'Nacos'),
        ('prometheus_client', 'Prometheus'),
        ('loguru', 'Loguru'),
        ('openpyxl', 'Excel'),
        ('langchain_core', 'LangChain'),
        ('langgraph', 'LangGraph'),
        ('mcp', 'MCP'),
        ('sqlglot', 'SQL Parser'),
    ]
    installed = 0
    for module_name, label in optional_deps:
        try:
            mod = importlib.import_module(module_name)
            ver = getattr(mod, '__version__', 'installed')
            print(f"  [✓] {label}: {module_name} ({ver})")
            installed += 1
        except ImportError:
            pass  # 未安装的不显示
    print(f"共 {installed} 个可选依赖已安装")


def _cmd_list(args: argparse.Namespace) -> None:
    """列出可用模块或注解。"""
    if args.what == 'modules':
        _list_modules()
    elif args.what == 'annotations':
        _list_annotations()


def _list_modules() -> None:
    """列出可用模块。"""
    modules = [
        ('annotations', 'IoC/AOP/Web/Security 注解（90+）'),
        ('context', '应用上下文与 Bean 容器'),
        ('web', 'Web MVC + Actuator + CSRF + HATEOAS'),
        ('orm', 'MyBatis 风格 ORM + 数据库迁移'),
        ('security', 'JWT + OAuth2 + 密码编码'),
        ('messaging', 'RabbitMQ + Kafka 消息队列'),
        ('cloud', '服务发现 + Seata + 网关 + 配置中心 + 事件总线'),
        ('ai', 'Spring AI 风格 ChatClient/Advisor/Tools/RAG'),
        ('langchain', 'LangChain 集成（agents/chains/memory）'),
        ('langgraph', 'LangGraph 状态图编排'),
        ('mcp', 'Model Context Protocol 客户端/服务端'),
        ('batch', 'Spring Batch 批处理框架'),
        ('csv', 'CSV 注解驱动读写'),
        ('excel', 'Excel 注解驱动读写（EasyExcel 风格）'),
        ('i18n', '国际化消息源'),
        ('data', 'Repository 抽象 + Data REST + 分页排序'),
        ('websocket', 'WebSocket 支持'),
        ('devtools', 'DevTools 热重载'),
        ('config', '配置加载与元数据'),
        ('scheduling', '定时任务'),
        ('validation', 'Bean Validation'),
        ('retry', '重试与恢复'),
    ]

    print(f"SpringBootAI 可用模块（{len(modules)} 个）:")
    print("-" * 60)
    for name, desc in modules:
        print(f"  {name:<20} {desc}")


def _list_annotations() -> None:
    """列出可用注解。"""
    try:
        from spring.annotations import __all__ as annotations_all
        print(f"SpringBootAI 可用注解（{len(annotations_all)} 个）:")
        print("-" * 60)
        for ann in sorted(annotations_all):
            print(f"  @{ann}")
    except ImportError:
        print("无法导入注解模块，请确认 spring 包已正确安装")


def _cmd_run(args: argparse.Namespace) -> None:
    """运行应用。

    使用 ``runpy.run_path`` 执行目标脚本，等价于 ``python <app_file>`` 命令。
    采用 Python 标准库方式替代 ``exec(compile(...))``，避免 Bandit B102 安全告警，
    同时保证 ``if __name__ == '__main__':`` 入口块能正确执行。
    """
    app_file = args.app_file
    if not os.path.exists(app_file):
        print(f"错误：应用文件不存在: {app_file}", file=sys.stderr)
        sys.exit(1)

    # 将应用文件所在目录加入 sys.path，确保脚本内的相对导入可用
    app_dir = os.path.dirname(os.path.abspath(app_file))
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)

    # runpy.run_path 以 __main__ 运行目标文件，等价于 `python <app_file>`
    print(f"运行应用: {app_file}")
    runpy.run_path(app_file, run_name='__main__')


def _cmd_docs(args: argparse.Namespace) -> None:
    """生成 API 文档。"""
    try:
        import subprocess
    except ImportError:
        print("subprocess 模块不可用", file=sys.stderr)
        sys.exit(1)

    docs_dir = Path(args.docs_dir or 'docs')
    output_dir = Path(args.output or 'docs/_build')

    if not docs_dir.exists():
        print(f"错误：文档目录不存在: {docs_dir}", file=sys.stderr)
        print("提示：docs/conf.py 是 Sphinx 配置文件，请确认项目结构", file=sys.stderr)
        sys.exit(1)

    print(f"生成 API 文档...")
    print(f"  源目录: {docs_dir}")
    print(f"  输出目录: {output_dir}")

    try:
        result = subprocess.run(
            ['sphinx-build', '-b', 'html', str(docs_dir), str(output_dir)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"文档已生成: {output_dir / 'index.html'}")
        else:
            print(f"Sphinx 构建失败:", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            sys.exit(1)
    except FileNotFoundError:
        print("错误：sphinx-build 命令未找到", file=sys.stderr)
        print("请安装 Sphinx: pip install sphinx", file=sys.stderr)
        sys.exit(1)


def create_parser() -> argparse.ArgumentParser:
    """创建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        prog='springbootai',
        description='SpringBootAI 命令行工具（对齐 Spring Boot CLI）',
    )
    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # version 命令
    subparsers.add_parser('version', help='显示框架版本信息')

    # info 命令
    subparsers.add_parser('info', help='显示运行环境信息')

    # list 命令
    list_parser = subparsers.add_parser('list', help='列出可用模块或注解')
    list_parser.add_argument(
        'what',
        choices=['modules', 'annotations'],
        help='列出内容: modules（模块）或 annotations（注解）',
    )

    # init 命令（复用 scaffold）
    init_parser = subparsers.add_parser('init', help='初始化新项目（类似 Spring Initializr）')
    init_parser.add_argument('project', help='项目名称/目标目录')
    init_parser.add_argument('--package', default=None, help='Python 包名')
    init_parser.add_argument('--modules', default='web', help='启用的模块，逗号分隔')
    init_parser.add_argument('--port', type=int, default=8080, help='服务端口')

    # run 命令
    run_parser = subparsers.add_parser('run', help='运行应用')
    run_parser.add_argument('app_file', help='应用入口文件（如 Application.py）')

    # docs 命令
    docs_parser = subparsers.add_parser('docs', help='生成 API 文档（Sphinx）')
    docs_parser.add_argument('--docs-dir', default='docs', help='Sphinx 配置目录（默认 docs）')
    docs_parser.add_argument('--output', default='docs/_build', help='输出目录')

    return parser


def main(argv: List[str] | None = None) -> None:
    """CLI 主入口（注册为 console_script: springbootai）。

    Args:
        argv: 命令行参数（None 表示使用 sys.argv）
    """
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return

    if args.command == 'version':
        _cmd_version(args)
    elif args.command == 'info':
        _cmd_info(args)
    elif args.command == 'list':
        _cmd_list(args)
    elif args.command == 'init':
        # 复用 scaffold 的 main 函数
        from spring.cli.scaffold import main as scaffold_main
        scaffold_argv = [args.project]
        if args.package:
            scaffold_argv.extend(['--package', args.package])
        if args.modules:
            scaffold_argv.extend(['--modules', args.modules])
        if args.port:
            scaffold_argv.extend(['--port', str(args.port)])
        scaffold_main(scaffold_argv)
    elif args.command == 'run':
        _cmd_run(args)
    elif args.command == 'docs':
        _cmd_docs(args)


if __name__ == '__main__':
    main()
