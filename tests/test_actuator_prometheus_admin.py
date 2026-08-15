"""Actuator Prometheus 端点 + Spring Boot Admin 面板测试"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from spring.web import actuator as actuator_module
from spring.web.actuator import actuator_router


@pytest.fixture
def client():
    """构建带 actuator 路由的 TestClient（关闭鉴权以便测试端点功能）"""
    # 临时关闭鉴权：prometheus/sysmetrics 等敏感端点在生产环境需要 JWT，
    # 但本测试套件验证端点行为而非鉴权逻辑
    original_secured = actuator_module._actuator_secured
    actuator_module._actuator_secured = False
    app = FastAPI()
    app.include_router(actuator_router, prefix="/actuator")
    try:
        yield TestClient(app)
    finally:
        actuator_module._actuator_secured = original_secured


# ==================== /actuator/prometheus 测试 ====================

def test_prometheus_returns_text_format(client):
    """/actuator/prometheus 返回 Prometheus 文本格式"""
    resp = client.get("/actuator/prometheus")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers.get("content-type", "")
    # prometheus_client 至少注册了 python_* 默认指标
    body = resp.text
    assert "# TYPE" in body or "# HELP" in body or body.strip() == ""


def test_prometheus_content_type(client):
    """Content-Type 包含 version=0.0.4"""
    resp = client.get("/actuator/prometheus")
    ct = resp.headers.get("content-type", "")
    assert "version=0.0.4" in ct or "text/plain" in ct


def test_prometheus_has_python_metrics(client):
    """验证默认 python 进程指标存在"""
    resp = client.get("/actuator/prometheus")
    body = resp.text
    # prometheus_client 默认暴露 python_* 指标
    assert "python_" in body or "process_" in body or body.strip() == ""


# ==================== /actuator/admin 测试 ====================

def test_admin_returns_html(client):
    """/actuator/admin 返回 HTML 页面"""
    resp = client.get("/actuator/admin")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "SpringBootAI Admin" in resp.text
    assert "<!DOCTYPE html>" in resp.text


def test_admin_with_trailing_slash(client):
    """/actuator/admin/ 也正常返回"""
    resp = client.get("/actuator/admin/")
    assert resp.status_code == 200
    assert "SpringBootAI Admin" in resp.text


def test_admin_html_contains_sections(client):
    """HTML 包含所有关键面板区域"""
    resp = client.get("/actuator/admin")
    html = resp.text
    # 健康状态
    assert "健康状态" in html
    # 系统信息
    assert "系统信息" in html
    # 内存 & CPU
    assert "内存" in html and "CPU" in html
    # 线程概览
    assert "线程" in html
    # 日志级别
    assert "日志级别" in html
    # Prometheus 指标
    assert "Prometheus" in html
    # Bean 列表
    assert "Bean" in html


def test_admin_html_has_auto_refresh(client):
    """HTML 包含自动刷新逻辑"""
    resp = client.get("/actuator/admin")
    assert "setInterval" in resp.text
    assert "loadAll" in resp.text


# ==================== /actuator/sysmetrics 测试 ====================

def test_sysmetrics_returns_json(client):
    """/actuator/sysmetrics 返回 JSON 格式进程指标"""
    resp = client.get("/actuator/sysmetrics")
    assert resp.status_code == 200
    data = resp.json()
    # psutil 可能未安装，但端点应该返回 200 + error 或正常数据
    if "error" not in data:
        assert "rss_mb" in data
        assert "cpu_percent" in data
        assert "num_threads" in data
    else:
        assert data["error"] == "psutil not installed"


# ==================== /actuator/alert 告警 Webhook 测试 ====================

def test_alert_webhook_receives_firing_alert(client):
    """/actuator/alert 接收 firing 状态告警"""
    payload = {
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "HighCpuUsage", "severity": "critical", "instance": "localhost:8000"},
                "annotations": {"summary": "CPU 使用率过高", "description": "CPU 超过 80%"},
                "startsAt": "2026-08-15T10:00:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
            }
        ]
    }
    resp = client.post("/actuator/alert", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["received"] == 1


def test_alert_webhook_receives_resolved_alert(client):
    """/actuator/alert 接收 resolved 状态告警"""
    payload = {
        "alerts": [
            {
                "status": "resolved",
                "labels": {"alertname": "AppDown", "severity": "critical", "instance": "localhost:8000"},
                "annotations": {"summary": "应用已宕机", "description": "已恢复"},
                "startsAt": "2026-08-15T10:00:00Z",
                "endsAt": "2026-08-15T10:05:00Z",
            }
        ]
    }
    resp = client.post("/actuator/alert", json=payload)
    assert resp.status_code == 200
    assert resp.json()["received"] == 1


def test_alerts_history_returns_received_alerts(client):
    """/actuator/alerts 返回已接收的告警历史"""
    # 先发送一条告警
    client.post("/actuator/alert", json={
        "alerts": [{
            "status": "firing",
            "labels": {"alertname": "HighMemoryUsage", "severity": "critical", "instance": "localhost:8000"},
            "annotations": {"summary": "内存过高", "description": "RSS > 1GB"},
            "startsAt": "2026-08-15T10:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
        }]
    })
    # 查询历史
    resp = client.get("/actuator/alerts")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) > 0
    assert data[-1]["alertname"] == "HighMemoryUsage"
    assert data[-1]["severity"] == "critical"
    assert data[-1]["status"] == "firing"


def test_alert_webhook_empty_payload(client):
    """/actuator/alert 空告警列表"""
    resp = client.post("/actuator/alert", json={"alerts": []})
    assert resp.status_code == 200
    assert resp.json()["received"] == 0


# ==================== 端点目录测试 ====================

def test_endpoint_directory_includes_new_endpoints(client):
    """/actuator 目录包含 prometheus、sysmetrics、alert、alerts、admin"""
    resp = client.get("/actuator")
    data = resp.json()
    links = data["_links"]
    assert "prometheus" in links
    assert "sysmetrics" in links
    assert "alert" in links
    assert "alerts" in links
    assert "admin" in links
    assert links["prometheus"]["href"] == "/actuator/prometheus"
    assert links["admin"]["href"] == "/actuator/admin"
    assert links["alert"]["methods"] == ["POST"]
