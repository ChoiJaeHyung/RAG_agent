# R-Agent Learning Database 설치 가이드

## 📋 개요

R-Agent의 학습 및 성능 추적을 위한 전용 데이터베이스 `r_agent_db` 설치 가이드입니다.

## 🎯 목적

- **도구 성능 추적**: 각 도구의 실행 기록 및 성능 지표 저장
- **학습 기능**: 과거 데이터 기반 최적 도구 선택
- **세션 관리**: 다중 턴 대화 컨텍스트 유지
- **패턴 학습**: 효과적인 도구 선택 패턴 발견 및 적용

## 📊 데이터베이스 구조

```
r_agent_db
├── tool_performance_log       -- 모든 도구 실행 이벤트 기록
├── tool_performance_stats     -- 도구별/질문타입별 집계 통계
├── tool_selection_patterns    -- 학습된 최적 도구 선택 패턴
└── session_context           -- 세션 컨텍스트 및 대화 히스토리
```

## 🚀 설치 방법

### 1단계: 데이터베이스 생성

```bash
# MariaDB 접속
mysql -u rsup -p'rsup#EDC3900' -h 127.0.0.1 -P 9443

# 또는 스크립트 직접 실행
mysql -u rsup -p'rsup#EDC3900' -h 127.0.0.1 -P 9443 < database/01_create_database.sql
```

**실행 결과:**
```
Database created: r_agent_db
Grants assigned to 'rsup'@'%' and 'rsup'@'localhost'
```

### 2단계: 테이블 생성

```bash
mysql -u rsup -p'rsup#EDC3900' -h 127.0.0.1 -P 9443 < database/02_create_tables.sql
```

**실행 결과:**
```
Table created: tool_performance_log
Table created: tool_performance_stats
Table created: tool_selection_patterns
Table created: session_context
Total tables: 4
```

### 3단계: 설치 검증

```bash
# Python 테스트 스크립트 실행
python database/test_learning_db.py
```

**예상 출력:**
```
✅ Learning DB 연결 성공
✅ 테이블 4개 확인
✅ 테스트 데이터 삽입 성공
✅ 테스트 데이터 조회 성공
✅ 테스트 데이터 삭제 성공
✨ 설치 검증 완료!
```

## 🔍 수동 검증

### 데이터베이스 확인
```sql
-- 데이터베이스 존재 확인
SHOW DATABASES LIKE 'r_agent_db';

-- 데이터베이스 선택
USE r_agent_db;

-- 테이블 목록 확인
SHOW TABLES;

-- 테이블 구조 확인
DESC tool_performance_log;
DESC tool_performance_stats;
DESC tool_selection_patterns;
DESC session_context;
```

### 권한 확인
```sql
-- rsup 계정 권한 확인
SHOW GRANTS FOR 'rsup'@'%';
SHOW GRANTS FOR 'rsup'@'localhost';
```

## 📝 테이블 상세 설명

### 1. tool_performance_log
**목적**: 모든 도구 실행 이벤트를 상세히 기록

**주요 컬럼**:
- `session_id`: 세션 식별자
- `question`: 사용자 질문
- `question_type`: 질문 유형 (list, qa, error_code, how_to, keyword, concept)
- `tool_name`: 실행된 도구
- `execution_order`: 실행 순서 (1=primary, 2+=fallback)
- `success`: 성공 여부
- `execution_time`: 실행 시간 (초)
- `doc_count`: 반환된 문서 수

**사용 예시**:
```sql
-- 최근 10개 실행 기록 조회
SELECT * FROM tool_performance_log
ORDER BY created_at DESC
LIMIT 10;

-- 특정 도구의 성공률 계산
SELECT
    tool_name,
    COUNT(*) as total,
    SUM(success) as successes,
    AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) as success_rate
FROM tool_performance_log
WHERE tool_name = 'search_qdrant_semantic'
GROUP BY tool_name;
```

### 2. tool_performance_stats
**목적**: 도구별/질문타입별 집계 통계 (최근 30일)

