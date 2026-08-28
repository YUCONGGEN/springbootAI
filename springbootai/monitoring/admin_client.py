"""Spring Boot Admin Server registration client."""
import inspect
import math
from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any, Dict, Optional
from urllib.parse import quote, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from springbootai.logging.context import outbound_request_id


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _http_url(value: str, name: str) -> str:
    try:
        parsed = urlsplit(value)
        parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a valid HTTP URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{name} must use http or https and include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{name} must not contain embedded credentials")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{name} must not contain a query or fragment")
    return value.rstrip("/")


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if math.isfinite(parsed) and parsed > 0 else default


def _bounded_retries(value: Any, default: int = 2) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(0, min(parsed, 10))


@dataclass
class AdminClientProperties:
    enabled: bool = False
    url: str = "http://127.0.0.1:1111"
    name: str = "springbootai"
    service_url: str = ""
    management_url: str = ""
    health_url: str = ""
    timeout_seconds: float = 5.0
    max_retries: int = 2
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "AdminClientProperties":
        spring = config.get("spring", {}) if isinstance(config, dict) else {}
        boot = spring.get("boot", {}) if isinstance(spring, dict) else {}
        admin = boot.get("admin", {}) if isinstance(boot, dict) else {}
        client = admin.get("client", {}) if isinstance(admin, dict) else {}
        if not isinstance(client, dict):
            client = {}
        service_url = str(client.get("service-url", client.get("service_url", ""))).rstrip("/")
        management_url = str(client.get("management-url", client.get("management_url", service_url + "/actuator" if service_url else ""))).rstrip("/")
        health_url = str(client.get("health-url", client.get("health_url", management_url + "/health" if management_url else ""))).rstrip("/")
        return cls(
            enabled=_as_bool(client.get("enabled", False)),
            url=str(client.get("url", "http://127.0.0.1:1111")).rstrip("/"),
            name=str(client.get("name", "springbootai")),
            service_url=service_url,
            management_url=management_url,
            health_url=health_url,
            timeout_seconds=_positive_float(
                client.get("timeout-seconds", client.get("timeout_seconds", 5)),
                5.0,
            ),
            max_retries=_bounded_retries(
                client.get("max-retries", client.get("max_retries", 2))),
            metadata=(
                dict(client.get("metadata", {}))
                if isinstance(client.get("metadata", {}), Mapping) else {}
            ),
        )


class SpringBootAdminClient:
    """Registers this application with a Spring Boot Admin Server."""

    def __init__(self, properties: AdminClientProperties, session: Optional[requests.Session] = None):
        self.properties = properties
        self._session = session or requests.Session()
        self._owns_session = session is None
        self._closed = False
        self.instance_id: Optional[str] = None
        try:
            self.timeout_seconds = float(self.properties.timeout_seconds)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                "Spring Boot Admin timeout_seconds must be greater than zero"
            ) from exc
        if (not math.isfinite(self.timeout_seconds)
                or self.timeout_seconds <= 0):
            raise ValueError("Spring Boot Admin timeout_seconds must be greater than zero")
        if self._owns_session:
            retries = _bounded_retries(self.properties.max_retries)
            adapter = HTTPAdapter(max_retries=Retry(
                total=retries,
                connect=retries,
                read=retries,
                status=retries,
                backoff_factor=0.2,
                status_forcelist=(429, 502, 503, 504),
                allowed_methods=frozenset({"HEAD", "GET", "DELETE", "OPTIONS"}),
                respect_retry_after_header=True,
                raise_on_status=False,
            ))
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)

    def close(self) -> None:
        if not self._closed and self._owns_session:
            self._session.close()
        self._closed = True

    def __enter__(self) -> "SpringBootAdminClient":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def _request(self, method: str, url: str, **kwargs):
        """Call requests-compatible sessions without following redirects.

        Real ``requests.Session`` methods accept ``allow_redirects`` through
        ``**kwargs``.  A few lightweight user/test adapters expose a narrower
        signature; keep those adapters compatible while making the security
        policy explicit for every requests implementation that supports it.
        """
        caller = getattr(self._session, method)
        supports_redirect_option = True
        supports_headers = True
        try:
            parameters = tuple(inspect.signature(caller).parameters.values())
            has_var_kwargs = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters
            )
            supports_redirect_option = any(
                has_var_kwargs or parameter.name == "allow_redirects"
                for parameter in parameters
            )
            supports_headers = any(
                has_var_kwargs or parameter.name == "headers"
                for parameter in parameters
            )
        except (TypeError, ValueError):
            pass
        if supports_redirect_option:
            kwargs["allow_redirects"] = False
        if supports_headers:
            headers = dict(kwargs.pop("headers", {}) or {})
            headers.setdefault("X-Request-ID", outbound_request_id())
            kwargs["headers"] = headers
        return caller(url, **kwargs)

    @staticmethod
    def _reject_redirect(response) -> None:
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int) and 300 <= status_code < 400:
            raise requests.HTTPError(
                "Spring Boot Admin redirects are not allowed",
                response=response,
            )

    @staticmethod
    def _response_instance_id(response) -> Optional[str]:
        """Read the registered ID from Location or Spring Admin's JSON body."""
        headers = getattr(response, "headers", {}) or {}
        location = str(headers.get("Location", "") or "").rstrip("/")
        if location:
            return location.rsplit("/", 1)[-1] or None

        try:
            payload = response.json()
        except (AttributeError, TypeError, ValueError):
            return None
        if not isinstance(payload, Mapping):
            return None
        instance_id = payload.get("id")
        # Some Jackson configurations serialize InstanceId as {"value": ...}.
        if isinstance(instance_id, Mapping):
            instance_id = instance_id.get("value")
        if isinstance(instance_id, bool) or instance_id is None:
            return None
        candidate = str(instance_id).strip()
        return candidate or None

    def register(self) -> Optional[str]:
        if self._closed:
            raise RuntimeError("Spring Boot Admin client is closed")
        if not self.properties.enabled:
            return None
        if not self.properties.service_url or not self.properties.management_url or not self.properties.health_url:
            raise ValueError("springbootai.boot.admin.client requires service-url, management-url and health-url")
        admin_url = _http_url(self.properties.url, "admin client url")
        service_url = _http_url(self.properties.service_url, "service-url")
        management_url = _http_url(self.properties.management_url, "management-url")
        health_url = _http_url(self.properties.health_url, "health-url")
        response = None
        try:
            response = self._request(
                "post",
                f"{admin_url}/instances",
                json={
                    "name": self.properties.name,
                    "serviceUrl": service_url,
                    "managementUrl": management_url,
                    "healthUrl": health_url,
                    "metadata": self.properties.metadata,
                },
                timeout=self.timeout_seconds,
            )
            self._reject_redirect(response)
            response.raise_for_status()
            self.instance_id = self._response_instance_id(response)
            return self.instance_id
        finally:
            closer = getattr(response, "close", None)
            if callable(closer):
                closer()

    def deregister(self) -> None:
        if self._closed:
            raise RuntimeError("Spring Boot Admin client is closed")
        if not self.instance_id:
            return
        response = None
        try:
            admin_url = _http_url(self.properties.url, "admin client url")
            instance_id = quote(str(self.instance_id), safe="")
            response = self._request(
                "delete",
                f"{admin_url}/instances/{instance_id}",
                timeout=self.timeout_seconds,
            )
            self._reject_redirect(response)
            response.raise_for_status()
            # Only forget the ID after the server accepted deregistration.
            # On transport/HTTP failure it remains available for a retry.
            self.instance_id = None
        finally:
            closer = getattr(response, "close", None)
            if callable(closer):
                closer()
