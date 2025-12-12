# Chat UI 사용 가이드

## 🎉 구축 완료!

**구현 내용**:
- ✅ Streamlit 기반 Chat UI
- ✅ 실시간 대화형 인터페이스
- ✅ 5단계 피드백 버튼 (매우 만족 ~ 매우 불만족)
- ✅ 사용 통계 대시보드
- ✅ 세션별 피드백 자동 저장
- ✅ 출처 문서 및 디버그 정보 표시

---

## 🚀 실행 방법

### 1. Chat UI 시작

```bash
cd /rsupport/software/R-agent
streamlit run chat_ui.py --server.port 8501
```

**접속**:
```
브라우저: http://localhost:8501
또는
외부 접속: http://[서버IP]:8501
```

---

## 📱 UI 구성

### 왼쪽 사이드바

**📊 사용 통계**:
- 총 검색 횟수
- 피드백 개수
- 평균 만족도
- 피드백률
- 1,000회 달성 진행률

**⚙️ 검색 설정**:
- 최대 반복 횟수 (1-10)
- 디버그 정보 표시 ON/OFF
- 출처 문서 표시 ON/OFF

**🔄 새 대화 시작**: 대화 히스토리 초기화

---

### 메인 화면

**💬 채팅 인터페이스**:
- 사용자 질문 입력
- Agent 답변 표시
- 검색 상세 정보 (접을 수 있음)
- 출처 문서 (접을 수 있음)

**피드백 버튼** (각 답변마다):
```
👍 매우 만족  |  🙂 만족  |  😐 보통  |  👎 불만족  |  😡 매우 불만족
    (5점)         (4점)      (3점)       (2점)         (1점)
```

---

## 💡 사용 예시

### 1. 질문 입력
```
질문: Docker란 무엇인가요?
```

### 2. 답변 확인
```
📝 답변이 표시됨

🔍 검색 상세 정보:
  - 반복 횟수: 2
  - 문서 수: 10
  - 실행 시간: 24.96s
  - 사용 도구: 1개

📚 출처 문서 (10개):
  [1] redmine_issues
      점수: 17.60 | 미리보기: Docker는 애플리케이션을...
```

### 3. 피드백 제공
```
이 답변이 도움이 되었나요?
👍 매우 만족  |  🙂 만족  |  😐 보통  |  👎 불만족  |  😡 매우 불만족
```

**클릭 시**:
- ✅ 피드백이 DB에 즉시 저장
- ✅ `session_context.avg_satisfaction` 업데이트
- ✅ `conversation_history` JSON에 피드백 추가
- ✅ "✅ 피드백 감사합니다!" 메시지 표시

---

## 📊 저장되는 데이터

### session_context 테이블

**업데이트 필드**:
```sql
avg_satisfaction = 4.5  -- 누적 평균 만족도
last_activity = CURRENT_TIMESTAMP
```

**conversation_history JSON**:
```json
[
  {
    "question": "Docker란 무엇인가요?",
    "answer": "Docker는 애플리케이션을...",
    "timestamp": "2025-11-07T16:04:54.638179",
    "sources_count": 10,
    "sources": [...],
    "metadata": {...},
    "feedback": {  // 🆕 추가됨!
      "satisfaction": 5,
      "is_relevant": true,
      "comment": "매우 만족",
      "timestamp": "2025-11-07T16:10:23.123456"
    }
  }
]
```

---

## 🎯 피드백 수집 목표

### Phase 1: 초기 수집 (0-200회)

**목표**:
- 200회 검색 완료
- 40개 이상 피드백 수집 (20% 이상)
- 피드백률 모니터링

**예상 기간**: 2-4주 (일일 10-15회 사용)

**분석**:
```sql
-- 질문 유형별 만족도
SELECT
    JSON_EXTRACT(conversation_history, '$[0].metadata.question_type') as q_type,
    AVG(avg_satisfaction) as avg_sat,
    COUNT(*) as count
FROM session_context
WHERE avg_satisfaction IS NOT NULL
GROUP BY q_type
ORDER BY avg_sat DESC;

-- 만족도 낮은 답변 분석
SELECT
    session_id,
    JSON_EXTRACT(conversation_history, '$[0].question') as question,
    avg_satisfaction,
    JSON_EXTRACT(conversation_history, '$[0].feedback.comment') as feedback
FROM session_context
WHERE avg_satisfaction < 3
ORDER BY avg_satisfaction ASC
LIMIT 20;
```

---

### Phase 2: 본격 수집 (200-1,000회)

**목표**:
- 1,000회 검색 달성
- 200개 이상 피드백 수집
- 만족도 3.5/5 이상 유지

**분석 포인트**:
1. **고만족 패턴** (4-5점):
   - 어떤 질문 유형이 만족도가 높은가?
   - 어떤 도구가 고품질 답변을 생성하는가?

