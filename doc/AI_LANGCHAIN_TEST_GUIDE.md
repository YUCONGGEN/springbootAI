# AI 与 LangChain 模块测试指南 —— 小白也能看懂

> 本文档说明 SpringBootAI 两个 AI 相关模块的全部测试用例：**有什么用、怎么跑、每个测试验证什么**。
> 测试总数：**672 个**（AI 模块 87 + LangChain 模块 585），全部通过，0 失败。
> - AI 模块：[tests/test_ai_module.py](../tests/test_ai_module.py) — 87 个
> - LangChain 基础测试：[tests/test_langchain_module.py](../tests/test_langchain_module.py) — 75 个
> - LangChain 扩展测试：[tests/test_langchain_ext.py](../tests/test_langchain_ext.py) — 510 个
> - 完整能力 Demo：[example_langchain/demo/langchain_full_demo.py](../example_langchain/demo/langchain_full_demo.py) — 15 章节

---

## 概念地图（测试是怎么组织起来的）

```
                    ┌──────────────────────────────┐
                    │   为什么要看这个文档？        │
                    │   1. 知道测试能验证什么       │
                    │   2. 学会自己跑测试           │
                    │   3. 测试挂了知道怎么办       │
                    └──────────────┬───────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
          ▼                        ▼                        ▼
 ┌────────────────┐    ┌──────────────────┐    ┌──────────────────┐
 │ AI 模块测试    │    │ LangChain 基础   │    │ LangChain 扩展    │
 │ (87个)         │    │ 测试 (75个)      │    │ 测试 (510个)      │
 │                │    │                  │    │                  │
 │ ChatClient     │    │ Adapter 转接头   │    │ 各子模块深度测试  │
 │ Advisor 安检   │    │ Partner 厂商     │    │ 边界/错误/组合    │
 │ RAG 翻书       │    │ Chain 流水线     │    │                  │
 │ Tool 手脚      │    │ Agent 助手       │    │                  │
 │ ETL 入库       │    │ Memory 记性      │    │                  │
 │ 熔断/流式/观测 │    │ Parser 解析      │    │                  │
 └────────────────┘    └──────────────────┘    └──────────────────┘
          │                        │                        │
          └────────────────────────┼────────────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │  全部使用 FakeChatModel       │
                    │  不需要 API Key、不需要联网   │
                    │  AI_ALLOW_FAKE=true 即可      │
                    └──────────────────────────────┘
```

---

## 为什么要看测试？

**大白话**：测试就像是给你的代码买了一份"保险"——以后改代码的时候，跑一下测试就知道有没有把东西改坏了。

具体来说，这份测试指南能帮你：

1. **快速验证环境**：装好依赖后跑一遍测试，如果全部通过，说明环境没问题
2. **理解代码行为**：看不懂某个功能怎么用？看对应的测试代码，比看文档更直观
3. **排查问题**：如果某个功能不工作了，跑对应测试看是哪里坏了
4. **新手学习**：测试代码是最好的"使用示例"，每个测试都演示了一个功能的正确用法

> 全部测试使用 `FakeChatModel` / `FakeEmbeddingModel`，**无需真实 API Key、无需联网**。设置 `AI_ALLOW_FAKE=true` 即可运行（测试套件已自动设置）。

---

## 如何自己跑这些测试（5 分钟上手）

### 第 1 步：确认环境

```bash
# 进入项目根目录
cd springbootAI

# 确认依赖已安装
pip install -r requirements-ai.txt
```

### 第 2 步：一键跑全部测试

```bash
# Windows PowerShell
$env:AI_ALLOW_FAKE = "true"
python -m pytest tests/test_ai_module.py tests/test_langchain_module.py tests/test_langchain_ext.py -q

# 期望输出：
# 584 passed, 1 skipped, 273 warnings in ~70s
```

### 第 3 步：按需跑部分测试

