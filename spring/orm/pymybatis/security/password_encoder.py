"""
PyMyBatis密码加密模块

实现密码字段的安全哈希存储和验证，支持多种算法：
- 旧 MD5 哈希只读兼容（新编码升级为 PBKDF2-SHA256）
- PBKDF2-SHA256
- BCrypt
"""

import hashlib
import hmac
import os
from typing import Optional
from enum import Enum


class EncryptionAlgorithm(Enum):
    """加密算法枚举"""
    MD5 = 'md5'
    SHA256 = 'sha256'
    BCRYPT = 'bcrypt'


class PasswordEncoder:
    """
    密码加密器

    核心功能：
    1. 支持 BCrypt、PBKDF2-SHA256 和旧 MD5 哈希迁移
    2. 自动添加随机盐值（Salt）
    3. 密码验证
    4. 支持配置加密算法
    """

    def __init__(self, algorithm: str = 'bcrypt'):
        """
        初始化密码加密器

        Args:
            algorithm: 加密算法（md5/sha256/bcrypt）
        """
        self.algorithm = EncryptionAlgorithm(algorithm.lower())
        self._bcrypt = None

        # 如果使用BCrypt，延迟加载bcrypt库
        if self.algorithm == EncryptionAlgorithm.BCRYPT:
            self._load_bcrypt()

    def _load_bcrypt(self) -> None:
        """加载BCrypt库"""
        try:
            import bcrypt
            self._bcrypt = bcrypt
        except ImportError:
            raise ImportError("请安装bcrypt: pip install bcrypt")

    def _generate_salt(self, length: int = 16) -> bytes:
        """
        生成随机盐值

        Args:
            length: 盐值长度

        Returns:
            盐值字节数组
        """
        return os.urandom(length)

    def encode(self, password: str, salt: Optional[str] = None) -> str:
        """
        加密密码

        Args:
            password: 明文密码
            salt: 盐值，不指定则自动生成

        Returns:
            加密后的密码字符串
        """
        if password is None:
            raise ValueError("密码不能为空")

        if self.algorithm == EncryptionAlgorithm.BCRYPT:
            return self._encode_bcrypt(password)
        elif self.algorithm == EncryptionAlgorithm.SHA256:
            return self._encode_sha256(password, salt)
        elif self.algorithm == EncryptionAlgorithm.MD5:
            return self._encode_md5(password, salt)

        raise ValueError(f"不支持的加密算法: {self.algorithm}")

    def _encode_bcrypt(self, password: str) -> str:
        """
        使用BCrypt加密密码

        Args:
            password: 明文密码

        Returns:
            加密后的密码字符串
        """
        if self._bcrypt is None:
            self._load_bcrypt()

        salt = self._bcrypt.gensalt()
        hashed = self._bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')

    def _encode_sha256(self, password: str, salt: Optional[str] = None) -> str:
        """
        使用SHA-256加密密码

        Args:
            password: 明文密码
            salt: 盐值

        Returns:
            加密后的密码字符串（格式：salt$hash）
        """
        if salt is None:
            salt = self._generate_salt(16).hex()

        salt_bytes = bytes.fromhex(salt)
        password_bytes = password.encode('utf-8')

        # 使用PBKDF2进行多次哈希
        import hashlib
        hashed = hashlib.pbkdf2_hmac(
            'sha256',
            password_bytes,
            salt_bytes,
            100000
        )

        return f"{salt}${hashed.hex()}"

    def _encode_md5(self, password: str, salt: Optional[str] = None) -> str:
        """
        兼容旧 ``algorithm=md5`` 配置，但新密码使用 PBKDF2-SHA256。

        Args:
            password: 明文密码
            salt: 盐值

        Returns:
            加密后的密码字符串（格式：salt$hash）
        """
        if salt is None:
            salt = self._generate_salt(16).hex()

        return f"pbkdf2_sha256${self._encode_sha256(password, salt)}"

    def matches(self, raw_password: str, encoded_password: str) -> bool:
        """
        验证密码是否匹配

        Args:
            raw_password: 明文密码
            encoded_password: 加密后的密码

        Returns:
            是否匹配
        """
        if raw_password is None or encoded_password is None:
            return False

        if self.algorithm == EncryptionAlgorithm.BCRYPT:
            return self._matches_bcrypt(raw_password, encoded_password)
        elif self.algorithm == EncryptionAlgorithm.SHA256:
            return self._matches_sha256(raw_password, encoded_password)
        elif self.algorithm == EncryptionAlgorithm.MD5:
            return self._matches_md5(raw_password, encoded_password)

        raise ValueError(f"不支持的加密算法: {self.algorithm}")

    def _matches_bcrypt(self, raw_password: str, encoded_password: str) -> bool:
        """
        使用BCrypt验证密码

        Args:
            raw_password: 明文密码
            encoded_password: 加密后的密码

        Returns:
            是否匹配
        """
        if self._bcrypt is None:
            self._load_bcrypt()

        return self._bcrypt.checkpw(
            raw_password.encode('utf-8'),
            encoded_password.encode('utf-8')
        )

    def _matches_sha256(self, raw_password: str, encoded_password: str) -> bool:
        """
        使用SHA-256验证密码

        Args:
            raw_password: 明文密码
            encoded_password: 加密后的密码

        Returns:
            是否匹配
        """
        parts = encoded_password.split('$')
        if len(parts) != 2:
            return False

        salt = parts[0]
        expected_hash = parts[1]

        salt_bytes = bytes.fromhex(salt)
        password_bytes = raw_password.encode('utf-8')

        hashed = hashlib.pbkdf2_hmac(
            'sha256',
            password_bytes,
            salt_bytes,
            100000
        )

        return hmac.compare_digest(hashed.hex(), expected_hash)

    def _matches_md5(self, raw_password: str, encoded_password: str) -> bool:
        """
        验证迁移模式密码；兼容读取旧 MD5，新的编码使用 PBKDF2-SHA256。

        Args:
            raw_password: 明文密码
            encoded_password: 加密后的密码

        Returns:
            是否匹配
        """
        parts = encoded_password.split('$')
        if len(parts) == 3 and parts[0] == 'pbkdf2_sha256':
            return self._matches_sha256(raw_password, '$'.join(parts[1:]))
        if len(parts) != 2:
            return False

        salt = parts[0]
        expected_hash = parts[1]

        # 仅验证已存在的旧哈希；成功登录后应使用 encode() 重新哈希。
        md5 = hashlib.md5(usedforsecurity=False)
        md5.update(salt.encode('utf-8'))
        md5.update(raw_password.encode('utf-8'))
        hashed = md5.hexdigest()

        return hmac.compare_digest(hashed, expected_hash)

    def set_algorithm(self, algorithm: str) -> None:
        """
        设置加密算法

        Args:
            algorithm: 加密算法名称
        """
        self.algorithm = EncryptionAlgorithm(algorithm.lower())
        if self.algorithm == EncryptionAlgorithm.BCRYPT and self._bcrypt is None:
            self._load_bcrypt()


# 全局默认密码加密器（使用BCrypt）
DEFAULT_PASSWORD_ENCODER = PasswordEncoder()


def encode_password(password: str) -> str:
    """
    便捷函数：加密密码（使用默认加密器）

    Args:
        password: 明文密码

    Returns:
        加密后的密码
    """
    return DEFAULT_PASSWORD_ENCODER.encode(password)


def verify_password(raw_password: str, encoded_password: str) -> bool:
    """
    便捷函数：验证密码（使用默认加密器）

    Args:
        raw_password: 明文密码
        encoded_password: 加密后的密码

    Returns:
        是否匹配
    """
    return DEFAULT_PASSWORD_ENCODER.matches(raw_password, encoded_password)
