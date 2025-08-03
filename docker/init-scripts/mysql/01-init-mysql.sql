-- MySQL initialization script
-- This script runs when the MySQL container starts for the first time

-- Create additional databases if needed
-- CREATE DATABASE trakbridge_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Grant permissions
GRANT ALL PRIVILEGES ON trakbridge_db.* TO 'mysql'@'%';
FLUSH PRIVILEGES;