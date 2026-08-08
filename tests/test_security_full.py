"""安全功能完整测试 - 覆盖 JWT、SecurityContext、密码编码、SQL注入检测等。"""

import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import tests._test_helpers  # noqa: F401  安装模块mock

from spring.annotations.core import PreAuthorize, Secured, Authenticate, get_spring_annotations
from spring.security.jwt_utils import JwtUtils
from spring.security.security_context import SecurityContext
from spring.orm.pymybatis.security.password_encoder import (
    PasswordEncoder, encode_password, verify_password,
)
from spring.orm.pymybatis.security.sql_injection_detector import (
    SQLInjectionDetector, SQLInjectionLevel,
)


# ==================== JWT 测试 ====================

class TestJwtUtilsConstruction:
    def test_default_construction(self):
        jwt = JwtUtils()
        assert jwt.algorithm == "HS256"
        assert jwt.issuer is None

    def test_with_secret_and_algorithm(self):
        jwt = JwtUtils(secret_key="mykey", algorithm="HS256")
        assert jwt.secret_key == "mykey"
        assert jwt.algorithm == "HS256"

    def test_algorithm_hs384(self):
        jwt = JwtUtils(algorithm="HS384")
        assert jwt.algorithm == "HS384"

    def test_algorithm_hs512(self):
        jwt = JwtUtils(algorithm="HS512")
        assert jwt.algorithm == "HS512"

    def test_rs256_not_supported(self):
        with pytest.raises(ValueError):
            JwtUtils(algorithm="RS256")

    def test_configure_with_issuer(self):
        jwt = JwtUtils(secret_key="key")
        jwt.configure(issuer="my-app")
        assert jwt.issuer == "my-app"

    def test_configure_with_audience(self):
        jwt = JwtUtils(secret_key="key")
        jwt.configure(audience="my-aud")
        assert jwt.audience == "my-aud"

    def test_constructor_does_not_accept_issuer(self):
        # 构造函数不接受 issuer 参数；应抛出 TypeError
        with pytest.raises(TypeError):
            JwtUtils(secret_key="key", issuer="my-app")


class TestJwtTokenGeneration:
    def setup_method(self):
        self.jwt = JwtUtils(secret_key="test-secret-key-for-unit-tests-0123456789abcdef", algorithm="HS256")

    def test_generate_token_returns_string(self):
        token = self.jwt.generate_token({"user_id": "u1"}, expires_in=3600)
        assert isinstance(token, str)
        assert token.count(".") == 2

    def test_generate_token_includes_claims(self):
        token = self.jwt.generate_token({"user_id": "u1"}, expires_in=3600)
        payload = self.jwt.get_payload(token)
        assert payload["user_id"] == "u1"
        assert "exp" in payload
        assert "iat" in payload
        assert "jti" in payload
        assert payload["token_type"] == "access"

    def test_generate_token_includes_issuer(self):
        self.jwt.configure(issuer="my-app")
        token = self.jwt.generate_token({"user_id": "u1"}, expires_in=3600)
        payload = self.jwt.get_payload(token)
        assert payload["iss"] == "my-app"

    def test_generate_token_zero_expires_raises(self):
        with pytest.raises(ValueError):
            self.jwt.generate_token({"user_id": "u1"}, expires_in=0)

    def test_validate_token_valid(self):
        token = self.jwt.generate_token({"user_id": "u1"}, expires_in=3600)
        assert self.jwt.validate_token(token) is True

    def test_validate_token_invalid(self):
        assert self.jwt.validate_token("invalid.token.here") is False

    def test_decode_token_returns_payload(self):
        token = self.jwt.generate_token({"user_id": "u1"}, expires_in=3600)
        payload = self.jwt.decode_token(token)
        assert payload["user_id"] == "u1"

    def test_verify_token_returns_payload(self):
        token = self.jwt.generate_token({"user_id": "u1"}, expires_in=3600)
        payload = self.jwt.verify_token(token)
        assert payload["user_id"] == "u1"

    def test_is_expired_false_for_fresh_token(self):
        token = self.jwt.generate_token({"user_id": "u1"}, expires_in=3600)
        assert self.jwt.is_expired(token) is False

    def test_is_expired_true_for_expired_token(self):
        # 生成一个已过期的 token：先生成再篡改 exp
        import jwt as pyjwt
        payload = {
            "user_id": "u1",
            "exp": int(time.time()) - 100,
            "iat": int(time.time()) - 200,
            "jti": "abc",
            "token_type": "access",
        }
        token = pyjwt.encode(payload, "test-secret-key-for-unit-tests-0123456789abcdef", algorithm="HS256")
        assert self.jwt.is_expired(token) is True

    def test_extract_user_id(self):
        token = self.jwt.generate_token({"user_id": "u1"}, expires_in=3600)
        assert self.jwt.extract_user_id(token) == "u1"

    def test_extract_user_id_from_sub(self):
        token = self.jwt.generate_token({"sub": "subj1"}, expires_in=3600)
        assert self.jwt.extract_user_id(token) == "subj1"

    def test_extract_roles_list(self):
        token = self.jwt.generate_token({"roles": ["ADMIN", "USER"]}, expires_in=3600)
        assert self.jwt.extract_roles(token) == ["ADMIN", "USER"]

    def test_extract_roles_string(self):
        token = self.jwt.generate_token({"roles": "ADMIN"}, expires_in=3600)
        assert self.jwt.extract_roles(token) == ["ADMIN"]

    def test_extract_permissions(self):
        token = self.jwt.generate_token({"permissions": ["read", "write"]}, expires_in=3600)
        assert self.jwt.extract_permissions(token) == ["read", "write"]


