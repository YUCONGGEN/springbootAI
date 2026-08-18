"""认证/授权失败必须绕过项目的宽泛异常 Advice。"""
from springbootai.security.security_aop import AuthenticationError, AuthorizationError
from springbootai.web.web_context import WebApplicationContext


def test_expired_or_invalid_token_is_a_standard_401_response():
    response = WebApplicationContext._security_failure_response(
        AuthenticationError("Invalid token: Signature has expired")
    )

    assert response is not None
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    assert b"Authentication required" in response.body
    assert b"Signature has expired" not in response.body


def test_authorization_failure_is_a_standard_403_response():
    response = WebApplicationContext._security_failure_response(
        AuthorizationError("Required role(s) ['ROLE_ADMIN']")
    )

    assert response is not None
    assert response.status_code == 403
    assert b"Access denied" in response.body


def test_non_security_errors_remain_available_to_project_exception_advice():
    assert WebApplicationContext._security_failure_response(ValueError("bad input")) is None
