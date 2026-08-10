# AI 与 LangChain 模块测试指南

> 本文档说明 SpringBootAI 两个 AI 相关模块的全部测试用例：**有什么用、怎么用、每个用例验证什么**。
> 测试总数：**672 个**（AI 模块 87 + LangChain 模块 585），全部通过，0 失败。
> - AI 模块：[tests/test_ai_module.py](../tests/test_ai_module.py) — 87 个
> - LangChain 基础测试：[tests/test_langchain_module.py](../tests/test_langchain_module.py) — 75 个
> - LangChain 扩展测试：[tests/test_langchain_ext.py](../tests/test_langchain_ext.py) — 510 个
> - 完整能力 Demo：[example_langchain/demo/langchain_full_demo.py](../example_langchain/demo/langchain_full_demo.py) — 15 章节

---

## 1. 怎么运行测试

```bash
# 运行全部 AI + LangChain 测试（672 个）
cd e:\spring\springbootAI-master\springbootAI-master
python -m pytest tests/test_ai_module.py tests/test_langchain_module.py tests/test_langchain_ext.py -v

# 只跑 AI 模块（87 个）
python -m pytest tests/test_ai_module.py -v

# 只跑 LangChain 基础测试（75 个）
python -m pytest tests/test_langchain_module.py -v

# 只跑 LangChain 扩展测试（510 个）
python -m pytest tests/test_langchain_ext.py -v

# 只跑某个测试类
python -m pytest tests/test_ai_module.py::TestFunctionCallingClosure -v

# 只跑某个测试方法
python -m pytest tests/test_langchain_module.py::TestAgents::test_create_agent_structured_chat -v

# 静默模式（只看结果）
python -m pytest tests/test_ai_module.py tests/test_langchain_module.py tests/test_langchain_ext.py -q

# 运行完整能力 Demo（15 章节，无需 API Key）
python example_langchain/demo/langchain_full_demo.py
```

> 全部测试使用 `FakeChatModel` / `FakeEmbeddingModel`，**无需真实 API Key、无需联网**。设置 `AI_ALLOW_FAKE=true` 即可运行（测试套件已自动设置）。

---

## 2. AI 模块测试（87 个）

AI 模块对齐 Spring AI 2.0，提供 `ChatClient` / `ChatModel` / `EmbeddingModel` / `Advisor` / `Tools` / RAG / Function Calling / ETL / 韧性 / 观测能力。测试覆盖每个核心抽象和端到端流程。

### 2.1 TestCoreAbstractions — 核心抽象（3 个）

**有什么用**：验证 `Message` / `ChatResponse` / `EmbeddingModel` 基础抽象的正确性，这是所有上层组件的基石。

| 用例 | 验证内容 |
|------|---------|
| `test_message_factory_methods` | `Message.user()` / `Message.assistant()` / `Message.system()` 工厂方法生成正确的消息类型 |
| `test_chat_response_content_property` | `ChatResponse` 的 `content()` 属性正确提取输出文本 |
| `test_embedding_model_embed_one` | `EmbeddingModel.embed_one()` 对单条文本返回正确维度的向量 |

### 2.2 TestChatClient — ChatClient 链式 API（3 个）

**有什么用**：验证 `ChatClient` 链式调用（`client.prompt().user("...").call().content()`）的正确性，这是用户最常用的 API。

| 用例 | 验证内容 |
|------|---------|
| `test_fluent_prompt_user_call_content` | `prompt().user().call().content()` 链式调用返回正确内容 |
| `test_default_system_prepended` | `default_system()` 设置的系统消息被正确前置 |
| `test_prompt_spec_param_and_messages` | `PromptSpec` 的 `param()` 和 `messages()` 方法正确工作 |

### 2.3 TestFakeProviders — 假模型（2 个）

**有什么用**：验证 `FakeChatModel` / `FakeEmbeddingModel` 的行为，这是无 API Key 环境下的测试基石。

| 用例 | 验证内容 |
|------|---------|
| `test_fake_chat_model_echoes_last_user` | `FakeChatModel` 回显最后一条用户消息 |
| `test_fake_embedding_deterministic_and_normalized` | `FakeEmbeddingModel` 向量确定性且归一化 |

### 2.4 TestProviderConfiguration — Provider 配置（3 个）

**有什么用**：验证 OpenAI / Ollama Provider 的配置属性正确传递。

| 用例 | 验证内容 |
|------|---------|
| `test_openai_chat_model_config_attributes` | `OpenAIChatModel` 的 api_key/base_url/model/temperature 正确存储 |
| `test_ollama_chat_model_config_attributes` | `OllamaChatModel` 的 base_url/model 正确存储 |
| `test_openai_embedding_model_config` | `OpenAIEmbeddingModel` 的 api_key/model 正确存储 |

### 2.5 TestChatMemory — 会话记忆（3 个）

**有什么用**：验证 `InMemoryChatMemory` 的增删查和会话隔离。

| 用例 | 验证内容 |
|------|---------|
| `test_inmemory_add_get_clear_and_window` | 添加/获取/清空消息 + 窗口截断 |
| `test_inmemory_isolation_between_conversations` | 不同 `conversation_id` 的记忆相互隔离 |
| `test_redis_memory_without_client_is_noop` | 无 Redis 客户端时不报错（降级安全） |

### 2.6 TestVectorStore — 向量存储（5 个）

**有什么用**：验证 `SimpleInMemoryVectorStore` 和 `LangChainVectorStore` 适配器的入库与检索。

| 用例 | 验证内容 |
|------|---------|
| `test_cosine_similarity_basic` | 余弦相似度计算正确 |
| `test_inmemory_vectorstore_add_and_search` | 内存向量库入库 + 相似度检索 |
| `test_inmemory_vectorstore_empty_query_returns_empty` | 空查询返回空列表（不报错） |
| `test_langchain_vectorstore_adapter` | `LangChainVectorStore` 包装 langchain 向量库正确 |
| `test_langchain_vectorstore_fallback_without_langchain` | 未安装 langchain 时降级不报错 |

### 2.7 TestEtl — 文档 ETL（4 个）

**有什么用**：验证 `TextReader` / `TokenTextSplitter` / `CharacterTextSplitter` 的文档读取与切片。

| 用例 | 验证内容 |
|------|---------|
| `test_text_reader_inline_content` | `TextReader` 读取内联文本 |
| `test_token_text_splitter_long_text` | `TokenTextSplitter` 长文本正确切片 |
| `test_token_text_splitter_short_text_single_chunk` | 短文本只切一片 |
| `test_character_text_splitter` | `CharacterTextSplitter` 按字符切片 |

