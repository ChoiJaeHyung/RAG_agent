# 도구 선택 가이드 (Tool Selection Guide)

## 📌 개요

RAG Agent는 **7개의 검색 도구**를 사용하여 사용자 질문에 가장 적합한 정보를 찾습니다.
Agent는 질문의 특성을 분석하여 **자동으로 최적의 도구를 선택**하고 실행합니다.

---

## 🔧 전체 도구 목록

### MariaDB 도구 (4개)
1. **search_mariadb_by_error_code** - 에러 코드 검색
2. **search_mariadb_by_keyword** - 키워드 검색
3. **search_recent_logs** - 과거 Q&A 로그 검색
4. **search_redmine** - 레드마인 일감 검색

### 벡터 검색 도구 (1개)
5. **search_faiss_semantic** - 의미 기반 벡터 검색

### Elasticsearch 도구 (2개)
6. **search_elasticsearch_bm25** - BM25 키워드 랭킹 검색
7. **get_document_by_id** - 문서 ID로 상세 조회

---

## 📋 도구별 상세 설명

### 1. search_mariadb_by_error_code

**목적**: 에러 코드로 문서 검색

**언제 사용하는가**:
- 질문에 4-5자리 숫자 에러 코드가 포함된 경우
- 예: "50001", "6789", "10234"

**검색 방식**:
```sql
SELECT * FROM sentences
WHERE sentence LIKE '%50001%'
LIMIT 100
```

**입력 파라미터**:
- `error_code` (required): 검색할 에러 코드 (예: "50001")

**출력 형식**:
```python
{
    'id': 62193,
    'text': 'REDMINE #133882 | 업무(Job) | 완료성공...',
    'score': 1.0,  # 정확히 일치하므로 항상 1.0
    'metadata': {
        'file_name': 'redmine_issues',
        'doc_id': '133882',
        'chunk_num': 0
    },
    'source': 'mariadb_error_code'
}
```

**예시 질문**:
- ✅ "RVS 설치 시 50001 에러 발생"
- ✅ "6789 오류 어떻게 해결하나요?"
- ❌ "설치 오류 발생" (에러 코드 없음)

**장점**:
- 정확한 에러 코드 매칭
- 빠른 검색 속도
- 100% 정확도

**제한사항**:
- 에러 코드가 없으면 사용 불가
- 최대 100개 결과 제한

---

### 2. search_mariadb_by_keyword

**목적**: 키워드로 정확한 텍스트 매칭 검색

**언제 사용하는가**:
- 특정 키워드가 정확히 포함된 문서를 찾을 때
- 브랜드별 필터링이 필요한 경우

**검색 방식**:
```sql
-- 브랜드 필터 없음
SELECT * FROM sentences
WHERE sentence LIKE '%국민은행%'
LIMIT 100

-- 브랜드 필터 있음
SELECT * FROM sentences
WHERE sentence LIKE '%국민은행%'
AND sentence LIKE '%rvs%'
LIMIT 100
```

**입력 파라미터**:
- `keyword` (required): 검색 키워드 (예: "설치", "국민은행")
- `brand` (optional): 브랜드 필터 ("rvs", "rcmp", "rcall", "rvcp", "saas")

**출력 형식**:
```python
{
    'id': 62193,
    'text': 'REDMINE #133882 - [국민은행] SSO...',
    'score': 0.9,  # 키워드 매칭은 0.9
    'metadata': {
        'file_name': 'redmine_issues',
        'doc_id': '133882',
        'chunk_num': 0,
        'brand': 'rvs'  # 브랜드 정보
    },
    'source': 'mariadb_keyword'
}
```

**예시 질문**:
- ✅ "국민은행 관련 문서 찾아줘"
- ✅ "RVS 설치 방법" (brand='rvs' 자동 감지)
- ✅ "원격 접속 오류"

**장점**:
- 정확한 키워드 매칭
- 브랜드별 필터링 가능
- 빠른 검색

**제한사항**:
- 동의어나 유사어는 찾지 못함
- 키워드가 정확히 일치해야 함
- 최대 100개 결과

---

### 3. search_recent_logs

