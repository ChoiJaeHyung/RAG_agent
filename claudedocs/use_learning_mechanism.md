# use_learning 학습 메커니즘 상세 가이드

## 📋 현재 상태 요약

**설정**: `use_learning = False` (비활성화)
**활성화 시점**: 1,000회 검색 후
**현재 진행**: 5회 / 1,000회 (0.5%)

---

## 🎯 use_learning이 제어하는 기능

### ❌ 비활성화된 기능 (use_learning = False)

**1. 학습 기반 도구 추천** (search_agent.py:1199)
```python
def _get_optimal_tool_for_question(self, question_type: str) -> Optional[str]:
    """질문 유형에 가장 적합한 도구를 학습 데이터로 추천"""
    if not self.use_learning:
        return None  # ❌ 추천 비활성화

    # ✅ use_learning=True일 때만 실행
    best_tool = self.perf_repo.get_best_tool_for_question_type(
        question_type=question_type,
        min_executions=10  # 최소 10회 실행 데이터 필요
    )

    if best_tool:
        tool_name, success_rate = best_tool
        if success_rate >= 0.7:  # 성공률 70% 이상만 추천
            return tool_name
```

**영향**:
- 현재는 LLM이 매번 도구를 자유롭게 선택
- 과거 성공 패턴을 고려하지 않음
- 실패했던 도구도 재시도 가능

---

### ✅ 항상 활성화된 기능 (use_learning 무관)

**1. Tool 실행 로깅** (search_agent.py:1119, 1146, 1168)
```python
def _execute_tool_with_tracking(self, tool_name, ...):
    """도구 실행 + 성능 추적"""

    start_time = time.time()

    # 도구 실행
    result = tool_registry.execute_tool(tool_name, tool_args)

    execution_time = time.time() - start_time

    # ✅ use_learning과 무관하게 항상 로깅
    self.perf_repo.log_tool_execution(
        session_id=self.session_id,
        question=question[:200],
        question_type=question_type,
        tool_name=tool_name,
        execution_order=execution_order,
        is_fallback=is_fallback,
        doc_count=len(results),
        avg_score=avg_score,
        execution_time=execution_time,
        success=success,
        error_message=error_msg,
        error_type=error_type
    )
```

**왜 항상 로깅하는가?**
- 1,000회 검색 데이터 수집을 위해
- 활성화 후 즉시 학습 데이터 사용 가능
- 데이터 수집과 활용을 분리

---

## 🗄️ 데이터베이스 테이블 역할

### 1. tool_performance_log (로그 테이블)
**역할**: 모든 도구 실행 이벤트 기록 (Raw Data)

**저장 시점**:
- ✅ **항상** (use_learning=False일 때도 저장됨!)
- 매 도구 실행마다 1개 레코드 생성
- 성공/실패 모두 기록

