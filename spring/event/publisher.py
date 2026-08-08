"""Synchronous application event publication for managed beans."""

import asyncio
import inspect
import threading
from typing import Any, Callable, List, Optional, Tuple, Type

from spring.annotations.core import ApplicationEvent


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
        if not isinstance(event, ApplicationEvent):
            event = ApplicationEvent(source=event)

        with self._lock:
            listeners = list(self._listeners)

        for event_type, callback, _, _ in listeners:
            if event_type is not None and not isinstance(event, event_type):
                continue
            result = callback(event)
            if inspect.isawaitable(result):
                self._finish_awaitable(result)
        return event

    @staticmethod
    def _finish_awaitable(awaitable) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(awaitable)
        else:
            loop.create_task(awaitable)

    def listener_count(self) -> int:
        with self._lock:
            return len(self._listeners)

    def clear(self) -> None:
        with self._lock:
            self._listeners.clear()
