# Actuator —— 系统健康检查面板

> 框架版本：SpringBootAI 2.2.5
> 返回 [八大模块总览](EIGHT_MODULES.md)

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
- [mini-FAQ](#mini-faq)

---

## 你遇到了什么问题？

应用上线后出问题了——内存够不够？数据库连不连得上？哪些配置生效了？你没法钻到服务器里看，线上又不能随便打断点调试。

## ① 是什么

**给应用装一个"体检仪"**——一个内置的管理页面，随时查看应用健康状态、配置、内存、线程等。就像体检时用各种仪器检查身体各项指标，看到系统是否正常运行。

## ② 怎么用

```python
from spring.web.actuator import configure_actuator

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

只要 Actuator 已注册，**无需任何额外配置**，直接浏览器访问：

```
http://127.0.0.1:8080/actuator/admin
```

> 末尾带不带斜杠都行：`/actuator/admin/` 同样可访问。

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
from spring.monitoring.prometheus import prometheus_metrics

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
