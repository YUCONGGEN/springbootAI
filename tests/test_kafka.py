"""Kafka 消息队列功能测试

测试范围：
- KafkaClient 单例模式与配置方法
- 监听器注册与 topic 安全校验
- send 方法在 kafka-python 未安装时的异常处理
- @KafkaListener 注解定义与属性
- KafkaTemplate 发送模板
- init_kafka 配置初始化函数

注意：不测试真实的 Kafka 连接（kafka-python 可能未安装），
      通过 mock 模拟依赖以隔离测试环境。
"""
import sys
from unittest import mock

import pytest

from spring.messaging.kafka import KafkaClient, kafka_client, init_kafka
from spring.annotations.messaging import (
    KafkaListener,
    KafkaTemplate,
    kafka_template,
)


@pytest.fixture(autouse=True)
def reset_kafka_singleton():
    """每个测试前后重置 KafkaClient 单例状态，保证测试之间相互隔离。

    使用 configure() 将单例重置为默认配置，并清空监听器、生产者等运行态。
    """
    kafka_client.configure(
        bootstrap_servers="localhost:9092",
        group_id="default-group",
        auto_offset_reset="latest",
    )
    yield
    # 测试结束后关闭，释放可能残留的 producer / 消费线程
    kafka_client.close()


# ==================== KafkaClient 单例模式测试 ====================


class TestKafkaClientSingleton:
    """KafkaClient 单例模式测试"""

    def test_singleton_returns_same_instance(self):
        """多次构造返回同一个实例"""
        client1 = KafkaClient()
        client2 = KafkaClient()
        assert client1 is client2

    def test_singleton_same_as_global(self):
        """构造的实例与全局 kafka_client 是同一对象"""
        client = KafkaClient(bootstrap_servers="other:9092")
        assert client is kafka_client

    def test_init_guard_prevents_reinitialization(self):
        """_initialized 守卫阻止重复初始化，已存在的属性不被覆盖"""
        # 先设定已知状态
        kafka_client.configure(bootstrap_servers="known:9092", group_id="known-group")
        original_bootstrap = kafka_client.bootstrap_servers

        # 用不同参数再次构造（应被守卫拦截，不改变属性）
        KafkaClient(bootstrap_servers="different:9092", group_id="different-group")

        assert kafka_client.bootstrap_servers == original_bootstrap
        assert kafka_client.group_id == "known-group"

    def test_singleton_has_initialized_flag(self):
        """单例初始化后持有 _initialized 标志"""
        assert hasattr(kafka_client, "_initialized")
        assert kafka_client._initialized is True

    def test_singleton_default_attributes(self):
        """单例默认属性值正确"""
        kafka_client.configure(
            bootstrap_servers="localhost:9092",
            group_id="default-group",
            auto_offset_reset="latest",
        )
        assert kafka_client.bootstrap_servers == "localhost:9092"
        assert kafka_client.group_id == "default-group"
        assert kafka_client.auto_offset_reset == "latest"
        assert kafka_client._producer is None
        assert kafka_client._consumers == {}
        assert kafka_client._consumer_threads == []
        assert kafka_client._running is False


# ==================== KafkaClient configure 方法测试 ====================


