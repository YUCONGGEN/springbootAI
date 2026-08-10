"""
ORM 数据访问控制器 — 测试 MyBatis 注解 + XML Mapper 混合使用
以及 Schedule 状态端点
"""
from spring.annotations.core import (
    RestController, RequestMapping, GetMapping, PostMapping, PutMapping, DeleteMapping,
    Autowired, Slf4j,
)
from spring.web.result import Result
from example_all.mappers.UserMapper import UserMapper
from example_all.service.OrmBridgeService import OrmBridgeService
from example_all.service.ScheduledService import ScheduledService


@RestController
@RequestMapping("/api/orm")
@Slf4j
class OrmController:
    """ORM Mapper 测试控制器 — 注解 + XML 混合"""

    @Autowired
    def __init__(self, user_mapper: UserMapper, orm_bridge_service: OrmBridgeService):
        self.user_mapper = user_mapper
        self.orm_service = orm_bridge_service

    # ==================== 注解版 Mapper CRUD ====================

    @PostMapping("/init-db")
    def init_database(self):
        """初始化 MySQL 数据库表（直连 pymysql）"""
        try:
            import os
            import pymysql
            # 从 example_all/config/application.yml 读取 MySQL 配置，避免硬编码凭据
            from spring.config.config_loader import ConfigLoader
            example_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_cfg = ConfigLoader(base_path=example_dir).get_config().get('database', {})
            host = db_cfg.get('host', 'localhost')
            port = int(db_cfg.get('port', 3306))
            connection_options = dict(
                user=db_cfg.get('username', 'root'),
                password=str(db_cfg.get('password', '') or ''),
                database=db_cfg.get('database', 'springpy'), charset='utf8mb4',
                connect_timeout=5,
            )
            try:
                conn = pymysql.connect(host=host, port=port, **connection_options)
            except pymysql.MySQLError:
                # Docker Desktop publishes MySQL on localhost.  Only fall back
                # to the container IP when that configured endpoint is really
                # unavailable; eagerly replacing localhost breaks Windows/macOS.
                if host not in ('localhost', '127.0.0.1', '0.0.0.0'):
                    raise
                from spring.orm.pymybatis.pool.connection_pool import _get_docker_container_ip_by_port
                docker_ip = _get_docker_container_ip_by_port(port)
                if not docker_ip or docker_ip == host:
                    raise
                conn = pymysql.connect(
                    host=docker_ip, port=port, **connection_options
                )
            try:
                cur = conn.cursor()
                # 重建表以保证与 Mapper 期望的 schema 一致（幂等初始化）
                cur.execute("DROP TABLE IF EXISTS users")
                cur.execute("""
                    CREATE TABLE users (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        username VARCHAR(50) NOT NULL,
                        email VARCHAR(100),
                        phone VARCHAR(20),
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
                conn.commit()
                return Result.success(data={"created": "users table initialized"})
            finally:
                conn.close()
        except Exception as e:
            return Result.error(message=f"DB init failed: {e}", code=500)

    @PostMapping("/annotation/user")
    def create_user_annotation(self, username: str, email: str, phone: str = ""):
        """@Insert 注解版 — 插入用户"""
        result = self.user_mapper.insert(username, email, phone)
        return Result.success(data={"result": result, "username": username})

    @GetMapping("/annotation/user/{user_id}")
    def get_user_annotation(self, user_id: int):
        """@Select 注解版 — 查询用户"""
        result = self.user_mapper.find_by_id(user_id)
        return Result.success(data=result)

    @GetMapping("/annotation/users")
    def list_users_annotation(self):
        """@Select 注解版 — 查询所有"""
        result = self.user_mapper.find_all()
        return Result.success(data={"count": len(result), "users": result})

    @GetMapping("/annotation/search")
    def search_users_annotation(self, username: str = "", email: str = ""):
        """@Select 注解版 — 动态条件查询"""
        result = self.user_mapper.find_by_condition(
            username=username or None,
            email=email or None,
        )
        if result is None:
            result = []
        return Result.success(data={"count": len(result), "users": result})

    @PutMapping("/annotation/user/{user_id}")
    def update_user_annotation(self, user_id: int, username: str = "", email: str = "", phone: str = ""):
        """@Update 注解版 — 更新用户"""
        result = self.user_mapper.update(
            user_id,
            username=username or None,
            email=email or None,
            phone=phone or None,
        )
        return Result.success(data={"affected": result})

    @DeleteMapping("/annotation/user/{user_id}")
    def delete_user_annotation(self, user_id: int):
        """@Delete 注解版 — 删除用户"""
        result = self.user_mapper.delete(user_id)
        return Result.success(data={"deleted": result})

    # ==================== transactional 操作 ====================

    @PostMapping("/transactional/create")
    def transactional_create(self, username: str, email: str):
        """@Transactional — 事务创建"""
        result = self.orm_service.transactional_create(username, email)
        return Result.success(data=result)

    @PostMapping("/transactional/rollback")
    def transactional_rollback(self, should_rollback: bool = True):
        """@Transactional — 事务回滚"""
        try:
            result = self.orm_service.transactional_with_rollback(should_rollback)
            return Result.success(data={"result": result})
        except Exception as e:
            return Result.error(message=f"Rollback: {e}", code=400)

    # ==================== @Cacheable + @Retryable ====================

    @GetMapping("/cache/user/{user_id}")
    def cached_user(self, user_id: int):
        """@Cacheable — 缓存用户"""
        result = self.orm_service.cached_get_user(user_id)
        return Result.success(data=result)

    @GetMapping("/retry/network")
    def retry_network(self, fail: bool = False):
        """@Retryable — 自动重试网络调用"""
        try:
            result = self.orm_service.flaky_network_call(fail)
            return Result.success(data={"result": result})
        except Exception as e:
            return Result.error(message=str(e), code=503)

    # ==================== ORM 统计 ====================

    @GetMapping("/stats")
    def orm_stats(self):
        """ORM 统计信息"""
        count_result = self.user_mapper.count_all()
        return Result.success(data={"total_users": count_result})

    @GetMapping("/batch-delete")
    def batch_delete_annotation(self, ids: str = ""):
        """@Delete + foreach 批量删除"""
        id_list = [int(i) for i in ids.split(",") if i.strip()]
        if id_list:
            result = self.user_mapper.delete_batch(id_list)
            return Result.success(data={"deleted": result, "ids": id_list})
        return Result.bad_request(message="No IDs provided")


@RestController
@RequestMapping("/api/schedule")
@Slf4j
class ScheduleController:
    """定时任务状态控制器"""

    @Autowired
    def __init__(self, scheduled_service: ScheduledService):
        self.scheduled_service = scheduled_service

    @GetMapping("/stats")
    def schedule_stats(self):
        """获取定时任务执行统计"""
        return Result.success(data=self.scheduled_service.get_stats())
