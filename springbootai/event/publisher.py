"""Deterministic synchronous and asynchronous application event publication."""

import asyncio
import inspect
import threading
from typing import Any, Callable, List, Optional, Tuple, Type

from springbootai.annotations.core import ApplicationEvent


ListenerEntry = Tuple[Optional[Type[ApplicationEvent]], Callable, int, int]


class ApplicationEventPublisher:
    """Publish events to listeners registered by the application context."""

    def __init__(self):
        self._listeners: List[ListenerEntry] = []
        self._lock = threading.RLock()
        self._sequence = 0

    def add_listener(
        self,
        callback: Callable,
        event_type: Optional[Type[ApplicationEvent]] = None,
        order: int = 0,
    ) -> None:
        with self._lock:
            self._sequence += 1
            self._listeners.append((event_type, callback, order, self._sequence))
            self._listeners.sort(key=lambda item: (item[2], item[3]))

    def remove_listener(self, callback: Callable) -> None:
        with self._lock:
            self._listeners = [
                entry for entry in self._listeners if entry[1] != callback
            ]

    def publish_event(self, event: Any) -> ApplicationEvent:
        event, listeners = self._matching_listeners(event)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            running_loop = False
        else:
            running_loop = True

        if running_loop and any(
            inspect.iscoroutinefunction(callback)
            for _, callback, _, _ in listeners
        ):
            raise RuntimeError(
                "async event listeners require 'await publish_event_async(...)' "
                "when an event loop is running"
            )

        for _, callback, _, _ in listeners:
            result = callback(event)
            if inspect.isawaitable(result):
                if running_loop:
                    close = getattr(result, "close", None)
                    if callable(close):
                        close()
                    raise RuntimeError(
                        "an event listener returned an awaitable; use "
                        "'await publish_event_async(...)'"
                    )
                asyncio.run(result)
        return event

    async def publish_event_async(self, event: Any) -> ApplicationEvent:
        """Publish an event and await every matching listener in order.

        Exceptions are propagated to the publisher instead of being lost in a
        detached task, so callers can apply transaction/retry semantics.
        """
        event, listeners = self._matching_listeners(event)
        for _, callback, _, _ in listeners:
            result = callback(event)
            if inspect.isawaitable(result):
                await result
        return event

    def _matching_listeners(
        self, event: Any
    ) -> Tuple[ApplicationEvent, List[ListenerEntry]]:
        if not isinstance(event, ApplicationEvent):
            event = ApplicationEvent(source=event)
        with self._lock:
            listeners = [
                entry for entry in self._listeners
                if entry[0] is None or isinstance(event, entry[0])
            ]
        return event, listeners

    def listener_count(self) -> int:
        with self._lock:
            return len(self._listeners)

    def clear(self) -> None:
        with self._lock:
            self._listeners.clear()