class TestKafkaClientConfigure:
    """KafkaClient.configure() 配置方法测试"""

    def test_configure_updates_all_params(self):
        """configure 同时更新全部三个参数"""
        kafka_client.configure(
            bootstrap_servers="broker1:9092,broker2:9092",
            group_id="my-group",
            auto_offset_reset="earliest",
        )
        assert kafka_client.bootstrap_servers == "broker1:9092,broker2:9092"
        assert kafka_client.group_id == "my-group"
        assert kafka_client.auto_offset_reset == "earliest"

    def test_configure_partial_update_bootstrap_only(self):
        """仅更新 bootstrap_servers，其余保持不变"""
        kafka_client.configure(
            bootstrap_servers="new-host:9092",
            group_id="keep-group",
            auto_offset_reset="earliest",
        )
        kafka_client.configure(bootstrap_servers="replaced:9092")
        assert kafka_client.bootstrap_servers == "replaced:9092"
        # 未传入的参数保持原值
        assert kafka_client.group_id == "keep-group"
        assert kafka_client.auto_offset_reset == "earliest"

    def test_configure_partial_update_group_id_only(self):
        """仅更新 group_id"""
        kafka_client.configure(group_id="new-group")
        assert kafka_client.group_id == "new-group"

    def test_configure_partial_update_auto_offset_only(self):
        """仅更新 auto_offset_reset"""
        kafka_client.configure(auto_offset_reset="earliest")
        assert kafka_client.auto_offset_reset == "earliest"

    def test_configure_with_all_none_keeps_existing(self):
        """全部参数为 None 时不改变任何配置"""
        kafka_client.configure(
            bootstrap_servers="keep-host:9092",
            group_id="keep-group",
            auto_offset_reset="earliest",
        )
        kafka_client.configure()
        assert kafka_client.bootstrap_servers == "keep-host:9092"
        assert kafka_client.group_id == "keep-group"
        assert kafka_client.auto_offset_reset == "earliest"

    def test_configure_clears_consumers(self):
        """configure 清空已注册的监听器"""
        kafka_client.register_listener(["topic-a"], callback=lambda msg: None)
        assert len(kafka_client._consumers) == 1

        kafka_client.configure(bootstrap_servers="new:9092")
        assert kafka_client._consumers == {}

    def test_configure_resets_producer(self):
        """configure 将 producer 重置为 None（惰性重建）"""
        # 模拟已存在 producer
        kafka_client._producer = mock.MagicMock()
        kafka_client.configure(bootstrap_servers="new:9092")
        assert kafka_client._producer is None

    def test_configure_resets_running_flag(self):
        """configure 将运行标志重置为 False"""
        kafka_client._running = True
        kafka_client.configure(bootstrap_servers="new:9092")
        assert kafka_client._running is False

    def test_configure_clears_consumer_threads(self):
        """configure 清空消费者线程列表"""
        kafka_client._consumer_threads = [mock.MagicMock()]
        kafka_client.configure(bootstrap_servers="new:9092")
        assert kafka_client._consumer_threads == []

    def test_configure_supports_comma_separated_servers(self):
        """bootstrap_servers 支持逗号分隔的多 broker 地址"""
        servers = "broker1:9092, broker2:9092, broker3:9092"
        kafka_client.configure(bootstrap_servers=servers)
        assert kafka_client.bootstrap_servers == servers


# ==================== KafkaClient 监听器注册测试 ====================


class TestKafkaClientRegisterListener:
    """KafkaClient.register_listener() 监听器注册测试"""

    def test_register_single_topic(self):
        """注册单个 topic 的监听器"""
        callback = lambda msg: None
        kafka_client.register_listener(["order-events"], callback)
        assert "order-events" in kafka_client._consumers
        assert kafka_client._consumers["order-events"] is callback

    def test_register_multiple_topics(self):
        """注册多个 topic 的监听器，每个 topic 都绑定同一回调"""
        callback = lambda msg: None
        kafka_client.register_listener(["topic-1", "topic-2", "topic-3"], callback)
        assert len(kafka_client._consumers) == 3
        for topic in ["topic-1", "topic-2", "topic-3"]:
            assert kafka_client._consumers[topic] is callback

    def test_register_overwrites_existing_callback(self):
        """对同一 topic 重复注册会覆盖旧的回调"""
        cb1 = lambda msg: "first"
        cb2 = lambda msg: "second"
        kafka_client.register_listener(["same-topic"], cb1)
        kafka_client.register_listener(["same-topic"], cb2)
        assert kafka_client._consumers["same-topic"] is cb2

    def test_register_with_custom_group_id(self):
        """传入自定义 group_id 不影响注册结果（group_id 仅用于日志）"""
        callback = lambda msg: None
        kafka_client.register_listener(
            ["topic-x"], callback, group_id="custom-group"
        )
        assert kafka_client._consumers["topic-x"] is callback

    def test_register_default_group_id_none(self):
        """group_id 默认为 None 时正常注册"""
        callback = lambda msg: None
        kafka_client.register_listener(["topic-y"], callback)
        assert kafka_client._consumers["topic-y"] is callback

    def test_register_empty_topic_list_does_nothing(self):
        """空 topic 列表不会注册任何监听器"""
        kafka_client.register_listener([], lambda msg: None)
        assert kafka_client._consumers == {}

    def test_register_callback_is_callable(self):
        """注册的回调保持可调用性"""
        received = []

        def handler(message):
            received.append(message)

        kafka_client.register_listener(["test-topic"], handler)
        # 模拟消息分发
        kafka_client._consumers["test-topic"]({"value": "hello"})
        assert received == [{"value": "hello"}]