**저장 데이터**:
```sql
CREATE TABLE tool_performance_log (
    id INT PRIMARY KEY AUTO_INCREMENT,
    session_id VARCHAR(36),           -- 검색 세션 ID
    user_id VARCHAR(50),               -- 사용자 ID (선택)
    question TEXT,                     -- 사용자 질문 (200자 제한)
    question_type VARCHAR(50),         -- 질문 유형 (concept, qa, list, error_code, how_to)
    tool_name VARCHAR(100),            -- 실행된 도구명
    execution_order INT,               -- 실행 순서 (1=primary, 2+=fallback)
    is_fallback BOOLEAN,               -- 폴백 실행 여부
    doc_count INT,                     -- 반환된 문서 수
    avg_score FLOAT,                   -- 평균 관련성 점수
    execution_time FLOAT,              -- 실행 시간 (초)
    success BOOLEAN,                   -- 성공 여부
    error_message TEXT,                -- 에러 메시지 (실패 시)
    error_type VARCHAR(100),           -- 에러 유형 (실패 시)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**예시 데이터**:
| session_id | question | question_type | tool_name | execution_order | is_fallback | doc_count | avg_score | execution_time | success |
|-----------|----------|---------------|-----------|----------------|-------------|-----------|-----------|----------------|---------|
| abc-123 | Docker란 무엇인가요? | concept | search_qdrant_semantic | 1 | 0 | 0 | 0.0 | 6.8 | 0 |
| abc-123 | Docker란 무엇인가요? | concept | search_mariadb_by_keyword | 1 | 1 | 0 | 0.0 | 0.5 | 0 |
| abc-123 | Docker란 무엇인가요? | concept | search_elasticsearch_bm25 | 1 | 1 | 10 | 12.79 | 0.3 | 1 |

**용도**:
- 🔍 디버깅: 어떤 도구가 실행되었는지 추적
- 📊 분석: 도구별 성능 추이 파악
- 🎯 학습: tool_performance_stats 집계의 원천 데이터

---

### 2. tool_performance_stats (집계 테이블)
**역할**: 질문 유형 × 도구별 성능 통계 (Aggregated Data)

**저장 시점**:
- ✅ **수동 집계** (tool_performance_log 기반)
- 주기적으로 `update_aggregated_stats()` 실행 필요
- 최근 30일 데이터 기준 집계

**저장 데이터**:
```sql
CREATE TABLE tool_performance_stats (
    id INT PRIMARY KEY AUTO_INCREMENT,
    tool_name VARCHAR(100),
    question_type VARCHAR(50),
    total_executions INT,              -- 총 실행 횟수
    successful_executions INT,         -- 성공 횟수
    failed_executions INT,             -- 실패 횟수
    success_rate FLOAT,                -- 성공률 (0.0 ~ 1.0)
    avg_doc_count FLOAT,               -- 평균 문서 수
    avg_execution_time FLOAT,          -- 평균 실행 시간
    updated_at TIMESTAMP,
    UNIQUE KEY (tool_name, question_type)
);
```

**예시 데이터**:
| tool_name | question_type | total_executions | successful_executions | success_rate | avg_doc_count | avg_execution_time |
|-----------|---------------|------------------|----------------------|--------------|---------------|-------------------|
| search_elasticsearch_bm25 | concept | 250 | 230 | 0.92 | 8.5 | 0.35 |
| search_qdrant_semantic | concept | 180 | 95 | 0.53 | 4.2 | 1.2 |
| search_mariadb_by_keyword | concept | 120 | 78 | 0.65 | 3.1 | 0.18 |
| search_elasticsearch_bm25 | error_code | 180 | 165 | 0.92 | 12.3 | 0.28 |
| search_mariadb_by_keyword | error_code | 220 | 210 | 0.95 | 15.8 | 0.22 |

**용도**:
- 💡 **도구 추천**: `get_best_tool_for_question_type()`에서 사용
- 🔗 **폴백 체인**: `get_tool_fallback_chain()`에서 사용
- 📈 **모니터링**: 대시보드에서 성능 비교

**집계 로직**:
```python
# tool_performance_repository.py:113
def update_aggregated_stats(self, days_back: int = 30):
    """최근 30일 데이터로 집계 통계 업데이트"""
    # tool_performance_log → tool_performance_stats 변환
    INSERT INTO tool_performance_stats (...)
    SELECT
        tool_name,
        question_type,
        COUNT(*) as total_executions,
        SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) as successful_executions,
        AVG(CASE WHEN success = TRUE THEN 1.0 ELSE 0.0 END) as success_rate,
        AVG(doc_count) as avg_doc_count,
        AVG(execution_time) as avg_execution_time
    FROM tool_performance_log
    WHERE created_at >= (NOW() - INTERVAL 30 DAY)
    GROUP BY tool_name, question_type
    ON DUPLICATE KEY UPDATE ...
