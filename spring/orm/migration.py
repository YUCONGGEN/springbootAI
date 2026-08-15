"""
数据库迁移管理器 (Database Migration Manager)

类 Flyway 风格的轻量数据库迁移工具：
- 基于 SQL 文件版本号管理
- 自动追踪已执行迁移（schema_version 表）
- 支持 checksum 校验防止篡改
- 支持 MySQL/PostgreSQL/SQLite
- 迁移文件命名: V{version}__{description}.sql
- 支持 Undo 回滚迁移: U{version}__{description}.sql
- 支持迁移锁防止并发执行
- 支持变量替换 ${var_name}
"""

import re
import hashlib
import logging
import time
import threading
from typing import List, Dict, Tuple, Optional
from pathlib import Path

logger = logging.getLogger("Spring.ORM.Migration")

# 迁移文件命名模式: V1__init.sql, V2__add_users_table.sql
_MIGRATION_PATTERN = re.compile(r'^V(\d+(?:\.\d+)?)__(.+)\.sql$', re.IGNORECASE)
# Undo 迁移文件命名模式: U1__rollback_init.sql
_UNDO_PATTERN = re.compile(r'^U(\d+(?:\.\d+)?)__(.+)\.sql$', re.IGNORECASE)
# 版本号分隔符
_VERSION_SPLIT = re.compile(r'[._]')
# 变量替换模式: ${var_name}
_VAR_PATTERN = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')


class MigrationError(Exception):
    """迁移执行错误"""
    pass


class MigrationState:
    """迁移状态"""
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class MigrationRecord:
    """单条迁移记录"""
    __slots__ = ('version', 'description', 'script', 'checksum',
                 'installed_on', 'execution_time', 'success')

    def __init__(self, version: str, description: str, script: str,
                 checksum: str, execution_time: float = 0.0,
                 success: bool = True):
        self.version = version
        self.description = description
        self.script = script
        self.checksum = checksum
        self.installed_on = time.time()
        self.execution_time = execution_time
        self.success = success


