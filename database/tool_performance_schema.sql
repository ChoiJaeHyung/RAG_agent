-- Tool Performance Tracking Schema
-- Enables learning and data-driven tool selection

CREATE TABLE IF NOT EXISTS tool_performance_log (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Execution Context
    session_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100),
    question TEXT NOT NULL,
    question_type ENUM('list', 'qa', 'error_code', 'how_to', 'keyword', 'concept') NOT NULL,

    -- Tool Execution Details
    tool_name VARCHAR(100) NOT NULL,
    execution_order INT NOT NULL,  -- 1st tool, 2nd tool (fallback), etc.
    is_fallback BOOLEAN DEFAULT FALSE,

    -- Performance Metrics
    doc_count INT DEFAULT 0,
    avg_score FLOAT DEFAULT 0.0,
    execution_time FLOAT NOT NULL,  -- seconds
    success BOOLEAN NOT NULL,

    -- Quality Metrics
    relevance_score FLOAT,  -- Future: semantic relevance
    user_feedback ENUM('positive', 'negative', 'neutral'),

    -- Error Tracking
    error_message TEXT,
    error_type VARCHAR(100),

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Indexes for fast queries
    INDEX idx_tool_name (tool_name),
    INDEX idx_question_type (question_type),
    INDEX idx_success (success),
    INDEX idx_created_at (created_at),
    INDEX idx_session (session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Aggregated Tool Performance Statistics
CREATE TABLE IF NOT EXISTS tool_performance_stats (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Dimensions
    tool_name VARCHAR(100) NOT NULL,
    question_type ENUM('list', 'qa', 'error_code', 'how_to', 'keyword', 'concept'),

    -- Aggregated Metrics (last 30 days)
    total_executions INT DEFAULT 0,
    successful_executions INT DEFAULT 0,
    failed_executions INT DEFAULT 0,
    success_rate FLOAT DEFAULT 0.0,

    avg_doc_count FLOAT DEFAULT 0.0,
    avg_execution_time FLOAT DEFAULT 0.0,
    avg_relevance_score FLOAT,

    -- User Satisfaction
    positive_feedback INT DEFAULT 0,
    negative_feedback INT DEFAULT 0,
    satisfaction_rate FLOAT DEFAULT 0.0,

    -- Last Update
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Unique constraint
    UNIQUE KEY unique_tool_question (tool_name, question_type),

    -- Indexes
    INDEX idx_success_rate (success_rate),
    INDEX idx_tool_name (tool_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tool Selection Patterns (learned patterns)
CREATE TABLE IF NOT EXISTS tool_selection_patterns (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Pattern Definition
    pattern_name VARCHAR(200) NOT NULL,
    question_pattern TEXT NOT NULL,  -- Regex or keywords
    question_type ENUM('list', 'qa', 'error_code', 'how_to', 'keyword', 'concept'),

    -- Recommended Strategy
    primary_tool VARCHAR(100) NOT NULL,
    fallback_tools JSON,  -- Array of fallback tool names

    -- Pattern Performance
    times_used INT DEFAULT 0,
    success_rate FLOAT DEFAULT 0.0,
    avg_execution_time FLOAT DEFAULT 0.0,

    -- Learning Metadata
    confidence_score FLOAT DEFAULT 0.5,  -- How confident we are in this pattern
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used TIMESTAMP,

    -- Indexes
    INDEX idx_question_type (question_type),
    INDEX idx_confidence (confidence_score),
    INDEX idx_success_rate (success_rate)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Session Context (for multi-turn conversations)
CREATE TABLE IF NOT EXISTS session_context (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Session Details
    session_id VARCHAR(100) NOT NULL UNIQUE,
    user_id VARCHAR(100),

    -- Context Data
    conversation_history JSON,  -- Array of {question, answer, timestamp}
    user_profile JSON,  -- {expertise_level, preferences, topics_of_interest}

    -- Session Metrics
    total_questions INT DEFAULT 0,
    successful_answers INT DEFAULT 0,
    avg_satisfaction FLOAT DEFAULT 0.0,

    -- Timestamps
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_session_id (session_id),
    INDEX idx_user_id (user_id),
    INDEX idx_last_activity (last_activity)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
