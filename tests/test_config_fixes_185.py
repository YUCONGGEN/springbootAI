"""v1.8.5 配置读取细节修复的回归测试。

覆盖：
- Bug 1: DatabaseManager.configure() 单例配置生效
- Bug 2: profile 特定配置文件 application-{profile}.yml 加载与深度合并
- Bug 3: 嵌套占位符 ${A:${B:default}} 解析
- Bug 4: database.enabled 默认值 True
- 风险5: 环境变量命名兼容（占位符风格 + 显式覆盖风格）
- 风险6: 统一布尔转换（true/1/yes/on）
- 风险7: config_loader.get() 松散绑定
- 风险8: CLI 参数覆盖
- 风险9: discovery / rabbitmq 的 configure() 方法
- 风险10: redis.timeout 配置生效
"""
import os
import sys

import pytest


# ==================== Bug 1: DatabaseManager.configure() ====================

class TestDatabaseManagerConfigure:
    """验证 DatabaseManager 单例配置能通过 configure() 生效。"""

    def setup_method(self):
        # 重置单例，确保每个测试独立
        from springbootai.orm.database import DatabaseManager
        DatabaseManager._instance = None

    def test_configure_updates_db_url(self):
        from springbootai.orm.database import DatabaseManager
        mgr = DatabaseManager(db_url="sqlite:///./initial.db", echo=False)
        assert mgr.db_url == "sqlite:///./initial.db"
        # 单例守卫：再次 __init__ 不会更新
        DatabaseManager(db_url="sqlite:///./changed.db", echo=True)
        assert mgr.db_url == "sqlite:///./initial.db"
        # configure() 能更新
        mgr.configure(db_url="sqlite:///./configured.db", echo=True)
        assert mgr.db_url == "sqlite:///./configured.db"
        assert mgr.echo is True

    def test_configure_resets_engine(self):
        from springbootai.orm.database import DatabaseManager
        mgr = DatabaseManager()
        # 模拟已建立连接
        mgr._engine = object()
        mgr._session_factory = object()
        mgr._scoped_session = object()
        mgr.configure(db_url="sqlite:///./new.db")
        assert mgr._engine is None
        assert mgr._session_factory is None
        assert mgr._scoped_session is None

    def test_configure_partial_update_keeps_others(self):
        from springbootai.orm.database import DatabaseManager
        mgr = DatabaseManager(db_url="sqlite:///./keep.db", echo=False)
        # 只更新 echo，db_url 保留
        mgr.configure(echo=True)
        assert mgr.db_url == "sqlite:///./keep.db"
        assert mgr.echo is True

    def test_init_database_uses_configure(self):
        """init_database 应通过 configure 生效，而非被 _initialized 守卫忽略。"""
        from springbootai.orm.database import DatabaseManager, init_database
        DatabaseManager._instance = None
        # 先创建默认单例
        DatabaseManager()
        # init_database 用新配置初始化（不实际连接，用 sqlite 内存库）
        init_database({
            'url': 'sqlite:///:memory:',
            'echo': False,
        })
        from springbootai.orm.database import db_manager
        assert db_manager.db_url == 'sqlite:///:memory:'


# ==================== Bug 2: profile 配置文件加载 ====================

