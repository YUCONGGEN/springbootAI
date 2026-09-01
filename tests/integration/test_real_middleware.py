import os

import pytest


pytestmark = pytest.mark.integration

if os.getenv("RUN_INTEGRATION_TESTS") != "1":
    pytest.skip("set RUN_INTEGRATION_TESTS=1 with docker-compose.integration.yml", allow_module_level=True)


def test_mysql_through_springpy_connection_pool():
    from springbootai.orm.pymybatis.pool.connection_pool import MySQLConnectionPool

    pool = MySQLConnectionPool({
        "host": "127.0.0.1",
        "port": 3306,
        "username": "root",
        "password": "root123",
        "database": "springpy",
        "min_size": 0,
        "max_size": 2,
        "wait_timeout": 3,
        "leak_detection_enabled": False,
        "circuit_breaker_enabled": False,
    })
    connection = pool.get_connection()
    try:
        cursor = connection.get_connection().cursor()
        cursor.execute("SELECT 1 AS value")
        assert cursor.fetchone()["value"] == 1
        cursor.close()
    finally:
        pool.return_connection(connection)
        pool.close()


def test_redis_through_springpy_client():
    from springbootai.utils.redis_client import RedisClient

    client = RedisClient(host="127.0.0.1", port=6379, db=15)
    client.connect(strict=True)
    raw = client.get_client()
    raw.set("springpy:integration", "ok", ex=30)
    assert raw.get("springpy:integration") == "ok"
    raw.delete("springpy:integration")
    raw.close()


def test_rabbitmq_publish_and_consume_through_springpy_client():
    from springbootai.messaging.rabbitmq import init_rabbitmq, rabbitmq_client

    init_rabbitmq({
        "host": "127.0.0.1",
        "port": 5672,
        "username": "admin",
        "password": "admin123",
        "virtual_host": "/",
    })
    queue = "springpy.integration"
    try:
        rabbitmq_client.declare_queue(queue, durable=False, auto_delete=True)
        rabbitmq_client.publish_to_queue(queue, {"status": "ok"}, persistent=False)
        method, _, body = rabbitmq_client.get_channel().basic_get(queue, auto_ack=True)
        assert method is not None
        assert b'"status": "ok"' in body
    finally:
        if rabbitmq_client._channel is not None:
            rabbitmq_client._channel.queue_delete(queue=queue)
        rabbitmq_client.close()


def test_nacos_real_readiness_endpoint():
    import requests

    response = requests.get(
        "http://127.0.0.1:8848/nacos/v1/console/health/readiness",
        timeout=5,
    )
    response.raise_for_status()
    assert response.text.strip().upper() == "OK"


def test_kafka_publish_through_springpy_client():
    from springbootai.messaging.kafka import KafkaClient

    KafkaClient._instance = None
    client = KafkaClient(bootstrap_servers="127.0.0.1:9092")
    try:
        metadata = client.send_and_wait(
            "springpy.integration", {"status": "ok"}, timeout=15
        )
        assert metadata.topic == "springpy.integration"
        assert metadata.offset >= 0
    finally:
        client.close()
        KafkaClient._instance = None
