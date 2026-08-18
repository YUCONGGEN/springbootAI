"""Executable annotations backed by the existing LangChain services."""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
from typing import Any, Callable

from springbootai.annotations.core import Component, SpringAnnotation, get_spring_annotations


_MODES = {"chain", "conversation", "summarize", "agent"}


def _validate_input_size(arguments: dict[str, Any], maximum: int) -> None:
    try:
        encoded = json.dumps(arguments, ensure_ascii=False, default=str).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TypeError("LangChain annotation inputs must be serializable") from exc
    if len(encoded) > maximum:
        raise ValueError(f"LangChain annotation input exceeds {maximum} bytes")


def _class_annotation(instance: Any) -> Any:
    target = instance if inspect.isclass(instance) else type(instance)
    return next(
        (
            item
            for item in reversed(get_spring_annotations(target))
            if isinstance(item, LangChainClient)
        ),
        None,
    )


def _resolve_bean(instance: Any, bean_name: str, attributes: tuple[str, ...]) -> Any:
    for attribute in attributes:
        bean = getattr(instance, attribute, None)
        if bean is not None:
            return bean

    from springbootai.context.registry import BeanRegistry

    bean = BeanRegistry().get(bean_name)
    if bean is None:
        raise RuntimeError(
            f"LangChain bean {bean_name!r} is unavailable; run configure_langchain() "
            "or inject the service on the annotated instance"
        )
    return bean


def _bound_arguments(
    function: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> tuple[Any, dict[str, Any]]:
    bound = inspect.signature(function).bind(*args, **kwargs)
    bound.apply_defaults()
    instance = bound.arguments.pop("self", None)
    bound.arguments.pop("cls", None)
    return instance, dict(bound.arguments)


class LangChainClient(Component):
    """Mark a component whose annotated methods execute LangChain services."""

    _annotation_type = "langchain_client"

    def __init__(
        self,
        value: str = "",
        chain_service_bean: str = "lcChainService",
        agent_service_bean: str = "lcAgentService",
    ):
        super().__init__(value=value)
        self.chain_service_bean = chain_service_bean
        self.agent_service_bean = agent_service_bean


class LangChainCall(SpringAnnotation):
    """Execute a chain, conversation, summary, or agent when a method is called.

    The decorated function body is a declarative placeholder. Its signature is
    used as the input contract and is preserved for dependency injection and
    API documentation.
    """

    _annotation_type = "langchain_call"

    def __init__(
        self,
        prompt: str = "",
        *,
        mode: str = "chain",
        input_name: str = "",
        tools_bean: str = "",
        agent_type: str = "react",
        memory_bean: str = "",
        max_input_bytes: int = 65_536,
    ):
        normalized = mode.strip().lower()
        if normalized not in _MODES:
            raise ValueError(f"unsupported LangChainCall mode: {mode!r}")
        if normalized == "chain" and not prompt:
            raise ValueError("LangChainCall chain mode requires prompt")
        if normalized == "agent" and not tools_bean:
            raise ValueError(
                "LangChainCall agent mode requires tools_bean so callers cannot inject tools"
            )
        if max_input_bytes < 1024 or max_input_bytes > 10 * 1024 * 1024:
            raise ValueError("max_input_bytes must be between 1024 and 10485760")
        super().__init__(
            prompt=prompt,
            mode=normalized,
            input_name=input_name,
            tools_bean=tools_bean,
            agent_type=agent_type,
            memory_bean=memory_bean,
            max_input_bytes=max_input_bytes,
        )

    def _execute(self, instance: Any, arguments: dict[str, Any]) -> Any:
        _validate_input_size(arguments, self.max_input_bytes)
        class_config = _class_annotation(instance)
        chain_bean = (
            class_config.chain_service_bean if class_config else "lcChainService"
        )
        agent_bean = (
            class_config.agent_service_bean if class_config else "lcAgentService"
        )

        if self.mode == "chain":
            service = _resolve_bean(
                instance, chain_bean, ("_lc_chain_service", "lc_chain_service")
            )
            return service.run_llm_chain(self.prompt, **arguments)

        if self.mode == "summarize":
            key = self.input_name or "texts"
            if key not in arguments:
                raise TypeError(f"LangChainCall summarize input {key!r} is missing")
            texts = arguments[key]
            if not isinstance(texts, (list, tuple)) or not all(
                isinstance(item, str) for item in texts
            ):
                raise TypeError("LangChainCall summarize input must be a list of strings")
            service = _resolve_bean(
                instance, chain_bean, ("_lc_chain_service", "lc_chain_service")
            )
            return service.run_summarize(list(texts))

        key = self.input_name or "user_input"
        if key not in arguments:
            raise TypeError(f"LangChainCall {self.mode} input {key!r} is missing")
        user_input = arguments[key]
        if not isinstance(user_input, str):
            raise TypeError(f"LangChainCall {self.mode} input must be a string")

        if self.mode == "conversation":
            service = _resolve_bean(
                instance, chain_bean, ("_lc_chain_service", "lc_chain_service")
            )
            memory = None
            if self.memory_bean:
                memory = _resolve_bean(instance, self.memory_bean, ("_lc_memory",))
            return service.run_conversation(user_input, memory=memory)

        service = _resolve_bean(
            instance, agent_bean, ("_lc_agent_service", "lc_agent_service")
        )
        tools = _resolve_bean(instance, self.tools_bean, ("_lc_agent_tools",))
        return service.run_agent(
            tools,
            user_input,
            agent_type=self.agent_type,
        )

    def __call__(self, function: Callable[..., Any]) -> Callable[..., Any]:
        if not callable(function):
            raise TypeError("LangChainCall can decorate only a callable")

        if inspect.iscoroutinefunction(function):

            @functools.wraps(function)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                instance, arguments = _bound_arguments(function, args, kwargs)
                return await asyncio.to_thread(self._execute, instance, arguments)

            wrapper = async_wrapper
        else:

            @functools.wraps(function)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                instance, arguments = _bound_arguments(function, args, kwargs)
                return self._execute(instance, arguments)

            wrapper = sync_wrapper

        wrapper.__spring_annotations__ = list(
            getattr(function, "__dict__", {}).get("__spring_annotations__", [])
        ) + [self]
        self._original_class = function
        return wrapper


def bind_langchain_client(
    instance: Any, *, chain_service: Any = None, agent_service: Any = None,
    tools: Any = None, memory: Any = None
) -> Any:
    """Explicitly inject services for tests or applications without auto-config."""
    if _class_annotation(instance) is None:
        raise TypeError("bind_langchain_client target must use @LangChainClient")
    if chain_service is not None:
        instance._lc_chain_service = chain_service
    if agent_service is not None:
        instance._lc_agent_service = agent_service
    if tools is not None:
        instance._lc_agent_tools = tools
    if memory is not None:
        instance._lc_memory = memory
    return instance


__all__ = ["LangChainCall", "LangChainClient", "bind_langchain_client"]
