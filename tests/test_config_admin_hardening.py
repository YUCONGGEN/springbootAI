"""Regression tests for config-center and Spring Boot Admin reliability."""

import json
import re

import pytest
import requests

from springbootai.cloud.config_center import (
    ConfigCenterClient, ConfigCenterError, config_client, init_config_center,
)
from springbootai.monitoring.admin_client import (
    AdminClientProperties,
    SpringBootAdminClient,
)


@pytest.fixture(autouse=True)
def _reset_config_client():
    config_client.close()
    config_client._configured = False
    yield
    config_client.close()
    config_client._configured = False


def _file_config(path, *, name="orders", profile="prod"):
    return {
        "spring": {
            "application": {"name": name},
            "profiles": {"active": profile},
            "cloud": {
                "config": {
                    "enabled": True,
                    "backend": "file",
                    "file": {"path": str(path)},
                },
            },
        },
    }


def test_config_initialization_establishes_refresh_baseline(tmp_path):
    (tmp_path / "orders-prod.yml").write_text(
        "feature:\n  enabled: true\n", encoding="utf-8",
    )

    init_config_center(_file_config(tmp_path))
    assert config_client.get_config() == {"feature.enabled": True}
    assert config_client._cached_hash

    listener_calls = []
    config_client.register_change_listener(
        lambda old, new: listener_calls.append((old, new)),
    )
    assert config_client.refresh() == {}
    assert listener_calls == []


class _ConfigResponse:
    status_code = 200

    def __init__(self, values):
        self.payload = json.dumps({
            "propertySources": [{"source": values}],
        }).encode("utf-8")
        self.headers = {"Content-Length": str(len(self.payload))}
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=64 * 1024):
        yield self.payload

    def close(self):
        self.closed = True


def test_config_refresh_network_failure_retains_last_known_good(monkeypatch):
    response = _ConfigResponse({"feature.enabled": True, "limit": 5})
    request_options = []

    def get_config(*args, **kwargs):
        request_options.append(kwargs)
        if len(request_options) == 1:
            return response
        raise requests.ConnectionError("config server offline")

    monkeypatch.setattr("requests.get", get_config)
    init_config_center({
        "spring": {"cloud": {"config": {
            "enabled": True,
            "uri": "https://config.test",
            "retry": {"max-attempts": 1},
        }}},
    })
    baseline = config_client.get_config()
    listener_calls = []
    config_client.register_change_listener(
        lambda old, new: listener_calls.append((old, new)),
    )

    assert config_client.refresh() == {}
    assert config_client.get_config() == baseline
    assert listener_calls == []
    assert response.closed is True
    assert all(call["allow_redirects"] is False for call in request_options)


def test_config_file_non_string_keys_are_stable(tmp_path):
    (tmp_path / "orders-prod.yml").write_text(
        "1:\n  nested: one\na: two\n", encoding="utf-8",
    )

    init_config_center(_file_config(tmp_path))
    assert config_client.get_config() == {"1.nested": "one", "a": "two"}
    assert config_client.refresh() == {}


def test_config_rejects_colliding_normalized_keys():
    with pytest.raises(ConfigCenterError, match="Duplicate normalized"):
        ConfigCenterClient._flatten({1: "numeric", "1": "string"})


class _AdminResponse:
    def __init__(self, *, status_code=201, payload=None, headers=None,
                 error=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.error = error
        self.closed = False

    def raise_for_status(self):
        if self.error is not None:
            raise self.error

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON response")
        return self._payload

    def close(self):
        self.closed = True


class _AdminSession:
    def __init__(self, post_response, delete_response):
        self.post_response = post_response
        self.delete_response = delete_response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.post_response

    def delete(self, url, **kwargs):
        self.calls.append(("DELETE", url, kwargs))
        return self.delete_response


def _admin_properties():
    return AdminClientProperties(
        enabled=True,
        url="https://admin.test",
        name="orders",
        service_url="https://orders.test",
        management_url="https://orders.test/actuator",
        health_url="https://orders.test/actuator/health",
    )


def test_admin_uses_json_instance_id_and_disables_redirects():
    registered = _AdminResponse(payload={"id": "json-instance-id"})
    deregistered = _AdminResponse(status_code=204)
    session = _AdminSession(registered, deregistered)
    client = SpringBootAdminClient(_admin_properties(), session=session)

    assert client.register() == "json-instance-id"
    assert registered.closed is True
    assert session.calls[0][2]["allow_redirects"] is False
    assert re.fullmatch(
        r"[0-9a-f]{32}", session.calls[0][2]["headers"]["X-Request-ID"])

    client.deregister()
    assert client.instance_id is None
    assert deregistered.closed is True
    assert session.calls[1][2]["allow_redirects"] is False
    assert session.calls[1][1].endswith("/instances/json-instance-id")


def test_admin_deregister_failure_retains_instance_id_for_retry():
    failed = _AdminResponse(
        status_code=503,
        error=requests.HTTPError("admin unavailable"),
    )
    session = _AdminSession(_AdminResponse(payload={"id": "unused"}), failed)
    client = SpringBootAdminClient(_admin_properties(), session=session)
    client.instance_id = "retry-me"

    with pytest.raises(requests.HTTPError, match="admin unavailable"):
        client.deregister()

    assert client.instance_id == "retry-me"
    assert failed.closed is True
    assert session.calls[0][2]["allow_redirects"] is False
