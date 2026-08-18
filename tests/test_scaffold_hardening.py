"""Focused regression tests for the SpringBootAI project scaffold.

These tests intentionally exercise the public CLI surface rather than private
template constants.  A generated project must be usable from a clean,
non-interactive shell and must not overwrite an existing project directory.
"""

from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO, TextIOWrapper
import os
import runpy
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from springbootai.cli.main import create_parser, main as cli_main
from springbootai.cli.scaffold import collect_project_options, create_project, main as scaffold_main


@pytest.fixture(autouse=True)
def _restore_config_loader_and_import_path():
    """Keep generated-project contexts from leaking process-global config."""
    from springbootai.config.config_loader import ConfigLoader, config_loader

    original_state = dict(config_loader.__dict__)
    original_base_path = ConfigLoader._default_base_path
    original_sys_path = list(sys.path)
    try:
        yield
    finally:
        config_loader.__dict__.clear()
        config_loader.__dict__.update(original_state)
        ConfigLoader._default_base_path = original_base_path
        sys.path[:] = original_sys_path


def _create_project(path: Path, **kwargs) -> Path:
    """Create a project without making test output noisy."""
    with redirect_stdout(StringIO()):
        return create_project(str(path), **kwargs)


def test_scaffold_defaults_are_noninteractive(tmp_path):
    """The documented defaults work without prompting for any input."""
    target = tmp_path / "default-app"
    captured = {}

    def fake_create_project(project_path, **kwargs):
        captured["project_path"] = project_path
        captured.update(kwargs)
        return target

    with patch("springbootai.cli.scaffold.create_project", side_effect=fake_create_project):
        with patch("builtins.input", side_effect=AssertionError("scaffold must not prompt")):
            assert scaffold_main([str(target), "--non-interactive"]) == 0

    assert captured == {
        "project_path": str(target),
        "package": None,
        "modules": "web",
        "port": 8000,
    }


def test_interactive_empty_answers_use_documented_defaults(tmp_path):
    """The Chinese wizard's empty answers keep stable, local-only defaults."""
    target = tmp_path / "interactive-app"
    answers = iter([""] * 10)
    with patch("builtins.input", side_effect=lambda _prompt: next(answers)):
        options = collect_project_options(str(target))

    assert options.project_path == str(target)
    assert options.package == "interactive_app"
    assert options.modules == "web"
    assert options.port == 8000
    assert options.database == "none"
    assert options.redis is False
    assert options.ai is False
    assert options.cloud is False
    assert options.docker is True
    assert options.sample_crud is False


def test_unified_init_keeps_scaffold_port_default(tmp_path):
    """``springbootai init`` and the standalone scaffold use port 8000."""
    args = create_parser().parse_args(["init", str(tmp_path / "app")])
    assert args.port == 8000

    target = tmp_path / "unified-app"
    with redirect_stdout(StringIO()):
        cli_main(["init", str(target), "--non-interactive"])
    config = yaml.safe_load((target / "config" / "application.yml").read_text(encoding="utf-8"))
    assert config["server"]["port"] == 8000


def test_unified_init_exposes_interactive_wizard_without_project():
    """The main console command keeps the scaffold's no-argument wizard reachable."""
    with patch("springbootai.cli.scaffold.main", return_value=0) as scaffold:
        assert cli_main(["init"]) == 0
    scaffold.assert_called_once_with(["--port", "8000"])


def test_unified_init_forwards_noninteractive_generation_options(tmp_path):
    """The umbrella CLI must preserve scaffold flags used by CI templates."""
    target = tmp_path / "ci-template"
    with redirect_stdout(StringIO()):
        assert cli_main([
            "init", str(target), "--non-interactive", "--modules", "web,orm",
            "--port", "9130", "--no-docker", "--sample-crud",
        ]) == 0

    config = yaml.safe_load((target / "config" / "application.yml").read_text(encoding="utf-8"))
    assert config["server"]["port"] == 9130
    assert config["database"]["enabled"] is True
    assert config["database"]["driver"] == "sqlite"
    assert not (target / "Dockerfile").exists()
    assert not (target / ".dockerignore").exists()
    assert (target / "src" / "ci_template" / "controllers" / "user_controller.py").exists()


def test_scaffold_generates_complete_layout_and_merged_yaml(tmp_path):
    """All supported modules produce one valid, non-overwriting spring map."""
    target = _create_project(
        tmp_path / "blog-service",
        modules="web,orm,ai,cloud",
        port=9123,
    )

    expected_files = {
        "Application.py",
        "README.md",
        "requirements.txt",
        "config/application.yml",
        "src/blog_service/__init__.py",
        "src/blog_service/controllers/__init__.py",
        "src/blog_service/models/__init__.py",
    }
    actual_files = {str(path.relative_to(target)).replace("\\", "/") for path in target.rglob("*") if path.is_file()}
    assert expected_files <= actual_files

    config = yaml.safe_load((target / "config" / "application.yml").read_text(encoding="utf-8"))
    spring = config["spring"]
    assert config["server"]["port"] == 9123
    assert spring["application"]["name"] == "blog-service"
    assert spring["ai"]["openai"]["api_key"] == "${OPENAI_API_KEY:}"
    assert spring["cloud"]["nacos"]["discovery"]["enabled"] is False
    assert config["database"]["driver"] == "sqlite"
    assert config["redis"]["enabled"] is False
    assert (target / ".dockerignore").read_text(encoding="utf-8").splitlines()[0] == ".git/"
    assert "HEALTHCHECK" in (target / "Dockerfile").read_text(encoding="utf-8")

    requirements = (target / "requirements.txt").read_text(encoding="utf-8")
    assert "PyMySQL==1.2.0" in requirements
    assert "langchain-openai==1.4.2" in requirements
    assert "redis==8.1.0" in requirements


