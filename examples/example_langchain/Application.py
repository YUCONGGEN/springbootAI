"""
example_langchain 应用入口
演示如何把 spring.langchain 模块集成进 SpringBootAI 应用。

启动流程：
1. @SpringBootApplication 触发组件扫描（发现 @Configuration / @Service / @RestController）
2. LangChainAppConfig 的 @Bean 方法在 refresh 阶段调用 configure_ai + configure_langchain，
   把全部 lc* Bean 注册到 BeanFactory（可被 @Autowired 注入）
3. 各 @Service 通过构造器 @Autowired 拿到 lcChainService / lcAgentService / lcIndexService
4. @RestController 暴露 HTTP 接口

无 API Key 时设置环境变量 AI_ALLOW_FAKE=true，会降级 FakeChatModel 跑通全部流程。
"""
import sys
import os

# 移动到 examples/ 后需同时加入项目根（导入 spring）和 examples/（导入 example_langchain 包）
_HERE = os.path.dirname(os.path.abspath(__file__))
_EXAMPLES_DIR = os.path.dirname(_HERE)
_PROJECT_ROOT = os.path.dirname(_EXAMPLES_DIR)
for _p in (_PROJECT_ROOT, _EXAMPLES_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 无 key 环境下自动降级 FakeChatModel（生产环境请删除此行并配置真实 key）
os.environ.setdefault("AI_ALLOW_FAKE", "true")

from spring import SpringBootApplication


@SpringBootApplication(scan_base_packages=["example_langchain"])
class Application:
    """LangChain 集成示例应用启动类"""


if __name__ == "__main__":
    from spring import run
    run(Application, port=8081)