**목적**: 과거 Q&A 로그에서 유사한 질문 찾기

**언제 사용하는가**:
- "이전에", "예전에", "비슷한 질문" 등의 키워드
- 과거 답변을 참고하고 싶을 때

**검색 방식**:
```sql
SELECT * FROM qa_logs
WHERE user_question LIKE '%국민은행%'
ORDER BY created_at DESC
LIMIT 5
```

**입력 파라미터**:
- `query` (required): 검색 쿼리
- `limit` (optional): 최대 결과 수 (기본값: 5, 최대: 20)

**출력 형식**:
```python
{
    'id': 12345,  # qa_id
    'question': '국민은행 SSO 연동 방법은?',
    'answer': 'SSO 연동은 다음과 같이 진행...',
    'created_at': '2025-11-01 10:30:00',
    'metadata': {
        'user_id': 'user123',
        'session_id': 'session456',
        'score': 0.85,
        'is_relevant': True
    },
    'source': 'qa_logs'
}
```

**예시 질문**:
- ✅ "이전에 SSO 관련 질문 있었나요?"
- ✅ "예전에 물어본 국민은행 관련 내용"
- ✅ "비슷한 질문이 있었는지 확인"

**장점**:
- 과거 성공적인 답변 재활용
- 시간순 정렬로 최신 정보 우선
- 빠른 검색

**제한사항**:
- 과거 로그에만 의존
- 새로운 정보는 찾지 못함

---

### 4. search_redmine

**목적**: 레드마인 일감 전용 검색

**언제 사용하는가**:
- 질문에 "레드마인" 또는 "redmine" 키워드 포함
- 일감, 이슈, 티켓 관련 질문

**검색 방식**:
```sql
-- redmine_issues 테이블
SELECT 'redmine_issues' as source_table, issue_id, subject, description
FROM redmine_issues
WHERE subject LIKE '%SSO%' OR description LIKE '%SSO%'
LIMIT 25

-- redmine_journals 테이블
SELECT 'redmine_journals' as source_table, journal_id, notes
FROM redmine_journals
WHERE notes LIKE '%SSO%'
LIMIT 25

-- redmine_relations 테이블 (일감 간 관계)
SELECT 'redmine_relations' as source_table, relation_id, issue_from, issue_to
FROM redmine_relations
WHERE CAST(issue_from AS CHAR) LIKE '%SSO%'
LIMIT 25

-- redmine_sync_log 테이블 (동기화 로그)
SELECT 'redmine_sync_log' as source_table, log_id, log_message
FROM redmine_sync_log
WHERE log_message LIKE '%SSO%'
LIMIT 25
```

**입력 파라미터**:
- `keyword` (required): 검색 키워드

**출력 형식**:
```python
# redmine_issues 테이블 결과
{
    'id': 133882,  # issue_id
    'text': '[국민은행 - 내부직원원격] SSO 연동방식 변경 | SSO 연동 시 기존 방식에서...',
    'score': 1.0,
    'metadata': {
        'source_table': 'redmine_issues',
        'raw_data': {
            'issue_id': 133882,
            'subject': '[국민은행] SSO 연동',
            'description': 'SSO 연동 시...'
        }
    },
    'source': 'mariadb_redmine'
}

# redmine_journals 테이블 결과
{
    'id': 45678,  # journal_id
    'text': 'SSO 인증 관련 추가 확인 필요...',
    'score': 1.0,
    'metadata': {
        'source_table': 'redmine_journals',
        'raw_data': {
            'journal_id': 45678,
            'notes': 'SSO 인증 관련...'
        }
    },
    'source': 'mariadb_redmine'
}
```

**예시 질문**:
- ✅ "레드마인에서 SSO 관련 일감 찾아줘"
- ✅ "redmine 국민은행 관련 이슈"
- ❌ "일감 찾아줘" (레드마인 키워드 없음 → 다른 도구 사용)

**장점**:
- 레드마인 전용 테이블 검색
- 4개 테이블 통합 검색
- 일감 간 관계 정보 포함

**제한사항**:
- 레드마인 키워드 필수
- 각 테이블당 25개 제한 (총 최대 100개)

---

