-- FRD PostgreSQL 初始化扩展
-- 由 docker-entrypoint-initdb.d 自动执行

-- TimescaleDB 扩展（时序数据）
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- pgcrypto 扩展（UUID v4/gen_random_uuid）
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- citext 扩展（不区分大小写文本，邮箱等）
CREATE EXTENSION IF NOT EXISTS citext;

-- pg_trgm 扩展（模糊搜索）
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- uuid-ossp（备用 UUID 生成）
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 验证
SELECT 'extensions installed' AS status;
