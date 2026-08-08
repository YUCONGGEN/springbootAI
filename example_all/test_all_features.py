"""
example_all 全量集成测试脚本
============================================================================
测试环境:
  - MySQL    : Docker mysql:8.0 @ localhost:3306
  - Redis    : Docker redis:7-alpine @ localhost:6379
  - Nacos    : Docker nacos/nacos-server @ localhost:8848
  - RabbitMQ : Docker rabbitmq:3-management-alpine @ localhost:5672
  - Prometheus: 内嵌 @ localhost:8000

覆盖的注解:
  [Web]  18个, [组件/DI/配置] 15个, [AOP] 10个, [安全] 3个,
  [功能] 6个, [ORM] 8个, [Cloud] 9个, [消息] 2个
============================================================================
"""
import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_01_module_imports():
    """模块导入测试 (25个模块)"""
    print("=" * 60)
    print("测试1: 全量模块导入")
    print("=" * 60)

    modules = {
        # Controller (8)
        "AllWebController": "example_all.controller.AllWebController",
        "AopController": "example_all.controller.AopController",
        "SecurityController": "example_all.controller.SecurityController",
        "ExceptionController": "example_all.controller.ExceptionController",
        "OrmController": "example_all.controller.OrmController",
        "CloudController": "example_all.controller.CloudController",
        "MessagingController": "example_all.controller.MessagingController",
        "LimitationsController": "example_all.controller.LimitationsController",
        # Service (8)
        "AllAnnotationService": "example_all.service.AllAnnotationService",
        "AopService": "example_all.service.AopService",
        "AsyncService": "example_all.service.AsyncService",
        "ScheduledService": "example_all.service.ScheduledService",
        "SecurityService": "example_all.service.SecurityService",
        "OrmBridgeService": "example_all.service.OrmBridgeService",
        "CloudService": "example_all.service.CloudService",
        "MessagingService": "example_all.service.MessagingService",
        "PrimaryService": "example_all.service.AllAnnotationService",
        "SecondaryService": "example_all.service.AllAnnotationService",
        "LazyService": "example_all.service.AllAnnotationService",
        # Config (2)
        "AppConfig": "example_all.config.AppConfig",
        "AppProperties": "example_all.config.AppConfig",
        # Repository (1)
        "UserRepository": "example_all.repository.UserRepository",
        # Mapper (1)
        "UserMapper": "example_all.mappers.UserMapper",
        # Interceptor (2)
        "LoggingInterceptor": "example_all.interceptor.AllInterceptor",
        "SecurityHeaderInterceptor": "example_all.interceptor.AllInterceptor",
    }

    ok = 0; fail = 0
    for name, module_path in modules.items():
        try:
            module_name, cls_name = module_path.rsplit(".", 1)
            mod = __import__(module_name, fromlist=[cls_name])
            obj = getattr(mod, cls_name, None)
            print(f"  OK  {name}") if obj else print(f"  FAIL {name}")
            ok += 1 if obj else 0
            fail += 0 if obj else 1
        except Exception as e:
            print(f"  FAIL {name} — {e}")
            fail += 1
    print(f"\n  导入: {ok} 成功, {fail} 失败")
    assert fail == 0, f"{fail} 个模块导入失败"


def test_02_xml_mapper_parsing():
    """XML Mapper 文件解析"""
    print("\n" + "=" * 60)
    print("测试2: XML Mapper 解析 (MySQL版)")
    print("=" * 60)

    from spring.orm.pymybatis.xml_parser import XmlParser

    base_dir = os.path.dirname(os.path.abspath(__file__))
    xml_path = os.path.join(base_dir, "mappers", "UserMapper.xml")
    if not os.path.exists(xml_path):
        print(f"  FAIL: XML 文件不存在: {xml_path}")
        assert False, f"XML 文件不存在: {xml_path}"

    parser = XmlParser()
    parser.parse_file(xml_path)
    ns = parser.get_namespace()
    statements = parser.get_all_mapped_statements()

    print(f"  namespace: {ns}")
    print(f"  MappedStatements: {len(statements)}")
    for s in statements:
        print(f"    [{s.sql_type}] {s.id}" +
              (f" (resultMap={s.result_map})" if s.result_map else ""))

    expected = {
        "find_all_xml": "SELECT", "find_by_id_xml": "SELECT",
        "search_users": "SELECT", "find_by_ids": "SELECT",
        "find_pagination": "SELECT", "count_users": "SELECT",
        "insert_xml": "INSERT", "batch_insert": "INSERT",
        "update_xml": "UPDATE", "delete_xml": "DELETE", "batch_delete": "DELETE",
    }
    ok = sum(1 for stmt_id, exp in expected.items()
             if (s := parser.get_mapped_statement(f"{ns}.{stmt_id}"))
             and s.sql_type == exp)
    print(f"\n  XML解析: {ok}/{len(expected)}")
    assert ok == len(expected), f"XML解析 {ok}/{len(expected)} 不匹配"


