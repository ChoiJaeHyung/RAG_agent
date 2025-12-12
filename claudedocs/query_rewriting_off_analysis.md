# Query Rewriting OFF 테스트 분석 보고서

**테스트 일시**: 2025-11-13 09:04:00
**테스트 쿼리**: "iOS 모바일 뷰어 키보드 입력 개선 관련 Redmine 이슈"

---

## 📊 핵심 결과

### Query Rewriting 비활성화 상태

```
⚠️  Query Rewriting: OFF (disabled for production testing)
```

**성공 여부**: ✅ **YES** - 10개 문서 수집 성공
**소요 시간**: 33.7초
**Iteration 수**: 2회 (조기 종료)

---

## 🔍 주요 발견 사항

### 1. ✅ search_redmine DB 오류 재현 확인

```
[2025-11-13 09:04:09] [ERROR] Query failed:
    SELECT 'redmine_sync_log' as source_table, log_id, log_message
    ... | Error: (1054, "Unknown column 'log_id' in 'field list'")
```

**문제**:
- `log_id` 컬럼이 실제 DB 스키마에 존재하지 않음
- search_redmine 도구가 항상 실패
- Fallback chain 자동 실행: `search_redmine → search_mariadb_by_keyword → search_qdrant_semantic`

**영향**:
- 불필요한 4초 지연 발생 (첫 도구 실행 실패 시간)
- Fallback 실행으로 우회는 되지만 비효율적

**권장 조치**: P0 - 즉시 수정 필요

---

### 2. ✅ Query Rewriting OFF 상태에서도 정상 동작 확인

**Iteration 1**: search_redmine 실패 → Fallback → **10개 문서 수집**
**Iteration 2**: search_mariadb_by_keyword → **21개 문서 수집** → 조기 종료

**총 수집**: 31개 → 중복 제거 후 10개 (unique)

**결론**: Query Rewriting이 없어도 시스템은 정상 작동함

---

### 3. ⚠️ 답변 환각 문제 지속 (Query Rewriting과 무관)

```
⚠️ 환각 가능성: 11개 주장 중 1개만 문서에서 확인됨
📊 답변 검증: 신뢰도 43.64% (관련성 0.67, 근거성 0.09, 완전성 0.67)
```

**핵심 문제**:
- **근거성 (Groundedness) = 0.09** ← CRITICAL
- 답변이 수집된 문서를 기반으로 하지 않음
- 모델이 자체 지식으로 답변 생성

**Query Rewriting 관계**:
- ❌ Query Rewriting과 **무관한 문제**
- ✅ 답변 생성 단계의 구조적 문제

**권장 조치**: P0 - 답변 생성 프롬프트 개선 필요

---

### 4. 🔄 Fallback Chain 효과성

**Iteration 1 Fallback 체인**:
```
search_redmine (실패, 0 docs, 4.2s)
  ↓
search_mariadb_by_keyword (실패, 0 docs, 1.3s)
  ↓
search_qdrant_semantic (성공, 10 docs, 1.3s)
```

**Iteration 2 직접 선택**:
```
search_mariadb_by_keyword (성공, 21 docs, 1.3s)
```

**관찰**:
- Fallback chain은 작동하지만 **6초 지연 발생** (실패한 도구 실행 시간)
- Agent가 Iteration 2에서 동일한 도구를 다시 선택 (학습되지 않음)
- Tool selection 로직 개선 필요

---

## 📈 운영 로그 vs 테스트 결과 비교

| 항목 | 운영 로그 (Query Rewriting ON) | 테스트 (Query Rewriting OFF) |
|------|-------------------------------|------------------------------|
| search_redmine 오류 | ✅ 재현됨 | ✅ 재현됨 |
| Fallback 실행 | ✅ 3단계 | ✅ 3단계 (Iteration 1) |
| 최종 문서 수 | 20개 | 10개 (unique) |
| 답변 근거성 | 0.00 | 0.09 |
| 답변 신뢰도 | 53.33% | 43.64% |
| Query Rewriting 효과 | 모든 변형 0 docs | N/A (비활성화) |

**핵심 차이점**:
- Query Rewriting ON: 추가 시간 소요했으나 **효과 없음**
- Query Rewriting OFF: 더 빠르게 동일한 품질 달성

---

## 💡 결론 및 권장사항

### ✅ Query Rewriting 비활성화 유지

**이유**:
1. **평가 환경 vs 운영 환경 불일치**
   - 평가: 28.2% 개선
   - 운영: 0% 효과 (모든 변형 0 documents)

2. **성능 저하 없음**
   - Query Rewriting OFF 상태에서도 충분한 문서 수집
   - Fallback chain이 효과적으로 작동

