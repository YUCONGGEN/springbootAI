"""
原生 OpenTelemetry 兼容分布式追踪 (Native OpenTelemetry-compatible Tracer)

实现 W3C Trace Context 标准的分布式追踪，无需外部 SkyWalking agent：
- 生成/传播 traceId, spanId (W3C traceparent header)
- 支持 HTTP 自动注入/提取
- 支持 Feign 跨服务调用追踪
- 支持方法级 @Trace 注解
- 支持导出到日志/控制台，兼容 Zipkin/Jaeger OTLP 格式（可选）
"""

import time
import uuid
import random
import threading
import logging
import functools
import inspect
from collections import deque
from typing import Deque, Dict, List, Optional, Any, Callable
from contextvars import ContextVar
from enum import Enum

from springbootai.logging.context import redact_log_data, safe_log_field

logger = logging.getLogger("Spring.Cloud.Tracer")


class SpanKind(Enum):
    INTERNAL = "INTERNAL"
    SERVER = "SERVER"
    CLIENT = "CLIENT"
    PRODUCER = "PRODUCER"
    CONSUMER = "CONSUMER"


class SpanStatus(Enum):
    OK = "OK"
    ERROR = "ERROR"
    UNSET = "UNSET"


class Span:
    """追踪 Span"""
    __slots__ = (
        'trace_id', 'span_id', 'parent_span_id', 'name', 'kind',
        'start_time_ns', 'end_time_ns', 'attributes', 'events',
        'status', 'status_description', 'service_name', '_ended'
    )

    def __init__(self, trace_id: str, span_id: str, parent_span_id: Optional[str],
                 name: str, kind: SpanKind, service_name: str = "unknown"):
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.name = name
        self.kind = kind
        self.start_time_ns = time.time_ns()
        self.end_time_ns = 0
        self.attributes: Dict[str, Any] = {}
        self.events: List[Dict[str, Any]] = []
        self.status = SpanStatus.UNSET
        self.status_description = ""
        self.service_name = service_name
        self._ended = False

    def set_attribute(self, key: str, value: Any):
        safe_key = safe_log_field(key, limit=128)
        self.attributes[safe_key] = redact_log_data({safe_key: value})[safe_key]
        return self

    def set_status(self, status: SpanStatus, description: str = ""):
        self.status = status
        self.status_description = safe_log_field(description, limit=512)
        return self

    def add_event(
        self, name: str, attributes: Optional[Dict[str, Any]] = None
    ):
        self.events.append({
            'name': safe_log_field(name, limit=128),
            'timestamp_ns': time.time_ns(),
            'attributes': redact_log_data(attributes or {}),
        })
        return self

    def record_exception(self, exception: Exception):
        self.add_event("exception", {
            'exception.type': type(exception).__name__,
            'exception.message': safe_log_field(exception, limit=512),
        })
        self.set_status(SpanStatus.ERROR, safe_log_field(exception, limit=512))
        return self

    def end(self):
        if not self._ended:
            self.end_time_ns = time.time_ns()
            if self.status == SpanStatus.UNSET:
                self.status = SpanStatus.OK
            self._ended = True

    @property
    def duration_ms(self) -> float:
        end = self.end_time_ns or time.time_ns()
        return (end - self.start_time_ns) / 1_000_000

    def to_dict(self) -> dict:
        tags = {
            **redact_log_data(self.attributes),
            'otel.status_code': self.status.value,
            'error': (
                safe_log_field(self.status_description, limit=512)
                if self.status == SpanStatus.ERROR else ''
            ),
        }
        return {
            'traceId': self.trace_id,
            'id': self.span_id,
            'parentId': self.parent_span_id or '',
            'name': self.name,
            'kind': self.kind.value,
            'timestamp': self.start_time_ns // 1000,  # microseconds for OTLP
            'duration': (self.end_time_ns - self.start_time_ns) // 1000 if self.end_time_ns else 0,
            'localEndpoint': {'serviceName': self.service_name},
            'annotations': [{'timestamp': e['timestamp_ns'] // 1000, 'value': e['name']} for e in self.events],
            'tags': tags,
        }


def _generate_trace_id() -> str:
    """生成 W3C 兼容 32-hex traceId"""
    return uuid.uuid4().hex


def _generate_span_id() -> str:
    """生成 16-hex spanId"""
    return '%016x' % random.getrandbits(64)


def _parse_traceparent(header: str) -> Optional[tuple]:
    """解析 W3C traceparent header: 00-traceid-spanid-flags"""
    try:
        parts = header.strip().split('-')
        if len(parts) < 4:
            return None
        version, trace_id, span_id, flags = parts[:4]
        if version == "00" and len(parts) != 4:
            return None
        if (len(version) != 2 or version.lower() == "ff"
                or len(trace_id) != 32 or len(span_id) != 16
                or len(flags) != 2):
            return None
        int(version, 16)
        int(trace_id, 16)
        int(span_id, 16)
        int(flags, 16)
        if trace_id == "0" * 32 or span_id == "0" * 16:
            return None
        return trace_id.lower(), span_id.lower(), flags.lower()
    except (AttributeError, TypeError, ValueError):
        return None
    return None


def _build_traceparent(trace_id: str, span_id: str, sampled: bool = True) -> str:
    flags = '01' if sampled else '00'
    return f"00-{trace_id}-{span_id}-{flags}"


class Tracer:
    """
    OpenTelemetry 兼容追踪器

    Usage:
        tracer = Tracer("my-service")
        with tracer.span("my-operation") as span:
            span.set_attribute("http.method", "GET")
            ...
    """
    def __init__(self, service_name: str = "springpy-app", enabled: bool = True,
                 sample_rate: float = 1.0, export_to_log: bool = True,
                 max_finished_spans: int = 10_000):
        if not isinstance(max_finished_spans, int) or not (
                1 <= max_finished_spans <= 1_000_000):
            raise ValueError("max_finished_spans must be in [1, 1000000]")
        self.service_name = service_name
        self.enabled = enabled
        self.sample_rate = sample_rate
        self.export_to_log = export_to_log
        self.max_finished_spans = max_finished_spans
        self._spans: Deque[Span] = deque(maxlen=max_finished_spans)
        self._lock = threading.Lock()
        self._span_stack: ContextVar[Optional[List[Span]]] = ContextVar(
            'span_stack', default=None)

    def _should_sample(self) -> bool:
        if self.sample_rate >= 1.0:
            return True
        if self.sample_rate <= 0:
            return False
        return random.random() < self.sample_rate

    def start_span(self, name: str, kind: SpanKind = SpanKind.INTERNAL,
                   attributes: Optional[Dict[str, Any]] = None,
                   traceparent: Optional[str] = None) -> Span:
        if not self.enabled or not self._should_sample():
            # 返回一个空span（disabled）
            span = Span("0" * 32, "0" * 16, None, name, kind, self.service_name)
            span._ended = True
            return span

        # 从context或traceparent获取父span
        stack = self._span_stack.get() or []
        parent_trace_id = None
        parent_span_id = None

        if traceparent:
            parsed = _parse_traceparent(traceparent)
            if parsed:
                parent_trace_id, parent_span_id, _ = parsed

        if parent_trace_id is None:
            if stack:
                parent = stack[-1]
                parent_trace_id = parent.trace_id
                parent_span_id = parent.span_id
            else:
                parent_trace_id = _generate_trace_id()

        span_id = _generate_span_id()
        span = Span(parent_trace_id, span_id, parent_span_id, name, kind, self.service_name)
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)

        new_stack = list(stack) + [span]
        self._span_stack.set(new_stack)
        return span

    def end_span(self, span: Span):
        if span._ended or span.trace_id == "0" * 32:
            return
        span.end()
        # 从栈中移除
        stack = self._span_stack.get() or []
        if stack and stack[-1] is span:
            self._span_stack.set(stack[:-1])
        with self._lock:
            self._spans.append(span)
        if self.export_to_log and span.status == SpanStatus.ERROR:
            logger.error(
                "[Trace] %s... %s status=%s duration=%.2fms error=%s",
                span.trace_id[:16], safe_log_field(span.name),
                span.status.value, span.duration_ms,
                safe_log_field(span.status_description),
            )
        elif self.export_to_log:
            logger.debug(
                "[Trace] %s... %s duration=%.2fms",
                span.trace_id[:16], safe_log_field(span.name), span.duration_ms,
            )

    def span(self, name: str, kind: SpanKind = SpanKind.INTERNAL,
             attributes: Optional[Dict[str, Any]] = None,
             traceparent: Optional[str] = None):
        return _SpanContext(self, name, kind, attributes, traceparent)

    def get_current_span(self) -> Optional[Span]:
        stack = self._span_stack.get() or []
        return stack[-1] if stack else None

    def get_traceparent_header(self) -> str:
        span = self.get_current_span()
        if span and span.trace_id != "0" * 32:
            return _build_traceparent(span.trace_id, span.span_id)
        return ""

    def inject_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """将traceparent注入HTTP headers（用于Feign跨服务调用）"""
        tp = self.get_traceparent_header()
        current_span = self.get_current_span()
        if tp and current_span is not None:
            headers['traceparent'] = tp
            headers['X-B3-TraceId'] = current_span.trace_id
            headers['X-B3-SpanId'] = current_span.span_id
        return headers

    def extract_from_headers(self, headers: Dict[str, str]) -> Optional[str]:
        """从HTTP headers提取traceparent"""
        if not headers:
            return None
        lowered = {str(key).lower(): str(value) for key, value in headers.items()}
        tp = lowered.get('traceparent')
        if not tp:
            # B3 支持 64/128-bit trace ID；W3C 只接受 128-bit，64-bit 左侧补零。
            tid = lowered.get('x-b3-traceid', '').strip()
            sid = lowered.get('x-b3-spanid', '').strip()
            if tid and sid:
                if len(tid) == 16:
                    tid = "0" * 16 + tid
                sampled = lowered.get('x-b3-sampled', '1').strip().lower()
                flags = '00' if sampled in {'0', 'false'} else '01'
                candidate = f"00-{tid}-{sid}-{flags}"
                tp = candidate if _parse_traceparent(candidate) else None
        return tp if tp and _parse_traceparent(tp) else None

    def get_spans(self, trace_id: Optional[str] = None) -> List[Span]:
        with self._lock:
            if trace_id:
                return [s for s in self._spans if s.trace_id == trace_id]
            return list(self._spans)

    def clear(self):
        with self._lock:
            self._spans.clear()


class _SpanContext:
    """Span 上下文管理器"""
    def __init__(self, tracer: Tracer, name: str, kind: SpanKind,
                 attributes: Optional[Dict[str, Any]],
                 traceparent: Optional[str]):
        self.tracer = tracer
        self.name = name
        self.kind = kind
        self.attributes = attributes
        self.traceparent = traceparent
        self.span: Optional[Span] = None

    def __enter__(self):
        self.span = self.tracer.start_span(self.name, self.kind,
                                           self.attributes, self.traceparent)
        return self.span

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.span is None:
            return False
        if exc_val is not None:
            self.span.record_exception(exc_val)
        self.tracer.end_span(self.span)
        return False


# 全局Tracer实例
_tracer_instance: Optional[Tracer] = None
_tracer_lock = threading.Lock()


def get_tracer(service_name: str = "springpy-app", **kwargs) -> Tracer:
    global _tracer_instance
    if _tracer_instance is None:
        with _tracer_lock:
            if _tracer_instance is None:
                _tracer_instance = Tracer(service_name, **kwargs)
    return _tracer_instance


def trace_span(name: str = "", kind: SpanKind = SpanKind.INTERNAL):
    """
    @Trace 方法级追踪注解装饰器

    Usage:
        @trace_span("my-method")
        def my_method():
            ...
    """
    def decorator(func: Callable) -> Callable:
        span_name = name or f"{func.__module__}.{func.__qualname__}"

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                tracer = get_tracer()
                with tracer.span(span_name, kind):
                    return await func(*args, **kwargs)
            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            tracer = get_tracer()
            with tracer.span(span_name, kind):
                return func(*args, **kwargs)
        return wrapper
    return decorator
