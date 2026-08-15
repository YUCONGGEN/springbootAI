"""
安全模块启用型注解

提供 OAuth2 资源服务器和 CSRF 防护的注解驱动启用方式。
标记在 SpringBootApplication 主类上，替代 application.yml 配置。

使用示例::

    @SpringBootApplication
    @EnableOAuth2  # 启用 OAuth2 资源服务器
    @EnableCsrf    # 启用 CSRF 防护
    class Application:
        pass

与配置文件的等价关系：
- @EnableOAuth2 等价于 spring.security.oauth2.enabled: true
- @EnableCsrf   等价于 server.csrf.enabled: true

注解优先级高于配置文件：如果主类上标注了注解，即使配置文件未设置 enabled 也会启用。
"""
from typing import Optional

from .core import SpringAnnotation


class EnableOAuth2(SpringAnnotation):
    """启用 OAuth2 资源服务器

    标记在主类上，应用启动时自动初始化 OAuth2ResourceServer。

    Attributes:
        issuer: 预期的 token 签发方（可选，用于验证 iss claim）
        audiences: 预期的 token 受众列表（可选，用于验证 aud claim）
        jwks_uri: JWKS 公钥端点 URL（RS256 算法时使用）
        algorithms: 允许的签名算法列表（默认 ['HS256']）

    使用示例::

        @SpringBootApplication
        @EnableOAuth2(
            issuer="https://auth.example.com",
            audiences=["my-api"],
            algorithms=["RS256"],
            jwks_uri="https://auth.example.com/.well-known/jwks.json",
        )
        class Application:
            pass

    对齐 Java Spring Security：
    - Java 通过 @EnableResourceServer + ResourceServerConfigurer 启用
    - Python 版本通过 @EnableOAuth2 注解 + application.yml 配置启用
    """

    _annotation_type = "security_oauth2"

    def __init__(
        self,
        issuer: Optional[str] = None,
        audiences: Optional[list] = None,
        jwks_uri: Optional[str] = None,
        algorithms: Optional[list] = None,
        secret_key: Optional[str] = None,
    ):
        super().__init__(
            issuer=issuer,
            audiences=audiences or [],
            jwks_uri=jwks_uri,
            algorithms=algorithms or ['HS256'],
            secret_key=secret_key,
        )


class EnableCsrf(SpringAnnotation):
    """启用 CSRF 防护

    标记在主类上，应用启动时自动注册 CSRFMiddleware。

    Attributes:
        token_length: CSRF Token 长度（默认 32 字节）
        token_ttl: Token 有效期（秒，默认 3600）
        cookie_name: 存储 Token 的 Cookie 名（默认 'XSRF-TOKEN'）
        header_name: 客户端回传 Token 的 Header 名（默认 'X-XSRF-TOKEN'）
        secure_cookie: 是否设置 Secure 标志（生产环境 HTTPS 应为 True）

    使用示例::

        @SpringBootApplication
        @EnableCsrf(token_ttl=7200, secure_cookie=True)
        class Application:
            pass

    对齐 Java Spring Security：
    - Java 通过 http.csrf().enable() 启用
    - Python 版本通过 @EnableCsrf 注解启用，实现 Double Submit Cookie 模式
    """

    _annotation_type = "security_csrf"

    def __init__(
        self,
        token_length: int = 32,
        token_ttl: int = 3600,
        cookie_name: str = 'XSRF-TOKEN',
        header_name: str = 'X-XSRF-TOKEN',
        secure_cookie: bool = False,
        same_site: str = 'Lax',
    ):
        super().__init__(
            token_length=token_length,
            token_ttl=token_ttl,
            cookie_name=cookie_name,
            header_name=header_name,
            secure_cookie=secure_cookie,
            same_site=same_site,
        )