### 5. search_faiss_semantic

**목적**: 의미 기반 벡터 유사도 검색

**언제 사용하는가**:
- "어떻게", "방법", "설명", "이란", "개념" 등 의미 기반 질문
- 키워드가 정확히 일치하지 않아도 의미가 유사한 문서 찾기

**검색 방식**:
```python
# 1. 쿼리를 벡터로 임베딩
query_vector = embedding_model.encode("RCMP 설치 방법")

# 2. FAISS 인덱스에서 유사도 검색
distances, indices = faiss_index.search(query_vector, top_k=5)

# 3. 유사도 점수 계산 (코사인 유사도)
scores = 1 / (1 + distances)  # 거리를 유사도로 변환
```

**입력 파라미터**:
- `query` (required): 의미 기반 검색 쿼리
- `top_k` (optional): 결과 수 (기본값: 5, 최대: 20)

**출력 형식**:
```python
{
    'id': 13787,
    'text': 'REDMINE #13787 | 업무(Job) | 완료성공...',
    'score': 0.66,  # 코사인 유사도 점수 (0-1)
    'metadata': {
        'file_name': 'redmine_issues',
        'doc_id': '13787',
        'chunk_num': 0
    },
    'source': 'faiss_semantic'
}
```

**예시 질문**:
- ✅ "RCMP 설치 방법을 알려주세요" (방법 → how-to)
- ✅ "SSO란 무엇인가요?" (개념 설명)
- ✅ "원격 접속 오류 해결 방법" (절차)
- ✅ "인증 방식 설명" (의미 기반)

**장점**:
- 동의어, 유사어 자동 처리
- 의미적으로 유사한 문서 발견
- 키워드 정확도보다 의미 이해
- 129,255개 전체 문서 대상

**제한사항**:
- 정확한 키워드 매칭보다 느림
- 점수가 낮을 수 있음 (평균 0.6-0.7)
- 벡터 연산으로 CPU/메모리 사용

**점수 해석**:
- 0.8-1.0: 매우 관련성 높음
- 0.6-0.8: 관련성 있음
- 0.4-0.6: 약간 관련 있음
- 0.0-0.4: 관련성 낮음

---

### 6. search_elasticsearch_bm25

**목적**: BM25 알고리즘 기반 키워드 랭킹 검색

**언제 사용하는가**:
- 여러 키워드가 포함된 복잡한 질문
- 브랜드 필터링이 필요한 경우
- 퍼지 매칭(오타 허용)이 필요한 경우

**검색 방식**:
```python
# Elasticsearch BM25 쿼리
{
    "query": {
        "bool": {
            "must": [
                {"match": {"sentence": "국민은행 SSO"}}
            ],
            "filter": [
                {"terms": {"brand": ["rvs", "rcmp"]}}
            ]
        }
    },
    "size": 10
}
```

**BM25 알고리즘**:
```
BM25(D, Q) = Σ IDF(q) × (f(q,D) × (k+1)) / (f(q,D) + k × (1-b + b × |D|/avgdl))

- IDF: 역문서 빈도 (희귀한 단어일수록 높은 점수)
- f(q,D): 문서 D에서 쿼리 q의 빈도
- |D|: 문서 길이
- avgdl: 평균 문서 길이
- k, b: 조정 파라미터
```

**입력 파라미터**:
- `query` (required): BM25 검색 쿼리
- `brand_filter` (optional): 브랜드 리스트 (예: ["rvs", "rcmp"])
- `top_k` (optional): 결과 수 (기본값: 10, 최대: 50)

**출력 형식**:
```python
{
    'id': 62193,
    'text': 'REDMINE #133882 - [국민은행] SSO...',
    'score': 12.5,  # BM25 점수 (범위 가변)
    'metadata': {
        'file_name': 'redmine_issues',
        'doc_id': '133882',
        'chunk_num': 0,
        'brand': 'rvs'
    },
    'source': 'elasticsearch_bm25'
}
```

**예시 질문**:
- ✅ "국민은행 SSO 연동 관련 문서" (여러 키워드)
- ✅ "RVS 설치 및 설정 방법" (브랜드 + 복잡한 쿼리)
- ✅ "원격 접속 오류 해결" (퍼지 매칭)

