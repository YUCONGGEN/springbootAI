"""
模型 Provider 适配层 - OpenAI 兼容 + Ollama（企业级）。

已落地的企业能力：
1. 函数调用闭环 - tools 注入请求体，tool_call 解析→执行→回填→续写循环
2. 真流式 SSE - stream=True 解析 data: 增量，逐块 yield
3. async - acall/astream 异步入口
4. 韧性 - 复用 spring.retry 重试 + AICircuitBreaker 熔断
5. 可观测 - ai_metrics 记录调用/token/延迟

底层优先复用 LangChain 生态（langchain_openai/langchain_community）做模型适配，
未安装时降级原生 HTTP（requests），保证开箱即用。
"""
import json
import logging
import time
from typing import Any, Dict, List, Optional

from spring.ai.core import (
    ChatModel, ChatResponse, EmbeddingModel, Generation, Message, MessageType,
)

logger = logging.getLogger("Spring.AI")


def _has_langchain_openai() -> bool:
    try:
        import langchain_openai  # noqa: F401
        return True
    except ImportError:
        return False


def _has_langchain_community() -> bool:
    try:
        import langchain_community  # noqa: F401
        return True
    except ImportError:
        return False


def _is_tool_registry(obj) -> bool:
    return obj is not None and hasattr(obj, "schemas") and hasattr(obj, "execute")


# ==================== OpenAI 兼容 ====================