class TestProfileConfig:
    """验证 application-{profile}.yml 加载与深度合并。"""

    def test_profile_overrides_main(self, tmp_path):
        from springbootai.config.config_loader import ConfigLoader
        main_yml = tmp_path / "application.yml"
        main_yml.write_text("server:\n  port: 8080\nlogging:\n  level: INFO\n", encoding="utf-8")
        profile_yml = tmp_path / "application-prod.yml"
        profile_yml.write_text("server:\n  port: 9000\n", encoding="utf-8")
        loader = ConfigLoader(config_path=str(main_yml))
        # profile 未激活，主配置生效
        assert loader.get('server.port') == 8080

    def test_profile_active_overrides(self, tmp_path, monkeypatch):
        from springbootai.config.config_loader import ConfigLoader
        main_yml = tmp_path / "application.yml"
        main_yml.write_text(
            "spring:\n  profiles:\n    active: staging\nserver:\n  port: 8080\n",
            encoding="utf-8")
        profile_yml = tmp_path / "application-staging.yml"
        profile_yml.write_text("server:\n  port: 9000\n", encoding="utf-8")
        loader = ConfigLoader(config_path=str(main_yml))
        assert loader.get('server.port') == 9000

    def test_profile_deep_merge_keeps_unrelated_keys(self, tmp_path, monkeypatch):
        from springbootai.config.config_loader import ConfigLoader
        main_yml = tmp_path / "application.yml"
        main_yml.write_text(
            "spring:\n  profiles:\n    active: dev\n"
            "server:\n  port: 8080\n  host: 0.0.0.0\n"
            "logging:\n  level: INFO\n",
            encoding="utf-8")
        profile_yml = tmp_path / "application-dev.yml"
        # 只覆盖 port，host 和 logging.level 应保留
        profile_yml.write_text("server:\n  port: 9000\n", encoding="utf-8")
        loader = ConfigLoader(config_path=str(main_yml))
        assert loader.get('server.port') == 9000
        assert loader.get('server.host') == '0.0.0.0'
        assert loader.get('logging.level') == 'INFO'

    def test_profile_via_env_var(self, tmp_path, monkeypatch):
        from springbootai.config.config_loader import ConfigLoader
        main_yml = tmp_path / "application.yml"
        main_yml.write_text("server:\n  port: 8080\n", encoding="utf-8")
        profile_yml = tmp_path / "application-staging.yml"
        profile_yml.write_text("server:\n  port: 7000\n", encoding="utf-8")
        monkeypatch.setenv('SPRING_PROFILES_ACTIVE', 'staging')
        loader = ConfigLoader(config_path=str(main_yml))
        assert loader.get('server.port') == 7000

    def test_deep_merge_utility(self):
        from springbootai.config.config_loader import ConfigLoader
        base = {'a': 1, 'b': {'x': 1, 'y': 2}, 'c': 3}
        override = {'b': {'y': 20, 'z': 30}, 'd': 4}
        result = ConfigLoader._deep_merge(base, override)
        assert result == {'a': 1, 'b': {'x': 1, 'y': 20, 'z': 30}, 'c': 3, 'd': 4}
        # 入参不被修改
        assert base['b'] == {'x': 1, 'y': 2}


# ==================== Malformed sections ====================

