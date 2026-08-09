"""
分布式事务模块
集成真实 Seata，并提供仅供开发验证的 HTTP 补偿协调器

支持三种模式：
- local: 本地模式，仅追踪事务状态（默认）
- http: 实验性 HTTP 补偿模式，不提供 AT 强一致性，禁止用于生产
- distributed: 真实Seata Server模式（需要seata SDK）

实验性 HTTP 补偿模式工作原理：
1. TM（事务发起方）开启全局事务，生成XID
2. Feign调用远程服务时，通过 X-TX-XID header 传递XID
3. RM（分支事务方）注册分支到TC（内嵌协调器）
4. TM 提交时通知所有分支提交；回滚时通知所有分支回滚
5. 分支服务暴露 /seata/branch/{branchId}/commit 和 /seata/branch/{branchId}/rollback 端点

注意：分布式模式(distributed)要启用完整的分布式事务功能，请：
1. 安装Seata Server（https://seata.io/zh-cn/docs/overview/what-is-seata.html）
2. 安装并验证与本适配层 API 兼容的企业 Seata Python SDK
3. 配置registry.conf和file.conf
4. 在启动时设置SEATA_ENABLED=true
"""
import logging
import time
import threading
import uuid
import json
from contextvars import ContextVar
from typing import Dict, Any, Optional, List, Callable
from urllib import request as urlrequest
from urllib.error import URLError, HTTPError

# 可选导入Seata
try:
    import seata
    from seata.rm import DataSourceProxy
    from seata.tm import GlobalTransaction
    from seata.core.context.RootContext import RootContext
    _seata_available = True
except ImportError:
    seata = None
    DataSourceProxy = None
    GlobalTransaction = None
    RootContext = None
    _seata_available = False

logger = logging.getLogger("Spring.Cloud.Seata")


class BranchStatus:
    """分支事务状态"""
    REGISTERED = "REGISTERED"
    COMMITTED = "COMMITTED"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"


