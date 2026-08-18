"""
分布式事务模块
通过官方 Java 客户端桥接真实 Apache Seata，并提供仅供开发验证的 HTTP 补偿协调器

支持四种模式：
- local: 本地模式，仅追踪事务状态（默认）
- http: 实验性 HTTP 补偿模式，不提供 AT 强一致性，禁止用于生产
- distributed: 真实 Seata Server + TCC 模式（需要官方 Java 客户端桥接服务）
- at: AT 模式，通过 ORM 拦截器自动记录 undo_log，回滚时自动反向恢复数据
      需配合 ``SeataATProxy.install()`` 使用，详见 ``springbootai.cloud.seata_at_proxy``

实验性 HTTP 补偿模式工作原理：
1. TM（事务发起方）开启全局事务，生成XID
2. Feign调用远程服务时，通过 X-TX-XID header 传递XID
3. RM（分支事务方）注册分支到TC（内嵌协调器）
4. TM 提交时通知所有分支提交；回滚时通知所有分支回滚
5. 分支服务暴露 /seata/branch/{branchId}/commit 和 /seata/branch/{branchId}/rollback 端点

distributed 模式不使用非官方 Python SDK。Python 通过受令牌保护的 HTTP
桥接服务调用 Apache Seata 官方 Java TM/RM 客户端；业务分支按 TCC 协议实现
prepare/commit/rollback 回调。
"""
import logging
import time
import threading
import uuid
import json
import os
import tempfile
from contextvars import ContextVar
from typing import Dict, Any, Optional, List, Callable
from urllib import parse as urlparse
from urllib import request as urlrequest
from springbootai.cloud.transaction_store import SQLiteTransactionStore
from springbootai.cloud.seata_bridge import SeataBridgeClient, SeataBridgeError

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
        self.bridge_url = os.getenv("SEATA_BRIDGE_URL", "http://localhost:18091")
        self.bridge_token = os.getenv("SEATA_BRIDGE_TOKEN", "")
        self.bridge_timeout_s = 5.0
        self.callback_allowed_hosts: tuple[str, ...] = ()
        self._bridge_client: Optional[SeataBridgeClient] = None
        self.mode = mode  # 'local', 'http', or 'distributed'
        self._transaction_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
            'springpy_seata_transaction_context', default=None
        )
        self._seata_client_initialized = False
        self._initialized = True
        self._transaction_store: Optional[SQLiteTransactionStore] = None
        self._transaction_store_path = ""
        self._recovery_grace_ms = 30000
        self._recovery_interval_s = 30.0
        self._recovery_stop = threading.Event()
        self._recovery_thread: Optional[threading.Thread] = None
        # 降级开关：distributed 模式下 bridge 不可达时是否降级为本地事务（默认 False=直接失败）
        self._fallback_to_local = False

        # HTTP compensation mode stores coordinator metadata durably.  Branch
        # callbacks still need callback_url to be recoverable after a restart.
        self._global_transactions: Dict[str, Dict] = {}
        self._branches: Dict[str, List[Dict]] = {}  # xid -> [branch]
        self._gt_lock = threading.Lock()

        # 分支事务回调注册（本地分支，用于同进程服务调用）
        self._branch_callbacks: Dict[str, Dict[str, Callable]] = {}
        self._cb_lock = threading.Lock()
        
        if mode == "distributed":
            self.set_mode(mode)

    def configure(
        self,
        server_addr: str = "localhost:8091",
        application_id: str = "",
        transaction_group: str = "my_tx_group",
        mode: str = "local",
        bridge_url: str = "http://localhost:18091",
        bridge_token: str = "",
        bridge_timeout_s: float = 5.0,
        store_path: Optional[str] = None,
        recovery_grace_ms: int = 30000,
        recovery_interval_s: float = 30.0,
        callback_allowed_hosts: Optional[List[str]] = None,
        fallback_to_local: bool = False,
    ) -> None:
        """重新配置单例；初始化入口不能依赖第二次构造调用。"""
        client_config_changed = (
            application_id != self.application_id
            or transaction_group != self.transaction_group
            or bridge_url.rstrip('/') != self.bridge_url.rstrip('/')
            or bridge_token != self.bridge_token
            or float(bridge_timeout_s) != self.bridge_timeout_s
        )
        self.server_addr = server_addr
        self.application_id = application_id
        self.transaction_group = transaction_group
        self.bridge_url = bridge_url
        self.bridge_token = bridge_token
        self.bridge_timeout_s = float(bridge_timeout_s)
        callback_hosts = (
            callback_allowed_hosts.split(",")
            if isinstance(callback_allowed_hosts, str)
            else (callback_allowed_hosts or ())
        )
        self.callback_allowed_hosts = tuple(
            str(host).strip().lower()
            for host in callback_hosts
            if str(host).strip()
        )
        if client_config_changed:
            self._bridge_client = None
            self._seata_client_initialized = False
        if store_path is not None:
            normalized_path = os.path.abspath(os.path.expanduser(store_path))
            if normalized_path != self._transaction_store_path:
                self._transaction_store = None
            self._transaction_store_path = normalized_path
        self._recovery_grace_ms = max(0, int(recovery_grace_ms))
        self._recovery_interval_s = max(0.0, float(recovery_interval_s))
        self._fallback_to_local = bool(fallback_to_local)
        self.set_mode(mode)

    def _validate_callback_url(self, callback_url: str) -> str:
        normalized = str(callback_url or "").strip().rstrip("/")
        parsed = urlparse.urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
            raise ValueError("Seata callback_url must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Seata callback_url must not contain credentials or a fragment")
        host = parsed.hostname.lower()
        allowed = any(
            host == pattern
            or (pattern.startswith("*.") and host.endswith(pattern[1:]))
            for pattern in self.callback_allowed_hosts
        )
        if not allowed:
            raise ValueError(f"Seata callback host is not allow-listed: {host}")
        return normalized

    def _ensure_transaction_store(self) -> SQLiteTransactionStore:
        if self._transaction_store is None:
            path = self._transaction_store_path or os.getenv(
                "SEATA_HTTP_STORE_PATH",
                os.path.join(tempfile.gettempdir(), "springpy-seata-http.sqlite3"),
            )
            self._transaction_store_path = path
            self._transaction_store = SQLiteTransactionStore(path)
        return self._transaction_store

    def _get_context(self) -> Dict[str, Any]:
        return self._transaction_context.get() or {}

    def _set_context(self, **values: Any) -> None:
        current = dict(self._get_context())
        current.update(values)
        self._transaction_context.set(current)
    
    def _init_seata_client(self):
        """连接官方 Java Seata bridge；分布式模式禁止静默降级。"""
        if not self.application_id:
            raise RuntimeError("seata.application_id is required in distributed mode")
        try:
            client = SeataBridgeClient(
                self.bridge_url,
                self.bridge_token,
                timeout_s=self.bridge_timeout_s,
            )
            health = client.health()
            if health.get('status') != 'UP':
                raise RuntimeError(f"Seata bridge is not ready: {health}")
            bridge_group = health.get('transactionGroup')
            if bridge_group and bridge_group != self.transaction_group:
                raise RuntimeError(
                    "Seata transaction group mismatch: "
                    f"client={self.transaction_group}, bridge={bridge_group}"
                )
            self._bridge_client = client
            self._seata_client_initialized = True
            logger.info(
                "[Seata] Official client bridge ready: bridge=%s server=%s application_id=%s",
                self.bridge_url,
                health.get('serverAddr', self.server_addr),
                self.application_id,
            )
        except Exception as e:
            self._bridge_client = None
            self._seata_client_initialized = False
            raise RuntimeError(f"failed to initialize distributed Seata client: {e}") from e

    def check_health(self) -> Dict[str, Any]:
        """Return live bridge and coordinator health for readiness checks."""
        if self.mode != "distributed" or self._bridge_client is None:
            return {"status": "DOWN", "reason": "distributed bridge is not initialized"}
        try:
            return self._bridge_client.health()
        except SeataBridgeError as exc:
            return {"status": "DOWN", "reason": str(exc)}
    
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

        # Durable HTTP compensation coordinator.  The local dictionaries are
        # only a hot cache for callbacks; recovery reads from the store.
        if self.mode == "http":
            store = self._ensure_transaction_store()
            start_time = time.time()
            try:
                store.create_transaction(
                    tx_id,
                    name=name,
                    status="BEGIN",
                    start_time=start_time,
                    timeout_ms=timeout,
                )
            except Exception:
                self._cleanup_context()
                raise
            with self._gt_lock:
                self._global_transactions[tx_id] = {
                    'xid': tx_id,
                    'name': name,
                    'status': 'BEGIN',
                    'start_time': start_time,
                    'timeout': timeout,
                }
                self._branches[tx_id] = []
            logger.info(f"[Seata-HTTP] Begin global transaction: {tx_id}")
        
        elif self.mode == "distributed":
            if not (self._bridge_client and self._seata_client_initialized):
                # bridge 未初始化：根据配置决定降级还是直接失败
                if self._fallback_to_local:
                    logger.warning(
                        "[Seata] distributed bridge not initialized, falling back to local transaction "
                        "(seata.fallback_to_local=True)"
                    )
                    # 降级为本地事务：上下文已设置，直接返回 tx_id
                    return tx_id
                self._cleanup_context()
                raise RuntimeError("distributed Seata client is not initialized")
            try:
                response = self._bridge_client.begin(
                    timeout_ms=timeout,
                    name=name or "springpy-global-transaction",
                    application_id=self.application_id,
                    transaction_group=self.transaction_group,
                )
                seata_tx_id = str(response.get('xid', ''))
                if not seata_tx_id:
                    raise RuntimeError("Seata transaction began without an XID")
                tx_id = seata_tx_id
                self._set_context(
                    tx_id=tx_id,
                    status=str(response.get('status', 'Begin')),
                )
                logger.info(f"[Seata] Begin global transaction (distributed): {tx_id}")
                return tx_id
            except Exception as e:
                if self._fallback_to_local:
                    logger.warning(
                        "[Seata] distributed begin failed (%s), falling back to local transaction "
                        "(seata.fallback_to_local=True)", e
                    )
                    # 上下文已设置（in_transaction=True, tx_id 已生成），直接降级返回
                    return tx_id
                self._cleanup_context()
                raise RuntimeError(f"failed to begin distributed Seata transaction: {e}") from e
        
        else:
            logger.info(f"[Seata] Begin transaction (local context): {tx_id}")

        return tx_id

    def restore_transaction_context(self, tx_id: str) -> bool:
        """Bind durable HTTP transaction metadata to the current async task."""
        context = self.get_transaction_context(tx_id)
        if context is None:
            return False
        self.bind_transaction_context(context)
        return True

    def bind_transaction_context(self, context: Dict[str, Any]) -> None:
        """Bind a previously read transaction context to the current task."""
        self._transaction_context.set(dict(context))

    def get_transaction_context(self, tx_id: str) -> Optional[Dict[str, Any]]:
        """Read a BEGIN transaction context without binding it to this task."""
        if self.mode != 'http':
            return None
        transaction = self._ensure_transaction_store().get_transaction(tx_id)
        if transaction is None or transaction['status'] != 'BEGIN':
            return None
        return {
            'in_transaction': True,
            'tx_id': tx_id,
            'status': transaction['status'],
            'timeout': transaction['timeout_ms'],
            'start_time': transaction['start_time'],
            'name': transaction['name'],
        }

    def register_branch(self, xid: str, branch_id: str = "", resource_id: str = "",
                        callback_url: str = "", commit_cb: Callable = None,
                        rollback_cb: Callable = None, service_name: str = "",
                        metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        注册分支事务。

        ``http`` 模式把回调写入本地补偿存储；``distributed`` 模式通过
        官方 Java RM 客户端向 Seata TC 注册真正的 TCC 分支，并立即执行
        ``callback_url/{branch_id}/prepare``。
        
        Args:
            xid: 全局事务ID
            branch_id: 分支ID（自动生成如果为空）
            resource_id: 资源标识（如数据库表名）
            callback_url: 远程回调URL（用于跨服务调用），如 http://order-service/seata/branch
            commit_cb: 本地提交回调函数
            rollback_cb: 本地回滚回调函数
            service_name: 服务名
            metadata: 传给三阶段回调的业务参数；不要放密钥或大对象

        Returns:
            branch_id
        """
        if not branch_id:
            branch_id = uuid.uuid4().hex[:16]

        if callback_url:
            callback_url = self._validate_callback_url(callback_url)

        if self.mode == 'http':
            transaction = self._ensure_transaction_store().get_transaction(xid)
            if transaction is None or transaction['status'] in {'COMMITTED', 'ROLLED_BACK'}:
                raise ValueError(f"Unknown or completed HTTP transaction: {xid}")

        if self.mode == 'distributed':
            if not (self._bridge_client and self._seata_client_initialized):
                raise RuntimeError("distributed Seata client is not initialized")
            if commit_cb or rollback_cb:
                raise ValueError(
                    "distributed TCC branches require durable callback_url endpoints; "
                    "process-local callbacks are not restart safe"
                )
            if not callback_url:
                raise ValueError("distributed TCC branches require callback_url")
            response = self._bridge_client.register_branch(
                xid,
                branch_id=branch_id,
                resource_id=resource_id,
                callback_url=callback_url,
                service_name=service_name or self.application_id,
                metadata=metadata,
            )
            returned_branch_id = str(response.get('branchId', ''))
            if returned_branch_id != branch_id:
                raise RuntimeError("Seata bridge returned a mismatched branch ID")

        branch = {
            'branch_id': branch_id,
            'xid': xid,
            'resource_id': resource_id,
            'callback_url': callback_url,
            'service_name': service_name or self.application_id,
            'status': BranchStatus.REGISTERED,
            'registered_at': time.time(),
            'metadata': metadata or {},
        }

        if self.mode == 'http':
            branch = self._ensure_transaction_store().register_branch(branch)

        with self._gt_lock:
            if xid not in self._branches:
                self._branches[xid] = []
            if not any(item['branch_id'] == branch_id for item in self._branches[xid]):
                self._branches[xid].append(branch)

        # 注册本地回调
        if commit_cb or rollback_cb:
            with self._cb_lock:
                self._branch_callbacks[branch_id] = {
                    'commit': commit_cb,
                    'rollback': rollback_cb,
                }

        logger.info(
            "[Seata-%s] Branch registered: xid=%s... branch_id=%s... service=%s url=%s",
            "TCC" if self.mode == "distributed" else "HTTP",
            xid[:16],
            branch_id[:16],
            service_name,
            callback_url,
        )
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
                url = self._validate_callback_url(url)
                full_url = f"{url.rstrip('/')}/{branch_id}/{action}"
                req = urlrequest.Request(full_url, method='POST',
                                         data=json.dumps({'xid': branch['xid'], 'branchId': branch_id}).encode(),
                                         headers={'Content-Type': 'application/json'})
                with urlrequest.urlopen(req, timeout=5) as resp:  # nosec B310 - URL is validated above
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

            store = None
            stored_transaction = None
            if self.mode == "http":
                store = self._ensure_transaction_store()
                stored_transaction = store.get_transaction(tx_id)
                if stored_transaction is None:
                    logger.error(f"[Seata-HTTP] Unknown transaction: {tx_id}")
                    return False
                if stored_transaction['status'] == 'COMMITTED':
                    return True
                if stored_transaction['status'] in {'ROLLED_BACK', 'ROLLING_BACK'}:
                    logger.error(
                        f"[Seata-HTTP] Cannot commit transaction in "
                        f"{stored_transaction['status']}"
                    )
                    return False

            start_time = context.get('start_time', 0)
            timeout = context.get('timeout', 60000)
            if stored_transaction is not None and not start_time:
                start_time = stored_transaction['start_time']
                timeout = stored_transaction['timeout_ms']
            duration = (time.time() - start_time) * 1000
            
            recovering_commit = (
                stored_transaction is not None
                and stored_transaction['status'] in {'COMMITTING', 'PARTIAL_COMMIT'}
            )
            if duration > timeout and not recovering_commit:
                logger.error(f"Transaction timeout: {duration}ms > {timeout}ms")
                self.rollback_transaction(tx_id)
                return False

            # Durable HTTP compensation mode: atomically claim the global
            # transaction and persist every branch outcome for retry/recovery.
            if self.mode == "http":
                assert store is not None
                if not store.transition_transaction(
                    tx_id,
                    'COMMITTING',
                    {'BEGIN', 'PARTIAL_COMMIT'},
                ):
                    logger.error(
                        f"[Seata-HTTP] Transaction {tx_id} is already being completed"
                    )
                    return False
                all_ok = True
                branches = store.list_branches(tx_id)
                for branch in branches:
                    if branch['status'] == BranchStatus.COMMITTED:
                        continue
                    ok = self._notify_branch(branch, 'commit')
                    status = BranchStatus.COMMITTED if ok else BranchStatus.FAILED
                    store.update_branch(
                        branch['branch_id'],
                        status,
                        "" if ok else "commit callback failed",
                    )
                    store.touch_transaction(tx_id, 'COMMITTING')
                    if not ok:
                        all_ok = False
                final_status = 'COMMITTED' if all_ok else 'PARTIAL_COMMIT'
                store.update_transaction(tx_id, final_status)
                with self._gt_lock:
                    if tx_id in self._global_transactions:
                        self._global_transactions[tx_id]['status'] = final_status
                if all_ok:
                    self._cleanup_http_transaction(tx_id)
                logger.info(f"[Seata-HTTP] Commit transaction {tx_id[:16]}... branches={len(branches)} success={all_ok}")
                return all_ok
            
            # 分布式模式
            if self.mode == "distributed":
                if not (self._bridge_client and self._seata_client_initialized):
                    logger.error("Distributed Seata client is not initialized; commit rejected")
                    return False
                try:
                    response = self._bridge_client.commit(tx_id)
                    if not response.get('success', False):
                        raise SeataBridgeError(f"commit rejected: {response}")
                    self._set_context(status=str(response.get('status', 'Committed')))
                    logger.info(f"[Seata] Commit global transaction: {tx_id}, duration={duration:.2f}ms")
                    return True
                except Exception as e:
                    logger.error(f"[Seata] Failed to commit global transaction: {e}")
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

            # Durable HTTP compensation mode: rollback is idempotent and each
            # branch result remains available after process restarts.
            if self.mode == "http":
                store = self._ensure_transaction_store()
                transaction = store.get_transaction(tx_id)
                if transaction is None:
                    logger.error(f"[Seata-HTTP] Unknown transaction: {tx_id}")
                    return False
                if transaction['status'] == 'ROLLED_BACK':
                    return True
                if transaction['status'] in {'COMMITTED', 'COMMITTING'}:
                    logger.error(f"[Seata-HTTP] Cannot roll back transaction in {transaction['status']}")
                    return False
                if not store.transition_transaction(
                    tx_id,
                    'ROLLING_BACK',
                    {'BEGIN', 'PARTIAL_ROLLBACK'},
                ):
                    logger.error(
                        f"[Seata-HTTP] Transaction {tx_id} is already being completed"
                    )
                    return False
                all_ok = True
                branches = store.list_branches(tx_id)
                for branch in branches:
                    if branch['status'] == BranchStatus.ROLLED_BACK:
                        continue
                    ok = self._notify_branch(branch, 'rollback')
                    status = BranchStatus.ROLLED_BACK if ok else BranchStatus.FAILED
                    store.update_branch(
                        branch['branch_id'],
                        status,
                        "" if ok else "rollback callback failed",
                    )
                    store.touch_transaction(tx_id, 'ROLLING_BACK')
                    if not ok:
                        all_ok = False
                final_status = 'ROLLED_BACK' if all_ok else 'PARTIAL_ROLLBACK'
                store.update_transaction(tx_id, final_status)
                with self._gt_lock:
                    if tx_id in self._global_transactions:
                        self._global_transactions[tx_id]['status'] = final_status
                if all_ok:
                    self._cleanup_http_transaction(tx_id)
                logger.info(f"[Seata-HTTP] Rollback transaction {tx_id[:16]}... branches={len(branches)} success={all_ok}")
                return all_ok
            
            # 分布式模式
            if self.mode == "distributed":
                if not (self._bridge_client and self._seata_client_initialized):
                    logger.error("Distributed Seata client is not initialized; rollback failed")
                    return False
                try:
                    response = self._bridge_client.rollback(tx_id)
                    if not response.get('success', False):
                        raise SeataBridgeError(f"rollback rejected: {response}")
                    self._set_context(status=str(response.get('status', 'Rollbacked')))
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

    def _cleanup_http_transaction(self, tx_id: str) -> None:
        """Drop process-local callback caches; durable audit state remains stored."""
        with self._gt_lock:
            branches = self._branches.pop(tx_id, [])
            self._global_transactions.pop(tx_id, None)
        with self._cb_lock:
            for branch in branches:
                self._branch_callbacks.pop(branch['branch_id'], None)

    def recover_pending_transactions(self) -> Dict[str, List[str]]:
        """Retry durable HTTP transactions left incomplete by a worker crash.

        A recorded commit/rollback intent is resumed.  A BEGIN transaction is
        rolled back only after its timeout.  Branches that relied solely on a
        process-local callback fail closed and remain PARTIAL_* for operators or
        a later retry; callback URLs remain fully recoverable.
        """
        if self.mode != "http":
            return {"committed": [], "rolled_back": [], "pending": []}

        store = self._ensure_transaction_store()
        transactions = store.list_transactions({
            'BEGIN', 'COMMITTING', 'ROLLING_BACK',
            'PARTIAL_COMMIT', 'PARTIAL_ROLLBACK',
        })
        result = {"committed": [], "rolled_back": [], "pending": []}
        now = time.time()
        for transaction in transactions:
            xid = transaction['xid']
            status = transaction['status']
            if status == 'COMMITTING':
                cutoff = now - self._recovery_grace_ms / 1000
                if not store.reclaim_stale_transaction(
                    xid, 'COMMITTING', 'PARTIAL_COMMIT', cutoff
                ):
                    result['pending'].append(xid)
                    continue
                status = 'PARTIAL_COMMIT'
            elif status == 'ROLLING_BACK':
                cutoff = now - self._recovery_grace_ms / 1000
                if not store.reclaim_stale_transaction(
                    xid, 'ROLLING_BACK', 'PARTIAL_ROLLBACK', cutoff
                ):
                    result['pending'].append(xid)
                    continue
                status = 'PARTIAL_ROLLBACK'

            if status == 'PARTIAL_COMMIT':
                if self.commit_transaction(xid):
                    result['committed'].append(xid)
                else:
                    result['pending'].append(xid)
                continue
            if status == 'PARTIAL_ROLLBACK':
                if self.rollback_transaction(xid):
                    result['rolled_back'].append(xid)
                else:
                    result['pending'].append(xid)
                continue

            elapsed_ms = (now - transaction['start_time']) * 1000
            if elapsed_ms >= transaction['timeout_ms']:
                if self.rollback_transaction(xid):
                    result['rolled_back'].append(xid)
                else:
                    result['pending'].append(xid)
            else:
                result['pending'].append(xid)
        return result

    def start_recovery_worker(self) -> None:
        """Start restart-safe recovery after the ASGI worker has forked."""
        if self.mode != 'http' or self._recovery_interval_s <= 0:
            return
        if self._recovery_thread and self._recovery_thread.is_alive():
            return
        self._recovery_stop.clear()

        def run() -> None:
            while not self._recovery_stop.wait(self._recovery_interval_s):
                try:
                    self.recover_pending_transactions()
                except Exception:
                    logger.exception("[Seata-HTTP] Recovery worker failed")

        self._recovery_thread = threading.Thread(
            target=run,
            name="springpy-seata-http-recovery",
            daemon=True,
        )
        self._recovery_thread.start()

    def stop_recovery_worker(self) -> None:
        """Stop the worker-owned recovery loop during ASGI shutdown."""
        thread = self._recovery_thread
        if thread is None:
            return
        self._recovery_stop.set()
        if thread is not threading.current_thread():
            thread.join(timeout=5)
        self._recovery_thread = None

    def get_stored_transaction(self, tx_id: str) -> Optional[Dict[str, Any]]:
        """Return durable global and branch state for monitoring or repair tooling."""
        if self.mode != "http":
            return None
        store = self._ensure_transaction_store()
        transaction = store.get_transaction(tx_id)
        if transaction is not None:
            transaction['branches'] = store.list_branches(tx_id)
        return transaction
    
    def is_in_transaction(self) -> bool:
        """检查是否在事务中"""
        return bool(self._get_context().get('in_transaction', False))
    
    def get_current_tx_id(self) -> str:
        """获取当前事务ID"""
        return self._get_context().get('tx_id', "")
    
    def get_transaction_status(self) -> str:
        """获取当前事务状态"""
        return self._get_context().get('status', "NONE")
    
    def get_mode(self) -> str:
        """获取当前事务模式"""
        return self.mode
    
    def set_mode(self, mode: str):
        """设置事务模式 (local/http/distributed)"""
        if mode not in ["local", "http", "distributed", "at"]:
            raise ValueError("Mode must be 'local', 'http', 'distributed' or 'at'")

        if mode != 'http':
            self.stop_recovery_worker()

        if mode == "http":
            self._ensure_transaction_store()
        
        if mode == "distributed":
            # 即使初始化失败也保持 distributed，后续事务必须失败关闭，
            # 不能沿用之前的 local 模式继续执行核心业务。
            self.mode = mode
            if not self._seata_client_initialized or self._bridge_client is None:
                self._init_seata_client()
            return
        self.mode = mode

    def get_transaction_info(self) -> Dict[str, Any]:
        """获取当前事务信息（用于调试/监控）"""
        if self.mode == "http":
            counts = self._ensure_transaction_store().active_counts()
        else:
            with self._gt_lock:
                counts = {
                    'active_global_tx': len(self._global_transactions),
                    'active_branches': sum(len(b) for b in self._branches.values()),
                }
        return {
            'mode': self.mode,
            **counts,
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
        server_addr: Seata Server 地址，仅用于状态展示，默认 localhost:8091
        application_id: Python 业务应用 ID，分布式模式必填
        transaction_group: 事务分组，必须与 bridge 一致
        mode: local、http 或 distributed
        bridge_url: 官方 Java 客户端桥接地址，默认 http://localhost:18091
        bridge_token: 调用 bridge 的共享令牌，分布式模式必填
        bridge_timeout_s: bridge HTTP 请求超时秒数
    
    分布式模式要求：
        1. 部署 Seata Server 和 deploy/seata-bridge
        2. 创建官方 ``tcc_fence_log`` 表
        3. 每个业务分支暴露幂等的 prepare/commit/rollback 回调
        4. 用 callback host allow-list 和 bridge token 限制内部调用
    """
    mode = str(config.get('mode', 'local')).lower()
    http_enabled = (
        config.get('http_compensation_enabled', False)
        or config.get('experimental_http_enabled', False)
    )
    if mode == 'http' and not http_enabled:
        raise ValueError(
            "seata.mode=http requires explicit compensation-mode opt-in; "
            "set seata.http_compensation_enabled=true"
        )
    seata_manager.configure(
        server_addr=config.get('server_addr', 'localhost:8091'),
        application_id=config.get('application_id', ''),
        transaction_group=config.get('transaction_group', 'my_tx_group'),
        mode=mode,
        bridge_url=config.get('bridge_url', config.get('bridge-url', 'http://localhost:18091')),
        bridge_token=config.get('bridge_token', config.get('bridge-token', '')),
        bridge_timeout_s=config.get('bridge_timeout_s', config.get('bridge-timeout-s', 5.0)),
        store_path=config.get('store_path') or config.get('store-path'),
        recovery_grace_ms=config.get('recovery_grace_ms', config.get('recovery-grace-ms', 30000)),
        recovery_interval_s=config.get('recovery_interval_s', config.get('recovery-interval-s', 30.0)),
        callback_allowed_hosts=config.get(
            'callback_allowed_hosts', config.get('callback-allowed-hosts', [])
        ),
    )
    if mode == 'http' and config.get('recover_on_startup', True):
        recovery = seata_manager.recover_pending_transactions()
        if recovery['committed'] or recovery['rolled_back'] or recovery['pending']:
            logger.info("[Seata-HTTP] Startup recovery result: %s", recovery)