```bash
# 只跑 AI 模块（87 个，验证基础聊天/RAG/工具/熔断等）
python -m pytest tests/test_ai_module.py -v

# 只跑 LangChain 基础测试（75 个，验证转接头/Chain/Agent 等）
python -m pytest tests/test_langchain_module.py -v

# 只跑 LangChain 扩展测试（510 个，深度边界测试）
python -m pytest tests/test_langchain_ext.py -v

# 只跑某个测试类（比如只看函数调用闭环）
python -m pytest tests/test_ai_module.py::TestFunctionCallingClosure -v

# 只跑某个测试方法
python -m pytest tests/test_langchain_module.py::TestAgents::test_create_agent_structured_chat -v

# 静默模式（只看结果，不看过程）
python -m pytest tests/test_ai_module.py tests/test_langchain_module.py tests/test_langchain_ext.py -q

# 运行完整能力 Demo（15 章节，无需 API Key）
python example_langchain/demo/langchain_full_demo.py
```

### 常见跑测试的问题

| 问题 | 解决办法 |
|------|---------|
| 测试报 `ModuleNotFoundError` | 运行 `pip install -r requirements-ai.txt` 安装依赖 |
| 测试报 `openai.AuthenticationError` | 设置 `$env:AI_ALLOW_FAKE = "true"` |
| 测试运行很慢（>2 分钟） | 正常，672 个测试含多个端到端集成测试 |
| 想加速 | 加 `-x` 在首个失败时停止；或按测试类单独跑 |

---

## 测试设计原则（为什么这样写测试？）

1. **无 API Key 可运行**：全部测试使用 `FakeChatModel` / `FakeEmbeddingModel`，设置 `AI_ALLOW_FAKE=true` 即可。不联网、不花钱。

2. **每个 Bug 有回归测试**：修复的每个 bug（bind_tools、沙箱逃逸、structured-chat prompt、流式重试等）都有对应的回归测试，防止复发。

3. **从单元到端到端**：测试分层设计——核心抽象（单元）→ 组件（集成）→ 完整流程（端到端 RAG / 多轮对话 / Agent）。

4. **边界与异常覆盖**：每个组件都测试了正常路径 + 未知类型 + 缺失依赖 + 空输入等边界场景。

5. **安全测试**：`TestSafeEvalArithmetic` 专门验证 6 种沙箱逃逸攻击手法被拦截（属性访问、函数调用、列表/字典、语法错误）。

---

## AI 模块测试（87 个）

> **这些测试验证什么？** 验证你能否用 `ChatClient` 正常聊天、加 Advisor 增强、用 RAG 翻书答题、让模型调用工具——所有核心功能都有测试覆盖。

### TestCoreAbstractions — 核心抽象（3 个）

**大白话**：验证消息（Message）、回复（ChatResponse）、嵌入（Embedding）这些最基础的概念是否正确。

| 用例 | 这个测试验证什么？ | 预期结果 |
|------|-------------------|---------|
| `test_message_factory_methods` | `Message.user()` / `Message.assistant()` / `Message.system()` 能正确创建不同类型的消息 | 3 种工厂方法生成的消息角色正确 |
| `test_chat_response_content_property` | `ChatResponse` 的 `content()` 能正确提取文本 | 返回正确的文本内容 |
| `test_embedding_model_embed_one` | 把一句话变成数字向量，维度正确 | 返回指定维度的 float 列表 |

### TestChatClient — ChatClient 链式 API（3 个）

**大白话**：验证你最常用的 `prompt().user().call().content()` 能不能正常工作。

| 用例 | 这个测试验证什么？ | 预期结果 |
|------|-------------------|---------|
| `test_fluent_prompt_user_call_content` | 链式调用 `prompt().user().call().content()` 返回正确内容 | 返回假模型回显的内容 |
| `test_default_system_prepended` | `default_system()` 设置的系统消息被正确前置 | 系统消息在用户消息前面 |
| `test_prompt_spec_param_and_messages` | `PromptSpec` 的 `param()` 和 `messages()` 方法正确 | 参数和消息都能正确传递 |

### TestFakeProviders — 假模型（2 个）

**大白话**：验证假模型（测试用的、不花钱的）行为是否符合预期。

| 用例 | 这个测试验证什么？ | 预期结果 |
|------|-------------------|---------|
| `test_fake_chat_model_echoes_last_user` | FakeChatModel 回显最后一条用户消息 | 输出 = 前缀 + 用户消息 |
| `test_fake_embedding_deterministic_and_normalized` | 假嵌入向量每次结果一样、且归一化 | 相同输入产生相同向量，模长为 1 |

### TestProviderConfiguration — Provider 配置（3 个）

**大白话**：验证 OpenAI / Ollama 的配置参数（api_key、model、temperature）能正确保存。