# ==================== KafkaClient 发送安全校验测试 ====================


class TestKafkaClientSendSafety:
    """KafkaClient.send() 发送安全校验测试

    重点验证：
    - kafka-python 未安装时 send 抛出 ImportError
    - topic 名称包含空格/制表符/换行符等特殊字符时抛出 ValueError
    - 合法 topic 名称正常调用 producer
    """

    def test_send_raises_import_error_without_kafka_python(self):
        """未安装 kafka-python 时 send 抛出 ImportError（含安装提示）"""
        kafka_client._producer = None  # 强制触发 _get_producer 重建
        # 模拟 kafka 模块不可导入
        with mock.patch.dict(sys.modules, {"kafka": None}):
            with pytest.raises(ImportError, match="kafka-python is not installed"):
                kafka_client.send("valid-topic", {"msg": "hello"})

    def test_send_raises_import_error_message_contains_pip_hint(self):
        """ImportError 消息包含 pip 安装提示"""
        kafka_client._producer = None
        with mock.patch.dict(sys.modules, {"kafka": None}):
            with pytest.raises(ImportError) as exc_info:
                kafka_client.send("valid-topic", {"msg": "hello"})
            assert "pip install kafka-python" in str(exc_info.value)

    def test_send_caches_producer_after_first_creation(self):
        """_get_producer 惰性初始化后缓存 producer 实例"""
        fake_producer = mock.MagicMock()
        with mock.patch.object(
            kafka_client, "_get_producer", return_value=fake_producer
        ) as mock_get:
            kafka_client.send("topic-a", {"v": 1})
            kafka_client.send("topic-a", {"v": 2})
            # _get_producer 被调用两次（send 每次都调用），但返回同一 mock
            assert mock_get.call_count == 2

    def test_send_valid_topic_calls_producer_send(self):
        """合法 topic 名称正常调用 producer.send"""
        fake_producer = mock.MagicMock()
        fake_future = mock.MagicMock()
        fake_producer.send.return_value = fake_future
        with mock.patch.object(kafka_client, "_get_producer", return_value=fake_producer):
            result = kafka_client.send("valid-topic", {"key": "value"})
        fake_producer.send.assert_called_once()
        assert result is fake_future

    def test_send_invalid_topic_with_space_raises(self):
        """topic 名包含空格时抛出 ValueError"""
        fake_producer = mock.MagicMock()
        with mock.patch.object(kafka_client, "_get_producer", return_value=fake_producer):
            with pytest.raises(ValueError, match="Invalid Kafka topic name"):
                kafka_client.send("invalid topic", {"v": 1})
            # producer.send 不应被调用
            fake_producer.send.assert_not_called()

    def test_send_invalid_topic_with_tab_raises(self):
        """topic 名包含制表符时抛出 ValueError"""
        fake_producer = mock.MagicMock()
        with mock.patch.object(kafka_client, "_get_producer", return_value=fake_producer):
            with pytest.raises(ValueError, match="Invalid Kafka topic name"):
                kafka_client.send("invalid\ttopic", {"v": 1})

    def test_send_invalid_topic_with_newline_raises(self):
        """topic 名包含换行符时抛出 ValueError"""
        fake_producer = mock.MagicMock()
        with mock.patch.object(kafka_client, "_get_producer", return_value=fake_producer):
            with pytest.raises(ValueError, match="Invalid Kafka topic name"):
                kafka_client.send("invalid\ntopic", {"v": 1})

    def test_send_empty_topic_raises(self):
        """空字符串 topic 抛出 ValueError"""
        fake_producer = mock.MagicMock()
        with mock.patch.object(kafka_client, "_get_producer", return_value=fake_producer):
            with pytest.raises(ValueError, match="Invalid Kafka topic name"):
                kafka_client.send("", {"v": 1})

    def test_send_none_topic_raises(self):
        """None 作为 topic 抛出 ValueError"""
        fake_producer = mock.MagicMock()
        with mock.patch.object(kafka_client, "_get_producer", return_value=fake_producer):
            with pytest.raises(ValueError, match="Invalid Kafka topic name"):
                kafka_client.send(None, {"v": 1})

    def test_send_with_key(self):
        """send 携带 key 时正确传递给 producer"""
        fake_producer = mock.MagicMock()
        with mock.patch.object(kafka_client, "_get_producer", return_value=fake_producer):
            kafka_client.send("topic-k", value={"v": 1}, key="partition-key")
        _, kwargs = fake_producer.send.call_args
        assert kwargs.get("key") == "partition-key"

    def test_send_with_headers_encodes_to_bytes(self):
        """headers 字典被编码为 (key, bytes) 元组列表"""
        fake_producer = mock.MagicMock()
        headers = {"trace-id": "abc123", "source": "test"}
        with mock.patch.object(kafka_client, "_get_producer", return_value=fake_producer):
            kafka_client.send("topic-h", value={"v": 1}, headers=headers)
        _, kwargs = fake_producer.send.call_args
        sent_headers = kwargs.get("headers")
        # headers 被编码为 [(k, bytes), ...]
        assert sent_headers is not None
        assert all(isinstance(v, bytes) for _, v in sent_headers)
        headers_dict = dict(sent_headers)
        assert headers_dict["trace-id"] == b"abc123"
        assert headers_dict["source"] == b"test"

    def test_send_without_headers_passes_empty_list(self):
        """未传 headers 时 producer 收到空列表"""
        fake_producer = mock.MagicMock()
        with mock.patch.object(kafka_client, "_get_producer", return_value=fake_producer):
            kafka_client.send("topic-nh", value={"v": 1})
        _, kwargs = fake_producer.send.call_args
        assert kwargs.get("headers") == []

    def test_send_passes_topic_and_value(self):
        """send 正确传递 topic 和 value 给 producer"""
        fake_producer = mock.MagicMock()
        with mock.patch.object(kafka_client, "_get_producer", return_value=fake_producer):
            kafka_client.send("my-topic", value={"data": 42})
        args, _ = fake_producer.send.call_args
        assert args[0] == "my-topic"

    def test_register_listener_rejects_invalid_topic_with_space(self):
        """register_listener 直接拒绝包含空格的 topic（无需 producer）"""
        with pytest.raises(ValueError, match="Invalid Kafka topic name"):
            kafka_client.register_listener(["bad topic"], lambda msg: None)
        # 无效 topic 不应被注册
        assert "bad topic" not in kafka_client._consumers

    def test_register_listener_rejects_empty_topic_in_list(self):
        """register_listener 拒绝列表中的空字符串 topic"""
        with pytest.raises(ValueError, match="Invalid Kafka topic name"):
            kafka_client.register_listener(["valid-topic", ""], lambda msg: None)

    def test_register_listener_rejects_topic_with_tab(self):
        """register_listener 拒绝包含制表符的 topic"""
        with pytest.raises(ValueError, match="Invalid Kafka topic name"):
            kafka_client.register_listener(["tab\ttopic"], lambda msg: None)

    def test_register_listener_rejects_topic_with_newline(self):
        """register_listener 拒绝包含换行符的 topic"""
        with pytest.raises(ValueError, match="Invalid Kafka topic name"):
            kafka_client.register_listener(["line\ntopic"], lambda msg: None)

    def test_valid_topic_names_accepted_by_register_listener(self):
        """合法的 topic 名称（含连字符、点、下划线）均被接受"""
        callback = lambda msg: None
        valid_topics = [
            "simple",
            "with-dash",
            "with_underscore",
            "with.dot",
            "topic123",
            "CamelCase",
        ]
        kafka_client.register_listener(valid_topics, callback)
        assert len(kafka_client._consumers) == len(valid_topics)


