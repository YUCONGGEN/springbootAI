# Actuator —— 系统健康检查面板

> SpringBootAI 2.3.11
> 返回 [README 模块导航](../README.md#模块文档导航)

---

## 目录

- [你遇到了什么问题？](#你遇到了什么问题)
- [① 是什么](#①-是什么)
- [② 怎么用](#②-怎么用)
- [端点一览](#端点一览)
- [③ 运行结果](#③-运行结果)
- [第四章：Spring Boot Admin 可视化面板](#第四章spring-boot-admin-可视化面板)
- [第五章：Prometheus + Grafana 工业级监控](#第五章prometheus--grafana-工业级监控)
- [第六章：自定义业务指标](#第六章自定义业务指标)
- [第七章：工业级监控一键部署（小白教程）](#第七章工业级监控一键部署小白教程)
- [mini-FAQ](#mini-faq)

---

## 你遇到了什么问题？

应用上线后出问题了——内存够不够？数据库连不连得上？哪些配置生效了？你没法钻到服务器里看，线上又不能随便打断点调试。

## ① 是什么

**给应用装一个"体检仪"**——一个内置的管理页面，随时查看应用健康状态、配置、内存、线程等。就像体检时用各种仪器检查身体各项指标，看到系统是否正常运行。

## ② 怎么用

```python
from springbootai.web.actuator import configure_actuator

# 在应用初始化后注册端点
configure_actuator(
    app,
    application_context,
    enabled_endpoints=["health", "info", "env", "loggers", "metrics"]
)
# 结果：访问 http://127.0.0.1:8080/actuator/health 即可查看健康状态
```

## 端点一览

| 端点地址 | 干什么用 | 什么时候用 |
|---|---|---|
| `/actuator` | 所有可用端点列表 | 看有哪些端点 |
| `/actuator/health` | 健康状态（UP/DOWN） | K8s/Docker 健康检查首选 |
| `/actuator/info` | 应用名称、版本 | 确认当前部署版本 |
| `/actuator/env` | 全部配置项（密码自动打码） | 排查配置是否生效 |
| `/actuator/loggers` | 列出所有日志级别 | 查看当前日志级别 |
| `/actuator/loggers/{name}` | 查看/修改某个 logger 级别 | 临时开 DEBUG 排查问题 |
| `/actuator/metrics` | 指标列表（JSON） | 查看注册了哪些指标名 |
| `/actuator/metrics/{name}` | 单个指标数值 | 查某个具体指标 |
| `/actuator/beans` | 已注册的所有 Bean | 排查 Bean 是否都注册了 |
| `/actuator/mappings` | 所有 HTTP 路由 | 确认接口路由是否注册成功 |
| `/actuator/threaddump` | 线程快照 | 排查死锁、卡死问题 |
| `/actuator/configprops` | 配置绑定结果 | 确认配置绑定是否正确 |
| `/actuator/prometheus` | **Prometheus 文本格式指标** | Prometheus Server 抓取入口 |
| `/actuator/sysmetrics` | **进程级系统指标（RSS/CPU/线程/FD）** | Admin 面板 JS 调用、快速诊断 |
| `/actuator/admin` | **Spring Boot Admin 风格可视化面板** | 浏览器打开即用 |
| `/actuator/thresholds` | 自定义阈值检查 | 自定义健康规则 |

## ③ 运行结果

访问 `http://127.0.0.1:8080/actuator/health`：

```json
{
  "status": "UP",
  "components": {
    "db": {"status": "UP", "detail": "Connected"},
    "diskSpace": {"status": "UP", "detail": "free: 50GB"}
  }
}
```

---

## 第四章：Spring Boot Admin 可视化面板

### 4.1 是什么

Spring Boot Admin 是 Spring 生态专门的 **Actuator 可视化面板**——把分散在十几个 `/actuator/*` 端点的 JSON 数据，整合成一个浏览器里就能看懂的 HTML 仪表盘。SpringBootAI 内置实现了一个等价的面板，**几秒钟就能搭起来**，无需独立部署 Admin Server。

### 4.2 怎么用

应用内置面板只要 Actuator 已注册即可直接访问：

```
http://127.0.0.1:8080/actuator/admin
```

> 末尾带不带斜杠都行：`/actuator/admin/` 同样可访问。

### 4.2.1 在 application.yml 配置内置面板

Admin 面板开箱即用，未配置时使用框架内置默认值：标题为
`SpringBootAI Admin Dashboard`、每 30 秒刷新、日志与 Bean 每页 10 条。
如需覆盖，在应用自己的 `application.yml` 中加入：

```yaml
management:
  admin:
    title: 我的应用运维面板
    subtitle: 生产环境监控
    refresh-interval-seconds: 30
    page-size: 10
    # 可选：框架自动建表并记录请求，显示在“线程概览”右侧。
    # 默认 false；开启后项目无需编写实体、Mapper、Controller 或拦截器。
    request-metrics:
      enabled: true
      title: 业务请求监控（数据库持久化）
      # 可选：业务接口统一以 /api 开头的项目，建议明确白名单，防止非业务页面被采集。
      include-paths:
        - /api/**
      # 可选：在框架默认排除项外，继续排除项目自己的非业务接口。
      exclude-paths:
        - /internal/**
```

四个字段均可选。字段未写、空字符串或数值不合法时，框架会只对该字段回退到
内置默认值；`refresh-interval-seconds` 的有效范围为 1-3600，`page-size` 为 1-100。
`request-metrics` 默认为关闭。开启后框架会创建 `springbootai_request_metrics` 表、
自动记录业务 HTTP 请求，并通过受 Actuator 鉴权保护的
`/actuator/request-metrics` 端点向面板提供请求总数、错误总数、平均耗时和最常访问路径。
项目不需要提供任何业务监控接口。

### 4.2.1.1 配置刷新监控（默认关闭）

需要排查“配置从哪里来、何时刷新、刷新是否成功”时，可开启框架内置配置监控：

\`\`\`yaml
management:
  config-monitor:
    enabled: true
    include-values: false   # 默认不记录配置值，避免泄露密码、Token 等敏感信息
    history-size: 100       # 1-10000，超过后淘汰最早事件
    refresh-events: true
\`\`\`

开启后，框架记录配置来源（YAML、profile、环境变量、Nacos、命令行）、变更键、
刷新耗时、成功/失败和错误摘要；不会阻塞配置刷新，记录异常也不会导致应用崩溃。
通过受 Actuator 鉴权保护的 \`GET /actuator/config-monitor\` 查询，Admin 面板会在
“配置刷新监控”卡片显示最近事件。未开启时不保存历史、不读取配置值，端点返回
\`enabled: false\`。也可使用环境变量
\`MANAGEMENT_CONFIG_MONITOR_ENABLED\`、\`MANAGEMENT_CONFIG_MONITOR_INCLUDE_VALUES\`、
\`MANAGEMENT_CONFIG_MONITOR_HISTORY_SIZE\` 和 \`MANAGEMENT_CONFIG_MONITOR_REFRESH_EVENTS\`
进行配置。

### 4.2.0.1 可选端点默认不主动启用

框架启动时如果没有显式配置可选运维端点，Admin 页面不会展示并轮询 Prometheus、系统指标、
线程、日志、Bean、告警等接口，因此不会因缺少管理员 Token 产生一批 401 日志。健康和
info 仍保持可用。需要哪些能力时，在配置中心、环境变量或本地 YAML 中显式开启：

```yaml
management:
  endpoints:
    web:
      exposure:
        include: [prometheus, sysmetrics, threaddump, loggers, beans]
  admin:
    request-metrics:
      enabled: true
```

也可以单独写 `management.endpoints.web.<endpoint>.enabled: true`，或通过
`PROMETHEUS_ENABLED=true` 开启 Prometheus。配置优先级和 Nacos 热更新规则与本节其他
字段相同；未开启的面板区域会显示“未启用”，不会发起后台请求。底层路由为保持
兼容仍保留，但仍受原有 Actuator 鉴权保护；生产环境可通过网关或 exposure 规则进一步
限制外部访问。

采集范围的规则是：框架始终排除 `/actuator/**`、`/docs/**`、`/doc/**`、`/redoc/**`、
`/openapi.json` 和 `/favicon.ico`，因此健康检查、Admin 自动轮询、Prometheus 抓取等运维请求不会进入业务统计。
`include-paths` 未配置时，其他所有 HTTP 路径都会采集，以兼容不使用 `/api` 前缀的项目；如果项目业务 API 有统一前缀，建议配置白名单（如 `/api/**`）。
`exclude-paths` 用于增加项目专用的排除规则。框架启动时还会清理表中与当前规则不匹配的旧历史记录，避免升级前的运维数据继续显示在面板中。

内置 Admin 的“健康状态”仅显示已启用的组件。Redis、Nacos、RabbitMQ、Seata 等未启用时仍会在
`/actuator/health` 的 `components` 中以 `enabled: false` 返回，方便自动化诊断，但不会在可视化面板显示，也不会被误判为故障。

### 4.2.1.1 配置来源、优先级与容错

上述 `management.*` 配置不绑定本地 `application.yml`：框架始终从 `ApplicationContext` 的最终配置读取。
优先级为：命令行参数 > 环境变量 > Nacos 远程配置 > profile 配置 > 本地配置 > 框架默认值。
因此生产环境可只保留 Nacos 的业务配置，或仅以环境变量控制面板：

```text
MANAGEMENT_ADMIN_REQUEST_METRICS_ENABLED=true
MANAGEMENT_ADMIN_REQUEST_METRICS_INCLUDE_PATHS=/api/**
MANAGEMENT_ADMIN_REQUEST_METRICS_EXCLUDE_PATHS=/internal/**
MANAGEMENT_ADMIN_REQUEST_METRICS_TABLE=springbootai_request_metrics
MANAGEMENT_ADMIN_PAGE_SIZE=20
MANAGEMENT_ENDPOINTS_WEB_SECURITY_ENABLED=true
MANAGEMENT_ENDPOINTS_WEB_SECURITY_ROLES=ROLE_ADMIN,ACTUATOR
```

路径列表使用逗号分隔。空值、类型错误、非法分页数和不可用的请求监控数据库均不会阻断应用启动：
前者回退到安全默认值；后者使 `/actuator/request-metrics` 返回 `persistent: false` 与简短错误状态，业务接口继续正常运行。

### 4.2.2 注册到独立 Spring Boot Admin Server

内置 `/actuator/admin` 不需要注册。若要在 `http://localhost:1111` 的独立 Spring Boot Admin Server 中看到应用，必须由应用主动 `POST /instances` 注册；仅在 Server 容器设置 `SPRING_BOOT_ADMIN_INSTANCE_*` 环境变量不会注册实例。

1. 启动监控栈：`docker compose -f monitoring/docker-compose.yml up -d`。
2. 在应用环境设置下列变量。`SERVICE_URL` 必须从 Admin Server 容器可访问；本机运行应用时使用 `host.docker.internal`。

```powershell
$env:SPRING_BOOT_ADMIN_CLIENT_ENABLED = "true"
$env:SPRING_BOOT_ADMIN_URL = "http://localhost:1111"
$env:SPRING_BOOT_ADMIN_NAME = "springbootai-demo"
$env:SPRING_BOOT_ADMIN_SERVICE_URL = "http://host.docker.internal:8000"
$env:SPRING_BOOT_ADMIN_MANAGEMENT_URL = "http://host.docker.internal:8000/actuator"
$env:SPRING_BOOT_ADMIN_HEALTH_URL = "http://host.docker.internal:8000/actuator/health"
python -m myapp.Application
```

3. 日志出现 `Registered with Spring Boot Admin` 后，打开 `http://localhost:1111`，实例状态应为 `UP`。关闭应用时会向 `/instances/{id}` 注销。

生产环境将这些值写入部署环境，而不是提交到仓库；当 Admin Server 与应用同一 Docker 网络时，改用服务 DNS，例如 `http://myapp:8080`。

### 4.3 面板内容

打开后是一个深色主题的仪表盘，包含以下区块（每 30 秒自动刷新，也可点右上角"刷新"按钮手动触发）：

| 区块 | 数据来源 | 说明 |
|---|---|---|
| **健康状态** | `/actuator/health` | 总体状态 + 各组件（db/diskSpace 等）细分 |
| **系统信息** | `/actuator/info` | 应用名、版本、Python 版本、操作系统 |
| **内存 & CPU** | `/actuator/sysmetrics` | 进程 RSS、虚拟内存、CPU 使用率、线程数、文件描述符数 |
| **线程概览** | `/actuator/threaddump` | 总线程数、活动线程数、守护线程数 |
| **日志级别管理** | `/actuator/loggers` | 表格列出所有 logger，**点击某行即可循环切换** DEBUG/INFO/WARNING/ERROR |
| **Prometheus 指标** | `/actuator/prometheus` | 两个 Tab：原始文本数据 / 指标摘要表格（指标名/类型/值） |
| **Bean 列表** | `/actuator/beans` | IoC 容器中所有 Bean 的名称、类型、Scope |

### 4.4 后端实现要点

- 端点函数 `admin_dashboard()` 返回 `HTMLResponse`，HTML 由 `_build_admin_dashboard_html()` 纯函数生成，便于测试。
- 前端 JS 用 `fetch` 异步调用各 Actuator 端点，**无需后端模板引擎**。
- 系统级指标（RSS/CPU/线程）通过 `/actuator/sysmetrics` 端点用 `psutil` 采集，避免在浏览器端调用 Python API。
- `setInterval(loadAll, 30000)` 实现 30 秒自动刷新。

### 4.5 注意事项

- `/actuator/admin` 本身**不鉴权**（HTML 是静态的，不含敏感数据），但面板内 JS 调用的 `/actuator/env`、`/actuator/loggers`、`/actuator/threaddump` 等敏感端点**仍受 Actuator 鉴权保护**。开发环境可通过 `management.endpoints.web.security.enabled=false` 关闭鉴权；生产环境请通过反向代理加 IP 白名单或 Basic Auth。
- `psutil` 未安装时，"内存 & CPU"区块会显示 "psutil not installed"，其它区块不受影响。安装：`pip install psutil`。

---

## 第五章：Prometheus + Grafana 工业级监控

### 5.1 是什么

Prometheus 是 CNCF 的工业级监控系统，Grafana 是可视化面板。两者组合是云原生监控的事实标准。SpringBootAI 通过 `/actuator/prometheus` 端点把应用指标以 **Prometheus 文本格式**暴露出来，Prometheus Server 定时抓取（pull 模式），数据进入 Grafana 后可绘制各种图表。

### 5.2 端点行为

```
GET /actuator/prometheus
Content-Type: text/plain; version=0.0.4; charset=utf-8
```

响应示例（节选）：

```
# HELP spring_python_http_requests_total Total HTTP requests
# TYPE spring_python_http_requests_total counter
spring_python_http_requests_total{method="GET",status="200"} 1234
# HELP spring_python_process_memory_rss_bytes Resident memory in bytes
# TYPE spring_python_process_memory_rss_bytes gauge
spring_python_process_memory_rss_bytes 4.56789e+07
```

**容错策略**：

| 情况 | HTTP 状态码 | 响应体 |
|---|---|---|
| 正常 | 200 | Prometheus 文本格式指标 |
| `prometheus_client` 未安装 | 503 | `# prometheus_client not installed` |
| 内部异常 | 500 | `# error: <异常信息>` |

### 5.3 三步接入 Prometheus + Grafana

#### Step 1：安装依赖

```bash
pip install prometheus_client psutil
```

#### Step 2：配置 Prometheus Server 抓取任务

编辑 `prometheus.yml`：

```yaml
scrape_configs:
  - job_name: 'springbootai'
    metrics_path: '/actuator/prometheus'
    scrape_interval: 15s
    static_configs:
      - targets: ['app-host:8080']
        labels:
          app: 'my-app'
          env: 'prod'
```

启动 Prometheus：

```bash
./prometheus --config.file=prometheus.yml
# 默认 Web UI: http://localhost:9090
```

#### Step 3：在 Grafana 配置数据源 + 仪表盘

1. 添加 Prometheus 数据源：URL 填 `http://localhost:9090`
2. 导入官方仪表盘（ID: `4701` —— JVM/Micrometer 通用面板）或自建面板
3. 常用 PromQL 示例：

```promql
# 进程内存 RSS（MB）
spring_python_process_memory_rss_bytes / 1024 / 1024

# HTTP 请求 QPS（按状态码）
rate(spring_python_http_requests_total[1m])

# 请求延迟 P99（如有 histogram）
histogram_quantile(0.99, rate(spring_python_http_request_duration_seconds_bucket[5m]))
```

### 5.4 多 Worker 部署注意事项

默认通过主应用 `/actuator/prometheus` 暴露指标，**避免多 worker 争抢端口**。若使用 `gunicorn --workers=4` 等多进程模式，需配置共享目录：

```bash
# 启动前设置环境变量
export PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc
mkdir -p $PROMETHEUS_MULTIPROC_DIR
```

框架会自动启用 `prometheus_client.multiprocess.MultiProcessCollector`，聚合各 worker 指标。

---

## 第六章：自定义业务指标

### 6.1 通过 PrometheusMetrics 单例创建指标

```python
from springbootai.monitoring.prometheus import prometheus_metrics

# 计数器：累计请求数
http_counter = prometheus_metrics.create_counter(
    name='http_requests_total',
    documentation='Total HTTP requests',
    labelnames=['method', 'status'],
)
http_counter.labels(method='GET', status='200').inc()

# 仪表盘：当前在线用户数
online_gauge = prometheus_metrics.create_gauge(
    name='online_users',
    documentation='Current online users',
)
online_gauge.set(42)

# 直方图：请求延迟分布
latency_hist = prometheus_metrics.create_histogram(
    name='http_request_duration_seconds',
    documentation='HTTP request latency',
    labelnames=['endpoint'],
    buckets=[0.01, 0.05, 0.1, 0.5, 1, 5],
)
latency_hist.labels(endpoint='/api/users').observe(0.123)

# 摘要：分位数
latency_summary = prometheus_metrics.create_summary(
    name='rpc_latency_seconds',
    documentation='RPC latency',
)
latency_summary.observe(0.456)
```

### 6.2 指标命名规则

框架自动加上 `namespace_subsystem_` 前缀（默认 `spring_python_`）：

| 你写的 name | 实际暴露的指标名 |
|---|---|
| `http_requests_total` | `spring_python_http_requests_total` |
| `online_users` | `spring_python_online_users` |

如需自定义前缀：

```python
prometheus_metrics.configure(namespace='myapp', subsystem='api')
```

> ⚠️ 配置必须在创建任何指标**之前**完成，已有指标后修改会抛 `RuntimeError`。

### 6.3 默认暴露的指标

只要安装了 `prometheus_client`，`/actuator/prometheus` 默认会暴露：

- `python_*`：Python 解释器指标（GC、线程数、对象数等）
- `process_*`：进程指标（CPU、内存、打开的 FD 数）

业务指标需按 6.1 节手动注册后才会出现。

---

## 第七章：工业级监控一键部署（小白教程）

> **这一章解决什么问题？**
> 前面几章的 `/actuator/admin` 是个简易面板，但它没有图表、没有告警、没有历史趋势。
> 这一章教你用**现成的工业级工具**（Prometheus + Grafana + Alertmanager + Spring Boot Admin），
> 搭一套专业监控体系——**有折线图、有告警推送、有历史数据**，跟大厂用的一样。
>
> **你不需要懂这些工具的内部原理**，只需要会复制粘贴命令就行。

### 7.1 先搞懂这四个工具分别是干什么的

打个比方，假设你的 SpringBootAI 应用是一个"病人"，这四个工具的角色如下：

| 工具 | 比喻 | 干什么 |
|------|------|--------|
| **Prometheus** | 护士 | 每 15 秒来量一次体温、血压（抓取 `/actuator/prometheus` 指标），记录到病历本 |
| **Grafana** | 体检报告 | 把护士记录的数据画成折线图、柱状图，让你一眼看出"体温趋势是否正常" |
| **Alertmanager** | 报警器 | 体温超过 38°C？立刻给你发钉钉/邮件/微信通知 |
| **Spring Boot Admin** | 主治医生 | 站在病房外看仪表盘，能看到病人整体状态、开药方（改日志级别） |

它们之间的关系：

```
你的 SpringBootAI 应用（病人，运行在 :8000 端口）
    │
    │  /actuator/prometheus（暴露指标数据）
    ├──→ Prometheus（护士，:9090）—— 每 15 秒来抓一次数据
    │        │
    │        │  数据存起来后
    │        ├──→ Grafana（体检报告，:3000）—— 把数据画成图表
    │        │
    │        │  发现异常时
    │        └──→ Alertmanager（报警器，:9093）—— 发钉钉/邮件通知
    │                 │
    │                 │  告警推送到
    │                 └──→ /actuator/alert（你的应用接收告警，显示在 Admin 面板）
    │
    │  /actuator/health（暴露健康状态）
    └──→ Spring Boot Admin（主治医生，:1111）—— 看整体状态
```

### 7.2 开始之前需要准备什么

**你需要安装 Docker Desktop。**

- **Windows/Mac**：去 https://www.docker.com/products/docker-desktop 下载安装，一路下一步就行
- **Linux**：执行 `curl -fsSL https://get.docker.com | sh`

安装完成后，打开终端（Windows 用 PowerShell），输入：

```bash
docker --version
```

如果显示 `Docker version 24.x.x` 之类的版本号，说明安装成功了。

> **小白提示**：Docker 就像一个"虚拟机"，能在你电脑上跑各种服务而不污染你的系统。后面四个监控工具都是用 Docker 跑的，你不需要单独安装它们。

### 7.3 三步启动完整监控栈

#### 第一步：启动你的 SpringBootAI 应用

```bash
# 在项目根目录下执行
python -m springbootai.main
```

应用启动后，浏览器打开 http://localhost:8000/actuator/health ，如果看到 `{"status":"UP"}` 就说明应用正常运行了。

> **为什么需要这步？** 监控工具要读取应用的指标数据，应用得先跑起来。

#### 第二步：启动监控栈

```bash
# 进入监控目录
cd monitoring

# 一键拉起四个监控服务（首次会下载镜像，约 5-10 分钟）
docker-compose up -d
```

> **小白提示**：
> - `-d` 表示后台运行，不会占用你的终端
> - 首次启动会下载四个 Docker 镜像（共约 1.5GB），请耐心等待
> - 下载完成后，以后每次启动只需要几秒钟

#### 第三步：验证服务是否启动成功

```bash
# 查看四个服务是否都在运行
docker-compose ps
```

你应该看到类似这样的输出：

```
NAME                          STATUS
springbootai-prometheus       Up
springbootai-grafana          Up
springbootai-alertmanager     Up
springbootai-admin            Up
```

如果四个都是 `Up`，恭喜你，监控栈启动成功了！

### 7.4 打开 Grafana 仪表盘看图表

浏览器打开 **http://localhost:3000**

- 用户名：`admin`
- 密码：`admin`
- （首次登录会提示修改密码，点 "Skip" 跳过即可）

登录后，左侧菜单点 **Dashboards** → 你会看到一个叫 **"SpringBootAI 应用全景监控"** 的仪表盘，点进去就能看到 8 个图表：

#### 你会看到什么

| 图表 | 看什么 | 正常情况 | 异常情况 |
|------|--------|----------|----------|
| **CPU 使用率** | 折线图，显示进程 CPU 占比 | 5%-30% 波动 | 持续 >80% = 有问题 |
| **内存使用** | 两条线：RSS（实际内存）+ Virtual（虚拟内存） | RSS 稳定不增长 | RSS 持续上涨 = 内存泄漏 |
| **文件描述符** | 打开的文件句柄数 | 稳定在几十到几百 | 持续上涨不回落 = 资源泄漏 |
| **GC 次数** | Python 垃圾回收次数（按代分组） | 偶尔波动 | 频繁密集 = GC 压力大 |
| **GC 回收对象** | 每秒回收的对象数（柱状图） | 低矮柱子 | 高柱子密集 = 内存压力大 |
| **进程运行时长** | 大数字，显示应用已运行多久 | 绿色（>1天） | 红色（<1小时）= 刚重启过 |
| **应用健康状态** | UP（绿色）或 DOWN（红色） | 绿色 UP | 红色 DOWN = 应用挂了 |
| **抓取状态总览** | 表格，列出所有被监控的实例 | 都是 1 | 有 0 = 抓取失败 |

#### 仪表盘的三个实用功能

1. **自动刷新**：右上角时间选择器旁有刷新图标，默认 15 秒自动刷新一次
2. **时间范围**：右上角可选 "Last 5 minutes" / "Last 1 hour" / "Last 24 hours" 等
3. **实例筛选**：仪表盘顶部有下拉框，如果部署了多个实例，可以选择只看某一个

### 7.5 打开 Spring Boot Admin 面板

浏览器打开 **http://localhost:1111**

这是 Java 生态的原版 Spring Boot Admin Server，它会自动发现并监控你的 SpringBootAI 应用。你会看到：

- **应用列表**：显示 springbootai 实例，状态为 UP（绿色）
- **详情页**：点击应用名进入，可以看到
  - **Health**：健康检查详情（数据库、Redis 等各组件状态）
  - **Info**：应用版本、Python 版本、操作系统信息
  - **Metrics**：JVM/进程指标
  - **Environment**：环境变量和配置（敏感字段自动脱敏）
  - **Loggers**：日志级别管理（可在线切换 DEBUG/INFO/WARN/ERROR）
  - **Threads**：线程转储（查看线程状态和调用栈）
  - **Mappings**：所有 HTTP 路由列表

### 7.6 打开 Prometheus 查看原始数据

浏览器打开 **http://localhost:9090**

- 顶部菜单 **Status → Targets**：能看到 springbootai 抓取目标的状态（UP = 正常）
- 顶部搜索框输入 `process_resident_memory_bytes`，点 Execute：能看到当前内存使用量
- 顶部菜单 **Alerts**：能看到所有告警规则及其状态（绿色=正常，红色=触发中）

> **小白提示**：Prometheus 本身的界面比较简陋，主要是给运维人员排查用的。日常看图表用 Grafana 就行。

### 7.7 告警是怎么工作的

#### 告警流程

```
Prometheus 发现异常（比如 CPU > 80% 持续 5 分钟）
    │
    └──→ 推送给 Alertmanager
            │
            ├──→ 发钉钉/企业微信/邮件通知你（需要配置，见 7.8 节）
            │
            └──→ 推送到 /actuator/alert（你的应用接收）
                    │
                    └──→ 显示在 /actuator/admin 面板的"告警通知"区块
```

#### 预置的 7 条告警规则

| 告警名称 | 什么时候触发 | 级别 | 持续多久才报 |
|----------|-------------|------|-------------|
| **AppDown** | 应用完全不可访问 | 严重（红色） | 1 分钟 |
| **HighCpuUsage** | CPU 使用率 > 80% | 严重（红色） | 5 分钟 |
| **HighMemoryUsage** | 内存 RSS > 1GB | 严重（红色） | 5 分钟 |
| **HighFileDescriptors** | 打开文件数 > 900 | 警告（橙色） | 3 分钟 |
| **HighGcPressure** | 每秒 GC > 10 次 | 警告（橙色） | 5 分钟 |
| **ProcessRestarted** | 进程重启了 | 警告（橙色） | 立即 |
| **ScrapeFailure** | Prometheus 抓取失败 | 提示（蓝色） | 30 秒 |

> **为什么有"持续时间"？** 避免误报。CPU 偶尔飙到 90% 是正常的，但持续 5 分钟都 >80% 就真的有问题了。

#### 在 Admin 面板看告警

访问 http://localhost:8000/actuator/admin ，你会看到"告警通知"区块：

- **无告警时**：显示绿色 "✓ 无活跃告警"
- **有告警时**：显示表格，每行一条告警，按级别着色：
  - critical = 红色
  - warning = 橙色
  - info = 蓝色
- 告警恢复后状态变为绿色 "resolved"

### 7.8 配置钉钉/企业微信/邮件通知

默认只推送到应用的 `/actuator/alert` 端点（显示在 Admin 面板）。如果你想收到钉钉/邮件通知，需要编辑配置文件。

#### 方式一：钉钉机器人通知

1. 打开钉钉群 → 群设置 → 智能群助手 → 添加机器人 → 选"自定义"
2. 机器人名字随便填，安全设置选"加签"，复制出 Webhook 地址（类似 `https://oapi.dingtalk.com/robot/send?access_token=xxx`）
3. 编辑 `monitoring/alertmanager/alertmanager.yml`，找到钉钉部分，取消注释并填入 URL：

```yaml
  - name: "dingtalk"
    webhook_configs:
      - url: "https://oapi.dingtalk.com/robot/send?access_token=你的token"
        send_resolved: true   # 告警恢复时也通知
```

4. 重启 Alertmanager：

```bash
cd monitoring
docker-compose restart alertmanager
```

#### 方式二：企业微信机器人通知

1. 企业微信群 → 右上角 ... → 添加群机器人 → 复制 Webhook 地址
2. 编辑 `monitoring/alertmanager/alertmanager.yml`，取消注释企业微信部分：

```yaml
  - name: "wechat"
    webhook_configs:
      - url: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key"
        send_resolved: true
```

3. 重启 Alertmanager：`docker-compose restart alertmanager`

#### 方式三：邮件通知

编辑 `monitoring/alertmanager/alertmanager.yml`，取消注释邮件部分并填入 SMTP 信息：

```yaml
  - name: "email"
    email_configs:
      - to: "ops@company.com"              # 收件人
        from: "alert@company.com"           # 发件人
        smarthost: "smtp.company.com:587"   # SMTP 服务器地址
        auth_username: "alert@company.com"
        auth_password: "your-password"      # SMTP 密码
        require_tls: true
```

然后修改顶部的 `receiver: "email"` 把默认通知渠道改为邮件，重启 Alertmanager。

> **Spring Boot Admin Server 端口说明**：
> SBA Docker 镜像内部默认监听 **8181** 端口（不是 1111）。
> docker-compose 中映射为 `1111:8181`，即宿主机 1111 → 容器 8181。
> 访问地址仍然是 http://localhost:1111。
>
> **Windows Docker Desktop 兼容性**：
> SBA 3.3.4 在 Windows Docker Desktop 上因 cgroup v2 兼容性问题会崩溃，
> 已通过环境变量 `JAVA_TOOL_OPTIONS=-XX:-UseContainerSupport` 修复。

### 7.9 监控配置文件说明

```
monitoring/
├── docker-compose.yml                        ← 总配置：定义四个服务怎么启动
├── prometheus/
│   ├── prometheus.yml                        ← 抓取配置：告诉 Prometheus 去哪里抓数据
│   └── alerting_rules.yml                    ← 告警规则：什么情况算异常
├── alertmanager/
│   └── alertmanager.yml                      ← 通知渠道：告警发给谁
└── grafana/
    ├── provisioning/
    │   ├── datasources/prometheus.yml        ← 自动配置：告诉 Grafana 数据在 Prometheus
    │   └── dashboards/springbootai.yml       ← 自动配置：告诉 Grafana 仪表盘在哪
    └── dashboards/
        └── springbootai-overview.json        ← 仪表盘定义：8 个图表的配置
```

**每个文件的作用解释**：

| 文件 | 你需要改吗 | 说明 |
|------|-----------|------|
| `docker-compose.yml` | 一般不用改 | 定义四个 Docker 服务的端口、镜像、依赖关系 |
| `prometheus/prometheus.yml` | 改端口时需要改 | 如果你的应用不在 8000 端口，改这里的 `targets` |
| `prometheus/alerting_rules.yml` | 按需改 | 想加新告警规则（如磁盘空间）在这里加 |
| `alertmanager/alertmanager.yml` | 需要改 | 配置钉钉/邮件/微信通知地址 |
| `grafana/provisioning/*` | 不用改 | Grafana 自动配置，启动时自动加载 |
| `grafana/dashboards/*.json` | 一般不用改 | 仪表盘图表定义，想加新图表可以用 Grafana 界面编辑 |

### 7.10 如果你的应用端口不是 8000

如果你的 SpringBootAI 应用跑在别的端口（比如 5000），需要改两个地方：

**第一处**：`monitoring/prometheus/prometheus.yml`

```yaml
# 把 host.docker.internal:8000 改成你的端口
static_configs:
  - targets:
      - "host.docker.internal:5000"   # ← 改这里
```

**第二处**：`monitoring/docker-compose.yml` 中 Spring Boot Admin 的环境变量

```yaml
environment:
  - SPRING_BOOT_ADMIN_INSTANCE_HEALTH_URL=http://host.docker.internal:5000/actuator/health   # ← 改端口
  - SPRING_BOOT_ADMIN_INSTANCE_MANAGEMENT_URL=http://host.docker.internal:5000/actuator      # ← 改端口
  - SPRING_BOOT_ADMIN_INSTANCE_SERVICE_URL=http://host.docker.internal:5000                  # ← 改端口
```

改完后重启：

```bash
cd monitoring
docker-compose down
docker-compose up -d
```

### 7.11 如果开启了 Actuator 鉴权

生产环境建议开启 Actuator 鉴权（防止敏感端点被未授权访问）。开启后 Prometheus 也需要带 Token 才能抓取。

编辑 `monitoring/prometheus/prometheus.yml`，取消注释 `bearer_token`：

```yaml
  - job_name: "springbootai"
    metrics_path: "/actuator/prometheus"
    scheme: "http"
    bearer_token: "你的JWT-Token"    # ← 填入有效的 JWT Token
    static_configs:
      - targets:
          - "host.docker.internal:8000"
```

> **小白提示**：开发环境可以关闭鉴权，在 `application.yml` 中设置：
> ```yaml
> management:
>   endpoints:
>     web:
>       security:
>         enabled: false    # 关闭鉴权（仅开发环境）
> ```

### 7.12 日常操作速查

| 我想... | 怎么做 |
|---------|--------|
| 启动监控 | `cd monitoring && docker-compose up -d` |
| 停止监控 | `cd monitoring && docker-compose down` |
| 重启某个服务 | `docker-compose restart prometheus`（换服务名即可） |
| 查看服务状态 | `docker-compose ps` |
| 查看日志 | `docker-compose logs -f grafana`（换服务名即可） |
| 看 Grafana 图表 | 浏览器打开 http://localhost:3000 |
| 看 Admin 面板 | 浏览器打开 http://localhost:1111 |
| 看应用内置面板 | 浏览器打开 http://localhost:8000/actuator/admin |
| 看告警状态 | 浏览器打开 http://localhost:9093 |
| 清掉所有数据重来 | `docker-compose down -v`（`-v` 删除数据卷） |

### 7.13 常见问题排查

**Q：docker-compose up 后 Grafana 打不开？**

等 30 秒让 Grafana 完全启动。如果还是不行，看日志：

```bash
docker-compose logs grafana
```

**Q：Prometheus Targets 显示 DOWN？**

1. 确认你的 SpringBootAI 应用正在运行：浏览器打开 http://localhost:8000/actuator/health
2. 确认 `/actuator/prometheus` 能访问：浏览器打开 http://localhost:8000/actuator/prometheus
3. 如果应用跑在 Docker 里而不是宿主机上，把 `prometheus.yml` 中的 `host.docker.internal:8000` 改成 `应用容器名:8000`

**Q：Grafana 里看不到数据？**

1. 确认 Prometheus Targets 是 UP（http://localhost:9090 → Status → Targets）
2. 确认时间范围选对了（右上角选 "Last 5 minutes"）
3. 确认应用确实有流量（CPU/内存图表在应用空闲时可能是一条直线）

**Q：Spring Boot Admin 显示应用 OFFLINE？**

1. 确认应用正在运行
2. 确认 `/actuator/health` 返回 `{"status":"UP"}`
3. 如果开启了鉴权，SBA 也需要配置 Token（目前 SBA 默认不带 Token，仅适用于鉴权关闭的环境）

**Q：告警收到了但 Admin 面板没显示？**

Admin 面板 30 秒刷新一次，等一会儿再看。或者手动点页面右上角"刷新"按钮。

### 7.14 生产环境注意事项

1. **不要把监控端口暴露到公网**：Grafana/Prometheus/Alertmanager 端口只在内网开放，用 Nginx 反向代理 + IP 白名单
2. **数据持久化**：docker-compose 已配置数据卷（`prometheus-data` / `grafana-data`），重启不丢数据。但 `docker-compose down -v` 会删除数据
3. **资源占用**：四个服务共约 2GB 内存。如果服务器内存紧张，可以只跑 Prometheus + Grafana（去掉 Alertmanager 和 SBA）
4. **Prometheus 存储保留**：默认保留 30 天（`--storage.tsdb.retention.time=30d`），历史数据多了会占磁盘
5. **Linux 注意**：`host.docker.internal` 在 Linux 上需要 Docker 20.10+，低版本需要手动添加 `extra_hosts`

---

## mini-FAQ

**Q：生产环境能把 /actuator 暴露到公网吗？**
绝对不能！通过 Nginx 或网关做 IP 白名单或加认证。

**Q：/actuator/env 会泄露密码吗？**
不会。框架自动对 key 含 `password`/`secret`/`key`/`token`/`credential` 的值用 `******` 掩码。

**Q：threaddump 要一直开着吗？**
不要。只在排查死锁问题时临时开启，平时关掉（它会暴露代码路径）。

**Q：/actuator/admin 面板需要单独部署吗？**
不需要。HTML 内嵌在框架中，访问 `/actuator/admin` 即用。但页面内调用的敏感端点仍受 Actuator 鉴权保护。

**Q：Prometheus 抓取返回 503 怎么办？**
检查 `prometheus_client` 是否安装：`pip install prometheus_client`。

**Q：多 worker 部署下指标丢失？**
设置了 `PROMETHEUS_MULTIPROC_DIR` 环境变量吗？参考 [5.4 节](#54-多-worker-部署注意事项)。

**Q：Admin 面板的"内存 & CPU"显示 psutil not installed？**
执行 `pip install psutil` 即可。其它区块不受影响。

---

## 改进记录

### 新增端点未纳入鉴权体系 — 高 ✅ 已修复 (v2.3.0)

**位置**：`springbootai/web/actuator.py` /actuator/prometheus、/actuator/sysmetrics

**现象**：`/actuator/prometheus`、`/actuator/sysmetrics` 两个新端点未挂载鉴权依赖。sysmetrics 暴露进程 RSS、CPU、线程数、FD 数；prometheus 暴露 python_*/process_* 指标。

**修复方案**：将 `prometheus`、`sysmetrics` 加入 `_SENSITIVE_ENDPOINTS` 集合，挂载 `Depends(_prometheus_auth)` / `Depends(_sysmetrics_auth)` 鉴权依赖。`/actuator/admin` 保持不鉴权（HTML 无敏感数据）。

### 死代码函数 _check_actuator_auth() — 低 ✅ 已修复 (v2.3.0)

**位置**：`springbootai/web/actuator.py`

**现象**：`_check_actuator_auth()` 永远 `raise HTTPException(401)`，且未被任何端点调用（实际鉴权由 `_create_actuator_dependency` 返回的闭包完成）。

**修复方案**：删除该死代码函数。
