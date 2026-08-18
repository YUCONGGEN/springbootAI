"""
自定义拦截器 — 测试 HandlerInterceptor (pre_handle / post_handle / after_completion)
"""
import time
from springbootai.web.interceptor import HandlerInterceptor
from springbootai.annotations import Component, Slf4j


@Component
@Slf4j
class LoggingInterceptor(HandlerInterceptor):
    """记录请求日志的拦截器"""

    def pre_handle(self, request, handler) -> bool:
        request.state._start_time = time.time()
        path = getattr(request, 'url', getattr(request, 'path', 'unknown'))
        method = getattr(request, 'method', 'GET')
        self.logger.info(f"[Interceptor-PRE] {method} {path}")
        return True  # 返回 True 继续执行

    def post_handle(self, request, response, handler) -> None:
        path = getattr(request, 'url', getattr(request, 'path', 'unknown'))
        status_code = getattr(response, 'status_code', 200)
        self.logger.info(f"[Interceptor-POST] {path} -> {status_code}")

    def after_completion(self, request, response, handler, ex=None) -> None:
        elapsed = 0
        if hasattr(request.state, '_start_time'):
            elapsed = (time.time() - request.state._start_time) * 1000
        path = getattr(request, 'url', getattr(request, 'path', 'unknown'))
        if ex:
            self.logger.error(f"[Interceptor-AFTER] {path} FAILED in {elapsed:.1f}ms: {ex}")
        else:
            self.logger.info(f"[Interceptor-AFTER] {path} completed in {elapsed:.1f}ms")


@Component
class SecurityHeaderInterceptor(HandlerInterceptor):
    """检查安全请求头的拦截器"""

    def pre_handle(self, request, handler) -> bool:
        # request.url 是 Starlette URL 对象，需取其 .path 字符串再做包含判断
        url = getattr(request, 'url', None)
        path = getattr(url, 'path', '') or getattr(request, 'path', '')
        # 只检查 /api/secure/ 路径
        if '/api/secure/' in path:
            headers = getattr(request, 'headers', {})
            api_key = headers.get('x-api-key', '')
            if not api_key:
                from fastapi import HTTPException
                raise HTTPException(status_code=401, detail="Missing X-API-Key header")
        return True
