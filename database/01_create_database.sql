-- ================================================================
-- R-Agent Learning Database 생성 스크립트
-- ================================================================
-- 목적: R-Agent의 학습 및 성능 추적을 위한 전용 데이터베이스
-- 기존 dc_db와 분리하여 독립적으로 관리
-- ================================================================

-- 데이터베이스 생성 (이미 존재하면 삭제 후 재생성)
DROP DATABASE IF EXISTS r_agent_db;
CREATE DATABASE r_agent_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

-- 데이터베이스 선택
USE r_agent_db;

-- 권한 설정 (기존 rsup 계정에 권한 부여)
GRANT ALL PRIVILEGES ON r_agent_db.* TO 'rsup'@'%';
GRANT ALL PRIVILEGES ON r_agent_db.* TO 'rsup'@'localhost';
FLUSH PRIVILEGES;

-- 생성 완료 메시지
SELECT 'r_agent_db 데이터베이스가 성공적으로 생성되었습니다.' AS status;
