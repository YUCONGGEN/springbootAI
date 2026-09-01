"""Regression coverage for production-safety boundaries."""
import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from springbootai.annotations.core import CircuitBreaker, Idempotent, Lock, RateLimit
from springbootai.aop.comprehensive_aop import (
    RateLimitExceeded,
    circuit_breaker_decorator,
    idempotent_decorator,
    lock_decorator,
    rate_limit_decorator,
)
from springbootai.data.rest import RepositoryRestController
from springbootai.security.security_aop import authenticate_decorator
from springbootai.security.security_context import SecurityContextHolder
from springbootai.web.csrf import init_csrf


def test_rate_limit_rejection_never_executes_business(monkeypatch):
    class Redis:
        def eval(self, *_args):
            return 0

    from springbootai.aop import comprehensive_aop as module
    monkeypatch.setattr(module.redis_client, "get_client", lambda: Redis())
    calls = 0

    @rate_limit_decorator(RateLimit(max_requests=1, time_window=60))
    def business():
        nonlocal calls
        calls += 1

    with pytest.raises(RateLimitExceeded):
        business()
    assert calls == 0


def test_circuit_breaker_business_exception_is_not_retried_locally(monkeypatch):
    class Redis:
        def __init__(self):
            self.state = {}

        def hgetall(self, _key):
            return dict(self.state)

        def hset(self, _key, mapping=None, **_kwargs):
            self.state.update(mapping or {})

    from springbootai.aop import comprehensive_aop as module
    monkeypatch.setattr(module.redis_client, "get_client", lambda: Redis())
    calls = 0

    @circuit_breaker_decorator(CircuitBreaker(failure_threshold=1))
    def business():
        nonlocal calls
        calls += 1
        raise ValueError("business failure")

    with pytest.raises(ValueError, match="business failure"):
        business()
    assert calls == 1


def test_idempotent_business_exception_is_not_retried_locally(monkeypatch):
    class Redis:
        def eval(self, script, *_args):
            if "return {'ACQUIRED'}" in script:
                return ["ACQUIRED"]
            return 1

    from springbootai.aop import comprehensive_aop as module
    monkeypatch.setattr(module.redis_client, "get_client", lambda: Redis())
    calls = 0

    @idempotent_decorator(Idempotent(key="request_id"))
    def business(request_id):
        nonlocal calls
        calls += 1
        raise ValueError("business failure")

    with pytest.raises(ValueError, match="business failure"):
        business("req-1")
    assert calls == 1


def test_distributed_lock_business_exception_is_not_retried_locally(monkeypatch):
    from springbootai.aop import comprehensive_aop as module
    monkeypatch.setattr(module.redis_client, "get_client", lambda: object())
    monkeypatch.setattr(module.redis_client, "acquire_lock", lambda *_a, **_k: "owner")
    monkeypatch.setattr(module.redis_client, "release_lock", lambda *_a, **_k: True)
    calls = 0

    @lock_decorator(Lock(key="item_id"))
    def business(item_id):
        nonlocal calls
        calls += 1
        raise ValueError("business failure")

    with pytest.raises(ValueError, match="business failure"):
        business(1)
    assert calls == 1


def test_async_distributed_lock_is_held_until_await_completes(monkeypatch):
    from springbootai.aop import comprehensive_aop as module
    state = {"held": False}
    monkeypatch.setattr(module.redis_client, "get_client", lambda: object())

    def acquire(*_args, **_kwargs):
        state["held"] = True
        return "owner"

    def release(*_args, **_kwargs):
        state["held"] = False
        return True

    monkeypatch.setattr(module.redis_client, "acquire_lock", acquire)
    monkeypatch.setattr(module.redis_client, "release_lock", release)

    @lock_decorator(Lock(key="item_id"))
    async def business(item_id):
        assert state["held"] is True
        await asyncio.sleep(0)
        assert state["held"] is True
        return item_id

    assert asyncio.run(business(7)) == 7
    assert state["held"] is False


def test_authenticate_uses_configured_oauth2_validator(monkeypatch):
    from springbootai.security.oauth2 import oauth2_resource_server
    from springbootai.security.jwt_utils import jwt_utils
    oauth2_resource_server.reset()
    oauth2_resource_server._configured = True
    monkeypatch.setattr(
        oauth2_resource_server,
        "validate_token",
        lambda token: {"sub": "oauth-user", "roles": ["USER"]},
    )
    monkeypatch.setattr(
        jwt_utils,
        "decode_token",
        lambda _token: pytest.fail("legacy JWT validator must not be used"),
    )

    @authenticate_decorator(object())
    def endpoint():
        return SecurityContextHolder.get_principal()

    try:
        assert endpoint(authorization="Bearer access-token") == "oauth-user"
    finally:
        oauth2_resource_server.reset()


def test_csrf_accepts_annotation_style_keys_and_enforces_cookie_rules():
    manager = init_csrf({
        "server": {
            "csrf": {
                "enabled": True,
                "token_length": 24,
                "token_ttl": 120,
                "cookie_name": "CSRF",
                "header_name": "X-CSRF",
                "secure_cookie": True,
                "same_site": "Strict",
            }
        }
    })
    assert manager.token_length == 24
    assert manager.expire_seconds == 120
    assert manager.cookie_name == "CSRF"
    assert manager.header_name == "X-CSRF"
    assert manager.secure is True
    assert manager.samesite == "strict"
    assert manager.validate_token(manager.generate_token()) is True


@dataclass
class _RestUser:
    id: int = 1
    name: str = "Alice"
    password_hash: str = "must-not-leak"
    roles: tuple = ()