```

---

### 3. tool_selection_patterns (패턴 학습 테이블)
**역할**: 질문 패턴 → 추천 도구 매핑 (Learned Patterns)

**저장 시점**:
- ✅ **수동 패턴 저장** (선택적)
- 특정 패턴을 발견했을 때 명시적으로 저장
- 예: "에러 코드 XXXX" → MariaDB 우선

**저장 데이터**:
```sql
CREATE TABLE tool_selection_patterns (
    id INT PRIMARY KEY AUTO_INCREMENT,
    pattern_name VARCHAR(100) UNIQUE,  -- 패턴 이름
    question_pattern VARCHAR(255),     -- 질문 매칭 패턴 (키워드/정규식)
    question_type VARCHAR(50),         -- 질문 유형
    primary_tool VARCHAR(100),         -- 1차 추천 도구
    fallback_tools JSON,               -- 폴백 도구 리스트
    confidence_score FLOAT,            -- 패턴 신뢰도 (0-1)
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

**예시 데이터**:
| pattern_name | question_pattern | question_type | primary_tool | fallback_tools | confidence_score |
|-------------|------------------|---------------|--------------|----------------|-----------------|
| redmine_issue_pattern | REDMINE.*#\d+ | keyword | search_mariadb_by_keyword | ["search_elasticsearch_bm25"] | 0.95 |
| error_code_pattern | 에러.*코드.*\d+ | error_code | search_mariadb_by_keyword | ["search_elasticsearch_bm25"] | 0.88 |
| concept_explanation | (이란\|무엇)\? | concept | search_elasticsearch_bm25 | ["search_qdrant_semantic"] | 0.82 |

**용도**:
- 🎯 **명시적 패턴 매칭**: 특정 질문 형태에 대한 확실한 전략
- 📚 **지식 축적**: 발견된 효과적 패턴 저장
- 🔄 **우선 순위**: 통계 기반 추천보다 우선 적용 가능

---

### 4. session_context (대화 히스토리 테이블)
**역할**: 질문 + 답변 + 출처 저장 (대화 전체 맥락)

**저장 시점**:
- ✅ **항상** (use_learning과 완전 무관)
- 매 검색마다 conversation_history JSON에 추가

**저장 데이터**:
```sql
CREATE TABLE session_context (
    id INT PRIMARY KEY AUTO_INCREMENT,
    session_id VARCHAR(36) UNIQUE,
    user_id VARCHAR(50),
    conversation_history JSON,         -- 질문+답변 쌍 배열
    total_questions INT,               -- 총 질문 수
    successful_answers INT,            -- 성공한 답변 수
    avg_satisfaction FLOAT,            -- 평균 만족도 (선택)
    started_at TIMESTAMP,
    last_activity TIMESTAMP
);
```

**conversation_history JSON 구조**:
```json
[
  {
    "question": "Docker란 무엇인가요?",
    "answer": "Docker는 애플리케이션을 컨테이너라는...",
    "timestamp": "2025-11-07T16:04:54.638179",
    "sources_count": 10,
    "sources": [
      {"file_name": "redmine_issues", "score": 17.60},
      {"file_name": "redmine_issues", "score": 13.75}
    ],
    "metadata": {
      "question_type": "concept",
      "iterations": 2,
      "execution_time": 24.96,
      "tools_used": ["search_elasticsearch_bm25"],
      "total_documents": 10
    }
  }
]
```

**용도**:
- 💬 **대화 컨텍스트**: 다음 질문 시 이전 맥락 참조
- 📊 **답변 품질 분석**: 답변 길이, 출처 품질 평가
- 😊 **사용자 만족도**: 재질문 비율, 세션 지속 시간 분석

---

## 🔄 use_learning = True 활성화 시 동작 흐름

### 검색 플로우 비교

#### 현재 (use_learning = False)
```
1. 사용자 질문 → "Docker란 무엇인가요?"
2. 질문 분석 → question_type = "concept"
3. LLM 도구 선택 → search_qdrant_semantic 선택
4. 도구 실행 → 실패 (0개 문서)
5. 로그 저장 → tool_performance_log에 실패 기록 ✅
6. 자동 폴백 → search_mariadb_by_keyword 시도
7. 도구 실행 → 실패 (0개 문서)
8. 로그 저장 → tool_performance_log에 실패 기록 ✅
9. 자동 폴백 → search_elasticsearch_bm25 시도
10. 도구 실행 → 성공 (10개 문서)
11. 로그 저장 → tool_performance_log에 성공 기록 ✅
12. 답변 생성 → "Docker는 애플리케이션을..."
13. 대화 저장 → session_context에 저장 ✅
```

**총 실행 시간**: 24.96초 (실패한 도구들까지 모두 시도)

---

#### 활성화 후 (use_learning = True)
```
1. 사용자 질문 → "Docker란 무엇인가요?"
2. 질문 분석 → question_type = "concept"
3. 학습 데이터 조회 💡 → _get_optimal_tool_for_question("concept")

   DB 쿼리:
   SELECT tool_name, success_rate FROM tool_performance_stats
   WHERE question_type = 'concept'
     AND total_executions >= 10
   ORDER BY success_rate DESC, avg_execution_time ASC
   LIMIT 1

   결과: search_elasticsearch_bm25 (성공률 92%, 평균 0.35초)

4. 시스템 메시지 생성 💡:
   "💡 학습 추천: 'concept' → search_elasticsearch_bm25 (성공률 92%)"

5. LLM에 추천 전달:
   {
     "role": "system",
     "content": "과거 데이터에 따르면 이 질문 유형에는 search_elasticsearch_bm25가 가장 효과적입니다 (성공률 92%). 이 도구를 우선 사용하는 것을 권장합니다."
   }

6. LLM 도구 선택 → search_elasticsearch_bm25 선택 (추천 수용)
7. 도구 실행 → 성공 (10개 문서)
8. 로그 저장 → tool_performance_log에 성공 기록 ✅
9. 답변 생성 → "Docker는 애플리케이션을..."
10. 대화 저장 → session_context에 저장 ✅
```

**총 실행 시간**: 약 10초 (실패 도구 건너뛰고 바로 성공)
**시간 단축**: 60% 개선 (24.96s → 10s)

---

### 학습 기반 추천 상세 로직

**1. 최적 도구 추천** (tool_performance_repository.py:167)
```python
def get_best_tool_for_question_type(
    self,
    question_type: str,
    min_executions: int = 10
) -> Optional[Tuple[str, float]]:
    """
    질문 유형에 가장 적합한 도구 찾기

    조건:
    - 최소 10회 이상 실행된 도구만 고려 (신뢰도 확보)
    - 성공률 우선 정렬
    - 동일 성공률이면 실행 시간 빠른 도구 선택
    """
    query = """
        SELECT tool_name, success_rate, total_executions
        FROM tool_performance_stats
        WHERE question_type = %s
          AND total_executions >= %s
        ORDER BY success_rate DESC, avg_execution_time ASC
        LIMIT 1
    """
    # 예: ('concept', 10)

    # 반환: ('search_elasticsearch_bm25', 0.92)
```

**2. 폴백 체인 추천** (tool_performance_repository.py:215)
```python
def get_tool_fallback_chain(
    self,
    question_type: str,
    max_tools: int = 3
) -> List[str]:
    """
    추천 폴백 순서 생성

    조건:
    - 최소 5회 이상 실행된 도구만 고려
    - 성공률 높은 순서대로 최대 3개
    """
    query = """
        SELECT tool_name FROM tool_performance_stats
        WHERE question_type = %s
          AND total_executions >= 5
        ORDER BY success_rate DESC, avg_execution_time ASC
        LIMIT %s
    """
    # 예: ('error_code', 3)

    # 반환: [
    #   'search_mariadb_by_keyword',      # 95% 성공률
    #   'search_elasticsearch_bm25',      # 92% 성공률
    #   'search_qdrant_semantic'          # 78% 성공률
    # ]
```

**3. LLM에 추천 전달** (search_agent.py:1207-1214)
```python
optimal_tool = self._get_optimal_tool_for_question(question_type)

if optimal_tool:
    logger.info(
        f"💡 학습 추천: '{question_type}' → {optimal_tool} "
        f"(성공률 {success_rate:.2%})"
    )
    # LLM 프롬프트에 추가:
    # "과거 데이터에 따르면 {optimal_tool}이 가장 효과적입니다"
```

---

## 📊 학습 효과 예측

### 시나리오: 1,000회 검색 후 데이터 분석

**가정**:
- 1,000회 검색 완료
- 질문 유형 분포:
  - concept: 300회
  - error_code: 250회
  - qa: 200회
  - how_to: 150회
  - list: 100회

**학습 결과 예시** (tool_performance_stats):

| question_type | tool_name | total_exec | success_rate | avg_time |
|--------------|-----------|-----------|--------------|----------|
| concept | search_elasticsearch_bm25 | 180 | 0.92 | 0.35s |
| concept | search_qdrant_semantic | 90 | 0.53 | 1.20s |
| concept | search_mariadb_by_keyword | 30 | 0.65 | 0.18s |
| error_code | search_mariadb_by_keyword | 150 | 0.95 | 0.22s |
| error_code | search_elasticsearch_bm25 | 80 | 0.92 | 0.28s |
| error_code | search_qdrant_semantic | 20 | 0.45 | 0.95s |
| qa | search_elasticsearch_bm25 | 120 | 0.88 | 0.42s |
| qa | search_qdrant_semantic | 60 | 0.72 | 1.05s |
| qa | search_mariadb_by_keyword | 20 | 0.55 | 0.25s |

**활성화 후 개선 효과**:

1. **실행 시간 단축**:
   - 평균 25초 → 12초 (52% 개선)
   - 실패 도구 시도 감소

2. **성공률 향상**:
   - 첫 시도 성공률: 65% → 90%
   - 폴백 발생률: 35% → 10%

3. **비용 절감**:
   - LLM 토큰 사용량 감소 (도구 실행 실패 재시도 감소)
   - 서버 리소스 효율화

4. **사용자 경험**:
   - 응답 속도 개선
   - 더 정확한 문서 검색

---

## 🚀 활성화 시나리오

### 시나리오 1: "Docker 설치 방법" 질문

**질문 분석**:
```python
question_type = _analyze_question_type("Docker 설치 방법")
# 결과: "how_to"
```

**use_learning = False 시**:
```
LLM 선택: search_qdrant_semantic (의미 유사도 기반)
결과: 실패 (문서 0개)
폴백: search_mariadb_by_keyword
결과: 성공 (5개 문서)
총 시간: 18초
```

**use_learning = True 시**:
```
학습 조회:
  SELECT * FROM tool_performance_stats
  WHERE question_type = 'how_to'
  ORDER BY success_rate DESC
  LIMIT 1

  결과: search_mariadb_by_keyword (성공률 93%)

시스템 메시지:
  "💡 'how_to' 질문에는 search_mariadb_by_keyword가 가장 효과적 (93%)"

LLM 선택: search_mariadb_by_keyword (추천 수용)
결과: 성공 (5개 문서)
총 시간: 8초
```

**개선**: 55% 시간 단축 (18초 → 8초)

---

### 시나리오 2: "REDMINE #148087" 키워드 검색

**질문 분석**:
```python
question_type = _analyze_question_type("REDMINE #148087")
# 결과: "keyword"
```

**tool_selection_patterns 패턴 매칭**:
```sql
SELECT * FROM tool_selection_patterns
WHERE question_pattern LIKE '%REDMINE%'

결과:
  pattern_name: 'redmine_issue_pattern'
  primary_tool: 'search_mariadb_by_keyword'
  confidence_score: 0.95
```

**use_learning = True 시**:
```
패턴 매칭 → search_mariadb_by_keyword 직접 추천
LLM 건너뛰고 즉시 실행 가능
결과: 성공 (8개 문서)
총 시간: 3초
```

**개선**: 패턴 기반 즉시 실행으로 극대화 효율

---

## 🛠️ 활성화 후 운영 전략

### 1. 주기적 집계 (크론잡)
```bash
# 매일 새벽 2시 통계 업데이트
0 2 * * * cd /rsupport/software/R-agent && python -c "
from repositories.tool_performance_repository import ToolPerformanceRepository
repo = ToolPerformanceRepository()
repo.update_aggregated_stats(days_back=30)  # 최근 30일 집계
"
```

### 2. 패턴 발견 및 저장
```python
# 특정 패턴 발견 시 수동 저장
from repositories.tool_performance_repository import ToolPerformanceRepository

repo = ToolPerformanceRepository()

# "에러 코드" 패턴 저장
repo.learn_pattern(
    pattern_name='error_code_pattern',
    question_pattern='에러.*코드.*\d+',
    question_type='error_code',
    primary_tool='search_mariadb_by_keyword',
    fallback_tools=['search_elasticsearch_bm25'],
    confidence_score=0.95
)
```

### 3. 성능 모니터링 쿼리
```sql
-- 질문 유형별 최적 도구 확인
SELECT
    question_type,
    tool_name,
    total_executions,
    success_rate,
    avg_execution_time
FROM tool_performance_stats
WHERE total_executions >= 10
ORDER BY question_type, success_rate DESC;

-- 도구별 전체 성능 요약
SELECT
    tool_name,
    SUM(total_executions) as total_uses,
    AVG(success_rate) as avg_success_rate,
    AVG(avg_execution_time) as avg_time
FROM tool_performance_stats
GROUP BY tool_name
ORDER BY total_uses DESC;

-- 최근 7일 도구 실행 추이
SELECT
    DATE(created_at) as date,
    tool_name,
    COUNT(*) as executions,
    AVG(CASE WHEN success = 1 THEN 1.0 ELSE 0.0 END) as success_rate
FROM tool_performance_log
WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
GROUP BY DATE(created_at), tool_name
ORDER BY date DESC, executions DESC;
```

### 4. A/B 테스트 (선택)
```python
# 50%는 학습 추천 사용, 50%는 LLM 자유 선택
import random

class SearchAgent:
    def _get_optimal_tool_for_question(self, question_type):
        if not self.use_learning:
            return None

        # A/B 테스트: 50% 확률로 추천 사용
        if random.random() < 0.5:
            return None  # B 그룹: LLM 자유 선택

        # A 그룹: 학습 추천 사용
        return self.perf_repo.get_best_tool_for_question_type(...)
```

---

## 📝 정리: 4개 테이블의 역할

| 테이블 | 저장 시점 | use_learning 의존 | 역할 | 크기 예상 |
|-------|---------|-----------------|------|---------|
| **tool_performance_log** | ✅ 항상 | ❌ 독립적 | 모든 도구 실행 기록 | 1,000회 = ~3,000 rows |
| **tool_performance_stats** | 수동 집계 | ❌ 독립적 | 질문 유형×도구 통계 | ~50 rows (고정) |
| **tool_selection_patterns** | 수동 저장 | ❌ 독립적 | 학습된 질문 패턴 | ~10-20 rows |
| **session_context** | ✅ 항상 | ❌ 독립적 | 질문+답변 히스토리 | 1,000회 = 1,000 rows |

---

## 🎯 핵심 정리

### use_learning = False (현재)
```
✅ 수집 중:
  - tool_performance_log (모든 도구 실행 기록)
  - session_context (모든 대화 히스토리)

❌ 비활성화:
  - 학습 기반 도구 추천
  - 최적 도구 우선 선택
  - 폴백 체인 최적화

목적: 1,000회 검색으로 신뢰도 높은 데이터 수집
```

### use_learning = True (1,000회 후)
```
✅ 활성화:
  - 질문 유형별 최적 도구 자동 추천
  - 성공률 높은 도구 우선 선택
  - 학습된 폴백 체인 적용
  - 실패 패턴 회피

기대 효과:
  - 실행 시간 50% 단축
  - 첫 시도 성공률 65% → 90%
  - 비용 및 리소스 절감
  - 사용자 경험 개선

지속 수집:
  - tool_performance_log (추가 학습)
  - session_context (대화 품질 분석)
```

---

**작성일**: 2025-11-07
**현재 진행**: 5회 / 1,000회 (0.5%)
**예상 활성화일**: 약 249일 후