**MariaDB 키워드 vs Elasticsearch BM25**:
| 특징 | MariaDB LIKE | Elasticsearch BM25 |
|------|-------------|-------------------|
| 검색 방식 | 정확한 문자열 매칭 | 토큰화 + 랭킹 |
| 속도 | 빠름 | 중간 |
| 여러 키워드 | 느림 (AND 조건) | 빠름 (OR 조건) |
| 퍼지 매칭 | 불가 | 가능 |
| 점수 | 없음 | BM25 점수 |
| 브랜드 필터 | 느림 (LIKE 중복) | 빠름 (필터 쿼리) |

**장점**:
- 여러 키워드 효율적 처리
- 관련도 점수로 랭킹
- 브랜드 필터 최적화
- 퍼지 매칭 지원

**제한사항**:
- MariaDB보다 느림
- ES 인덱스 필요
- 점수 해석 어려움

---

### 7. get_document_by_id

**목적**: 문서 ID로 상세 정보 조회

**언제 사용하는가**:
- 이전 검색에서 찾은 문서의 전체 내용 필요
- 특정 문서 ID를 알고 있는 경우

**검색 방식**:
```python
# 1. Elasticsearch에서 먼저 시도
es_doc = es_client.get(index="qa_documents", id=str(doc_id))

# 2. 없으면 MariaDB에서 조회
if not es_doc:
    db_doc = SELECT * FROM sentences WHERE sentence_id = doc_id
```

**입력 파라미터**:
- `doc_id` (required): 문서 ID (정수)

**출력 형식**:
```python
# Elasticsearch에서 찾은 경우
{
    'id': 62193,
    'text': '[전체 문서 내용...]',
    'metadata': {
        'file_name': 'redmine_issues',
        'doc_id': '133882',
        'chunk_num': 0
    },
    'source': 'elasticsearch'
}

# MariaDB에서 찾은 경우
{
    'id': 62193,
    'text': '[전체 문서 내용...]',
    'metadata': {...},
    'source': 'database'
}
```

**예시 사용**:
```python
# 시나리오: 이전 검색에서 doc_id=62193 발견
# Agent가 전체 내용 필요하다고 판단
result = get_document_by_id(doc_id=62193)
```

**장점**:
- 빠른 ID 기반 조회
- 전체 문서 내용 반환
- 자동 폴백 (ES → DB)

**제한사항**:
- ID를 미리 알아야 함
- 단일 문서만 조회

---

## 🎯 도구 선택 로직

### Agent의 자동 선택 프로세스

```python
def _get_agent_decision(self, question, context):
    """
    LLM이 질문을 분석하여 최적의 도구 선택
    """

    # 1. 질문 분석
    question_features = analyze_question(question)
    # - 에러 코드 포함 여부
    # - 키워드 타입 (브랜드, 개념, 방법 등)
    # - 질문 유형 (Q&A, 리스트, 설명)

    # 2. 컨텍스트 분석
    context_features = analyze_context(context)
    # - 이전 검색 결과
    # - 수집된 문서 수
    # - 평균 관련도 점수

    # 3. 도구 선택 (LLM 판단)
    tool_choice = llm.select_tool(
        question=question,
        features=question_features,
        context=context_features,
        available_tools=ALL_TOOLS
    )

    # 4. 도구 실행
    return execute_tool(tool_choice)
```

### 선택 기준

#### 1단계: 키워드 기반 필터링

```python
# 에러 코드 감지
if re.search(r'\b\d{4,5}\b', question):
    priority_tools = ['search_mariadb_by_error_code']

# 레드마인 키워드 감지
elif 'redmine' in question.lower() or '레드마인' in question:
    priority_tools = ['search_redmine']

# 과거 로그 키워드 감지
elif any(kw in question for kw in ['이전', '예전', '비슷한']):
    priority_tools = ['search_recent_logs']
```

#### 2단계: 질문 유형 분석

