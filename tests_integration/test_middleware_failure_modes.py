"""Failure-mode checks executed while CI deliberately stops one dependency."""

import os

import pytest


pytestmark = pytest.mark.integration

if os.getenv("RUN_FAILURE_INTEGRATION_TESTS") != "1":
    pytest.skip("failure-mode integration environment is not active", allow_module_level=True)


def test_redis_outage_fails_closed():
    from spring.utils.redis_client import RedisClient

    client = RedisClient(host="127.0.0.1", port=6379, db=15, timeout=1)
    with pytest.raises(Exception):
        client.connect(strict=True)


def test_seata_bridge_outage_fails_closed():
    from spring.cloud.seata_bridge import SeataBridgeClient, SeataBridgeError

    client = SeataBridgeClient(
        "http://127.0.0.1:18091",
        os.getenv("SEATA_BRIDGE_TOKEN", "springpy-integration-secret"),
        timeout_s=1,
    )
    with pytest.raises(SeataBridgeError):
        client.health()