class OpenAIChatModel(ChatModel):
    """
    OpenAI 兼容聊天模型 - 支持 OpenAI / Azure / DeepSeek / Moonshot 等兼容接口。

    企业能力：函数调用闭环 / 真流式 / 重试 / 熔断 / Prometheus 观测。
    """

    # 函数调用最大往返轮数（防止模型无限调用工具）
    MAX_TOOL_ITERATIONS = 5

    def __init__(self, api_key: str = "", base_url: str = "",
                 model: str = "gpt-4o-mini", temperature: float = 0.7,
                 timeout: int = 60,
                 max_retries: int = 3, retry_delay_ms: int = 500,
                 circuit_breaker=None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/") if base_url else "https://api.openai.com/v1"
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay_ms = retry_delay_ms
        self.circuit_breaker = circuit_breaker
        self._llm = None
        if _has_langchain_openai() and api_key:
            try:
                from langchain_openai import ChatOpenAI
                self._llm = ChatOpenAI(
                    api_key=api_key,
                    base_url=self.base_url if base_url else None,
                    model=model, temperature=temperature, timeout=timeout,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("ChatOpenAI 初始化失败，降级原生HTTP: %s", exc)
                self._llm = None

    # ---------- 公共入口 ----------

    def call(self, messages: List[Message],
             tool_registry=None,
             options: Optional[Dict[str, Any]] = None) -> ChatResponse:
        """同步调用（基类闭环 + 整体指标）"""
        from spring.ai.observability import ai_metrics
        start = time.time()
        try:
            resp = super().call(messages, tool_registry, options)
            usage = (resp.metadata or {}).get("usage") if resp else None
            ai_metrics.record_call("openai", self.model, "success",
                                   time.time() - start, usage)
            return resp
        except Exception:
            ai_metrics.record_call("openai", self.model, "failure",
                                   time.time() - start)
            raise

    async def acall(self, messages: List[Message],
                    tool_registry=None,
                    options: Optional[Dict[str, Any]] = None) -> ChatResponse:
        import asyncio
        return await asyncio.to_thread(self.call, messages, tool_registry, options)

    def stream(self, messages: List[Message],
               tool_registry=None,
               options: Optional[Dict[str, Any]] = None):
        """真流式 - SSE 增量生成器"""
        if self._llm is not None:
            yield from self._stream_via_langchain(messages, options)
            return
        yield from self._stream_via_http(messages, options)

    async def astream(self, messages: List[Message],
                      tool_registry=None,
                      options: Optional[Dict[str, Any]] = None):
        import asyncio
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def _producer():
            for chunk in self.stream(messages, tool_registry, options):
                asyncio.run_coroutine_threadsafe(queue.put(chunk), loop)
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)

        loop.run_in_executor(None, _producer)
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            yield chunk

    # ---------- Provider 单次调用 ----------

    def _raw_call(self, messages, tool_registry=None, options=None) -> ChatResponse:
        if self._llm is not None:
            return self._call_via_langchain(messages, options)
        return self._call_via_http(messages, tool_registry, options)

    def _call_via_langchain(self, messages, options) -> ChatResponse:
        lc_messages = [(m.type, m.content) for m in messages]
        result = self._llm.invoke(lc_messages)
        content = result.content if hasattr(result, "content") else str(result)
        usage = getattr(result, "usage_metadata", None) or {}
        return ChatResponse(
            generations=[Generation(output=Message.assistant(content))],
            metadata={"provider": "openai", "backend": "langchain", "usage": usage},
        )

    def _stream_via_langchain(self, messages, options):
        if self._llm is None:
            return
        for chunk in self._llm.stream([(m.type, m.content) for m in messages]):
            content = chunk.content if hasattr(chunk, "content") else str(chunk)
            if content:
                yield ChatResponse(generations=[Generation(
                    output=Message.assistant(content))],
                    metadata={"provider": "openai", "stream": True})

    def _call_via_http(self, messages, tool_registry, options) -> ChatResponse:
        """单次 HTTP 调用 - 注入 tools schema，解析 tool_calls 到 metadata"""
        from spring.ai.resilience import resilient_call, TransientError
        import requests

        payload = {
            "model": self.model,
            "messages": [self._serialize_msg(m) for m in messages],
            "temperature": self.temperature,
        }
        if options:
            payload.update(options)
        # 注入 tools schema（基类闭环依赖此）
        if _is_tool_registry(tool_registry) and tool_registry.names():
            payload["tools"] = tool_registry.schemas()

        def _do_post():
            try:
                resp = requests.post(
                    f"{self.base_url}/chat/completions", json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}",
                             "Content-Type": "application/json"},
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return resp.json()
            except (requests.ConnectionError, requests.Timeout) as exc:
                raise TransientError(str(exc)) from exc
            except requests.HTTPError as exc:
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise TransientError(str(exc)) from exc
                raise

        data = resilient_call(
            _do_post, max_retries=self.max_retries,
            retry_delay_ms=self.retry_delay_ms,
            retry_exceptions=(TransientError,),
            circuit_breaker=self.circuit_breaker,
            count_as_failure_exc=(TransientError,),
        )()

        choice = data.get("choices", [{}])[0]
        msg_obj = choice.get("message", {})
        tool_calls = msg_obj.get("tool_calls")
        usage = data.get("usage", {})
        content = msg_obj.get("content", "") or ""
        meta = {"provider": "openai", "backend": "http", "usage": usage}
        if tool_calls:
            # 标记 tool_calls，由基类 call() 闭环执行；assistant 消息保留 tool_calls 元数据以便重发
            meta["tool_calls"] = tool_calls
        return ChatResponse(
            generations=[Generation(output=Message(
                content=content, type=MessageType.ASSISTANT,
                metadata={"tool_calls": tool_calls or []}))],
            metadata=meta,
        )

    def _stream_via_http(self, messages, options):
        """真流式：解析 SSE data: 行，逐块 yield 增量内容"""
        import requests
        payload = {
            "model": self.model,
            "messages": [self._serialize_msg(m) for m in messages],
            "temperature": self.temperature,
            "stream": True,
        }
        if options:
            payload.update(options)
        with requests.post(
            f"{self.base_url}/chat/completions", json=payload, stream=True,
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            timeout=self.timeout,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[len("data:"):].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                delta = (chunk.get("choices", [{}])[0]
                         .get("delta", {}).get("content", ""))
                if delta:
                    yield ChatResponse(
                        generations=[Generation(output=Message.assistant(delta))],
                        metadata={"provider": "openai", "stream": True},
                    )

    # ---------- 消息序列化 ----------

    def _serialize_msg(self, m: Message) -> Dict[str, Any]:
        d = m.to_dict()
        if m.type == MessageType.TOOL:
            d["role"] = "tool"
            if m.metadata.get("tool_call_id"):
                d["tool_call_id"] = m.metadata["tool_call_id"]
        # assistant 消息携带 tool_calls 时重发（OpenAI 协议要求）
        if m.type == MessageType.ASSISTANT and m.metadata.get("tool_calls"):
            d["tool_calls"] = m.metadata["tool_calls"]
        return d


class OpenAIEmbeddingModel(EmbeddingModel):
    """OpenAI 兼容嵌入模型"""

    def __init__(self, api_key: str = "", base_url: str = "",
                 model: str = "text-embedding-3-small", timeout: int = 60,
                 max_retries: int = 3, retry_delay_ms: int = 500,
                 circuit_breaker=None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/") if base_url else "https://api.openai.com/v1"
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay_ms = retry_delay_ms
        self.circuit_breaker = circuit_breaker
        self._embedder = None
        if _has_langchain_openai() and api_key:
            try:
                from langchain_openai import OpenAIEmbeddings
                self._embedder = OpenAIEmbeddings(
                    api_key=api_key,
                    base_url=self.base_url if base_url else None,
                    model=model,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("OpenAIEmbeddings 初始化失败，降级HTTP: %s", exc)
                self._embedder = None

    def embed(self, texts: List[str]) -> List[List[float]]:
        if self._embedder is not None:
            try:
                return self._embedder.embed_documents(texts)
            except Exception as exc:  # pragma: no cover
                logger.warning("LangChain 嵌入失败，降级HTTP: %s", exc)
        return self._embed_via_http(texts)

    def _embed_via_http(self, texts: List[str]) -> List[List[float]]:
        from spring.ai.resilience import resilient_call, TransientError
        import requests

        def _do_post():
            try:
                resp = requests.post(
                    f"{self.base_url}/embeddings",
                    json={"model": self.model, "input": texts},
                    headers={"Authorization": f"Bearer {self.api_key}",
                             "Content-Type": "application/json"},
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return resp.json()
            except (requests.ConnectionError, requests.Timeout) as exc:
                raise TransientError(str(exc)) from exc
            except requests.HTTPError as exc:
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise TransientError(str(exc)) from exc
                raise

        data = resilient_call(
            _do_post, max_retries=self.max_retries,
            retry_delay_ms=self.retry_delay_ms,
            retry_exceptions=(TransientError,),
            circuit_breaker=self.circuit_breaker,
            count_as_failure_exc=(TransientError,),
        )()
        return [item["embedding"] for item in data["data"]]


# ==================== Ollama ====================

class OllamaChatModel(ChatModel):
    """Ollama 本地聊天模型（Llama3/Qwen/Phi3 等）"""

    MAX_TOOL_ITERATIONS = 5

    def __init__(self, base_url: str = "http://localhost:11434",
                 model: str = "llama3", temperature: float = 0.7,
                 timeout: int = 120, max_retries: int = 3,
                 retry_delay_ms: int = 500, circuit_breaker=None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay_ms = retry_delay_ms
        self.circuit_breaker = circuit_breaker
        self._llm = None
        if _has_langchain_community():
            try:
                from langchain_community.chat_models import ChatOllama
                self._llm = ChatOllama(
                    base_url=self.base_url, model=model,
                    temperature=temperature,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("ChatOllama 初始化失败，降级HTTP: %s", exc)
                self._llm = None

    def call(self, messages, tool_registry=None, options=None):
        """同步调用（基类闭环 + 整体指标）"""
        from spring.ai.observability import ai_metrics
        start = time.time()
        try:
            resp = super().call(messages, tool_registry, options)
            ai_metrics.record_call("ollama", self.model, "success",
                                   time.time() - start)
            return resp
        except Exception:
            ai_metrics.record_call("ollama", self.model, "failure",
                                   time.time() - start)
            raise

    def _raw_call(self, messages, tool_registry=None, options=None):
        if self._llm is not None:
            lc_messages = [(m.type, m.content) for m in messages]
            result = self._llm.invoke(lc_messages)
            content = result.content if hasattr(result, "content") else str(result)
            return ChatResponse(
                generations=[Generation(output=Message.assistant(content))],
                metadata={"provider": "ollama", "backend": "langchain"})
        return self._call_via_http(messages, options)

    def _call_via_http(self, messages, options):
        from spring.ai.resilience import resilient_call, TransientError
        import requests

        def _do_post():
            try:
                resp = requests.post(
                    f"{self.base_url}/api/chat", timeout=self.timeout,
                    json={"model": self.model, "stream": False,
                          "messages": [m.to_dict() for m in messages],
                          "options": {"temperature": self.temperature}},
                )
                resp.raise_for_status()
                return resp.json()
            except (requests.ConnectionError, requests.Timeout) as exc:
                raise TransientError(str(exc)) from exc
            except requests.HTTPError as exc:
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise TransientError(str(exc)) from exc
                raise

        data = resilient_call(
            _do_post, max_retries=self.max_retries,
            retry_delay_ms=self.retry_delay_ms,
            retry_exceptions=(TransientError,),
            circuit_breaker=self.circuit_breaker,
            count_as_failure_exc=(TransientError,),
        )()
        content = data.get("message", {}).get("content", "")
        return ChatResponse(
            generations=[Generation(output=Message.assistant(content))],
            metadata={"provider": "ollama", "backend": "http"})

    def stream(self, messages, tool_registry=None, options=None):
        import requests
        with requests.post(
            f"{self.base_url}/api/chat", stream=True, timeout=self.timeout,
            json={"model": self.model, "stream": True,
                  "messages": [m.to_dict() for m in messages]},
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                delta = chunk.get("message", {}).get("content", "")
                if delta:
                    yield ChatResponse(
                        generations=[Generation(output=Message.assistant(delta))],
                        metadata={"provider": "ollama", "stream": True})


class OllamaEmbeddingModel(EmbeddingModel):
    """Ollama 嵌入模型"""

    def __init__(self, base_url: str = "http://localhost:11434",
                 model: str = "llama3", timeout: int = 60,
                 max_retries: int = 3, retry_delay_ms: int = 500,
                 circuit_breaker=None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay_ms = retry_delay_ms
        self.circuit_breaker = circuit_breaker

    def embed(self, texts: List[str]) -> List[List[float]]:
        from spring.ai.resilience import resilient_call, TransientError
        import requests

        def _embed_one(text):
            def _do_post():
                try:
                    resp = requests.post(
                        f"{self.base_url}/api/embeddings", timeout=self.timeout,
                        json={"model": self.model, "prompt": text},
                    )
                    resp.raise_for_status()
                    return resp.json()
                except (requests.ConnectionError, requests.Timeout) as exc:
                    raise TransientError(str(exc)) from exc
            data = resilient_call(
                _do_post, max_retries=self.max_retries,
                retry_delay_ms=self.retry_delay_ms,
                retry_exceptions=(TransientError,),
                circuit_breaker=self.circuit_breaker,
                count_as_failure_exc=(TransientError,),
            )()
            return data.get("embedding", [])

        return [_embed_one(t) for t in texts]


# ==================== 测试用 Fake ====================

class FakeChatModel(ChatModel):
    """
    确定性聊天模型 - 测试用，不依赖网络。
    回复 echo 输入的最后一句话。
    支持模拟函数调用：当 tool_registry 非空且用户消息含 "调用工具" 时，
    第一轮在 metadata['tool_calls'] 标记工具调用（由基类闭环执行），
    下一轮返回工具结果摘要，验证闭环。
    """

    def __init__(self, prefix: str = "AI:", simulate_tool_call: bool = False):
        self.prefix = prefix
        self.simulate_tool_call = simulate_tool_call
        self.call_count = 0

    def _raw_call(self, messages, tool_registry=None, options=None):
        self.call_count += 1
        last_user = ""
        for msg in reversed(messages):
            if msg.type == "user":
                last_user = msg.content
                break

        # 模拟函数调用闭环：检测 tool 消息回填后给出最终回复
        has_tool_result = any(m.type == MessageType.TOOL for m in messages)
        if (self.simulate_tool_call and _is_tool_registry(tool_registry)
                and "调用工具" in last_user and not has_tool_result
                and tool_registry.names()):
            # 第一轮：在 metadata 标记 tool_calls，基类 call() 闭环执行
            tool_name = tool_registry.names()[0]
            return ChatResponse(
                generations=[Generation(output=Message(
                    content=f"[需要调用工具 {tool_name}]",
                    type=MessageType.ASSISTANT,
                    metadata={"tool_calls": [{"id": "call_fake",
                                              "function": {"name": tool_name,
                                                           "arguments": "{}"}}]}))],
                metadata={"provider": "fake", "tool_calls": [
                    {"id": "call_fake",
                     "function": {"name": tool_name, "arguments": "{}"}}]},
            )

        # 普通回复或工具回填后回复
        content = f"{self.prefix} {last_user}"
        if has_tool_result:
            tool_msgs = [m for m in messages if m.type == MessageType.TOOL]
            content = f"{self.prefix} 工具返回: {tool_msgs[-1].content}"
        return ChatResponse(
            generations=[Generation(output=Message.assistant(content))],
            metadata={"provider": "fake", "call_count": self.call_count},
        )

    def stream(self, messages, tool_registry=None, options=None):
        """模拟流式：逐 2 字符 yield（不走工具闭环）"""
        resp = self._raw_call(messages, tool_registry, options)
        content = resp.content()
        for i in range(0, len(content), 2):
            yield ChatResponse(
                generations=[Generation(output=Message.assistant(content[i:i+2]))],
                metadata={"provider": "fake", "stream": True},
            )


class FakeEmbeddingModel(EmbeddingModel):
    """确定性嵌入模型 - 哈希到固定维度向量，测试用"""

    def __init__(self, dim: int = 8):
        self.dim = dim
        self.call_count = 0

    def embed(self, texts: List[str]) -> List[List[float]]:
        self.call_count += 1
        results = []
        for text in texts:
            vec = [0.0] * self.dim
            for i, ch in enumerate(text):
                vec[i % self.dim] += (ord(ch) % 10) / 10.0
            norm = sum(v * v for v in vec) ** 0.5
            if norm > 0:
                vec = [v / norm for v in vec]
            results.append(vec)
        return results
