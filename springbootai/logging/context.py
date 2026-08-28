"""Request-scoped logging context and conservative secret redaction."""
from __future__ import annotations

import contextvars
import copy
import re
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from typing import Iterator, Optional
from urllib.parse import urlsplit, urlunsplit


_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "springbootai_request_id", default="-"
)
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_BEARER_PATTERN = re.compile(
    r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"
)
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(authorization|proxy.?authorization|x.?api.?key|api.?key|"
    r"password|passwd|client.?secret|access.?token|refresh.?token|token|"
    r"cookie|credential|secret)"
)
_UNQUOTED_HEADER_PATTERN = re.compile(
    r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie)"
    r"(?P<separator>[\"']?\s*[:=]\s*)(?![\"'])"
    r"(?P<value>[^\r\n,}]+)"
)
_KEY_VALUE_PATTERN = re.compile(
    r"(?i)(authorization|proxy-authorization|x-api-key|api[_-]?key|"
    r"password|passwd|client[_-]?secret|access[_-]?token|refresh[_-]?token|token|"
    r"cookie|set-cookie|credential)"
    r"(?P<key_quote>[\"']?)(?P<separator>\s*[:=]\s*)"
    r"(?:(?P<quote>[\"'])(?P<quoted>.*?)(?P=quote)|"
    r"(?P<value>[^\s,;\}\]&\"']+))"
)
_URL_SECRET_PATTERN = re.compile(
    r"(?i)([?&](?:access_token|refresh_token|token|api[_-]?key|password|secret)=)"
    r"([^&#\s]+)"
)


def normalize_request_id(value: Optional[str] = None) -> str:
    """Accept a safe caller ID or generate a compact random identifier."""
    candidate = str(value or "").strip()
    if candidate and _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return uuid.uuid4().hex


def get_request_id() -> str:
    return _request_id.get()


def outbound_request_id(candidate: Optional[str] = None) -> str:
    """Return the bound ID, or validate/generate one for non-request callers."""
    current = get_request_id()
    return current if current != "-" else normalize_request_id(candidate)


def set_request_id(value: Optional[str] = None):
    """Set the current request ID and return a token suitable for reset."""
    return _request_id.set(normalize_request_id(value))


def reset_request_id(token) -> None:
    _request_id.reset(token)


@contextmanager
def request_context(request_id: Optional[str] = None) -> Iterator[str]:
    """Bind a request ID around background jobs, CLI tasks or tests."""
    token = set_request_id(request_id)
    try:
        yield get_request_id()
    finally:
        reset_request_id(token)


def redact_sensitive(value: object) -> str:
    """Mask common credentials in free-form log messages."""
    text = str(value)
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    text = re.sub(
        r"[\x00-\x09\x0b\x0c\x0e-\x1f\x7f]",
        lambda match: f"\\x{ord(match.group()):02x}",
        text,
    )
    text = _UNQUOTED_HEADER_PATTERN.sub(
        lambda match: (
            f"{match.group(1)}{match.group('separator')}******"
        ),
        text,
    )
    text = _BEARER_PATTERN.sub("Bearer ******", text)
    text = _KEY_VALUE_PATTERN.sub(
        lambda match: (
            f"{match.group(1)}{match.group('key_quote')}"
            f"{match.group('separator')}"
            f"{match.group('quote') or ''}******{match.group('quote') or ''}"
        ),
        text,
    )
    return _URL_SECRET_PATTERN.sub(r"\1******", text)


def safe_log_field(value: object, limit: int = 160) -> str:
    """Return one bounded, credential-redacted field for structured logs."""
    try:
        text = redact_sensitive(value)
    except Exception:
        text = f"<unprintable:{type(value).__name__}>"
    text = (
        text.replace("\u0085", "\\u0085")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    try:
        bounded_limit = max(1, int(limit))
    except (TypeError, ValueError, OverflowError):
        bounded_limit = 160
    return (
        text if len(text) <= bounded_limit
        else text[:bounded_limit] + "..."
    )


def redact_log_data(value: object, *, _depth: int = 0):
    """Recursively sanitize structured log extras without stringifying them."""
    if _depth > 6:
        return "<redacted-depth-limit>"
    if isinstance(value, Mapping):
        return {
            key: (
                "******" if _SENSITIVE_KEY_PATTERN.search(str(key))
                else redact_log_data(item, _depth=_depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_log_data(item, _depth=_depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_log_data(item, _depth=_depth + 1) for item in value)
    if isinstance(value, BaseException):
        return sanitize_exception_value(value)
    if isinstance(value, str):
        return redact_sensitive(value)
    return value


def sanitize_exception_value(error: BaseException) -> BaseException:
    """Copy an exception with redacted args while retaining its traceback."""
    try:
        sanitized = copy.copy(error)
        sanitized.args = tuple(redact_log_data(arg) for arg in error.args)
        sanitized.__traceback__ = error.__traceback__
        # Exception chains can carry the original provider/database message
        # even after the top-level args are redacted.  Do not let a formatter
        # walk back into an unsanitized cause or implicit context.
        sanitized.__cause__ = None
        sanitized.__context__ = None
        sanitized.__suppress_context__ = True
        rendered = str(sanitized)
        safe_rendered = redact_sensitive(rendered)
        # Custom exception classes often render attributes outside ``args``.
        # Replacing args alone is therefore not a sufficient confidentiality
        # boundary; fall back to a plain exception whose renderer we control.
        if rendered != safe_rendered:
            replacement = RuntimeError(
                f"{type(error).__name__}: {safe_rendered}")
            replacement.__traceback__ = error.__traceback__
            replacement.__suppress_context__ = True
            return replacement
        return sanitized
    except Exception:
        try:
            safe_rendered = redact_sensitive(error)
        except Exception:
            safe_rendered = "<unprintable exception>"
        return RuntimeError(f"{type(error).__name__}: {safe_rendered}")


def sanitize_url(value: object, *, keep_query: bool = False) -> str:
    """Return a log-safe URL without credentials, fragments or query values."""
    try:
        parts = urlsplit(str(value))
    except (TypeError, ValueError):
        return "<invalid-url>"
    if not parts.scheme or not parts.netloc:
        return redact_sensitive(value)
    hostname = parts.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    try:
        port = parts.port
    except ValueError:
        return "<invalid-url>"
    if port is not None:
        netloc = f"{netloc}:{port}"
    query = redact_sensitive(parts.query) if keep_query else ""
    return urlunsplit((parts.scheme, netloc, parts.path, query, ""))


__all__ = [
    "get_request_id", "normalize_request_id", "outbound_request_id",
    "redact_log_data", "redact_sensitive",
    "request_context", "reset_request_id", "safe_log_field", "sanitize_url",
    "set_request_id",
    "sanitize_exception_value",
]