### TestChatMemory — 会话记忆（3 个）

**大白话**：验证"记性"功能——加了消息能取出来、不同人的记忆不会串、没有 Redis 也不会报错。

| 用例 | 这个测试验证什么？ |
|------|-------------------|
| `test_inmemory_add_get_clear_and_window` | 添加→获取→清空消息 + 窗口截断 |
| `test_inmemory_isolation_between_conversations` | 不同 conversation_id 的记忆相互隔离 |
| `test_redis_memory_without_client_is_noop` | 无 Redis 客户端时不报错（安全降级） |

### TestVectorStore — 向量存储（5 个）

**大白话**：验证"资料柜"——文档能存进去、能搜出来、空查询不报错。

| 用例 | 这个测试验证什么？ |
|------|-------------------|
| `test_cosine_similarity_basic` | 余弦相似度计算正确（-1 到 1 之间） |
| `test_inmemory_vectorstore_add_and_search` | 入库后能搜到相关内容 |
| `test_inmemory_vectorstore_empty_query_returns_empty` | 空查询返回空列表（不报错） |
| `test_langchain_vectorstore_adapter` | LangChain 向量库能被包装成框架格式 |
| `test_langchain_vectorstore_fallback_without_langchain` | 没装 langchain 时降级不报错 |

### TestEtl — 文档 ETL（4 个）

**大白话**：验证"读→切→存"流程——读文档、切文本块、长文本和短文本都能正确处理。

| 用例 | 这个测试验证什么？ |
|------|-------------------|
| `test_text_reader_inline_content` | TextReader 读取内联文本 |
| `test_token_text_splitter_long_text` | 长文本被切成多块，块之间有重叠 |
| `test_token_text_splitter_short_text_single_chunk` | 短文本只切一块 |
| `test_character_text_splitter` | 按字符数切片正确 |

### TestToolRegistry — 工具注册（3 个）

**大白话**：验证"手脚"——工具能注册、能执行、schema 能自动生成、未知工具报错。

| 用例 | 这个测试验证什么？ |
|------|-------------------|
| `test_register_and_schema_generation` | 注册工具后自动生成 JSON schema |
| `test_tool_execute` | 按名称执行工具并返回正确结果 |
| `test_tool_unknown_raises_and_self_skip` | 未知工具名抛异常；工具自身异常不阻塞其他工具 |

### TestAdvisors — 顾问/安检通道（5 个）

**大白话**：验证"安检通道"——记忆门能保存和恢复历史、RAG 门能检索并注入上下文、日志门能记录事件、多 Advisor 按 order 排序。

| 用例 | 这个测试验证什么？ |
|------|-------------------|
| `test_message_chat_memory_advisor_roundtrip` | 记忆顾问正确保存和恢复对话历史 |
| `test_question_answer_advisor_injects_context` | RAG 顾问检索文档并注入上下文 |
| `test_question_answer_advisor_harden_can_be_disabled` | RAG 加固模式可关闭 |
| `test_simple_logger_advisor_records_events` | 日志顾问记录调用事件 |
| `test_advisor_order_sorting` | 多个 Advisor 按 order 正确排序 |

### TestIntegrationScenarios — 集成场景（3 个）

**大白话**：端到端验证——RAG 完整流程（入库→检索→回答）、多轮对话+记忆、抽象类保护。

| 用例 | 这个测试验证什么？ |
|------|-------------------|
| `test_full_rag_pipeline_etl_to_answer` | ETL 入库 → 检索 → 回答 完整 RAG 流水线 |
| `test_multi_turn_conversation_with_memory` | 多轮对话 + 记忆累积 |
| `test_chat_model_abstract_cannot_instantiate` | ChatModel 抽象类不可直接实例化 |

### TestFunctionCallingClosure — 函数调用闭环（3 个）

**大白话**：验证模型调用工具的完整闭环——模型说要调工具→框架执行→结果回填→模型继续回答。整个过程自动完成。

| 用例 | 这个测试验证什么？ |
|------|-------------------|
| `test_tool_call_loop_executes_and_continues` | 工具调用 → 执行 → 回填 → 模型续写最终回答 |
| `test_tool_call_without_registry_returns_raw` | 无 ToolRegistry 时直接返回原始响应 |
| `test_tool_call_max_iterations_guard` | 超过 5 轮后停止（防死循环） |

