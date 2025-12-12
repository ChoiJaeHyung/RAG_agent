# Week 1 - Query Rewriting Implementation

## 구현 완료 (2025-11-12)

### ✅ 완료 항목

#### 1. Query Rewriting 엔진 구현 (`agents/query_rewriter.py`)

**핵심 기능:**
- GPT-3.5-turbo 기반 쿼리 변형 생성 (비용 효율적)
- 1개 쿼리 → 5개 변형 (원본 + 4개 변형)
- 5가지 재작성 전략:
  - keyword_extraction: 핵심 키워드 중심
  - semantic_expansion: 유사어/동의어 확장
  - technical_reformulation: 기술 용어 변환
  - question_decomposition: 하위 질문 분해
  - error_code_emphasis: 에러코드 강조

**견고성:**
- GPT 실패 시 규칙 기반 Fallback 구현
- Jaccard similarity 기반 중복 제거 (>0.9 threshold)
- 품질 필터링 (너무 짧음/김/유사한 변형 제거)

**테스트 결과:**
- ✅ 23개 단위 테스트 모두 통과
- GPT 성공/실패 시나리오 모두 검증
- Edge cases 처리 확인 (빈 쿼리, 특수문자, 에러코드)

---

#### 2. SearchAgent 통합 (`agents/search_agent.py`)

**통합 방식:**
- ReAct loop 시작 전 Query Rewriting 단계 추가
- 첫 번째 iteration에서만 multi-query search 수행
- semantic search에만 적용 (keyword search는 단일 쿼리)
- 중복 문서 제거 (`_deduplicate_documents` 메서드)

**성능 프로파일링:**
- PerformanceProfiler에 `query_rewriting` phase 추가
- 각 variant별 검색 시간 추적
- 중복 제거 효율성 측정

**코드 변경 요약:**
```python
# Line 28: Import
from agents.query_rewriter import query_rewriter

# Lines 164-177: Query Rewriting Phase
query_variants = query_rewriter.rewrite_query(
    original_query=question,
    num_variants=4,
    session_id=self.session_id
)

# Lines 234-276: Multi-Query Search Logic
if iteration == 1 and tool_name == 'search_qdrant_semantic' and query_variants:
    # Search with all variants
    # Deduplicate results

# Lines 705-733: Deduplication Method
def _deduplicate_documents(self, documents: List[Dict]) -> List[Dict]:
    # Remove duplicates by doc_id or content hash
```

**테스트 결과:**
- ✅ 12개 통합 테스트 모두 통과
- 중복 제거 검증 (ID, doc_id, document_id 필드 모두 지원)
- Content hash fallback 동작 확인
- Order preservation 검증

---

### 📊 테스트 커버리지

**총 35개 테스트 모두 통과:**

**QueryRewriter 단위 테스트 (23개):**
- ✅ Initialization
- ✅ GPT-based variant generation (success/failure)
- ✅ Rule-based fallback variants
- ✅ Keyword extraction
- ✅ Question form conversion
- ✅ Error code emphasis
- ✅ Brand name emphasis
- ✅ Duplicate filtering
- ✅ Length filtering (too short/long)
- ✅ Similarity filtering (>90%)
- ✅ Jaccard similarity calculation
- ✅ Best variant selection
- ✅ Max variants limit
- ✅ Edge cases (empty, special chars, numeric)

**SearchAgent 통합 테스트 (12개):**
- ✅ Deduplication by ID
- ✅ Deduplication by doc_id
- ✅ Deduplication by document_id
- ✅ Deduplication with missing IDs (content hash)
- ✅ Order preservation
- ✅ Empty list handling
- ✅ Single document
- ✅ All unique documents
- ✅ All duplicate documents
- ✅ Content hash deduplication
- ✅ Import verification
- ✅ Method existence verification

---

### 🎯 예상 성능 개선

**정확도 개선:**
- Multi-query retrieval: +20% 예상 (SOTA 연구 기반)
- Recall 향상: 다양한 표현으로 검색 → 더 많은 관련 문서 발견
- Precision 유지: 중복 제거로 품질 유지

**속도 영향:**
- Query rewriting: +0.2s (GPT-3.5 호출)
- Multi-query search: +0.5s (5배 검색)
- 총 예상: +0.7s
- **판단:** 정확도 +20%를 위해 0.7s 증가는 허용 가능

---

### 🔄 Backward Compatibility

**안전성 보장:**
- Query rewriting 실패 시 → 원본 쿼리로 Fallback
- GPT 실패 시 → 규칙 기반 variants 생성
- 기존 코드 영향 없음 (non-intrusive 통합)
- 첫 iteration에만 적용 → 이후 ReAct loop 정상 동작

---

### 📁 생성된 파일

```
agents/
├── query_rewriter.py                    # 새로 생성
├── search_agent.py                      # 수정됨 (3곳)

test_query_rewriter.py                   # 새로 생성 (23 tests)
test_search_agent_query_rewriting.py     # 새로 생성 (12 tests)

claudedocs/
└── WEEK1_QUERY_REWRITING_IMPLEMENTATION.md  # 이 문서
```

---

### ✅ 다음 단계: Reranking 구현

**Week 1 완성을 위한 남은 작업:**
1. ✅ Query Rewriting 구현 완료
2. 🔄 Reranking 구현 (다음 단계)
3. ⏳ Week 1 성능 테스트 (30문제 테스트셋)
4. ⏳ 정확도 75% → 90% 달성 검증

**Reranking 구현 계획:**
- Cohere Rerank API 통합
- Cross-encoder 기반 재정렬
- Top-50 문서 → Top-10 정밀 순위
- 예상 정확도 개선: +15%
- 예상 속도: +158ms

**최종 Week 1 목표:**
- Query Rewriting + Reranking = +35% 정확도
- 속도 증가: +0.86s (허용 범위)
- 75% → 90%+ 정확도 달성 예상

---

## 기술적 세부사항

### Query Rewriting 알고리즘

**GPT Prompt 전략:**
```
재작성 전략:
1. 핵심 키워드 중심으로 간결하게
2. 유사어/동의어를 사용하여 의미 확장
3. 기술 용어를 일반 용어로 또는 그 반대로
4. 질문을 더 구체적으로 또는 더 일반적으로

에러코드나 제품명이 있다면 반드시 포함하세요.
```

**Temperature 설정:**
- 0.7로 설정 (다양성 확보, 일관성 유지 균형)

**Fallback 규칙:**
1. 키워드 추출 (불용어 제거)
2. 질문형 → 서술형 변환
3. 에러코드 강조 (정규식: `\b\d{5}\b|\bRCXERR_\w+\b`)
4. 제품명 강조 (RemoteView, RemoteCall, RemoteMeeting, RemoteWOL)

### Deduplication 알고리즘

**우선순위:**
1. `id` 필드 확인
2. `doc_id` 필드 확인
3. `document_id` 필드 확인
4. 없으면 content hash (첫 200자)

**시간 복잡도:**
- O(n) with set-based tracking
- 효율적인 메모리 사용

---

## 결론

✅ **Query Rewriting 구현 및 테스트 완료**
- 35개 테스트 모두 통과
- 정확도 우선 전략에 부합
- 견고한 Fallback 메커니즘
- Backward compatible

🎯 **다음:** Reranking 구현으로 Week 1 완성