class SeataTransactionManager:
    """Seata事务管理器（支持local/http/distributed三种模式）"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, server_addr: str = "localhost:8091", application_id: str = "", 
                 transaction_group: str = "my_tx_group", mode: str = "local"):
        if hasattr(self, '_initialized'):
            return
        self.server_addr = server_addr
        self.application_id = application_id
        self.transaction_group = transaction_group
        self.mode = mode  # 'local', 'http', or 'distributed'
        self._transaction_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
            'springpy_seata_transaction_context', default=None
        )
        self._seata_client_initialized = False
        self._initialized = True

        # 实验性 HTTP 模式：进程内状态只用于开发验证，不承诺故障恢复。
        self._global_transactions: Dict[str, Dict] = {}
        self._branches: Dict[str, List[Dict]] = {}  # xid -> [branch]
        self._gt_lock = threading.Lock()

        # 分支事务回调注册（本地分支，用于同进程服务调用）
        self._branch_callbacks: Dict[str, Dict[str, Callable]] = {}
        self._cb_lock = threading.Lock()
        
        if mode == "distributed":
            self.set_mode(mode)

    def configure(self, server_addr: str = "localhost:8091", application_id: str = "",
                  transaction_group: str = "my_tx_group", mode: str = "local") -> None:
        """重新配置单例；初始化入口不能依赖第二次构造调用。"""
        self.server_addr = server_addr
        self.application_id = application_id
        self.transaction_group = transaction_group
        self.set_mode(mode)

    def _get_context(self) -> Dict[str, Any]:
        return self._transaction_context.get() or {}

    def _set_context(self, **values: Any) -> None:
        current = dict(self._get_context())
        current.update(values)
        self._transaction_context.set(current)
    
    def _init_seata_client(self):
        """初始化 Seata 客户端；分布式模式禁止静默降级。"""
        if not _seata_available:
            raise RuntimeError("seata.mode=distributed requires a compatible Seata Python SDK")
        if not self.application_id:
            raise RuntimeError("seata.application_id is required in distributed mode")
        try:
            # 设置Seata配置环境变量
            import os
            os.environ.setdefault('SEATA_IP', self.server_addr.split(':')[0])
            os.environ.setdefault('SEATA_PORT', self.server_addr.split(':')[1] if ':' in self.server_addr else '8091')
            os.environ.setdefault('SEATA_APPLICATION_ID', self.application_id)
            os.environ.setdefault('SEATA_TX_GROUP', self.transaction_group)
            
            logger.info(f"[Seata] Initializing Seata client with server: {self.server_addr}, application_id: {self.application_id}")
            
            if hasattr(seata, 'init'):
                seata.init()
            elif hasattr(seata, 'config') and hasattr(seata.config, 'init'):
                seata.config.init()
            else:
                raise RuntimeError("installed Seata SDK does not expose a supported init API")

            self._seata_client_initialized = True
            logger.info("[Seata] Client initialized successfully in distributed mode")
        except Exception as e:
            self._seata_client_initialized = False
            raise RuntimeError(f"failed to initialize distributed Seata client: {e}") from e
    
    def begin_transaction(self, timeout: int = 60000, name: str = "") -> str:
        """
        开启分布式事务
        
        支持三种模式：
        - local: 仅追踪事务上下文
        - http: 实验性 HTTP 补偿模式，生成本地 XID，提交/回滚通过 HTTP 通知分支
        - distributed: 使用真实Seata Server
        
        Args:
            timeout: 事务超时时间（毫秒）
            name: 事务名称
        
        Returns:
            事务ID (XID)
        """
        # 检查是否已经在事务中
        context = self._get_context()
        if context.get('in_transaction', False):
            logger.warning("Nested transaction detected, returning current tx_id")
            return context.get('tx_id', "")
        
        # 生成事务ID
        tx_id = uuid.uuid4().hex
        
        # 设置事务上下文
        self._transaction_context.set({
            'in_transaction': True,
            'tx_id': tx_id,
            'status': 'BEGIN',
            'timeout': timeout,
            'start_time': time.time(),
            'name': name,
        })

        # 实验性 HTTP 补偿模式：注册进程内全局事务
        if self.mode == "http":
            with self._gt_lock:
                self._global_transactions[tx_id] = {
                    'xid': tx_id,
                    'name': name,
                    'status': 'BEGIN',
                    'start_time': time.time(),
                    'timeout': timeout,
                }
                self._branches[tx_id] = []
            logger.info(f"[Seata-HTTP] Begin global transaction: {tx_id}")
        
        elif self.mode == "distributed":
            if not (_seata_available and self._seata_client_initialized):
                self._cleanup_context()
                raise RuntimeError("distributed Seata client is not initialized")
            try:
                GlobalTransaction.begin(timeout, name)
                seata_tx_id = RootContext.getXID()
                if not seata_tx_id:
                    raise RuntimeError("Seata transaction began without an XID")
                tx_id = seata_tx_id
                self._set_context(tx_id=tx_id)
                logger.info(f"[Seata] Begin global transaction (distributed): {tx_id}")
                return tx_id
            except Exception as e:
                self._cleanup_context()
                raise RuntimeError(f"failed to begin distributed Seata transaction: {e}") from e
        
        else:
            logger.info(f"[Seata] Begin transaction (local context): {tx_id}")

        return tx_id

    def register_branch(self, xid: str, branch_id: str = "", resource_id: str = "",
                        callback_url: str = "", commit_cb: Callable = None,
                        rollback_cb: Callable = None, service_name: str = "") -> str:
        """
        注册分支事务（实验性 HTTP 补偿模式）
        
        Args:
            xid: 全局事务ID
            branch_id: 分支ID（自动生成如果为空）
            resource_id: 资源标识（如数据库表名）
            callback_url: 远程回调URL（用于跨服务调用），如 http://order-service/seata/branch
            commit_cb: 本地提交回调函数
            rollback_cb: 本地回滚回调函数
            service_name: 服务名

        Returns:
            branch_id
        """
        if not branch_id:
            branch_id = uuid.uuid4().hex[:16]

        if self.mode == 'http':
            with self._gt_lock:
                if xid not in self._global_transactions:
                    raise ValueError(f"Unknown or completed experimental HTTP transaction: {xid}")

        branch = {
            'branch_id': branch_id,
            'xid': xid,
            'resource_id': resource_id,
            'callback_url': callback_url,
            'service_name': service_name or self.application_id,
            'status': BranchStatus.REGISTERED,
            'registered_at': time.time(),
        }

        with self._gt_lock:
            if xid not in self._branches:
                self._branches[xid] = []
            self._branches[xid].append(branch)

        # 注册本地回调
        if commit_cb or rollback_cb:
            with self._cb_lock:
                self._branch_callbacks[branch_id] = {
                    'commit': commit_cb,
                    'rollback': rollback_cb,
                }

        logger.info(f"[Seata-HTTP] Branch registered: xid={xid[:16]}... branch_id={branch_id[:16]}... "
                     f"service={service_name} url={callback_url}")
        return branch_id

    def _notify_branch(self, branch: dict, action: str) -> bool:
        """通知分支事务提交或回滚"""
        branch_id = branch['branch_id']
        # 本地回调优先
        with self._cb_lock:
            cb = self._branch_callbacks.get(branch_id)
        if cb:
            fn = cb.get('commit') if action == 'commit' else cb.get('rollback')
            if fn:
                try:
                    fn(branch['xid'], branch_id)
                    return True
                except Exception as e:
                    logger.error(f"[Seata-HTTP] Local branch {action} failed: {e}")
                    return False

        # HTTP回调
        url = branch.get('callback_url')
        if url:
            try:
                full_url = f"{url.rstrip('/')}/{branch_id}/{action}"
                req = urlrequest.Request(full_url, method='POST',
                                         data=json.dumps({'xid': branch['xid'], 'branchId': branch_id}).encode(),
                                         headers={'Content-Type': 'application/json'})
                resp = urlrequest.urlopen(req, timeout=5)
                return resp.status == 200
            except Exception as e:
                logger.error(f"[Seata-HTTP] HTTP branch {action} failed for {branch_id[:16]}: {e}")
                return False
        logger.error(
            f"[Seata-HTTP] Branch {branch_id[:16]} has no {action} callback; failing closed"
        )
        return False
    
    def commit_transaction(self, tx_id: str) -> bool:
        """
        提交分布式事务
        
        Args:
            tx_id: 事务ID
        
        Returns:
            是否成功
        """
        try:
            context = self._get_context()
            current_tx_id = context.get('tx_id', "")
            if current_tx_id and current_tx_id != tx_id:
                logger.error(f"Transaction mismatch: expected {tx_id}, got {current_tx_id}")
                return False
            
            start_time = context.get('start_time', 0)
            timeout = context.get('timeout', 60000)
            duration = (time.time() - start_time) * 1000
            
            if duration > timeout:
                logger.error(f"Transaction timeout: {duration}ms > {timeout}ms")
                self.rollback_transaction(tx_id)
                return False

            # 实验性 HTTP 补偿模式：通知所有分支提交
            if self.mode == "http":
                all_ok = True
                with self._gt_lock:
                    branches = list(self._branches.get(tx_id, []))
                    transaction = self._global_transactions.get(tx_id)
                    if transaction is None:
                        logger.error(f"[Seata-HTTP] Unknown transaction: {tx_id}")
                        return False
                    transaction['status'] = 'COMMITTING'
                for branch in branches:
                    ok = self._notify_branch(branch, 'commit')
                    branch['status'] = BranchStatus.COMMITTED if ok else BranchStatus.FAILED
                    if not ok:
                        all_ok = False
                with self._gt_lock:
                    self._global_transactions[tx_id]['status'] = 'COMMITTED' if all_ok else 'PARTIAL_COMMIT'
                if all_ok:
                    self._cleanup_http_transaction(tx_id)
                logger.info(f"[Seata-HTTP] Commit transaction {tx_id[:16]}... branches={len(branches)} success={all_ok}")
                return all_ok
            
            # 分布式模式
            if self.mode == "distributed":
                if not (_seata_available and self._seata_client_initialized):
                    logger.error("Distributed Seata client is not initialized; commit rejected")
                    return False
                try:
                    GlobalTransaction.commit()
                    self._set_context(status='COMMITTED')
                    logger.info(f"[Seata] Commit global transaction: {tx_id}, duration={duration:.2f}ms")
                    return True
                except Exception as e:
                    logger.error(f"[Seata] Failed to commit global transaction: {e}. Rolling back...")
                    self.rollback_transaction(tx_id)
                    return False
            
            # 本地模式
            self._set_context(status='COMMITTED')
            logger.info(f"[Seata] Commit transaction (local): {tx_id}, duration={duration:.2f}ms")
            return True
        finally:
            self._cleanup_context()
    
    def rollback_transaction(self, tx_id: str) -> bool:
        """
        回滚分布式事务
        
        Args:
            tx_id: 事务ID
        
        Returns:
            是否成功
        """
        try:
            current_tx_id = self._get_context().get('tx_id', "")
            if current_tx_id and current_tx_id != tx_id:
                logger.error(f"Transaction mismatch: expected {tx_id}, got {current_tx_id}")
                return False

            # 实验性 HTTP 补偿模式：通知所有分支回滚
            if self.mode == "http":
                all_ok = True
                with self._gt_lock:
                    branches = list(self._branches.get(tx_id, []))
                    if tx_id in self._global_transactions:
                        self._global_transactions[tx_id]['status'] = 'ROLLING_BACK'
                for branch in branches:
                    ok = self._notify_branch(branch, 'rollback')
                    branch['status'] = BranchStatus.ROLLED_BACK if ok else BranchStatus.FAILED
                    if not ok:
                        all_ok = False
                with self._gt_lock:
                    if tx_id in self._global_transactions:
                        self._global_transactions[tx_id]['status'] = 'ROLLED_BACK' if all_ok else 'PARTIAL_ROLLBACK'
                if all_ok:
                    self._cleanup_http_transaction(tx_id)
                logger.info(f"[Seata-HTTP] Rollback transaction {tx_id[:16]}... branches={len(branches)} success={all_ok}")
                return all_ok
            
            # 分布式模式
            if self.mode == "distributed":
                if not (_seata_available and self._seata_client_initialized):
                    logger.error("Distributed Seata client is not initialized; rollback failed")
                    return False
                try:
                    GlobalTransaction.rollback()
                    self._set_context(status='ROLLED_BACK')
                    logger.info(f"[Seata] Rollback global transaction: {tx_id}")
                    return True
                except Exception as e:
                    logger.error(f"[Seata] Failed to rollback global transaction: {e}")
                    return False
            
            # 本地模式
            self._set_context(status='ROLLED_BACK')
            logger.info(f"[Seata] Rollback transaction (local): {tx_id}")
            return True
        finally:
            self._cleanup_context()
    
    def _cleanup_context(self):
        """清理事务上下文"""
        self._transaction_context.set(None)
        
        # 清理Seata上下文
        if _seata_available and RootContext:
            try:
                RootContext.unbindXID()
            except Exception:
                pass

    def _cleanup_http_transaction(self, tx_id: str) -> None:
        """成功完成后移除协调状态和本地回调，避免长期进程内存增长。"""
        with self._gt_lock:
            branches = self._branches.pop(tx_id, [])
            self._global_transactions.pop(tx_id, None)
        with self._cb_lock:
            for branch in branches:
                self._branch_callbacks.pop(branch['branch_id'], None)
    
    def is_in_transaction(self) -> bool:
        """检查是否在事务中"""
        return bool(self._get_context().get('in_transaction', False))
    
    def get_current_tx_id(self) -> str:
        """获取当前事务ID"""
        # 优先从Seata获取
        if _seata_available and RootContext:
            try:
                seata_tx_id = RootContext.getXID()
                if seata_tx_id:
                    return seata_tx_id
            except Exception:
                pass
        
        return self._get_context().get('tx_id', "")
    
    def get_transaction_status(self) -> str:
        """获取当前事务状态"""
        return self._get_context().get('status', "NONE")
    
    def get_mode(self) -> str:
        """获取当前事务模式"""
        return self.mode
    
    def set_mode(self, mode: str):
        """设置事务模式 (local/http/distributed)"""
        if mode not in ["local", "http", "distributed"]:
            raise ValueError("Mode must be 'local', 'http' or 'distributed'")
        
        if mode == "distributed":
            # 即使初始化失败也保持 distributed，后续事务必须失败关闭，
            # 不能沿用之前的 local 模式继续执行核心业务。
            self.mode = mode
            if not self._seata_client_initialized:
                self._init_seata_client()
            return
        self.mode = mode

    def get_transaction_info(self) -> Dict[str, Any]:
        """获取当前事务信息（用于调试/监控）"""
        with self._gt_lock:
            return {
                'mode': self.mode,
                'active_global_tx': len(self._global_transactions),
                'active_branches': sum(len(b) for b in self._branches.values()),
                'in_transaction': self.is_in_transaction(),
                'current_xid': self.get_current_tx_id(),
            }

    @staticmethod
    def get_xid_from_headers(headers: Dict[str, str]) -> str:
        """从HTTP请求头中提取XID"""
        if not headers:
            return ""
        return (headers.get('X-TX-XID') or headers.get('X-Seata-XID') or
                headers.get('x-tx-xid') or headers.get('x-seata-xid') or "")

    @staticmethod
    def inject_xid_headers(headers: Dict[str, str], xid: str) -> Dict[str, str]:
        """将XID注入到HTTP请求头（供Feign使用）"""
        if xid:
            headers['X-TX-XID'] = xid
            headers['X-Seata-XID'] = xid
        return headers


# 创建全局Seata事务管理器实例
seata_manager = SeataTransactionManager()


def init_seata(config: dict) -> None:
    """
    初始化Seata配置
    
    Args:
        config: 配置字典，包含server_addr, application_id, transaction_group, mode等
    
    配置说明：
        server_addr: Seata Server地址，默认 localhost:8091
        application_id: 应用ID，必填（分布式模式）
        transaction_group: 事务分组，默认 my_tx_group
        mode: 事务模式，可选 'local'（默认）或 'distributed'
    
    分布式模式要求：
        1. 部署Seata Server
        2. 创建seata_undo_log表（MySQL示例）：
           CREATE TABLE IF NOT EXISTS `seata_undo_log` (
               `id` BIGINT(20) NOT NULL AUTO_INCREMENT COMMENT '主键',
               `branch_id` BIGINT(20) NOT NULL COMMENT '分支事务ID',
               `xid` VARCHAR(100) NOT NULL COMMENT '全局事务ID',
               `context` VARCHAR(128) NOT NULL COMMENT '上下文',
               `rollback_info` LONGBLOB NOT NULL COMMENT '回滚信息',
               `log_status` INT(11) NOT NULL COMMENT '状态',
               `log_created` DATETIME NOT NULL COMMENT '创建时间',
               `log_modified` DATETIME NOT NULL COMMENT '修改时间',
               PRIMARY KEY (`id`),
               UNIQUE KEY `ux_undo_log` (`xid`,`branch_id`)
           ) ENGINE=InnoDB AUTO_INCREMENT=1 DEFAULT CHARSET=utf8 COMMENT='Seata回滚日志表';
    """
    mode = str(config.get('mode', 'local')).lower()
    if mode == 'http' and not config.get('experimental_http_enabled', False):
        raise ValueError(
            "seata.mode=http is an experimental best-effort compensation mode; "
            "set seata.experimental_http_enabled=true only for development tests"
        )
    seata_manager.configure(
        server_addr=config.get('server_addr', 'localhost:8091'),
        application_id=config.get('application_id', ''),
        transaction_group=config.get('transaction_group', 'my_tx_group'),
        mode=mode,
    )