### TestResilience — 韧性（3 个）

**大白话**：验证"重试"和"熔断"——网络出错自动重试、连续失败太多就熔断、过一会再试试。

| 用例 | 这个测试验证什么？ |
|------|-------------------|
| `test_retry_retries_on_transient_error` | 瞬态错误自动重试 |
| `test_circuit_breaker_opens_after_threshold` | 失败超过阈值后熔断器打开 |
| `test_circuit_breaker_half_open_recovery` | 熔断器半开状态恢复 |

### TestStreamingAndAsync — 流式与异步（4 个）

**大白话**：验证"打字机效果"——流式输出逐块产出、异步调用不阻塞。

| 用例 | 这个测试验证什么？ |
|------|-------------------|
| `test_fake_stream_yields_delta_chunks` | FakeChatModel 流式产出增量块 |
| `test_chat_client_stream_via_prompt_spec` | ChatClient 通过 PromptSpec 流式调用 |
| `test_async_acall_returns_response` | `acall()` 异步调用返回 ChatResponse |
| `test_async_astream_yields_chunks` | `astream()` 异步流式产出块 |

### 其他 AI 测试类速查

| 测试类 | 用例数 | 大白话 |
|--------|--------|--------|
| TestAiAnnotations | 3 | 验证 @AiClient / @Tool / @AiAdvisor / @AiMemory 注解元数据 |
| TestAutoConfig | 3 | 验证 `configure_ai()` 一行代码装配所有 Bean |
| TestEmbeddingAutoconfigAndRedisVectorStore | 4 | 验证嵌入自动装配和 Redis 向量库持久化 |
| TestRedisReuse | 4 | 验证 AI 模块复用框架全局 Redis 单例 |
| TestObservability | 4 | 验证 Prometheus 指标（调用次数/token/延迟） |
| TestAIPropertiesBinding | 7 | 验证配置绑定、类型转换、环境变量覆盖 |
| TestP1Fixes | 7 | 验证关键 bug 修复（Fake 降级/Redis/熔断/流式重试） |
| TestOptimizationFixes | 5 | 验证流式记忆持久化、瞬态错误分类、HTTP 重试优化 |
| TestMultiProviderLangChain | 6 | 验证 DeepSeek 等厂商通过兼容模型接入 |

---

## LangChain 模块测试（585 个）

> **这些测试验证什么？** 验证 LangChain 全部 12+ 子模块（Chain/Agent/Memory/Parser/Loader/VectorStore/Retriever/Index/Tool/Utility/Callback）+ 转接头 + 30+ Partner 都正常工作。

### 基础测试（75 个）

#### TestAdapters — 双向转接头（7 个）

**大白话**：验证 springbootAI 模型和 LangChain 模型之间的"转接头"是否正常工作——消息不丢失、系统消息保留、双向转换一致。

| 用例 | 这个测试验证什么？ |
|------|-------------------|
| `test_spring_to_langchain_returns_base_chat_model` | springbootAI ChatModel → langchain BaseChatModel 类型正确 |
| `test_to_langchain_model_invokes_spring_backend` | 适配器调用底层 springbootAI 模型 |
| `test_to_langchain_model_preserves_system_message` | system 消息在桥接中不丢失 |
| `test_langchain_to_spring_model` | langchain 模型 → springbootAI ChatModel |
| `test_spring_to_langchain_embeddings` | springbootAI EmbeddingModel → langchain Embeddings |
| `test_langchain_to_spring_embeddings` | langchain Embeddings → springbootAI EmbeddingModel |
| `test_embeddings_roundtrip` | 双向桥接往返一致 |

#### TestPartners — Partner 提供商（6 个）

**大白话**：验证 30+ 厂商注册表——能列出所有厂商、能探测哪些可用、缺失的包给出安装提示。

| 用例 | 这个测试验证什么？ |
|------|-------------------|
| `test_registry_contains_major_providers` | 注册表包含 OpenAI/Anthropic/Ollama 等主流厂商 |
| `test_list_partners_sorted` | `list_partners()` 返回排序后的列表 |
| `test_is_partner_available_unknown_returns_false` | 未知 partner 返回 False |
| `test_partner_factory_unknown_raises` | 未知 partner 抛异常 |
| `test_partner_factory_missing_package_raises_import_error` | 依赖缺失时抛带安装提示的 ImportError |