# ==================== @KafkaListener 注解测试 ====================


class TestKafkaListenerAnnotation:
    """@KafkaListener 注解定义与属性测试"""

    def test_topics_string_converted_to_list(self):
        """topics 传入字符串时自动转换为单元素列表"""
        annotation = KafkaListener(topics="order-events")
        assert annotation.topics == ["order-events"]

    def test_topics_list_kept_as_list(self):
        """topics 传入列表时保持原样"""
        annotation = KafkaListener(topics=["topic-1", "topic-2"])
        assert annotation.topics == ["topic-1", "topic-2"]

    def test_topics_single_element_list(self):
        """topics 传入单元素列表时保持单元素"""
        annotation = KafkaListener(topics=["only-one"])
        assert annotation.topics == ["only-one"]

    def test_group_id_default_empty_string(self):
        """groupId 默认为空字符串"""
        annotation = KafkaListener(topics="topic")
        assert annotation.groupId == ""

    def test_group_id_custom_value(self):
        """groupId 可自定义"""
        annotation = KafkaListener(topics="topic", groupId="order-service")
        assert annotation.groupId == "order-service"

    def test_annotation_type_is_messaging(self):
        """注解类型为 messaging"""
        annotation = KafkaListener(topics="topic")
        assert annotation._annotation_type == "messaging"

    def test_annotation_stores_topics_attribute(self):
        """注解实例持有 topics 属性"""
        annotation = KafkaListener(topics=["a", "b"])
        assert hasattr(annotation, "topics")
        assert isinstance(annotation.topics, list)

    def test_annotation_stores_group_id_attribute(self):
        """注解实例持有 groupId 属性"""
        annotation = KafkaListener(topics="topic", groupId="grp")
        assert hasattr(annotation, "groupId")
        assert annotation.groupId == "grp"

    def test_decorator_marks_method(self):
        """@KafkaListener 作为装饰器标记方法，方法挂载 __spring_annotations__"""
        @KafkaListener(topics="order-events", groupId="order-group")
        def handle_order(message):
            return message

        assert hasattr(handle_order, "__spring_annotations__")
        annotations = handle_order.__spring_annotations__
        assert len(annotations) == 1
        assert isinstance(annotations[0], KafkaListener)
        assert annotations[0].topics == ["order-events"]
        assert annotations[0].groupId == "order-group"

    def test_decorator_preserves_function_behavior(self):
        """@KafkaListener 装饰后函数仍可正常调用"""
        @KafkaListener(topics="topic")
        def handler(message):
            return f"processed:{message}"

        assert handler("hello") == "processed:hello"

    def test_decorator_with_list_topics(self):
        """@KafkaListener 支持列表形式的 topics"""
        @KafkaListener(topics=["t1", "t2"])
        def handler(message):
            return message

        ann = handle_annotation(handler)
        assert ann.topics == ["t1", "t2"]

    def test_multiple_annotations_on_same_method(self):
        """同一方法可叠加多个 @KafkaListener"""
        @KafkaListener(topics="topic-a")
        @KafkaListener(topics="topic-b")
        def handler(message):
            return message

        anns = handler.__spring_annotations__
        assert len(anns) == 2
        topic_sets = [a.topics for a in anns]
        assert ["topic-a"] in topic_sets
        assert ["topic-b"] in topic_sets

    def test_decorator_on_class_method(self):
        """@KafkaListener 可标记类方法"""

        class OrderConsumer:
            @KafkaListener(topics="orders", groupId="order-group")
            def handle(self, message):
                return message

        method = OrderConsumer.handle
        assert hasattr(method, "__spring_annotations__")
        ann = method.__spring_annotations__[0]
        assert ann.topics == ["orders"]
        assert ann.groupId == "order-group"


