# 답변 저장 기능 통합 가이드

## 📋 현재 상태

### ✅ 저장되는 것 (use_learning=True 시)
- **사용자 질의**: `tool_performance_log.question`
- **Tool 활동**: `tool_performance_log` (도구명, 실행시간, 성공/실패 등)

### ❌ 저장 안 되는 것
- **최종 답변**: 현재 DB에 저장 안 됨

---

## 🔧 해결 방법

### 1단계: SessionContextRepository 추가 (✅ 완료)

```python
# repositories/session_context_repository.py
class SessionContextRepository:
    def add_conversation_turn(self, session_id, question, answer, sources):
        """질문 + 답변 + 출처를 conversation_history에 저장"""
```

---

### 2단계: SearchAgent에 통합

#### 수정 파일: `agents/search_agent.py`

**변경 1: Import 추가**
```python
# 기존 imports
from repositories.tool_performance_repository import ToolPerformanceRepository

# 추가
from repositories.session_context_repository import SessionContextRepository
```

**변경 2: __init__에 repository 추가**
```python
def __init__(self):
    # ... 기존 코드 ...
    self.perf_repo = ToolPerformanceRepository()

    # 🆕 추가
    self.session_repo = SessionContextRepository()

    self.session_id = None
    self.use_learning = False
```

**변경 3: search() 메서드 끝에 저장 로직 추가**
```python
def search(self, question: str, max_iterations=None, debug=False):
    # ... 기존 검색 로직 ...

    # 최종 답변 생성
    final_answer = self._generate_answer(
        question=question,
        documents=unique_documents,
        is_list_request=is_list_request
    )

    # 🆕 답변 저장 (use_learning과 무관하게 항상 저장)
    try:
        self.session_repo.add_conversation_turn(
            session_id=self.session_id,
            question=question,
            answer=final_answer,
            sources=unique_documents[:10],  # 상위 10개 출처
            metadata={
                'is_list_request': is_list_request,
                'question_type': question_type,
                'iterations': iteration,
                'execution_time': execution_time,
                'tools_used': tools_used
            }
        )
        logger.info(f"✓ Conversation saved: {self.session_id}")
    except Exception as e:
        logger.warning(f"Failed to save conversation: {e}")

    # 기존 return
    return {
        'answer': final_answer,
        'sources': unique_documents,
        ...
    }
```

---

## 📊 저장되는 데이터 구조

### session_context 테이블

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "conversation_history": [
    {
      "question": "Docker란 무엇인가요?",
      "answer": "Docker는 애플리케이션을 컨테이너로...",
      "timestamp": "2025-11-07T15:30:00",
      "sources_count": 10,
      "sources": [
        {
          "file_name": "REDMINE #148087.txt",
          "score": 12.5
        },
        ...
      ],
      "metadata": {
        "is_list_request": false,
        "question_type": "concept",
        "iterations": 2,
        "execution_time": 25.3,
        "tools_used": ["search_elasticsearch_bm25"]
      }
    }
  ],
  "total_questions": 1,
  "successful_answers": 1
}
```

---

## 🎯 활성화 옵션

### Option 1: 항상 저장 (권장)
```python
# use_learning과 무관하게 항상 대화 저장
self.session_repo.add_conversation_turn(...)
```

**장점**:
- ✅ 전체 대화 히스토리 확보
- ✅ 사용자 만족도 분석 가능
- ✅ 답변 품질 개선 데이터

**단점**:
- ⚠️ 약간의 DB 부하 (검색당 1회 INSERT)

---

### Option 2: use_learning=True 시에만 저장
```python
# use_learning 활성화 시에만 저장
if self.use_learning:
    self.session_repo.add_conversation_turn(...)
```

**장점**:
- ✅ DB 부하 최소화

**단점**:
- ❌ 1,000회 이전 데이터 유실

---

## 📈 데이터 활용 방안

### 1. 답변 품질 분석
```sql
-- 답변 길이 통계
SELECT
    AVG(JSON_LENGTH(conversation_history)) as avg_turns,
    AVG(CHAR_LENGTH(JSON_EXTRACT(conversation_history, '$[0].answer'))) as avg_answer_length
