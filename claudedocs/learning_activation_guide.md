# 학습 기능 활성화 가이드

## 📋 개요

**현재 상태**: `use_learning = False` (비활성화)
**활성화 시기**: 1,000회 검색 후
**활성화 효과**: 도구 선택 패턴 학습 및 최적화

---

## 🎯 활성화 전략

### Phase 1: 데이터 수집 (현재)
```
검색 횟수: 0 → 1,000회
기간: 1-2주 (예상)
목적: 실제 사용 패턴 축적
```

**활성화된 기능**:
- ✅ 하이브리드 외부 지식 시스템
- ✅ LLM 문서 충분성 판단
- ✅ Targeted external knowledge

**비활성화된 기능**:
- ❌ 도구 성능 추적 (`tool_performance_log`)
- ❌ 최적 도구 추천
- ❌ 학습 기반 도구 선택

---

### Phase 2: 학습 활성화 (1,000회 후)
```
검색 횟수: 1,000회 이상
use_learning: False → True
효과: 도구 선택 자동 최적화
```

**새로 활성화될 기능**:
- ✅ 모든 도구 실행 추적
- ✅ 질문 유형별 최적 도구 학습
- ✅ 실패 패턴 분석
- ✅ 자동 폴백 전략 개선

---

## 📊 진행 상황 확인

### 사용 횟수 체크

```bash
# 스크립트 실행 권한 부여
chmod +x scripts/check_usage_count.py

# 사용 횟수 확인
python scripts/check_usage_count.py
```

**출력 예시**:
```
================================================================================
  🔍 R-Agent 사용 횟수 확인
================================================================================

📊 사용 통계:
  - 전체 검색 횟수: 342회
  - 오늘 검색 횟수: 28회
  - 이번 주 검색 횟수: 156회
  - 일일 평균 (최근 7일): 22.3회

🎯 1,000회 달성 예상:
  - 남은 검색 횟수: 658회
  - 예상 소요 일수: 29.5일
  - 예상 달성일: 2025-12-06

📅 최근 7일 일별 통계:
  2025-11-07:  28회 ████████████████████████████
  2025-11-06:  31회 ███████████████████████████████
  2025-11-05:  19회 ███████████████████
  ...

================================================================================
  ⏳ 데이터 수집 중: 34.2% (342/1,000회)
  - use_learning은 비활성화 상태 유지
================================================================================
```

---

## 🔧 활성화 방법

### 1단계: 1,000회 달성 확인

```bash
python scripts/check_usage_count.py
```

**확인 사항**:
- ✅ 전체 검색 횟수 >= 1,000회
- ✅ 다양한 질문 유형 포함
- ✅ 시스템 안정적 운영

---

### 2단계: 코드 수정

```bash
# 파일 편집
vi agents/search_agent.py

# 또는
nano agents/search_agent.py
```

**변경 내용**:
```python
# 기존 (Line ~80)
def __init__(self):
    # ...
    self.perf_repo = ToolPerformanceRepository()
    self.session_id = None
    self.use_learning = False  # ← 이 줄 변경

# 변경 후
def __init__(self):
    # ...
    self.perf_repo = ToolPerformanceRepository()
    self.session_id = None
    self.use_learning = True  # ✅ 활성화
```

---

### 3단계: 서버 재시작

```bash
# FastAPI 서버 재시작
# 방법 1: systemd 사용 시
sudo systemctl restart r-agent

# 방법 2: 프로세스 재시작
pkill -f "uvicorn main:app"
nohup uvicorn main:app --host 0.0.0.0 --port 8001 &

# 방법 3: Docker 사용 시
docker restart r-agent-container
```

---

### 4단계: 활성화 확인

```bash
# 테스트 검색 실행
python -c "
from agents.search_agent import SearchAgent
agent = SearchAgent()
print(f'use_learning: {agent.use_learning}')
result = agent.search('테스트 질문', max_iterations=1)
"
```

**예상 출력**:
```
use_learning: True
[2025-11-07 15:30:00] [INFO] [rag_agent] ✓ SearchAgent initialized with 7 tools
...
```

**DB 확인**:
```sql
-- tool_performance_log에 데이터 쌓이는지 확인
SELECT COUNT(*) FROM r_agent_db.tool_performance_log
WHERE created_at > NOW() - INTERVAL 5 MINUTE;

-- 최근 로그 확인
SELECT * FROM r_agent_db.tool_performance_log
ORDER BY created_at DESC LIMIT 5;
```

---

## 📈 활성화 후 기대 효과

### 1. 도구 선택 최적화

**현재 (비활성화)**:
```python
# LLM이 매번 도구 선택
# 과거 성공 패턴 고려 안 함
```

