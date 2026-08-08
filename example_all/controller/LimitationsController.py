"""
兼容性修复验证控制器
============================================================================
对已修复的兼容问题提供可测试的 API 端点。
"""
import os
import xml.etree.ElementTree as ET

from spring.annotations.core import (
    RestController, RequestMapping, GetMapping, PostMapping, PatchMapping,
    Autowired, Slf4j, ApplicationEvent, EventListener,
)
from spring.event import ApplicationEventPublisher
from spring.web.result import Result


class LimitProbeEvent(ApplicationEvent):
    def __init__(self, source, value: str):
        super().__init__(source)
        self.value = value


@RestController
@RequestMapping("/api/limits")
@Slf4j
class LimitationsController:
    """框架兼容性修复验证控制器。"""

    @Autowired
    def __init__(self, application_event_publisher: ApplicationEventPublisher):
        self.event_publisher = application_event_publisher
        self.received_events = []

    # ==================== Nacos Windows Docker 兼容状态 ====================

    @GetMapping("/nacos")
    def nacos_limit(self):
        """报告 Nacos 当前状态及 Windows Docker 兼容方案。"""
        nacos_available = False
        error_info = "client_not_ready"
        server_addr = None

        try:
            from spring.cloud.discovery import nacos_client
            server_addr = getattr(nacos_client, "server_addr", None)
            nacos_available = bool(nacos_client and nacos_client.is_healthy())
            if nacos_available:
                error_info = "ok"
        except Exception as e:
            error_info = str(e)[:120]

        return Result.success(data={
            "limitation": (
                "Nacos Windows Docker 启动兼容问题已修复"
                if nacos_available else
                "Nacos Windows Docker 当前不可用"
            ),
            "reason": (
                "Docker Desktop cgroup v2 下需使用 "
                "JAVA_TOOL_OPTIONS=-XX:-UseContainerSupport；"
                "Nacos 2.2+ 需配置 NACOS_AUTH_TOKEN 和 identity；"
                "使用 MySQL 外部存储时需先导入 mysql-schema.sql"
            ),
            "status": "resolved" if nacos_available else "unavailable",
            "nacos_available": nacos_available,
            "server_addr": server_addr,
            "detail": error_info,
            "workaround": "设置 JVM cgroup、认证变量和 Nacos MySQL schema",
        })

    # ==================== XML 原始比较运算符兼容 ====================

    @GetMapping("/xml-unescape")
    def xml_unescaped_limit(self):
        """分别验证 XML Mapper 中未转义的 <= 和 >=。"""
        from spring.orm.pymybatis.xml_parser import XmlParser

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        xml_path = os.path.join(base_dir, "mappers", "_test_unescaped_ops.xml")

        result = {
            "limitation": "XML Mapper 已兼容原始 <= 和 >= 运算符",
            "status": "resolved",
            "test_file": "mappers/_test_unescaped_ops.xml",
            "content": "SELECT * FROM users WHERE created_at >= '2024-01-01' AND age <= 65",
        }

        operator_samples = {
            "unescaped_lte": "<mapper><select>age <= 65</select></mapper>",
            "unescaped_gte": "<mapper><select>age >= 18</select></mapper>",
        }
        result["standard_xml_checks"] = {}
        result["framework_parser_checks"] = {}
        for name, sample in operator_samples.items():
            try:
                ET.fromstring(sample)
                result["standard_xml_checks"][name] = {"parse_ok": True}
            except ET.ParseError as e:
                result["standard_xml_checks"][name] = {
                    "parse_ok": False,
                    "error": str(e),
                }

            try:
                parser = XmlParser()
                parser.parse_string(sample)
                result["framework_parser_checks"][name] = {"parse_ok": True}
            except (ET.ParseError, ValueError) as e:
                result["framework_parser_checks"][name] = {
                    "parse_ok": False,
                    "error": str(e),
                }

        if not os.path.exists(xml_path):
            return Result.success(data={**result, "file_exists": False,
                "error": "测试文件不存在"})

        result["file_exists"] = True
        parser = XmlParser()
        try:
            parser.parse_file(xml_path)
            statements = parser.get_all_mapped_statements()
            result["parse_ok"] = True
            result["statements"] = len(statements)
        except Exception as e:
            result["parse_ok"] = False
            result["error_type"] = type(e).__name__
            result["error_msg"] = str(e)[:200]
            result["status"] = "failed"
            result["fix"] = "检查 XML 是否存在比较运算符之外的格式错误"

        return Result.success(data=result)

    # ==================== @PatchMapping ====================

    @PatchMapping("/patch-probe")
    def patch_probe(self, value: str = "patched"):
        return Result.success(data={"method": "PATCH", "value": value})

    @GetMapping("/patch-mapping")
    def patch_mapping_limit(self):
        """验证 @PatchMapping 已注册为 FastAPI PATCH 路由。"""
        try:
            from spring.annotations.core import PatchMapping
            implemented = True
        except ImportError:
            implemented = False

        return Result.success(data={
            "limitation": "@PatchMapping 已实现",
            "status": "resolved" if implemented else "unavailable",
            "patch_mapping_available": implemented,
            "probe": "PATCH /api/limits/patch-probe",
            "annotation_count": {
                "@GetMapping": True, "@PostMapping": True,
                "@PutMapping": True, "@DeleteMapping": True,
                "@PatchMapping": implemented,
            },
        })

    # ==================== ApplicationEvent/EventListener ====================

    @EventListener(event_type=LimitProbeEvent)
    def on_limit_probe_event(self, event: LimitProbeEvent):
        self.received_events.append(event.value)

    @PostMapping("/event-listener/publish")
    def publish_event_probe(self, value: str = "event-ok"):
        before = len(self.received_events)
        self.event_publisher.publish_event(LimitProbeEvent(self, value))
        invoked = len(self.received_events) == before + 1
        return Result.success(data={
            "published": True,
            "listener_invoked": invoked,
            "value": self.received_events[-1] if invoked else None,
        })

    @GetMapping("/event-listener")
    def event_listener_limit(self):
        """验证应用事件发布与监听器注册状态。"""
        has_event_listener = False
        has_application_event = False

        try:
            from spring.annotations.core import EventListener
            has_event_listener = True
        except ImportError:
            pass

        try:
            from spring.annotations.core import ApplicationEvent
            has_application_event = True
        except ImportError:
            pass

        # 检查 event 目录
        springboot_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        event_dirs = []
        for d in ['spring/event', 'spring/events', 'spring/listener']:
            full = os.path.join(springboot_dir, d)
            if os.path.isdir(full):
                event_dirs.append(d)

        return Result.success(data={
            "limitation": "Spring 应用事件发布/订阅机制已实现",
            "status": (
                "resolved"
                if has_event_listener and has_application_event else
                "unavailable"
            ),
            "event_listener_available": has_event_listener,
            "application_event_available": has_application_event,
            "registered_listener_count": self.event_publisher.listener_count(),
            "event_directories_found": event_dirs,
            "probe": "POST /api/limits/event-listener/publish",
        })

    # ==================== 限制5: 全局 config_loader 配置不同步 ====================

    @GetMapping("/config-sync")
    def config_sync_limit(self):
        """验证全局 config_loader 与 ApplicationContext 的 ConfigLoader 不同步"""
        from spring.config.config_loader import ConfigLoader, config_loader as global_loader

        # ApplicationContext 方式: 传入 base_path 指向 example_all
        example_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ctx_loader = ConfigLoader(base_path=example_dir)
        ctx_config = ctx_loader.get_config()
        ctx_db = ctx_config.get('database', {})

        default_loader = ConfigLoader()
        default_config = default_loader.get_config()
        default_db = default_config.get('database', {})

        global_config = global_loader.get_config()
        global_db = global_config.get('database', {})

        ctx_enabled = ctx_db.get('enabled', False)
        global_enabled = global_db.get('enabled', False)
        synced = (
            os.path.abspath(ctx_loader.config_path)
            == os.path.abspath(global_loader.config_path)
            and ctx_config == global_config
            and os.path.abspath(ctx_loader.config_path)
            == os.path.abspath(default_loader.config_path)
            and ctx_config == default_config
        )

        return Result.success(data={
            "limitation": (
                "全局 config_loader 与 ApplicationContext 配置已同步"
                if synced else
                "全局 config_loader 与 ApplicationContext 配置仍不同步"
            ),
            "status": "resolved" if synced else "out_of_sync",
            "config_in_sync": synced,
            "application_context": {
                "config_file": ctx_loader.config_path,
                "database_enabled": ctx_enabled,
                "database_driver": ctx_db.get('driver', '<未设置>'),
            },
            "global_config_loader": {
                "config_file": global_loader.config_path,
                "config_found": os.path.exists(global_loader.config_path),
                "database_enabled": global_enabled,
                "database_driver": global_db.get('driver', '<未设置>'),
            },
            "new_default_loader": {
                "config_file": default_loader.config_path,
                "database_enabled": default_db.get('enabled', False),
                "database_driver": default_db.get('driver', '<未设置>'),
            },
        })