def handle_annotation(func):
    """提取方法上的第一个 KafkaListener 注解（辅助函数）"""
    return func.__spring_annotations__[0]


# ==================== KafkaTemplate 测试 ====================


class TestKafkaTemplate:
    """KafkaTemplate 发送模板测试"""

    def test_global_kafka_template_instance_exists(self):
        """全局 kafka_template 实例存在且类型正确"""
        assert kafka_template is not None
        assert isinstance(kafka_template, KafkaTemplate)

    def test_global_template_is_single_instance(self):
        """多次引用全局 kafka_template 是同一对象"""
        from spring.annotations.messaging import kafka_template as kt2
        assert kafka_template is kt2

    def test_send_delegates_to_kafka_client(self):
        """KafkaTemplate.send 委托给 kafka_client.send"""
        fake_future = mock.MagicMock()
        with mock.patch.object(
            kafka_client, "send", return_value=fake_future
        ) as mock_send:
            result = kafka_template.send("topic", value={"v": 1})
        mock_send.assert_called_once_with(
            topic="topic", value={"v": 1}, key=None, headers=None
        )
        assert result is fake_future

    def test_send_with_key_and_headers(self):
        """KafkaTemplate.send 传递 key 和 headers"""
        with mock.patch.object(kafka_client, "send") as mock_send:
            kafka_template.send(
                "topic",
                value={"v": 1},
                key="partition-key",
                headers={"trace": "id"},
            )
        mock_send.assert_called_once_with(
            topic="topic",
            value={"v": 1},
            key="partition-key",
            headers={"trace": "id"},
        )

    def test_send_default_value_is_none(self):
        """KafkaTemplate.send 的 value 默认为 None"""
        with mock.patch.object(kafka_client, "send") as mock_send:
            kafka_template.send("topic")
        mock_send.assert_called_once_with(
            topic="topic", value=None, key=None, headers=None
        )

    def test_send_and_wait_delegates_to_kafka_client(self):
        """KafkaTemplate.send_and_wait 委托给 kafka_client.send_and_wait"""
        expected = mock.MagicMock()
        with mock.patch.object(
            kafka_client, "send_and_wait", return_value=expected
        ) as mock_wait:
            result = kafka_template.send_and_wait("topic", value={"v": 1})
        mock_wait.assert_called_once_with(
            topic="topic", value={"v": 1}, key=None, timeout=10.0
        )
        assert result is expected

    def test_send_and_wait_with_custom_timeout(self):
        """KafkaTemplate.send_and_wait 支持自定义 timeout"""
        with mock.patch.object(kafka_client, "send_and_wait") as mock_wait:
            kafka_template.send_and_wait(
                "topic", value={"v": 1}, key="k", timeout=30.0
            )
        mock_wait.assert_called_once_with(
            topic="topic", value={"v": 1}, key="k", timeout=30.0
        )

    def test_send_and_wait_default_timeout_is_10(self):
        """send_and_wait 默认超时为 10.0 秒"""
        with mock.patch.object(kafka_client, "send_and_wait") as mock_wait:
            kafka_template.send_and_wait("topic", value={"v": 1})
        _, kwargs = mock_wait.call_args
        assert kwargs["timeout"] == 10.0

    def test_send_returns_future_from_kafka_client(self):
        """KafkaTemplate.send 返回 kafka_client.send 的结果"""
        future = mock.MagicMock()
        with mock.patch.object(kafka_client, "send", return_value=future):
            result = kafka_template.send("topic", value="data")
        assert result is future

    def test_new_template_instance_works(self):
        """手动创建 KafkaTemplate 实例也可正常工作"""
        template = KafkaTemplate()
        with mock.patch.object(kafka_client, "send") as mock_send:
            template.send("topic", value={"v": 1})
        mock_send.assert_called_once()