def test_generated_application_without_web_module_is_executable(tmp_path):
    """A non-web scaffold must not import a directory it did not generate."""
    target = _create_project(tmp_path / "worker-app", modules="orm")
    application_file = target / "Application.py"
    source = application_file.read_text(encoding="utf-8")
    compile(source, str(application_file), "exec")
    assert ".controllers import" not in source
    assert 'scan_base_packages=["worker_app"]' in source

    # Execute the generated entrypoint while replacing the long-running web
    # server call.  This still validates imports, decorators, and the main
    # block in a fresh script namespace.
    with patch("springbootai.main.SpringApplication.run", return_value=None) as run:
        runpy.run_path(str(application_file), run_name="__main__")
    run.assert_called_once()


def test_generated_web_application_declares_explicit_scan_package(tmp_path):
    """Hyphenated project names still expose the generated HelloController."""
    target = _create_project(tmp_path / "hello-world", modules="web")
    namespace = runpy.run_path(str(target / "Application.py"), run_name="generated_application")
    app_class = namespace["Application"]
    annotations = getattr(app_class, "__spring_annotations__", [])
    spring_app = next(annotation for annotation in annotations if annotation.__class__.__name__ == "SpringBootApplication")
    assert spring_app.scan_base_packages == ["hello_world"]


def test_default_generated_project_builds_asgi_app_without_external_services(tmp_path):
    """A clean generated project reaches its sample route before running a server."""
    target = _create_project(tmp_path / "startup-smoke")
    workspace = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    for name in list(env):
        if name.startswith(("SPRING_", "APP_", "DB_", "REDIS_", "RABBITMQ_", "NACOS_", "KAFKA_", "AI_", "OPENAI_", "JWT_", "SERVER_")):
            env.pop(name)
    env["PYTHONPATH"] = str(workspace) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    smoke = (
        "import runpy\n"
        "from springbootai.main import create_app\n"
        "namespace = runpy.run_path('Application.py', run_name='generated_application')\n"
        "app = create_app(namespace['Application'])\n"
        "assert '/api/hello' in [getattr(route, 'path', '') for route in app.routes]\n"
        "app.state.spring_application.application_context.destroy()\n"
        "print('generated-startup-ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", smoke],
        cwd=target,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "generated-startup-ok" in result.stdout


def test_generated_web_has_uniform_response_and_business_exception_handler(tmp_path):
    """示例端点应验证统一响应和生成的全局异常处理器都实际生效。"""
    from fastapi.testclient import TestClient
    from springbootai.main import create_app

    target = _create_project(tmp_path / "response-smoke")
    namespace = runpy.run_path(str(target / "Application.py"), run_name="generated_response_app")
    app = create_app(namespace["Application"])
    try:
        client = TestClient(app)
        ok = client.get("/api/hello")
        assert ok.status_code == 200
        assert ok.json()["code"] == 200
        assert ok.json()["data"]["message"].startswith("Hello from")

        business_error = client.get("/api/demo-error")
        assert business_error.status_code == 422
        assert business_error.json() == {
            "code": 422,
            "message": "这是一个示例业务错误",
            "data": None,
        }
    finally:
        app.state.spring_application.application_context.destroy()


def test_nonempty_directory_is_rejected_without_overwrite(tmp_path):
    """Refusing a non-empty target leaves the user's files untouched."""
    target = tmp_path / "existing"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("do not overwrite", encoding="utf-8")

    stderr = StringIO()
    with redirect_stderr(stderr):
        result = scaffold_main([str(target)])

    assert result == 1
    assert sentinel.read_text(encoding="utf-8") == "do not overwrite"
    assert not (target / "Application.py").exists()
    assert "not empty" in stderr.getvalue()


def test_unified_init_propagates_nonempty_directory_failure(tmp_path):
    """The console entrypoint must expose scaffold refusal as exit code 1."""
    target = tmp_path / "existing-unified"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")

    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        assert cli_main(["init", str(target)]) == 1


def test_success_output_does_not_crash_on_ascii_console(tmp_path):
    """Legacy Windows streams must not turn a successful generation into an error."""
    target = tmp_path / "ascii-console"
    raw = BytesIO()
    stream = TextIOWrapper(raw, encoding="ascii")
    try:
        with redirect_stdout(stream):
            result = scaffold_main([str(target)])
        stream.flush()
        assert result == 0
        assert target.joinpath("Application.py").exists()
        assert b"Application.py" in raw.getvalue()
    finally:
        stream.close()


@pytest.mark.parametrize("port", [0, 65536, -1])
def test_invalid_port_is_rejected_before_writing(tmp_path, port):
    target = tmp_path / f"invalid-{port}"
    with pytest.raises(ValueError, match="1-65535"):
        create_project(str(target), port=port)
    assert not target.exists()
