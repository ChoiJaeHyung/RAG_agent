-- ================================================================
-- AI 고객상담 시스템 - 테이블 생성 스크립트
-- ================================================================
-- 목적: LG U+ 클콜 LITE 연동 + 웹채팅 + 콜백 관리
-- DB: r_agent_db (기존 RAG 학습 테이블과 동일 DB)
-- ================================================================

USE r_agent_db;

-- ================================================================
-- 1. 채팅 토큰 (SMS 링크용 일회성 토큰)
-- ================================================================
-- 용도: 전화 수신 시 SMS로 발송되는 채팅 링크의 인증 토큰
-- 흐름: 전화수신 → 토큰생성 → SMS발송 → 고객클릭 → 토큰검증 → 채팅시작
-- ================================================================
CREATE TABLE IF NOT EXISTS chat_tokens (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- 토큰 정보
    token VARCHAR(36) NOT NULL COMMENT 'UUID v4 토큰',
    phone VARCHAR(20) NOT NULL COMMENT '고객 전화번호',

    -- 클콜 연동 정보
    call_unique_id VARCHAR(50) COMMENT '클콜 CALLEVENT DATA8 (통화 고유ID)',
    call_event_raw TEXT COMMENT '클콜 이벤트 원본 데이터 (디버깅용)',

    -- 상태 관리
    status ENUM('pending', 'used', 'expired', 'revoked') DEFAULT 'pending' COMMENT '토큰 상태',

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성 시각',
    expires_at TIMESTAMP NOT NULL COMMENT '만료 시각',
    used_at TIMESTAMP NULL COMMENT '사용된 시각',

    -- 제약조건
    UNIQUE KEY uk_token (token),

    -- 인덱스 (성능 최적화)
    INDEX idx_phone (phone),
    INDEX idx_status (status),
    INDEX idx_expires_at (expires_at),
    INDEX idx_created_at (created_at),
    INDEX idx_status_expires (status, expires_at)  -- 만료 토큰 정리 배치용

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='채팅 토큰 - SMS 링크용 일회성 인증 토큰';


-- ================================================================
-- 2. 채팅 세션 (웹 채팅 세션 관리)
-- ================================================================
-- 용도: 고객이 채팅 시작 시 생성되는 세션
-- 연동: session_context.session_id와 rag_session_id로 연결 가능
-- ================================================================
CREATE TABLE IF NOT EXISTS chat_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- 세션 식별
    session_id VARCHAR(36) NOT NULL COMMENT '채팅 세션 UUID',
    token_id INT NOT NULL COMMENT 'chat_tokens.id 참조',

    -- 고객 정보
    phone VARCHAR(20) NOT NULL COMMENT '고객 전화번호',

    -- RAG 연동 (기존 session_context와 연결)
    rag_session_id VARCHAR(100) COMMENT 'RAG API session_id (session_context.session_id 참조)',

    -- 세션 통계
    message_count INT DEFAULT 0 COMMENT '총 메시지 수',
    user_message_count INT DEFAULT 0 COMMENT '고객 메시지 수',
    bot_message_count INT DEFAULT 0 COMMENT 'AI 응답 수',

    -- 세션 상태
    status ENUM('active', 'callback_requested', 'callback_sent', 'closed', 'expired')
        DEFAULT 'active' COMMENT '세션 상태',

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '세션 시작',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '마지막 활동',
    closed_at TIMESTAMP NULL COMMENT '세션 종료 시각',

    -- 메타데이터
    client_info JSON COMMENT '클라이언트 정보 (UA, IP 등)',

    -- 제약조건
    UNIQUE KEY uk_session_id (session_id),

    -- 외래키
    CONSTRAINT fk_chat_sessions_token
        FOREIGN KEY (token_id) REFERENCES chat_tokens(id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    -- 인덱스
    INDEX idx_phone (phone),
    INDEX idx_status (status),
    INDEX idx_rag_session (rag_session_id),
    INDEX idx_created_at (created_at),
    INDEX idx_updated_at (updated_at),
    INDEX idx_status_updated (status, updated_at)  -- 활성 세션 조회용

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='채팅 세션 - 웹 채팅 세션 관리';


-- ================================================================
-- 3. 채팅 메시지 (대화 내역 정규화 저장)
-- ================================================================
-- 용도: 개별 메시지 저장 (검색, 분석, 콜백 전송용)
-- 참고: session_context.conversation_history (JSON)과 별도 관리
--       → 고객상담용 상세 로그, RAG 학습은 기존 JSON 방식 유지
-- ================================================================
CREATE TABLE IF NOT EXISTS chat_messages (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- 세션 연결
    chat_session_id INT NOT NULL COMMENT 'chat_sessions.id 참조',

    -- 메시지 내용
    role ENUM('user', 'assistant', 'system') NOT NULL COMMENT '발신자 역할',
    content TEXT NOT NULL COMMENT '메시지 내용',

    -- RAG 응답 메타데이터 (role=assistant일 때)
    rag_task_id VARCHAR(100) COMMENT 'RAG API task_id',
    rag_confidence FLOAT COMMENT 'RAG 신뢰도 점수 (0.0~1.0)',
    rag_sources JSON COMMENT 'RAG 참조 문서 목록',
    rag_execution_time FLOAT COMMENT 'RAG 처리 시간 (초)',

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '메시지 생성 시각',

    -- 외래키
    CONSTRAINT fk_chat_messages_session
        FOREIGN KEY (chat_session_id) REFERENCES chat_sessions(id)
        ON DELETE CASCADE ON UPDATE CASCADE,

    -- 인덱스
    INDEX idx_session_created (chat_session_id, created_at),
    INDEX idx_role (role),
    INDEX idx_created_at (created_at)

    -- 참고: FULLTEXT 인덱스는 필요시 별도 추가
    -- FULLTEXT idx_content_ft (content)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='채팅 메시지 - 개별 메시지 정규화 저장';


-- ================================================================
-- 4. 콜백 요청 (상담원 콜백 관리)
-- ================================================================
-- 용도: 5회 응답 후 상담원 통화 요청 관리
-- 흐름: 버튼클릭 → DB저장 → 외부서버전송 → 상담원확인 → 콜백완료
-- ================================================================
CREATE TABLE IF NOT EXISTS chat_callbacks (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- 세션 연결
    chat_session_id INT NOT NULL COMMENT 'chat_sessions.id 참조',

    -- 고객 정보
    phone VARCHAR(20) NOT NULL COMMENT '콜백 전화번호',

    -- 콜백 상태
    status ENUM('pending', 'sent', 'assigned', 'in_progress', 'completed', 'failed', 'cancelled')
        DEFAULT 'pending' COMMENT '콜백 처리 상태',

    -- 처리 추적
    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '콜백 요청 시각',
    sent_at TIMESTAMP NULL COMMENT '외부 서버 전송 완료 시각',
    assigned_at TIMESTAMP NULL COMMENT '상담원 배정 시각',
    completed_at TIMESTAMP NULL COMMENT '콜백 완료 시각',

    -- 외부 서버 연동
    external_request_id VARCHAR(100) COMMENT '외부 서버 요청 ID',
    external_response JSON COMMENT '외부 서버 응답 데이터',

    -- 상담원 정보
    agent_id VARCHAR(50) COMMENT '담당 상담원 ID',
    agent_name VARCHAR(100) COMMENT '담당 상담원 이름',

    -- 콜백 결과
    callback_result ENUM('resolved', 'escalated', 'callback_later', 'no_answer', 'cancelled')
        COMMENT '콜백 처리 결과',
    callback_notes TEXT COMMENT '상담원 메모',

    -- 재시도 관리
    retry_count INT DEFAULT 0 COMMENT '전송 재시도 횟수',
    last_error TEXT COMMENT '마지막 에러 메시지',

    -- 우선순위
    priority ENUM('low', 'normal', 'high', 'urgent') DEFAULT 'normal' COMMENT '콜백 우선순위',

    -- 외래키
    CONSTRAINT fk_chat_callbacks_session
        FOREIGN KEY (chat_session_id) REFERENCES chat_sessions(id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    -- 인덱스 (대기 목록 조회 최적화)
    INDEX idx_status (status),
    INDEX idx_phone (phone),
    INDEX idx_priority_requested (priority, requested_at),
    INDEX idx_status_requested (status, requested_at),  -- 대기 콜백 목록
    INDEX idx_agent (agent_id),
    INDEX idx_requested_at (requested_at)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='콜백 요청 - 상담원 콜백 관리';


-- ================================================================
-- 5. SMS 발송 로그 (발송 이력 추적)
-- ================================================================
-- 용도: SMS 발송 이력 관리 (LG U+ SC_TRAN과 별도로 자체 로그)
-- 참고: SC_TRAN은 LG U+ DB에 INSERT, 이 테이블은 자체 추적용
-- ================================================================
CREATE TABLE IF NOT EXISTS sms_send_log (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- 연결 정보
    token_id INT NOT NULL COMMENT 'chat_tokens.id 참조',

    -- SMS 정보
    phone VARCHAR(20) NOT NULL COMMENT '수신 전화번호',
    callback_number VARCHAR(20) NOT NULL COMMENT '회신 번호',
    message VARCHAR(255) NOT NULL COMMENT 'SMS 내용',

    -- 발송 상태
    status ENUM('pending', 'sent', 'delivered', 'failed') DEFAULT 'pending' COMMENT '발송 상태',

    -- SC_TRAN 연동
    sc_tran_inserted BOOLEAN DEFAULT FALSE COMMENT 'SC_TRAN INSERT 성공 여부',
    sc_tran_error TEXT COMMENT 'SC_TRAN INSERT 에러 메시지',

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '발송 요청 시각',
    sent_at TIMESTAMP NULL COMMENT '발송 완료 시각',

    -- 외래키
    CONSTRAINT fk_sms_log_token
        FOREIGN KEY (token_id) REFERENCES chat_tokens(id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    -- 인덱스
    INDEX idx_phone (phone),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='SMS 발송 로그 - SMS 발송 이력 추적';


-- ================================================================
-- 뷰: 활성 콜백 대기 목록 (상담원 화면용)
-- ================================================================
CREATE OR REPLACE VIEW v_pending_callbacks AS
SELECT
    cb.id AS callback_id,
    cb.phone,
    cb.priority,
    cb.requested_at,
    cb.retry_count,
    cs.session_id,
    cs.message_count,
    cs.created_at AS session_started,
    TIMESTAMPDIFF(MINUTE, cb.requested_at, NOW()) AS waiting_minutes
FROM chat_callbacks cb
JOIN chat_sessions cs ON cb.chat_session_id = cs.id
WHERE cb.status IN ('pending', 'sent')
ORDER BY
    FIELD(cb.priority, 'urgent', 'high', 'normal', 'low'),
    cb.requested_at ASC;


-- ================================================================
-- 뷰: 세션 상세 (대화 요약 포함)
-- ================================================================
CREATE OR REPLACE VIEW v_session_summary AS
SELECT
    cs.id,
    cs.session_id,
    cs.phone,
    cs.status,
    cs.message_count,
    cs.created_at,
    cs.updated_at,
    ct.token,
    ct.call_unique_id,
    (SELECT COUNT(*) FROM chat_callbacks WHERE chat_session_id = cs.id) AS callback_count,
    (SELECT status FROM chat_callbacks WHERE chat_session_id = cs.id ORDER BY id DESC LIMIT 1) AS last_callback_status
FROM chat_sessions cs
JOIN chat_tokens ct ON cs.token_id = ct.id;


-- ================================================================
-- 이벤트: 만료된 토큰 정리 (매시간 실행)
-- ================================================================
-- 참고: 이벤트 스케줄러 활성화 필요
-- SET GLOBAL event_scheduler = ON;
-- ================================================================
DELIMITER //

CREATE EVENT IF NOT EXISTS evt_cleanup_expired_tokens
ON SCHEDULE EVERY 1 HOUR
STARTS CURRENT_TIMESTAMP
DO
BEGIN
    -- 만료된 pending 토큰을 expired로 변경
    UPDATE chat_tokens
    SET status = 'expired'
    WHERE status = 'pending'
      AND expires_at < NOW();

    -- 오래된 expired 세션 정리 (30일 이상)
    UPDATE chat_sessions
    SET status = 'expired'
    WHERE status = 'active'
      AND updated_at < DATE_SUB(NOW(), INTERVAL 30 DAY);
END //

DELIMITER ;


-- ================================================================
-- 테이블 생성 완료 확인
-- ================================================================
SELECT
    '고객상담 테이블 생성 완료' AS status,
    (SELECT COUNT(*) FROM information_schema.tables
     WHERE table_schema = 'r_agent_db'
       AND table_name LIKE 'chat_%') AS chat_tables,
    (SELECT COUNT(*) FROM information_schema.tables
     WHERE table_schema = 'r_agent_db'
       AND table_name = 'sms_send_log') AS sms_table;
