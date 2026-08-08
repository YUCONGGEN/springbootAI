# Spring 注解使用指南

本文档详细介绍所有注解的含义、参数、用法示例和注意事项。

---

## 目录

- [一、核心基础注解](#一核心基础注解)
  - [1. 启动与扫描](#1-启动与扫描)
  - [2. 组件与依赖注入](#2-组件与依赖注入)
  - [3. Web 控制器](#3-web-控制器)
  - [4. 参数绑定](#4-参数绑定)
  - [5. 配置与属性](#5-配置与属性)
  - [6. 异常处理](#6-异常处理)
  - [7. 事务与缓存](#7-事务与缓存)
  - [8. 定时任务与异步](#8-定时任务与异步)
  - [9. 日志与生命周期](#9-日志与生命周期)
  - [10. 应用事件](#10-应用事件)
- [二、核心高级注解（10个）](#二核心高级注解10个)
- [三、Spring Cloud 微服务注解（11个）](#三spring-cloud-微服务注解11个)
- [四、注解组合使用指南](#四注解组合使用指南)
- [五、常见问题](#五常见问题)

---

## 一、核心基础注解

### 1. 启动与扫描

#### @SpringBootApplication

**含义**：Spring Boot 应用启动类注解，组合了 `@Configuration`、`@ComponentScan` 和 `@Configuration` 的功能。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| scan_base_packages | List[str] | None | 扫描的基础包路径 |

**用法示例**：
```python
from spring.annotations.core import SpringBootApplication

@SpringBootApplication(scan_base_packages=["com.example.service", "com.example.controller"])
class Application:
    pass
```

**注意事项**：
- 每个应用只能有一个启动类
- 不指定 scan_base_packages 时，默认扫描启动类所在包及其子包

---

#### @ComponentScan

**含义**：指定 Spring 容器扫描的包路径，用于发现和注册 Bean。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| base_packages | List[str] | None | 扫描的基础包路径 |

**用法示例**：
```python
from spring.annotations.core import Configuration, ComponentScan

@Configuration
@ComponentScan(base_packages=["com.example.service", "com.example.dao"])
class AppConfig:
    pass
```

---

### 2. 组件与依赖注入

#### @Service

**含义**：标记业务逻辑层组件，属于 `@Component` 的特化版本。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| value | str | "" | Bean 名称，默认使用类名首字母小写 |

**用法示例**：
```python
from spring.annotations.core import Service

@Service
class UserService:
    """用户服务"""
    def get_user(self, user_id: int):
        return {"id": user_id, "name": "test"}
```

---

#### @Component

**含义**：通用组件注解，标记一个类为 Spring 管理的 Bean。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| value | str | "" | Bean 名称 |

**用法示例**：
```python
from spring.annotations.core import Component

@Component
class EmailUtil:
    """邮件工具类"""
    def send(self, to: str, content: str):
        pass
```

---

#### @Repository

**含义**：数据访问层组件注解，属于 `@Component` 的特化版本。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| value | str | "" | Bean 名称 |

**用法示例**：
```python
from spring.annotations.core import Repository

@Repository
class UserRepository:
    """用户数据访问层"""
    def find_by_id(self, user_id: int):
        pass
```

---

#### @Controller

**含义**：控制器层组件，用于处理 HTTP 请求并返回视图。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| value | str | "" | Bean 名称 |

**用法示例**：
```python
from spring.annotations.core import Controller, GetMapping

@Controller
class PageController:
    """页面控制器"""
    @GetMapping("/home")
    def home(self):
        return "home.html"
```

---

#### @RestController

**含义**：RESTful 控制器，组合了 `@Controller` 和 `@ResponseBody`，返回值自动序列化为 JSON。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| value | str | "" | Bean 名称 |

**用法示例**：
```python
from spring.annotations.core import RestController, GetMapping

@RestController
class UserController:
    """用户 API 控制器"""
    @GetMapping("/api/users/{id}")
    def get_user(self, id: int):
        return {"id": id, "name": "test"}
```

---

#### @Autowired

**含义**：自动装配依赖，按类型注入 Bean。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| required | bool | True | 是否必须注入，为 False 时找不到 Bean 不会报错 |

**用法示例**：
```python
from spring.annotations.core import Service, Autowired

@Service
class UserService:
    # 构造函数注入（推荐）
    @Autowired
    def __init__(self, user_repository):
        self.user_repository = user_repository
```

---

#### @Qualifier

**含义**：当有多个同类型 Bean 时，指定要注入的 Bean 名称。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| value | str | 必填 | Bean 名称 |

**用法示例**：
```python
from spring.annotations.core import Service, Autowired, Qualifier

@Service
class OrderService:
    @Autowired
    def __init__(self, @Qualifier("mysqlDataSource") data_source):
        self.data_source = data_source
```

---

#### @Primary

**含义**：当有多个同类型 Bean 时，标记首选的 Bean。

**用法示例**：
```python
from spring.annotations.core import Configuration, Bean, Primary

@Configuration
class DataSourceConfig:
    @Bean
    @Primary
    def primary_data_source(self):
        return {"url": "jdbc:mysql://primary:3306/db"}
    
    @Bean
    def secondary_data_source(self):
        return {"url": "jdbc:mysql://secondary:3306/db"}
```

---

### 3. Web 控制器

#### @RequestMapping

**含义**：映射 HTTP 请求到处理方法，支持多种 HTTP 方法。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| path | str \| List[str] | "" | 请求路径 |
| method | List[str] | [] | HTTP 方法：GET, POST, PUT, PATCH, DELETE 等 |
| consumes | str | None | 请求的 Content-Type |
| produces | str | None | 响应的 Content-Type |

**用法示例**：
```python
from spring.annotations.core import RestController, RequestMapping

@RestController
@RequestMapping("/api/users")
class UserController:
    """用户控制器"""
    
    @RequestMapping(path="/{id}", method=["GET"])
    def get_user(self, id: int):
        return {"id": id}
```

---

#### @GetMapping

**含义**：GET 请求映射，相当于 `@RequestMapping(method=["GET"])`。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| path | str \| List[str] | "" | 请求路径 |
| consumes | str | None | 请求 Content-Type |
| produces | str | None | 响应 Content-Type |

**用法示例**：
```python
from spring.annotations.core import RestController, GetMapping

@RestController
class UserController:
    @GetMapping("/api/users/{id}")
    def get_user(self, id: int):
        return {"id": id, "name": "test"}
```

---

#### @PostMapping

**含义**：POST 请求映射，用于创建资源。

**用法示例**：
```python
from spring.annotations.core import RestController, PostMapping

@RestController
class UserController:
    @PostMapping("/api/users")
    def create_user(self, name: str, email: str):
        return {"id": 1, "name": name, "email": email}
```

---

#### @PutMapping

**含义**：PUT 请求映射，用于更新资源。

**用法示例**：
```python
from spring.annotations.core import RestController, PutMapping

@RestController
class UserController:
    @PutMapping("/api/users/{id}")
    def update_user(self, id: int, name: str):
        return {"id": id, "name": name}
```

---

#### @PatchMapping

**含义**：PATCH 请求映射，用于对资源执行部分更新。框架会把它注册为真实的 FastAPI PATCH 路由，并纳入默认 CORS 方法。

**用法示例**：
```python
from spring.annotations.core import RestController, PatchMapping

@RestController
class UserController:
    @PatchMapping("/api/users/{id}")
    def patch_user(self, id: int, name: str = ""):
        return {"id": id, "name": name, "method": "PATCH"}
```

---

#### @DeleteMapping

**含义**：DELETE 请求映射，用于删除资源。

**用法示例**：
```python
from spring.annotations.core import RestController, DeleteMapping

@RestController
class UserController:
    @DeleteMapping("/api/users/{id}")
    def delete_user(self, id: int):
        return {"status": "deleted", "id": id}
```

---

#### @CrossOrigin

**含义**：跨域资源共享（CORS）配置，允许前端跨域访问。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| origins | List[str] | ["*"] | 允许的源 |
| methods | List[str] | ["GET","POST","PUT","PATCH","DELETE","OPTIONS"] | 允许的 HTTP 方法 |
| allowedHeaders | List[str] | ["*"] | 允许的请求头 |
| allowCredentials | bool | False | 是否允许携带凭证 |
| maxAge | int | 3600 | 预检请求缓存时间（秒） |

**用法示例**：
```python
from spring.annotations.core import RestController, GetMapping, CrossOrigin

@RestController
@CrossOrigin(origins=["http://localhost:3000"], allow_credentials=True)
class UserController:
    @GetMapping("/api/users")
    def list_users(self):
        return []
```

---

#### @ResponseStatus

**含义**：设置方法返回的 HTTP 状态码。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| code | int | 必填 | HTTP 状态码 |
| reason | str | "" | 状态原因 |

**用法示例**：
```python
from spring.annotations.core import RestController, PostMapping, ResponseStatus

@RestController
class UserController:
    @PostMapping("/api/users")
    @ResponseStatus(code=201, reason="Created")
    def create_user(self, name: str):
        return {"id": 1, "name": name}
```

---

### 4. 参数绑定

#### @RequestParam

**含义**：绑定 URL 查询参数到方法参数。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | None | 参数名，默认使用方法参数名 |
| required | bool | True | 是否必须 |
| default | Any | None | 默认值 |

**用法示例**：
```python
from spring.annotations.core import RestController, GetMapping, RequestParam

@RestController
class UserController:
    @GetMapping("/api/users")
    def list_users(
        self,
        page: int = RequestParam(name="page", default=1),
        size: int = RequestParam(name="size", default=10)
    ):
        return {"page": page, "size": size, "data": []}
```

---

#### @PathVariable

**含义**：绑定 URL 路径变量到方法参数。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | None | 变量名，默认使用方法参数名 |
| required | bool | True | 是否必须 |

**用法示例**：
```python
from spring.annotations.core import RestController, GetMapping, PathVariable

@RestController
class UserController:
    @GetMapping("/api/users/{id}")
    def get_user(self, id: int = PathVariable(name="id")):
        return {"id": id}
```

---

#### @RequestBody

**含义**：绑定请求体（JSON）到方法参数。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| required | bool | True | 是否必须 |

**用法示例**：
```python
from spring.annotations.core import RestController, PostMapping, RequestBody

@RestController
class UserController:
    @PostMapping("/api/users")
    def create_user(self, user_data: dict = RequestBody()):
        return {"id": 1, **user_data}
```

---

#### @RequestHeader

**含义**：绑定请求头到方法参数。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | None | 请求头名称 |
| required | bool | True | 是否必须 |
| default | Any | None | 默认值 |

**用法示例**：
```python
from spring.annotations.core import RestController, GetMapping, RequestHeader

@RestController
class UserController:
    @GetMapping("/api/user/profile")
    def get_profile(self, token: str = RequestHeader(name="Authorization")):
        return {"token": token}
```

---

#### @CookieValue

**含义**：绑定 Cookie 值到方法参数。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | None | Cookie 名称 |
| required | bool | True | 是否必须 |
| default | Any | None | 默认值 |

**用法示例**：
```python
from spring.annotations.core import RestController, GetMapping, CookieValue

@RestController
class UserController:
    @GetMapping("/api/user/theme")
    def get_theme(self, theme: str = CookieValue(name="theme", default="light")):
        return {"theme": theme}
```

---

### 5. 配置与属性

#### @Configuration

**含义**：配置类注解，用于定义 Bean 和配置。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| proxyBeanMethods | bool | True | 是否代理 Bean 方法以实现单例 |

**用法示例**：
```python
from spring.annotations.core import Configuration, Bean

@Configuration
class AppConfig:
    @Bean
    def data_source(self):
        return {"url": "jdbc:mysql://localhost:3306/db"}
```

---

#### @Bean

**含义**：在配置类中定义一个 Bean。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | None | Bean 名称，默认使用方法名 |
| scope | str | "singleton" | 作用域：singleton, prototype |
| init_method | str | None | 初始化方法名 |
| destroy_method | str | None | 销毁方法名 |

**用法示例**：
```python
from spring.annotations.core import Configuration, Bean

@Configuration
class AppConfig:
    @Bean(name="dataSource", init_method="init", destroy_method="close")
    def data_source(self):
        return DataSource()
```

---

#### @Value

**含义**：注入配置值到字段或方法参数。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| value | str | 必填 | 配置键，如 "${app.name}" |

**用法示例**：
```python
from spring.annotations.core import Service, Value

@Service
class AppService:
    def __init__(self):
        self.app_name = None
    
    @Value("${app.name}")
    def set_app_name(self, value: str):
        self.app_name = value
```

---

#### @ConfigurationProperties

**含义**：批量绑定配置属性到类。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| prefix | str | 必填 | 配置前缀 |

**用法示例**：
```python
from spring.annotations.core import ConfigurationProperties, Component

@Component
@ConfigurationProperties(prefix="spring.datasource")
class DataSourceProperties:
    def __init__(self):
        self.url = ""
        self.username = ""
        self.password = ""
        self.driver_class_name = ""
```

---

#### @Profile

**含义**：指定 Bean 在特定环境（Profile）下才生效。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| value | str \| List[str] | 必填 | 环境名称 |

**用法示例**：
```python
from spring.annotations.core import Configuration, Bean, Profile

@Configuration
class DataSourceConfig:
    @Bean
    @Profile("dev")
    def dev_data_source(self):
        return {"url": "jdbc:mysql://dev:3306/db"}
    
    @Bean
    @Profile("prod")
    def prod_data_source(self):
        return {"url": "jdbc:mysql://prod:3306/db"}
```

---

#### @Lazy

**含义**：延迟初始化 Bean，在首次使用时才创建。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| value | bool | True | 是否延迟加载 |

**用法示例**：
```python
from spring.annotations.core import Service, Lazy

@Service
@Lazy
class HeavyService:
    """重量级服务，延迟初始化"""
    def __init__(self):
        # 耗时的初始化操作
        pass
```

---

#### ConfigLoader 与 ApplicationContext

`ApplicationContext` 会根据启动类目录读取 `application.yml`，找不到时读取 `config/application.yml`，并把加载器状态绑定到全局 `spring.config.config_loader`。绑定完成后，新建的 `ConfigLoader()` 会复用同一配置目录；因此不要再依赖进程当前工作目录，也不要在应用启动后维护另一份全局配置对象。

### 6. 异常处理

#### @ControllerAdvice

**含义**：全局控制器增强，用于全局异常处理、全局数据绑定等。

**用法示例**：
```python
from spring.annotations.core import ControllerAdvice, ExceptionHandler

@ControllerAdvice
class GlobalExceptionHandler:
    @ExceptionHandler(Exception)
    def handle_exception(self, e: Exception):
        return {"code": 500, "message": str(e)}
```

---

#### @ExceptionHandler

**含义**：异常处理方法注解，捕获指定类型的异常并处理。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| *exceptions | Type[Exception] | - | 要捕获的异常类型（可变参数） |
| value | List[Type[Exception]] | None | 要捕获的异常类型列表 |

**用法示例**：
```python
from spring.annotations.core import ControllerAdvice, ExceptionHandler

@ControllerAdvice
class GlobalExceptionHandler:
    @ExceptionHandler(ValueError, TypeError)
    def handle_validation_error(self, e: Exception):
        return {"code": 400, "message": f"参数错误: {str(e)}"}
    
    @ExceptionHandler(Exception)
    def handle_generic_error(self, e: Exception):
        return {"code": 500, "message": f"服务器错误: {str(e)}"}
```

---

### 7. 事务与缓存

#### @Transactional

**含义**：事务管理注解，确保方法内的操作要么全部成功，要么全部回滚。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| propagation | str | "REQUIRED" | 传播行为 |
| rollback_for | List[Type[Exception]] | [] | 触发回滚的异常 |
| no_rollback_for | List[Type[Exception]] | [] | 不触发回滚的异常 |

**用法示例**：
```python
from spring.annotations.core import Service, Transactional

@Service
class OrderService:
    @Transactional(rollback_for=[Exception])
    def create_order(self, user_id: int, product_id: int):
        # 1. 创建订单
        # 2. 扣减库存
        # 3. 任意一步异常都会回滚
        return {"order_id": 1}
```

---

#### @Cacheable

**含义**：方法结果缓存注解，首次调用后缓存结果，后续相同参数直接返回缓存。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| value | str | 必填 | 缓存名称 |
| key | str | None | 缓存键 |
| condition | str | None | 缓存条件 |

**用法示例**：
```python
from spring.annotations.core import Service, Cacheable

@Service
class UserService:
    @Cacheable(value="users", key="#user_id")
    def get_user(self, user_id: int):
        # 耗时的数据库查询
        return {"id": user_id, "name": "test"}
```

---

### 8. 定时任务与异步

#### @Scheduled

**含义**：定时任务注解，按指定规则周期性执行方法。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| fixed_rate | int | None | 固定速率执行（毫秒） |
| fixed_delay | int | None | 固定延迟执行（毫秒） |
| cron | str | None | Cron 表达式 |
| initial_delay | int | 0 | 初始延迟（毫秒） |

**用法示例**：
```python
from spring.annotations.core import Service, Scheduled

@Service
class ScheduledTasks:
    # 每 5 秒执行一次
    @Scheduled(fixed_rate=5000)
    def report_current_time(self):
        print("Current time:", time.time())
    
    # 每分钟执行一次（Cron 表达式）
    @Scheduled(cron="0 * * * * *")
    def hourly_task(self):
        print("Hourly task executed")
```

---

#### @Async

**含义**：异步执行注解，被注解的方法会在单独的线程中执行。

**用法示例**：
```python
from spring.annotations.core import Service, Async

@Service
class EmailService:
    @Async
    def send_email(self, to: str, content: str):
        # 异步发送邮件，不会阻塞调用方
        time.sleep(1)  # 模拟发送耗时
        print(f"Email sent to {to}")
```

---

### 9. 日志与生命周期

#### @Slf4j

**含义**：自动注入 logger 对象，简化日志代码。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| logger_name | str | None | Logger 名称，默认使用类名 |

**用法示例**：
```python
from spring.annotations.core import Service, Slf4j

@Service
@Slf4j
class UserService:
    def create_user(self, name: str):
        self.logger.info(f"Creating user: {name}")
        return {"id": 1, "name": name}
```

---

#### @LogExecutionTime

**含义**：自动记录方法执行时间的日志。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| log_level | str | "info" | 日志级别 |

**用法示例**：
```python
from spring.annotations.core import Service, LogExecutionTime

@Service
class ReportService:
    @LogExecutionTime(log_level="info")
    def generate_report(self, report_type: str):
        # 耗时的报表生成
        time.sleep(1)
        return {"report": report_type}
```

---

#### @PostConstruct

**含义**：Bean 初始化完成后执行的方法，在依赖注入完成后调用。

**用法示例**：
```python
from spring.annotations.core import Service, PostConstruct

@Service
class InitService:
    def __init__(self):
        self.config = None
    
    @PostConstruct
    def init(self):
        # 初始化逻辑，在所有依赖注入完成后执行
        self.config = self.load_config()
        print("InitService initialized")
```

---

#### @PreDestroy

**含义**：Bean 销毁前执行的方法，用于清理资源。

**用法示例**：
```python
from spring.annotations.core import Service, PreDestroy

@Service
class ConnectionService:
    def __init__(self):
        self.connection = None
    
    @PreDestroy
    def cleanup(self):
        # 销毁前清理资源
        if self.connection:
            self.connection.close()
            print("Connection closed")
```

---

### 10. 应用事件

`ApplicationEvent` 是事件基类，`@EventListener` 标记受管 Bean 的监听方法。`ApplicationContext` 刷新时会自动扫描监听器，`publish_event()` 默认按 `order` 同步调用匹配的监听器；异步监听方法会被调度到当前事件循环或异步执行器。

```python
from spring.annotations import ApplicationEvent, Autowired, EventListener, Service
from spring.event import ApplicationEventPublisher


class UserCreatedEvent(ApplicationEvent):
    def __init__(self, user_id: int):
        super().__init__(source="user-service")
        self.user_id = user_id


@Service
class UserEventHandler:
    @EventListener(event_type=UserCreatedEvent, order=1)
    def on_user_created(self, event: UserCreatedEvent):
        print(f"created: {event.user_id}")


@Service
class UserService:
    @Autowired
    def __init__(self, publisher: ApplicationEventPublisher):
        self.publisher = publisher

    def create(self, user_id: int):
        self.publisher.publish_event(UserCreatedEvent(user_id))
```

监听方法的第一个事件参数可以省略 `event_type`，框架会从类型注解推断。监听器异常会由发布调用方感知；需要隔离失败时应在监听器内部处理异常或使用异步任务。

---

## 二、核心高级注解（10个）

### 1. @RateLimit - 接口限流

**含义**：限制接口在指定时间窗口内的请求次数，防止接口被恶意刷流量。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| max_requests | int | 100 | 时间窗口内允许的最大请求数 |
| time_window | int | 60 | 时间窗口（秒） |
| key | str | None | 限流键，支持动态参数（见下方说明） |

**Key 动态解析规则**：
- 直接写参数名：`key="user_id"` → 按用户ID限流
- 使用占位符：`key="ip_{ip}"` → 组合前缀和参数
- 不指定：使用方法全限定名作为键

**用法示例**：
```python
from spring.annotations.core import RateLimit, Service

@Service
class OrderService:
    
    # 每分钟最多100次请求（全局限流）
    @RateLimit(max_requests=100, time_window=60)
    def create_order(self, user_id: str, product_id: str):
        """创建订单"""
        return {"order_id": "ORD_123"}
    
    # 按用户ID限流，每个用户每秒最多10次
    @RateLimit(max_requests=10, time_window=1, key="user_id")
    def get_user_info(self, user_id: str):
        """获取用户信息"""
        return {"user_id": user_id}
```

**注意事项**：
- 线程安全，支持高并发场景
- 存储有大小限制（10000条），超出自动清理最旧条目
- 超出限流会抛出 `Exception: Rate limit exceeded: ...`

---

### 2. @CircuitBreaker - 熔断器

**含义**：监控方法调用失败率，达到阈值后自动熔断，快速失败避免级联故障。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| failure_threshold | int | 5 | 连续失败次数阈值，达到后熔断 |
| recovery_timeout | int | 30 | 熔断恢复时间（秒），过后进入半开状态 |
| fallback_method | str | None | 熔断时的降级方法名 |

**状态流转**：
```
CLOSED（关闭）→ 失败达到阈值 → OPEN（熔断）
     ↑                        ↓
     ↓  半开状态成功     等待recovery_timeout
HALF_OPEN（半开） ←───────────┘
```

**用法示例**：
```python
from spring.annotations.core import CircuitBreaker, Service

@Service
class PaymentService:
    
    @CircuitBreaker(failure_threshold=3, recovery_timeout=10, fallback_method="payment_fallback")
    def process_payment(self, order_id: str, amount: float):
        """调用第三方支付接口"""
        if amount > 10000:
            raise Exception("Payment gateway timeout")
        return {"status": "success", "transaction_id": "TXN_123"}
    
    def payment_fallback(self, order_id: str, amount: float):
        """支付降级处理"""
        return {"status": "degraded", "message": "Payment service unavailable, please try again later"}
```

**注意事项**：
- 降级方法必须定义在同一个类中
- 降级方法的参数列表必须与原方法完全一致
- 半开状态下如果调用成功，自动恢复到关闭状态

---

### 3. @Idempotent - 幂等性

**含义**：确保相同请求多次调用产生的结果一致，防止重复提交。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| key | str | None | 幂等键参数名，如 `"order_id"`，支持占位符 |
| expire | int | 300 | 幂等结果缓存时间（秒） |
| prefix | str | "idempotent" | 键前缀，用于区分不同业务 |

**用法示例**：
```python
from spring.annotations.core import Idempotent, Service

@Service
class OrderService:
    
    # 按订单ID保证幂等
    @Idempotent(key="order_id", expire=300, prefix="order")
    def create_order(self, order_id: str, user_id: str, amount: float):
        """创建订单（重复调用返回相同结果）"""
        return {"order_id": order_id, "status": "created"}
    
    # 不指定key时，使用所有参数的哈希值作为幂等键
    @Idempotent(expire=60)
    def generate_report(self, start_date: str, end_date: str):
        """生成报表（相同参数重复调用返回缓存结果）"""
        return {"report": "...", "generated_at": "..."}
```

**注意事项**：
- 缓存有大小限制，超出自动清理最旧条目
- 方法抛出异常时，幂等键会被移除，允许重试
- 首次调用正在处理时，后续请求会重新执行（简单实现）

---

### 4. @AuditLog - 审计日志

**含义**：自动记录方法调用的审计日志，包括操作人、操作内容、执行时间、状态等。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| action | str | "" | 操作名称，如"创建用户" |
| target | str | "" | 操作对象，如"用户管理" |
| detail | str | "" | 操作详情，支持占位符，如"删除用户{user_id}" |
| level | str | "INFO" | 日志级别：DEBUG/INFO/WARN/ERROR |

**用法示例**：
```python
from spring.annotations.core import AuditLog, Service

@Service
class UserService:
    
    @AuditLog(action="创建用户", target="用户管理", detail="创建用户{username}", level="INFO")
    def create_user(self, username: str, email: str):
        """创建用户"""
        return {"user_id": 1, "username": username}
    
    @AuditLog(action="删除用户", target="用户管理", detail="删除用户ID={user_id}", level="WARN")
    def delete_user(self, user_id: int):
        """删除用户"""
        return {"status": "deleted"}
```

**注意事项**：
- 日志在方法执行完成后（finally块）记录
- detail 支持使用 `{参数名}` 占位符动态填充
- 异常时状态标记为 FAILED，正常执行为 SUCCESS

---

### 5. @FeatureToggle - 功能开关

**含义**：通过环境变量或配置动态控制功能是否启用，实现灰度发布。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | 必填 | 功能名称，环境变量为 `FEATURE_{NAME}` |
| default | bool | False | 默认状态（未配置环境变量时） |

**用法示例**：
```python
from spring.annotations.core import FeatureToggle, Service

@Service
class FeatureService:
    
    # 新功能默认关闭，通过环境变量 FEATURE_NEW_PAYMENT=true 启用
    @FeatureToggle(name="new_payment", default=False)
    def new_payment_flow(self, order_id: str):
        """新版支付流程（灰度功能）"""
        return {"status": "new_flow"}
    
    # 默认启用的功能
    @FeatureToggle(name="email_notification", default=True)
    def send_email(self, user_id: str, content: str):
        """发送邮件通知"""
        return {"status": "sent"}
```

**控制功能开关**：
```python
from spring.aop.comprehensive_aop import enable_feature, disable_feature

# 启用功能
enable_feature("new_payment")

# 禁用功能
disable_feature("new_payment")
```

**注意事项**：
- 通过环境变量 `FEATURE_{名称大写}` 控制
- 启用值：true/1/yes/enabled（不区分大小写）
- 功能未启用时抛出 `Exception: Feature 'xxx' is not enabled`

---

### 6. @Lock - 分布式锁

**含义**：基于内存锁实现的分布式锁，确保同一时间只有一个线程执行被注解的方法。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| key | str | None | 锁键，支持 `{参数名}` 动态拼接 |
| expire | int | 10 | 锁过期时间（秒），预留参数 |
| wait_timeout | int | 5 | 等待锁的超时时间（秒） |
| prefix | str | "lock" | 锁键前缀 |

**用法示例**：
```python
from spring.annotations.core import Lock, Service

@Service
class StockService:
    
    # 按商品ID加锁，防止超卖
    @Lock(key="product_{product_id}", wait_timeout=3, prefix="stock")
    def deduct_stock(self, product_id: str, quantity: int):
        """扣减库存"""
        return {"product_id": product_id, "remaining": 100}
    
    # 方法级别的锁，同一时间只能有一个线程执行
    @Lock(prefix="global")
    def generate_unique_code(self):
        """生成唯一编码"""
        return {"code": "UNIQUE_123"}
```

**注意事项**：
- 锁获取失败抛出 `Exception: Could not acquire lock for ...`
- key 支持动态参数，格式：`前缀_{参数名}`
- 方法执行完成后自动释放锁

---

### 7. @Metrics - 指标监控

**含义**：自动收集方法的调用次数、执行时间、错误率等性能指标。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | None | 指标名称，默认使用方法全限定名 |
| tags | List[str] | None | 标签（预留扩展） |

**收集的指标**：
- count: 调用总次数
- total_time: 总耗时
- errors: 错误次数
- min_time: 最小耗时
- max_time: 最大耗时

**用法示例**：
```python
from spring.annotations.core import Metrics, Service

@Service
class OrderService:
    
    @Metrics(name="order.create")
    def create_order(self, user_id: str, product_id: str):
        """创建订单"""
        return {"order_id": "ORD_123"}
    
    @Metrics(name="order.query")
    def get_order(self, order_id: str):
        """查询订单"""
        return {"order_id": order_id, "status": "pending"}
```

**获取指标数据**：
```python
from spring.aop.comprehensive_aop import get_metrics

metrics = get_metrics()
# 返回: {"order.create": {"count": 100, "total_time": 5.2, "errors": 2, ...}}
```

**注意事项**：
- 每 100 次调用自动打印一次统计日志
- 指标存储有大小限制，超出自动清理
- 线程安全，支持高并发统计

---

### 8. @Synchronized - 方法同步

**含义**：确保被注解的方法在同一时间只能被一个线程执行，类似于 Java 的 synchronized 关键字。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| lock_name | str | None | 锁名称，默认使用方法全限定名 |

**用法示例**：
```python
from spring.annotations.core import Synchronized, Service

@Service
class CounterService:
    
    def __init__(self):
        self.count = 0
    
    # 方法级同步
    @Synchronized
    def increment(self):
        """计数器自增（线程安全）"""
        self.count += 1
        return self.count
    
    # 指定锁名称，多个方法共享同一把锁
    @Synchronized(lock_name="counter_lock")
    def decrement(self):
        """计数器自减"""
        self.count -= 1
        return self.count
    
    @Synchronized(lock_name="counter_lock")
    def reset(self):
        """重置计数器"""
        self.count = 0
```

**注意事项**：
- 比 `@Lock` 更轻量，专门用于方法同步
- 相同 lock_name 的方法共享同一把锁
- 当前实现不可重入，注意避免死锁

---

### 9. @Validate - 参数校验

**含义**：对方法参数进行校验，包括长度、数值范围、正则表达式等。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| field | str | None | 要校验的参数名，不指定则校验所有参数 |
| min_length | int | None | 最小长度 |
| max_length | int | None | 最大长度 |
| min | float | None | 最小值（数值类型） |
| max | float | None | 最大值（数值类型） |
| regex | str | None | 正则表达式 |
| message | str | None | 自定义错误消息 |

**用法示例**：
```python
from spring.annotations.core import Validate, Service

@Service
class UserService:
    
    # 校验用户名长度和年龄范围
    @Validate(field="username", min_length=3, max_length=20)
    @Validate(field="age", min=1, max=120)
    @Validate(field="email", regex=r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    def register(self, username: str, age: int, email: str):
        """用户注册"""
        return {"status": "success"}
    
    # 校验手机号格式
    @Validate(field="phone", regex=r'^1[3-9]\d{9}$', message="手机号格式不正确")
    def send_sms(self, phone: str, code: str):
        """发送短信验证码"""
        return {"status": "sent"}
```

**注意事项**：
- 可以在一个方法上使用多个 `@Validate` 注解，分别校验不同参数
- 数值校验会自动尝试转换为 float，非数值参数跳过
- 校验失败抛出 `Exception: Validation failed: ...`

---

### 10. @Trace - 分布式追踪

**含义**：为方法调用生成追踪ID和跨度，便于分布式系统中的问题定位。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| trace_id_key | str | "X-Trace-ID" | Trace ID 的键名 |
| span_name | str | None | 跨度名称，默认使用方法名 |

**用法示例**：
```python
from spring.annotations.core import Trace, Service

@Service
class OrderService:
    
    @Trace(span_name="create_order")
    def create_order(self, user_id: str, product_id: str):
        """创建订单"""
        # 调用其他服务
        self.payment_service.process_payment(...)
        return {"order_id": "ORD_123"}
    
    @Trace(span_name="query_order")
    def get_order(self, order_id: str):
        """查询订单"""
        return {"order_id": order_id}
```

**输出示例**：
```
[Trace] Start span=create_order, trace_id=a1b2c3d4e5f6
[Trace] Start span=process_payment, trace_id=a1b2c3d4e5f6
[Trace] End span=process_payment, trace_id=a1b2c3d4e5f6, duration=0.0523s
[Trace] End span=create_order, trace_id=a1b2c3d4e5f6, duration=0.1234s
```

**注意事项**：
- 同一线程内的嵌套调用共享同一个 trace_id
- trace_id 基于时间戳和线程ID生成
- 异常时会记录错误日志

---

## 三、Spring Cloud 微服务注解（11个）

### 1. @EnableDiscoveryClient - 服务注册发现

**含义**：启用服务注册与发现客户端，将当前服务注册到注册中心。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| client_type | str | "nacos" | 注册中心类型：nacos/eureka/consul |

**用法示例**：
```python
from spring.annotations.core import SpringBootApplication
from spring.annotations.cloud import EnableDiscoveryClient

@SpringBootApplication
@EnableDiscoveryClient(client_type="nacos")
class Application:
    pass
```

**注意事项**：
- 注解提供发现元数据；实际初始化由 `discovery.enabled` 和 `ApplicationContext` 启动流程控制
- Nacos 需要安装 `nacos-sdk-python`，并配置 `NACOS_SERVER`、`NACOS_USERNAME`、`NACOS_PASSWORD`
- Nacos 2.2+ Docker 还需要服务端 `NACOS_AUTH_TOKEN`、`NACOS_AUTH_IDENTITY_KEY` 和 `NACOS_AUTH_IDENTITY_VALUE`
- 服务间调用通过服务名而非 IP 地址；Windows Docker 方案见部署指南

---

### 2. @NacosValue - 配置中心值注入

**含义**：从 Nacos 配置中心注入配置值，支持动态刷新。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| value | str | 必填 | 配置键，如 `"${user.name}"` |
| auto_refreshed | bool | False | 是否自动刷新配置 |

**用法示例**：
```python
from spring.annotations.core import Service
from spring.annotations.cloud import NacosValue

@Service
class ConfigService:
    
    # 基础类型配置，支持动态刷新
    @NacosValue(value="${app.version}", auto_refreshed=True)
    def get_version(self):
        """获取应用版本"""
        return self._app_version
    
    # 不支持动态刷新，启动时读取一次
    @NacosValue(value="${db.url}", auto_refreshed=False)
    def get_db_url(self):
        """获取数据库URL"""
        return self._db_url
```

**注意事项**：
- 与 `@Value` 区别：@NacosValue 支持 auto_refreshed 动态刷新
- 基础类型效果最好，复杂实体类推荐用 `@ConfigurationProperties`

---

### 3. @RefreshScope - 配置刷新作用域

**含义**：配置刷新作用域，添加此注解的类在配置变更时会重新创建实例。

**参数**：无

**用法示例**：
```python
from spring.annotations.core import Service
from spring.annotations.cloud import RefreshScope

@Service
@RefreshScope
class DynamicConfigService:
    """动态配置服务"""
    
    def __init__(self):
        self.feature_flag = True
        self.timeout = 30
    
    def get_config(self):
        return {"feature_flag": self.feature_flag, "timeout": self.timeout}
```

**触发刷新**：
```python
from spring.aop.cloud_aop import trigger_config_refresh

# 触发配置刷新
trigger_config_refresh()
```

**注意事项**：
- 不能标注在 `@Controller` 上，会导致请求参数解析异常
- 动态配置读取建议放在 Service 层
- 会创建代理类，存在循环依赖的 Bean 会启动失败

---

### 4. @EnableFeignClients - 启用Feign客户端

**含义**：启用 Feign 客户端扫描，自动注册 Feign 接口为 Bean。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| base_packages | List[str] | None | 扫描包路径，默认扫描启动类同包 |

**用法示例**：
```python
from spring.annotations.core import SpringBootApplication
from spring.annotations.cloud import EnableFeignClients

@SpringBootApplication
@EnableFeignClients(base_packages=["com.example.feign"])
class Application:
    pass
```

**注意事项**：
- Feign 接口放在其他包时必须指定扫描路径
- 默认只扫描启动类同包下的 Feign 接口

---

### 5. @FeignClient - Feign客户端

**含义**：声明式 HTTP 客户端，用于调用远程服务。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| value | str | 必填 | 目标服务名 |
| path | str | "" | 接口路径前缀 |
| fallback | Type | None | 降级实现类 |
| fallback_factory | Type | None | 降级工厂类 |
| url | str | "" | 直接指定URL（调试用） |

**用法示例**：
```python
from spring.annotations.cloud import FeignClient
from spring.annotations.core import GetMapping, PostMapping

@FeignClient(value="user-service", path="/api")
class UserFeign:
    """用户服务Feign客户端"""
    
    @GetMapping("/users/{id}")
    def get_user(self, id: int):
        """获取用户信息"""
        pass  # 由Feign自动实现
    
    @PostMapping("/users")
    def create_user(self, name: str, email: str):
        """创建用户"""
        pass  # 由Feign自动实现
```

**注意事项**：
- value 值必须和目标服务的 spring.application.name 完全一致
- 目标服务有 context-path 时，通过 path 属性指定

---

### 6. @SentinelResource - Sentinel资源保护

**含义**：Sentinel 资源保护注解，支持限流、熔断、降级、热点参数限流。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| value | str | 必填 | 资源名称，全局唯一 |
| block_handler | str | "" | 限流/阻断处理方法名 |
| fallback | str | "" | 业务异常降级方法名 |
| hotkey | str | "" | 热点参数名 |

**blockHandler vs fallback 区别**：
- **blockHandler**: 处理 Sentinel 主动阻断（限流、系统保护、黑名单等）
- **fallback**: 处理业务异常、远程调用失败

**用法示例**：
```python
from spring.annotations.core import Service
from spring.annotations.cloud import SentinelResource

@Service
class OrderService:
    
    # 带降级的资源保护
    @SentinelResource(value="create_order", fallback="create_order_fallback")
    def create_order(self, user_id: str, product_id: str):
        """创建订单"""
        return {"order_id": "ORD_123"}
    
    def create_order_fallback(self, user_id: str, product_id: str):
        """创建订单降级处理"""
        return {"status": "degraded", "message": "系统繁忙，请稍后重试"}
    
    # 热点参数限流（按product_id限流）
    @SentinelResource(value="get_product", hotkey="product_id")
    def get_product(self, product_id: str):
        """获取商品信息"""
        return {"product_id": product_id, "name": "测试商品"}
```

**注意事项**：
- 降级/限流处理方法的返回值、参数列表必须和原方法完全一致
- blockHandler 和 fallback 分工不同，不要混用
- 热点参数限流只对基础类型参数生效
- 线程安全，存储有大小限制

---

### 7. @EnableGateway - 启用网关

**含义**：启用 Spring Cloud Gateway 网关功能。

**参数**：无

**用法示例**：
```python
from spring.annotations.core import SpringBootApplication
from spring.annotations.cloud import EnableGateway

@SpringBootApplication
@EnableGateway
class GatewayApplication:
    """网关服务启动类"""
    pass
```

**注意事项**：
- 仅网关模块启动类添加
- 业务服务禁止引入 Gateway 依赖和该注解
- 会引入 WebFlux 依赖，与 SpringMVC 冲突

---

### 8. @LoadBalanced - 负载均衡

**含义**：为 RestTemplate 启用客户端负载均衡能力。

**参数**：无

**用法示例**：
```python
from spring.annotations.core import Configuration, Bean
from spring.annotations.cloud import LoadBalanced

@Configuration
class RestTemplateConfig:
    
    @Bean
    @LoadBalanced
    def rest_template(self):
        """创建带负载均衡的RestTemplate"""
        return {"type": "RestTemplate", "max_connections": 100}
```

**注意事项**：
- 只能标注在 `@Bean` 修饰的创建 RestTemplate 的方法上
- 不能标注在注入字段、类上

---

### 9. @GlobalTransactional - 分布式事务

**含义**：Seata 全局事务注解，用于分布式事务的发起方。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| timeout | int | 60000 | 事务超时时间（毫秒） |
| name | str | "" | 事务名称 |
| rollback_for | List[Type] | [] | 需要回滚的异常类 |
| no_rollback_for | List[Type] | [] | 不需要回滚的异常类 |

**用法示例**：
```python
from spring.annotations.core import Service, Autowired
from spring.annotations.cloud import GlobalTransactional

@Service
class OrderService:
    
    @Autowired
    def __init__(self, inventory_feign, payment_feign):
        self.inventory_feign = inventory_feign
        self.payment_feign = payment_feign
    
    @GlobalTransactional(timeout=30000, name="create_order_tx")
    def create_order(self, user_id: str, product_id: str, amount: float):
        """创建订单（分布式事务）"""
        # 1. 创建订单
        order = self.save_order(user_id, product_id, amount)
        
        # 2. 扣减库存（远程调用）
        self.inventory_feign.deduct(product_id, 1)
        
        # 3. 扣减余额（远程调用）
        self.payment_feign.deduct(user_id, amount)
        
        return order
```

**注意事项**：
- 只在事务发起入口方法添加，参与方不需要
- 不支持嵌套事务
- 所有异常都会触发回滚
- 禁止在异步线程中使用，事务上下文无法传递
- 基于线程本地存储实现事务上下文

---

### 10. @Valid - 参数校验

**含义**：JSR-303 参数校验注解，用于实体类参数校验。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| groups | List[Type] | [] | 校验分组 |

**用法示例**：
```python
from spring.annotations.core import Service
from spring.annotations.cloud import Valid

@Service
class UserService:
    
    @Valid
    def create_user(self, name: str, age: int, email: str):
        """创建用户"""
        return {"status": "success"}
```

**校验规则**：
- 空字符串校验：参数值不能为 ""
- 嵌套对象校验：递归检查对象属性不能为 None

**注意事项**：
- 实体类参数校验配合 `@RequestBody` 使用
- 嵌套实体校验时，内部实体必须添加 `@Valid`

---

### 11. @Validated - 分组参数校验

**含义**：Spring 扩展的参数校验注解，支持分组校验。

**参数**：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| groups | List[Type] | [] | 校验分组 |

**用法示例**：
```python
from spring.annotations.core import Service
from spring.annotations.cloud import Validated

@Service
class UserService:
    
    @Validated
    def update_user(self, id: int, name: str, value: str):
        """更新用户"""
        return {"status": "success"}
```

**校验规则**：
- 非负数校验：数值类型不能小于 0
- 非空字符串校验：字符串 trim 后不能为空

**与 @Valid 的区别**：
| 特性 | @Valid | @Validated |
|------|--------|------------|
| 分组校验 | 不支持 | 支持 |
| 嵌套校验 | 支持 | 不支持 |
| 使用位置 | 方法参数、字段 | 类、方法 |

---

## 四、注解组合使用指南

### 常用组合模式

#### 1. 接口防护三件套
```python
@SentinelResource(value="xxx", fallback="xxx_fallback")  # 降级熔断
@Metrics(name="xxx")  # 性能监控
@RateLimit(max_requests=100, time_window=60)  # 限流
def xxx_method(self):
    pass
```

#### 2. 写操作安全组合
```python
@GlobalTransactional  # 分布式事务
@Synchronized(lock_name="xxx_lock")  # 同步锁
@AuditLog(action="xxx", target="xxx")  # 审计日志
def xxx_write_method(self):
    pass
```

#### 3. 查询接口组合
```python
@Idempotent(key="xxx_id", expire=300)  # 幂等缓存
@Metrics(name="xxx.query")  # 监控
@Trace(span_name="xxx_query")  # 追踪
def xxx_query_method(self):
    pass
```

#### 4. 完整的订单创建接口
```python
@SentinelResource(value="order.create", fallback="create_fallback")
@Metrics(name="order.create")
@AuditLog(action="创建订单", target="订单管理", detail="订单{order_id}")
@Idempotent(key="order_id", expire=600)
@GlobalTransactional
def create_order(self, order_id: str, user_id: str, amount: float):
    """创建订单"""
    # 业务逻辑
    pass
```

### 注解执行顺序

AOP 注解的执行顺序（从外到内）：
```
1. @SentinelResource / @CircuitBreaker  （最外层，熔断降级）
2. @RateLimit                           （限流）
3. @Lock / @Synchronized                （锁）
4. @Metrics                             （监控）
5. @Trace                               （追踪）
6. @AuditLog                            （审计）
7. @Idempotent                          （幂等）
8. @Validate / @Valid / @Validated      （参数校验）
9. 业务方法
```

### 性能影响

| 注解 | 性能损耗 | 内存占用 | 线程安全 |
|------|----------|----------|----------|
| @RateLimit | 低 (<1ms) | 低 | ✓ 安全 |
| @CircuitBreaker | 低 (<1ms) | 低 | ✓ 安全 |
| @Idempotent | 低 (<2ms) | 中 | ✓ 安全 |
| @AuditLog | 极低 (<0.1ms) | 无 | ✓ 安全 |
| @FeatureToggle | 极低 (<0.1ms) | 无 | ✓ 安全 |
| @Lock | 中 (取决于锁竞争) | 低 | ✓ 安全 |
| @Metrics | 低 (<0.5ms) | 低 | ✓ 安全 |
| @Synchronized | 中 (取决于锁竞争) | 低 | ✓ 安全 |
| @Validate | 低 (<1ms) | 无 | ✓ 安全 |
| @Trace | 低 (<0.5ms) | 低 | ✓ 安全 |
| @SentinelResource | 低 (<1ms) | 低 | ✓ 安全 |
| @GlobalTransactional | 低 (<2ms) | 低 | ✓ 安全 |

---

## 五、常见问题

### Q: 注解不生效怎么办？
A: 检查以下几点：
1. 类是否被 Spring 管理（@Service/@Component 等）
2. 方法是否是 public 的
3. 是否是类内部调用（this.xxx() 不会触发 AOP）
4. 注解参数是否正确

### Q: 内存会不会泄漏？
A: 不会。所有存储都有大小限制（默认 10000 条），超出自动清理最旧条目。

### Q: 线程安全吗？
A: 所有 AOP 注解都是线程安全的，使用全局锁保护共享存储。

### Q: 异常会被吃掉吗？
A: 不会。除了明确配置了 fallback 的情况，所有异常都会正常抛出。

### Q: 动态键（key）怎么用？
A: 支持两种方式：
1. 直接写参数名：`key="user_id"` → 取参数 user_id 的值
2. 占位符格式：`key="stock_{product_id}"` → 组合前缀和参数值
