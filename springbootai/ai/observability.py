"""
AI 模块可观测性 - 复用框架 springbootai.monitoring.prometheus.PrometheusMetrics 单例，
记录 AI 调用次数、token 用量、延迟、错误率，对接企业 Prometheus + Grafana 监控体系。
"""
import logging
import time
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger("Spring.AI.Observability")

try:
    from springbootai.monitoring.prometheus import PrometheusMetrics
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False


class AIMetrics:
    """
    AI 指标采集器 - 单例，懒初始化 Prometheus 指标。

    指标清单：
    - ai_calls_total{provider,model,status}        调用次数（success/failure）
    - ai_tokens_total{provider,type}               token 用量（prompt/completion）
    - ai_call_duration_seconds{provider,model}      调用延迟直方图
    - ai_tool_calls_total{tool,status}             工具调用次数
    - ai_circuit_breaker_state{provider}           熔断器状态（0=CLOSED 1=OPEN 2=HALF_OPEN）
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, enabled: bool = True):
        if getattr(self, "_initialized", False):
            return
        self.enabled = enabled and _PROMETHEUS_AVAILABLE
        self._metrics = None
        if self.enabled:
            try:
                pm = PrometheusMetrics()
                self._calls = pm.create_counter(
                    "ai_calls_total", "AI 模型调用次数",
                    labelnames=["provider", "model", "status"],
                )
                self._tokens = pm.create_counter(
                    "ai_tokens_total", "AI token 用量",
                    labelnames=["provider", "type"],
                )
                self._duration = pm.create_histogram(
                    "ai_call_duration_seconds", "AI 调用延迟(秒)",
                    labelnames=["provider", "model"],
                    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60, 120],
                )
                self._tool_calls = pm.create_counter(
                    "ai_tool_calls_total", "AI 工具调用次数",
                    labelnames=["tool", "status"],
                )
                self._cb_state = pm.create_gauge(
                    "ai_circuit_breaker_state", "AI 熔断器状态(0=CLOSED,1=OPEN,2=HALF_OPEN)",
                    labelnames=["provider"],
                )
                self._metrics = pm
                logger.info("AI Prometheus 指标已注册")
            except Exception as exc:
                logger.warning(
                    "AI 指标注册失败，降级为无监控 error_type=%s",
                    type(exc).__name__)
                self.enabled = False
        self._initialized = True

    def record_call(self, provider: str, model: str, status: str,
                    duration: float, usage: Optional[dict] = None):
        """记录一次模型调用"""
        if not self.enabled:
            return
        try:
            self._calls.labels(provider=provider, model=model,
                               status=status).inc()
            self._duration.labels(provider=provider, model=model).observe(duration)
            if usage:
                if usage.get("prompt_tokens"):
                    self._tokens.labels(provider=provider,
                                        type="prompt").inc(usage["prompt_tokens"])
                if usage.get("completion_tokens"):
                    self._tokens.labels(provider=provider,
                                        type="completion").inc(usage["completion_tokens"])
        except Exception as exc:  # 监控不应影响主流程
            logger.debug("record_call 失败 error_type=%s", type(exc).__name__)

    def record_tokens(self, provider: str, usage: dict):
        """只记录 token 用量，不额外虚构一次模型调用。"""
        if not self.enabled:
            return
        try:
            for key, label in (("prompt_tokens", "prompt"),
                               ("completion_tokens", "completion")):
                value = usage.get(key)
                if value:
                    self._tokens.labels(provider=provider or "unknown", type=label).inc(value)
        except Exception as exc:
            logger.debug("record_tokens 失败 error_type=%s", type(exc).__name__)

    def record_tool_call(self, tool: str, status: str):
        """记录一次工具调用"""
        if not self.enabled:
            return
        try:
            self._tool_calls.labels(tool=tool, status=status).inc()
        except Exception:
            pass

    def record_circuit_state(self, provider: str, state: str):
        """记录熔断器状态"""
        if not self.enabled:
            return
        mapping = {"CLOSED": 0, "OPEN": 1, "HALF_OPEN": 2}
        try:
            self._cb_state.labels(provider=provider).set(mapping.get(state, 0))
        except Exception:
            pass

    @contextmanager
    def observe(self, provider: str, model: str):
        """上下文管理器：自动计时并记录成功/失败"""
        start = time.time()
        status = "success"
        usage = None
        try:
            yield self
        except Exception:
            status = "failure"
            raise
        finally:
            duration = time.time() - start
            self.record_call(provider, model, status, duration, usage)


# 全局单例
ai_metrics = AIMetrics()
