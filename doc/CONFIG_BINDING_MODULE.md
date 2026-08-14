# 配置绑定 —— 把 YAML 配置自动变成 Python 对象

> 框架版本：SpringBootAI 2.2.5
> 返回 [八大模块总览](EIGHT_MODULES.md)

---

## 你遇到了什么问题？

配置文件越来越长，你手写 `config["my-app"]["app-name"]` 取配置，字段名打错了要到运行时才报错，IDE 也没有提示。

## ① 是什么

**把 YAML 配置文件自动变成 Python 对象。** 你不用手动 `yaml.load()` 然后逐字段读取，框架自动把 `application.yml` 里的内容填进你定义的类，还帮你检查格式对不对。

## ② 怎么用

`application.yml`：

```yaml
my-app:
  app-name: demo-app
  max-connections: 32
  database:
    url: sqlite:///mem.db
    pool-size: 10
```

Python 代码：

```python
from spring.annotations.core import ConfigurationProperties, Component, Validated
from spring.config.binding import NestedConfigurationProperties

# 嵌套配置类
@NestedConfigurationProperties
class DatabaseProps:
    url: str = ""
    pool_size: int = 5     # 对应 YAML 的 pool-size（框架自动转换命名风格）

# 主配置类
@ConfigurationProperties("my-app")  # 绑定 my-app 前缀下的所有配置
@Component
@Validated                           # 启用字段校验
class MyAppProps:
    app_name: str = ""               # 绑定 my-app.app-name
    max_connections: int = 10        # 绑定 my-app.max-connections
    database: DatabaseProps = None   # 绑定 my-app.database.*
    # 结果：启动后这些字段自动填好，你不用写一行 yaml.load()
```

## 松散绑定规则（命名风格自动转换）

| YAML 里写的 | Python 字段名 | 能匹配吗？ |
|---|---|---|
| `app-name` | `app_name` | ✅ |
| `app-name` | `appName` | ✅ |
| `APP_NAME` | `app_name` | ✅ |
| `AppName` | `app_name` | ✅ |

## ③ 运行结果

启动后，`MyAppProps().app_name` 已经是 `"demo-app"`，`MyAppProps().database.url` 已经是 `"sqlite:///mem.db"`。IDE 有自动补全，拼错字段名启动时报错。

## mini-FAQ

**Q：嵌套配置为什么不生效？**
嵌套的类必须加 `@NestedConfigurationProperties`，否则子对象的字段不会绑定。

**Q：配置能动态刷新吗？**
不能。`@ConfigurationProperties` 只在启动时加载一次。需要动态刷新的配置用 `@NacosValue`（参见 [Cloud 模块文档](CLOUD_MODULE.md)）。

**Q：YAML 里写 `max-connections: "32"` 能自动转成 int 吗？**
不能！字符串不会自动转数字，YAML 里写 `max-connections: 32`（不加引号）才是数字。
