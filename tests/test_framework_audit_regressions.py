"""Reproduce request binding, identity isolation and transaction boundary bugs."""
from __future__ import annotations

import asyncio
import sqlite3
from typing import Dict, Optional

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel

from springbootai.annotations.core import Cacheable, PathVariable, RequestBody, Transactional
from springbootai.context.bean_definition import BeanDefinition
from springbootai.context.bean_factory import BeanFactory
from springbootai.orm.pymybatis import build_session_factory
from springbootai.security.security_aop import AuthenticationError, authenticate_decorator
from springbootai.security.security_context import SecurityContext, SecurityContextHolder
from springbootai.web.web_context import WebApplicationContext


def test_child_tasks_setting_authentication_do_not_change_parent_or_siblings():
    async def scenario():
        token = SecurityContextHolder.set_context(SecurityContext())
        try:
            SecurityContextHolder.set_authentication({"principal": "parent"})

            async def child(name):
                SecurityContextHolder.set_authentication({
                    "principal": name, "roles": [name], "permissions": [name],
                })
                await asyncio.sleep(0)
                return (
                    SecurityContextHolder.get_principal(),
                    SecurityContextHolder.get_roles(),
                    SecurityContextHolder.get_permissions(),
                )

            children = await asyncio.gather(child("alice"), child("bob"))
            return children, SecurityContextHolder.get_principal()
        finally:
            SecurityContextHolder.reset_context(token)

    children, parent = asyncio.run(scenario())
    assert children == [("alice", ["alice"], ["alice"]), ("bob", ["bob"], ["bob"])]
    assert parent == "parent"


def test_authentication_does_not_alias_caller_owned_role_lists():
    roles = ["USER"]
    permissions = ["read"]
    authentication = {"principal": "alice", "roles": roles, "permissions": permissions}
    token = SecurityContextHolder.set_context(SecurityContext())
    try:
        SecurityContextHolder.set_authentication(authentication)
        authentication["principal"] = "bob"
        roles.append("ADMIN")
        permissions.append("write")
        assert SecurityContextHolder.get_authentication()["principal"] == "alice"
        assert SecurityContextHolder.get_roles() == ["USER"]
        assert SecurityContextHolder.get_permissions() == ["read"]
    finally:
        SecurityContextHolder.reset_context(token)


def _client(controller, method, path, http_method="GET"):
    web = WebApplicationContext(object())
    endpoint = web._create_endpoint(controller, method, path)
    web.fastapi_app.add_api_route(path, endpoint, methods=[http_method])
    return TestClient(web.fastapi_app)


def test_path_variable_alias_uses_the_url_placeholder():
    class Controller:
        def item(self, item_id=PathVariable(name="id")):
            return {"id": item_id}

    Controller.item.__annotations__ = {"item_id": int}
    with _client(Controller(), Controller.item, "/items/{id}") as client:
        response = client.get("/items/42")
        assert response.status_code == 200
        assert response.json()["data"] == {"id": 42}
        operation = client.get("/openapi.json").json()["paths"]["/items/{id}"]["get"]
        assert operation["parameters"][0]["name"] == "id"
        assert client.get("/items/invalid").status_code == 422


class _AuditPayload(BaseModel):
    count: int


@pytest.mark.parametrize("annotation", [
    dict, Dict[str, int], Optional[dict], dict | None,
    dict[str, int], Optional[dict[str, int]],
])
def test_nullable_dictionary_parameters_bind_json_bodies(annotation):
    class Controller:
        def create(self, payload=None):
            return payload or {}

    Controller.create.__annotations__ = {"payload": annotation}
    with _client(Controller(), Controller.create, "/items", "POST") as client:
        response = client.post("/items", json={"count": 7})
        assert response.status_code == 200
        assert response.json()["data"] == {"count": 7}
        assert client.post("/items").json()["data"] == {}
        assert client.post("/items", json=["invalid"]).status_code == 422
        operation = client.get("/openapi.json").json()["paths"]["/items"]["post"]
        assert "requestBody" in operation
        assert not any(item["name"] == "payload" for item in operation.get("parameters", []))