class TestJwtRefreshToken:
    def setup_method(self):
        self.jwt = JwtUtils(secret_key="test-secret-key-for-unit-tests-0123456789abcdef", algorithm="HS256")

    def test_generate_refresh_token(self):
        token = self.jwt.generate_refresh_token({"user_id": "u1"}, expires_in=86400)
        payload = self.jwt.get_payload(token)
        assert payload["token_type"] == "refresh"

    def test_refresh_token_returns_new_access_token(self):
        refresh = self.jwt.generate_refresh_token({"user_id": "u1"}, expires_in=86400)
        new_access = self.jwt.refresh_token(refresh, expires_in=3600)
        payload = self.jwt.decode_token(new_access)
        assert payload["user_id"] == "u1"
        assert payload["token_type"] == "access"

    def test_refresh_token_rejects_access_token(self):
        access = self.jwt.generate_token({"user_id": "u1"}, expires_in=3600)
        with pytest.raises(Exception):
            self.jwt.refresh_token(access, expires_in=3600)


# ==================== SecurityContext 测试 ====================

class TestSecurityContext:
    def test_default_not_authenticated(self):
        ctx = SecurityContext()
        assert ctx.is_authenticated() is False

    def test_set_authentication(self):
        ctx = SecurityContext()
        ctx.authentication = {"principal": "u1"}
        assert ctx.is_authenticated() is True
        assert ctx.principal is None  # principal only set via SecurityContextHolder

    def test_has_role(self):
        ctx = SecurityContext()
        ctx.roles = ["ADMIN", "USER"]
        assert ctx.has_role("ADMIN") is True
        assert ctx.has_role("GUEST") is False

    def test_has_any_role(self):
        ctx = SecurityContext()
        ctx.roles = ["ADMIN"]
        assert ctx.has_any_role("ADMIN", "USER") is True
        assert ctx.has_any_role("USER", "GUEST") is False

    def test_has_permission(self):
        ctx = SecurityContext()
        ctx.permissions = ["read", "write"]
        assert ctx.has_permission("read") is True
        assert ctx.has_permission("delete") is False

    def test_has_any_permission(self):
        ctx = SecurityContext()
        ctx.permissions = ["read"]
        assert ctx.has_any_permission("read", "write") is True
        assert ctx.has_any_permission("write", "delete") is False

    def test_clear(self):
        ctx = SecurityContext()
        ctx.authentication = {"principal": "u1"}
        ctx.roles = ["ADMIN"]
        ctx.permissions = ["read"]
        ctx.clear()
        assert ctx.is_authenticated() is False
        assert ctx.roles == []
        assert ctx.permissions == []


# ==================== 安全注解测试 ====================

class TestSecurityAnnotations:
    def test_pre_authorize_value(self):
        ann = PreAuthorize("hasRole('ROLE_ADMIN')")
        assert ann.value == "hasRole('ROLE_ADMIN')"

    def test_pre_authorize_decorates(self):
        @PreAuthorize("hasRole('ROLE_ADMIN')")
        def secure():
            pass

        anns = get_spring_annotations(secure)
        assert len(anns) == 1
        assert isinstance(anns[0], PreAuthorize)

    def test_secured_value_list(self):
        ann = Secured(["ROLE_ADMIN", "ROLE_EDITOR"])
        assert ann.value == ["ROLE_ADMIN", "ROLE_EDITOR"]

    def test_authenticate_default(self):
        ann = Authenticate()
        assert ann._annotation_type == "security"

    def test_authenticate_decorates(self):
        @Authenticate()
        def secure():
            pass

        anns = get_spring_annotations(secure)
        assert len(anns) == 1
        assert isinstance(anns[0], Authenticate)


# ==================== PasswordEncoder 测试 ====================

class TestPasswordEncoderSha256:
    def setup_method(self):
        self.encoder = PasswordEncoder(algorithm="sha256")

    def test_encode_returns_string(self):
        encoded = self.encoder.encode("password123")
        assert isinstance(encoded, str)
        assert "$" in encoded

    def test_encode_different_inputs_differ(self):
        e1 = self.encoder.encode("password1")
        e2 = self.encoder.encode("password2")
        assert e1 != e2

    def test_encode_with_explicit_salt(self):
        encoded = self.encoder.encode("password", salt="abcdef0123456789")
        assert encoded.startswith("abcdef0123456789$")

    def test_matches_correct_password(self):
        encoded = self.encoder.encode("password123")
        assert self.encoder.matches("password123", encoded) is True

    def test_matches_wrong_password(self):
        encoded = self.encoder.encode("password123")
        assert self.encoder.matches("wrong", encoded) is False

    def test_matches_none_returns_false(self):
        encoded = self.encoder.encode("password123")
        assert self.encoder.matches(None, encoded) is False