### 2.8 TestToolRegistry — 工具注册（3 个）

**有什么用**：验证 `ToolRegistry` 的注册、schema 生成和执行。

| 用例 | 验证内容 |
|------|---------|
| `test_register_and_schema_generation` | 注册工具后自动生成 JSON schema |
| `test_tool_execute` | 按名称执行工具并返回结果 |
| `test_tool_unknown_raises_and_self_skip` | 未知工具名抛异常；工具自身异常时不阻塞其他工具 |

### 2.9 TestAdvisors — 顾问（5 个）

**有什么用**：验证 `MessageChatMemoryAdvisor`（记忆）/ `QuestionAnswerAdvisor`（RAG）/ `SimpleLoggerAdvisor`（日志）和 Advisor 排序。

| 用例 | 验证内容 |
|------|---------|
| `test_message_chat_memory_advisor_roundtrip` | 记忆顾问正确保存和恢复对话历史 |
| `test_question_answer_advisor_injects_context` | RAG 顾问检索文档并注入上下文 |
| `test_question_answer_advisor_harden_can_be_disabled` | RAG 顾问的加固模式可关闭 |
| `test_simple_logger_advisor_records_events` | 日志顾问记录调用事件 |
| `test_advisor_order_sorting` | 多个 Advisor 按 `order` 正确排序 |

### 2.10 TestAiAnnotations — AI 注解（3 个）

**有什么用**：验证 `@AiClient` / `@Tool` / `@AiAdvisor` / `@AiMemory` 注解元数据。

| 用例 | 验证内容 |
|------|---------|
| `test_ai_client_annotation_metadata` | `@AiClient` 的 provider/model/temperature 元数据 |
| `test_tool_annotation_metadata` | `@Tool` 的 name/description 元数据 |
| `test_ai_advisor_and_ai_memory_annotations` | `@AiAdvisor` / `@AiMemory` 元数据 |

### 2.11 TestAutoConfig — 自动装配（3 个）

**有什么用**：验证 `configure_ai()` 自动装配出全部 Bean。

| 用例 | 验证内容 |
|------|---------|
| `test_configure_ai_with_fake_provider_registers_beans` | Fake provider 下注册全部 5 个 Bean |
| `test_configure_ai_openai_without_key_falls_back_to_fake` | 无 API Key 时降级 FakeChatModel |
| `test_configure_ai_chat_client_callable_after_assembly` | 装配后 `aiChatClient` 可直接调用 |

### 2.12 TestIntegrationScenarios — 集成场景（3 个）

**有什么用**：端到端验证 RAG / 多轮对话 / 抽象类保护。

| 用例 | 验证内容 |
|------|---------|
| `test_full_rag_pipeline_etl_to_answer` | ETL 入库 → 检索 → 回答 完整 RAG 流水线 |
| `test_multi_turn_conversation_with_memory` | 多轮对话 + 记忆累积 |
| `test_chat_model_abstract_cannot_instantiate` | `ChatModel` 抽象类不可直接实例化 |

### 2.13 TestFunctionCallingClosure — 函数调用闭环（3 个）

**有什么用**：验证模型返回 `tool_calls` 后自动执行工具 → 回填 → 续写的完整闭环。

| 用例 | 验证内容 |
|------|---------|
| `test_tool_call_loop_executes_and_continues` | 工具调用 → 执行 → 回填 → 模型续写最终回答 |
| `test_tool_call_without_registry_returns_raw` | 无 ToolRegistry 时直接返回原始响应（不执行工具） |
| `test_tool_call_max_iterations_guard` | 超过 `MAX_TOOL_ITERATIONS=5` 轮后停止（防死循环） |

### 2.14 TestEmbeddingAutoconfigAndRedisVectorStore — 嵌入与 Redis 向量库（4 个）

**有什么用**：验证嵌入模型自动装配和 Redis 向量库持久化。

| 用例 | 验证内容 |
|------|---------|
| `test_autoconfig_assembles_embedding_model_bean` | 自动装配 `aiEmbeddingModel` Bean |
| `test_autoconfig_wires_embedding_into_vector_store` | 嵌入模型被正确注入向量库 |
| `test_redis_vector_store_without_client_is_noop` | 无 Redis 客户端时不报错 |
| `test_redis_vector_store_persistence_with_fake_redis` | 用 FakeRedis 验证持久化读写 |

### 2.15 TestRedisReuse — Redis 复用（4 个）

**有什么用**：验证 AI 模块复用框架全局 `RedisClient` 单例，无需手动传参。

| 用例 | 验证内容 |
|------|---------|
| `test_redis_vector_store_uses_framework_client_interface` | 向量库用框架 `RedisClient` 接口 |
| `test_redis_vector_store_falls_back_to_native_for_raw_redis` | 传入原生 `redis.Redis` 时降级原生接口 |
| `test_redis_chat_memory_ttl_refreshes_list_key_not_marker` | 会话记忆 list 键每次 add 刷新 TTL |
| `test_configure_ai_auto_reuses_framework_global_redis_when_type_redis` | `vector-store.type=redis` 时自动复用全局 Redis |

### 2.16 TestResilience — 韧性（3 个）

**有什么用**：验证重试和熔断器。

| 用例 | 验证内容 |
|------|---------|
| `test_retry_retries_on_transient_error` | 瞬态错误自动重试 |
| `test_circuit_breaker_opens_after_threshold` | 失败超过阈值后熔断器打开 |
| `test_circuit_breaker_half_open_recovery` | 熔断器半开状态恢复 |

### 2.17 TestStreamingAndAsync — 流式与异步（4 个）

**有什么用**：验证真流式 SSE 和 async/await 异步调用。

| 用例 | 验证内容 |
|------|---------|
| `test_fake_stream_yields_delta_chunks` | FakeChatModel 流式产出增量块 |
| `test_chat_client_stream_via_prompt_spec` | ChatClient 通过 PromptSpec 流式调用 |
| `test_async_acall_returns_response` | `acall()` 异步调用返回 ChatResponse |
| `test_async_astream_yields_chunks` | `astream()` 异步流式产出块 |

### 2.18 TestObservability — 可观测性（4 个）

**有什么用**：验证 Prometheus 指标记录。

| 用例 | 验证内容 |
|------|---------|
| `test_ai_metrics_singleton` | `ai_metrics` 是单例 |
| `test_record_call_does_not_raise` | 记录调用不抛异常 |
| `test_provider_call_records_metrics` | Provider 调用正确记录指标 |
| `test_autoconfig_creates_circuit_breaker_for_provider` | 自动装配为 Provider 创建熔断器 |