def test_controller_resolves_postponed_body_annotations_in_its_own_module():
    class Controller:
        def create(self, payload: _AuditPayload = RequestBody()):
            return {"count": payload.count}

    with _client(Controller(), Controller.create, "/items", "POST") as client:
        response = client.post("/items", json={"count": "7"})
        assert response.status_code == 200
        assert response.json()["data"] == {"count": 7}
        assert client.post("/items", json={"count": "invalid"}).status_code == 422
        assert client.get("/openapi.json").status_code == 200


def test_managed_controller_resolves_annotations_through_aop_wrappers():
    class Controller:
        @Cacheable(value="audit-payload")
        def create(self, payload: _AuditPayload = RequestBody()):
            return {"count": payload.count}

    factory = BeanFactory()
    factory.register_bean_definition("controller", BeanDefinition(Controller, "controller"))
    controller = factory.get_bean("controller")
    with _client(controller, controller.create, "/items", "POST") as client:
        response = client.post("/items", json={"count": 8})
        assert response.status_code == 200
        assert response.json()["data"] == {"count": 8}


@pytest.mark.parametrize("asynchronous", [False, True])
def test_exception_advice_can_return_a_native_response(asynchronous):
    class Controller:
        def fail(self):
            raise ValueError("application rejection")

    def handle(_error):
        return JSONResponse({"rejected": True}, status_code=409, headers={"X-Advice": "yes"})

    async def async_handle(error):
        return handle(error)

    web = WebApplicationContext(object())
    web._exception_handlers[ValueError] = async_handle if asynchronous else handle
    endpoint = web._create_endpoint(Controller(), Controller.fail, "/fail")
    web.fastapi_app.add_api_route("/fail", endpoint, methods=["GET"])
    with TestClient(web.fastapi_app) as client:
        response = client.get("/fail")
        assert response.status_code == 409
        assert response.json() == {"rejected": True}
        assert response.headers["x-advice"] == "yes"


@pytest.mark.parametrize("streaming", [False, True])
def test_controller_preserves_native_response_body_status_and_headers(streaming):
    class Controller:
        def download(self):
            if streaming:
                return StreamingResponse(iter([b"event: done\n", b"data: ok\n\n"]),
                                         media_type="text/event-stream", headers={"X-Custom": "yes"})
            return JSONResponse({"accepted": True}, status_code=202, headers={"X-Custom": "yes"})

    with _client(Controller(), Controller.download, "/download") as client:
        response = client.get("/download")
        assert response.headers["x-custom"] == "yes"
        if streaming:
            assert response.status_code == 200
            assert response.content == b"event: done\ndata: ok\n\n"
            assert response.headers["content-type"].startswith("text/event-stream")
        else:
            assert response.status_code == 202
            assert response.json() == {"accepted": True}


def test_controller_preserves_http_exception_status_detail_and_headers():
    class Controller:
        def reject(self):
            raise HTTPException(429, detail={"reason": "quota"}, headers={"Retry-After": "10"})

    with _client(Controller(), Controller.reject, "/reject") as client:
        response = client.get("/reject")
        assert response.status_code == 429
        assert response.json() == {"detail": {"reason": "quota"}}
        assert response.headers["retry-after"] == "10"


def test_string_jwt_authorities_are_matched_as_whole_values(monkeypatch):
    from springbootai.security.jwt_utils import jwt_utils
    from springbootai.security.oauth2 import oauth2_resource_server
    monkeypatch.setattr(oauth2_resource_server, "_configured", False)
    monkeypatch.setattr(jwt_utils, "decode_token", lambda _token: {
        "sub": "alice", "roles": "SUPERADMIN", "permissions": "user:read_all",
    })

    @authenticate_decorator(object())
    def check():
        return (SecurityContextHolder.has_role("ADMIN"),
                SecurityContextHolder.has_role("SUPERADMIN"),
                SecurityContextHolder.has_permission("user:read"),
                SecurityContextHolder.has_permission("user:read_all"))

    assert check(authorization="Bearer signed-token") == (False, True, False, True)


