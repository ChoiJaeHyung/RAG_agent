-- r_agent_db 데이터베이스 간단 생성 (root 권한 필요)

CREATE DATABASE IF NOT EXISTS r_agent_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

-- rsup 계정에 권한 부여
GRANT ALL PRIVILEGES ON r_agent_db.* TO 'rsup'@'%';
GRANT ALL PRIVILEGES ON r_agent_db.* TO 'rsup'@'localhost';
FLUSH PRIVILEGES;

SELECT 'r_agent_db 생성 완료' AS status;
