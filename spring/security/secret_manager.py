"""
密钥管理器 (Secret Manager)

生产级密钥管理：
- 优先从环境变量读取（推荐与Vault/K8s Secrets/AWS Secrets Manager集成）
- 支持 .env 文件（开发环境）
- 支持 base64 编码密钥解码
- 密钥脱敏（日志中不输出明文）
- 密钥轮换支持
"""

import os
import base64
import logging
import hashlib
from typing import Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger("Spring.Security.Secret")

# 敏感配置键名模式
_SENSITIVE_KEY_PATTERNS = {
    'password', 'secret', 'token', 'key', 'credential',
    'api_key', 'apikey', 'access_key', 'private_key',
}


def is_sensitive_key(key: str) -> bool:
    """判断配置键是否为敏感字段"""
    key_lower = key.lower()
    return any(pattern in key_lower for pattern in _SENSITIVE_KEY_PATTERNS)


def mask_secret(value: str, show_chars: int = 4) -> str:
    """脱敏显示密钥，仅显示前后show_chars位"""
    if not value or not isinstance(value, str):
        return "***"
    if len(value) <= show_chars * 2:
        return "***"
    return f"{value[:show_chars]}***{value[-show_chars:]}"


class SecretManager:
    """
    密钥管理器

    密钥加载优先级:
    1. 环境变量 (SPRING_SECRETS_ 前缀或直接变量名)
    2. Docker/K8s secrets 文件 (/run/secrets/{name})
    3. .env 文件（仅开发环境，需显式启用）
    """

    _instance = None
    _secrets: Dict[str, str] = {}
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._secrets = {}
            self._initialized = False
            self._init_from_env()

    def _init_from_env(self):
        """从环境变量初始化密钥"""
        # 从 SPRING_SECRETS_ 前缀加载
        prefix = "SPRING_SECRETS_"
        for key, value in os.environ.items():
            if key.startswith(prefix):
                secret_name = key[len(prefix):].lower()
                self._secrets[secret_name] = value
                logger.debug(f"Loaded secret from env: {secret_name}={mask_secret(value)}")

        # Docker/K8s secrets 文件
        secrets_dir = os.getenv('SPRING_SECRETS_DIR', '/run/secrets')
        secrets_path = Path(secrets_dir)
        if secrets_path.exists() and secrets_path.is_dir():
            for f in secrets_path.iterdir():
                if f.is_file():
                    name = f.name.lower().replace('-', '_')
                    try:
                        self._secrets[name] = f.read_text().strip()
                        logger.debug(f"Loaded secret from file: {name}")
                    except Exception as e:
                        logger.warning(f"Failed to read secret file {f}: {e}")

        # 开发环境：.env 文件
        if os.getenv('SPRING_ENV', '').lower() in ('dev', 'development', 'local'):
            env_file = Path('.env')
            if env_file.exists():
                try:
                    for line in env_file.read_text().splitlines():
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            k, v = line.split('=', 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            if k.startswith(prefix):
                                secret_name = k[len(prefix):].lower()
                                self._secrets[secret_name] = v
                    logger.debug("Loaded secrets from .env file (development only)")
                except Exception as e:
                    logger.warning(f"Failed to read .env file: {e}")

        self._initialized = True

    def get_secret(self, name: str, default: Optional[str] = None,
                   decode_base64: bool = False) -> Optional[str]:
        """
        获取密钥

        Args:
            name: 密钥名称（不区分大小写，自动转换下划线/连字符）
            default: 默认值
            decode_base64: 是否base64解码

        Returns:
            密钥值，不存在时返回default
        """
        name_normalized = name.lower().replace('-', '_')

        # 1. 从已加载的secrets中查找
        if name_normalized in self._secrets:
            value = self._secrets[name_normalized]
            return self._decode(value, decode_base64)

        # 2. 直接从环境变量查找（支持DB_PASSWORD, REDIS_PASSWORD等标准命名）
        env_variants = [
            name.upper(),
            name.upper().replace('.', '_'),
            name.upper().replace('-', '_'),
        ]
        for env_name in env_variants:
            if env_name in os.environ:
                return self._decode(os.environ[env_name], decode_base64)

        return default

    def _decode(self, value: str, decode_base64: bool) -> str:
        """解码密钥值"""
        if decode_base64 and value:
            try:
                return base64.b64decode(value).decode('utf-8')
            except Exception:
                logger.warning("Failed to decode base64 secret, returning raw value")
        return value

    def require_secret(self, name: str, decode_base64: bool = False) -> str:
        """获取必须存在的密钥，不存在则抛出异常"""
        value = self.get_secret(name, decode_base64=decode_base64)
        if value is None:
            raise ValueError(f"Required secret '{name}' not found. "
                             f"Set environment variable {name.upper()} or "
                             f"SPRING_SECRETS_{name.upper()}")
        return value

    def get_database_password(self) -> str:
        """获取数据库密码"""
        return self.get_secret('db_password', '') or ''

    def get_redis_password(self) -> str:
        """获取Redis密码"""
        return self.get_secret('redis_password', '') or ''

    def get_rabbitmq_password(self) -> str:
        """获取RabbitMQ密码"""
        return self.get_secret('rabbitmq_password', '') or ''

    def get_jwt_secret(self) -> str:
        """获取JWT密钥"""
        return self.require_secret('jwt_secret_key')

    def get_nacos_password(self) -> str:
        """获取Nacos密码"""
        return self.get_secret('nacos_password', 'nacos') or 'nacos'

    def set_secret(self, name: str, value: str) -> None:
        """运行时设置密钥（用于密钥轮换）"""
        name_normalized = name.lower().replace('-', '_')
        self._secrets[name_normalized] = value
        logger.info(f"Secret rotated: {name_normalized}")

    def clear(self) -> None:
        """清空所有密钥（测试用）"""
        self._secrets.clear()
        self._initialized = False

    @classmethod
    def reset(cls):
        """重置单例（测试用）"""
        cls._instance = None


def resolve_secret_config(config: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """
    递归解析配置中的密钥引用

    支持 ${secret:key_name} 或 ${secret:key_name:default} 格式
    """
    secret_mgr = SecretManager()
    import re
    _SECRET_PATTERN = re.compile(r'^\$\{secret:([^}:]+)(?::(.*))?\}$')

    def _resolve(value, path=""):
        if isinstance(value, dict):
            return {k: _resolve(v, f"{path}.{k}" if path else k) for k, v in value.items()}
        if isinstance(value, list):
            return [_resolve(v, f"{path}[{i}]") for i, v in enumerate(value)]
        if isinstance(value, str):
            match = _SECRET_PATTERN.match(value)
            if match:
                secret_name = match.group(1)
                default_val = match.group(2)
                resolved = secret_mgr.get_secret(secret_name, default=default_val)
                if resolved is None:
                    if is_sensitive_key(path.split('.')[-1] if path else ''):
                        logger.warning(f"Secret '{secret_name}' not found for config '{path}'")
                    return default_val if default_val is not None else value
                return resolved
        return value

    return _resolve(config)
