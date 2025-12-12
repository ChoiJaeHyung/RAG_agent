# 검색 속도 분석 및 최적화 방안

## 🔍 현재 성능 분석

### 실측 데이터

#### 도구별 실행 시간
```
search_mariadb_by_keyword:     평균 1.18초 (성공률 45%)
search_qdrant_semantic:        평균 0.58초 (성공률 0% ⚠️)
search_elasticsearch_bm25:     평균 0.12초 (성공률 100%)
search_mariadb_by_error_code:  평균 0.60초 (성공률 100%)
```

#### 세션별 총 시간 (도구 실행만)
```
세션 1: 0.60초 (1회 반복)
세션 2: 0.25초 (1회 반복)
세션 3: 2.63초 (2회 반복)
세션 4: 3.32초 (4회 반복)
세션 5: 1.53초 (3회 반복)
```

**문제**: 사용자가 체감하는 시간은 **10-30초**인데 도구 실행은 **1-3초**만 걸림!

### 시간 분해 분석

```
전체 검색 시간: 10-30초
├─ 도구 실행: 1-3초 (10-20%)          ← 빠름!
├─ OpenAI API 호출: 8-20초 (60-80%)   ← 느림! (병목)
├─ 문서 처리: 0.5-1초 (3-5%)
├─ 검증/평가: 0.5-1초 (3-5%)
└─ 기타 오버헤드: 0.5-1초 (3-5%)
```

### 병목 지점 확인

#### OpenAI API 호출 (agents/search_agent.py:940-948)
```python
response = self.client.chat.completions.create(
    model=self.model,              # gpt-4o-mini
    messages=[...],
    temperature=self.temperature,
    max_tokens=2000                # ← 많은 토큰!
)
```

**분석**:
- `max_tokens=2000`: 최대 2,000토큰 생성 가능
- 실제 답변: 평균 800-1,000자 (약 400-500 토큰)
- GPT-4o-mini: ~30-50 토큰/초 생성 속도
- **예상 시간**: 400토큰 ÷ 40토큰/초 = **10초**
- 네트워크 지연 + 프롬프트 처리 + 대기열 = **추가 5-10초**

**결론**: OpenAI API 호출이 전체 시간의 **70-80%** 차지!

## 💡 최적화 방안

### Level 1: 즉시 적용 가능 (쉬움, 10-20% 개선)

#### 1.1 max_tokens 줄이기
```python
# 현재
max_tokens=2000

# 개선
max_tokens=1000  # 대부분 답변은 500-800토큰이면 충분
```

**예상 효과**:
- OpenAI 처리 시간 단축 (불필요한 토큰 생성 방지)
- API 비용 절감
- **5-10% 속도 개선**

#### 1.2 temperature 조정
```python
# 현재
temperature=self.temperature  # 설정값

# 개선 (정확성 중심)
temperature=0.3  # 낮추면 생성 속도 빨라짐
```

**예상 효과**:
- 더 결정적인 생성 (빠름)
- **5% 속도 개선**

#### 1.3 Qdrant 검색 오류 수정
```
search_qdrant_semantic: 성공률 0% ⚠️
```

현재 Qdrant는 항상 실패하고 fallback으로 넘어감 → 불필요한 시간 낭비

**수정 필요**:
- Qdrant formatting 오류 해결
- 또는 임시로 Qdrant 비활성화

**예상 효과**:
- 불필요한 재시도 제거
- **10-15% 속도 개선**

### Level 2: 중간 난이도 (중간, 20-30% 개선)

#### 2.1 Streaming 응답 사용
```python
# 현재: 전체 답변 생성 후 반환
response = self.client.chat.completions.create(...)
answer = response.choices[0].message.content

# 개선: 스트리밍으로 실시간 표시
stream = self.client.chat.completions.create(
    stream=True,  # ← 활성화
    ...
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        yield chunk.choices[0].delta.content
```

