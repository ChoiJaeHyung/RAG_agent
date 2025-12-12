# Chat UI 테스트 가이드

## ✅ 수정 완료 사항

**문제**: `st.rerun()`이 try-except 블록 내부에 있어서 성공한 검색도 에러로 표시됨
**해결**: `st.rerun()`을 try-except 외부로 이동, 실제 에러 시에만 `st.stop()` 실행

## 🚀 테스트 실행 방법

### 1. Chat UI 시작

```bash
cd /rsupport/software/R-agent
streamlit run chat_ui.py --server.port 8501
```

**접속**: http://localhost:8501

### 2. 기본 테스트 시나리오

#### 시나리오 1: 정상 검색 테스트
```
질문: "Docker란 무엇인가요?"

예상 결과:
✅ 답변이 정상 표시됨
✅ 🔍 검색 상세 정보 표시 (반복 횟수, 문서 수, 실행 시간)
✅ 📚 출처 문서 표시 (10개)
✅ 피드백 버튼 5개 표시 (👍 매우 만족 ~ 😡 매우 불만족)
❌ 에러 메시지 없음
```

#### 시나리오 2: 피드백 제출 테스트
```
1. 위 검색 완료 후 피드백 버튼 클릭 (예: 🙂 만족)
2. 예상 결과:
   ✅ "✅ 피드백 저장 완료! (만족도: 4/5)" 메시지
   ✅ 피드백 버튼이 "✅ 피드백 감사합니다!"로 변경
   ✅ 같은 답변에 다시 피드백 불가
   ✅ 사이드바 통계 업데이트 (피드백 개수 +1)
```

#### 시나리오 3: 연속 검색 테스트
```
질문 1: "Docker란 무엇인가요?"
→ 답변 확인 → 피드백 제공

질문 2: "Kubernetes 설치 방법"
→ 답변 확인 → 피드백 제공

질문 3: "RVS 로그인 설정"
→ 답변 확인 → 피드백 제공

예상 결과:
✅ 각 질문마다 독립적인 답변 표시
✅ 각 답변마다 독립적인 피드백 버튼
✅ 대화 히스토리에 모든 질문-답변 누적 표시
✅ 사이드바 "현재 세션 검색" 카운트 증가 (3회)
```

#### 시나리오 4: 통계 확인 테스트
```
1. 사이드바에서 통계 확인:
   - 총 검색: 현재 누적 검색 횟수
   - 피드백: 제출된 피드백 개수
   - 평균 만족도: 전체 평균 (X/5)
   - 피드백률: (피드백 / 총 검색) * 100%
   - 진행률: 1,000회 달성률 (%)

2. "📊 통계 새로고침" 버튼 클릭
   ✅ 최신 통계로 업데이트
```

#### 시나리오 5: 세션 초기화 테스트
```
1. "🔄 새 대화 시작" 버튼 클릭

예상 결과:
✅ 대화 히스토리 초기화 (화면 비움)
✅ 현재 세션 검색 카운트 0으로 초기화
✅ 피드백 상태 초기화
✅ 총 검색 통계는 유지 (DB에 저장됨)
```

### 3. 에러 처리 테스트

#### 시나리오 6: DB 연결 오류 시뮬레이션
```
(이 테스트는 선택사항 - DB 연결을 의도적으로 끊어야 함)

예상 결과:
❌ "❌ 검색 실패: [에러 메시지]" 표시
✅ 화면이 중단되고 더 이상 진행 안 됨 (st.stop() 작동)
✅ 이전 대화 히스토리는 유지
```

## 📊 DB 검증

테스트 후 DB에 데이터가 정상 저장되었는지 확인:

```bash
python -c "
import mysql.connector
from config.settings import settings

conn = mysql.connector.connect(
    host=settings.LEARNING_DB_HOST,
    port=settings.LEARNING_DB_PORT,
    user=settings.LEARNING_DB_USER,
    password=settings.LEARNING_DB_PASSWORD,
    database=settings.LEARNING_DB_NAME
)

cursor = conn.cursor(dictionary=True)

# 최근 3개 검색 조회
cursor.execute('''
    SELECT
        session_id,
        JSON_EXTRACT(conversation_history, '$[0].question') as question,
        JSON_EXTRACT(conversation_history, '$[0].answer') as answer_preview,
        avg_satisfaction,
        last_activity
    FROM session_context
    ORDER BY last_activity DESC
    LIMIT 3
''')

print('\\n=== 최근 검색 3개 ===')
for row in cursor.fetchall():
    print(f\"\\nSession: {row['session_id'][:8]}...\")
    print(f\"질문: {row['question']}\")
    print(f\"답변: {str(row['answer_preview'])[:100]}...\")
    print(f\"만족도: {row['avg_satisfaction']}/5\")
    print(f\"시간: {row['last_activity']}\")

cursor.close()
conn.close()
"
```

## ✅ 테스트 체크리스트

- [ ] Chat UI 정상 시작
- [ ] 검색 실행 및 답변 표시
- [ ] 검색 상세 정보 표시 (반복 횟수, 문서 수, 실행 시간, 도구)
- [ ] 출처 문서 표시 (접을 수 있는 형태)
- [ ] 피드백 버튼 5개 표시
- [ ] 피드백 제출 성공 메시지
- [ ] 피드백 후 버튼 비활성화
- [ ] 사이드바 통계 표시
- [ ] 통계 새로고침 작동
- [ ] 연속 검색 가능
- [ ] 대화 히스토리 누적 표시
- [ ] "새 대화 시작" 버튼 작동
- [ ] 세션 카운트 정상 작동
- [ ] DB에 데이터 정상 저장
- [ ] 에러 발생 시 정상 처리 (st.stop() 작동)

## 🎯 다음 단계

테스트 완료 후:

1. **정상 작동 확인 시**:
   - 실제 사용 시작 (일일 10-15회)
   - 피드백 적극 수집
   - 200회 달성 목표 (2-4주)

2. **문제 발견 시**:
   - 에러 로그 확인
   - 문제 상황 기록
   - 필요 시 수정

## 📝 테스트 기록

**테스트 날짜**: _______
**테스터**: _______
**테스트 횟수**: _______
**발견된 문제**: _______
**전체 평가**: ⭐⭐⭐⭐⭐

---

**작성일**: 2025-11-07
**상태**: Chat UI 수정 완료, 테스트 준비 완료
