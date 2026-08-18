"""Spring Cloud Config 配置中心客户端测试"""
import os
import tempfile
from pathlib import Path

import pytest
import yaml

from springbootai.cloud.config_center import (
    ConfigCenterClient,
    ConfigCenterError,
    config_client,
    init_config_center,
)


@pytest.fixture(autouse=True)
def reset_singleton():
    """每个测试前重置单例状态"""
    config_client._configured = False
    config_client._cached_config = {}
    config_client._cached_hash = ''
    config_client._refresh_callbacks = []
    config_client._change_listeners = []
    yield
    config_client._configured = False
    config_client._cached_config = {}
    config_client._cached_hash = ''
    config_client._refresh_callbacks = []
    config_client._change_listeners = []


class TestConfigCenterConfigure:
    """配置初始化测试"""

    def test_configure_disabled(self):
        """未启用配置中心时configure不生效"""
        config_client.configure({'spring': {'cloud': {'config': {'enabled': False}}}})
        assert config_client.configured is False

    def test_configure_enabled_http(self):
        """HTTP后端配置"""
        config_client.configure({
            'spring': {
                'application': {'name': 'myapp'},
                'profiles': {'active': 'dev'},
                'cloud': {'config': {
                    'enabled': True,
                    'uri': 'http://config:8888',
                    'label': 'main',
                }},
            }
        })
        assert config_client.configured is True
        assert config_client._backend == 'http'
        assert config_client._uri == 'http://config:8888'
        assert config_client._name == 'myapp'
        assert config_client._profile == 'dev'
        assert config_client._label == 'main'

    def test_configure_file_backend(self):
        """本地文件后端配置"""
        config_client.configure({
            'spring': {
                'cloud': {'config': {
                    'enabled': True,
                    'backend': 'file',
                    'file': {'path': './config-repo'},
                }},
            }
        })
        assert config_client._backend == 'file'
        assert config_client._file_path == './config-repo'

    def test_configure_retry_settings(self):
        """重试参数解析"""
        config_client.configure({
            'spring': {'cloud': {'config': {
                'enabled': True,
                'retry': {'max-attempts': 10, 'initial-interval': 500, 'multiplier': 2.0},
                'timeout': 3000,
            }}}
        })
        assert config_client._retry_max == 10
        assert config_client._retry_initial == 500
        assert config_client._retry_multiplier == 2.0
        assert config_client._timeout == 3000


class TestConfigCenterFileBackend:
    """本地文件后端测试"""

    def test_fetch_from_file(self, tmp_path):
        """从本地文件拉取配置"""
        # 创建配置文件
        config_file = tmp_path / "myapp-dev.yml"
        config_file.write_text(yaml.dump({
            'app': {'name': 'test-app', 'version': '1.0'},
            'db': {'url': 'sqlite:///test.db'},
        }), encoding='utf-8')

        config_client.configure({
            'spring': {'cloud': {'config': {
                'enabled': True,
                'backend': 'file',
                'file': {'path': str(tmp_path)},
                'name': 'myapp',
                'profile': 'dev',
            }}}
        })
        result = config_client.fetch()
        assert result.get('app.name') == 'test-app'
        assert result.get('app.version') == '1.0'
        assert result.get('db.url') == 'sqlite:///test.db'

    def test_fetch_from_file_fallback_to_application_yml(self, tmp_path):
        """回退到application.yml"""
        config_file = tmp_path / "application.yml"
        config_file.write_text(yaml.dump({'server': {'port': 9000}}), encoding='utf-8')

        config_client.configure({
            'spring': {'cloud': {'config': {
                'enabled': True,
                'backend': 'file',
                'file': {'path': str(tmp_path)},
                'name': 'nonexistent',
                'profile': 'prod',
            }}}
        })
        result = config_client.fetch()
        assert result.get('server.port') == 9000

    def test_fetch_from_file_not_found(self, tmp_path):
        """配置目录不存在文件时返回空"""
        config_client.configure({
            'spring': {'cloud': {'config': {
                'enabled': True,
                'backend': 'file',
                'file': {'path': str(tmp_path)},
                'name': 'nonexistent',
                'profile': 'none',
            }}}
        })
        result = config_client.fetch()
        assert result == {}