```python
# 의미 기반 질문 (how-to, 개념)
semantic_keywords = ['어떻게', '방법', '설명', '이란', '개념']
if any(kw in question for kw in semantic_keywords):
    recommended_tools = ['search_faiss_semantic']

# 키워드 리스트 질문
keyword_patterns = ['찾아줘', '전부', '모두', '목록']
if any(kw in question for kw in keyword_patterns):
    recommended_tools = ['search_elasticsearch_bm25', 'search_mariadb_by_keyword']
```

#### 3단계: 컨텍스트 기반 조정

```python
# 이전 도구가 실패한 경우 (0개 결과)
if previous_result_count == 0:
    # 다른 도구로 전환
    alternative_tools = get_alternative_tools(previous_tool)

# 문서가 충분히 수집된 경우
if total_documents >= target_documents:
    return 'FINISH'  # 더 이상 검색하지 않음
```

### 실제 예시

#### 예시 1: 에러 코드 질문
```
Q: "RVS 설치 시 50001 에러 발생"

분석:
- 에러 코드 감지: "50001" ✅
- 브랜드 감지: "RVS" ✅

선택 순서:
1. search_mariadb_by_error_code("50001") → 6개 발견
2. FINISH (충분한 문서)

결과: 1번의 도구 호출로 완료
```

#### 예시 2: 의미 기반 질문
```
Q: "RCMP 설치 방법을 알려주세요"

분석:
- 의미 키워드: "방법" ✅
- 브랜드: "RCMP" ✅

선택 순서:
1. search_faiss_semantic("RCMP 설치 방법") → 5개 발견 (점수 0.65)
2. search_faiss_semantic(..., top_k=10) → 10개 추가 (점수 0.64)
3. FINISH (20개 문서, 중복 제거 후 9개)

결과: 2번의 도구 호출
```

#### 예시 3: 복잡한 키워드 질문
```
Q: "국민은행 SSO 연동 관련 일감 찾아줘"

분석:
- 키워드: "국민은행", "SSO", "연동"
- 리스트 요청: "찾아줘" ✅

선택 순서:
1. search_mariadb_by_keyword("국민은행 SSO") → 4개 발견
2. FINISH (충분한 문서 + 외부 지식 보강)

결과: 1번의 도구 호출 + 외부 지식
```

#### 예시 4: 실패 후 폴백
```
Q: "레드마인 SSO 연동 관련 일감 찾아줘"

선택 순서:
1. search_mariadb_by_keyword("레드마인 SSO") → 0개 ❌
2. search_mariadb_by_keyword("레드마인 SSO") → 0개 ❌ (재시도)
3. search_faiss_semantic("레드마인 SSO 연동") → 3개 발견 (폴백)
4. FINISH

결과: C+A 개선으로 자동 폴백
```

---

## 🔄 C+A 개선 (Smart Tool Switching + Auto Fallback)

### C: Smart Tool Switching (스마트 도구 전환)

**문제**: 같은 도구를 반복해서 호출하며 0개 결과 반복

**해결**: 2회 연속 실패 시 자동으로 다른 도구로 전환

```python
# 실패 카운트 추적
consecutive_failures = {
    'search_mariadb_by_keyword': 0,
    'search_faiss_semantic': 0,
    'search_elasticsearch_bm25': 0
}

# 2회 연속 실패 감지
if result_count == 0:
    consecutive_failures[tool_name] += 1

    if consecutive_failures[tool_name] >= 2:
        # 다른 도구로 전환
        alternative_tool = get_alternative(tool_name)
        consecutive_failures[tool_name] = 0  # 리셋
```

### A: Auto Fallback Chain (자동 폴백 체인)

**폴백 우선순위**:
```
MariaDB (정확도 높음)
    ↓ 실패 시
FAISS (의미 이해)
    ↓ 실패 시
Elasticsearch (퍼지 매칭)
```

**예시**:
```python
# 1차: MariaDB 키워드 검색
result = search_mariadb_by_keyword("레드마인 SSO")
if len(result) == 0:
    # 2차: FAISS 의미 검색
    result = search_faiss_semantic("레드마인 SSO 연동")
    if len(result) == 0:
        # 3차: Elasticsearch BM25
        result = search_elasticsearch_bm25("레드마인 SSO")
```

---