class TestMalformedConfigSections:
    """Malformed optional sections should degrade to defaults, not crash startup."""

    def test_non_mapping_sections_are_normalized(self, tmp_path):
        from springbootai.config.config_loader import ConfigLoader

        config_file = tmp_path / "application.yml"
        config_file.write_text(
            "spring:\n  profiles:\n    active: null\n"
            "server: []\nredis: null\njwt: bad\n",
            encoding="utf-8",
        )

        loader = ConfigLoader(config_path=str(config_file))

        assert loader.get("server.port") == 8080
        assert loader.get("redis.enabled") is False
        assert loader.get_active_profile() == "default"

    def test_missing_jwt_secret_stays_empty_for_runtime_random_key(self, tmp_path, monkeypatch):
        """ConfigLoader must not revive the removed hard-coded JWT secret."""
        from springbootai.config.config_loader import ConfigLoader

        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("SPRING_PROFILES_ACTIVE", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        config_file = tmp_path / "application.yml"
        config_file.write_text("jwt:\n  algorithm: HS256\n", encoding="utf-8")

        loader = ConfigLoader(config_path=str(config_file))

        assert loader.get("jwt.secret_key") == ""

    def test_project_dotenv_resolves_placeholders_without_overriding_process_env(self, tmp_path, monkeypatch):
        """The documented project-root .env is loaded before YAML binding."""
        from springbootai.config.config_loader import ConfigLoader

        monkeypatch.delenv("SPRING_PROFILES_ACTIVE", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "application.yml"
        config_file.write_text("server:\n  port: ${SERVER_PORT:8000}\n", encoding="utf-8")
        (tmp_path / ".env").write_text("SERVER_PORT=9234\n", encoding="utf-8")

        previous = os.environ.get("SERVER_PORT")
        try:
            os.environ.pop("SERVER_PORT", None)
            assert ConfigLoader(config_path=str(config_file)).get("server.port") == 9234

            os.environ["SERVER_PORT"] = "9345"
            assert ConfigLoader(config_path=str(config_file)).get("server.port") == 9345
        finally:
            if previous is None:
                os.environ.pop("SERVER_PORT", None)
            else:
                os.environ["SERVER_PORT"] = previous

    def test_malformed_ai_provider_reports_missing_key(self, tmp_path, monkeypatch):
        from springbootai.config.config_loader import ConfigLoader, ConfigurationError

        monkeypatch.setenv("SPRING_PROFILES_ACTIVE", "prod")
        monkeypatch.setenv("JWT_SECRET_KEY", "x" * 40)
        config_file = tmp_path / "application.yml"
        config_file.write_text(
            "spring:\n  ai:\n    default-provider: openai\n    openai: [invalid]\n",
            encoding="utf-8",
        )

        with pytest.raises(ConfigurationError, match="api-key"):
            ConfigLoader(config_path=str(config_file))

    def test_malformed_scalar_values_use_safe_defaults(self, tmp_path, monkeypatch):
        from springbootai.config.config_loader import ConfigLoader

        for name in (
            "SERVER_PORT", "REDIS_PORT", "REDIS_DB", "DB_PORT",
            "RABBITMQ_PORT", "PROMETHEUS_PORT", "LOG_LEVEL", "LOG_DIR",
        ):
            monkeypatch.delenv(name, raising=False)

        config_file = tmp_path / "application.yml"
        config_file.write_text(
            "server:\n  port: invalid\n  host: []\n"
            "redis:\n  port: []\n  db: bad\n"
            "database:\n  port: null\n"
            "rabbitmq:\n  port: bad\n"
            "prometheus:\n  port: []\n"
            "logging:\n  level: []\n  log_dir: []\n",
            encoding="utf-8",
        )

        loader = ConfigLoader(config_path=str(config_file))

        assert loader.get("server.port") == 8080
        assert loader.get("server.host") == "0.0.0.0"
        assert loader.get("redis.port") == 6379
        assert loader.get("redis.db") == 0
        assert loader.get("database.port") == 3306
        assert loader.get("rabbitmq.port") == 5672
        assert loader.get("prometheus.port") == 8000
        assert loader.get("logging.level") == "INFO"
        assert loader.get("logging.log_dir") is None

    @pytest.mark.parametrize(
        ("configured_value", "expected"),
        [("false", False), ("0", False), ("true", True), ("yes", True)],
    )
    def test_quoted_fail_fast_uses_boolean_parsing(
        self, tmp_path, monkeypatch, configured_value, expected
    ):
        """Quoted YAML booleans must match STARTUP_FAIL_FAST semantics."""
        from springbootai.config.config_loader import ConfigLoader

        monkeypatch.delenv("STARTUP_FAIL_FAST", raising=False)
        config_file = tmp_path / "application.yml"
        config_file.write_text(
            f'startup:\n  fail_fast: "{configured_value}"\n',
            encoding="utf-8",
        )

        loader = ConfigLoader(config_path=str(config_file))

        assert loader.get("startup.fail_fast") is expected


# ==================== Bug 3: 嵌套占位符 ====================

class TestNestedPlaceholder:
    """验证嵌套占位符 ${A:${B:default}} 解析。"""

    def test_nested_both_unset_uses_inner_default(self, monkeypatch):
        from springbootai.config.config_loader import ConfigLoader
        loader = ConfigLoader.__new__(ConfigLoader)
        loader._config = {}
        monkeypatch.delenv('A', raising=False)
        monkeypatch.delenv('B', raising=False)
        assert loader._resolve_env_var('${A:${B:default}}') == 'default'

    def test_nested_inner_set_outer_unset(self, monkeypatch):
        from springbootai.config.config_loader import ConfigLoader
        loader = ConfigLoader.__new__(ConfigLoader)
        loader._config = {}
        monkeypatch.setenv('B', 'envB')
        monkeypatch.delenv('A', raising=False)
        assert loader._resolve_env_var('${A:${B:default}}') == 'envB'

    def test_nested_outer_set(self, monkeypatch):
        from springbootai.config.config_loader import ConfigLoader
        loader = ConfigLoader.__new__(ConfigLoader)
        loader._config = {}
        monkeypatch.setenv('A', 'envA')
        monkeypatch.delenv('B', raising=False)
        assert loader._resolve_env_var('${A:${B:default}}') == 'envA'

    def test_nested_type_inference(self, monkeypatch):
        from springbootai.config.config_loader import ConfigLoader
        loader = ConfigLoader.__new__(ConfigLoader)
        loader._config = {}
        monkeypatch.setenv('PORT', '9000')
        monkeypatch.delenv('DEFAULT_PORT', raising=False)
        # 嵌套占位符整体解析后做类型推断
        result = loader._resolve_env_var('${SERVER_PORT:${DEFAULT_PORT:8080}}')
        assert result == 8080  # int 类型推断

    def test_simple_placeholder_still_works(self, monkeypatch):
        from springbootai.config.config_loader import ConfigLoader
        loader = ConfigLoader.__new__(ConfigLoader)
        loader._config = {}
        monkeypatch.delenv('LOG_DIR', raising=False)
        assert loader._resolve_env_var('${LOG_DIR:logs}') == 'logs'

    def test_is_single_placeholder_balanced(self):
        from springbootai.config.config_loader import ConfigLoader
        assert ConfigLoader._is_single_placeholder('${LOG_DIR:logs}') is True
        assert ConfigLoader._is_single_placeholder('${A:${B:default}}') is True
        assert ConfigLoader._is_single_placeholder('prefix-${A}') is False
        assert ConfigLoader._is_single_placeholder('${A}-${B}') is False
        assert ConfigLoader._is_single_placeholder('plain') is False


# ==================== Bug 4: database.enabled 默认值 ====================

class TestDatabaseEnabledDefault:
    """验证 database.enabled 默认 True（对齐 application.yml 占位符）。"""

    def test_database_enabled_default_true_when_missing(self, tmp_path, monkeypatch):
        from springbootai.config.config_loader import ConfigLoader
        # 精简配置，缺失 database 段
        main_yml = tmp_path / "application.yml"
        main_yml.write_text("server:\n  port: 8080\n", encoding="utf-8")
        monkeypatch.delenv('DB_ENABLED', raising=False)
        monkeypatch.delenv('SPRING_PROFILES_ACTIVE', raising=False)
        loader = ConfigLoader(config_path=str(main_yml))
        assert loader.get('database.enabled') is True


# ==================== 风险5: 环境变量命名兼容 ====================

class TestEnvVarNamingCompat:
    """验证占位符风格与显式覆盖风格环境变量都能生效。"""

    def test_discovery_server_addr_placeholder_style(self, tmp_path, monkeypatch):
        from springbootai.config.config_loader import ConfigLoader
        main_yml = tmp_path / "application.yml"
        main_yml.write_text("discovery:\n  enabled: true\n", encoding="utf-8")
        monkeypatch.setenv('NACOS_SERVER', 'nacos:8848')
        monkeypatch.delenv('DISCOVERY_SERVER_ADDR', raising=False)
        loader = ConfigLoader(config_path=str(main_yml))
        assert loader.get('discovery.server_addr') == 'nacos:8848'

    def test_discovery_server_addr_explicit_style(self, tmp_path, monkeypatch):
        from springbootai.config.config_loader import ConfigLoader
        main_yml = tmp_path / "application.yml"
        main_yml.write_text("discovery:\n  enabled: true\n", encoding="utf-8")
        monkeypatch.delenv('NACOS_SERVER', raising=False)
        monkeypatch.setenv('DISCOVERY_SERVER_ADDR', 'explicit:8848')
        loader = ConfigLoader(config_path=str(main_yml))
        assert loader.get('discovery.server_addr') == 'explicit:8848'

    def test_seata_app_id_both_styles(self, tmp_path, monkeypatch):
        from springbootai.config.config_loader import ConfigLoader
        main_yml = tmp_path / "application.yml"
        main_yml.write_text("seata:\n  enabled: false\n", encoding="utf-8")
        # 占位符风格优先（_get_env_any 按顺序检查）
        monkeypatch.setenv('SEATA_APP_ID', 'short-id')
        monkeypatch.setenv('SEATA_APPLICATION_ID', 'long-id')
        loader = ConfigLoader(config_path=str(main_yml))
        assert loader.get('seata.application_id') == 'short-id'

    def test_rabbitmq_vhost_placeholder_style(self, tmp_path, monkeypatch):
        from springbootai.config.config_loader import ConfigLoader
        main_yml = tmp_path / "application.yml"
        main_yml.write_text("rabbitmq:\n  enabled: false\n", encoding="utf-8")
        monkeypatch.setenv('RABBITMQ_VHOST', '/dev')
        monkeypatch.delenv('RABBITMQ_VIRTUAL_HOST', raising=False)
        loader = ConfigLoader(config_path=str(main_yml))
        assert loader.get('rabbitmq.virtual_host') == '/dev'


# ==================== 风险6: 统一布尔转换 ====================

class TestUnifiedBoolConversion:
    """验证 _to_bool 接受 true/1/yes/on。"""

    @pytest.mark.parametrize('value,expected', [
        ('true', True), ('True', True), ('TRUE', True),
        ('1', True), ('yes', True), ('on', True),
        ('false', False), ('0', False), ('no', False), ('off', False),
        ('', False), ('anything', False),
        (True, True), (False, False),
        (None, False),
    ])
    def test_to_bool_values(self, value, expected):
        from springbootai.config.config_loader import _to_bool
        assert _to_bool(value) is expected

    def test_to_bool_default_for_none(self):
        from springbootai.config.config_loader import _to_bool
        assert _to_bool(None, default=True) is True

    def test_redis_enabled_with_1(self, tmp_path, monkeypatch):
        """REDIS_ENABLED=1 应启用 Redis（之前 .lower()=='true' 会判为 False）。"""
        from springbootai.config.config_loader import ConfigLoader
        main_yml = tmp_path / "application.yml"
        main_yml.write_text("redis:\n  host: localhost\n", encoding="utf-8")
        monkeypatch.setenv('REDIS_ENABLED', '1')
        loader = ConfigLoader(config_path=str(main_yml))
        assert loader.get('redis.enabled') is True


# ==================== 风险7: get() 松散绑定 ====================

class TestGetLooseBinding:
    """验证 get() 支持 kebab/snake/大小写不敏感。"""

    def test_get_kebab_matches_snake(self, tmp_path, monkeypatch):
        from springbootai.config.config_loader import ConfigLoader
        main_yml = tmp_path / "application.yml"
        main_yml.write_text("logging:\n  log_dir: ./mylogs\n", encoding="utf-8")
        monkeypatch.delenv('SPRING_PROFILES_ACTIVE', raising=False)
        loader = ConfigLoader(config_path=str(main_yml))
        # snake_case 精确匹配
        assert loader.get('logging.log_dir') == './mylogs'
        # kebab-case 松散匹配
        assert loader.get('logging.log-dir') == './mylogs'
        # 大写松散匹配
        assert loader.get('logging.LOG_DIR') == './mylogs'

    def test_get_case_insensitive_section(self, tmp_path, monkeypatch):
        """用不被 _override_with_env 触碰的自定义段验证大小写不敏感。"""
        from springbootai.config.config_loader import ConfigLoader
        main_yml = tmp_path / "application.yml"
        main_yml.write_text("App:\n  Name: my-service\n  Version: 1.0\n", encoding="utf-8")
        monkeypatch.delenv('SPRING_PROFILES_ACTIVE', raising=False)
        loader = ConfigLoader(config_path=str(main_yml))
        # 大小写不敏感匹配段与键
        assert loader.get('app.name') == 'my-service'
        assert loader.get('App.Name') == 'my-service'
        assert loader.get('APP.NAME') == 'my-service'
        assert loader.get('app.version') == 1.0

    def test_get_exact_match_priority(self, tmp_path, monkeypatch):
        """精确匹配优先于松散匹配。"""
        from springbootai.config.config_loader import ConfigLoader
        loader = ConfigLoader.__new__(ConfigLoader)
        loader._config = {'log_dir': 'exact', 'log-dir': 'loose'}
        # 精确命中 log_dir
        assert loader.get('log_dir') == 'exact'
        # 精确命中 log-dir
        assert loader.get('log-dir') == 'loose'


# ==================== 风险8: CLI 参数覆盖 ====================

class TestCliArgsOverride:
    """验证 --key=value CLI 参数覆盖配置（优先级最高）。"""

    def test_cli_equals_form(self, tmp_path, monkeypatch):
        from springbootai.config.config_loader import ConfigLoader
        main_yml = tmp_path / "application.yml"
        main_yml.write_text("server:\n  port: 8080\n", encoding="utf-8")
        monkeypatch.setattr(sys, 'argv', ['app', '--server.port=9000'])
        loader = ConfigLoader(config_path=str(main_yml))
        assert loader.get('server.port') == 9000

    def test_cli_space_form(self, tmp_path, monkeypatch):
        from springbootai.config.config_loader import ConfigLoader
        main_yml = tmp_path / "application.yml"
        main_yml.write_text("server:\n  host: 0.0.0.0\n", encoding="utf-8")
        monkeypatch.setattr(sys, 'argv', ['app', '--server.host', '127.0.0.1'])
        loader = ConfigLoader(config_path=str(main_yml))
        assert loader.get('server.host') == '127.0.0.1'

    def test_cli_type_inference(self, tmp_path, monkeypatch):
        from springbootai.config.config_loader import ConfigLoader
        main_yml = tmp_path / "application.yml"
        main_yml.write_text("server:\n  port: 8080\n", encoding="utf-8")
        monkeypatch.setattr(sys, 'argv', ['app', '--server.port=9000'])
        loader = ConfigLoader(config_path=str(main_yml))
        # yaml 类型推断：9000 → int
        assert loader.get('server.port') == 9000
        assert isinstance(loader.get('server.port'), int)

    def test_cli_overrides_env(self, tmp_path, monkeypatch):
        """CLI 优先级高于环境变量。"""
        from springbootai.config.config_loader import ConfigLoader
        main_yml = tmp_path / "application.yml"
        main_yml.write_text("server:\n  port: 8080\n", encoding="utf-8")
        monkeypatch.setenv('SERVER_PORT', '7777')
        monkeypatch.setattr(sys, 'argv', ['app', '--server.port=9000'])
        loader = ConfigLoader(config_path=str(main_yml))
        assert loader.get('server.port') == 9000

    def test_cli_nested_key(self, tmp_path, monkeypatch):
        from springbootai.config.config_loader import ConfigLoader
        main_yml = tmp_path / "application.yml"
        main_yml.write_text("logging:\n  level: INFO\n", encoding="utf-8")
        monkeypatch.setattr(sys, 'argv', ['app', '--logging.level=DEBUG'])
        loader = ConfigLoader(config_path=str(main_yml))
        assert loader.get('logging.level') == 'DEBUG'


# ==================== 风险9: discovery / rabbitmq configure() ====================

class TestDiscoveryConfigure:
    """验证 NacosDiscoveryClient.configure() 单例配置生效。"""

    def setup_method(self):
        from springbootai.cloud.discovery import NacosDiscoveryClient
        NacosDiscoveryClient._instance = None

    def test_configure_updates_server_addr(self):
        from springbootai.cloud.discovery import NacosDiscoveryClient
        client = NacosDiscoveryClient(server_addr="initial:8848")
        assert client.server_addr == "initial:8848"
        client.configure(server_addr="changed:8848")
        assert client.server_addr == "changed:8848"

    def test_configure_resets_client_on_change(self):
        from springbootai.cloud.discovery import NacosDiscoveryClient
        client = NacosDiscoveryClient()
        client._client = object()
        client._ready = True
        client.configure(server_addr="new:8848")
        assert client._client is None
        assert client._ready is False

    def test_configure_no_change_keeps_client(self):
        from springbootai.cloud.discovery import NacosDiscoveryClient
        client = NacosDiscoveryClient(server_addr="same:8848")
        client._client = object()
        client._ready = True
        # 相同参数不应重置
        client.configure(server_addr="same:8848")
        assert client._client is not None
        assert client._ready is True

    def test_init_discovery_uses_configure(self):
        from springbootai.cloud.discovery import NacosDiscoveryClient, init_discovery
        NacosDiscoveryClient._instance = None
        # 重建全局单例
        import springbootai.cloud.discovery as disc
        disc.nacos_client = NacosDiscoveryClient()
        # 不实际 connect（NacosClient 未安装会优雅降级）
        init_discovery({
            'server_addr': 'configured:8848',
            'namespace': 'ns1',
            'group': 'G1',
            'username': 'u',
            'password': 'p',
        })
        assert disc.nacos_client.server_addr == 'configured:8848'
        assert disc.nacos_client.namespace == 'ns1'


class TestRabbitMqConfigure:
    """验证 RabbitMQClient.configure() 单例配置生效。"""

    def setup_method(self):
        from springbootai.messaging.rabbitmq import RabbitMQClient
        RabbitMQClient._instance = None

    def test_configure_updates_host_port(self):
        from springbootai.messaging.rabbitmq import RabbitMQClient
        client = RabbitMQClient(host="initial", port=5672)
        assert client.host == "initial"
        client.configure(host="changed", port=5673)
        assert client.host == "changed"
        assert client.port == 5673

    def test_configure_resets_connection(self):
        from unittest.mock import MagicMock
        from springbootai.messaging.rabbitmq import RabbitMQClient
        client = RabbitMQClient()
        # 用 MagicMock 模拟真实连接对象（含 is_closed 属性）
        client._connection = MagicMock()
        client._connection.is_closed = False
        client._channel = MagicMock()
        client.configure(host="new-host")
        assert client._connection is None
        assert client._channel is None

    def test_configure_partial_update(self):
        from springbootai.messaging.rabbitmq import RabbitMQClient
        client = RabbitMQClient(host="keep", port=5672, username="guest")
        client.configure(port=5673)
        assert client.host == "keep"
        assert client.port == 5673
        assert client.username == "guest"


# ==================== 风险10: redis.timeout 生效 ====================

class TestRedisTimeout:
    """验证 redis.timeout 配置项生效。"""

    def test_configure_accepts_timeout(self):
        from springbootai.utils.redis_client import RedisClient
        client = RedisClient(timeout=10)
        assert client.timeout == 10.0

    def test_configure_updates_timeout(self):
        from springbootai.utils.redis_client import RedisClient
        client = RedisClient(timeout=5)
        client.configure(host='h', port=6379, db=0, timeout=15)
        assert client.timeout == 15.0

    def test_init_redis_converts_ms_to_seconds(self, monkeypatch):
        """init_redis 应把毫秒 timeout 换算为秒。"""
        import springbootai.utils.redis_client as rc_module
        # 用 mock 避免真实连接
        called = {}

        def fake_connect(self, strict=False):
            called['timeout'] = self.timeout

        monkeypatch.setattr(rc_module.RedisClient, 'connect', fake_connect)
        rc_module.redis_client.configure(host='h', port=6379, db=0, timeout=5)
        rc_module.init_redis({'host': 'h', 'port': 6379, 'db': 0, 'timeout': 5000})
        # 5000ms → 5.0s
        assert rc_module.redis_client.timeout == 5.0
        assert called['timeout'] == 5.0

    def test_init_redis_default_timeout(self, monkeypatch):
        import springbootai.utils.redis_client as rc_module

        def fake_connect(self, strict=False):
            pass

        monkeypatch.setattr(rc_module.RedisClient, 'connect', fake_connect)
        rc_module.init_redis({'host': 'h', 'port': 6379, 'db': 0})
        # 默认 5000ms → 5.0s
        assert rc_module.redis_client.timeout == 5.0


# ==================== 集成：完整配置加载链路 ====================

class TestConfigLoaderIntegration:
    """端到端验证配置加载链路（主配置 + profile + 占位符 + env + CLI）。"""

    def test_full_chain_priority(self, tmp_path, monkeypatch):
        """优先级：CLI > env > profile > 主配置。"""
        from springbootai.config.config_loader import ConfigLoader
        main_yml = tmp_path / "application.yml"
        main_yml.write_text(
            "spring:\n  profiles:\n    active: dev\n"
            "server:\n  port: 8080\n",
            encoding="utf-8")
        profile_yml = tmp_path / "application-dev.yml"
        profile_yml.write_text("server:\n  port: 9000\n", encoding="utf-8")
        monkeypatch.setenv('SERVER_PORT', '7777')
        monkeypatch.setattr(sys, 'argv', ['app', '--server.port=11111'])
        loader = ConfigLoader(config_path=str(main_yml))
        # CLI 优先级最高
        assert loader.get('server.port') == 11111

    def test_env_overrides_profile(self, tmp_path, monkeypatch):
        """env 优先级高于 profile。"""
        from springbootai.config.config_loader import ConfigLoader
        main_yml = tmp_path / "application.yml"
        main_yml.write_text(
            "spring:\n  profiles:\n    active: dev\n"
            "server:\n  port: 8080\n",
            encoding="utf-8")
        profile_yml = tmp_path / "application-dev.yml"
        profile_yml.write_text("server:\n  port: 9000\n", encoding="utf-8")
        monkeypatch.setenv('SERVER_PORT', '7777')
        monkeypatch.setattr(sys, 'argv', ['app'])
        loader = ConfigLoader(config_path=str(main_yml))
        assert loader.get('server.port') == 7777
