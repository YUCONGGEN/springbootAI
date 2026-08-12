# Changelog

本项目从 `2.1.0` 开始按 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 记录面向使用者的变化，并使用语义化版本号。

## [2.1.1] - 2026-08-12

### 修复

- 锁定兼容的 `langchain-core==1.5.4` 与 `langchain-openai==1.4.2`，避免可选 AI 依赖解析冲突。
- CI 中间件恢复命令改用 `docker compose up -d --wait <service>`，兼容不支持 `start --wait` 的 Compose 版本。

## [2.1.0] - 2026-08-12

### 新增

- 新增独立 `spring.langgraph` 模块，锁定 `langgraph==1.2.9`，提供状态图、条件路由、人工中断、恢复、流式调用和注解式工作流。
- 新增官方 SQLite checkpointer 安全工厂；关闭 pickle fallback、限制反序列化类型，并验证连接关闭后重新打开仍能恢复流程。
- 新增 `spring.mcp` 客户端和服务端，基于官方 MCP Python SDK，支持 Tool、Resource、Prompt 及注解调用。
- 新增 LangChain 和 LangGraph 注解 API；注解只负责声明，执行继续委托官方框架。
- 压测新增 AI、LangChain、LangGraph、MCP workload，并纳入 9 小时 mixed 稳定性脚本。
- CI 新增真实 MySQL、Redis、RabbitMQ、Nacos、Seata TCC 集成测试和依赖停机测试。

### 修复

- 同步 Controller 由有界线程池执行，避免阻塞 ASGI 事件循环。
- Gateway 支持正确的 ASGI 挂载和异步请求体/上游转发。
- Seata distributed 模式对接真实 Seata Server 与 Java bridge，并通过 TCC prepare/commit/rollback 合同测试。
- 健康检查会把 Nacos、RabbitMQ 和 Seata 状态纳入总体状态和 readiness。
- 修复动态 SQL/DDL 的不安全表达式求值、XML 外部实体、Redis pickle 反序列化、动态排序标识符和 callback SSRF 风险。
- 补齐 `requests`、`defusedxml`、LangGraph SQLite checkpoint 和 MCP 的发布依赖。

### 安全与发布

- Bandit 所有中高危发现和四份 `pip-audit` 结果成为强制门禁，不再使用 `|| true` 放行。
- 发布工作流要求 git tag 与 `pyproject.toml` 版本完全一致，并在上传前执行全量测试、覆盖率、安全审计、wheel 内容和干净安装检查。
- `langgraph-checkpoint-sqlite` 使用已修复公开漏洞的 `3.1.1`，并启用严格反序列化策略。

### 兼容性提醒

- Redis ORM 缓存不再接受 `pickle` 序列化。旧 pickle 缓存应在升级前清理，并改用 JSON。
- Seata `distributed` 提供真实 TC + TCC 协调，不是 Python AT 数据源代理，不会自动生成 `undo_log`。
- 内存 LangGraph checkpointer 仅用于测试；多 worker 生产环境必须注入共享存储后端。

[2.1.1]: https://github.com/YUCONGGEN/springbootAI/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/YUCONGGEN/springbootAI/compare/v2.0.2...v2.1.0