#### TestPrompts — Prompt 模板（5 个）

**大白话**：验证三种模板（字符串/对话/少样本）的创建和变量替换。

#### TestChains — Chain 服务（6 个）

**大白话**：验证 LLMChain / ConversationChain / SequentialChain / 摘要链都能正确创建和执行。

#### TestAgents — Agent 服务（6 个）

**大白话**：验证 6 种 Agent 类型（ReAct / openai-tools / structured-chat 等）的创建。

#### TestSafeEvalArithmetic — 安全算术求值器（5 个）

**大白话**：验证 `eval()` 的替代品——能做算术，但拒绝一切危险操作（属性访问、函数调用、import）。

| 用例 | 这个测试验证什么？ |
|------|-------------------|
| `test_basic_arithmetic` | 7 种算术运算（+ - * / // % **）正确 |
| `test_blocks_attribute_access` | 属性访问（`(1).__class__...`）被拒绝 |
| `test_blocks_function_call` | 函数调用（`__import__`/`open`/`getattr`）被拒绝 |
| `test_blocks_collections` | 列表/字典字面量被拒绝 |
| `test_syntax_error_raises_value_error` | 语法错误抛 ValueError |

#### 其他 LangChain 基础测试速查

| 测试类 | 用例数 | 大白话 |
|--------|--------|--------|
| TestConfigBinding | 5 | 验证 LangChain 配置绑定 |
| TestAutoConfig | 4 | 验证 `configure_langchain()` 自动装配 |
| TestMemory | 6 | 验证 4 种记忆类型 |
| TestParsers | 5 | 验证 5 种输出解析器 |
| TestVectorStores | 5 | 验证 7 种向量库创建和检索 |
| TestRetrievers | 1 | 验证检索器类型列表 |
| TestIndexService | 2 | 验证一键 RAG 流程 |
| TestTools | 5 | 验证 langchain Tool 创建和 ToolRegistry |
| TestRegistries | 3 | 验证 Loader/Utility/Callback 注册表 |
| TestEndToEndIntegration | 4 | 验证完整业务端到端流程 |

### 扩展测试（510 个）

扩展测试在基础测试之上，对每个子模块做深度边界/错误/组合测试，确保功能与原 langchain classic 完全等价。

| 测试类 | 用例数 | 大白话 |
|--------|--------|--------|
| TestAdaptersExt | 35 | 转接头的深度边界测试（消息映射/流式/工具绑定/异常） |
| TestConfigBindingExt | 25 | 配置绑定的全字段默认值/env覆盖/类型转换 |
| TestAutoConfigExt | 25 | 自动装配的 14 个 Bean 齐全性/disabled/幂等性 |
| TestPartnersExt | 35 | 33 个 partner 注册表完整性/可用性探测/工厂创建 |
| TestPromptsExt | 30 | 3 类模板的变量提取/格式化/多角色/错误处理 |
| TestChainsExt | 35 | LLMChain/Conversation/Sequential/RetrievalQA 等 |
| TestAgentsExt | 35 | 3 种 Agent 的创建/工具绑定/执行/迭代限制 |
| TestSafeEvalExt | 25 | 安全求值的全运算 + 攻击拒绝（防沙箱逃逸） |
| TestMemoryExt | 30 | 4 种记忆的增删查/窗口截断/错误处理 |
| TestParsersExt | 30 | 5 种解析器的 parse/get_format_instructions/错误恢复 |
| TestVectorStoresExt | 35 | 7 种向量库的入库/检索/元数据/错误处理 |
| TestRetrieversExt | 25 | 6 种检索器的创建/k值/invoke |
| TestIndexServiceExt | 25 | 一键 RAG 的建库/查询/文档加载/端到端 |
| TestToolsExt | 30 | Tool 创建/ToolRegistry 注册管理/中文描述 |
| TestLoadersExt | 20 | Text/CSV/JSON/PDF 加载器的创建和加载 |
| TestUtilitiesExt | 15 | 11 种实用工具的懒加载探测 |
| TestCallbacksExt | 15 | 3 种回调的创建和 CallbackRegistry 注册表 |
| TestEndToEndExt | 40 | 完整流程（Chain+Memory+RAG+Agent+装配）组合测试 |

---

## 完整能力 Demo（15 章节）

