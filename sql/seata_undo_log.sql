-- ========================================
-- Seata 分布式事务回滚日志表
-- ========================================
-- 注意：此脚本需要在每个参与分布式事务的数据库中执行

-- ========================================
-- MySQL 版本
-- 执行方式: mysql -u username -p database_name < seata_undo_log.sql
-- 或: mysql -u username -p -e "source seata_undo_log.sql" database_name
-- ========================================
-- CREATE TABLE IF NOT EXISTS `seata_undo_log` (
--     `id` BIGINT(20) NOT NULL AUTO_INCREMENT COMMENT '主键',
--     `branch_id` BIGINT(20) NOT NULL COMMENT '分支事务ID',
--     `xid` VARCHAR(100) NOT NULL COMMENT '全局事务ID',
--     `context` VARCHAR(128) NOT NULL COMMENT '上下文',
--     `rollback_info` LONGBLOB NOT NULL COMMENT '回滚信息',
--     `log_status` INT(11) NOT NULL COMMENT '状态: 0-正常, 1-已清理',
--     `log_created` DATETIME NOT NULL COMMENT '创建时间',
--     `log_modified` DATETIME NOT NULL COMMENT '修改时间',
--     PRIMARY KEY (`id`),
--     UNIQUE KEY `ux_undo_log` (`xid`,`branch_id`)
-- ) ENGINE=InnoDB AUTO_INCREMENT=1 DEFAULT CHARSET=utf8mb4 COMMENT='Seata回滚日志表';

-- ========================================
-- MySQL 版本（兼容 MySQL 8+，支持 caching_sha2_password）
-- ========================================
CREATE TABLE IF NOT EXISTS `seata_undo_log` (
    `id` BIGINT(20) NOT NULL AUTO_INCREMENT COMMENT '主键',
    `branch_id` BIGINT(20) NOT NULL COMMENT '分支事务ID',
    `xid` VARCHAR(100) NOT NULL COMMENT '全局事务ID',
    `context` VARCHAR(128) NOT NULL COMMENT '上下文',
    `rollback_info` LONGBLOB NOT NULL COMMENT '回滚信息',
    `log_status` INT(11) NOT NULL COMMENT '状态: 0-正常, 1-已清理',
    `log_created` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `log_modified` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '修改时间',
    PRIMARY KEY (`id`) USING BTREE,
    UNIQUE KEY `ux_undo_log` (`xid`, `branch_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Seata回滚日志表';

-- ========================================
-- PostgreSQL 版本（取消注释后使用）
-- ========================================
-- CREATE TABLE IF NOT EXISTS seata_undo_log (
--     id BIGSERIAL PRIMARY KEY,
--     branch_id BIGINT NOT NULL,
--     xid VARCHAR(100) NOT NULL,
--     context VARCHAR(128) NOT NULL,
--     rollback_info BYTEA NOT NULL,
--     log_status INT NOT NULL,
--     log_created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
--     log_modified TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
-- );
-- 
-- CREATE UNIQUE INDEX ux_undo_log ON seata_undo_log (xid, branch_id);

-- ========================================
-- SQLite 版本（取消注释后使用）
-- ========================================
-- CREATE TABLE IF NOT EXISTS seata_undo_log (
--     id INTEGER PRIMARY KEY AUTOINCREMENT,
--     branch_id INTEGER NOT NULL,
--     xid TEXT NOT NULL,
--     context TEXT NOT NULL,
--     rollback_info BLOB NOT NULL,
--     log_status INTEGER NOT NULL,
--     log_created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
--     log_modified TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
-- );
-- 
-- CREATE UNIQUE INDEX ux_undo_log ON seata_undo_log (xid, branch_id);