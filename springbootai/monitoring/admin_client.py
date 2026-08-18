"""Spring Boot Admin Server registration client."""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import requests


@dataclass
class AdminClientProperties:
    enabled: bool = False
    url: str = "http://127.0.0.1:1111"
    name: str = "springbootai"
    service_url: str = ""
    management_url: str = ""
    health_url: str = ""
    timeout_seconds: float = 5.0
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
            enabled=bool(client.get("enabled", False)),
            url=str(client.get("url", "http://127.0.0.1:1111")).rstrip("/"),
            name=str(client.get("name", "springbootai")),
            service_url=service_url,
            management_url=management_url,
            health_url=health_url,
            timeout_seconds=float(client.get("timeout-seconds", client.get("timeout_seconds", 5))),
            metadata=dict(client.get("metadata", {}) or {}),
        )


class SpringBootAdminClient:
    """Registers this application with a Spring Boot Admin Server."""

    def __init__(self, properties: AdminClientProperties, session: Optional[requests.Session] = None):
        self.properties = properties
        self._session = session or requests.Session()
        self.instance_id: Optional[str] = None

    def register(self) -> Optional[str]:
        if not self.properties.enabled:
            return None
        if not self.properties.service_url or not self.properties.management_url or not self.properties.health_url:
            raise ValueError("springbootai.boot.admin.client requires service-url, management-url and health-url")
        response = self._session.post(
            f"{self.properties.url}/instances",
            json={
                "name": self.properties.name,
                "serviceUrl": self.properties.service_url,
                "managementUrl": self.properties.management_url,
                "healthUrl": self.properties.health_url,
                "metadata": self.properties.metadata,
            },
            timeout=self.properties.timeout_seconds,
        )
        response.raise_for_status()
        location = response.headers.get("Location", "").rstrip("/")
        self.instance_id = location.rsplit("/", 1)[-1] if location else None
        return self.instance_id

    def deregister(self) -> None:
        if not self.instance_id:
            return
        try:
            self._session.delete(f"{self.properties.url}/instances/{self.instance_id}", timeout=self.properties.timeout_seconds).raise_for_status()
        finally:
            self.instance_id = None