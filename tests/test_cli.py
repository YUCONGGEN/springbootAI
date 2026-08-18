"""Spring CLI 命令行工具测试"""
import os
import subprocess
import sys
from io import StringIO
from unittest.mock import patch

import pytest

from springbootai.cli.main import (
    create_parser,
    main as cli_main,
    _cmd_version,
    _cmd_info,
    _cmd_list,
    _list_modules,
    _list_annotations,
)


class TestParser:
    """参数解析器测试"""

    def test_create_parser(self):
        parser = create_parser()
        assert parser.prog == 'springbootai'

    def test_no_command_prints_help(self):
        """无子命令时打印帮助"""
        with patch('sys.stdout', new=StringIO()) as fake_out:
            cli_main([])
            output = fake_out.getvalue()
            assert 'springbootai' in output
            assert 'usage' in output.lower()


class TestVersionCommand:
    """version 子命令测试"""

    def test_version_prints_info(self):
        with patch('sys.stdout', new=StringIO()) as fake_out:
            cli_main(['version'])
            output = fake_out.getvalue()
            assert 'SpringBootAI' in output
            assert 'Python' in output

    def test_version_contains_framework_version(self):
        import springbootai
        with patch('sys.stdout', new=StringIO()) as fake_out:
            cli_main(['version'])
            output = fake_out.getvalue()
            assert springbootai.__version__ in output


class TestInfoCommand:
    """info 子命令测试"""

    def test_info_prints_environment(self):
        with patch('sys.stdout', new=StringIO()) as fake_out:
            cli_main(['info'])
            output = fake_out.getvalue()
            assert 'Python 版本' in output
            assert '操作系统' in output
            assert '已安装的依赖' in output


class TestListCommand:
    """list 子命令测试"""

    def test_list_modules(self):
        with patch('sys.stdout', new=StringIO()) as fake_out:
            cli_main(['list', 'modules'])
            output = fake_out.getvalue()
            assert '可用模块' in output
            assert 'annotations' in output
            assert 'web' in output
            assert 'orm' in output

    def test_list_annotations(self):
        with patch('sys.stdout', new=StringIO()) as fake_out:
            cli_main(['list', 'annotations'])
            output = fake_out.getvalue()
            assert '可用注解' in output
            assert '@' in output  # 注解以 @ 开头

    def test_list_invalid_what(self):
        """无效的列表类型"""
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(['list', 'invalid'])


class TestInitCommand:
    """init 子命令测试（通过 scaffold 复用）"""

    def test_init_creates_project(self, tmp_path):
        project_dir = tmp_path / "test-project"
        cli_main(['init', str(project_dir), '--modules', 'web', '--port', '9000'])

        assert project_dir.exists()
        assert (project_dir / "Application.py").exists()
        assert (project_dir / "config" / "application.yml").exists()
        assert (project_dir / "requirements.txt").exists()
        assert (project_dir / "README.md").exists()

    def test_init_with_package(self, tmp_path):
        project_dir = tmp_path / "my-app"
        cli_main(['init', str(project_dir), '--package', 'myapp', '--modules', 'web'])

        assert (project_dir / "src" / "myapp").exists()
        assert (project_dir / "src" / "myapp" / "__init__.py").exists()

    def test_init_multiple_modules(self, tmp_path):
        project_dir = tmp_path / "multi-app"
        cli_main(['init', str(project_dir), '--modules', 'web,orm'])

        # orm 模块应创建 models 目录
        pkg = (project_dir / "src" / "multi_app")
        assert (pkg / "models").exists()


class TestRunCommand:
    """run 子命令测试（验证 runpy.run_path 实现）"""

    def test_run_executes_main_block(self, tmp_path, capsys):
        """run 子命令应执行目标脚本的 ``if __name__ == '__main__':`` 块"""
        app_file = tmp_path / "app.py"
        app_file.write_text(
            'print("hello from app")\n'
            'if __name__ == "__main__":\n'
            '    print("main block executed")\n',
            encoding="utf-8",
        )
        cli_main(['run', str(app_file)])
        captured = capsys.readouterr()
        assert "hello from app" in captured.out
        assert "main block executed" in captured.out

    def test_run_missing_file_exits_with_error(self, tmp_path, capsys):
        """run 子命令在文件不存在时应打印错误并以非零状态退出"""
        missing = tmp_path / "nonexistent.py"
        with pytest.raises(SystemExit) as excinfo:
            cli_main(['run', str(missing)])
        assert excinfo.value.code == 1
        assert "不存在" in capsys.readouterr().err

    def test_run_adds_app_dir_to_sys_path(self, tmp_path, capsys):
        """run 子命令应将应用文件所在目录加入 sys.path"""
        app_file = tmp_path / "pathcheck.py"
        app_file.write_text(
            'import sys, os\n'
            'print(os.path.dirname(os.path.abspath(__file__)) in sys.path)\n',
            encoding="utf-8",
        )
        cli_main(['run', str(app_file)])
        assert "True" in capsys.readouterr().out


class TestRunCliIntegration:
    """run_cli 集成测试（验证子命令检测）"""

    def test_run_cli_dispatches_to_subcommand(self):
        """验证 run_cli 能正确分发子命令"""
        from springbootai.main import run_cli

        with patch('sys.argv', ['springbootai', 'version']):
            with patch('sys.stdout', new=StringIO()):
                run_cli()  # 应该不抛异常

    def test_run_cli_traditional_mode(self):
        """验证传统启动模式不会被误判为子命令"""
        from springbootai.main import run_cli

        # 传统模式：springbootai myapp.Application
        # 这个测试只验证参数解析，不实际运行应用
        with patch('sys.argv', ['springbootai', 'myapp.Application', '--port', '8080']):
            with patch('springbootai.main.run') as mock_run:
                with patch('importlib.import_module') as mock_import:
                    mock_import.side_effect = ImportError("test module not found")
                    with pytest.raises(ImportError):
                        run_cli()
