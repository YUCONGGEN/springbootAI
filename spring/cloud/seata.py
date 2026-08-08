"""
分布式事务模块
基于Seata实现分布式事务管理

注意：要启用完整的分布式事务功能，请：
1. 安装Seata Server（https://seata.io/zh-cn/docs/overview/what-is-seata.html）
2. 配置registry.conf和file.conf
3. 在启动时设置SEATA_ENABLED=true
4. 确保数据库中创建了seata_undo_log表

当前实现支持两种模式：
- 本地模式：仅追踪事务状态，不进行分布式协调（默认）
- 分布式模式：连接Seata Server进行真实的分布式事务协调
"""
import logging
import time
import hashlib
import threading
from typing import Dict, Any, Optional

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


class SeataTransactionManager:
    """Seata事务管理器（支持本地模式和分布式模式）"""
    
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
        self.mode = mode  # 'local' or 'distributed'
        self._transaction_context = threading.local()
        self._seata_client_initialized = False
        self._initialized = True
        
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
        
        如果模式为分布式且Seata Server可用，则使用Seata进行全局事务管理；
        否则使用本地事务上下文管理（仅追踪事务状态，不进行分布式协调）。
        
        Args:
            timeout: 事务超时时间（毫秒）
            name: 事务名称
        
        Returns:
            事务ID
        """
        # 检查是否已经在事务中
        if getattr(self._transaction_context, 'in_transaction', False):
            logger.warning("Nested transaction detected, returning current tx_id")
            return getattr(self._transaction_context, 'tx_id', "")
        
        # 生成事务ID
        tx_id = hashlib.md5(f"{time.time()}-{threading.current_thread().ident}".encode()).hexdigest()
        
        # 设置事务上下文
        self._transaction_context.in_transaction = True
        self._transaction_context.tx_id = tx_id
        self._transaction_context.status = "BEGIN"
        self._transaction_context.timeout = timeout
        self._transaction_context.start_time = time.time()
        self._transaction_context.name = name
        
        # 如果是分布式模式且Seata可用，尝试开启全局事务
        if self.mode == "distributed" and _seata_available and self._seata_client_initialized:
            try:
                # 使用Seata的GlobalTransaction开启全局事务
                global_tx = GlobalTransaction.begin(timeout, name)
                
                # 获取Seata的全局事务ID
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
        
        logger.info(f"[Seata] Begin transaction (local context): {tx_id}")
        return tx_id
    
    def commit_transaction(self, tx_id: str) -> bool:
        """
        提交分布式事务
        
        Args:
            tx_id: 事务ID
        
        Returns:
            是否成功
        """
        try:
            # 检查事务上下文
            current_tx_id = getattr(self._transaction_context, 'tx_id', "")
            if current_tx_id != tx_id:
                logger.error(f"Transaction mismatch: expected {tx_id}, got {current_tx_id}")
                return False
            
            # 检查超时
            start_time = getattr(self._transaction_context, 'start_time', 0)
            timeout = getattr(self._transaction_context, 'timeout', 60000)
            duration = (time.time() - start_time) * 1000
            
            if duration > timeout:
                logger.error(f"Transaction timeout: {duration}ms > {timeout}ms")
                self.rollback_transaction(tx_id)
                return False
            
            # 如果是分布式模式，使用Seata提交
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
            
            # 本地模式提交
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
            # 检查事务上下文
            current_tx_id = getattr(self._transaction_context, 'tx_id', "")
            if current_tx_id != tx_id:
                logger.error(f"Transaction mismatch: expected {tx_id}, got {current_tx_id}")
                return False
            
            # 如果是分布式模式，使用Seata回滚
            if self.mode == "distributed" and _seata_available and self._seata_client_initialized:
                try:
                    GlobalTransaction.rollback()
                    self._transaction_context.status = "ROLLED_BACK"
                    logger.info(f"[Seata] Rollback global transaction: {tx_id}")
                    return True
                except Exception as e:
                    logger.error(f"[Seata] Failed to rollback global transaction: {e}")
            
            # 本地模式回滚
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
        """设置事务模式"""
        if mode not in ["local", "distributed"]:
            raise ValueError("Mode must be 'local' or 'distributed'")
        
        self.mode = mode
        
        # 如果切换到分布式模式，尝试初始化Seata
        if mode == "distributed" and not self._seata_client_initialized:
            self._init_seata_client()


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