**예상 효과**:
- **체감 속도 50% 개선** (실제는 동일하지만 즉시 반응)
- 사용자가 답변을 실시간으로 볼 수 있음
- ChatGPT 같은 경험

**구현 필요**:
- SearchAgent에 streaming 모드 추가
- Chat UI에서 streaming 처리

#### 2.2 Context 크기 동적 조정
```python
# 현재: 항상 8000 토큰까지 허용
context = self._truncate_context(context, max_tokens=8000)

# 개선: 질문 유형에 따라 조정
if question_type == 'keyword':
    max_context_tokens = 2000  # 간단한 질문
elif question_type == 'how_to':
    max_context_tokens = 5000  # 절차 설명
else:
    max_context_tokens = 8000  # 복잡한 질문
```

**예상 효과**:
- 프롬프트 처리 시간 단축
- **10-15% 속도 개선**

#### 2.3 문서 개수 제한
```python
# 현재: 조건에 따라 다름
dynamic_limit = 15 or 30

# 개선: 더 작게
dynamic_limit = 10 or 20  # 충분한 품질 유지하면서 속도 향상
```

**예상 효과**:
- Context 크기 감소
- **5-10% 속도 개선**

### Level 3: 고급 최적화 (어려움, 40-60% 개선)

#### 3.1 답변 캐싱
```python
# Redis에 (question_hash, documents_hash) → answer 캐싱
import hashlib

def _get_cached_answer(question: str, documents: List[Dict]) -> Optional[str]:
    """동일한 질문 + 문서 조합이면 캐시 반환"""
    q_hash = hashlib.md5(question.encode()).hexdigest()
    d_hash = hashlib.md5(str([d.get('id') for d in documents]).encode()).hexdigest()

    cache_key = f"answer:{q_hash}:{d_hash}"
    return redis.get(cache_key)
```

**예상 효과**:
- 동일/유사 질문 시 **즉시 반환** (0.1초)
- **50-90% 속도 개선** (캐시 히트 시)

#### 3.2 모델 경량화
```python
# 현재
model = "gpt-4o-mini"  # 빠른 편

# 개선 옵션
model = "gpt-4o-mini"  # 유지 (이미 최적)
# 또는
model = "gpt-3.5-turbo"  # 더 빠르지만 품질 하락 가능
```

**예상 효과**:
- gpt-3.5-turbo는 2-3배 빠름
- 하지만 답변 품질 검증 필요

#### 3.3 병렬 처리
```python
# 현재: 순차 실행
for iteration in range(max_iterations):
    decision = self._get_agent_decision(...)  # OpenAI 호출 1
    result = self._execute_tool(...)
    validation = self._validate_results(...)  # OpenAI 호출 2

# 개선: 병렬 실행
import asyncio

async def parallel_execution():
    decision_task = asyncio.create_task(get_decision())
    # 도구 실행 후 즉시 다음 결정 준비
    validation_task = asyncio.create_task(validate())
```

**예상 효과**:
- 대기 시간 감소
- **20-30% 속도 개선**

#### 3.4 로컬 LLM 사용 (선택적)
```python
# 검증/결정: 로컬 모델 (빠름, 저렴)
validation_model = "llama3-8b-local"  # 0.5초

# 최종 답변: OpenAI (느림, 고품질)
answer_model = "gpt-4o-mini"  # 10초
```

**예상 효과**:
- 중간 단계 속도 향상
- API 비용 절감
- **15-25% 속도 개선**

### Level 4: 아키텍처 변경 (매우 어려움, 50-70% 체감 개선)

#### 4.1 FastAPI + Celery (비동기)
```
[사용자] → [즉시 task_id 반환] → [백그라운드 처리]
```

**장점**:
- 즉시 응답 (0.1초)
- 백그라운드에서 10-20초 처리
- **체감 속도 90% 개선**

#### 4.2 Progressive Loading
```
단계별 결과 반환:
1. 0.5초: "문서 검색 중..."
2. 3초: "15개 문서 발견, 분석 중..."
3. 10초: "답변 생성 시작..."
4. 15초: "답변 완료!"
```