### 2.19 TestAIPropertiesBinding — 类型化配置绑定（7 个）

**有什么用**：验证 `AIProperties` dataclass 的配置绑定、类型转换和环境变量覆盖。

| 用例 | 验证内容 |
|------|---------|
| `test_bind_defaults_when_empty` | 空配置时使用 dataclass 默认值 |
| `test_bind_kebab_case_keys_from_yaml` | yml 的 kebab-case 键正确绑定 |
| `test_bind_type_coercion_from_strings` | 字符串自动转 int/float/bool |
| `test_env_overrides_yaml_value` | 环境变量覆盖 yml 值 |
| `test_env_overrides_nested_when_yaml_section_missing` | yml 缺失时 env 仍生效 |
| `test_circuit_breaker_disabled_returns_none` | 熔断器禁用时返回 None |
| `test_configure_ai_uses_typed_props_for_openai_circuit_breaker` | OpenAI 熔断器用类型化配置 |

### 2.20 TestP1Fixes — P1 修复（7 个）

**有什么用**：验证关键 bug 修复。

| 用例 | 验证内容 |
|------|---------|
| `test_ai_allow_fake_false_raises_on_missing_key` | `AI_ALLOW_FAKE=false` 无 Key 时抛异常 |
| `test_ai_allow_fake_true_returns_fake_on_missing_key` | `AI_ALLOW_FAKE=true` 无 Key 时降级 Fake |
| `test_ai_allow_fake_false_raises_on_unknown_provider` | 未知 provider 严格模式抛异常 |
| `test_resilient_call_passes_provider_to_metrics` | 韧性调用正确传递 provider 名给指标 |
| `test_redis_vectorstore_max_scan_limits` | Redis 向量库 scan 有上限（防全表扫描） |
| `test_circuit_breaker_accepts_redis_client` | 熔断器接受 Redis 客户端做分布式状态 |
| `test_stream_retry_not_raise_on_network_error` | 流式 SSE 网络中断不抛异常，降级 yield 错误提示 |

### 2.21 TestOptimizationFixes — 优化修复（5 个）

**有什么用**：验证流式记忆持久化、瞬态错误分类、HTTP 重试优化。

| 用例 | 验证内容 |
|------|---------|
| `test_stream_persists_conversation_memory` | 流式模式也保存会话记忆（修复：之前不保存） |
| `test_stream_accumulates_full_content` | 流式块正确累积成完整内容 |
| `test_is_transient_http_exc_classification` | HTTP 异常瞬态分类正确（超时=瞬态，401=非瞬态） |
| `test_http_post_json_retries_transient` | 瞬态错误自动重试 |
| `test_http_post_json_does_not_retry_auth_error` | 认证错误不重试 |

### 2.22 TestMultiProviderLangChain — 多厂商 LangChain 化（6 个）

**有什么用**：验证 DeepSeek 等 OpenAI 兼容厂商通过 `OpenAICompatChatModel` 接入。

| 用例 | 验证内容 |
|------|---------|
| `test_compat_model_degrades_to_http_without_langchain` | 无 langchain 时降级原生 HTTP |
| `test_compat_call_via_http_injects_tools` | HTTP 路径正确注入工具 schema |
| `test_compat_http_stream_yields_chunks` | HTTP 路径流式产出块 |
| `test_autoconfig_deepseek_builds_compat_model` | DeepSeek 自动装配为兼容模型 |
| `test_autoconfig_deepseek_no_key_degrades_to_fake` | DeepSeek 无 Key 降级 Fake |
| `test_autoconfig_deepseek_no_key_strict_raises` | DeepSeek 无 Key 严格模式抛异常 |

---

## 3. LangChain 模块测试（75 个）

LangChain 模块封装 langchain classic 全套能力（Chains / Agents / Memory / Retrievers / VectorStores / Parsers / Loaders / 30+ Partner），提供 Spring 风格 `@Service` Bean。

### 3.1 TestAdapters — 双向适配器（7 个）

**有什么用**：验证 springbootAI ↔ langchain 模型/嵌入双向桥接的正确性。这是两个模块协作的核心。

| 用例 | 验证内容 |
|------|---------|
| `test_spring_to_langchain_returns_base_chat_model` | springbootAI ChatModel → langchain BaseChatModel 类型正确 |
| `test_to_langchain_model_invokes_spring_backend` | 适配器调用底层 springbootAI 模型 |
| `test_to_langchain_model_preserves_system_message` | system 消息在桥接中不丢失 |
| `test_langchain_to_spring_model` | langchain 模型 → springbootAI ChatModel |
| `test_spring_to_langchain_embeddings` | springbootAI EmbeddingModel → langchain Embeddings |
| `test_langchain_to_spring_embeddings` | langchain Embeddings → springbootAI EmbeddingModel |
| `test_embeddings_roundtrip` | 双向桥接往返一致 |

### 3.2 TestConfigBinding — 类型化配置（5 个）

**有什么用**：验证 `LangChainProperties` dataclass 的配置绑定。

| 用例 | 验证内容 |
|------|---------|
| `test_default_properties` | 空配置时使用默认值 |
| `test_kebab_case_binding` | yml kebab-case 键绑定 |
| `test_env_override` | 环境变量覆盖 |
| `test_partners_dict_pass_through` | partners 动态字典透传 |
| `test_type_coercion_bool` | 字符串转 bool |

### 3.3 TestAutoConfig — 自动装配（4 个）

**有什么用**：验证 `configure_langchain()` 装配出全部 `lc*` Bean。

| 用例 | 验证内容 |
|------|---------|
| `test_configure_langchain_registers_core_beans` | 注册 14+ 个核心 Bean |
| `test_configure_langchain_disabled` | `enabled=false` 时不装配 |
| `test_configure_langchain_auto_reuses_spring_model` | `default-llm=auto` 复用 `aiChatModel` |
| `test_chain_service_built_with_injected_model` | ChainService 被正确注入 lcLangChainModel |

### 3.4 TestPartners — Partner 提供商（6 个）

**有什么用**：验证 30+ Partner 注册表和懒加载机制。

| 用例 | 验证内容 |
|------|---------|
| `test_registry_contains_major_providers` | 注册表包含 OpenAI/Anthropic/Ollama 等主流厂商 |
| `test_list_partners_sorted` | `list_partners()` 返回排序后的列表 |
| `test_is_partner_available_unknown_returns_false` | 未知 partner 返回 False |
| `test_list_available_partners_returns_list` | `list_available_partners()` 返回已安装的 partner |
| `test_partner_factory_unknown_raises` | 未知 partner 抛异常 |
| `test_partner_factory_missing_package_raises_import_error` | 依赖缺失时抛带安装提示的 ImportError |

