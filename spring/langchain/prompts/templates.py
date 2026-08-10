"""
Prompt 模板工厂 - 封装 langchain classic 的 PromptTemplate / ChatPromptTemplate /
FewShotPromptTemplate，作为 @Component Bean 注入业务服务。

设计原则：保留 langchain 模板的全部能力，仅在外层提供 Spring 风格的统一入口与
中文注释，便于业务侧用同一工厂创建各类模板。
"""
import logging
from typing import Any, Dict, List, Optional


logger = logging.getLogger("Spring.LangChain")


class PromptTemplateFactory:
    """
    Prompt 模板工厂 Bean。

    提供 3 类模板的创建入口：
    - create_prompt_template: 基础字符串模板（单变量 / 多变量）
    - create_chat_prompt_template: 多角色对话模板（system/user/assistant）
    - create_few_shot_prompt_template: Few-shot 示例模板

    所有方法返回 langchain 原生模板实例，可直接用于 LLMChain / Agent。
    """

    @staticmethod
    def create_prompt_template(template: str,
                               input_variables: Optional[List[str]] = None
                               ) -> Any:
        """
        创建字符串 PromptTemplate。

        Args:
            template: 模板字符串，含 {var} 占位符
            input_variables: 占位变量列表；为空时自动从 template 解析
        """
        from langchain_core.prompts import PromptTemplate
        if input_variables is None:
            # 自动解析 {var} 占位符
            import string
            formatter = string.Formatter()
            input_variables = [
                fn for _, fn, _, _ in formatter.parse(template) if fn
            ]
        return PromptTemplate(input_variables=input_variables,
                              template=template)

    @staticmethod
    def create_chat_prompt_template(messages: List[Any],
                                    input_variables: Optional[List[str]] = None
                                    ) -> Any:
        """
        创建对话模板 ChatPromptTemplate。

        Args:
            messages: 消息列表，每项可为：
                      - dict: {"role": "system|user|assistant", "content": "...{var}..."}
                      - tuple/list: ("system", "...{var}...")（与 langchain from_messages 等价）
            input_variables: 占位变量列表（可选）
        """
        from langchain_core.prompts import ChatPromptTemplate
        # 兼容 dict 与 tuple/list 两种形态，统一转为 (role, content) 元组列表
        tuples = []
        for m in messages:
            if isinstance(m, dict):
                tuples.append((m["role"], m["content"]))
            elif isinstance(m, (tuple, list)):
                tuples.append((m[0], m[1]))
            else:
                raise TypeError(
                    f"messages 项必须是 dict 或 tuple，得到 {type(m).__name__}")
        # langchain 1.x 用 from_messages（from_tuples 在新版已移除）
        return ChatPromptTemplate.from_messages(tuples)

    @staticmethod
    def create_few_shot_prompt_template(examples: List[Dict[str, str]],
                                        example_prompt: Any,
                                        prefix: str = "",
                                        suffix: str = "",
                                        input_variables: Optional[List[str]] = None
                                        ) -> Any:
        """
        创建 Few-shot 模板。

        Args:
            examples: 示例字典列表
            example_prompt: 单条示例的 PromptTemplate
            prefix/suffix: 模板前缀/后缀
            input_variables: 最终模板的输入变量
        """
        from langchain_core.prompts import FewShotPromptTemplate
        return FewShotPromptTemplate(
            examples=examples,
            example_prompt=example_prompt,
            prefix=prefix,
            suffix=suffix,
            input_variables=input_variables or [],
        )

    @staticmethod
    def from_template(template: str, **kwargs) -> Any:
        """便捷入口：直接从字符串创建 ChatPromptTemplate（langchain 风格）。"""
        from langchain_core.prompts import ChatPromptTemplate
        return ChatPromptTemplate.from_template(template, **kwargs)
