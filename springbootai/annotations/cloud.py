"""
Spring Cloud 微服务注解
包含注册发现、配置中心、Feign、熔断限流、网关、负载均衡、分布式事务等注解
"""
from typing import Optional, Type, List
from .core import SpringAnnotation, Valid, Validated  # noqa: F401  # 重导出给 cloud 子模块使用


# ==================== 注册发现注解 ====================

class EnableDiscoveryClient(SpringAnnotation):
    """
    启用服务注册发现
    所有微服务（服务提供者、消费者、网关）都要加
    通用兼容：SpringCloud新版本统一使用该注解，不要混用@EnableEurekaClient
    
    使用注意：
    - 必须在application.yml配置springbootai.application.name，否则注册中心显示未知服务
    - Feign调用依赖服务名配置
    """
    _annotation_type = "discovery"

    def __init__(self, client_type: str = "nacos"):
        super().__init__(client_type=client_type)


class NacosValue(SpringAnnotation):
    """
    Nacos配置动态刷新注解
    和@Value区别：@Value配置变更不会自动刷新，@NacosValue(autoRefreshed=True)才支持动态刷新
    
    使用注意：
    - 基础类型生效，复杂实体类不推荐
    - 批量配置绑定优先使用@ConfigurationProperties
    """
    _annotation_type = "value"

    def __init__(self, value: str, auto_refreshed: bool = False):
        super().__init__(value=value, auto_refreshed=auto_refreshed)


# ==================== 配置中心注解 ====================

class RefreshScope(SpringAnnotation):
    """
    配置刷新作用域注解
    仅加了该注解的类，配置变更才会自动刷新
    
    使用注意：
    - 不能标注在@Controller上，会导致接口上下文丢失、请求参数解析异常
    - 动态配置读取放在Service层
    - 会创建代理类，存在循环依赖的Bean会启动直接报错
    """
    _annotation_type = "refresh_scope"

    def __init__(self):
        super().__init__()


# ==================== Feign远程调用注解 ====================

class EnableFeignClients(SpringAnnotation):
    """
    启用Feign客户端扫描
    默认只扫描启动类同包下的Feign接口
    
    使用注意：
    - Feign接口放在其他包时，必须指定扫描路径
    - 不能和Dubbo注解混用，会出现RPC上下文冲突
    """
    _annotation_type = "feign"

    def __init__(self, base_packages: Optional[List[str]] = None):
        super().__init__(base_packages=base_packages)


class FeignClient(SpringAnnotation):
    """
    Feign客户端注解
    value值必须和目标服务springbootai.application.name完全一致，大小写敏感
    
    使用注意：
    - fallback降级类必须实现当前Feign接口，且交给Spring管理
    - 如果目标服务配置server.servlet.context-path，必须通过path属性指定
    - 禁止在Feign接口方法上使用@Valid做参数校验
    """
    _annotation_type = "feign"

    def __init__(
        self,
        value: str,
        path: str = "",
        fallback: Optional[Type] = None,
        fallback_factory: Optional[Type] = None,
        url: str = "",
    ):
        super().__init__(
            value=value,
            path=path,
            fallback=fallback,
            fallback_factory=fallback_factory,
            url=url,
        )


# ==================== 熔断限流注解 ====================

class SentinelResource(SpringAnnotation):
    """
    Sentinel资源保护注解（Alibaba Sentinel，生产推荐）
    value资源名唯一，建议和接口路径保持一致
    
    使用注意：
    - blockHandler：只处理限流、黑名单、系统保护这类Sentinel阻断异常
    - fallback：处理业务异常、远程调用异常，二者分工不同
    - 限流/降级处理函数：返回值、参数列表必须和原接口完全一致
    - 热点参数限流：需要指定hotkey="参数名"，基础类型参数才生效
    """
    _annotation_type = "aop"

    def __init__(
        self,
        value: str,
        block_handler: str = "",
        fallback: str = "",
        block_handler_class: Optional[Type] = None,
        fallback_class: Optional[Type] = None,
        hotkey: str = "",
        exceptions_to_ignore: Optional[List[Type[Exception]]] = None,
    ):
        super().__init__(
            value=value,
            block_handler=block_handler,
            fallback=fallback,
            block_handler_class=block_handler_class,
            fallback_class=fallback_class,
            hotkey=hotkey,
            exceptions_to_ignore=exceptions_to_ignore or [],
        )


# ==================== 网关注解 ====================

class EnableGateway(SpringAnnotation):
    """
    启用Gateway网关
    仅网关模块启动类添加，业务服务禁止引入Gateway依赖和该注解
    
    使用注意：
    - 会引入WebFlux依赖，和SpringMVC冲突
    - 不能使用SpringMVC的拦截器，自定义逻辑必须使用Gateway全局过滤器GlobalFilter
    """
    _annotation_type = "gateway"

    def __init__(self):
        super().__init__()


# ==================== 负载均衡注解 ====================

class LoadBalanced(SpringAnnotation):
    """
    负载均衡注解
    仅作用于@Bean修饰的RestTemplate
    
    使用注意：
    - 不能标注在注入字段、类上，仅能放在创建RestTemplate的Bean方法上
    - WebClient负载均衡需单独配置，该注解不生效
    """
    _annotation_type = "bean"

    def __init__(self, strategy: str = "round_robin"):
        super().__init__()
        self.strategy = strategy


# ==================== 分布式事务注解 ====================

class GlobalTransactional(SpringAnnotation):
    """
    Seata 分布式事务注解。

    仅事务发起入口方法添加。distributed 模式使用官方 Java 客户端桥接和
    Seata TCC；参与服务通过 ``register_branch`` 注册业务分支。
    
    使用注意：
    - 必须配置 Seata Server、bridge、共享令牌和事务组
    - TCC 分支必须实现持久化资源预留和幂等的 prepare/commit/rollback
    - 回调要处理重复提交、空回滚和悬挂，不能只修改进程内变量
    - 不支持嵌套事务
    - 业务方法抛出异常时会触发全局回滚
    - 不要把 ContextVar 事务上下文直接复制到独立后台任务中继续使用
    """
    _annotation_type = "aop"

    def __init__(
        self,
        timeout: int = 60000,
        name: str = "",
        rollback_for: Optional[List[Type[Exception]]] = None,
        no_rollback_for: Optional[List[Type[Exception]]] = None,
    ):
        super().__init__(
            timeout=timeout,
            name=name,
            rollback_for=rollback_for or [],
            no_rollback_for=no_rollback_for or [],
        )

