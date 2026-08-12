"""Secure factories for official LangGraph checkpoint implementations."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator, Union

from spring.langgraph.runtime import LangGraphUnavailableError


@contextmanager
def open_sqlite_checkpointer(
    database: Union[str, os.PathLike[str]], *, timeout_seconds: float = 30.0
) -> Iterator[Any]:
    """Open an official SQLite checkpointer with strict deserialization.

    SQLite is useful for local development and a single application process.
    Multi-worker or multi-host deployments must inject a checkpointer backed by
    shared infrastructure instead.
    """

    if timeout_seconds <= 0 or timeout_seconds > 300:
        raise ValueError("timeout_seconds must be in (0, 300]")
    try:
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as exc:  # pragma: no cover - optional dependency boundary
        raise LangGraphUnavailableError(
            "SQLite checkpoint support is not installed. Install it with "
            "pip install springbootAI[langgraph]"
        ) from exc

    serializer = JsonPlusSerializer(
        pickle_fallback=False,
        allowed_json_modules=None,
        allowed_msgpack_modules=None,
    )
    connection = sqlite3.connect(
        os.fspath(database),
        timeout=timeout_seconds,
        check_same_thread=False,
    )
    try:
        connection.execute(f"PRAGMA busy_timeout = {int(timeout_seconds * 1000)}")
        yield SqliteSaver(connection, serde=serializer)
    finally:
        connection.close()
