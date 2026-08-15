"""监控栈测试脚本：验证 Prometheus 抓取、Grafana 数据源、Alertmanager 告警推送"""
import json
import urllib.request
import sys

def check_url(name, url, parser=None):
    """检查 URL 是否可访问，可选解析 JSON"""
    try:
        r = urllib.request.urlopen(url, timeout=5)
        data = r.read().decode()
        if parser:
            result = parser(json.loads(data))
            print(f"[OK] {name}: {result}")
        else:
            print(f"[OK] {name}: HTTP {r.status}")
        return True
    except Exception as e:
        print(f"[FAIL] {name}: {e}")
        return False

def parse_targets(d):
    targets = d['data']['activeTargets']
    results = []
    for t in targets:
        job = t['labels'].get('job', '?')
        health = t['health']
        url = t['scrapeUrl']
        results.append(f"job={job} health={health} url={url}")
    return " | ".join(results)

def parse_prometheus_query(d):
    results = d.get('data', {}).get('result', [])
    if not results:
        return "no data yet (等待 15s 抓取周期)"
    return f"{len(results)} series, sample: {results[0]['value'][1]}"

def test_alert_webhook():
    """测试告警 Webhook 端点"""
    payload = json.dumps({
        "alerts": [{
            "status": "firing",
            "labels": {"alertname": "TestAlert", "severity": "warning", "instance": "localhost:8000"},
            "annotations": {"summary": "测试告警", "description": "这是测试推送的告警"},
            "startsAt": "2026-08-15T10:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
        }]
    }).encode()
    try:
        req = urllib.request.Request(
            "http://localhost:8000/actuator/alert",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        r = urllib.request.urlopen(req, timeout=5)
        d = json.loads(r.read())
        print(f"[OK] Alert Webhook: {d}")
        return True
    except Exception as e:
        print(f"[FAIL] Alert Webhook: {e}")
        return False

def check_alerts_history():
    """查询告警历史"""
    try:
        r = urllib.request.urlopen("http://localhost:8000/actuator/alerts", timeout=5)
        d = json.loads(r.read())
        print(f"[OK] Alerts History: {len(d)} 条告警")
        for a in d[-3:]:
            print(f"  - {a['alertname']} [{a['severity']}] {a['status']} — {a['summary']}")
        return True
    except Exception as e:
        print(f"[FAIL] Alerts History: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("SpringBootAI 监控栈测试")
    print("=" * 60)

    print("\n--- 1. SpringBootAI 应用端点 ---")
    check_url("Health", "http://localhost:8000/actuator/health")
    check_url("Prometheus 端点", "http://localhost:8000/actuator/prometheus")
    check_url("Admin 面板", "http://localhost:8000/actuator/admin")
    check_url("端点目录", "http://localhost:8000/actuator")

    print("\n--- 2. Prometheus 服务 ---")
    check_url("Prometheus 主页", "http://localhost:9090/-/healthy")
    check_url("抓取目标", "http://localhost:9090/api/v1/targets", parse_targets)
    check_url("内存指标查询", "http://localhost:9090/api/v1/query?query=process_resident_memory_bytes", parse_prometheus_query)
    check_url("CPU 指标查询", "http://localhost:9090/api/v1/query?query=rate(process_cpu_seconds_total[1m])", parse_prometheus_query)
    check_url("告警规则", "http://localhost:9090/api/v1/rules")

    print("\n--- 3. Grafana 服务 ---")
    check_url("Grafana 主页", "http://localhost:3000/api/health")

    print("\n--- 4. Alertmanager 服务 ---")
    check_url("Alertmanager 主页", "http://localhost:9093/-/healthy")

    print("\n--- 5. 告警 Webhook 测试 ---")
    test_alert_webhook()
    check_alerts_history()

    print("\n" + "=" * 60)
    print("测试完成！")
    print("访问地址：")
    print("  Grafana:       http://localhost:3000  (admin/admin)")
    print("  Prometheus:    http://localhost:9090")
    print("  Alertmanager:  http://localhost:9093")
    print("  Admin 面板:    http://localhost:8000/actuator/admin")
    print("=" * 60)