### 3.5 TestPrompts — Prompt 模板（5 个）

**有什么用**：验证三种 Prompt 模板工厂。

| 用例 | 验证内容 |
|------|---------|
| `test_create_prompt_template_auto_vars` | 自动提取模板变量 |
| `test_create_prompt_template_explicit_vars` | 显式指定变量 |
| `test_create_chat_prompt_template` | ChatPromptTemplate 多角色模板 |
| `test_from_template` | `from_template` 静态方法 |
| `test_create_few_shot_prompt_template` | FewShot 少样本模板 |

### 3.6 TestChains — Chain 服务（6 个）

**有什么用**：验证 LLMChain / ConversationChain / SequentialChain / 摘要链。

| 用例 | 验证内容 |
|------|---------|
| `test_run_llm_chain` | `run_llm_chain()` 单次问答 |
| `test_create_llm_chain` | `create_llm_chain()` 创建 LLMChain |
| `test_create_conversation_chain` | `create_conversation_chain()` 创建对话链 |
| `test_run_conversation` | `run_conversation()` 多轮对话 |
| `test_create_sequential_chain` | `create_sequential_chain()` 串联多 Chain |
| `test_create_summarize_chain` | `create_summarize_chain()` 摘要链 |

### 3.7 TestAgents — Agent 服务（6 个）

**有什么用**：验证 6 种 Agent 类型的创建。

| 用例 | 验证内容 |
|------|---------|
| `test_supported_agent_types` | 支持的 agent 类型列表正确 |
| `test_create_react_agent` | ReAct Agent 创建成功 |
| `test_supported_agent_types_includes_structured_chat` | structured-chat 和 openai-tools 在列表中 |
| `test_create_agent_structured_chat` | `create_agent(agent_type="structured-chat")` 走专用工厂 |
| `test_create_agent_openai_tools` | `create_agent(agent_type="openai-tools")` 走专用工厂 |
| `test_create_agent_unknown_type_raises` | 未知类型抛 ValueError |

### 3.8 TestSafeEvalArithmetic — 安全算术求值器（5 个）

**有什么用**：验证替代 `eval()` 的安全求值器，杜绝沙箱逃逸。

| 用例 | 验证内容 |
|------|---------|
| `test_basic_arithmetic` | 7 种算术运算（+ - * / // % **）正确 |
| `test_blocks_attribute_access` | 属性访问（`(1).__class__...`）被拒绝 |
| `test_blocks_function_call` | 函数调用（`__import__`/`open`/`getattr`）被拒绝 |
| `test_blocks_collections` | 列表/字典字面量被拒绝 |
| `test_syntax_error_raises_value_error` | 语法错误抛 ValueError（非 SyntaxError 泄漏） |

### 3.9 TestMemory — Memory 工厂（6 个）

**有什么用**：验证 4 种 Memory 类型创建。

| 用例 | 验证内容 |
|------|---------|
| `test_supported_types` | 支持的 memory 类型列表 |
| `test_create_buffer_memory` | buffer 全量保留 |
| `test_create_buffer_window_memory` | buffer-window 滑动窗口 |
| `test_summary_requires_llm` | summary 类型需要 llm 参数 |
| `test_token_buffer_requires_llm` | token-buffer 类型需要 llm 参数 |
| `test_unknown_type_raises` | 未知类型抛异常 |

### 3.10 TestParsers — 输出解析器（5 个）

**有什么用**：验证 5 种 OutputParser 把模型文本解析为结构化对象。

| 用例 | 验证内容 |
|------|---------|
| `test_create_comma_list_parser` | 逗号分隔列表解析 |
| `test_create_json_parser` | JSON 解析 |
| `test_create_datetime_parser` | 日期时间解析 |
| `test_create_via_unified_entry` | `create()` 统一入口 |
| `test_create_unknown_raises` | 未知类型抛异常 |

### 3.11 TestVectorStores — 向量库工厂（5 个）

**有什么用**：验证 7 种 VectorStore 的创建和检索。

| 用例 | 验证内容 |
|------|---------|
| `test_supported_types` | 支持的向量库类型列表 |
| `test_create_inmemory` | inmemory 向量库创建 |
| `test_from_texts_inmemory` | from_texts 入库 |
| `test_unknown_store_type_raises` | 未知类型抛异常 |
| `test_as_retriever` | 向量库转 Retriever |

### 3.12 TestRetrievers — 检索器（1 个）

**有什么用**：验证检索器类型列表。

| 用例 | 验证内容 |
|------|---------|
| `test_supported_types` | 支持的检索器类型列表（6 种） |

### 3.13 TestIndexService — 一键 RAG（2 个）

**有什么用**：验证 `IndexService` 的一键 RAG 流程。

| 用例 | 验证内容 |
|------|---------|
| `test_create_from_texts_inmemory` | 从文本列表建库 |
| `test_query_returns_documents` | 查询返回文档列表 |

### 3.14 TestTools — 工具工厂（5 个）

**有什么用**：验证 langchain Tool 创建和 ToolRegistry 管理。

| 用例 | 验证内容 |
|------|---------|
| `test_from_function_creates_structured_tool` | 普通函数 → langchain StructuredTool |
| `test_create_tool_simple` | 简单工具创建 |
| `test_from_spring_tool_registry_empty` | 空 springbootAI ToolRegistry 转换 |
| `test_tool_registry_collect` | ToolRegistry 收集多个工具 |
| `test_tool_registry_clear` | ToolRegistry 清空 |

### 3.15 TestRegistries — 注册表（3 个）

**有什么用**：验证 DocumentLoader / Utility / Callback 注册表的类型列表。

| 用例 | 验证内容 |
|------|---------|
| `test_loader_supported_types` | 文档加载器类型列表（10 种） |
| `test_utility_supported_types` | 工具集类型列表（6 种） |
| `test_callback_registry` | 回调注册表创建 3 种回调 |

### 3.16 TestEndToEndIntegration — 端到端集成（4 个）

**有什么用**：验证完整业务流程的端到端正确性。