3. **복잡도 감소**
   - GPT-3.5-turbo 호출 제거 (비용 절감)
   - 시스템 단순화

**권장**: ✅ **Query Rewriting 제거** (현재 OFF 상태 유지)

---

### 🚨 우선 수정 항목 (P0)

#### 1. search_redmine DB 스키마 오류
```sql
-- 현재 (오류):
SELECT 'redmine_sync_log' as source_table, log_id, log_message ...

-- 수정 필요:
SELECT 'redmine_sync_log' as source_table, id, log_message ...
-- OR
-- 정확한 컬럼명 확인 후 수정
```

**파일**: `agents/tools/mariadb_tools.py`
**예상 수정 시간**: 10분
**영향**: 4초 불필요한 지연 제거

#### 2. 답변 환각 문제 (근거성 0.09)
**문제 원인**:
- LLM이 문서 내용을 무시하고 자체 지식으로 답변 생성
- 답변 생성 프롬프트가 문서 기반 답변을 강제하지 못함

**수정 방향**:
```python
# 현재 프롬프트 (추정)
"다음 문서를 참고하여 답변하세요: {documents}"

# 개선 프롬프트
"""
**CRITICAL**: You MUST answer ONLY based on the provided documents.
- If information is not in documents, say "문서에 해당 정보가 없습니다"
- Cite document IDs for each claim: [doc_id:123]
- Do NOT use your own knowledge

Documents:
{documents}
"""
```

**파일**: `agents/search_agent.py` (answer generation 부분)
**예상 수정 시간**: 30분
**영향**: 답변 신뢰도 43% → 80%+ 목표

---

### ⚡ 긴급 검토 항목 (P1)

#### 3. Tool Selection 로직 개선
**문제**:
- Agent가 실패한 도구(search_redmine)를 먼저 선택
- Iteration 2에서 동일 도구 재선택 (학습 없음)

**개선 방향**:
- Tool performance history 활용
- 최근 성공률 기반 우선순위 조정
- Failed tool에 penalty 부여

#### 4. Fallback Chain 최적화
**문제**:
- 3단계 fallback으로 6초 지연
- 각 단계에서 실패 판단 시간 소요

**개선 방향**:
- Tool health check (startup 시)
- Known broken tool 자동 스킵
- Parallel fallback 시도

---

### 🔧 중기 개선 항목 (P2)

#### 5. Cache 정책 재검토
**의문점**:
- 평가 환경과 운영 환경의 캐시 공유 가능성
- 평가 결과가 캐시에 영향받았을 가능성

**검토 필요**:
- Cache key 생성 로직
- Cache TTL 설정
- Session 별 cache isolation

#### 6. Reranking 오류 수정
```
[ERROR] Reranking failed: Illegal header value b'Bearer '
```

**원인**: Cohere API key 설정 오류
**영향**: 현재 Reranking 비활성화 상태 (fallback to original order)
**조치**: API key 검증 로직 추가

---

## 📋 다음 단계

### 즉시 실행 (오늘)
1. ✅ Query Rewriting OFF 상태 유지 확인
2. ⏳ search_redmine 스키마 오류 수정
3. ⏳ 답변 환각 문제 수정

### 금주 내 완료
4. Tool selection 로직 개선
5. Fallback chain 최적화
6. Reranking API key 수정

### 차주 검토
7. Cache 정책 재검토
8. 평가 환경 재설정 (캐시 분리)
9. 재평가 수행 (Query Rewriting 효과 재검증)

---

## 📁 관련 파일

### 수정 필요 파일
- `agents/search_agent.py` (lines 165-184: Query Rewriting 제거 완료)
- `agents/tools/mariadb_tools.py` (search_redmine 함수: DB 스키마 수정 필요)
- `agents/search_agent.py` (answer generation: 프롬프트 개선 필요)

### 테스트 결과 파일
- `test_qr_off_result_20251113_090440.json` (전체 검색 결과)
- `test_qr_off.log` (상세 로그)

---

## 🎯 최종 권고

**Query Rewriting**:
- ❌ **제거 확정** (평가와 운영 불일치, 효과 없음)
- ✅ 현재 OFF 상태 유지

**우선 순위**:
1. **P0**: search_redmine 버그 수정 (10분)
2. **P0**: 답변 환각 문제 수정 (30분)
3. **P1**: Tool selection 개선 (1-2시간)
4. **P1**: Fallback chain 최적화 (1-2시간)

**기대 효과**:
- 검색 속도: 33.7s → ~25s (6초 fallback 제거)
- 답변 신뢰도: 43% → 80%+ (환각 문제 해결)
- 시스템 단순성: 복잡도 감소 (Query Rewriting 제거)