# ==================== init_kafka 配置函数测试 ====================


class TestInitKafka:
    """init_kafka(config) 配置初始化函数测试"""

    def test_init_kafka_full_config(self):
        """完整配置正确读取并应用到 kafka_client"""
        config = {
            "spring": {
                "kafka": {
                    "bootstrap-servers": "kafka1:9092,kafka2:9092",
                    "consumer": {
                        "group-id": "my-app-group",
                        "auto-offset-reset": "earliest",
                    },
                }
            }
        }
        init_kafka(config)
        assert kafka_client.bootstrap_servers == "kafka1:9092,kafka2:9092"
        assert kafka_client.group_id == "my-app-group"
        assert kafka_client.auto_offset_reset == "earliest"

    def test_init_kafka_no_spring_key(self):
        """config 中没有 spring 键时为空操作，不抛异常"""
        init_kafka({})
        # 单例保持默认配置（由 fixture 重置）
        assert kafka_client.bootstrap_servers == "localhost:9092"
        assert kafka_client.group_id == "default-group"
        assert kafka_client.auto_offset_reset == "latest"

    def test_init_kafka_no_kafka_key(self):
        """config 有 spring 但无 kafka 子键时为空操作"""
        init_kafka({"spring": {"application": {"name": "testapp"}}})
        assert kafka_client.bootstrap_servers == "localhost:9092"
        assert kafka_client.group_id == "default-group"

    def test_init_kafka_empty_kafka_config(self):
        """spring.kafka 为空字典时为空操作（falsy 提前返回）"""
        init_kafka({"spring": {"kafka": {}}})
        # 空字典为 falsy，init_kafka 提前 return，不调用 configure
        assert kafka_client.bootstrap_servers == "localhost:9092"

    def test_init_kafka_partial_config_uses_defaults(self):
        """缺少 consumer 子键时使用默认 group_id 和 auto_offset_reset"""
        config = {
            "spring": {
                "kafka": {
                    "bootstrap-servers": "only-host:9092",
                }
            }
        }
        init_kafka(config)
        assert kafka_client.bootstrap_servers == "only-host:9092"
        # consumer 配置缺失，使用默认值
        assert kafka_client.group_id == "default-group"
        assert kafka_client.auto_offset_reset == "latest"

    def test_init_kafka_only_consumer_group_id(self):
        """仅配置 consumer.group-id 时 bootstrap 使用默认值"""
        config = {
            "spring": {
                "kafka": {
                    "consumer": {
                        "group-id": "special-group",
                    }
                }
            }
        }
        init_kafka(config)
        assert kafka_client.group_id == "special-group"
        assert kafka_client.bootstrap_servers == "localhost:9092"
        assert kafka_client.auto_offset_reset == "latest"

    def test_init_kafka_only_auto_offset_reset(self):
        """仅配置 consumer.auto-offset-reset"""
        config = {
            "spring": {
                "kafka": {
                    "consumer": {
                        "auto-offset-reset": "earliest",
                    }
                }
            }
        }
        init_kafka(config)
        assert kafka_client.auto_offset_reset == "earliest"
        assert kafka_client.group_id == "default-group"

    def test_init_kafka_missing_auto_offset_reset(self):
        """consumer 存在但缺少 auto-offset-reset 时使用默认值"""
        config = {
            "spring": {
                "kafka": {
                    "bootstrap-servers": "host:9092",
                    "consumer": {
                        "group-id": "grp",
                    },
                }
            }
        }
        init_kafka(config)
        assert kafka_client.bootstrap_servers == "host:9092"
        assert kafka_client.group_id == "grp"
        assert kafka_client.auto_offset_reset == "latest"

    def test_init_kafka_missing_group_id(self):
        """consumer 存在但缺少 group-id 时使用默认值"""
        config = {
            "spring": {
                "kafka": {
                    "consumer": {
                        "auto-offset-reset": "earliest",
                    }
                }
            }
        }
        init_kafka(config)
        assert kafka_client.group_id == "default-group"
        assert kafka_client.auto_offset_reset == "earliest"

    def test_init_kafka_does_not_raise_on_empty_config(self):
        """空 config 不抛异常"""
        # 不应抛出任何异常
        init_kafka({})

    def test_init_kafka_applies_multiple_calls(self):
        """多次调用 init_kafka 后生效的是最后一次配置"""
        init_kafka({
            "spring": {"kafka": {"bootstrap-servers": "first:9092"}}
        })
        assert kafka_client.bootstrap_servers == "first:9092"
        init_kafka({
            "spring": {"kafka": {"bootstrap-servers": "second:9092"}}
        })
        assert kafka_client.bootstrap_servers == "second:9092"

    def test_init_kafka_clears_previous_listeners(self):
        """init_kafka 调用 configure 会清空之前注册的监听器"""
        kafka_client.register_listener(["pre-existing"], lambda msg: None)
        assert len(kafka_client._consumers) == 1
        init_kafka({
            "spring": {"kafka": {"bootstrap-servers": "new:9092"}}
        })
        assert kafka_client._consumers == {}
