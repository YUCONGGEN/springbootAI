"""Starter 机制测试。

验证 ``pyproject.toml`` 中 ``[project.optional-dependencies]`` 的组合 Starter 配置：
- 单项 extras（mysql / redis / rabbitmq / kafka）存在且包含关键依赖
- 组合 Starter（web / cloud / all）存在且正确引用其他 extras
"""
import sys
from pathlib import Path

import pytest

# Python 3.11+ 内置 tomllib，低版本回退 tomli
if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

# pyproject.toml 路径（相对当前测试文件定位，便于跨环境运行）
PYPROJECT_FILE = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _load_optional_dependencies():
    """加载 pyproject.toml 中的 [project.optional-dependencies] 段。"""
    with PYPROJECT_FILE.open("rb") as f:
        data = tomllib.load(f)
    return data["project"]["optional-dependencies"]


class TestStarterExtras:
    """Starter 组合测试。"""

    def test_mysql_extra_exists(self):
        """mysql extras 存在。"""
        extras = _load_optional_dependencies()
        assert "mysql" in extras, "缺少 mysql extras"

    def test_redis_extra_exists(self):
        """redis extras 存在。"""
        extras = _load_optional_dependencies()
        assert "redis" in extras, "缺少 redis extras"

    def test_rabbitmq_extra_exists(self):
        """rabbitmq extras 存在。"""
        extras = _load_optional_dependencies()
        assert "rabbitmq" in extras, "缺少 rabbitmq extras"

    def test_kafka_extra_exists(self):
        """kafka extras 存在。"""
        extras = _load_optional_dependencies()
        assert "kafka" in extras, "缺少 kafka extras"

    def test_web_starter_exists(self):
        """web 组合 Starter 存在。"""
        extras = _load_optional_dependencies()
        assert "web" in extras, "缺少 web 组合 Starter"

    def test_cloud_starter_exists(self):
        """cloud 组合 Starter 存在。"""
        extras = _load_optional_dependencies()
        assert "cloud" in extras, "缺少 cloud 组合 Starter"

    def test_all_starter_exists(self):
        """all 组合 Starter 存在。"""
        extras = _load_optional_dependencies()
        assert "all" in extras, "缺少 all 组合 Starter"

    def test_web_starter_contains_fastapi(self):
        """web 组合 Starter 包含 fastapi。"""
        extras = _load_optional_dependencies()
        deps = extras["web"]
        assert any("fastapi" in dep for dep in deps), "web Starter 未包含 fastapi"

    def test_web_starter_contains_uvicorn(self):
        """web 组合 Starter 包含 uvicorn。"""
        extras = _load_optional_dependencies()
        deps = extras["web"]
        assert any("uvicorn" in dep for dep in deps), "web Starter 未包含 uvicorn"

    def test_cloud_starter_references_web(self):
        """cloud 组合 Starter 引用 web。"""
        extras = _load_optional_dependencies()
        deps = extras["cloud"]
        assert any("springbootAI[web]" in dep for dep in deps), (
            "cloud Starter 未引用 web"
        )

    def test_all_starter_references_all(self):
        """all 组合 Starter 引用所有模块。"""
        extras = _load_optional_dependencies()
        deps = extras["all"]
        required_refs = [
            "springbootAI[web]",
            "springbootAI[mysql]",
            "springbootAI[redis]",
            "springbootAI[rabbitmq]",
            "springbootAI[kafka]",
        ]
        for ref in required_refs:
            assert any(ref in dep for dep in deps), f"all Starter 未引用 {ref}"

    def test_kafka_extra_has_kafka_python(self):
        """kafka extras 包含 kafka-python。"""
        extras = _load_optional_dependencies()
        deps = extras["kafka"]
        assert any("kafka-python" in dep for dep in deps), (
            "kafka extras 未包含 kafka-python"
        )

    def test_rabbitmq_extra_has_pika(self):
        """rabbitmq extras 包含 pika。"""
        extras = _load_optional_dependencies()
        deps = extras["rabbitmq"]
        assert any("pika" in dep for dep in deps), "rabbitmq extras 未包含 pika"