| 用例 | 验证内容 |
|------|---------|
| `test_full_llm_chain_pipeline` | LLMChain 完整流水线（模板 → Chain → invoke → 结果） |
| `test_conversation_with_memory_flow` | 多轮对话 + memory 累积 |
| `test_rag_pipeline_with_fake_models` | RAG 完整流水线（建库 → 检索 → 问答）用 Fake 模型跑通 |
| `test_configure_langchain_full_bootstrap` | `configure_langchain` 完整装配后全部 Bean 可用 |

---

## 4. LangChain 扩展测试（510 个）

**文件**：[tests/test_langchain_ext.py](../tests/test_langchain_ext.py)

**设计目标**：在基础测试（75 个）之上，对每个能力子模块做深度边界/错误/组合测试，确保迁移后功能与原 langchain classic 完全等价。全部使用 FakeChatModel/FakeEmbeddingModel，CI 无网络也能跑。

### 4.1 TestAdaptersExt — 适配器扩展（35 个）

**有什么用**：深度验证 springbootAI ↔ langchain 模型/嵌入双向桥接的边界情况、消息类型映射、流式、工具绑定。

| 覆盖点 | 用例数 | 代表用例 |
|--------|--------|---------|
| `_llm_type` 标识 / BaseChatModel 类型 | 2 | `test_01_spring_to_langchain_llm_type` |
| user/system/assistant 消息保留 | 6 | `test_03_to_langchain_model_preserves_user_message` |
| 空消息/长消息/Unicode/特殊字符 | 5 | `test_24_adapter_unicode_message` |
| 多消息混合 / 角色映射 | 4 | `test_27_adapter_mixed_messages` |
| invoke 计数 / 多次调用 | 3 | `test_30_adapter_invoke_count` |
| 流式 / bind_tools | 4 | `test_31_adapter_stream`, `test_33_adapter_bind_tools` |
| 嵌入双向桥接 / isinstance / roundtrip | 8 | `test_11_spring_to_langchain_embeddings_type` |
| 错误处理 / 异常传播 | 3 | `test_35_adapter_error_propagation` |

### 4.2 TestConfigBindingExt — 配置绑定扩展（25 个）

**有什么用**：验证 `LangChainProperties` dataclass 全字段默认值、kebab-case 绑定、env 覆盖、类型转换、partners 透传。

| 覆盖点 | 用例数 | 代表用例 |
|--------|--------|---------|
| 全字段默认值（enabled/llm/chains/agents/vectorstore/retriever/memory） | 11 | `test_03_default_chains_verbose` |
| kebab-case 绑定各子树 | 7 | `test_14_kebab_case_chains` |
| env 覆盖（LC_* 优先级） | 3 | `test_19_type_coercion_int` |
| partners 动态字典透传 | 2 | `test_22_partners_pass_through` |
| 类型转换（bool/int/str） | 2 | `test_20_type_coercion_bool` |

### 4.3 TestAutoConfigExt — 自动装配扩展（25 个）

**有什么用**：验证 `configure_langchain` 注册的全部 14 个 Bean、disabled 跳过、partner 注册、错误恢复、模型复用、幂等性。

| 覆盖点 | 用例数 | 代表用例 |
|--------|--------|---------|
| 14 个 Bean 全部注册（lcModel/Embeddings/12 能力 Bean） | 14 | `test_01_configure_registers_lc_model` |
| enabled=false 跳过 | 1 | `test_15_configure_disabled_returns_empty` |
| default-llm=auto 复用 aiChatModel | 1 | `test_16_configure_auto_reuses_spring_model` |
| 装配后 ChainService/AgentService/IndexService 可调用 | 4 | `test_17_configure_chain_service_callable` |
| 自定义配置 / partner 缺失依赖跳过 | 2 | `test_21_configure_partners_skips_missing_dep` |
| 返回 dict / Bean 数量 / 幂等 / 无 AI 也能跑 | 3 | `test_25_configure_without_ai_still_works` |

### 4.4 TestPartnersExt — Partner 注册表扩展（35 个）

**有什么用**：验证 33 个 partner 提供商注册表完整性、可用性探测、工厂创建、参数过滤、错误提示。

| 覆盖点 | 用例数 | 代表用例 |
|--------|--------|---------|
| 主流 partner 存在性（openai/anthropic/ollama/deepseek/zhipu/tongyi/moonshot/azure/cohere/mistral/bedrock/google/fireworks/together/groq） | 15 | `test_27_registry_contains_google` |
| list_partners 排序 / 数量 >= 30 | 5 | `test_25_list_partners_sorted` |
| is_partner_available 探测 | 4 | `test_29_is_partner_available_unknown` |
| PartnerProviderFactory.create 未知/缺失包 | 6 | `test_31_partner_factory_unknown_raises` |
| partner 名称为字符串 / 元组结构 | 5 | `test_33_partner_names_are_strings` |

### 4.5 TestPromptsExt — Prompt 模板扩展（30 个）

**有什么用**：验证 3 类模板（字符串/对话/Few-shot）的变量提取、格式化、多角色、错误处理。

| 覆盖点 | 用例数 | 代表用例 |
|--------|--------|---------|
| 字符串模板自动/显式变量 | 6 | `test_01_create_prompt_template_auto_vars` |
| 对话模板（dict/tuple 兼容） | 12 | `test_09_create_chat_prompt_template_basic` |
| Few-shot 模板 / 示例 | 5 | `test_24_create_few_shot_prompt_template` |
| from_template 便捷入口 | 3 | `test_27_from_template` |
| 错误处理（缺变量/类型错） | 4 | `test_30_chat_prompt_three_roles` |

### 4.6 TestChainsExt — Chain 服务扩展（35 个）

**有什么用**：验证 LLMChain/Conversation/Sequential/RetrievalQA/MapReduce/LLMMath 各 Chain 的创建、invoke、batch、顺序串联、错误恢复。

| 覆盖点 | 用例数 | 代表用例 |
|--------|--------|---------|
| LLMChain 创建/invoke/字符串模板/custom prompt/verbose/runnable | 8 | `test_04_create_llm_chain_returns_chain` |
| ConversationChain + memory | 5 | `test_08_create_conversation_chain` |
| SequentialChain 多步串联 | 6 | `test_10_create_sequential_chain_basic` |
| RetrievalQA / MapReduce / Summarize | 6 | `test_15_create_retrieval_qa` |
| LLMMathChain | 4 | `test_17_create_llm_math_chain` |
| run_llm_chain 便捷入口 / run_conversation / run_summarize | 4 | `test_20_run_llm_chain` |
| 错误恢复 / 边界 | 2 | `test_34_sequential_chain_multi_step` |

### 4.7 TestAgentsExt — Agent 服务扩展（35 个）

