# WebSocket —— 像微信一样实时通信

> SpringBootAI 2.3.10
> 返回 [README 模块导航](../README.md#模块文档导航)

---

## 你遇到了什么问题？

你需要做实时通知、聊天、数据看板——但普通的 HTTP 请求是"问一句答一句"，用户不问服务器就不答。要么用户不停地轮询（浪费资源），要么有消息了用户却不知道。

## ① 是什么

**就像打电话（或微信聊天）一样，双方随时可以给对方发消息，不用等对方问。** 普通 HTTP 是"你问我才答"，WebSocket 是"我想说就说"——浏览器和服务器建立一条持久连接，双向实时通信，像微信一样实时。

## ② 怎么用

方式一：简单回声（JSR-356 风格）

```python
from springbootai.websocket import ServerEndpoint

@ServerEndpoint("/ws/echo")
class EchoEndpoint:
    async def on_open(self, session):
        await session.send_text("欢迎连接！")  # 连接建立时发欢迎消息

    async def on_message(self, session, message):
        await session.send_text("回声: " + message)  # 收到什么就回什么

    async def on_close(self, session, reason):
        print(f"连接断开: {reason}")

# 客户端连接 ws://127.0.0.1:8080/ws/echo
# 发送 "你好" → 收到 "回声: 你好"
```

方式二：聊天室（Spring STOMP 风格）

```python
from springbootai.websocket import ServerEndpoint, MessageMapping, SendTo, SendToUser

@ServerEndpoint("/ws/chat")
class ChatEndpoint:
    @MessageMapping("/chat.send")
    @SendTo("/topic/messages")         # 广播给所有订阅者
    def send_message(self, message):
        return {"text": message}
        # 结果：所有订阅 /topic/messages 的人都收到

    @MessageMapping("/chat.private")
    @SendToUser                         # 只回发给发送者本人
    def private_message(self, message, session):
        return {"text": "私密: " + message}
        # 结果：只有发送者自己收到，其他人收不到
```

安装到 FastAPI：

```python
from springbootai.websocket import WebSocketRouter, discover_server_endpoints

router = WebSocketRouter()
for endpoint_cls in discover_server_endpoints():   # 自动发现所有 @ServerEndpoint
    router.add_endpoint(endpoint_cls.__spring_endpoint_path__, endpoint_cls)
router.install(app)   # 注册到 FastAPI
```

## ③ 运行结果

- 客户端 A 发消息 → 所有订阅者（包括 A 自己）都收到 → 聊天室效果
- 客户端 A 发私密消息 → 只有 A 收到 → 私信效果

## mini-FAQ

**Q：WebSocket 和普通 HTTP 有什么区别？**
HTTP 是"你问我才答"，每次请求建立新连接。WebSocket 是"建立一条热线一直通着"，双方随时说话。

**Q：InMemoryBroker 重启后消息还在吗？**
不在了。内存级 broker 重启后所有订阅丢失。需要持久化消息用 Redis 或消息队列。

**Q：on_open/on_message/on_close 必须是 async def 吗？**
是的，因为 WebSocket 是异步 I/O。用 `async def` 和 `await`。

**Q：Nginx 需要特殊配置吗？**
需要。Nginx 必须正确配置 `Upgrade` 和 `Connection` 头来支持 WebSocket 协议升级。

**Q：怎么测试 WebSocket？**
不能用 `requests` 库（它是 HTTP 客户端），需要用 `websockets` 库或 FastAPI 的 `TestClient`。

---

## 改进记录

### Session 注册表广播无速率限制 — 中 ⏳ 待处理 (v2.3.0)

**位置**：`springbootai/websocket/session.py` broadcast() / send_to_user()

**现象**：`broadcast()` 和 `send_to_user()` 遍历所有 session 同步发送消息，无速率限制。恶意客户端高频触发广播可导致事件循环阻塞。

**改进方案**：引入 `asyncio.Semaphore` 限制并发发送数（默认 100）；增加每秒消息数限制（令牌桶）；大规模广播使用 `asyncio.gather(*tasks, return_exceptions=True)` 并发发送。

### Session close() 非线程安全 — 中 ⏳ 待处理 (v2.3.0)

**位置**：`springbootai/websocket/session.py` close() / mark_closed()

**现象**：`close()` 和 `mark_closed()` 修改 `_closed` 标志时无锁保护，并发调用可能导致状态不一致。

**改进方案**：使用 `asyncio.Lock` 或 `threading.Lock` 保护状态变更，`close()` 内部检查 `if self._closed: return` 实现幂等。
