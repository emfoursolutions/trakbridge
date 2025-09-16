-- MySQL/MariaDB initialization script
-- This script runs when the MySQL/MariaDB container starts for the first time

-- Create additional databases if needed
-- CREATE DATABASE trakbridge CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- MariaDB 11 specific configuration to prevent "Got an error reading communication packets"
SET GLOBAL max_allowed_packet = 1024*1024*1024;  -- 1GB max packet size
SET GLOBAL net_read_timeout = 600;               -- 10 minutes read timeout
SET GLOBAL net_write_timeout = 600;              -- 10 minutes write timeout
SET GLOBAL interactive_timeout = 28800;          -- 8 hours interactive timeout
SET GLOBAL wait_timeout = 28800;                 -- 8 hours wait timeout
SET GLOBAL connect_timeout = 60;                 -- 60 seconds connect timeout

-- Set SQL mode for MariaDB 11 compatibility
SET GLOBAL sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO';

-- Optimize InnoDB settings for containerized environment
SET GLOBAL innodb_buffer_pool_size = 134217728;  -- 128MB (adjust based on container memory)
SET GLOBAL innodb_log_file_size = 50331648;      -- 48MB

-- Grant permissions
GRANT ALL PRIVILEGES ON trakbridge.* TO 'trakbridge'@'%';
FLUSH PRIVILEGES;

-- Log configuration for debugging
SELECT 'MariaDB 11 TrakBridge initialization completed' AS status;