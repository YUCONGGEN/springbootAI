# Actuator —— 系统健康检查面板

> 框架版本：SpringBootAI 2.2.4
> 返回 [八大模块总览](EIGHT_MODULES.md)

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
| `/actuator/metrics` | 指标列表 | 监控系统拉取指标 |
| `/actuator/metrics/{name}` | 单个指标数值 | 查某个具体指标 |
| `/actuator/beans` | 已注册的所有 Bean | 排查 Bean 是否都注册了 |
| `/actuator/mappings` | 所有 HTTP 路由 | 确认接口路由是否注册成功 |
| `/actuator/threaddump` | 线程快照 | 排查死锁、卡死问题 |
| `/actuator/configprops` | 配置绑定结果 | 确认配置绑定是否正确 |
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

## mini-FAQ

**Q：生产环境能把 /actuator 暴露到公网吗？**
绝对不能！通过 Nginx 或网关做 IP 白名单或加认证。

**Q：/actuator/env 会泄露密码吗？**
不会。框架自动对 key 含 `password`/`secret`/`key`/`token` 的值用 `******` 掩码。

**Q：threaddump 要一直开着吗？**
不要。只在排查死锁问题时临时开启，平时关掉（它会暴露代码路径）。
