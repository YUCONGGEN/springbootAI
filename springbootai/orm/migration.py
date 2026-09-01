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
from contextlib import contextmanager
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

    @contextmanager
    def _connection(self):
        """Borrow a pooled connection and always return it, including on failure."""
        pooled = self.pool.get_connection()
        conn = pooled.connection
        try:
            yield conn
        except BaseException:
            try:
                conn.rollback()
            except Exception:
                logger.debug("Migration connection rollback failed", exc_info=True)
            raise
        finally:
            try:
                self.pool.return_connection(pooled)
            except Exception:
                logger.warning("Failed to return migration connection to pool", exc_info=True)

    @contextmanager
    def _migration_lock(self):
        """Hold a database/session lock for the whole migration operation."""
        with self._connection() as conn:
            acquired = False
            try:
                acquired = self._acquire_db_lock(conn)
                if not acquired:
                    raise MigrationError(
                        "Failed to acquire migration lock (another migration may be running)"
                    )
                yield
            finally:
                if acquired:
                    self._release_db_lock(conn)

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

        try:
            with self._connection() as conn:
                cursor = conn.cursor()
                try:
                    for stmt in self._split_sql_statements(ddl):
                        if stmt.strip():
                            cursor.execute(stmt)
                    conn.commit()
                finally:
                    cursor.close()
        except Exception as e:
            raise MigrationError(
                f"Failed to create version table ({type(e).__name__})"
            ) from e

    def _get_applied_versions(self) -> Dict[str, MigrationRecord]:
        """获取已执行的迁移版本"""
        try:
            with self._connection() as conn:
                cursor = conn.cursor()
                try:
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
                                execution_time=row[5] if len(row) > 5 else 0,
                                success=bool(row[6]) if len(row) > 6 else True
                            )
                        applied[rec.version] = rec
                    return applied
                finally:
                    cursor.close()
        except Exception as e:
            raise MigrationError(
                f"Failed to read applied versions ({type(e).__name__})"
            ) from e

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
        versions = [migration[0] for migration in migrations]
        duplicates = sorted({version for version in versions if versions.count(version) > 1})
        if duplicates:
            raise MigrationError(
                "Duplicate migration version(s): " + ", ".join(duplicates)
            )
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
        start = time.monotonic()
        try:
            with self._connection() as conn:
                cursor = conn.cursor()
                try:
                    sql_content = self._substitute_variables(sql_content)
                    for stmt in self._split_sql_statements(sql_content):
                        if stmt.strip():
                            logger.debug("Executing migration SQL statement")
                            cursor.execute(stmt)

                    elapsed = time.monotonic() - start
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
                finally:
                    cursor.close()

            record = MigrationRecord(version, description, script_name, checksum, elapsed, True)
            logger.info(f"Migration V{version} ({description}) applied successfully in {elapsed:.2f}s")
            return record

        except Exception as e:
            elapsed = time.monotonic() - start
            logger.error(
                "Migration V%s failed after %.2fs (%s)",
                version, elapsed, type(e).__name__,
            )
            raise MigrationError(
                f"Migration V{version} ({description}) failed ({type(e).__name__})"
            ) from e

    def migrate(self, baseline: bool = False) -> List[MigrationRecord]:
        """
        执行所有待执行的迁移

        Args:
            baseline: 如果为True，将现有数据库标记为已完成初始迁移（用于在已有数据库上启用迁移）

        Returns:
            本次执行的迁移记录列表
        """
        with self._migration_lock():
            return self._migrate_locked(baseline=baseline)

    def _migrate_locked(self, baseline: bool = False) -> List[MigrationRecord]:
        """Migration implementation; caller must hold ``_migration_lock``."""
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
                try:
                    with self._connection() as baseline_conn:
                        cursor = baseline_conn.cursor()
                        try:
                            if self.dialect == 'mysql':
                                cursor.execute(
                                    f"INSERT IGNORE INTO `{self.table_name}` (version, description, script, checksum, installed_on, execution_time, success) VALUES (%s, %s, %s, %s, %s, %s, %s)",  # nosec B608
                                    (version, description, script, checksum, int(time.time()), 0, 1)
                                )
                            else:
                                ph = '?' if self.dialect == 'sqlite' else '%s'
                                cursor.execute(
                                    f'INSERT INTO "{self.table_name}" (version, description, script, checksum, installed_on, execution_time, success) SELECT {ph},{ph},{ph},{ph},{ph},{ph},{ph} WHERE NOT EXISTS (SELECT 1 FROM "{self.table_name}" WHERE version = {ph})',  # nosec B608
                                    (version, description, script, checksum, int(time.time()), 0, 1, version)
                                )
                            baseline_conn.commit()
                        finally:
                            cursor.close()
                except Exception as exc:
                    raise MigrationError(
                        f"Failed to baseline migration V{version} ({type(exc).__name__})"
                    ) from exc
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
        try:
            with self._migration_lock():
                with self._connection() as conn:
                    cursor = conn.cursor()
                    try:
                        if self.dialect == 'mysql':
                            cursor.execute(f"DELETE FROM `{self.table_name}` WHERE success = 0")  # nosec B608
                        else:
                            cursor.execute(f'DELETE FROM "{self.table_name}" WHERE success = 0')  # nosec B608
                        deleted = cursor.rowcount
                        conn.commit()
                    finally:
                        cursor.close()
            logger.info(f"Repaired {deleted} failed migration record(s)")
            return deleted
        except Exception as e:
            raise MigrationError(f"Repair failed ({type(e).__name__})") from e

    # ==================== 变量替换 ====================

    def _substitute_variables(self, sql: str) -> str:
        """替换 SQL 中的 ${var_name} 变量。

        Values are deliberately restricted to an unquoted SQL token. Callers
        can place the placeholder inside quotes in the migration when a string
        literal is required. This prevents a variable from changing SQL shape.
        """
        if not self.variables:
            return sql

        def _replacer(match):
            var_name = match.group(1)
            if var_name not in self.variables:
                raise MigrationError(f"Undefined migration variable: ${{{var_name}}}")
            value = str(self.variables[var_name])
            if len(value.encode("utf-8")) > 1024:
                raise MigrationError(
                    f"Migration variable '{var_name}' exceeds 1024 bytes"
                )
            if ';' in value:
                raise MigrationError(
                    f"Migration variable '{var_name}' contains semicolon ';', "
                    f"which is not allowed for security reasons"
                )
            if not re.fullmatch(r"[A-Za-z0-9_.:/@+?&=%-]*", value):
                raise MigrationError(
                    f"Migration variable '{var_name}' contains unsafe characters"
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
            try:
                cursor.execute("SELECT GET_LOCK('springbootai_migration', 10)")  # nosec B608
                result = cursor.fetchone()
                return bool(result[0] if result and isinstance(result, (tuple, list)) else result)
            finally:
                cursor.close()
        elif self.dialect == 'postgresql':
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT pg_try_advisory_lock(123456789)")  # nosec B608
                result = cursor.fetchone()
                return bool(result and result[0])
            finally:
                cursor.close()
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
        with self._migration_lock():
            return self._rollback_locked(target_version)

    def _rollback_locked(self, target_version: Optional[str]) -> List[MigrationRecord]:
        applied = self._get_applied_versions()
        if not applied:
            logger.info("No migrations to rollback")
            return []

        undo_scripts = self._discover_undo_migrations()
        sorted_versions = sorted(applied.keys(), key=self._version_tuple, reverse=True)
        if target_version:
            target_tuple = self._version_tuple(target_version)
            to_rollback = [
                version for version in sorted_versions
                if self._version_tuple(version) > target_tuple
            ]
        else:
            to_rollback = [sorted_versions[0]]
        if not to_rollback:
            logger.info("No migrations to rollback")
            return []

        rolled_back = []
        try:
            with self._connection() as conn:
                for version in to_rollback:
                    if version not in undo_scripts:
                        raise MigrationError(
                            f"Undo script U{version}__*.sql not found. "
                            f"Cannot rollback migration V{version} without undo script."
                        )
                    desc, script_name, sql_content = undo_scripts[version]
                    sql_content = self._substitute_variables(sql_content)
                    start = time.monotonic()
                    cursor = conn.cursor()
                    try:
                        for stmt in self._split_sql_statements(sql_content):
                            if stmt.strip():
                                logger.debug("Executing undo SQL statement")
                                cursor.execute(stmt)
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
                        conn.commit()
                    finally:
                        cursor.close()
                    elapsed = time.monotonic() - start
                    rolled_back.append(MigrationRecord(
                        version, f"UNDO: {desc}", script_name, "", elapsed, True
                    ))
                    logger.info(
                        "Rollback U%s (%s) completed in %.2fs",
                        version, desc, elapsed,
                    )
            return rolled_back
        except Exception as exc:
            logger.error("Rollback failed (%s)", type(exc).__name__)
            if isinstance(exc, MigrationError):
                raise
            raise MigrationError(
                f"Rollback failed ({type(exc).__name__})"
            ) from exc

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
        """Split SQL without breaking quoted strings, comments, or routine bodies.

        Supports MySQL ``DELIMITER`` directives and PostgreSQL dollar-quoted
        blocks. The directive itself is client syntax and is not sent to the DB.
        """
        statements: List[str] = []
        current: List[str] = []
        delimiter = ";"
        quote: Optional[str] = None
        dollar_tag: Optional[str] = None
        in_block_comment = False

        for line in sql_content.splitlines(keepends=True):
            if not quote and not dollar_tag and not in_block_comment and not "".join(current).strip():
                directive = re.fullmatch(r"\s*DELIMITER\s+(\S+)\s*(?:\r?\n)?", line, re.IGNORECASE)
                if directive:
                    delimiter = directive.group(1)
                    if len(delimiter) > 16:
                        raise MigrationError("SQL delimiter is too long")
                    continue

            index = 0
            line_comment = False
            while index < len(line):
                char = line[index]
                following = line[index + 1] if index + 1 < len(line) else ""

                if line_comment:
                    if char in "\r\n":
                        current.append(char)
                        line_comment = False
                    index += 1
                    continue
                if in_block_comment:
                    if char == "*" and following == "/":
                        in_block_comment = False
                        index += 2
                    else:
                        index += 1
                    continue
                if dollar_tag:
                    if line.startswith(dollar_tag, index):
                        current.append(dollar_tag)
                        index += len(dollar_tag)
                        dollar_tag = None
                    else:
                        current.append(char)
                        index += 1
                    continue
                if quote:
                    current.append(char)
                    if char == "\\" and index + 1 < len(line):
                        current.append(line[index + 1])
                        index += 2
                        continue
                    if char == quote:
                        if following == quote:
                            current.append(following)
                            index += 2
                            continue
                        quote = None
                    index += 1
                    continue

                if char == "/" and following == "*":
                    in_block_comment = True
                    index += 2
                    continue
                if char == "#" or (
                    char == "-" and following == "-" and
                    (index + 2 >= len(line) or line[index + 2].isspace())
                ):
                    line_comment = True
                    index += 1 if char == "#" else 2
                    continue
                if char in {"'", '"', "`"}:
                    quote = char
                    current.append(char)
                    index += 1
                    continue
                if char == "$":
                    match = re.match(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", line[index:])
                    if match:
                        dollar_tag = match.group(0)
                        current.append(dollar_tag)
                        index += len(dollar_tag)
                        continue
                if delimiter and line.startswith(delimiter, index):
                    statement = "".join(current).strip()
                    if statement:
                        statements.append(statement)
                    current = []
                    index += len(delimiter)
                    continue
                current.append(char)
                index += 1

        if quote:
            raise MigrationError("Unterminated SQL quoted string")
        if dollar_tag:
            raise MigrationError("Unterminated SQL dollar-quoted block")
        if in_block_comment:
            raise MigrationError("Unterminated SQL block comment")
        remaining = "".join(current).strip()
        if remaining:
            statements.append(remaining)
        return statements
