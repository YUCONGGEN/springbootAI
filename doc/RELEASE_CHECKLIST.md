# GitHub 与 PyPI 发布检查清单

这份清单用于发布 SpringBootAI。第一次发布时从上到下执行，不要跳过失败项。

## 1. 先理解两个版本

- `pyproject.toml` 中的 `project.version` 是准备发布的新版本，例如 `2.2.0`。
- Git tag 必须是同一个版本加 `v`，例如 `v2.2.0`。
- PyPI 上已经存在的版本不能覆盖。如果命令显示该版本已存在，必须修改版本号并重新测试，不能删除后重传。

## 2. 发布前本地验证

在仓库根目录和干净虚拟环境执行：

```powershell
python -m pip install -r requirements-lock.txt
python -m pip install -r requirements-ai.txt
python -m pip install -r requirements-langgraph.txt
python -m pip install -r requirements-mcp.txt

python -m pytest tests tests_runtime -q `
  --cov=spring --cov-report=term --cov-fail-under=60
```

预期：没有失败，覆盖率不少于 60%。`skipped` 必须逐个确认是明确的可选能力，不能把依赖安装失败当成正常跳过。

启动 Docker 中间件并执行真实集成测试：

```powershell
docker compose -f docker-compose.integration.yml up -d --build --wait
$env:RUN_INTEGRATION_TESTS = "1"
$env:RUN_SEATA_INTEGRATION_TESTS = "1"
$env:SEATA_BRIDGE_TOKEN = "springpy-integration-secret"
python -m pytest tests_integration -m integration -v
```

预期：MySQL、Redis、RabbitMQ、Nacos 和 Seata TCC 测试全部通过。测试完成后可执行：

```powershell
docker compose -f docker-compose.integration.yml down -v
```

该命令会删除这套集成测试的容器和数据卷，不要对生产 Compose 项目执行。

## 3. 安全检查

Windows PowerShell 先启用 UTF-8，避免中文注释导致审计器读取失败：

```powershell
$env:PYTHONUTF8 = "1"
pip-audit -r requirements-lock.txt --progress-spinner off
pip-audit -r requirements-ai.txt --progress-spinner off
pip-audit -r requirements-langgraph.txt --progress-spinner off
pip-audit -r requirements-mcp.txt --progress-spinner off
bandit -r spring example_langchain example_langgraph example_mcp -ll -q
```

预期：四份依赖均显示 `No known vulnerabilities found`，Bandit 退出码为 0。不要用 `|| true` 或 `--exit-zero` 绕过结果。

## 4. 压测冒烟

```powershell
.\scripts\run-load-test.ps1 -Profile smoke -Workload mixed -Rate 5 -Duration 20s
```

预期：阈值全部通过、HTTP 失败率为 0、无 dropped iteration。它只验证压测链路，不代表企业容量；9 小时测试命令见 [`tests_performance/README.md`](../tests_performance/README.md)。

## 5. 构建并检查制品

```powershell
python -m build
python -m twine check dist\*
python -m zipfile -l dist\springbootai-2.2.0-py3-none-any.whl
```

确认 wheel 包含 `spring/langchain`、`spring/langgraph` 和 `spring/mcp`，并从新虚拟环境安装 wheel 后执行：

```powershell
python -c "import spring, spring.ai, spring.langchain, spring.langgraph, spring.mcp; print(spring.__version__)"
```

## 6. GitHub 与 PyPI 发布顺序

1. 检查 `git diff --check`、`git status` 和 CHANGELOG，确认没有密钥、数据库、日志、覆盖率文件或压测结果。
2. 提交代码并推送 `master`，等待 CI 和 Security Scan 全绿。
3. 创建并推送匹配版本的 tag：`git tag -a v2.2.0 -m "SpringBootAI 2.2.0"`、`git push origin v2.2.0`。
4. 在 GitHub 用这个 tag 创建 Release，发布工作流才会通过 Trusted Publishing 上传 PyPI。
5. 上传后在全新环境运行 `pip install springbootAI==2.2.0` 和最小示例，检查 PyPI README 链接与代码块。

不要在本机手工保存 PyPI token。仓库发布工作流使用 OIDC Trusted Publishing，并拒绝从普通分支上传。