**주요 컬럼**:
- `tool_name`: 도구명
- `question_type`: 질문 유형
- `total_executions`: 총 실행 횟수
- `success_rate`: 성공률 (0.0 ~ 1.0)
- `avg_execution_time`: 평균 실행 시간

**사용 예시**:
```sql
-- 질문 유형별 최고 성능 도구 찾기
SELECT
    question_type,
    tool_name,
    success_rate,
    total_executions
FROM tool_performance_stats
WHERE total_executions >= 10
ORDER BY question_type, success_rate DESC;
```

### 3. tool_selection_patterns
**목적**: 학습된 최적 도구 선택 패턴 저장

**주요 컬럼**:
- `pattern_name`: 패턴 이름
- `question_pattern`: 질문 매칭 패턴
- `primary_tool`: 1차 추천 도구
- `fallback_tools`: 폴백 도구 배열 (JSON)
- `confidence_score`: 신뢰도 (0.0 ~ 1.0)

**사용 예시**:
```sql
-- 고신뢰도 패턴 조회
SELECT * FROM tool_selection_patterns
WHERE confidence_score >= 0.8
ORDER BY success_rate DESC;
```

### 4. session_context
**목적**: 세션 컨텍스트 및 다중 턴 대화 관리

**주요 컬럼**:
- `session_id`: 세션 식별자
- `conversation_history`: 대화 히스토리 (JSON)
- `user_profile`: 사용자 프로필 (JSON)
- `total_questions`: 총 질문 수
- `avg_satisfaction`: 평균 만족도

## 🔧 유지보수

### 통계 업데이트
```python
from repositories.tool_performance_repository import ToolPerformanceRepository

repo = ToolPerformanceRepository()
repo.update_aggregated_stats(days_back=30)
```

### 오래된 로그 삭제
```sql
-- 90일 이상 된 로그 삭제
DELETE FROM tool_performance_log
WHERE created_at < DATE_SUB(NOW(), INTERVAL 90 DAY);
```

### 백업
```bash
# 데이터베이스 전체 백업
mysqldump -u rsup -p'rsup#EDC3900' -h 127.0.0.1 -P 9443 r_agent_db > r_agent_db_backup.sql

# 복원
mysql -u rsup -p'rsup#EDC3900' -h 127.0.0.1 -P 9443 r_agent_db < r_agent_db_backup.sql
```

## ⚠️ 주의사항

1. **기존 dc_db와 완전히 분리**: 기존 시스템에 영향 없음
2. **동일한 계정 사용**: rsup 계정으로 두 DB 모두 접근
3. **성능 영향 최소화**: 비동기 로깅 권장
4. **개인정보 주의**: user_id는 익명화 추천

## 📈 다음 단계

설치 완료 후:
1. **SearchAgent 통합**: 도구 실행 시 자동 로깅
2. **학습 기능 활성화**: 과거 데이터 기반 도구 선택
3. **대시보드 구축**: 성능 모니터링 시각화
4. **패턴 분석**: 정기적인 패턴 학습 및 적용

## 🆘 문제 해결

### 연결 오류
```
ERROR: Access denied for user 'rsup'@'...'
```
**해결**: 권한 재설정
```sql
GRANT ALL PRIVILEGES ON r_agent_db.* TO 'rsup'@'%';
FLUSH PRIVILEGES;
```

### 테이블 생성 실패
```
ERROR: Table already exists
```
**해결**: DROP TABLE 후 재생성 또는 스키마 수정

### Python 연결 오류
```
ModuleNotFoundError: No module named 'mysql.connector'
```
**해결**:
```bash
pip install mysql-connector-python
```

## 📚 참고자료

- [MariaDB 공식 문서](https://mariadb.org/documentation/)
- [R-Agent 아키텍처 문서](../claudedocs/ai_agent_enhancement_analysis.md)
- [도구 성능 추적 가이드](../claudedocs/enhancement_summary.md)
