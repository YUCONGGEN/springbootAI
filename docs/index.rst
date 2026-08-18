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

.. automodule:: springbootai.annotations
   :members:

.. automodule:: springbootai.context.application_context
   :members:

.. automodule:: springbootai.context.bean_factory
   :members:

.. automodule:: springbootai.aop.aspect
   :members:

Web MVC / Actuator / CSRF
-------------------------

.. automodule:: springbootai.web.actuator
   :members:

.. automodule:: springbootai.web.csrf
   :members:

.. automodule:: springbootai.web.interceptor
   :members:

ORM / MyBatis / 数据库迁移
-------------------------

.. automodule:: springbootai.orm.database
   :members:

.. automodule:: springbootai.orm.ddl_auto
   :members:

.. automodule:: springbootai.orm.migration
   :members:

.. automodule:: springbootai.orm.pymybatis.core.sql_session
   :members:

安全 / JWT / OAuth2
-------------------

.. automodule:: springbootai.security.jwt_utils
   :members:

.. automodule:: springbootai.security.oauth2
   :members:

.. automodule:: springbootai.security.security_aop
   :members:

消息队列 / Kafka / RabbitMQ
---------------------------

.. automodule:: springbootai.messaging.kafka
   :members:

.. automodule:: springbootai.messaging.rabbitmq
   :members:

Cloud / Seata / Gateway
-----------------------

.. automodule:: springbootai.cloud.seata
   :members:

.. automodule:: springbootai.cloud.seata_at_proxy
   :members:

.. automodule:: springbootai.cloud.gateway
   :members:

.. automodule:: springbootai.cloud.feign
   :members:

.. automodule:: springbootai.cloud.discovery
   :members:

AI / LangChain / LangGraph / MCP
--------------------------------

.. automodule:: springbootai.ai.core
   :members:

.. automodule:: springbootai.ai.annotations
   :members:

.. automodule:: springbootai.langchain.core
   :members:

.. automodule:: springbootai.langgraph.runtime
   :members:

.. automodule:: springbootai.mcp.client
   :members:

.. automodule:: springbootai.mcp.server
   :members:

DevTools / CLI / 配置
---------------------

.. automodule:: springbootai.devtools
   :members:

.. automodule:: springbootai.cli.scaffold
   :members:

.. automodule:: springbootai.config.binding
   :members:

.. automodule:: springbootai.config.config_loader
   :members:

批处理 / 数据 / 校验 / 文件处理
--------------------------------

.. automodule:: springbootai.batch
   :members:

.. automodule:: springbootai.data.repository
   :members:

.. automodule:: springbootai.data.rest
   :members:

.. automodule:: springbootai.validation.validator
   :members:

.. automodule:: springbootai.csv.easy_csv
   :members:

.. automodule:: springbootai.excel.easy_excel
   :members:

基础设施 / 国际化 / WebSocket / 事务
-------------------------------------

.. automodule:: springbootai.i18n.middleware
   :members:

.. automodule:: springbootai.websocket.router
   :members:

.. automodule:: springbootai.tx.events
   :members:

.. automodule:: springbootai.datasource.dynamic
   :members:

索引
----

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