class MigrationManager:
    """
    数据库迁移管理器

    Usage:
        manager = MigrationManager(connection_pool, migrations_dir="sql/migrations")
        manager.migrate()  # 执行所有待执行迁移
        manager.rollback("2")  # 回滚到 V2 之前（执行 U2）
        manager.validate()  # 仅校验不执行
    """

    def __init__(self, connection_pool, migrations_dir: str,
                 dialect: str = "mysql", table_name: str = "schema_version",
                 variables: Optional[Dict[str, str]] = None):
        self.pool = connection_pool
        self.migrations_dir = Path(migrations_dir)
        self.dialect = dialect.lower()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", str(table_name)):
            raise ValueError("migration table_name must be a simple SQL identifier")
        self.table_name = str(table_name)
        # 变量替换字典（用于 ${var_name} 替换）
        self.variables: Dict[str, str] = variables or {}
        # 进程级迁移锁（防止同一进程并发迁移）
        self._lock = threading.Lock()
        self._ensure_version_table()

    def _ensure_version_table(self) -> None:
        """确保 schema_version 表存在"""
        ddl_map = {
            'mysql': f"""
                CREATE TABLE IF NOT EXISTS `{self.table_name}` (
                    `version` VARCHAR(50) NOT NULL PRIMARY KEY,
                    `description` VARCHAR(200) NOT NULL,
                    `script` VARCHAR(500) NOT NULL,
                    `checksum` VARCHAR(64) NOT NULL,
                    `installed_on` BIGINT NOT NULL,
                    `execution_time` INT NOT NULL,
                    `success` TINYINT(1) NOT NULL DEFAULT 1
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            'postgresql': f"""
                CREATE TABLE IF NOT EXISTS "{self.table_name}" (
                    "version" VARCHAR(50) PRIMARY KEY,
                    "description" VARCHAR(200) NOT NULL,
                    "script" VARCHAR(500) NOT NULL,
                    "checksum" VARCHAR(64) NOT NULL,
                    "installed_on" BIGINT NOT NULL,
                    "execution_time" INTEGER NOT NULL,
                    "success" BOOLEAN NOT NULL DEFAULT TRUE
                )
            """,
            'sqlite': f"""
                CREATE TABLE IF NOT EXISTS "{self.table_name}" (
                    "version" TEXT PRIMARY KEY,
                    "description" TEXT NOT NULL,
                    "script" TEXT NOT NULL,
                    "checksum" TEXT NOT NULL,
                    "installed_on" INTEGER NOT NULL,
                    "execution_time" INTEGER NOT NULL,
                    "success" INTEGER NOT NULL DEFAULT 1
                )
            """,
        }

        ddl = ddl_map.get(self.dialect)
        if not ddl:
            logger.warning(f"Migration: dialect '{self.dialect}' not officially supported, trying generic")
            ddl = ddl_map['mysql']

        conn = None
        try:
            pooled = self.pool.get_connection()
            conn = pooled.connection
            cursor = conn.cursor()
            for stmt in ddl.split(';'):
                stmt = stmt.strip()
                if stmt:
                    cursor.execute(stmt)
            conn.commit()
            cursor.close()
            self.pool.return_connection(pooled)
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise MigrationError(f"Failed to create version table: {e}") from e

    def _get_applied_versions(self) -> Dict[str, MigrationRecord]:
        """获取已执行的迁移版本"""
        conn = None
        try:
            pooled = self.pool.get_connection()
            conn = pooled.connection
            cursor = conn.cursor()
            if self.dialect == 'mysql':
                cursor.execute(f"SELECT version, description, script, checksum, installed_on, execution_time, success FROM `{self.table_name}` WHERE success = 1")  # nosec B608
            else:
                cursor.execute(f'SELECT version, description, script, checksum, installed_on, execution_time, success FROM "{self.table_name}" WHERE success = 1')  # nosec B608

            applied = {}
            for row in cursor.fetchall():
                if isinstance(row, dict):
                    rec = MigrationRecord(
                        version=str(row['version']),
                        description=row['description'],
                        script=row['script'],
                        checksum=row['checksum'],
                        execution_time=row.get('execution_time', 0),
                        success=bool(row.get('success', True))
                    )
                else:
                    rec = MigrationRecord(
                        version=str(row[0]),
                        description=row[1],
                        script=row[2],
                        checksum=row[3],
                        execution_time=row[4] if len(row) > 4 else 0,
                        success=bool(row[6]) if len(row) > 6 else True
                    )
                applied[rec.version] = rec
            cursor.close()
            self.pool.return_connection(pooled)
            return applied
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise MigrationError(f"Failed to read applied versions: {e}") from e

    def _discover_migrations(self) -> List[Tuple[str, str, str, str]]:
        """发现迁移文件，返回 [(version, description, filename, content_checksum)]"""
        if not self.migrations_dir.exists():
            logger.warning(f"Migration directory not found: {self.migrations_dir}")
            return []

        migrations = []
        for f in sorted(self.migrations_dir.iterdir()):
            if not f.is_file():
                continue
            match = _MIGRATION_PATTERN.match(f.name)
            if not match:
                continue
            version = match.group(1)
            description = match.group(2).replace('_', ' ')
            content = f.read_text(encoding='utf-8')
            checksum = hashlib.sha256(content.encode('utf-8')).hexdigest()[:63]
            migrations.append((version, description, f.name, content, checksum))

        # 按版本号排序
        def _version_key(item):
            parts = []
            for p in _VERSION_SPLIT.split(item[0]):
                try:
                    parts.append((0, int(p)))
                except ValueError:
                    parts.append((1, p))
            return parts

        migrations.sort(key=_version_key)
        return [(m[0], m[1], m[2], m[4]) for m in migrations]

    def _version_tuple(self, version: str) -> tuple:
        """版本号转可比较tuple"""
        parts = []
        for p in _VERSION_SPLIT.split(version):
            try:
                parts.append(int(p))
            except ValueError:
                parts.append(p)
        return tuple(parts)

    def _execute_migration(self, version: str, description: str,
                           script_name: str, sql_content: str,
                           checksum: str) -> MigrationRecord:
        """执行单条迁移"""
        conn = None
        start = time.monotonic()
        try:
            pooled = self.pool.get_connection()
            conn = pooled.connection
            cursor = conn.cursor()

            # 变量替换
            sql_content = self._substitute_variables(sql_content)

            # 按分号分割语句
            statements = self._split_sql_statements(sql_content)

            for stmt in statements:
                stmt = stmt.strip()
                if stmt:
                    logger.debug(f"Executing migration SQL: {stmt[:100]}...")
                    cursor.execute(stmt)

            elapsed = time.monotonic() - start

            # 记录迁移
            if self.dialect == 'mysql':
                cursor.execute(
                    f"INSERT INTO `{self.table_name}` (version, description, script, checksum, installed_on, execution_time, success) VALUES (%s, %s, %s, %s, %s, %s, %s)",  # nosec B608
                    (version, description, script_name, checksum, int(time.time()), int(elapsed * 1000), 1)
                )
            else:
                ph = '?' if self.dialect == 'sqlite' else '%s'
                table_ref = f'"{self.table_name}"'
                cursor.execute(
                    f'INSERT INTO {table_ref} (version, description, script, checksum, installed_on, execution_time, success) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})',  # nosec B608
                    (version, description, script_name, checksum, int(time.time()), int(elapsed * 1000), 1)
                )

            conn.commit()
            cursor.close()
            self.pool.return_connection(pooled)

            record = MigrationRecord(version, description, script_name, checksum, elapsed, True)
            logger.info(f"Migration V{version} ({description}) applied successfully in {elapsed:.2f}s")
            return record

        except Exception as e:
            elapsed = time.monotonic() - start
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.error(f"Migration V{version} failed after {elapsed:.2f}s: {e}")
            raise MigrationError(f"Migration V{version} ({description}) failed: {e}") from e

    def migrate(self, baseline: bool = False) -> List[MigrationRecord]:
        """
        执行所有待执行的迁移

        Args:
            baseline: 如果为True，将现有数据库标记为已完成初始迁移（用于在已有数据库上启用迁移）

        Returns:
            本次执行的迁移记录列表
        """
        applied = self._get_applied_versions()
        discovered = self._discover_migrations()

        if not discovered:
            logger.info("No migration files found")
            return []

        # 校验已执行迁移的checksum
        for version, rec in applied.items():
            for disc_ver, desc, script, checksum in discovered:
                if disc_ver == version and rec.checksum != checksum:
                    raise MigrationError(
                        f"Checksum mismatch for migration V{version}! "
                        f"Applied checksum={rec.checksum}, current={checksum}. "
                        f"Migration files must not be modified after application."
                    )

        executed = []
        for version, description, script, checksum in discovered:
            if version in applied:
                continue

            if baseline and not executed:
                # baseline模式：将第一条之前的视为已baseline
                logger.info(f"Baseline: marking migrations up to V{version} as applied")
                baseline_conn = None
                try:
                    pooled = self.pool.get_connection()
                    baseline_conn = pooled.connection
                    cursor = baseline_conn.cursor()
                    if self.dialect == 'mysql':
                        cursor.execute(
                            f"INSERT IGNORE INTO `{self.table_name}` (version, description, script, checksum, installed_on, execution_time, success) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                            (version, description, script, checksum, int(time.time()), 0, 1)
                        )
                    else:
                        ph = '?' if self.dialect == 'sqlite' else '%s'
                        cursor.execute(
                            f'INSERT INTO "{self.table_name}" (version, description, script, checksum, installed_on, execution_time, success) SELECT {ph},{ph},{ph},{ph},{ph},{ph},{ph} WHERE NOT EXISTS (SELECT 1 FROM "{self.table_name}" WHERE version = {ph})',  # nosec B608
                            (version, description, script, checksum, int(time.time()), 0, 1, version)
                        )
                    baseline_conn.commit()
                    cursor.close()
                    self.pool.return_connection(pooled)
                except Exception:
                    if baseline_conn:
                        try:
                            baseline_conn.rollback()
                        except Exception:
                            pass
                baseline = False
                continue

            record = self._execute_migration(version, description, script, self._read_sql(script), checksum)
            executed.append(record)

        if not executed:
            logger.info(f"All {len(applied)} migrations are up to date")
        else:
            logger.info(f"Applied {len(executed)} new migration(s)")

        return executed

    def _read_sql(self, script_name: str) -> str:
        """读取SQL文件内容"""
        path = self.migrations_dir / script_name
        return path.read_text(encoding='utf-8')

    def status(self) -> Dict:
        """获取迁移状态"""
        applied = self._get_applied_versions()
        discovered = self._discover_migrations()

        migrations = []
        for version, description, script, checksum in discovered:
            state = MigrationState.SUCCESS if version in applied else MigrationState.PENDING
            if version in applied and applied[version].checksum != checksum:
                state = "CHECKSUM_MISMATCH"
            migrations.append({
                'version': version,
                'description': description,
                'script': script,
                'state': state,
            })

        pending = [m for m in migrations if m['state'] == MigrationState.PENDING]
        return {
            'total': len(migrations),
            'applied': len(applied),
            'pending': len(pending),
            'migrations': migrations,
        }

    def repair(self) -> int:
        """修复失败的迁移记录（标记为可重试）"""
        conn = None
        try:
            pooled = self.pool.get_connection()
            conn = pooled.connection
            cursor = conn.cursor()
            if self.dialect == 'mysql':
                cursor.execute(f"DELETE FROM `{self.table_name}` WHERE success = 0")  # nosec B608
            else:
                cursor.execute(f'DELETE FROM "{self.table_name}" WHERE success = 0')  # nosec B608
            deleted = cursor.rowcount
            conn.commit()
            cursor.close()
            self.pool.return_connection(pooled)
            logger.info(f"Repaired {deleted} failed migration record(s)")
            return deleted
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise MigrationError(f"Repair failed: {e}") from e

    # ==================== 变量替换 ====================

    def _substitute_variables(self, sql: str) -> str:
        """替换 SQL 中的 ${var_name} 变量。

        安全说明：变量值仅做字符串替换，不执行 SQL 解析。
        变量值不能包含分号（;），防止 SQL 注入。
        """
        if not self.variables:
            return sql

        def _replacer(match):
            var_name = match.group(1)
            if var_name not in self.variables:
                raise MigrationError(f"Undefined migration variable: ${{{var_name}}}")
            value = str(self.variables[var_name])
            # 防止 SQL 注入：变量值不能包含分号
            if ';' in value:
                raise MigrationError(
                    f"Migration variable '{var_name}' contains semicolon ';', "
                    f"which is not allowed for security reasons"
                )
            return value

        return _VAR_PATTERN.sub(_replacer, sql)

    # ==================== 迁移锁 ====================

    def _acquire_db_lock(self, conn) -> bool:
        """获取数据库级迁移锁（防止多实例并发迁移）。

        MySQL: GET_LOCK('migration_lock', 10)
        PostgreSQL: pg_advisory_lock(123456)
        SQLite: 使用进程级锁（SQLite 单写入者）
        """
        if self.dialect == 'mysql':
            cursor = conn.cursor()
            cursor.execute("SELECT GET_LOCK('springbootai_migration', 10)")  # nosec B608
            result = cursor.fetchone()
            return bool(result[0] if result and isinstance(result, (tuple, list)) else result)
        elif self.dialect == 'postgresql':
            cursor = conn.cursor()
            cursor.execute("SELECT pg_advisory_lock(123456789)")  # nosec B608
            return True
        else:
            # SQLite 使用进程级锁
            return self._lock.acquire(timeout=30)

    def _release_db_lock(self, conn) -> None:
        """释放数据库级迁移锁。"""
        if self.dialect == 'mysql':
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT RELEASE_LOCK('springbootai_migration')")  # nosec B608
                cursor.close()
            except Exception:
                pass
        elif self.dialect == 'postgresql':
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT pg_advisory_unlock(123456789)")  # nosec B608
                cursor.close()
            except Exception:
                pass
        else:
            # SQLite 进程级锁
            try:
                self._lock.release()
            except RuntimeError:
                pass  # 锁已被释放

    # ==================== Undo 回滚迁移 ====================

    def _discover_undo_migrations(self) -> Dict[str, Tuple[str, str, str]]:
        """发现 Undo 迁移文件，返回 {version: (description, filename, content)}"""
        if not self.migrations_dir.exists():
            return {}

        undos = {}
        for f in sorted(self.migrations_dir.iterdir()):
            if not f.is_file():
                continue
            match = _UNDO_PATTERN.match(f.name)
            if not match:
                continue
            version = match.group(1)
            description = match.group(2).replace('_', ' ')
            undos[version] = (description, f.name, f.read_text(encoding='utf-8'))
        return undos

    def rollback(self, target_version: str = None) -> List[MigrationRecord]:
        """回滚迁移（执行 Undo 脚本）。

        Args:
            target_version: 回滚到指定版本（不包含该版本）。
                           如 rollback("3") 会执行 U3、U2（回滚到 V1 状态）。
                           如果为 None，则只回滚最后一个版本。

        Returns:
            本次回滚的迁移记录列表

        注意：Undo 脚本文件命名为 U{version}__{description}.sql，
              与正向迁移 V{version}__{description}.sql 一一对应。
        """
        applied = self._get_applied_versions()
        if not applied:
            logger.info("No migrations to rollback")
            return []

        undo_scripts = self._discover_undo_migrations()

        # 按版本号降序排列已应用的迁移
        sorted_versions = sorted(applied.keys(), key=self._version_tuple, reverse=True)

        # 确定回滚范围
        if target_version:
            target_tuple = self._version_tuple(target_version)
            to_rollback = [v for v in sorted_versions if self._version_tuple(v) > target_tuple]
        else:
            to_rollback = [sorted_versions[0]]  # 只回滚最后一个

        if not to_rollback:
            logger.info("No migrations to rollback")
            return []

        rolled_back = []
        conn = None
        try:
            pooled = self.pool.get_connection()
            conn = pooled.connection

            # 获取迁移锁
            if not self._acquire_db_lock(conn):
                raise MigrationError("Failed to acquire migration lock (another migration may be running)")

            try:
                for version in to_rollback:
                    if version not in undo_scripts:
                        raise MigrationError(
                            f"Undo script U{version}__*.sql not found. "
                            f"Cannot rollback migration V{version} without undo script."
                        )

                    desc, script_name, sql_content = undo_scripts[version]
                    # 变量替换
                    sql_content = self._substitute_variables(sql_content)

                    start = time.monotonic()
                    cursor = conn.cursor()

                    # 执行 Undo SQL
                    statements = self._split_sql_statements(sql_content)
                    for stmt in statements:
                        stmt = stmt.strip()
                        if stmt:
                            logger.debug(f"Executing undo SQL: {stmt[:100]}...")
                            cursor.execute(stmt)

                    # 删除迁移记录
                    if self.dialect == 'mysql':
                        cursor.execute(
                            f"DELETE FROM `{self.table_name}` WHERE version = %s",  # nosec B608
                            (version,)
                        )
                    else:
                        ph = '?' if self.dialect == 'sqlite' else '%s'
                        cursor.execute(
                            f'DELETE FROM "{self.table_name}" WHERE version = {ph}',  # nosec B608
                            (version,)
                        )

                    elapsed = time.monotonic() - start
                    conn.commit()
                    cursor.close()

                    record = MigrationRecord(version, f"UNDO: {desc}", script_name, "", elapsed, True)
                    rolled_back.append(record)
                    logger.info(f"Rollback U{version} ({desc}) completed in {elapsed:.2f}s")

            finally:
                self._release_db_lock(conn)

            self.pool.return_connection(pooled)
            return rolled_back

        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.error(f"Rollback failed: {e}")
            raise MigrationError(f"Rollback failed: {e}") from e

    # ==================== 校验 ====================

    def validate(self) -> bool:
        """校验已执行迁移的 checksum 是否一致（不执行任何 SQL）。

        Returns:
            True 如果所有已执行迁移的 checksum 一致
            False 如果存在 checksum 不匹配

        Raises:
            MigrationError 如果读取失败
        """
        applied = self._get_applied_versions()
        discovered = self._discover_migrations()

        for version, rec in applied.items():
            found = False
            for disc_ver, desc, script, checksum in discovered:
                if disc_ver == version:
                    found = True
                    if rec.checksum != checksum:
                        logger.error(
                            f"Checksum mismatch for migration V{version}: "
                            f"applied={rec.checksum}, current={checksum}"
                        )
                        return False
                    break
            if not found:
                logger.warning(f"Applied migration V{version} not found in migrations directory")
                return False

        logger.info(f"Validation passed: {len(applied)} migrations OK")
        return True

    # ==================== SQL 分割（公共方法） ====================

    def _split_sql_statements(self, sql_content: str) -> List[str]:
        """按分号分割 SQL 语句，跳过注释行。"""
        statements = []
        current = []
        for line in sql_content.split('\n'):
            stripped = line.strip()
            if stripped.startswith('--') or stripped.startswith('#'):
                continue
            current.append(line)
            if stripped.endswith(';'):
                stmt = '\n'.join(current).strip().rstrip(';')
                if stmt:
                    statements.append(stmt)
                current = []
        remaining = '\n'.join(current).strip()
        if remaining:
            statements.append(remaining)
        return statements