FROM session_context;
```

### 2. 사용자 만족도 분석
```sql
-- 재질문 비율 (같은 세션에서 유사 질문)
SELECT
    COUNT(*) as sessions_with_requestion
FROM session_context
WHERE total_questions > 1;
```

### 3. 대화 패턴 분석
```sql
-- 질문 유형별 답변 특성
SELECT
    JSON_EXTRACT(conversation_history, '$[0].metadata.question_type') as q_type,
    AVG(JSON_EXTRACT(conversation_history, '$[0].metadata.execution_time')) as avg_time,
    AVG(JSON_EXTRACT(conversation_history, '$[0].sources_count')) as avg_sources
FROM session_context
GROUP BY q_type;
```

---

## 🧪 테스트

### 통합 테스트 스크립트

```python
# test_answer_storage.py
from agents.search_agent import SearchAgent
from repositories.session_context_repository import SessionContextRepository

def test_answer_storage():
    print("\n" + "=" * 80)
    print("  답변 저장 통합 테스트")
    print("=" * 80)

    # 검색 실행
    agent = SearchAgent()
    result = agent.search(
        question="Docker란 무엇인가요?",
        max_iterations=2,
        debug=True
    )

    session_id = agent.session_id
    print(f"\n✅ 검색 완료: session_id={session_id}")
    print(f"   - 답변 길이: {len(result['answer'])} chars")

    # DB 확인
    repo = SessionContextRepository()
    history = repo.get_conversation_history(session_id, limit=1)

    if history:
        print(f"\n✅ 답변 저장 확인:")
        turn = history[0]
        print(f"   - 질문: {turn['question'][:50]}...")
        print(f"   - 답변: {turn['answer'][:100]}...")
        print(f"   - 출처: {turn['sources_count']}개")
        print(f"   - 시간: {turn['timestamp']}")
    else:
        print(f"\n❌ 답변 저장 실패!")

    print("=" * 80)

if __name__ == "__main__":
    test_answer_storage()
```

---

## ⚠️ 주의사항

### DB 용량 관리

**예상 증가량**:
- 1회 검색 = 약 2-5KB (질문 + 답변 + 출처)
- 1,000회 = 약 2-5MB
- 10,000회 = 약 20-50MB

**대응책**:
```python
# 오래된 세션 자동 정리 (크론잡)
repo = SessionContextRepository()
deleted = repo.delete_old_sessions(days=30)  # 30일 이상 세션 삭제
```

---

### 개인정보 처리

**주의**:
- 질문/답변에 민감 정보 포함 가능
- GDPR/개인정보보호법 준수 필요

**대응**:
```python
# 개인정보 마스킹 옵션 추가 (향후)
def add_conversation_turn(self, ..., mask_pii=True):
    if mask_pii:
        question = self._mask_personal_info(question)
        answer = self._mask_personal_info(answer)
```

---

## 🚀 배포 계획

### 단계별 적용

**Phase 1: 테스트 환경**
```bash
# 1. SessionContextRepository 배포
# 2. SearchAgent 수정
# 3. 100회 테스트
# 4. DB 용량 및 성능 확인
```

**Phase 2: 프로덕션**
```bash
# 1. 프로덕션 배포
# 2. 1주일 모니터링
# 3. 데이터 분석 시작
```

---

## 📝 최종 체크리스트

### 구현 전
- [ ] SessionContextRepository 배포
- [ ] DB 테이블 확인 (session_context 존재)
- [ ] DB 권한 확인

### 구현 시
- [ ] SearchAgent.__init__ 수정
- [ ] SearchAgent.search() 끝에 저장 로직 추가
- [ ] 에러 핸들링 추가 (try-except)

### 구현 후
- [ ] 테스트 실행 (test_answer_storage.py)
- [ ] DB 저장 확인
- [ ] 1주일 모니터링
- [ ] 데이터 분석 및 활용

---

**작성일**: 2025-11-07
**상태**: SessionContextRepository 구현 완료, SearchAgent 통합 대기
**권장사항**: Option 1 (항상 저장) 추천
