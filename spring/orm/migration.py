"""
数据库迁移管理器 (Database Migration Manager)

类 Flyway 风格的轻量数据库迁移工具：
- 基于 SQL 文件版本号管理
- 自动追踪已执行迁移（schema_version 表）
- 支持 checksum 校验防止篡改
- 支持 MySQL/PostgreSQL/SQLite
- 迁移文件命名: V{version}__{description}.sql
"""

import os
import re
import hashlib
import logging
import time
from typing import List, Dict, Optional, Tuple
from pathlib import Path

logger = logging.getLogger("Spring.ORM.Migration")

# 迁移文件命名模式: V1__init.sql, V2__add_users_table.sql
_MIGRATION_PATTERN = re.compile(r'^V(\d+(?:\.\d+)?)__(.+)\.sql$', re.IGNORECASE)
# 版本号分隔符
_VERSION_SPLIT = re.compile(r'[._]')


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
    """

    def __init__(self, connection_pool, migrations_dir: str,
                 dialect: str = "mysql", table_name: str = "schema_version"):
        self.pool = connection_pool
        self.migrations_dir = Path(migrations_dir)
        self.dialect = dialect.lower()
        self.table_name = table_name
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
                cursor.execute(f"SELECT version, description, script, checksum, installed_on, execution_time, success FROM `{self.table_name}` WHERE success = 1")
            else:
                cursor.execute(f'SELECT version, description, script, checksum, installed_on, execution_time, success FROM "{self.table_name}" WHERE success = 1')

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

            # 按分号分割语句（简单分割，不处理存储过程中的分号）
            statements = []
            current = []
            for line in sql_content.split('\n'):
                stripped = line.strip()
                # 跳过注释
                if stripped.startswith('--') or stripped.startswith('#'):
                    continue
                current.append(line)
                if stripped.endswith(';'):
                    stmt = '\n'.join(current).strip().rstrip(';')
                    if stmt:
                        statements.append(stmt)
                    current = []
            # 最后一条可能没有分号
            remaining = '\n'.join(current).strip()
            if remaining:
                statements.append(remaining)

            for stmt in statements:
                stmt = stmt.strip()
                if stmt:
                    logger.debug(f"Executing migration SQL: {stmt[:100]}...")
                    cursor.execute(stmt)

            elapsed = time.monotonic() - start

            # 记录迁移
            if self.dialect == 'mysql':
                cursor.execute(
                    f"INSERT INTO `{self.table_name}` (version, description, script, checksum, installed_on, execution_time, success) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (version, description, script_name, checksum, int(time.time()), int(elapsed * 1000), 1)
                )
            else:
                ph = '?' if self.dialect == 'sqlite' else '%s'
                table_ref = f'"{self.table_name}"'
                cursor.execute(
                    f'INSERT INTO {table_ref} (version, description, script, checksum, installed_on, execution_time, success) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})',
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
                            f'INSERT INTO "{self.table_name}" (version, description, script, checksum, installed_on, execution_time, success) SELECT {ph},{ph},{ph},{ph},{ph},{ph},{ph} WHERE NOT EXISTS (SELECT 1 FROM "{self.table_name}" WHERE version = {ph})',
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
                cursor.execute(f"DELETE FROM `{self.table_name}` WHERE success = 0")
            else:
                cursor.execute(f'DELETE FROM "{self.table_name}" WHERE success = 0')
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
