"""配置元数据文件完整性测试。

测试 ``springbootai/config/spring-configuration-metadata.json`` 的结构与内容：
- 文件存在性与 JSON 合法性
- version / metadata / properties 顶层字段
- 每个 property 必备 name / description 字段
- 关键配置项（server.port、springbootai.application.name、springbootai.security.jwt.secret-key 等）存在
- name 唯一性、type 字段合法性、defaultValue 覆盖度
"""
import json
from pathlib import Path

import pytest

# 元数据文件路径（相对当前测试文件定位，便于跨环境运行）
METADATA_FILE = (
    Path(__file__).resolve().parent.parent
    / "spring" / "config" / "spring-configuration-metadata.json"
)

# 有效的 Java 类型前缀白名单（对齐 Spring Boot configuration-metadata 约定）
VALID_JAVA_TYPE_PREFIXES = (
    "java.lang.",
    "java.util.",
)

# 关键配置项（必须存在）
KNOWN_CONFIG_KEYS = [
    "server.port",
    "springbootai.application.name",
    "springbootai.security.jwt.secret-key",
]


def _load_metadata():
    """加载元数据 JSON，供多个测试复用。"""
    with METADATA_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


class TestMetadataFile:
    """元数据文件测试。"""

    def test_file_exists(self):
        """元数据文件存在。"""
        assert METADATA_FILE.exists(), f"元数据文件不存在: {METADATA_FILE}"
        assert METADATA_FILE.is_file(), f"路径不是文件: {METADATA_FILE}"

    def test_file_valid_json(self):
        """文件内容是合法 JSON。"""
        data = _load_metadata()
        assert isinstance(data, dict), "元数据根节点应为 JSON 对象"

    def test_has_version(self):
        """包含 version 字段。"""
        data = _load_metadata()
        assert "version" in data, "缺少 version 字段"
        assert isinstance(data["version"], int), "version 应为整数"

    def test_has_metadata(self):
        """包含 metadata 字段。"""
        data = _load_metadata()
        assert "metadata" in data, "缺少 metadata 字段"
        assert isinstance(data["metadata"], dict), "metadata 应为 JSON 对象"

    def test_has_properties(self):
        """包含 properties 数组。"""
        data = _load_metadata()
        assert "properties" in data, "缺少 properties 字段"
        assert isinstance(data["properties"], list), "properties 应为数组"
        assert len(data["properties"]) > 0, "properties 数组不应为空"

    def test_properties_have_required_fields(self):
        """每个 property 都有 name 和 description 字段。"""
        data = _load_metadata()
        for prop in data["properties"]:
            assert "name" in prop, f"property 缺少 name 字段: {prop}"
            assert "description" in prop, f"property 缺少 description 字段: {prop}"
            assert prop["name"], f"property name 不能为空: {prop}"
            assert prop["description"], f"property description 不能为空: {prop}"

    def test_known_config_keys_present(self):
        """关键配置项存在。"""
        data = _load_metadata()
        names = {prop["name"] for prop in data["properties"]}
        for key in KNOWN_CONFIG_KEYS:
            assert key in names, f"缺少关键配置项: {key}"

    def test_no_duplicate_names(self):
        """没有重复的 name。"""
        data = _load_metadata()
        names = [prop["name"] for prop in data["properties"]]
        duplicates = {name for name in names if names.count(name) > 1}
        assert not duplicates, f"存在重复的 property name: {duplicates}"

    def test_types_are_valid(self):
        """type 字段是有效的 Java 类型。"""
        data = _load_metadata()
        for prop in data["properties"]:
            if "type" not in prop:
                continue
            type_value = prop["type"]
            assert isinstance(type_value, str), f"type 应为字符串: {prop}"
            assert type_value.startswith(VALID_JAVA_TYPE_PREFIXES), (
                f"type 不是有效的 Java 类型: {type_value}"
            )

    def test_default_values_present(self):
        """存在带 defaultValue 的 property。"""
        data = _load_metadata()
        with_default = [
            prop for prop in data["properties"] if "defaultValue" in prop
        ]
        assert len(with_default) > 0, "没有任何 property 提供 defaultValue"
