"""HTTP client for the official Apache Seata Java bridge."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest


class SeataBridgeError(RuntimeError):
    """Raised when the Seata bridge rejects or cannot complete an operation."""


class SeataBridgeClient:
    """Small fail-closed client used by ``SeataTransactionManager``.

    The bridge embeds the official Java TM/RM client. Python never attempts to
    implement Seata's private TCP protocol itself.
    """

    _MAX_RESPONSE_BYTES = 1024 * 1024

    def __init__(self, base_url: str, token: str, timeout_s: float = 5.0):
        normalized_url = str(base_url or "").strip().rstrip("/")
        parsed = urlparse.urlparse(normalized_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("seata.bridge_url must be an absolute HTTP(S) URL")
        if not token:
            raise ValueError("seata.bridge_token is required in distributed mode")
        if timeout_s <= 0:
            raise ValueError("seata.bridge_timeout_s must be greater than zero")
        self.base_url = normalized_url
        self.token = token
        self.timeout_s = float(timeout_s)

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        authenticated: bool = True,
    ) -> Dict[str, Any]:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if authenticated:
            headers["X-Seata-Bridge-Token"] = self.token

        req = urlrequest.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlrequest.urlopen(req, timeout=self.timeout_s) as response:
                raw = response.read(self._MAX_RESPONSE_BYTES + 1)
                if len(raw) > self._MAX_RESPONSE_BYTES:
                    raise SeataBridgeError("Seata bridge response exceeded 1 MiB")
        except urlerror.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            raise SeataBridgeError(
                f"Seata bridge returned HTTP {exc.code}: {detail}"
            ) from exc
        except (urlerror.URLError, TimeoutError, OSError) as exc:
            raise SeataBridgeError(f"Seata bridge request failed: {exc}") from exc

        if not raw:
            return {}
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SeataBridgeError("Seata bridge returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise SeataBridgeError("Seata bridge returned a non-object JSON response")
        return result

    def health(self) -> Dict[str, Any]:
        return self._request("GET", "/health", authenticated=False)

    def begin(
        self,
        *,
        timeout_ms: int,
        name: str,
        application_id: str,
        transaction_group: str,
    ) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/transactions",
            {
                "timeoutMs": int(timeout_ms),
                "name": name,
                "applicationId": application_id,
                "transactionGroup": transaction_group,
            },
        )

    def register_branch(
        self,
        xid: str,
        *,
        branch_id: str,
        resource_id: str,
        callback_url: str,
        service_name: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        encoded_xid = urlparse.quote(xid, safe="")
        return self._request(
            "POST",
            f"/api/v1/transactions/{encoded_xid}/branches",
            {
                "branchId": branch_id,
                "resourceId": resource_id,
                "callbackUrl": callback_url,
                "serviceName": service_name,
                "metadata": metadata or {},
            },
        )

    def commit(self, xid: str) -> Dict[str, Any]:
        encoded_xid = urlparse.quote(xid, safe="")
        return self._request(
            "POST", f"/api/v1/transactions/{encoded_xid}/commit", {}
        )

    def rollback(self, xid: str) -> Dict[str, Any]:
        encoded_xid = urlparse.quote(xid, safe="")
        return self._request(
            "POST", f"/api/v1/transactions/{encoded_xid}/rollback", {}
        )

    def status(self, xid: str) -> Dict[str, Any]:
        encoded_xid = urlparse.quote(xid, safe="")
        return self._request("GET", f"/api/v1/transactions/{encoded_xid}")