**文件**：[example_langchain/demo/langchain_full_demo.py](../example_langchain/demo/langchain_full_demo.py)

**大白话**：一个脚本跑通 LangChain 全部 12 个能力子模块 + SafeEval + Partner，不用 Spring 容器、不用 HTTP、不用 API Key。

```bash
python example_langchain/demo/langchain_full_demo.py
```

**章节列表**：

| 章节 | 主题 | 演示内容 |
|------|------|---------|
| 1 | 适配层 | springbootAI ↔ langchain 模型/嵌入双向桥接 |
| 2 | Prompt 模板 | 字符串/对话/Few-shot 三类模板 |
| 3 | Chain | LLMChain/Conversation/Sequential/Math |
| 4 | Agent | ReAct Agent + 工具调用 |
| 5 | Memory | buffer/window/summary/token-buffer |
| 6 | OutputParser | list/datetime/json/pydantic/enum |
| 7 | VectorStore | inmemory 入库 + 检索 |
| 8 | Retriever | similarity 检索器 |
| 9 | IndexService | 一键 RAG |
| 10 | Tools | StructuredTool/Tool/ToolRegistry |
| 11 | DocumentLoader | Text/CSV/JSON 文件加载 |
| 12 | Utility | DuckDuckGo 等懒加载工具 |
| 13 | Callbacks | stdout/streaming/file 回调 |
| 14 | SafeEval | AST 安全算术求值 + 攻击拒绝演示 |
| 15 | Partner | 33 个第三方模型提供商注册表 |

---

## 测试覆盖矩阵

### AI 模块功能覆盖

| 功能 | 测试类 | 用例数 |
|------|--------|--------|
| 核心抽象（Message/ChatResponse/Embedding） | TestCoreAbstractions | 3 |
| ChatClient 链式 API | TestChatClient | 3 |
| Fake 测试模型 | TestFakeProviders | 2 |
| Provider 配置（OpenAI/Ollama） | TestProviderConfiguration | 3 |
| 会话记忆（InMemory/Redis） | TestChatMemory | 3 |
| 向量存储（InMemory/LangChain适配器） | TestVectorStore | 5 |
| 文档 ETL（Reader/Splitter） | TestEtl | 4 |
| 工具注册与执行 | TestToolRegistry | 3 |
| Advisor（记忆/RAG/日志/排序） | TestAdvisors | 5 |
| AI 注解（@AiClient/@Tool/@AiAdvisor） | TestAiAnnotations | 3 |
| 自动装配（configure_ai） | TestAutoConfig | 3 |
| 集成场景（RAG/多轮/抽象类） | TestIntegrationScenarios | 3 |
| 函数调用闭环（tool_call 循环） | TestFunctionCallingClosure | 3 |
| 嵌入与 Redis 向量库 | TestEmbeddingAutoconfigAndRedisVectorStore | 4 |
| Redis 复用 | TestRedisReuse | 4 |
| 韧性（重试/熔断） | TestResilience | 3 |
| 流式与异步（SSE/async） | TestStreamingAndAsync | 4 |
| 可观测性（Prometheus 指标） | TestObservability | 4 |
| 类型化配置绑定 | TestAIPropertiesBinding | 7 |
| P1 修复（Fake降级/Redis/熔断/流式重试） | TestP1Fixes | 7 |
| 优化修复（流式记忆/瞬态分类/HTTP重试） | TestOptimizationFixes | 5 |
| 多厂商 LangChain 化（DeepSeek） | TestMultiProviderLangChain | 6 |
| **合计** | **22 个测试类** | **87** |

### LangChain 模块功能覆盖

| 功能 | 基础用例数 | 扩展用例数 |
|------|-----------|-----------|
| 双向适配器（spring↔langchain） | 7 | 35 |
| 类型化配置绑定 | 5 | 25 |
| 自动装配（configure_langchain） | 4 | 25 |
| 30+ Partner 提供商 | 6 | 35 |
| Prompt 模板（3 种） | 5 | 30 |
| Chain 服务（6 种 Chain） | 6 | 35 |
| Agent 服务（6 种 Agent） | 6 | 35 |
| 安全算术求值器（防沙箱逃逸） | 5 | 25 |
| Memory 工厂（4 种） | 6 | 30 |
| 输出解析器（5 种） | 5 | 30 |
| 向量库工厂（7 种） | 5 | 35 |
| 检索器（6 种） | 1 | 25 |
| 一键 RAG（IndexService） | 2 | 25 |
| 工具工厂（ToolFactory/ToolRegistry） | 5 | 30 |
| 加载器 | 1 | 20 |
| Utility 工具 | 1 | 15 |
| Callbacks | 1 | 15 |
| 端到端集成 | 4 | 40 |
| **合计** | **75 + 510 = 585** | |

