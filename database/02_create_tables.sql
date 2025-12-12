-- ================================================================
-- R-Agent Learning Database - 테이블 생성 스크립트
-- ================================================================
-- 목적: 도구 성능 추적, 학습 패턴, 세션 컨텍스트 관리
-- ================================================================

USE r_agent_db;

-- ================================================================
-- 1. 도구 실행 로그 (모든 도구 실행 기록)
-- ================================================================
CREATE TABLE IF NOT EXISTS tool_performance_log (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- 실행 컨텍스트
    session_id VARCHAR(100) NOT NULL COMMENT '세션 식별자',
    user_id VARCHAR(100) COMMENT '사용자 식별자',
    question TEXT NOT NULL COMMENT '사용자 질문',
    question_type ENUM('list', 'qa', 'error_code', 'how_to', 'keyword', 'concept') NOT NULL COMMENT '질문 유형',

    -- 도구 실행 상세
    tool_name VARCHAR(100) NOT NULL COMMENT '실행된 도구 이름',
    execution_order INT NOT NULL COMMENT '실행 순서 (1=primary, 2+=fallback)',
    is_fallback BOOLEAN DEFAULT FALSE COMMENT '폴백 실행 여부',

    -- 성능 지표
    doc_count INT DEFAULT 0 COMMENT '반환된 문서 수',
    avg_score FLOAT DEFAULT 0.0 COMMENT '평균 관련성 점수',
    execution_time FLOAT NOT NULL COMMENT '실행 시간 (초)',
    success BOOLEAN NOT NULL COMMENT '성공 여부',

    -- 품질 지표
    relevance_score FLOAT COMMENT '의미적 관련성 점수 (향후 구현)',
    user_feedback ENUM('positive', 'negative', 'neutral') COMMENT '사용자 피드백',

    -- 에러 추적
    error_message TEXT COMMENT '에러 메시지',
    error_type VARCHAR(100) COMMENT '에러 유형',

    -- 메타데이터
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성 시각',

    -- 인덱스 (빠른 조회를 위해)
    INDEX idx_tool_name (tool_name),
    INDEX idx_question_type (question_type),
    INDEX idx_success (success),
    INDEX idx_created_at (created_at),
    INDEX idx_session (session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='도구 실행 로그 - 모든 도구 실행 이벤트 기록';

-- ================================================================
-- 2. 도구 성능 통계 (집계된 통계)
-- ================================================================
CREATE TABLE IF NOT EXISTS tool_performance_stats (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- 차원
    tool_name VARCHAR(100) NOT NULL COMMENT '도구 이름',
    question_type ENUM('list', 'qa', 'error_code', 'how_to', 'keyword', 'concept') COMMENT '질문 유형',

    -- 집계 지표 (최근 30일 기준)
    total_executions INT DEFAULT 0 COMMENT '총 실행 횟수',
    successful_executions INT DEFAULT 0 COMMENT '성공한 실행 횟수',
    failed_executions INT DEFAULT 0 COMMENT '실패한 실행 횟수',
    success_rate FLOAT DEFAULT 0.0 COMMENT '성공률 (0.0 ~ 1.0)',

    avg_doc_count FLOAT DEFAULT 0.0 COMMENT '평균 문서 반환 수',
    avg_execution_time FLOAT DEFAULT 0.0 COMMENT '평균 실행 시간 (초)',
    avg_relevance_score FLOAT COMMENT '평균 관련성 점수',

    -- 사용자 만족도
    positive_feedback INT DEFAULT 0 COMMENT '긍정 피드백 수',
    negative_feedback INT DEFAULT 0 COMMENT '부정 피드백 수',
    satisfaction_rate FLOAT DEFAULT 0.0 COMMENT '만족도 (0.0 ~ 1.0)',

    -- 마지막 업데이트
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '업데이트 시각',

    -- 유니크 제약 (도구명 + 질문타입 조합은 유일)
    UNIQUE KEY unique_tool_question (tool_name, question_type),

    -- 인덱스
    INDEX idx_success_rate (success_rate),
    INDEX idx_tool_name (tool_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='도구 성능 통계 - 도구별/질문타입별 집계 데이터';

-- ================================================================
-- 3. 도구 선택 패턴 (학습된 패턴)
-- ================================================================
CREATE TABLE IF NOT EXISTS tool_selection_patterns (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- 패턴 정의
    pattern_name VARCHAR(200) NOT NULL COMMENT '패턴 이름',
    question_pattern TEXT NOT NULL COMMENT '질문 매칭 패턴 (키워드 또는 정규식)',
    question_type ENUM('list', 'qa', 'error_code', 'how_to', 'keyword', 'concept') COMMENT '질문 유형',

    -- 추천 전략
    primary_tool VARCHAR(100) NOT NULL COMMENT '1차 추천 도구',
    fallback_tools JSON COMMENT '폴백 도구 배열',

    -- 패턴 성능
    times_used INT DEFAULT 0 COMMENT '사용 횟수',
    success_rate FLOAT DEFAULT 0.0 COMMENT '성공률',
    avg_execution_time FLOAT DEFAULT 0.0 COMMENT '평균 실행 시간',

    -- 학습 메타데이터
    confidence_score FLOAT DEFAULT 0.5 COMMENT '패턴 신뢰도 (0.0 ~ 1.0)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '생성 시각',
    last_used TIMESTAMP COMMENT '마지막 사용 시각',

    -- 인덱스
    INDEX idx_question_type (question_type),
    INDEX idx_confidence (confidence_score),
    INDEX idx_success_rate (success_rate)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='도구 선택 패턴 - 학습된 최적 도구 선택 전략';

-- ================================================================
-- 4. 세션 컨텍스트 (대화 컨텍스트 관리)
-- ================================================================
CREATE TABLE IF NOT EXISTS session_context (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- 세션 정보
    session_id VARCHAR(100) NOT NULL UNIQUE COMMENT '세션 식별자',
    user_id VARCHAR(100) COMMENT '사용자 식별자',

    -- 컨텍스트 데이터
    conversation_history JSON COMMENT '대화 히스토리 [{question, answer, timestamp}]',
    user_profile JSON COMMENT '사용자 프로필 {expertise_level, preferences, topics}',

    -- 세션 지표
    total_questions INT DEFAULT 0 COMMENT '총 질문 수',
    successful_answers INT DEFAULT 0 COMMENT '성공한 답변 수',
    avg_satisfaction FLOAT DEFAULT 0.0 COMMENT '평균 만족도',

    -- 타임스탬프
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '세션 시작 시각',
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '마지막 활동 시각',

    -- 인덱스
    INDEX idx_session_id (session_id),
    INDEX idx_user_id (user_id),
    INDEX idx_last_activity (last_activity)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='세션 컨텍스트 - 다중 턴 대화 및 사용자 프로필 관리';

-- ================================================================
-- 테이블 생성 완료
-- ================================================================
SELECT
    '테이블 생성 완료' AS status,
    (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'r_agent_db') AS total_tables;
