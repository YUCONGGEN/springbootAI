# SpringBootAI

SpringBootAI 是一个采用 Spring 风格注解和分层结构的 Python 应用框架。你可以使用 Python 编写 `@RestController`、`@Service`、`@Mapper` 和 `@Autowired`，框架负责组件扫描、依赖注入、Web 路由、事务切面及应用生命周期。

Web 运行时建立在 FastAPI、Starlette 和 Uvicorn 之上，同时提供 ORM、事务、缓存、消息队列、服务发现、生产治理以及 AI 生态集成。

> SpringBootAI 不是 Java Spring Boot 的 Python 绑定，也不是 Spring 官方项目。它适合熟悉 Controller、Service、Mapper 分层方式的团队，用统一写法开发 Web API、内部管理系统、数据服务和 AI 应用。

## 安装

SpringBootAI 2.3.6 支持 Python 3.10、3.11 和 3.12：

```bash
python -m pip install springbootAI
```

需要可选模块时，可以按需安装：

```bash
python -m pip install "springbootAI[ai]"
python -m pip install "springbootAI[langchain]"
python -m pip install "springbootAI[langgraph]"
python -m pip install "springbootAI[mcp]"
python -m pip install "springbootAI[mysql]"
python -m pip install "springbootAI[redis]"
```

安装全部可选能力：

```bash
python -m pip install "springbootAI[all]"
```

## 快速开始

创建应用入口 `demo/Application.py`：

```python
from springbootai.annotations import SpringBootApplication
from springbootai.main import run


@SpringBootApplication(scan_base_packages=["demo"])
class Application:
    pass


if __name__ == "__main__":
    run(Application)
```

创建控制器 `demo/controller/HelloController.py`：

```python
from springbootai.annotations import GetMapping, RequestMapping, RestController
from springbootai.web.swagger import Operation, Tag


@Tag(name="入门接口", description="确认应用已经正常运行")
@RequestMapping("/api")
@RestController
class HelloController:
    @Operation(summary="打招呼")
    @GetMapping("/hello/{name}")
    def hello(self, name: str):
        return {"message": f"Hello, {name}"}
```

创建 `demo/application.yml`，首次运行时关闭暂时不需要的外部资源：

```yaml
server:
  host: 127.0.0.1
  port: 8080

database:
  enabled: false

redis:
  enabled: false
```

启动应用：

```bash
python -m demo.Application
```

访问 `http://127.0.0.1:8080/api/hello/Alice` 验证接口，访问 `http://127.0.0.1:8080/docs` 查看 Swagger 文档。

## 核心能力

| 方向 | 能力 |
|---|---|
| Web 与 IoC | 路由映射、参数绑定、组件扫描、依赖注入、生命周期、Swagger |
| 数据与事务 | PyMyBatis Mapper、XML Mapper、分页、动态 SQL、事务和自动回滚 |
| 中间件与 Cloud | Redis、RabbitMQ、Kafka、Nacos、Feign、Gateway |
| 工程治理 | 配置合并、Profile、日志、健康检查、Prometheus、限流、熔断和链路追踪 |
| 安全能力 | JWT、OAuth2、CSRF、访问控制、密码加密和 SQL 注入防护 |
| AI 生态 | ChatClient、Tools、RAG、Advisor、LangChain、LangGraph 和 MCP client/server |
| 测试能力 | 测试切片、MockBean、TestPropertySource、集成测试和性能测试脚本 |

## 考试认证与证书

SpringBootAI 提供配套的在线考试认证平台。学习者、团队成员和项目使用方可以通过认证考试检验自己对框架核心能力的掌握情况，并在通过考试后获得对应证书。

认证入口：[http://www.yucg.cn:8230](http://www.yucg.cn:8230)

认证内容建议重点关注：

- 安装、项目结构、启动入口、扫描包、配置文件和 Swagger。
- Controller、Service、Mapper 分层以及 Bean 注册、依赖注入和生命周期。
- PyMyBatis、动态 SQL、分页、事务边界和回滚行为。
- Profile、日志、健康检查、Prometheus、限流、熔断和测试切片。
- JWT、OAuth2、CSRF、访问控制和常见安全错误处理。
- ChatClient、Tools、RAG、LangChain、LangGraph 和 MCP。

考试规则、题量、通过标准、证书领取方式和有效期以认证平台展示为准。

## 文档

- [GitHub 项目主页](https://github.com/YUCONGGEN/springbootAI)
- [完整 README](https://github.com/YUCONGGEN/springbootAI#readme)
- [新手指南](https://github.com/YUCONGGEN/springbootAI/blob/master/doc/BEGINNER_GUIDE.md)
- [全部模块文档](https://github.com/YUCONGGEN/springbootAI/tree/master/doc)
- [变更日志](https://github.com/YUCONGGEN/springbootAI/blob/master/CHANGELOG.md)
- [安全报告](https://github.com/YUCONGGEN/springbootAI/blob/master/SECURITY.md)

## 生产使用说明

项目当前标记为 Beta。用于公网高并发、合规敏感或支付、订单、库存等核心系统前，请完成目标数据库、流量模型、故障恢复和安全基线验证。

内嵌 Gateway 适合内部路由，不替代公网 Nginx、Kong 或 WAF。Seata `distributed` 模式对接官方 TC 与 TCC 回调；`at` 模式通过 ORM 拦截器生成 `undo_log` 实现自动回滚。

## 许可证

SpringBootAI 使用 [MIT License](https://github.com/YUCONGGEN/springbootAI/blob/master/LICENSE)。