---

## 测试失败怎么办？（常见问题排查）

### 问题 1：`ModuleNotFoundError: No module named 'langchain_xxx'`

**大白话**：你缺少某个 langchain 的依赖包。

**怎么修**：这不是 bug！`test_partner_factory_missing_package_raises_import_error` 这个测试就是故意验证"缺失依赖时给出友好提示"的。

```bash
# 如果确实要用这个 partner，安装对应包
pip install langchain-anthropic   # 举例
```

### 问题 2：`openai.AuthenticationError`

**大白话**：某个测试试图连真的 OpenAI API。

**怎么修**：确认设置了 `AI_ALLOW_FAKE=true`。在 PowerShell 中：
```bash
$env:AI_ALLOW_FAKE = "true"
```

### 问题 3：`LangChainDeprecationWarning` 刷屏

**大白话**：langchain 官方在弃用一些旧 API（LLMChain、ConversationChain 等）。

**怎么修**：这是框架级的警告，不影响功能。代码已用 `warnings.filterwarnings` 屏蔽，pytest 运行时仍会记录但不会导致失败。

### 问题 4：测试运行慢（~70 秒）

**大白话**：672 个测试有多个端到端集成测试（RAG 流水线、Agent 执行、完整装配），需要初始化多个组件。

**怎么加速**：
```bash
# 只跑某一个测试类
python -m pytest tests/test_ai_module.py::TestFunctionCallingClosure -v

# 首个失败就停
python -m pytest tests/test_ai_module.py -x

# 并行跑（需要 pytest-xdist）
python -m pytest tests/test_ai_module.py tests/test_langchain_module.py -n 4
```

### 问题 5：`test_18_create_faiss_missing_dep_raises` 被跳过

**大白话**：faiss 已经安装了，这个测试就自动跳过（它只在不装 faiss 时才跑）。

**怎么修**：不需要修。这个测试设计就是"有 faiss 就跳过，没 faiss 才跑"来验证错误提示是否正确。

### 问题 6：测试全部通过但 Demo 失败

**大白话**：Demo 依赖某些 langchain 可选包（如 duckduckgo-search）。

**怎么修**：
```bash
pip install duckduckgo-search wikipedia
```

---

## 新手常见问题 FAQ

**Q1：为什么要写这么多测试？672 个太多了吧？**

A：这个项目封装了 LangChain 全部 12+ 子模块 + 30+ Partner 提供商，每个子模块都需要验证正常路径、边界情况和错误处理。672 个测试确保了迁移后的代码和原 langchain 行为完全一致。

**Q2：我没有 API Key，能跑通所有测试吗？**

A：能！全部测试使用 `FakeChatModel`，不花一分钱，不需要联网。

**Q3：测试全绿就代表代码没 bug 了吗？**

A：测试覆盖了已知的功能路径和边界情况，但不能保证 100% 没有 bug。它确保的是"已知的功能不会因为改代码而变坏"。

**Q4：怎么知道哪些测试覆盖了哪些功能？**

A：看测试类名就行。比如 `TestFunctionCallingClosure` 测试函数调用闭环，`TestAdvisors` 测试安检通道。每个测试方法的名称也描述了验证内容。

**Q5：我想加一个新功能的测试，应该放在哪个文件？**

A：AI 模块的新测试放在 `tests/test_ai_module.py`，LangChain 基础测试放在 `tests/test_langchain_module.py`，深度边界测试放在 `tests/test_langchain_ext.py`。

**Q6：测试和 Demo 有什么区别？**

A：测试是自动化的——跑完一行命令就知道过没过。Demo 是给人看的——它打印出每一步的结果，帮你理解每个功能是怎么用的。

---

> **相关文档**：[AI 模块使用指南](AI_MODULE.md) | [LangChain 模块使用指南](LANGCHAIN_MODULE.md) | [新手入门指南](BEGINNER_GUIDE.md)
