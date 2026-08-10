-- Apache Seata TCC fence table. Source schema:
-- https://github.com/apache/incubator-seata/blob/v2.5.0/script/client/tcc/db/mysql.sql
CREATE TABLE IF NOT EXISTS `tcc_fence_log`
(
    `xid`          VARCHAR(128) NOT NULL COMMENT 'global id',
    `branch_id`    BIGINT       NOT NULL COMMENT 'branch id',
    `action_name`  VARCHAR(64)  NOT NULL COMMENT 'action name',
    `status`       TINYINT      NOT NULL COMMENT 'tried:1;committed:2;rollbacked:3;suspended:4',
    `gmt_create`   DATETIME(3)  NOT NULL COMMENT 'create time',
    `gmt_modified` DATETIME(3)  NOT NULL COMMENT 'update time',
    PRIMARY KEY (`xid`, `branch_id`),
    KEY `idx_gmt_modified` (`gmt_modified`),
    KEY `idx_status` (`status`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;