def test_03_annotations_combo():
    """注解组合验证"""
    print("\n" + "=" * 60)
    print("测试3: 注解组合验证")
    print("=" * 60)

    from example_all.service.AopService import AopService
    method = AopService.multi_annotation_combo
    annotations = getattr(method, '__spring_annotations__', [])
    ann_types = [type(a).__name__ for a in annotations]
    print(f"  multi_annotation_combo 上的注解: {ann_types}")

    expected = {"RateLimit", "AuditLog", "Metrics", "Trace"}
    found = {name for name in ann_types if name in expected}
    passed = expected == found
    print(f"  组合注解: {'PASS' if passed else 'FAIL'} (期望{expected}, 实际{found})")
    assert passed, f"组合注解不匹配: 期望{expected}, 实际{found}"


def test_04_component_scan():
    """组件扫描验证"""
    print("\n" + "=" * 60)
    print("测试4: 组件扫描验证")
    print("=" * 60)

    components = {
        "Controller (7个)": [
            "example_all.controller.AllWebController.AllWebController",
            "example_all.controller.AllWebController.ViewController",
            "example_all.controller.AopController.AopController",
            "example_all.controller.SecurityController.SecurityController",
            "example_all.controller.ExceptionController.GlobalExceptionHandler",
            "example_all.controller.ExceptionController.ErrorTriggerController",
            "example_all.controller.OrmController.OrmController",
            "example_all.controller.OrmController.ScheduleController",
            "example_all.controller.CloudController.CloudController",
            "example_all.controller.MessagingController.MessagingController",
            "example_all.controller.MessagingController.MessageConsumer",
            "example_all.controller.LimitationsController.LimitationsController",
        ],
        "Service (10个)": [
            "example_all.service.AllAnnotationService.AllAnnotationService",
            "example_all.service.AllAnnotationService.ConsumerService",
            "example_all.service.AllAnnotationService.PrimaryService",
            "example_all.service.AllAnnotationService.SecondaryService",
            "example_all.service.AllAnnotationService.LazyService",
            "example_all.service.AopService.AopService",
            "example_all.service.AsyncService.AsyncService",
            "example_all.service.SecurityService.SecurityService",
            "example_all.service.OrmBridgeService.OrmBridgeService",
            "example_all.service.CloudService.CloudService",
            "example_all.service.MessagingService.MessagingService",
        ],
        "Component/Repository/Mapper": [
            "example_all.service.ScheduledService.ScheduledService",
            "example_all.repository.UserRepository.UserRepository",
            "example_all.mappers.UserMapper.UserMapper",
        ],
    }

    ok = 0; fail = 0
    for group, cls_paths in components.items():
        for cls_path in cls_paths:
            module_name, cls_name = cls_path.rsplit(".", 1)
            try:
                mod = __import__(module_name, fromlist=[cls_name])
                ok += 1
            except Exception as e:
                print(f"  FAIL: {cls_path} — {e}")
                fail += 1
    print(f"  组件扫描: {ok} 成功, {fail} 失败")
    assert fail == 0, f"{fail} 个组件扫描失败"