class TestConfigCenterRefresh:
    """配置刷新测试"""

    def test_refresh_detects_changes(self, tmp_path):
        """刷新检测配置变更"""
        config_file = tmp_path / "myapp-dev.yml"
        config_file.write_text(yaml.dump({'app.value': 'old'}), encoding='utf-8')

        config_client.configure({
            'spring': {'cloud': {'config': {
                'enabled': True,
                'backend': 'file',
                'file': {'path': str(tmp_path)},
                'name': 'myapp',
                'profile': 'dev',
            }}}
        })
        # 首次拉取
        config_client.fetch()
        config_client._cached_config = config_client.fetch()
        import hashlib, json
        config_client._cached_hash = hashlib.sha256(
            json.dumps(config_client._cached_config, sort_keys=True, default=str).encode()
        ).hexdigest()

        # 修改配置文件
        config_file.write_text(yaml.dump({'app.value': 'new'}), encoding='utf-8')

        # 刷新
        changes = config_client.refresh()
        assert 'app.value' in changes
        assert changes['app.value'] == 'new'

    def test_refresh_no_changes(self, tmp_path):
        """配置未变化时不触发刷新"""
        config_file = tmp_path / "myapp-dev.yml"
        config_file.write_text(yaml.dump({'app.value': 'stable'}), encoding='utf-8')

        config_client.configure({
            'spring': {'cloud': {'config': {
                'enabled': True,
                'backend': 'file',
                'file': {'path': str(tmp_path)},
                'name': 'myapp',
                'profile': 'dev',
            }}}
        })
        # 首次拉取并缓存
        config_client._cached_config = config_client.fetch()
        import hashlib, json
        config_client._cached_hash = hashlib.sha256(
            json.dumps(config_client._cached_config, sort_keys=True, default=str).encode()
        ).hexdigest()

        # 再次刷新（文件未变）
        changes = config_client.refresh()
        assert changes == {}

    def test_refresh_callback_invoked(self, tmp_path):
        """刷新回调被调用"""
        config_file = tmp_path / "myapp-dev.yml"
        config_file.write_text(yaml.dump({'app.value': 'old'}), encoding='utf-8')

        config_client.configure({
            'spring': {'cloud': {'config': {
                'enabled': True,
                'backend': 'file',
                'file': {'path': str(tmp_path)},
                'name': 'myapp',
                'profile': 'dev',
            }}}
        })
        config_client._cached_config = config_client.fetch()
        import hashlib, json
        config_client._cached_hash = hashlib.sha256(
            json.dumps(config_client._cached_config, sort_keys=True, default=str).encode()
        ).hexdigest()

        callback_called = []
        config_client.register_refresh_callback(lambda: callback_called.append(True))

        config_file.write_text(yaml.dump({'app.value': 'new'}), encoding='utf-8')
        config_client.refresh()
        assert len(callback_called) == 1

    def test_change_listener_invoked(self, tmp_path):
        """配置变更监听器被调用"""
        config_file = tmp_path / "myapp-dev.yml"
        config_file.write_text(yaml.dump({'app.value': 'old'}), encoding='utf-8')

        config_client.configure({
            'spring': {'cloud': {'config': {
                'enabled': True,
                'backend': 'file',
                'file': {'path': str(tmp_path)},
                'name': 'myapp',
                'profile': 'dev',
            }}}
        })
        config_client._cached_config = config_client.fetch()
        import hashlib, json
        config_client._cached_hash = hashlib.sha256(
            json.dumps(config_client._cached_config, sort_keys=True, default=str).encode()
        ).hexdigest()

        listener_called = []
        config_client.register_change_listener(
            lambda old, new: listener_called.append((old, new))
        )

        config_file.write_text(yaml.dump({'app.value': 'new'}), encoding='utf-8')
        config_client.refresh()
        assert len(listener_called) == 1
        old, new = listener_called[0]
        assert old.get('app.value') == 'old'
        assert new.get('app.value') == 'new'


class TestInitConfigCenter:
    """init_config_center 函数测试"""

    def test_init_disabled(self):
        """未启用时不初始化"""
        init_config_center({'spring': {'cloud': {'config': {'enabled': False}}}})
        assert config_client.configured is False

    def test_init_enabled_file_backend(self, tmp_path):
        """启用文件后端时初始化"""
        config_file = tmp_path / "myapp-dev.yml"
        config_file.write_text(yaml.dump({'app.name': 'test'}), encoding='utf-8')

        init_config_center({
            'spring': {
                'application': {'name': 'myapp'},
                'profiles': {'active': 'dev'},
                'cloud': {'config': {
                    'enabled': True,
                    'backend': 'file',
                    'file': {'path': str(tmp_path)},
                }},
            }
        })
        assert config_client.configured is True


class TestFlatten:
    """_flatten 方法测试"""

    def test_flatten_nested_dict(self):
        data = {'a': {'b': {'c': 1}}, 'd': 2}
        result = ConfigCenterClient._flatten(data)
        assert result == {'a.b.c': 1, 'd': 2}

    def test_flatten_empty(self):
        result = ConfigCenterClient._flatten({})
        assert result == {}
