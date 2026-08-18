# example_all.common 全局基础设施

这个目录只放应用启动后自动生效的横切组件，不放分页、DTO、响应拼装或业务校验。

| 文件 | 自动机制 | 作用 |
| --- | --- | --- |
| `advice.py` | `@ControllerAdvice` + `@ExceptionHandler` | 统一异常转换为 `Result` |
| `monitoring.py` | `@Entity` + `@Mapper` + `@Component` + `HandlerInterceptor` | 将每个 HTTP 请求的次数、错误数和耗时持久化到数据库 |
| `context.py` | `ContextVar` | 保存当前请求的关联 ID，供日志和服务调用读取 |
| `exceptions.py` | Advice 自动匹配 | 定义应用级异常及状态码 |
| `constants.py` | 基础配置 | 请求头名称和错误码约定 |
| `utils.py` | 基础工具 | 生成关联 ID、脱敏日志元数据 |

## 自动执行链路

`Application` 使用 `@SpringBootApplication(scan_base_packages=["example_all"])`，并使用：

```python
@MapperScan(base_packages=["example_all.mappers", "example_all.common"])
```

框架启动时会自动完成以下工作：

1. 发现 `GlobalExceptionHandler`，注册为全局异常处理器。
2. 发现 `RequestMonitoringInterceptor`，自动加入 `InterceptorManager`。
3. 发现 `RequestMetricMapper`，注册 Mapper 代理。
4. 发现 `RequestMetric`，由 DDL 自动建表创建 `request_metrics` 表。
5. 每个请求经过拦截器生命周期，按路径执行查询、插入或累加更新。

## 持久化监控

访问：

```text
GET /api/common/monitoring
```

返回数据来自数据库中的 `request_metrics` 表，不是进程内字典；应用重启后计数仍然保留。`average_ms` 由持久化的总耗时和请求次数计算得到。

数据库配置需要启用 ORM，并将 `example_all.common` 放入实体扫描路径：

```yaml
database:
  enabled: true
  orm: mybatis
  ddl-auto:
    mode: update
    entity_packages:
      - example_all.common
```

`controller/ExceptionController.py` 仅用于主动抛出异常验证 Advice，不是全局配置。

## `context.py` 怎么用

`context.py` 保存的是当前执行链的关联 ID，例如 `order-123`。它只存在于当前
请求/异步任务的上下文中，适合让服务层和日志读取同一个 ID；它不会保存到数据库，
也不会代替 `request_metrics` 的监控数据。

### HTTP 请求（无需手动调用）

`RequestMonitoringInterceptor.pre_handle()` 会自动从 `X-Request-ID` 请求头读取 ID；
没有请求头时自动生成一个。请求结束时 `after_completion()` 会自动恢复上下文。

### 非 HTTP 任务（需要手动建立作用域）

```python
from example_all.common import get_request_id, request_scope

with request_scope("job-20260816"):
    # 这里调用的任意服务都可以读取同一个 ID
    print(get_request_id())  # job-20260816

# 退出 with 后，当前上下文恢复为进入之前的值
assert get_request_id() is None
```

### 底层 API

只有需要手动管理生命周期的框架代码才使用 `set_request_id()` 和
`reset_request_id(token)`；普通 Controller、Service 和定时任务优先使用
`request_scope()`，避免忘记恢复上下文。
