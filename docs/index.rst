SpringBootAI API 参考文档
=========================

SpringBootAI 是一个 Spring 风格的 Python 框架，对齐 Java Spring Boot 编程模型，
提供 IoC/AOP/ORM/Web/Cloud/AI 等完整能力。本文档由 Sphinx + autodoc 自动从源码
docstring 生成，覆盖 ``spring`` 包下的所有公开 API。

完整使用指南请参阅项目根目录的 ``doc/`` 下的模块文档（如 ``WEB_MODULE.md``、
``ORM_MODULE.md`` 等），本文档聚焦于 API 签名与参数说明。

.. note::
   构建命令::

       pip install sphinx
       sphinx-build -b html docs docs/_build

   构建后用浏览器打开 ``docs/_build/index.html``。

模块 API
---------

本文档按模块组织，每个章节使用 ``automodule`` 指令自动从源码 docstring 生成。
点击下方索引可快速跳转到对应模块。

- :ref:`modindex` 模块索引
- :ref:`genindex` 全文索引
- :ref:`search` 搜索

核心 IoC / AOP / 注解
---------------------

.. automodule:: spring.annotations
   :members:

.. automodule:: spring.context.application_context
   :members:

.. automodule:: spring.context.bean_factory
   :members:

.. automodule:: spring.aop.aspect
   :members:

Web MVC / Actuator / CSRF
-------------------------

.. automodule:: spring.web.actuator
   :members:

.. automodule:: spring.web.csrf
   :members:

.. automodule:: spring.web.interceptor
   :members:

ORM / MyBatis / 数据库迁移
-------------------------

.. automodule:: spring.orm.database
   :members:

.. automodule:: spring.orm.ddl_auto
   :members:

.. automodule:: spring.orm.migration
   :members:

.. automodule:: spring.orm.pymybatis.core.sql_session
   :members:

安全 / JWT / OAuth2
-------------------

.. automodule:: spring.security.jwt_utils
   :members:

.. automodule:: spring.security.oauth2
   :members:

.. automodule:: spring.security.security_aop
   :members:

消息队列 / Kafka / RabbitMQ
---------------------------

.. automodule:: spring.messaging.kafka
   :members:

.. automodule:: spring.messaging.rabbitmq
   :members:

Cloud / Seata / Gateway
-----------------------

.. automodule:: spring.cloud.seata
   :members:

.. automodule:: spring.cloud.seata_at_proxy
   :members:

.. automodule:: spring.cloud.gateway
   :members:

.. automodule:: spring.cloud.feign
   :members:

.. automodule:: spring.cloud.discovery
   :members:

AI / LangChain / LangGraph / MCP
--------------------------------

.. automodule:: spring.ai.core
   :members:

.. automodule:: spring.ai.annotations
   :members:

.. automodule:: spring.langchain.core
   :members:

.. automodule:: spring.langgraph.runtime
   :members:

.. automodule:: spring.mcp.client
   :members:

.. automodule:: spring.mcp.server
   :members:

DevTools / CLI / 配置
---------------------

.. automodule:: spring.devtools
   :members:

.. automodule:: spring.cli.scaffold
   :members:

.. automodule:: spring.config.binding
   :members:

.. automodule:: spring.config.config_loader
   :members:

索引
----

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