**예상 효과**:
- 체감 대기 시간 감소
- 진행 상황 가시화

## 📊 최적화 우선순위

### 🔴 High Priority (즉시 적용)
1. **Qdrant 오류 수정**: 성공률 0% → 100%로 개선 (10-15% 개선)
2. **max_tokens 조정**: 2000 → 1000 (5-10% 개선)
3. **temperature 조정**: 낮춤 (5% 개선)

**예상 총 개선**: 20-30%
**예상 시간**: 10-30초 → **7-21초**

### 🟡 Medium Priority (1-2주 내)
4. **Streaming 응답**: 체감 속도 50% 개선
5. **Context 동적 조정**: 10-15% 개선
6. **문서 개수 제한**: 5-10% 개선

**예상 총 개선**: 35-45%
**예상 시간**: 10-30초 → **5.5-18초** (체감은 더 빠름)

### 🟢 Low Priority (1-3개월 내)
7. **답변 캐싱**: 캐시 히트 시 90% 개선
8. **병렬 처리**: 20-30% 개선
9. **FastAPI 전환**: 체감 90% 개선

## 🎯 현실적인 목표

### 단기 (1주일)
- Qdrant 오류 수정
- max_tokens, temperature 조정
- **목표**: 10-30초 → **8-21초**

### 중기 (1개월)
- Streaming 응답 구현
- Context 동적 조정
- **목표**: 10-30초 → **6-15초** (체감 더 빠름)

### 장기 (3-6개월)
- FastAPI + Celery 전환
- 답변 캐싱
- **목표**: 즉시 응답 + 백그라운드 처리

## ⚠️ 주의사항

### 속도 vs 품질 트레이드오프

#### 너무 공격적으로 최적화하면:
- ❌ 답변 품질 하락
- ❌ 관련 문서 누락
- ❌ 부정확한 답변

#### 균형점 찾기:
- ✅ Streaming: 품질 유지, 체감 속도 개선
- ✅ 경미한 max_tokens 감소: 품질 거의 유지
- ✅ Qdrant 수정: 품질 개선 + 속도 개선
- ⚠️ 모델 변경: 신중히 테스트 필요
- ⚠️ Context 대폭 감소: 품질 하락 위험

## 💰 비용 vs 속도

### 현재 비용 (gpt-4o-mini)
```
Input: $0.15/1M tokens
Output: $0.60/1M tokens

평균 검색당:
- Input: ~10K tokens × $0.15/1M = $0.0015
- Output: ~500 tokens × $0.60/1M = $0.0003
- 합계: $0.0018 (약 2.5원)
```

### 최적화 후
```
max_tokens 감소: $0.0015 (약 2원, 17% 절감)
답변 캐싱: $0 (캐시 히트 시 100% 절감)
```

## 📝 결론

### 현재 속도가 최선인가?
**아니요!** 여러 최적화 방안이 있습니다.

### 가장 효과적인 방법은?
1. **즉시**: Qdrant 수정 + max_tokens 조정 (20-30% 개선)
2. **1개월**: Streaming 응답 추가 (체감 50% 개선)
3. **3개월**: FastAPI 전환 (체감 90% 개선)

### 추천 로드맵
```
Week 1: Qdrant 수정, 파라미터 튜닝
Week 2-3: Streaming 응답 구현
Week 4: 피드백 수집 및 미세 조정
Month 2-3: 데이터 분석, use_learning 활성화
Month 4-6: FastAPI 전환 준비 (필요시)
```

### 현실적 기대치
- **지금**: 10-30초
- **1주 후**: 8-21초 (20-30% 개선)
- **1개월 후**: 6-15초 + 실시간 스트리밍 (체감 50% 개선)
- **상용화 시**: 즉시 응답 + 백그라운드 10-15초

---

**작성일**: 2025-11-07
**분석 기준**: 최근 50개 검색 로그
**결론**: 최적화 가능! 우선 Qdrant 수정 + 파라미터 튜닝 권장