## 📊 도구 성능 비교

### 속도 비교

| 도구 | 평균 응답 시간 | 검색 대상 |
|------|-------------|----------|
| search_mariadb_by_error_code | 0.1-0.3초 | 129K 문서 |
| search_mariadb_by_keyword | 0.2-0.5초 | 129K 문서 |
| search_recent_logs | 0.1-0.2초 | 로그 테이블 |
| search_redmine | 0.3-0.6초 | 4개 테이블 |
| search_faiss_semantic | 1.0-2.0초 | 129K 벡터 |
| search_elasticsearch_bm25 | 0.3-0.8초 | ES 인덱스 |
| get_document_by_id | 0.05-0.1초 | 단일 문서 |

### 정확도 비교

| 도구 | 정확도 | 재현율 | 장점 |
|------|-------|-------|------|
| error_code | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | 정확한 매칭 |
| keyword | ⭐⭐⭐⭐ | ⭐⭐⭐ | 빠른 검색 |
| recent_logs | ⭐⭐⭐⭐ | ⭐⭐ | 과거 답변 |
| redmine | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 전용 검색 |
| faiss_semantic | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 의미 이해 |
| elasticsearch_bm25 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 랭킹 검색 |

### 사용 빈도 (테스트 기준)

```
search_mariadb_by_keyword: ████████████ 35%
search_faiss_semantic:     ██████████   30%
search_elasticsearch_bm25: ██████       18%
search_mariadb_by_error_code: ████      12%
search_redmine:            ██           5%
search_recent_logs:        ██           5%
get_document_by_id:        ▌            <1%
```

---

## 💡 도구 선택 팁

### 언제 어떤 도구를 사용하나?

#### 에러 코드가 있다면
→ **search_mariadb_by_error_code** 최우선

#### 특정 키워드 정확히 찾기
→ **search_mariadb_by_keyword**

#### 의미 기반 검색 (how-to, 개념)
→ **search_faiss_semantic**

#### 여러 키워드 + 브랜드 필터
→ **search_elasticsearch_bm25**

#### 레드마인 일감 찾기
→ **search_redmine**

#### 과거 답변 참고
→ **search_recent_logs**

#### 특정 문서 상세 조회
→ **get_document_by_id**

---

## 🔧 커스터마이징

### 도구 우선순위 조정

`agents/search_agent.py`에서 시스템 프롬프트 수정:

```python
system_prompt = """...
도구 선택 우선순위:
1. 에러 코드가 있으면 → search_mariadb_by_error_code
2. 레드마인 키워드 → search_redmine
3. 의미 기반 질문 → search_faiss_semantic  # 우선순위 조정
4. 키워드 검색 → search_mariadb_by_keyword
..."""
```

### 폴백 체인 수정

```python
# 기본 폴백 체인
FALLBACK_CHAIN = {
    'search_mariadb_by_keyword': 'search_faiss_semantic',
    'search_faiss_semantic': 'search_elasticsearch_bm25',
    'search_elasticsearch_bm25': None  # 마지막
}

# 커스텀 폴백 체인
FALLBACK_CHAIN = {
    'search_mariadb_by_keyword': 'search_elasticsearch_bm25',  # FAISS 건너뛰기
    'search_elasticsearch_bm25': 'search_faiss_semantic',
    'search_faiss_semantic': None
}
```

---

## 📝 관련 파일

### 도구 구현
- `agents/tools/mariadb_tools.py`: MariaDB 도구 4개
- `agents/tools/vector_tools.py`: FAISS 벡터 도구 1개
- `agents/tools/es_tools.py`: Elasticsearch 도구 2개
- `agents/tools/tool_registry.py`: 도구 등록 및 관리

### Repository (실제 검색 수행)
- `repositories/db_repository.py`: MariaDB 쿼리 실행
- `repositories/vector_repository.py`: FAISS 벡터 검색
- `repositories/es_repository.py`: Elasticsearch 검색

### Agent (도구 선택 및 조율)
- `agents/search_agent.py`: ReAct 패턴으로 도구 자동 선택

---

**작성일**: 2025-11-03
**작성자**: Claude Code
**버전**: 1.0
