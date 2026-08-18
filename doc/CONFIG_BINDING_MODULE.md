# 配置绑定 —— 把 YAML 配置自动变成 Python 对象

> SpringBootAI 2.3.2
> 返回 [README 模块导航](../README.md#模块文档导航)

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
from springbootai.annotations.core import ConfigurationProperties, Component, Validated
from springbootai.config.binding import NestedConfigurationProperties

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

---

## 改进记录

### ApplicationContext._current_context 无锁保护 — 中 ⏳ 待处理 (v2.3.0)

**位置**：`springbootai/context/application_context.py` _current_context 类变量

**现象**：`_current_context` 是类变量，在 `__init__` 中直接赋值，无锁保护。多线程环境下存在数据竞争。

**改进方案**：使用 `threading.Lock` 保护读写，或改为 `ContextVar` 实现协程安全的上下文传播。

### refresh() 失败后部分 Bean 已注册，状态不一致 — 高 ✅ 已修复 (v2.3.0)

**位置**：`springbootai/context/application_context.py` refresh()

**现象**：`refresh()` 按顺序执行各步骤，若中间某步抛异常，前面已注册的 Bean 不会回滚，`_started` 仍为 `False`，再次调用 `refresh()` 行为不可预测。

**修复方案**：在 `refresh()` 入口保存 Bean 名快照，失败时调用新增的 `_rollback_refresh()` 方法：停止已启动的定时任务、移除本次新增的 Bean 定义，确保状态一致。

### 生产环境配置校验逻辑重复且分散 — 低 ⏳ 待处理 (v2.4.0)

**位置**：`springbootai/config/config_loader.py` _validate_prod_config

**现象**：`_validate_prod_config` 中对 JWT、Seata、AI 的校验逻辑各自独立，缺乏统一校验框架，违反开闭原则。

**改进方案**：抽象 `ProdConfigRule` 接口，每条规则独立一个类，通过注册表模式收集所有规则。

---

## 配置元数据（IDE 自动补全）

### 配置元数据是什么？

**配置元数据 = 一份描述"框架支持哪些配置项"的清单文件。** IDE 读取这份文件后，在编辑 `application.yml` 时能提供配置项的自动补全、类型提示和文档说明——就像 Spring Boot 在 IDEA 里编辑 `application.properties` 时的体验。

> 💡 比喻：配置元数据像"配置字典"——IDE 翻开它，就知道框架认得哪些配置项、每项是什么类型、默认值是多少。

### 文件位置

```
springbootai/config/spring-configuration-metadata.json
```

> 对齐 Java Spring Boot 的 `META-INF/spring-configuration-metadata.json` 约定，文件名保持一致，便于工具识别。

### 文件格式

JSON 结构，顶层包含 `version`、`metadata` 和 `properties` 三部分：

```json
{
  "version": 1,
  "metadata": {
    "description": "SpringBootAI 配置元数据（对齐 Spring Boot additional-spring-configuration-metadata.json）",
    "note": "IDE 可读取此文件提供配置自动补全和文档提示"
  },
  "properties": [
    {
      "name": "server.port",
      "type": "java.lang.Integer",
      "description": "HTTP 服务端口",
      "defaultValue": 8000
    },
    {
      "name": "springbootai.kafka.bootstrap-servers",
      "type": "java.lang.String",
      "description": "Kafka Bootstrap Servers",
      "defaultValue": "localhost:9092"
    }
  ]
}
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `version` | `int` | 元数据格式版本（当前为 `1`） |
| `metadata.description` | `str` | 元数据文件描述 |
| `metadata.note` | `str` | 使用说明 |
| `properties[].name` | `str` | 配置项全名（如 `server.port`） |
| `properties[].type` | `str` | 配置项类型（对齐 Java 类型命名） |
| `properties[].description` | `str` | 配置项说明（IDE 提示展示） |
| `properties[].defaultValue` | `Any` | 默认值（可选） |

### 支持的配置项

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `server.port` | Integer | `8000` | HTTP 服务端口 |
| `server.host` | String | `0.0.0.0` | HTTP 服务绑定地址 |
| `server.cors.allow-origins` | List<String> | — | CORS 允许的源列表 |
| `server.cors.allow-credentials` | Boolean | `false` | CORS 是否允许携带凭证 |
| `server.csrf.enabled` | Boolean | `false` | 是否启用 CSRF 防护（Bearer Token 认证无需开启） |
| `springbootai.application.name` | String | — | 应用名称 |
| `springbootai.profiles.active` | String | — | 激活的 Profile |
| `springbootai.devtools.restart.enabled` | Boolean | `false` | 是否启用 DevTools 热重载（仅开发环境） |
| `springbootai.devtools.restart.poll-interval` | Float | `1.0` | 文件轮询间隔（秒） |
| `springbootai.datasource.url` | String | — | 数据库连接 URL |
| `springbootai.datasource.username` | String | — | 数据库用户名 |
| `springbootai.datasource.password` | String | — | 数据库密码 |
| `springbootai.datasource.driver-class-name` | String | — | 数据库驱动类名 |
| `springbootai.datasource.pool-size` | Integer | `10` | 连接池大小 |
| `springbootai.ddl-auto.mode` | String | `none` | DDL 自动生成模式（none/create/update/validate/create-drop） |
| `springbootai.ddl-auto.entity-packages` | List<String> | — | @Entity 实体类所在包列表 |
| `springbootai.security.jwt.secret-key` | String | — | JWT 签名密钥（长度 ≥ 32，生产环境必须配置） |
| `springbootai.security.jwt.access-token-expiry` | Integer | `3600` | Access Token 过期时间（秒） |
| `springbootai.security.jwt.refresh-token-expiry` | Integer | `604800` | Refresh Token 过期时间（秒） |
| `springbootai.security.oauth2.resourceserver.jwt.issuer-uri` | String | — | OAuth2 Authorization Server 的 Issuer URI |
| `springbootai.security.oauth2.resourceserver.jwt.jwk-set-uri` | String | — | OAuth2 JWKS 公钥集 URI |
| `springbootai.rabbitmq.host` | String | `localhost` | RabbitMQ 主机 |
| `springbootai.rabbitmq.port` | Integer | `5672` | RabbitMQ 端口 |
| `springbootai.kafka.bootstrap-servers` | String | `localhost:9092` | Kafka Bootstrap Servers |
| `springbootai.kafka.consumer.group-id` | String | — | Kafka 消费者组 ID |
| `springbootai.kafka.consumer.auto-offset-reset` | String | `latest` | Kafka 消费者 Offset 重置策略（latest/earliest） |
| `springbootai.redis.host` | String | `localhost` | Redis 主机 |
| `springbootai.redis.port` | Integer | `6379` | Redis 端口 |
| `springbootai.cloud.nacos.discovery.server-addr` | String | — | Nacos 服务发现地址 |
| `springbootai.cloud.seata.mode` | String | `at` | Seata 分布式事务模式（at/tcc/http/distributed） |
| `management.endpoints.web.security.enabled` | Boolean | `true` | Actuator 敏感端点鉴权开关 |
| `management.endpoints.web.security.roles` | List<String> | `["ADMIN","ACTUATOR"]` | Actuator 访问角色列表 |
| `springbootai.ai.provider` | String | — | AI 模型提供商（openai/deepseek/ollama/zhipu/fake） |
| `springbootai.ai.api-key` | String | — | AI API Key |
| `springbootai.ai.allow-fake` | Boolean | `false` | 无 API Key 时是否降级 FakeChatModel |

### 如何在 IDE 中使用

1. **保持文件位置不变**：文件需放在 `springbootai/config/spring-configuration-metadata.json`，IDE 插件按此路径检索。
2. **安装对应插件**：
   - IntelliJ IDEA：安装 Spring Boot 插件，它会识别 `spring-configuration-metadata.json` 文件并提供 `application.yml` 的自动补全。
   - VS Code：安装 Spring Boot Tools 扩展，可识别同类元数据文件。
3. **编辑 `application.yml` 时**：在配置项的键位置触发补全（`Ctrl+Space`），IDE 会列出所有已声明的配置项及其说明。
4. **悬停查看文档**：鼠标悬停在配置项上，IDE 会显示 `description` 字段的说明文本。
5. **新增自定义配置**：在 `properties` 数组中追加一个对象（含 `name` / `type` / `description` / `defaultValue`），重启 IDE 即可生效。

> ⚠️ 元数据只影响 IDE 提示体验，不影响框架运行时行为。即使不配置元数据，框架仍能正常运行——只是少了自动补全。

### 与 Java Spring Boot 的对照

| 维度 | Java Spring Boot | SpringBootAI |
|------|------------------|--------------|
| 文件名 | `spring-configuration-metadata.json` | `spring-configuration-metadata.json`（同名） |
| 文件位置 | `META-INF/`（jar 内） | `springbootai/config/`（源码目录） |
| 文件格式 | JSON（`properties` + `hints`） | JSON（`properties`，暂无 `hints`） |
| 类型命名 | Java 全限定类名（如 `java.lang.Integer`） | 同 Java 命名（保持一致） |
| 生成方式 | 注解处理器自动生成（`@ConfigurationProperties`） | 手动维护 JSON 文件 |
| IDE 支持 | IDEA / VS Code 原生支持 | 复用同一套 IDE 插件识别 |
| 额外提示 | 支持 `hints`（枚举值提示） | 暂未实现 `hints` 段 |
