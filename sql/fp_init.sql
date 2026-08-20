-- ============================================
-- 法拍监控系统 - 数据库初始化脚本
-- 数据库: by_hardware
-- 所有表以 fp_ 开头
-- 使用方法: mysql -h127.0.0.1 -P4000 -uroot -p123456 < sql/fp_init.sql
-- ============================================

CREATE DATABASE IF NOT EXISTS `by_hardware` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE `by_hardware`;


-- ============================================
-- 表1: fp_keywords (监控关键词表)
-- ============================================
DROP TABLE IF EXISTS `fp_keywords`;
CREATE TABLE `fp_keywords` (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
    `keyword` VARCHAR(255) NOT NULL COMMENT '搜索关键词',
    `enabled` TINYINT DEFAULT 1 COMMENT '是否启用：1=启用，0=禁用',
    `remark` VARCHAR(500) DEFAULT NULL COMMENT '备注',
    `last_run_at` DATETIME DEFAULT NULL COMMENT '上次抓取时间',
    `last_total` INT DEFAULT 0 COMMENT '上次抓取总数',
    `last_status` VARCHAR(20) DEFAULT NULL COMMENT '上次抓取状态',
    `last_error` VARCHAR(1000) DEFAULT NULL COMMENT '上次抓取错误信息',
    `is_deleted` TINYINT DEFAULT 0 COMMENT '逻辑删除',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY `uk_keyword` (`keyword`, `is_deleted`),
    INDEX `idx_enabled` (`enabled`),
    INDEX `idx_is_deleted` (`is_deleted`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='法拍监控关键词表';


-- ============================================
-- 表2: fp_items (拍卖标的表 - 主表)
-- ============================================
DROP TABLE IF EXISTS `fp_items`;
CREATE TABLE `fp_items` (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
    `sf_item_id` BIGINT NOT NULL COMMENT '淘宝标的 ID（详情URL中的数字部分）',
    `keyword_id` INT DEFAULT NULL COMMENT '触发首次入库的关键词 ID',
    `title` VARCHAR(500) DEFAULT NULL COMMENT '标的名称',
    `status` VARCHAR(16) DEFAULT NULL COMMENT '状态: doing/todo/done/closed',
    `initial_price` DECIMAL(14,2) DEFAULT NULL COMMENT '起拍价',
    `current_price` DECIMAL(14,2) DEFAULT NULL COMMENT '当前价',
    `consult_price` DECIMAL(14,2) DEFAULT NULL COMMENT '评估价',
    `market_price` DECIMAL(14,2) DEFAULT NULL COMMENT '市场价',
    `apply_count` INT DEFAULT 0 COMMENT '报名人数',
    `bid_count` INT DEFAULT 0 COMMENT '竞价次数',
    `viewer_count` INT DEFAULT 0 COMMENT '围观人数',
    `delay_count` INT DEFAULT 0 COMMENT '延时次数',
    `start_at` DATETIME DEFAULT NULL COMMENT '开拍时间',
    `end_at` DATETIME DEFAULT NULL COMMENT '结束时间',
    `support_loans` TINYINT DEFAULT 0 COMMENT '是否支持贷款',
    `sell_off` TINYINT DEFAULT 0 COMMENT '是否流拍',
    `item_url` VARCHAR(500) DEFAULT NULL COMMENT '详情页 URL',
    `pic_url` VARCHAR(500) DEFAULT NULL COMMENT '图片 URL',
    `first_seen_at` DATETIME DEFAULT NULL COMMENT '首次入库时间',
    `last_seen_at` DATETIME DEFAULT NULL COMMENT '最近一次抓到时间',
    `is_deleted` TINYINT DEFAULT 0 COMMENT '逻辑删除',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY `uk_sf_item_id` (`sf_item_id`),
    INDEX `idx_status` (`status`),
    INDEX `idx_keyword_id` (`keyword_id`),
    INDEX `idx_end_at` (`end_at`),
    INDEX `idx_last_seen_at` (`last_seen_at`),
    INDEX `idx_is_deleted` (`is_deleted`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='法拍标的表';


-- ============================================
-- 表3: fp_item_history (标的变动历史表 - 每日快照)
-- ============================================
DROP TABLE IF EXISTS `fp_item_history`;
CREATE TABLE `fp_item_history` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
    `sf_item_id` BIGINT NOT NULL COMMENT '淘宝标的 ID',
    `item_pk` INT NOT NULL COMMENT '对应 fp_items.id',
    `status` VARCHAR(16) DEFAULT NULL COMMENT '当时状态',
    `current_price` DECIMAL(14,2) DEFAULT NULL COMMENT '当时当前价',
    `apply_count` INT DEFAULT 0 COMMENT '当时报名人数',
    `bid_count` INT DEFAULT 0 COMMENT '当时竞价次数',
    `viewer_count` INT DEFAULT 0 COMMENT '当时围观人数',
    `snapshot_date` DATE NOT NULL COMMENT '快照日期',
    `snapshot_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '快照时间',
    `is_deleted` TINYINT DEFAULT 0 COMMENT '逻辑删除',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    UNIQUE KEY `uk_item_date` (`sf_item_id`, `snapshot_date`),
    INDEX `idx_item_pk` (`item_pk`),
    INDEX `idx_snapshot_date` (`snapshot_date`),
    INDEX `idx_is_deleted` (`is_deleted`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='法拍标的变动历史快照';


-- ============================================
-- 表4: fp_run_logs (抓取运行日志表)
-- ============================================
DROP TABLE IF EXISTS `fp_run_logs`;
CREATE TABLE `fp_run_logs` (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
    `keyword_id` INT DEFAULT NULL COMMENT '关键词 ID',
    `keyword_name` VARCHAR(255) DEFAULT NULL COMMENT '关键词名（冗余）',
    `start_at` DATETIME DEFAULT NULL COMMENT '开始时间',
    `end_at` DATETIME DEFAULT NULL COMMENT '结束时间',
    `duration_sec` INT DEFAULT 0 COMMENT '耗时(秒)',
    `pages_scanned` INT DEFAULT 0 COMMENT '翻页数',
    `items_found` INT DEFAULT 0 COMMENT '本次扫到的条目数',
    `items_new` INT DEFAULT 0 COMMENT '新增条目数',
    `items_updated` INT DEFAULT 0 COMMENT '更新条目数',
    `status` VARCHAR(20) DEFAULT NULL COMMENT 'success / failed / partial',
    `error_msg` VARCHAR(2000) DEFAULT NULL COMMENT '错误信息',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    INDEX `idx_keyword_id` (`keyword_id`),
    INDEX `idx_start_at` (`start_at`),
    INDEX `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='法拍抓取运行日志';


-- ============================================
-- 初始化示例监控关键词（可自行删除/修改）
-- ============================================
INSERT INTO `fp_keywords` (`keyword`, `enabled`, `remark`) VALUES
('服务器', 1, '服务器类法拍'),
('服务器拍卖', 1, '服务器拍卖'),
('机房', 1, '机房相关'),
('交换机', 1, '网络设备'),
('路由器', 1, '网络设备'),
('防火墙', 1, '安全设备'),
('存储设备', 1, '存储类'),
('工作站', 1, '图形工作站'),
('笔记本电脑', 1, '笔记本'),
('台式机', 1, '台式机');

