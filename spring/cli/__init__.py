"""SpringBootAI 命令行工具包。

提供两个模块：
- :mod:`spring.cli.scaffold`：项目脚手架（类似 Spring Initializr）
- :mod:`spring.cli.main`：统一 CLI 入口（类似 Spring Boot CLI），支持 version/info/list/init/run/docs 子命令

CLI 命令入口：
- ``springbootai``：主命令（传统启动模式 + 子命令模式自动切换）
- ``springbootai-init``：脚手架快捷命令
"""
from spring.cli.scaffold import main as scaffold_main

try:
    from spring.cli.main import main as cli_main, create_parser
except Exception:
    cli_main = None  # type: ignore
    create_parser = None  # type: ignore

__all__ = ['scaffold_main', 'cli_main', 'create_parser']