**활성화 후**:
```python
# 질문 유형별 최적 도구 자동 추천
# 성공률 높은 도구 우선 선택
# 실패 패턴 회피
```

**예시**:
```
질문: "에러 코드 1234 해결 방법"
과거 데이터: search_mariadb_by_keyword 성공률 92%
→ 해당 도구 우선 추천
```

---

### 2. 자동 폴백 전략 개선

**현재**:
```python
# 하드코딩된 폴백 순서
# Qdrant → MariaDB → Elasticsearch
```

**활성화 후**:
```python
# 질문 유형별 최적 폴백 순서 학습
# "에러 코드" → MariaDB 먼저 시도
# "개념 설명" → Qdrant 먼저 시도
```

---

### 3. 성능 인사이트

**수집 데이터**:
- 질문 유형별 도구 성공률
- 평균 실행 시간
- 문서 품질 (평균 점수, 문서 수)
- 폴백 발생률

**활용**:
```sql
-- 질문 유형별 최적 도구 분석
SELECT
    question_type,
    tool_name,
    AVG(avg_score) as avg_quality,
    AVG(execution_time) as avg_time,
    COUNT(*) as usage_count
FROM tool_performance_log
WHERE success = 1
GROUP BY question_type, tool_name
ORDER BY question_type, avg_quality DESC;
```

---

## 🔍 모니터링

### 일일 확인

```bash
# 오늘 로깅된 실행 수
echo "SELECT COUNT(*) as today_logs FROM r_agent_db.tool_performance_log WHERE DATE(created_at) = CURDATE();" | mysql -u rsup -p
```

### 주간 리포트

```sql
-- 주간 통계
SELECT
    DATE(created_at) as date,
    question_type,
    COUNT(*) as executions,
    AVG(execution_time) as avg_time,
    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) / COUNT(*) * 100 as success_rate
FROM tool_performance_log
WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
GROUP BY DATE(created_at), question_type
ORDER BY date DESC, question_type;
```

---

## ⚠️ 주의사항

### DB 부하 증가

**활성화 전**:
- 검색당 DB INSERT: 0회

**활성화 후**:
- 검색당 DB INSERT: 평균 3-5회 (도구 실행 수만큼)

**대응**:
- DB 연결 풀 크기 확인 (현재: 10)
- 인덱스 최적화 (`session_id`, `created_at`)
- 배치 INSERT 고려 (향후)

---

### 디스크 사용량

**예상 증가량**:
- 1회 검색 = 평균 3개 로그
- 1개 로그 = 약 500 bytes
- 1,000회 검색 = 1.5 MB

**월간 예상 (10,000회)**:
- 약 15 MB

**대응**:
- 정기적 로그 아카이빙 (3개월 이상 데이터)
- 파티셔닝 고려 (월별)

---

## 🎯 활성화 체크리스트

### 활성화 전
- [ ] 1,000회 이상 검색 완료 확인
- [ ] 시스템 안정성 확인 (에러율 <1%)
- [ ] DB 연결 상태 정상
- [ ] 디스크 공간 충분 (>1GB 여유)

### 활성화 시
- [ ] `use_learning = True` 변경
- [ ] 서버 재시작
- [ ] 활성화 확인 (로그 출력)
- [ ] DB 로깅 확인

### 활성화 후
- [ ] 첫 24시간 모니터링
- [ ] DB 부하 체크
- [ ] 성능 저하 없음 확인
- [ ] 1주일 후 학습 효과 분석

---

## 📝 롤백 방법

**문제 발생 시**:

```bash
# 1. 코드 되돌리기
vi agents/search_agent.py
# self.use_learning = True → False

# 2. 서버 재시작
sudo systemctl restart r-agent

# 3. 확인
python -c "
from agents.search_agent import SearchAgent
agent = SearchAgent()
print(f'use_learning: {agent.use_learning}')
"
# 출력: use_learning: False
```

**로그 삭제 (선택)**:
```sql
-- 활성화 후 생성된 로그만 삭제
DELETE FROM r_agent_db.tool_performance_log
WHERE created_at >= '2025-11-XX 00:00:00';  -- 활성화 시점
```

---

## 🚀 다음 단계

### 활성화 후 1주일
- [ ] 학습 데이터 분석
- [ ] 질문 유형별 최적 도구 파악
- [ ] 성공률 개선 확인

### 활성화 후 1개월
- [ ] `_get_optimal_tool_for_question()` 활성화
- [ ] 자동 도구 추천 적용
- [ ] A/B 테스트 (학습 vs 비학습)

---

**작성일**: 2025-11-07
**활성화 예정일**: 1,000회 검색 달성 시
**담당자**: TBD
