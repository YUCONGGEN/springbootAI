"""
PyMyBatis拦截器模块

支持自定义插件拦截SQL执行过程，类似于MyBatis的Interceptor机制
"""

from typing import Any, Optional
from abc import ABC, abstractmethod


class InterceptorChain:
    """
    拦截器链

    管理多个拦截器，按照顺序执行
    """

    def __init__(self):
        """初始化拦截器链"""
        self.interceptors: list = []

    def add_interceptor(self, interceptor: 'Interceptor') -> None:
        """
        添加拦截器

        Args:
            interceptor: 拦截器实例
        """
        self.interceptors.append(interceptor)

    def remove_interceptor(self, interceptor: 'Interceptor') -> None:
        """
        移除拦截器

        Args:
            interceptor: 拦截器实例
        """
        if interceptor in self.interceptors:
            self.interceptors.remove(interceptor)

    def clear(self) -> None:
        """清空所有拦截器"""
        self.interceptors.clear()

    def plugin_all(self, target: Any) -> Any:
        """
        为目标对象添加所有拦截器

        Args:
            target: 目标对象

        Returns:
            包装后的目标对象
        """
        for interceptor in self.interceptors:
            target = interceptor.plugin(target)
        return target

    def invoke(self, target: Any, method: str, args: tuple, kwargs: dict,
               proceed) -> Any:
        """Run interceptors as one ordered invocation chain.

        This path is used by ``SqlSession`` directly, avoiding a proxy around
        the session that would recursively invoke the same public method.
        """
        def invoke_at(index: int) -> Any:
            if index >= len(self.interceptors):
                return proceed()
            invocation = Invocation(
                target, method, args, kwargs,
                proceed=lambda: invoke_at(index + 1),
            )
            return self.interceptors[index].intercept(invocation)

        return invoke_at(0)


class Interceptor(ABC):
    """
    拦截器抽象基类

    定义拦截器的核心接口：
    - intercept: 执行拦截逻辑
    - plugin: 包装目标对象
    - set_properties: 设置属性
    """

    @abstractmethod
    def intercept(self, invocation: 'Invocation') -> Any:
        """
        执行拦截逻辑

        Args:
            invocation: 调用对象

        Returns:
            拦截结果
        """
        pass

    def plugin(self, target: Any) -> Any:
        """
        包装目标对象

        Args:
            target: 目标对象

        Returns:
            包装后的目标对象
        """
        return Plugin.wrap(target, self)

    def set_properties(self, properties: dict) -> None:
        """
        设置属性

        Args:
            properties: 属性字典
        """
        pass


class Invocation:
    """
    调用对象

    封装被拦截的方法调用
    """

    def __init__(self, target: Any, method: str, args: tuple,
                 kwargs: Optional[dict] = None, proceed=None):
        """
        初始化调用对象

        Args:
            target: 目标对象
            method: 方法名
            args: 方法参数
        """
        self.target = target
        self.method = method
        self.args = args
        self.kwargs = kwargs or {}
        self._proceed = proceed

    def proceed(self) -> Any:
        """
        执行原方法

        Returns:
            方法执行结果
        """
        if self._proceed is not None:
            return self._proceed()
        return getattr(self.target, self.method)(*self.args, **self.kwargs)

    def get_target(self) -> Any:
        """获取目标对象"""
        return self.target

    def get_method(self) -> str:
        """获取方法名"""
        return self.method

    def get_args(self) -> tuple:
        """获取方法参数"""
        return self.args

    def get_kwargs(self) -> dict:
        """Return keyword arguments passed to the intercepted method."""
        return dict(self.kwargs)


class Plugin:
    """
    插件包装器

    使用动态代理包装目标对象，实现拦截功能
    """

    @staticmethod
    def wrap(target: Any, interceptor: Interceptor) -> Any:
        """
        包装目标对象

        Args:
            target: 目标对象
            interceptor: 拦截器

        Returns:
            包装后的对象
        """
        return PluginProxy(target, interceptor)


class PluginProxy:
    """
    插件代理类

    实现动态代理，拦截目标对象的方法调用
    """

    def __init__(self, target: Any, interceptor: Interceptor):
        """
        初始化代理对象

        Args:
            target: 目标对象
            interceptor: 拦截器
        """
        self.target = target
        self.interceptor = interceptor

    def __getattr__(self, name: str):
        """
        获取属性

        Args:
            name: 属性名

        Returns:
            属性值或方法包装器
        """
        attr = getattr(self.target, name)

        if callable(attr):
            def wrapper(*args, **kwargs):
                invocation = Invocation(self.target, name, args, kwargs)
                return self.interceptor.intercept(invocation)
            return wrapper

        return attr