class TestPasswordEncoderMd5:
    def setup_method(self):
        self.encoder = PasswordEncoder(algorithm="md5")

    def test_encode_returns_string(self):
        encoded = self.encoder.encode("password123")
        assert isinstance(encoded, str)
        assert "$" in encoded

    def test_matches_correct(self):
        encoded = self.encoder.encode("password123")
        assert self.encoder.matches("password123", encoded) is True

    def test_matches_wrong(self):
        encoded = self.encoder.encode("password123")
        assert self.encoder.matches("wrong", encoded) is False


class TestPasswordEncoderInvalid:
    def test_invalid_algorithm_raises(self):
        with pytest.raises(ValueError):
            PasswordEncoder(algorithm="invalid_algo")

    def test_encode_none_password_raises(self):
        encoder = PasswordEncoder(algorithm="sha256")
        with pytest.raises(ValueError):
            encoder.encode(None)

    def test_set_algorithm(self):
        encoder = PasswordEncoder(algorithm="sha256")
        encoder.set_algorithm("md5")
        assert encoder.algorithm.value == "md5"


class TestPasswordFunctions:
    def test_encode_password_uses_default_encoder(self):
        # 默认是 bcrypt
        encoded = encode_password("mypassword")
        assert isinstance(encoded, str)

    def test_verify_password_correct(self):
        encoded = encode_password("mypassword")
        assert verify_password("mypassword", encoded) is True

    def test_verify_password_wrong(self):
        encoded = encode_password("mypassword")
        assert verify_password("wrongpassword", encoded) is False


# ==================== SQLInjectionDetector 测试 ====================

class TestSQLInjectionLevel:
    def test_none_value(self):
        assert SQLInjectionLevel.NONE.value == 0

    def test_low_value(self):
        assert SQLInjectionLevel.LOW.value == 1

    def test_medium_value(self):
        assert SQLInjectionLevel.MEDIUM.value == 2

    def test_high_value(self):
        assert SQLInjectionLevel.HIGH.value == 3


class TestSQLInjectionDetector:
    def setup_method(self):
        self.detector = SQLInjectionDetector(enabled=True, max_risk_level=SQLInjectionLevel.LOW)

    def test_clean_input_returns_none(self):
        assert self.detector.detect("normal_value") == SQLInjectionLevel.NONE

    def test_clean_number_returns_none(self):
        assert self.detector.detect(123) == SQLInjectionLevel.NONE

    def test_none_returns_none(self):
        assert self.detector.detect(None) == SQLInjectionLevel.NONE

    def test_union_select_detected(self):
        level = self.detector.detect("1 UNION SELECT * FROM users")
        assert level == SQLInjectionLevel.HIGH

    def test_drop_detected(self):
        level = self.detector.detect("DROP TABLE users")
        assert level == SQLInjectionLevel.HIGH

    def test_comment_injection(self):
        level = self.detector.detect("1; -- comment")
        assert level.value > SQLInjectionLevel.NONE.value

    def test_returns_enum_not_object(self):
        level = self.detector.detect("normal")
        assert isinstance(level, SQLInjectionLevel)

    def test_disabled_returns_none(self):
        detector = SQLInjectionDetector(enabled=False)
        assert detector.detect("DROP TABLE users") == SQLInjectionLevel.NONE


class TestSQLInjectionDetectorDDL:
    def setup_method(self):
        self.detector = SQLInjectionDetector(block_ddl=True)

    def test_drop_detected_as_ddl(self):
        assert self.detector.detect_ddl("DROP TABLE users") is True

    def test_alter_detected_as_ddl(self):
        assert self.detector.detect_ddl("ALTER TABLE users ADD COLUMN x") is True

    def test_create_table_detected(self):
        assert self.detector.detect_ddl("CREATE TABLE users (id INT)") is True

    def test_select_not_ddl(self):
        assert self.detector.detect_ddl("SELECT * FROM users") is False

    def test_ddl_blocked_when_block_ddl_true(self):
        assert self.detector.is_ddl_blocked("DROP TABLE users") is True

    def test_ddl_not_blocked_when_block_ddl_false(self):
        detector = SQLInjectionDetector(block_ddl=False)
        assert detector.is_ddl_blocked("DROP TABLE users") is False


class TestSQLInjectionDetectorBlock:
    def test_is_blocked_high(self):
        detector = SQLInjectionDetector(max_risk_level=SQLInjectionLevel.LOW)
        assert detector.is_blocked("1 UNION SELECT *") is True

    def test_is_safe_normal(self):
        detector = SQLInjectionDetector(max_risk_level=SQLInjectionLevel.LOW)
        assert detector.is_safe("normal_value") is True

    def test_sanitize_removes_comments(self):
        detector = SQLInjectionDetector()
        cleaned = detector.sanitize("value -- comment")
        assert "--" not in cleaned
        assert "comment" not in cleaned


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