2. **저만족 패턴** (1-2점):
   - 어떤 질문 유형이 실패하는가?
   - 어떤 도구가 엉뚱한 답변을 하는가?

3. **개선 전략**:
   - 저만족 도구 제외 또는 가중치 하락
   - 고만족 도구 우선 추천

---

## 🔍 모니터링 쿼리

### 실시간 통계

```sql
-- 오늘 피드백 통계
SELECT
    COUNT(*) as today_feedback,
    AVG(avg_satisfaction) as avg_sat,
    SUM(CASE WHEN avg_satisfaction >= 4 THEN 1 ELSE 0 END) as high_sat,
    SUM(CASE WHEN avg_satisfaction <= 2 THEN 1 ELSE 0 END) as low_sat
FROM session_context
WHERE DATE(last_activity) = CURDATE()
    AND avg_satisfaction IS NOT NULL;

-- 피드백 추이 (최근 7일)
SELECT
    DATE(last_activity) as date,
    COUNT(*) as feedback_count,
    AVG(avg_satisfaction) as avg_sat,
    MIN(avg_satisfaction) as min_sat,
    MAX(avg_satisfaction) as max_sat
FROM session_context
WHERE last_activity >= DATE_SUB(NOW(), INTERVAL 7 DAY)
    AND avg_satisfaction IS NOT NULL
GROUP BY DATE(last_activity)
ORDER BY date DESC;

-- 질문 유형별 만족도 분포
SELECT
    CASE
        WHEN avg_satisfaction >= 4.5 THEN '매우 만족 (4.5-5)'
        WHEN avg_satisfaction >= 3.5 THEN '만족 (3.5-4.5)'
        WHEN avg_satisfaction >= 2.5 THEN '보통 (2.5-3.5)'
        WHEN avg_satisfaction >= 1.5 THEN '불만족 (1.5-2.5)'
        ELSE '매우 불만족 (1-1.5)'
    END as satisfaction_level,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM session_context WHERE avg_satisfaction IS NOT NULL), 1) as percentage
FROM session_context
WHERE avg_satisfaction IS NOT NULL
GROUP BY satisfaction_level
ORDER BY avg_satisfaction DESC;
```

---

## ⚠️ 주의사항

### 1. 피드백 중복 방지

- 같은 답변에 여러 번 피드백 불가
- `st.session_state.feedback_given` Set으로 관리
- 이미 피드백 준 경우 "✅ 피드백 감사합니다!" 표시

### 2. 세션 관리

- 각 검색마다 새로운 session_id 생성
- "🔄 새 대화 시작" 버튼으로 히스토리 초기화
- 세션별 피드백 독립적으로 저장

### 3. 통계 새로고침

- "📊 통계 새로고침" 버튼으로 최신 데이터 확인
- 자동 새로고침은 없음 (성능 고려)

---

## 🛠️ 문제 해결

### 포트 충돌 시

```bash
# 다른 포트 사용
streamlit run chat_ui.py --server.port 8502
```

### DB 연결 오류 시

```bash
# settings.py 확인
cat config/settings.py | grep LEARNING_DB

# DB 연결 테스트
python -c "
from repositories.session_context_repository import SessionContextRepository
repo = SessionContextRepository()
print('DB 연결 성공!')
"
```

### Streamlit 재시작

```bash
# Ctrl+C로 종료 후 재시작
streamlit run chat_ui.py --server.port 8501

# 또는 캐시 클리어 후 재시작
streamlit cache clear
streamlit run chat_ui.py --server.port 8501
```

---

## 📈 다음 단계

### 200회 달성 후

1. **피드백 데이터 분석**:
   ```bash
   python -c "
   from repositories.session_context_repository import SessionContextRepository
   import mysql.connector
   from config.settings import settings

   # 만족도 분석 스크립트 실행
   "
   ```

2. **패턴 발견**:
   - 고만족 질문 유형 식별
   - 저만족 도구 제외 검토
   - 개선 방향 수립

### 1,000회 달성 후

1. **use_learning=True 활성화**:
   ```bash
   vi agents/search_agent.py
   # Line 55: self.use_learning = False → True
   ```

2. **품질 기반 성공률 재계산**:
   ```sql
   -- 실제 품질을 반영한 도구 성공률
   -- is_relevant=True인 경우만 성공으로 간주
   ```

3. **모니터링 강화**:
   - 학습 기반 추천 효과 측정
   - A/B 테스트 (학습 ON vs OFF)
   - 지속적 품질 개선

---

**작성일**: 2025-11-07
**상태**: Chat UI 구축 완료, 테스트 준비 완료
**다음 작업**: Chat UI 실행 및 피드백 수집 시작
