-- ================================================================
-- 외부 콜백 서버 DB 스키마 (단순화 버전)
-- ================================================================
-- 목적: RAG 채팅 사용자 목록 + 콜백 요청 표시
-- 엔드포인트:
--   POST /call-history/callbot       - 대화 내역 저장
--   GET  /call-history/callbot-list  - 전체 목록 조회
-- ================================================================

-- ================================================================
-- 콜봇 대화 기록 (R-Agent에서 전송받은 데이터)
-- ================================================================
CREATE TABLE IF NOT EXISTS call_history (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- 세션 식별
    session_id VARCHAR(36) NOT NULL COMMENT 'R-Agent 채팅 세션 ID',
    phone VARCHAR(20) NOT NULL COMMENT '고객 전화번호',

    -- 대화 내역
    conversation JSON NOT NULL COMMENT '전체 대화 내역',
    /*
    [
        {"role": "user", "content": "...", "timestamp": "..."},
        {"role": "assistant", "content": "...", "timestamp": "...", "confidence": 0.85}
    ]
    */
    message_count INT DEFAULT 0 COMMENT '총 메시지 수',

    -- 콜백 상태
    callback_requested BOOLEAN DEFAULT FALSE COMMENT '콜백 요청 여부',
    callback_requested_at TIMESTAMP NULL COMMENT '콜백 요청 시각',
    callback_completed BOOLEAN DEFAULT FALSE COMMENT '콜백 처리 완료',
    callback_completed_at TIMESTAMP NULL COMMENT '콜백 완료 시각',
    callback_memo TEXT COMMENT '상담원 메모',

    -- 메타데이터
    caller_id VARCHAR(50) COMMENT '클콜 통화 고유 ID',
    token VARCHAR(36) COMMENT '채팅 토큰',

    -- 시간
    session_started_at TIMESTAMP COMMENT '세션 시작 시각',
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '데이터 수신 시각',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 제약조건
    UNIQUE KEY uk_session_id (session_id),

    -- 인덱스
    INDEX idx_phone (phone),
    INDEX idx_callback_requested (callback_requested),
    INDEX idx_received_at (received_at)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='콜봇 대화 기록 - RAG 채팅 사용자 목록';


-- ================================================================
-- API 응답 예시
-- ================================================================
/*
GET /call-history/callbot-list 응답:

{
  "total": 25,
  "list": [
    {
      "id": 1,
      "phone": "010-1234-5678",
      "session_id": "abc-123",
      "message_count": 5,
      "callback_requested": true,        // 🔔 표시
      "callback_requested_at": "2025-01-15T10:30:00Z",
      "callback_completed": false,
      "session_started_at": "2025-01-15T10:00:00Z",
      "first_message": "RemoteCall 설치가 안돼요"
    },
    ...
  ]
}


POST /call-history/callbot 요청 body:

{
  "session_id": "uuid-xxx",
  "phone": "01012345678",
  "conversation": [...],
  "message_count": 5,
  "callback_requested": true,
  "callback_requested_at": "2025-01-15T10:30:00Z",
  "session_started_at": "2025-01-15T10:00:00Z",
  "caller_id": "1427344822.1189678",
  "token": "abc-123-xyz"
}
*/