def test_05_http_api():
    """HTTP API 全量端点测试"""
    print("\n" + "=" * 60)
    print("测试5: HTTP API 全量端点测试")
    print("=" * 60)

    import threading
    import uvicorn
    import urllib.request
    import urllib.error

    port = 9999
    server_started = threading.Event()

    def run_server():
        from example_all.Application import Application
        from spring.main import create_app
        try:
            app = create_app(Application)
            server_started.set()
            config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
            uvicorn.Server(config).run()
        except Exception as ex:
            server_started.set()
            print(f"  Server error: {ex}")

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()

    if not server_started.wait(timeout=30):
        print("  FAIL: 服务器启动超时")
        assert False, "服务器启动超时"
    time.sleep(3)

    base_url = f"http://127.0.0.1:{port}"

    api_tests = [
        # === Web 层 (5) ===
        ("GET", "/api/web/hello", 200, "@GetMapping"),
        ("GET", "/api/web/hello/world", 200, "@GetMapping+@PathVariable"),
        ("GET", "/api/web/search?keyword=test&page=1&size=5", 200, "@GetMapping+@RequestParam"),
        ("GET", "/api/web/config/info", 200, "@LogExecutionTime"),
        ("POST", "/api/web/user/form?username=test&email=test@example.com", 200, "@PostMapping form"),

        # === AOP (8) ===
        ("GET", "/api/aop/rate-limit", 200, "@RateLimit"),
        ("GET", "/api/aop/synchronized", 200, "@Synchronized"),
        ("GET", "/api/aop/metrics/info", 200, "@Metrics info"),
        ("POST", "/api/aop/metrics/process?data=hello", 200, "@Metrics process"),
        ("GET", "/api/aop/trace?span_name=test", 200, "@Trace"),
        ("POST", "/api/aop/audit-log?target_id=42&action=test", 200, "@AuditLog"),
        ("POST", "/api/aop/validate?email=test@ex.com&username=usr&age=25", 200, "@Validate pass"),
        ("POST", "/api/aop/validate?email=bad&username=ab&age=10", 400, "@Validate fail"),

        # === 异常处理 (2) ===
        ("GET", "/api/errors/value", 400, "@ExceptionHandler ValueError"),
        ("GET", "/api/errors/runtime", 500, "@ExceptionHandler RuntimeError"),

        # === 安全 (2) ===
        ("GET", "/api/security/public", 200, "@Security public"),
        ("POST", "/api/security/login?username=admin&role=ROLE_ADMIN", 200, "@Security login JWT"),

        # === 调度 (1) ===
        ("GET", "/api/schedule/stats", 200, "@Scheduled stats"),

        # === ORM MySQL (6) ===
        ("POST", "/api/orm/init-db", 200, "MySQL 建表"),
        ("POST", "/api/orm/annotation/user?username=john&email=john@test.com&phone=1380001", 200, "@Insert MySQL"),
        ("GET", "/api/orm/annotation/user/1", 200, "@Select MySQL byId"),
        ("GET", "/api/orm/annotation/users", 200, "@Select MySQL all"),
        ("GET", "/api/orm/annotation/search?username=john", 200, "@Select 动态条件"),
        ("GET", "/api/orm/stats", 200, "ORM stats MySQL"),

        # === Cloud (2) ===
        ("GET", "/api/cloud/status", 200, "@Cloud status"),
        ("GET", "/api/cloud/loadbalance/status", 200, "@LoadBalanced"),

        # === Messaging (1) ===
        ("GET", "/api/messaging/status", 200, "@RabbitMQ status"),

        # === 框架兼容性修复探针 (7) ===
        ("GET", "/api/limits/nacos", 200, "@Limits: Nacos状态"),
        ("GET", "/api/limits/xml-unescape", 200, "@Limits: XML 运算符兼容"),
        ("GET", "/api/limits/patch-mapping", 200, "@Limits: @PatchMapping注册"),
        ("PATCH", "/api/limits/patch-probe?value=patched", 200, "@PatchMapping实际路由"),
        ("GET", "/api/limits/event-listener", 200, "@Limits: Event/Listener注册"),
        ("POST", "/api/limits/event-listener/publish?value=event-ok", 200, "Event发布/监听实际调用"),
        ("GET", "/api/limits/config-sync", 200, "@Limits: config_loader同步"),
        ("POST", "/api/event/publish/user?username=probe&email=probe%40test.com", 200, "ApplicationEvent用户事件"),
        ("GET", "/api/event/stats", 200, "EventListener统计"),
    ]

    ok = 0; fail = 0
    for method, path, expected_code, desc in api_tests:
        url = f"{base_url}{path}"
        try:
            req = urllib.request.Request(url, method=method)
            resp = urllib.request.urlopen(req, timeout=10)
            actual = resp.getcode()
            if actual == expected_code:
                print(f"  OK  [{actual}] {desc}")
                ok += 1
            else:
                print(f"  WARN [{actual}/{expected_code}] {desc}")
                fail += 1
        except urllib.error.HTTPError as e:
            if e.code == expected_code:
                print(f"  OK  [{e.code}] {desc} (expected error)")
                ok += 1
            else:
                print(f"  FAIL [{e.code}/{expected_code}] {desc}")
                fail += 1
        except Exception as e:
            print(f"  FAIL {desc} — {type(e).__name__}: {e}")
            fail += 1

    print(f"\n  API: {ok} 通过, {fail} 失败")
    assert fail == 0, f"{fail} 个HTTP API失败"


# ==================== 主入口 ====================

if __name__ == '__main__':
    print(f"Python: {sys.version}")
    print(f"项目: {os.path.dirname(os.path.abspath(__file__))}\n")

    tests = [
        ("模块导入 (26项)", test_01_module_imports),
        ("XML Mapper解析 (11项)", test_02_xml_mapper_parsing),
        ("注解组合 (4项)", test_03_annotations_combo),
        ("组件扫描 (26项)", test_04_component_scan),
        ("HTTP API端点 (36项)", test_05_http_api),
    ]

    results = []
    for name, fn in tests:
        try:
            fn()
            results.append((name, True))
        except Exception as e:
            print(f"\n  ERROR: {name} 异常: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    all_ok = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            all_ok = False

    if all_ok:
        print("\n所有测试通过!")
    else:
        print("\n部分测试失败")
        sys.exit(1)