class ExecutorInterceptor(Interceptor):
    """
    Executor拦截器

    拦截SQL执行过程，可用于日志记录、性能监控等
    """

    def intercept(self, invocation: Invocation) -> Any:
        """
        执行拦截逻辑

        Args:
            invocation: 调用对象

        Returns:
            拦截结果
        """
        method = invocation.get_method()
        args = invocation.get_args()

        # 记录执行前信息
        print(f"[ExecutorInterceptor] Executing method: {method}")
        print(f"[ExecutorInterceptor] Args: {args}")

        # 执行原方法
        result = invocation.proceed()

        # 记录执行后信息
        print(f"[ExecutorInterceptor] Method {method} completed")

        return result


class LogInterceptor(Interceptor):
    """
    日志拦截器

    记录SQL执行日志，包括SQL语句、参数和执行时间
    """

    def __init__(self, logger=None):
        """
        初始化日志拦截器

        Args:
            logger: 日志记录器，不指定则使用print
        """
        self.logger = logger

    def intercept(self, invocation: Invocation) -> Any:
        """
        执行拦截逻辑

        Args:
            invocation: 调用对象

        Returns:
            拦截结果
        """
        import time

        method = invocation.get_method()
        args = invocation.get_args()

        # 提取SQL和参数
        sql = None
        params = None
        if args:
            for arg in args:
                if isinstance(arg, str) and ('SELECT' in arg.upper() or 'INSERT' in arg.upper()
                                             or 'UPDATE' in arg.upper() or 'DELETE' in arg.upper()):
                    sql = arg
                elif isinstance(arg, dict):
                    params = arg

        # 记录开始时间
        start_time = time.time()

        # 执行原方法
        result = invocation.proceed()

        # 记录执行时间
        end_time = time.time()
        elapsed_time = (end_time - start_time) * 1000

        # 记录日志
        log_message = f"[SQL] {method}: {sql}"
        if params:
            log_message += f" | Params: {params}"
        log_message += f" | Time: {elapsed_time:.2f}ms"

        if self.logger:
            self.logger.info(log_message)
        else:
            print(log_message)

        return result


class PerformanceInterceptor(Interceptor):
    """
    性能监控拦截器

    监控SQL执行性能，记录慢查询
    """

    def __init__(self, slow_query_threshold: float = 1.0):
        """
        初始化性能监控拦截器

        Args:
            slow_query_threshold: 慢查询阈值（秒），默认为1秒
        """
        self.slow_query_threshold = slow_query_threshold

    def intercept(self, invocation: Invocation) -> Any:
        """
        执行拦截逻辑

        Args:
            invocation: 调用对象

        Returns:
            拦截结果
        """
        import time

        # 记录开始时间
        start_time = time.time()

        # 执行原方法
        result = invocation.proceed()

        # 记录执行时间
        end_time = time.time()
        elapsed_time = end_time - start_time

        # 检查是否慢查询
        if elapsed_time > self.slow_query_threshold:
            method = invocation.get_method()
            args = invocation.get_args()

            # 提取SQL
            sql = None
            if args:
                for arg in args:
                    if isinstance(arg, str) and ('SELECT' in arg.upper() or 'INSERT' in arg.upper()
                                                 or 'UPDATE' in arg.upper() or 'DELETE' in arg.upper()):
                        sql = arg

            print(f"[SLOW QUERY] {method}: {sql} | Time: {elapsed_time:.2f}s")

        return result


class SecurityInterceptor(Interceptor):
    """
    安全拦截器

    检查SQL结构策略，不扫描预编译参数值。

    ``#{}`` 参数由数据库驱动绑定，即使消息正文包含 SQL 关键字也不会改变
    SQL 结构。将这些值交给基于正则的 SQL 检测器会误报代码、日志和 AI
    消息。``${}`` 原始片段由 ``DynamicSQLProcessor`` 单独执行白名单校验。
    """

    def intercept(self, invocation: Invocation) -> Any:
        """
        执行拦截逻辑

        Args:
            invocation: 调用对象

        Returns:
            拦截结果
        """
        args = invocation.get_args()

        # Only the first argument represents a SQL template (or statement id).
        # Remaining arguments are bound data and must never be interpreted as
        # SQL text.  Keep the structural DDL policy in the interceptor; the
        # SqlSession performs the same check after resolving mapped statements.
        sql = args[0] if args and isinstance(args[0], str) else None
        target = invocation.get_target()
        detector = getattr(target, 'sql_injection_detector', None)
        if detector is None:
            from ..security.sql_injection_detector import DEFAULT_DETECTOR
            detector = DEFAULT_DETECTOR
        if sql is not None and detector.is_ddl_blocked(sql):
            raise InterceptorSecurityError(f"DDL语句被阻止: {sql}")

        # 执行原方法
        return invocation.proceed()


class InterceptorSecurityError(Exception):
    """安全异常"""
    pass
