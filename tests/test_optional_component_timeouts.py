"""可选 Nacos/RabbitMQ 组件的启动超时回归测试。

这些测试只检查连接参数，不依赖本机中间件；服务关闭时的真实行为由
有限的 socket/HTTP 超时保证，避免测试套件本身被外部服务拖慢。
"""

from types import SimpleNamespace
import threading

import pytest


def test_nacos_timeout_is_applied_to_sdk_client(monkeypatch):
    import springbootai.cloud.discovery as discovery

    class FakeNacosClient:
        instances = []

        def __init__(self, server_addr, **kwargs):
            self.default_timeout = 30
            self.instances.append(self)

        def list_naming_services(self, **kwargs):
            return {"doms": []}

    monkeypatch.setattr(discovery, "NacosClient", FakeNacosClient)
    monkeypatch.setattr(discovery.NacosDiscoveryClient, "_instance", None)
    client = discovery.NacosDiscoveryClient(
        server_addr="fake:8848", timeout=1.25
    )
    # 单例实例可能被其他测试初始化过，显式 configure 确保本测试配置生效。
    client.configure(server_addr="fake:8848", timeout=1.25)
    client.connect()

    assert client._ready is True
    assert FakeNacosClient.instances[-1].default_timeout == 1.25


def test_nacos_invalid_timeout_falls_back_to_finite_default():
    from springbootai.cloud.discovery import NacosDiscoveryClient

    assert NacosDiscoveryClient._normalize_timeout("not-a-number") == 3.0
    assert NacosDiscoveryClient._normalize_timeout(0) == 3.0
    assert NacosDiscoveryClient._normalize_timeout(float("inf")) == 3.0
    assert NacosDiscoveryClient._normalize_timeout(9999) == 60.0


def test_rabbitmq_connection_parameters_are_bounded(monkeypatch):
    import springbootai.messaging.rabbitmq as rabbitmq

    captured = {}

    class FakeConnection:
        is_closed = False

        def channel(self):
            return SimpleNamespace()

        def close(self):
            self.is_closed = True

    def fake_parameters(**kwargs):
        captured.update(kwargs)
        return kwargs

    monkeypatch.setattr(rabbitmq.pika, "ConnectionParameters", fake_parameters)
    monkeypatch.setattr(rabbitmq.pika, "BlockingConnection", lambda params: FakeConnection())
    monkeypatch.setattr(rabbitmq.RabbitMQClient, "_instance", None)

    client = rabbitmq.RabbitMQClient(
        host="offline", connection_timeout=1.5,
        connection_attempts=1, retry_delay=0,
    )
    client.connect()

    assert captured["connection_attempts"] == 1
    assert captured["retry_delay"] == 0.0
    assert captured["socket_timeout"] == 1.5
    assert captured["stack_timeout"] == 1.5
    client.close()


def test_rabbitmq_invalid_timeout_and_attempts_use_safe_defaults():
    from springbootai.messaging.rabbitmq import RabbitMQClient

    assert RabbitMQClient._normalize_timeout(0) == 5.0
    assert RabbitMQClient._normalize_timeout(float("inf")) == 5.0
    assert RabbitMQClient._normalize_timeout(9999) == 60.0
    assert RabbitMQClient._normalize_attempts(0) == 1
    assert RabbitMQClient._normalize_attempts(999) == 10


def test_rabbitmq_publisher_uses_owned_confirmed_channel(monkeypatch):
    from springbootai.messaging.rabbitmq import RabbitMQClient

    class Channel:
        is_open = True

        def __init__(self):
            self.confirmed = False
            self.calls = []

        def confirm_delivery(self):
            self.confirmed = True

        def basic_publish(self, **kwargs):
            self.calls.append((threading.get_ident(), kwargs))
            return True

    class Connection:
        is_closed = False

        def __init__(self):
            self.channel_instance = Channel()

        def channel(self):
            return self.channel_instance

        def close(self):
            self.is_closed = True

    client = object.__new__(RabbitMQClient)
    client.__init__(publish_timeout=1)
    connection = Connection()
    monkeypatch.setattr(client, "_open_connection", lambda: connection)
    caller_thread = threading.get_ident()
    try:
        client.publish("events", "orders.created", {"id": 1})
        assert connection.channel_instance.confirmed is True
        worker_thread, kwargs = connection.channel_instance.calls[0]
        assert worker_thread != caller_thread
        assert kwargs["mandatory"] is True
    finally:
        client.close()


def test_rabbitmq_failed_message_moves_to_confirmed_dlq():
    import pika
    from springbootai.messaging.rabbitmq import RabbitMQClient

    client = object.__new__(RabbitMQClient)
    client.__init__(max_delivery_attempts=1)

    class Channel:
        def __init__(self):
            self.declared = []
            self.published = []
            self.acked = []
            self.nacked = []

        def queue_declare(self, **kwargs):
            self.declared.append(kwargs)

        def basic_publish(self, **kwargs):
            self.published.append(kwargs)
            return True

        def basic_ack(self, **kwargs):
            self.acked.append(kwargs)

        def basic_nack(self, **kwargs):
            self.nacked.append(kwargs)

    channel = Channel()
    handler = client._create_message_handler(
        lambda _message: (_ for _ in ()).throw(RuntimeError("failed")),
        queue_name="orders",
    )
    handler(
        channel,
        SimpleNamespace(delivery_tag=7, exchange="", routing_key="orders"),
        pika.BasicProperties(headers={}),
        b'{"id": 1}',
    )

    assert channel.declared[0]["queue"] == "orders.DLQ"
    assert channel.published[0]["routing_key"] == "orders.DLQ"
    assert channel.published[0]["mandatory"] is True
    assert channel.acked == [{"delivery_tag": 7}]
    assert channel.nacked == []


def test_config_loader_exposes_optional_component_timeout_overrides(tmp_path, monkeypatch):
    from springbootai.config.config_loader import ConfigLoader

    monkeypatch.setenv("NACOS_TIMEOUT", "1.2")
    monkeypatch.setenv("RABBITMQ_CONNECTION_TIMEOUT", "2.5")
    monkeypatch.setenv("RABBITMQ_SOCKET_TIMEOUT", "2")
    monkeypatch.setenv("RABBITMQ_STACK_TIMEOUT", "2")
    monkeypatch.setenv("RABBITMQ_CONNECTION_ATTEMPTS", "1")
    config = tmp_path / "application.yml"
    config.write_text("discovery:\n  enabled: true\nrabbitmq:\n  enabled: true\n", encoding="utf-8")

    loader = ConfigLoader(config_path=str(config))

    assert loader.get("discovery.timeout") == 1.2
    assert loader.get("rabbitmq.connection_timeout") == 2.5
    assert loader.get("rabbitmq.socket_timeout") == 2.0
    assert loader.get("rabbitmq.stack_timeout") == 2.0
    assert loader.get("rabbitmq.connection_attempts") == 1