class _RestRepository:
    def find_all(self, pageable=None):
        return [_RestUser()]

    def find_by_id(self, item_id):
        return _RestUser(id=item_id)

    def save(self, entity):
        return entity

    def delete_by_id(self, _item_id):
        return None


def test_secured_data_rest_requires_bearer_and_filters_sensitive_fields(monkeypatch):
    from springbootai.security.oauth2 import oauth2_resource_server
    from springbootai.security.jwt_utils import jwt_utils
    oauth2_resource_server.reset()
    monkeypatch.setattr(jwt_utils, "decode_token", lambda _token: {"sub": "user"})
    app = FastAPI()
    RepositoryRestController(
        repository=_RestRepository(),
        path="/users",
        entity_class=_RestUser,
        secured=True,
    ).register(app)
    client = TestClient(app)

    assert client.get("/users").status_code == 401
    response = client.get("/users", headers={"Authorization": "Bearer token"})
    assert response.status_code == 200
    assert "password_hash" not in response.json()["content"][0]

    response = client.post(
        "/users",
        headers={"Authorization": "Bearer token"},
        json={"name": "Mallory", "roles": ["ADMIN"]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid resource payload"


def test_oauth2_resource_server_accepts_canonical_nested_configuration():
    from springbootai.security.oauth2 import oauth2_resource_server
    oauth2_resource_server.reset()
    try:
        oauth2_resource_server.configure({
            "spring": {
                "security": {
                    "oauth2": {
                        "resourceserver": {
                            "jwt": {
                                "issuer-uri": "https://issuer.example",
                                "jwk-set-uri": "https://issuer.example/jwks",
                                "audiences": ["enterprise-api"],
                                "algorithms": ["RS256"],
                            }
                        }
                    }
                }
            }
        })
        assert oauth2_resource_server.is_configured is True
        assert oauth2_resource_server._issuer == "https://issuer.example"
        assert oauth2_resource_server._audiences == ["enterprise-api"]
        assert oauth2_resource_server._algorithms == ["RS256"]
        assert oauth2_resource_server._jwks_cache.jwk_set_uri.endswith("/jwks")
    finally:
        oauth2_resource_server.reset()


def test_data_rest_scans_application_context_public_bean_api():
    from springbootai.annotations.data import RepositoryRestResource
    from springbootai.main import SpringApplication

    @RepositoryRestResource(path="users", entity_class=_RestUser)
    class Repository(_RestRepository):
        pass

    repository = Repository()

    class Context:
        def get_bean_names(self):
            return ["userRepository"]

        def get_bean(self, name):
            assert name == "userRepository"
            return repository

    application = object.__new__(SpringApplication)
    application.application_context = Context()
    application.logger = __import__('logging').getLogger("test")
    application._register_repository_rest_resources("/api")

    assert len(application._pending_rest_controllers) == 1
    controller = application._pending_rest_controllers[0]
    assert controller.path == "/api/users"
    assert controller.secured is True


def test_seata_at_mode_invokes_registered_commit_and_rollback_callbacks():
    from springbootai.cloud.seata import SeataTransactionManager
    manager = SeataTransactionManager()
    previous_mode = manager.get_mode()
    events = []
    try:
        manager._cleanup_context()
        manager.set_mode("at")
        xid = manager.begin_transaction(name="commit")
        manager.register_branch(
            xid,
            branch_id="commit-branch",
            commit_cb=lambda *_args: events.append("commit"),
        )
        assert manager.commit_transaction(xid) is True

        xid = manager.begin_transaction(name="rollback")
        manager.register_branch(
            xid,
            branch_id="rollback-branch",
            rollback_cb=lambda *_args: events.append("rollback"),
        )
        assert manager.rollback_transaction(xid) is True
        assert events == ["commit", "rollback"]
    finally:
        manager._cleanup_context()
        manager.set_mode(previous_mode)


def test_health_and_actuator_contexts_are_isolated_per_application():
    from springbootai.web.actuator import actuator_router, configure_actuator
    from springbootai.web.health import configure_health_checks, health_router

    class WebContext:
        def __init__(self, app):
            self._app = app

        def get_app(self):
            return self._app

    class Context:
        def __init__(self, app, name):
            self.web_context = WebContext(app)
            self._config = {
                "spring": {"application": {"name": name}},
                "management": {"endpoints": {"web": {
                    "security": {"enabled": False},
                }}},
            }

        def get_config(self):
            return self._config

    apps = []
    for name in ("application-a", "application-b"):
        app = FastAPI()
        context = Context(app, name)
        configure_health_checks(context)
        configure_actuator(context)
        app.include_router(health_router, prefix="/actuator")
        app.include_router(actuator_router, prefix="/actuator")
        apps.append(app)

    first = TestClient(apps[0])
    second = TestClient(apps[1])
    assert first.get("/actuator/info").json()["application"]["name"] == "application-a"
    assert second.get("/actuator/info").json()["application"]["name"] == "application-b"
    first_env = first.get("/actuator/env").json()
    second_env = second.get("/actuator/env").json()
    assert first_env["propertySources"][0]["properties"]["spring"]["application"]["name"] == "application-a"
    assert second_env["propertySources"][0]["properties"]["spring"]["application"]["name"] == "application-b"


def test_unexposed_actuator_endpoint_returns_not_found():
    from springbootai.web.actuator import actuator_router, configure_actuator

    app = FastAPI()

    class Context:
        def __init__(self, application):
            self.web_context = SimpleNamespace(
                get_app=lambda: application)

        @staticmethod
        def get_config():
            return {"management": {"endpoints": {"web": {
                "security": {"enabled": True},
                "exposure": {"include": []},
            }}}}

    configure_actuator(Context(app))
    app.include_router(actuator_router, prefix="/actuator")
    response = TestClient(app).get("/actuator/env")
    assert response.status_code == 404
