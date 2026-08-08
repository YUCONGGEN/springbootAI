"""
分布式事务模块
基于Seata理念实现分布式事务管理

支持三种模式：
- local: 本地模式，仅追踪事务状态（默认）
- http: HTTP-AT模式，通过REST端点协调跨服务事务（无需Seata Server）
- distributed: 真实Seata Server模式（需要seata SDK）

HTTP-AT 模式工作原理：
1. TM（事务发起方）开启全局事务，生成XID
2. Feign调用远程服务时，通过 X-TX-XID header 传递XID
3. RM（分支事务方）注册分支到TC（内嵌协调器）
4. TM 提交时通知所有分支提交；回滚时通知所有分支回滚
5. 分支服务暴露 /seata/branch/{branchId}/commit 和 /seata/branch/{branchId}/rollback 端点

注意：分布式模式(distributed)要启用完整的分布式事务功能，请：
1. 安装Seata Server（https://seata.io/zh-cn/docs/overview/what-is-seata.html）
2. 配置registry.conf和file.conf
3. 在启动时设置SEATA_ENABLED=true
"""
import logging
import time
import hashlib
import threading
import uuid
import json
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
        self._transaction_context = threading.local()
        self._seata_client_initialized = False
        self._initialized = True

        # HTTP-AT 模式：全局事务 -> 分支事务列表
        self._global_transactions: Dict[str, Dict] = {}
        self._branches: Dict[str, List[Dict]] = {}  # xid -> [branch]
        self._gt_lock = threading.Lock()

        # 分支事务回调注册（本地分支，用于同进程服务调用）
        self._branch_callbacks: Dict[str, Dict[str, Callable]] = {}
        self._cb_lock = threading.Lock()
        
        # 如果Seata可用且模式为分布式，尝试初始化
        if _seata_available and mode == "distributed" and application_id:
            self._init_seata_client()
    
    def _init_seata_client(self):
        """初始化Seata客户端"""
        try:
            # 设置Seata配置环境变量
            import os
            os.environ.setdefault('SEATA_IP', self.server_addr.split(':')[0])
            os.environ.setdefault('SEATA_PORT', self.server_addr.split(':')[1] if ':' in self.server_addr else '8091')
            os.environ.setdefault('SEATA_APPLICATION_ID', self.application_id)
            os.environ.setdefault('SEATA_TX_GROUP', self.transaction_group)
            
            logger.info(f"[Seata] Initializing Seata client with server: {self.server_addr}, application_id: {self.application_id}")
            
            # 尝试启动Seata代理（具体方式取决于Seata Python版本）
            try:
                # 方式1：尝试使用seata.init()
                if hasattr(seata, 'init'):
                    seata.init()
                
                # 方式2：尝试使用seata.config.init()
                elif hasattr(seata, 'config') and hasattr(seata.config, 'init'):
                    seata.config.init()
                
                self._seata_client_initialized = True
                logger.info(f"[Seata] Client initialized successfully in distributed mode")
            except Exception as init_e:
                logger.warning(f"[Seata] Failed to initialize client: {init_e}. Falling back to local mode.")
                self._seata_client_initialized = False
                self.mode = "local"
                
        except Exception as e:
            logger.warning(f"[Seata] Failed to initialize Seata client: {e}. Falling back to local transaction management.")
            self._seata_client_initialized = False
            self.mode = "local"
    
    def begin_transaction(self, timeout: int = 60000, name: str = "") -> str:
        """
        开启分布式事务
        
        支持三种模式：
        - local: 仅追踪事务上下文
        - http: HTTP-AT模式，生成本地XID，后续Feign调用自动传递，提交/回滚通过HTTP通知分支
        - distributed: 使用真实Seata Server
        
        Args:
            timeout: 事务超时时间（毫秒）
            name: 事务名称
        
        Returns:
            事务ID (XID)
        """
        # 检查是否已经在事务中
        if getattr(self._transaction_context, 'in_transaction', False):
            logger.warning("Nested transaction detected, returning current tx_id")
            return getattr(self._transaction_context, 'tx_id', "")
        
        # 生成事务ID
        tx_id = hashlib.md5(f"{time.time()}-{threading.current_thread().ident}-{uuid.uuid4().hex}".encode()).hexdigest()[:32]
        
        # 设置事务上下文
        self._transaction_context.in_transaction = True
        self._transaction_context.tx_id = tx_id
        self._transaction_context.status = "BEGIN"
        self._transaction_context.timeout = timeout
        self._transaction_context.start_time = time.time()
        self._transaction_context.name = name

        # HTTP-AT 模式：注册全局事务
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
        
        # 如果是分布式模式且Seata可用，尝试开启全局事务
        elif self.mode == "distributed" and _seata_available and self._seata_client_initialized:
            try:
                global_tx = GlobalTransaction.begin(timeout, name)
                seata_tx_id = RootContext.getXID()
                if seata_tx_id:
                    tx_id = seata_tx_id
                    self._transaction_context.tx_id = tx_id
                    logger.info(f"[Seata] Begin global transaction (distributed): {tx_id}")
                else:
                    logger.warning(f"[Seata] Global transaction started but XID not found, using local ID")
                return tx_id
            except Exception as e:
                logger.warning(f"[Seata] Failed to begin global transaction: {e}. Using local context.")
                self.mode = "local"
        
        else:
            logger.info(f"[Seata] Begin transaction (local context): {tx_id}")

        return tx_id

    def register_branch(self, xid: str, branch_id: str = "", resource_id: str = "",
                        callback_url: str = "", commit_cb: Callable = None,
                        rollback_cb: Callable = None, service_name: str = "") -> str:
        """
        注册分支事务（HTTP-AT模式）
        
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
        return True  # no callback: treat as success
    
    def commit_transaction(self, tx_id: str) -> bool:
        """
        提交分布式事务
        
        Args:
            tx_id: 事务ID
        
        Returns:
            是否成功
        """
        try:
            current_tx_id = getattr(self._transaction_context, 'tx_id', "")
            if current_tx_id and current_tx_id != tx_id:
                logger.error(f"Transaction mismatch: expected {tx_id}, got {current_tx_id}")
                return False
            
            start_time = getattr(self._transaction_context, 'start_time', 0)
            timeout = getattr(self._transaction_context, 'timeout', 60000)
            duration = (time.time() - start_time) * 1000
            
            if duration > timeout:
                logger.error(f"Transaction timeout: {duration}ms > {timeout}ms")
                self.rollback_transaction(tx_id)
                return False

            # HTTP-AT模式：通知所有分支提交
            if self.mode == "http":
                all_ok = True
                with self._gt_lock:
                    branches = list(self._branches.get(tx_id, []))
                    self._global_transactions[tx_id]['status'] = 'COMMITTING'
                for branch in branches:
                    ok = self._notify_branch(branch, 'commit')
                    branch['status'] = BranchStatus.COMMITTED if ok else BranchStatus.FAILED
                    if not ok:
                        all_ok = False
                with self._gt_lock:
                    self._global_transactions[tx_id]['status'] = 'COMMITTED' if all_ok else 'PARTIAL_COMMIT'
                logger.info(f"[Seata-HTTP] Commit transaction {tx_id[:16]}... branches={len(branches)} success={all_ok}")
                return all_ok
            
            # 分布式模式
            if self.mode == "distributed" and _seata_available and self._seata_client_initialized:
                try:
                    GlobalTransaction.commit()
                    self._transaction_context.status = "COMMITTED"
                    logger.info(f"[Seata] Commit global transaction: {tx_id}, duration={duration:.2f}ms")
                    return True
                except Exception as e:
                    logger.error(f"[Seata] Failed to commit global transaction: {e}. Rolling back...")
                    self.rollback_transaction(tx_id)
                    return False
            
            # 本地模式
            self._transaction_context.status = "COMMITTED"
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
            current_tx_id = getattr(self._transaction_context, 'tx_id', "")
            if current_tx_id and current_tx_id != tx_id:
                logger.error(f"Transaction mismatch: expected {tx_id}, got {current_tx_id}")
                return False

            # HTTP-AT模式：通知所有分支回滚
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
                logger.info(f"[Seata-HTTP] Rollback transaction {tx_id[:16]}... branches={len(branches)} success={all_ok}")
                return all_ok
            
            # 分布式模式
            if self.mode == "distributed" and _seata_available and self._seata_client_initialized:
                try:
                    GlobalTransaction.rollback()
                    self._transaction_context.status = "ROLLED_BACK"
                    logger.info(f"[Seata] Rollback global transaction: {tx_id}")
                    return True
                except Exception as e:
                    logger.error(f"[Seata] Failed to rollback global transaction: {e}")
            
            # 本地模式
            self._transaction_context.status = "ROLLED_BACK"
            logger.info(f"[Seata] Rollback transaction (local): {tx_id}")
            return True
        finally:
            self._cleanup_context()
    
    def _cleanup_context(self):
        """清理事务上下文"""
        self._transaction_context.in_transaction = False
        self._transaction_context.tx_id = None
        self._transaction_context.status = None
        self._transaction_context.timeout = None
        self._transaction_context.start_time = None
        self._transaction_context.name = None
        
        # 清理Seata上下文
        if _seata_available and RootContext:
            try:
                RootContext.unbindXID()
            except Exception:
                pass
    
    def is_in_transaction(self) -> bool:
        """检查是否在事务中"""
        return getattr(self._transaction_context, 'in_transaction', False)
    
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
        
        return getattr(self._transaction_context, 'tx_id', "")
    
    def get_transaction_status(self) -> str:
        """获取当前事务状态"""
        return getattr(self._transaction_context, 'status', "NONE")
    
    def get_mode(self) -> str:
        """获取当前事务模式"""
        return self.mode
    
    def set_mode(self, mode: str):
        """设置事务模式 (local/http/distributed)"""
        if mode not in ["local", "http", "distributed"]:
            raise ValueError("Mode must be 'local', 'http' or 'distributed'")
        
        self.mode = mode
        
        # 如果切换到分布式模式，尝试初始化Seata
        if mode == "distributed" and not self._seata_client_initialized:
            self._init_seata_client()

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
    global seata_manager
    seata_manager = SeataTransactionManager(
        server_addr=config.get('server_addr', 'localhost:8091'),
        application_id=config.get('application_id', ''),
        transaction_group=config.get('transaction_group', 'my_tx_group'),
        mode=config.get('mode', 'local')
    )