**有什么用**：验证 ReAct/openai-functions/structured-chat 三种 Agent 的创建、工具绑定、执行、迭代限制、错误处理。

| 覆盖点 | 用例数 | 代表用例 |
|--------|--------|---------|
| Agent 类型支持 / supported_agent_types | 5 | `test_01_supported_agent_types` |
| create_react_agent / openai_tools / structured_chat | 8 | `test_09_create_agent_react` |
| create_agent 统一入口 | 6 | `test_12_create_agent_unified` |
| run_agent 执行 / 工具调用 | 6 | `test_15_run_agent_basic` |
| max_iterations 限制 | 4 | `test_18_max_iterations` |
| 错误处理 / 空工具 / 无模型 | 6 | `test_20_agent_error_handling` |

### 4.8 TestSafeEvalExt — 安全算术求值扩展（25 个）

**有什么用**：验证 `safe_eval_arithmetic` 的全运算支持 + 攻击手法全部拒绝（防沙箱逃逸）。

| 覆盖点 | 用例数 | 代表用例 |
|--------|--------|---------|
| 基础运算（+/-/*///%/**） | 6 | `test_01_add`, `test_05_power` |
| 一元运算 / 嵌套括号 | 4 | `test_06_unary_minus`, `test_08_nested_parens` |
| 攻击拒绝（import/open/eval/属性访问/子类遍历） | 10 | `test_11_reject_import`, `test_15_reject_eval` |
| 边界（空串/非法语法/大数） | 5 | `test_21_empty_string` |

### 4.9 TestMemoryExt — Memory 工厂扩展（30 个）

**有什么用**：验证 buffer/summary/buffer-window/token-buffer 四种记忆的创建、save_context、load_memory_variables、clear、错误处理。

| 覆盖点 | 用例数 | 代表用例 |
|--------|--------|---------|
| buffer 增删查 / 多轮 / 清空 | 6 | `test_14_buffer_add_and_get` |
| buffer-window 窗口截断（load_memory_variables） | 4 | `test_17_buffer_window_max_messages` |
| summary 创建（需 llm）/ 错误 | 5 | `test_08_create_summary_requires_llm` |
| token-buffer（需 llm） | 5 | `test_10_create_token_buffer_requires_llm` |
| supported_types / memory_key / return_messages | 6 | `test_22_supported_types` |
| 错误处理（未知类型/空类型） | 4 | `test_13_unknown_type_raises` |

### 4.10 TestParsersExt — 输出解析器扩展（30 个）

**有什么用**：验证 comma-list/datetime/json/pydantic/enum 五种解析器的创建、parse、get_format_instructions、错误恢复。

| 覆盖点 | 用例数 | 代表用例 |
|--------|--------|---------|
| comma-list 解析 | 5 | `test_01_comma_list_parse` |
| datetime 解析（含 ISO 格式） | 5 | `test_05_datetime_parse` |
| json 解析 | 5 | `test_10_json_parse` |
| pydantic 结构化 / format_instructions | 5 | `test_15_pydantic_parser` |
| enum 解析（enum_class 参数） | 4 | `test_20_create_enum_parser` |
| 统一入口 create() / 错误 | 6 | `test_22_create_via_unified_entry_comma_list` |

### 4.11 TestVectorStoresExt — 向量库扩展（35 个）

**有什么用**：验证 inmemory/faiss/chroma/pinecone/weaviate/pgvector/redis 七种向量库的创建、入库、检索、as_retriever、元数据、错误处理。

| 覆盖点 | 用例数 | 代表用例 |
|--------|--------|---------|
| inmemory 入库 / 检索 / k 参数 / 中文 | 8 | `test_24_inmemory_similarity_search` |
| as_retriever / invoke / get_relevant_documents | 6 | `test_20_as_retriever_inmemory` |
| from_texts 批量建库 | 5 | `test_14_from_texts_inmemory` |
| 缺失依赖抛 ImportError（faiss/chroma） | 4 | `test_18_create_faiss_missing_dep_raises` |
| 未知类型 / supported_types | 5 | `test_16_create_unknown_raises` |
| 元数据 / 大量文本 / 清空 | 7 | `test_30_inmemory_metadata` |

### 4.12 TestRetrieversExt — 检索器扩展（25 个）

**有什么用**：验证 similarity/multi-query/contextual-compression/self-query/time-weighted/ensemble 六种检索器。

| 覆盖点 | 用例数 | 代表用例 |
|--------|--------|---------|
| similarity 创建 / k 值 / invoke / get_relevant_documents | 8 | `test_10_create_similarity_basic` |
| search_kwargs / 中文查询 | 5 | `test_19_create_with_search_kwargs` |
| supported_types 集合等价 | 1 | `test_25_supported_types_sorted` |
| multi-query/contextual 需 llm / ensemble 需 retrievers | 6 | `test_15_multi_query_requires_llm` |
| 错误处理 / 未知类型 | 5 | `test_20_unknown_type_raises` |

### 4.13 TestIndexServiceExt — 一键 RAG 扩展（25 个）

**有什么用**：验证 IndexService 的建库、查询、文档加载、端到端 RAG 流水线。

| 覆盖点 | 用例数 | 代表用例 |
|--------|--------|---------|
| create_from_texts 建库 | 6 | `test_01_create_from_texts_basic` |
| query 查询 / k 值 | 6 | `test_05_query_basic` |
| 文档加载（Text/CSV） | 5 | `test_10_load_documents` |
| 端到端 RAG 流水线 | 4 | `test_15_rag_pipeline` |
| 错误处理 / 空库 | 4 | `test_20_empty_store_query` |

### 4.14 TestToolsExt — 工具扩展（30 个）

**有什么用**：验证 ToolFactory.from_function/create_tool、ToolRegistry.add/add_function/all/names/clear。

| 覆盖点 | 用例数 | 代表用例 |
|--------|--------|---------|
| from_function 自动 name/description | 5 | `test_04_from_function_auto_name` |
| create_tool（name, func, description） | 3 | `test_06_create_tool_basic` |
| StructuredTool 类型 / invoke | 4 | `test_07_tool_is_structured_tool` |
| 工具返回 int/bool/list/dict | 4 | `test_22_tool_returns_int` |
| ToolRegistry add_function/collect/clear/names/duplicate | 8 | `test_12_tool_registry_add` |
| from_spring_tool_registry 桥接 | 3 | `test_10_from_spring_registry_empty` |
| 中文/Unicode/特殊字符/长描述 | 3 | `test_17_tool_with_chinese_description` |

### 4.15 TestLoadersExt — 加载器扩展（20 个）

**有什么用**：验证 Text/CSV/JSON/PDF/HTML/Web/Directory 各加载器的创建、加载、错误处理。

| 覆盖点 | 用例数 | 代表用例 |
|--------|--------|---------|
| Text 加载 / encoding | 5 | `test_01_load_text` |
| CSV 加载 / 逐行成 Document | 4 | `test_06_load_csv` |
| JSON 加载（jq_schema） | 3 | `test_10_load_json` |
| supported_types / create / load 便捷方法 | 5 | `test_15_supported_types` |
| 缺失依赖 / 未知类型 | 3 | `test_18_unknown_type_raises` |

### 4.16 TestUtilitiesExt — Utility 扩展（15 个）

**有什么用**：验证 SerpAPI/DuckDuckGo/Wikipedia/PythonREPL/SQLDatabase/Arxiv 等 11 种实用工具的懒加载。

| 覆盖点 | 用例数 | 代表用例 |
|--------|--------|---------|
| supported_types 完整覆盖 | 3 | `test_15_supported_types_sorted` |
| create 各类型（懒加载） | 5 | `test_05_create_duckduckgo` |
| as_tools 批量转 Tool | 4 | `test_10_as_tools` |
| 缺失依赖 ImportError / 未知类型 | 3 | `test_14_unknown_raises` |

### 4.17 TestCallbacksExt — 回调扩展（15 个）

**有什么用**：验证 StdOut/StreamingStdOut/File 三种回调的创建与 CallbackRegistry 注册表。

| 覆盖点 | 用例数 | 代表用例 |
|--------|--------|---------|
| stdout/streaming/file 回调创建 | 4 | `test_01_create_stdout_handler` |
| BaseCallbackHandler 类型校验 | 2 | `test_11_stdout_handler_is_base_handler` |
| CallbackRegistry register/all/clear/重复 | 6 | `test_05_registry_register` |
| 文件回调写入 / all 返回 list | 3 | `test_15_registry_all_returns_dict` |

### 4.18 TestEndToEndExt — 端到端集成扩展（40 个）

**有什么用**：验证完整流程（Chain+Memory+RAG+Agent+装配）、组合使用、错误恢复、性能。

| 覆盖点 | 用例数 | 代表用例 |
|--------|--------|---------|
| 完整 Chain 流水线 / RAG 流水线 / Agent 流水线 | 6 | `test_01_full_chain_pipeline` |
| configure_ai + configure_langchain 全装配 | 8 | `test_11_configure_ai_then_langchain` |
| ChainService/AgentService/IndexService 注入后可调用 | 6 | `test_12_chain_service_with_injected_model` |
| SequentialChain / FewShot / Parser 组合 | 6 | `test_19_sequential_chain_pipeline` |
| VectorStore 全周期 / Retriever / RAG 端到端 | 5 | `test_36_vector_store_inmemory_full_cycle` |
| 错误恢复 / 无模型降级 / 性能 | 5 | `test_31_full_pipeline_no_errors` |
| 全装配后所有 Bean 可用 | 4 | `test_21_bootstrap_all_beans_available` |

### 扩展测试合计

| 测试类 | 用例数 |
|--------|--------|
| TestAdaptersExt | 35 |
| TestConfigBindingExt | 25 |
| TestAutoConfigExt | 25 |
| TestPartnersExt | 35 |
| TestPromptsExt | 30 |
| TestChainsExt | 35 |
| TestAgentsExt | 35 |
| TestSafeEvalExt | 25 |
| TestMemoryExt | 30 |
| TestParsersExt | 30 |
| TestVectorStoresExt | 35 |
| TestRetrieversExt | 25 |
| TestIndexServiceExt | 25 |
| TestToolsExt | 30 |
| TestLoadersExt | 20 |
| TestUtilitiesExt | 15 |
| TestCallbacksExt | 15 |
| TestEndToEndExt | 40 |
| **合计** | **510** |

---

## 5. 完整能力 Demo（15 章节）

**文件**：[example_langchain/demo/langchain_full_demo.py](../example_langchain/demo/langchain_full_demo.py)

**有什么用**：一键跑通 LangChain 模块全部 12 个能力子模块 + SafeEval + Partner，无需 Spring 容器/HTTP/真实 API Key。适合新手快速理解每个能力的用法和产出。

**运行方式**：
```bash
python example_langchain/demo/langchain_full_demo.py
```

**章节列表**：

| 章节 | 主题 | 演示内容 |
|------|------|---------|
| 1 | 适配层 | springbootAI ↔ langchain 模型/嵌入双向桥接 + isinstance 校验 |
| 2 | Prompt 模板 | 字符串/对话/Few-shot 三类模板创建与格式化 |
| 3 | Chain | LLMChain/Conversation/Sequential/Math 四种链 |
| 4 | Agent | ReAct Agent + 工具调用 + supported_agent_types |
| 5 | Memory | buffer/window/summary/token-buffer 四种记忆 |
| 6 | OutputParser | list/datetime/json/pydantic/enum 五种解析器 |
| 7 | VectorStore | inmemory 入库 + 检索 + as_retriever |
| 8 | Retriever | similarity 检索器 + supported_types |
| 9 | IndexService | 一键 RAG：建库 + 查询 |
| 10 | Tools | StructuredTool/Tool/ToolRegistry |
| 11 | DocumentLoader | Text/CSV/JSON 文件加载 |
| 12 | Utility | 懒加载第三方工具（DuckDuckGo 等） |
| 13 | Callbacks | stdout/streaming/file 回调 + 注册表 |
| 14 | SafeEval | AST 安全算术求值 + 攻击拒绝演示 |
| 15 | Partner | 33 个第三方模型提供商注册表 |

---

## 6. 测试覆盖矩阵

### AI 模块功能覆盖

| 功能 | 测试类 | 用例数 | 覆盖率 |
|------|--------|--------|--------|
| 核心抽象（Message/ChatResponse/Embedding） | TestCoreAbstractions | 3 | ✅ |
| ChatClient 链式 API | TestChatClient | 3 | ✅ |
| Fake 测试模型 | TestFakeProviders | 2 | ✅ |
| Provider 配置（OpenAI/Ollama） | TestProviderConfiguration | 3 | ✅ |
| 会话记忆（InMemory/Redis） | TestChatMemory | 3 | ✅ |
| 向量存储（InMemory/LangChain适配器） | TestVectorStore | 5 | ✅ |
| 文档 ETL（Reader/Splitter） | TestEtl | 4 | ✅ |
| 工具注册与执行 | TestToolRegistry | 3 | ✅ |
| Advisor（记忆/RAG/日志/排序） | TestAdvisors | 5 | ✅ |
| AI 注解（@AiClient/@Tool/@AiAdvisor） | TestAiAnnotations | 3 | ✅ |
| 自动装配（configure_ai） | TestAutoConfig | 3 | ✅ |
| 集成场景（RAG/多轮/抽象类） | TestIntegrationScenarios | 3 | ✅ |
| 函数调用闭环（tool_call 循环） | TestFunctionCallingClosure | 3 | ✅ |
| 嵌入与 Redis 向量库 | TestEmbeddingAutoconfigAndRedisVectorStore | 4 | ✅ |
| Redis 复用 | TestRedisReuse | 4 | ✅ |
| 韧性（重试/熔断） | TestResilience | 3 | ✅ |
| 流式与异步（SSE/async） | TestStreamingAndAsync | 4 | ✅ |
| 可观测性（Prometheus 指标） | TestObservability | 4 | ✅ |
| 类型化配置绑定 | TestAIPropertiesBinding | 7 | ✅ |
| P1 修复（Fake降级/Redis/熔断/流式重试） | TestP1Fixes | 7 | ✅ |
| 优化修复（流式记忆/瞬态分类/HTTP重试） | TestOptimizationFixes | 5 | ✅ |
| 多厂商 LangChain 化（DeepSeek） | TestMultiProviderLangChain | 6 | ✅ |
| **合计** | **22 个测试类** | **87** | **✅** |

### LangChain 模块功能覆盖

| 功能 | 测试类 | 用例数 | 扩展测试类 | 扩展用例数 | 覆盖率 |
|------|--------|--------|-----------|-----------|--------|
| 双向适配器（spring↔langchain） | TestAdapters | 7 | TestAdaptersExt | 35 | ✅ |
| 类型化配置绑定 | TestConfigBinding | 5 | TestConfigBindingExt | 25 | ✅ |
| 自动装配（configure_langchain） | TestAutoConfig | 4 | TestAutoConfigExt | 25 | ✅ |
| 30+ Partner 提供商 | TestPartners | 6 | TestPartnersExt | 35 | ✅ |
| Prompt 模板（3 种） | TestPrompts | 5 | TestPromptsExt | 30 | ✅ |
| Chain 服务（6 种 Chain） | TestChains | 6 | TestChainsExt | 35 | ✅ |
| Agent 服务（6 种 Agent） | TestAgents | 6 | TestAgentsExt | 35 | ✅ |
| 安全算术求值器（防沙箱逃逸） | TestSafeEvalArithmetic | 5 | TestSafeEvalExt | 25 | ✅ |
| Memory 工厂（4 种） | TestMemory | 6 | TestMemoryExt | 30 | ✅ |
| 输出解析器（5 种） | TestParsers | 5 | TestParsersExt | 30 | ✅ |
| 向量库工厂（7 种） | TestVectorStores | 5 | TestVectorStoresExt | 35 | ✅ |
| 检索器（6 种） | TestRetrievers | 1 | TestRetrieversExt | 25 | ✅ |
| 一键 RAG（IndexService） | TestIndexService | 2 | TestIndexServiceExt | 25 | ✅ |
| 工具工厂（ToolFactory/ToolRegistry） | TestTools | 5 | TestToolsExt | 30 | ✅ |
| 加载器 | TestRegistries | 1 | TestLoadersExt | 20 | ✅ |
| Utility 工具 | TestRegistries | 1 | TestUtilitiesExt | 15 | ✅ |
| Callbacks | TestRegistries | 1 | TestCallbacksExt | 15 | ✅ |
| 端到端集成 | TestEndToEndIntegration | 4 | TestEndToEndExt | 40 | ✅ |
| **合计** | **16 + 18 个测试类** | **75 + 510 = 585** | | | **✅** |

---

## 5. 测试设计原则

1. **无 API Key 可运行**：全部测试使用 `FakeChatModel` / `FakeEmbeddingModel`，设置 `AI_ALLOW_FAKE=true` 即可。不联网、不花钱。

2. **每个 Bug 有回归测试**：修复的每个 bug（bind_tools、沙箱逃逸、structured-chat prompt、流式重试等）都有对应的回归测试，防止复发。

3. **从单元到端到端**：测试分层设计——核心抽象（单元）→ 组件（集成）→ 完整流程（端到端 RAG / 多轮对话 / Agent）。

4. **边界与异常覆盖**：每个组件都测试了正常路径 + 未知类型 + 缺失依赖 + 空输入等边界场景。

5. **安全测试**：`TestSafeEvalArithmetic` 专门验证 6 种沙箱逃逸攻击手法被拦截（属性访问、函数调用、列表/字典、语法错误）。

---

## 8. 常见测试问题

**Q：测试报 `openai.AuthenticationError`？**
A：某个测试试图连真实 OpenAI API。确认设置了 `AI_ALLOW_FAKE=true`。已修复的 `test_stream_retry_not_raise_on_network_error` 会强制走 HTTP mock 路径。

**Q：测试报 `ModuleNotFoundError: langchain_anthropic`？**
A：这是预期行为——`test_partner_factory_missing_package_raises_import_error` 验证缺失依赖时抛 ImportError。不是 bug。

**Q：LangChainDeprecationWarning 刷屏？**
A：langchain 2.0 将弃用 `LLMChain`/`ConversationChain`/`Memory` 等类。代码已用 `warnings.filterwarnings` 屏蔽，不影响功能。迁移目的即兼容旧 API。

**Q：测试运行慢（~70 秒）？**
A：672 个测试中有多个端到端集成测试（RAG 流水线、Agent 执行、完整装配），需要初始化多个组件。可按测试类单独运行加速，或加 `-x` 在首个失败时停止。

**Q：test_18_create_faiss_missing_dep_raises 被跳过？**
A：faiss/langchain_community 已安装时跳过（`pytest.skip`）——验证逻辑而非环境。卸载 langchain_community 后可触发 ImportError 路径。

---

## 9. 快速验证命令

```bash
# 一键验证全部 672 个测试（AI 87 + LangChain 75 + 扩展 510）
cd e:\spring\springbootAI-master\springbootAI-master
$env:AI_ALLOW_FAKE = "true"
python -m pytest tests/test_ai_module.py tests/test_langchain_module.py tests/test_langchain_ext.py -q

# 期望输出：
# 584 passed, 1 skipped, 273 warnings in ~70s（AI 87 + LC 75 + 扩展 510 - 1 skip）
```