@pytest.mark.parametrize("claims", [{"roles": {"ADMIN": True}}, {"permissions": [42]}])
def test_malformed_jwt_authorities_fail_authentication(monkeypatch, claims):
    from springbootai.security.jwt_utils import jwt_utils
    from springbootai.security.oauth2 import oauth2_resource_server
    monkeypatch.setattr(oauth2_resource_server, "_configured", False)
    monkeypatch.setattr(jwt_utils, "decode_token", lambda _token: {"sub": "alice", **claims})
    called = []

    @authenticate_decorator(object())
    def check():
        called.append(True)

    with pytest.raises(AuthenticationError):
        check(authorization="Bearer signed-token")
    assert called == []


@pytest.fixture
def session_factory():
    factory = build_session_factory({
        "datasource": {"driver": "sqlite", "database": ":memory:"},
        "pool": {"min_size": 1, "max_size": 1},
        "security": {"block_ddl": False, "sql_injection_detection": False},
    })
    try:
        yield factory
    finally:
        factory.close()


def test_failed_commit_rolls_back_before_the_same_session_is_reused(session_factory):
    with session_factory.open_session() as session:
        connection = session.get_connection()
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("CREATE TABLE parents (id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE children (parent_id INTEGER REFERENCES parents(id) "
            "DEFERRABLE INITIALLY DEFERRED)"
        )
        connection.commit()
        with pytest.raises(sqlite3.IntegrityError), session.transaction():
            connection.execute("INSERT INTO children VALUES (999)")

        assert not connection.in_transaction
        assert not session.in_transaction
        assert connection.execute("SELECT COUNT(*) FROM children").fetchone()[0] == 0
        with session.transaction():
            connection.execute("INSERT INTO parents VALUES (1)")
            connection.execute("INSERT INTO children VALUES (1)")
        assert [tuple(row) for row in connection.execute("SELECT parent_id FROM children")] == [(1,)]


class _BrokenRollbackConnection:
    def __init__(self, connection):
        self.connection = connection
        self.closed = False

    def execute(self, sql):
        return self.connection.execute(sql)

    def cursor(self):
        return self.connection.cursor()

    def commit(self):
        raise ValueError("commit failed")

    def rollback(self):
        raise RuntimeError("rollback failed")

    def close(self):
        self.closed = True
        self.connection.close()


def _break_connection(session):
    connection = _BrokenRollbackConnection(session.get_connection())
    session._current_connection = connection
    session._current_pooled_conn.connection = connection
    return connection


def test_failed_commit_and_rollback_discard_connection_without_masking_commit_error(session_factory, monkeypatch):
    with session_factory.open_session() as session:
        connection = _break_connection(session)
        monkeypatch.setattr(session, "_set_transaction_isolation", lambda *_args: None)
        with pytest.raises(ValueError, match="commit failed"), session.transaction():
            pass
        assert connection.closed
        assert session._current_connection is None
        assert session_factory.connection_pool.get_pool_stats()["active_connections"] == 0


def test_session_close_releases_connection_even_when_rollback_fails(session_factory):
    session = session_factory.open_session()
    connection = _break_connection(session)
    connection.execute("BEGIN")
    session._transaction_depth = 1
    session.close()
    assert connection.closed
    assert not session.in_transaction
    assert session_factory.connection_pool.get_pool_stats()["active_connections"] == 0
    session.close()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("policy", [
    {"rollback_for": [ValueError]},
    {"no_rollback_for": [BaseException]},
])
def test_transactional_cancellation_always_rolls_back(session_factory, asynchronous, policy, monkeypatch):
    with session_factory.open_session() as session:
        connection = session.get_connection()
        connection.execute("CREATE TABLE writes (id INTEGER PRIMARY KEY)")
        connection.commit()

    factory = BeanFactory()
    monkeypatch.setattr(factory, "get_bean", lambda _name: session_factory)

    def write_and_cancel():
        from springbootai.orm.mybatis_integration import get_transaction_session
        get_transaction_session().get_connection().execute("INSERT INTO writes VALUES (1)")
        raise asyncio.CancelledError()

    def work():
        write_and_cancel()

    async def async_work():
        write_and_cancel()

    wrapped = factory._wrap_transactional(object(), async_work if asynchronous else work, Transactional(**policy))
    with pytest.raises(asyncio.CancelledError):
        if asynchronous:
            asyncio.run(wrapped())
        else:
            wrapped()

    with session_factory.open_session() as session:
        assert session.get_connection().execute("SELECT COUNT(*) FROM writes").fetchone()[0] == 0
