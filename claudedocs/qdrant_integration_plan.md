# Qdrant 통합 구현 계획서

**작성일**: 2025-11-07
**목적**: MariaDB 기반 텍스트 검색을 Qdrant로 완전 통합하여 단일 벡터 데이터베이스 아키텍처 구현

---

## 📋 개요

### 현재 상태
- **Vector Search**: FAISS → Qdrant 마이그레이션 완료 ✅
- **Text Search**: MariaDB 기반 (4개 도구)
- **Elasticsearch**: BM25 검색

### 목표 상태
- **Vector Search**: Qdrant ✅
- **Text Search**: Qdrant (통합 필요)
- **Elasticsearch**: BM25 검색 유지

---

## 🎯 통합 범위

### 대상 도구 (4개)

| 도구명 | 현재 구현 | Qdrant 구현 방식 |
|--------|----------|-----------------|
| `search_text_by_error_code` | MariaDB LIKE | Qdrant scroll + payload filter |
| `search_text_by_keyword` | MariaDB LIKE | Qdrant semantic + text filter |
| `search_recent_logs` | MariaDB Q&A 테이블 | Qdrant semantic search |
| `search_redmine` | MariaDB Redmine 테이블 | Qdrant payload metadata filter |

---

## 🏗️ 아키텍처 변경

### Before (현재)
```
SearchAgent
├── VectorTools → VectorRepository → Qdrant
├── MariaDBTools → DatabaseRepository → MariaDB
└── ElasticsearchTools → ESRepository → Elasticsearch
```

### After (목표)
```
SearchAgent
├── VectorTools → VectorRepository → Qdrant (semantic)
├── TextTools → VectorRepository → Qdrant (filtered)
└── ElasticsearchTools → ESRepository → Elasticsearch
```

**핵심 변경**:
- `MariaDBTools` → `TextTools`
- `DatabaseRepository` 의존성 제거
- `VectorRepository`로 통합 (Qdrant만 사용)

---

## 📊 Qdrant 데이터 구조

### Collection: `rag_documents`

```python
{
    "id": 12345,  # sentence_id
    "vector": [0.1, 0.2, ...],  # 768-dim embedding
    "payload": {
        "sentence_id": 12345,
        "doc_id": 456,
        "sentence": "문서 내용 텍스트...",
        "file_name": "guide.pdf",
        "file_type": "pdf",
        "chunk_num": 3,
        "pages": 10,
        "brand": "rvs",  # Optional: 브랜드 정보
        "source_type": "redmine",  # Optional: redmine/qa_log/document
        "redmine_issue_id": 789,  # Optional: redmine 전용
    }
}
```

---

## 🔧 구현 전략

### 1️⃣ **에러 코드 검색** (`search_text_by_error_code`)

**요구사항**: 4-5자리 에러 코드 정확 매칭

**구현 방식**:
```python
# Approach 1: Scroll + Filter (정확도 우선)
def search_by_error_code(error_code: str):
    # Qdrant scroll API로 모든 문서 스캔
    # payload.sentence에서 error_code 포함 여부 확인
    filter = {
        "must": [
            {"key": "sentence", "match": {"text": error_code}}
        ]
    }

# Approach 2: Semantic + Post-filter (속도 우선)
def search_by_error_code(error_code: str):
    # 1. Semantic search with "error {code}"
    results = qdrant.search(f"error code {error_code}")
    # 2. Filter results containing exact error_code
    return [r for r in results if error_code in r['text']]
```

**선택**: Approach 2 (속도와 정확도 균형)

---

### 2️⃣ **키워드 검색** (`search_text_by_keyword`)

**요구사항**: 키워드 포함 문서, 브랜드 필터링 지원

**구현 방식**:
```python
def search_by_keyword(keyword: str, brand: Optional[str] = None):
    # Qdrant semantic search + payload filter
    filter_conditions = []

    if brand:
        filter_conditions.append({
            "key": "brand",
            "match": {"value": brand}
        })

    results = qdrant.search(
        query=keyword,
        query_filter={"must": filter_conditions} if filter_conditions else None,
        limit=10
    )

    # Post-filter: keyword 포함 확인
    return [r for r in results if keyword in r['text']]
```

---

### 3️⃣ **Q&A 로그 검색** (`search_recent_logs`)

**요구사항**: 과거 유사 질문 찾기

**구현 방식**:
```python
def search_recent_logs(query: str, limit: int = 5):
    # Qdrant semantic search with source_type filter
    filter = {
        "must": [
            {"key": "source_type", "match": {"value": "qa_log"}}
        ]
    }

    results = qdrant.search(
        query=query,
        query_filter=filter,
        limit=limit
    )

    return results
```

**데이터 요구사항**:
- Q&A 로그도 Qdrant에 저장 필요
- `payload.source_type = "qa_log"` 태깅

---

### 4️⃣ **Redmine 검색** (`search_redmine`)

**요구사항**: Redmine 관련 데이터만 검색

**구현 방식**:
```python
def search_redmine(keyword: str):
    # Qdrant semantic search with redmine filter
    filter = {
        "must": [
            {"key": "source_type", "match": {"value": "redmine"}}
        ]
    }

    results = qdrant.search(
        query=f"redmine {keyword}",
        query_filter=filter,
        limit=10
    )

    return results
```

**데이터 요구사항**:
- Redmine 데이터도 Qdrant에 저장 필요
- `payload.source_type = "redmine"` 태깅
- `payload.redmine_issue_id` 등 메타데이터

---

## 📝 구현 단계

### Phase 1: VectorRepository 확장
**목적**: Qdrant 필터링 기능 추가

**작업**:
1. `search_with_filter()` 메서드 추가
2. `scroll_with_filter()` 메서드 추가 (대용량 검색)
3. Payload 기반 필터링 지원

**파일**: `repositories/vector_repository.py`

---

### Phase 2: TextTools 구현
**목적**: MariaDB → Qdrant 전환

**작업**:
1. `text_tools.py` 생성
2. 4개 검색 도구 구현 (Qdrant 기반)
3. 도구명 변경:
   - `search_mariadb_by_error_code` → `search_text_by_error_code`
   - `search_mariadb_by_keyword` → `search_text_by_keyword`
   - `search_recent_logs` (유지)
   - `search_redmine` (유지)

**파일**: `agents/tools/text_tools.py`

---

### Phase 3: SearchAgent 업데이트
**목적**: TextTools 통합

**작업**:
1. Import 변경: `MariaDBTools` → `TextTools`
2. 초기화 변경: `db_repo` → `vector_repo`
3. Fallback chain 업데이트:
   - `search_mariadb_by_keyword` → `search_text_by_keyword`
4. System prompt 업데이트

**파일**: `agents/search_agent.py`

---

### Phase 4: 정리 및 테스트
**목적**: 레거시 제거 및 검증

**작업**:
1. `mariadb_tools.py` 삭제
2. `DatabaseRepository` 의존성 제거 (선택적)
3. 통합 테스트 실행
4. 성능 비교 (MariaDB vs Qdrant)

---

## 🎨 코드 설계

### VectorRepository 확장

```python
class VectorRepository:
    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """기존 semantic search"""

    def search_with_filter(
        self,
        query: str,
        filters: Dict,
        top_k: int = 5
    ) -> List[Dict]:
        """필터링된 semantic search"""
        search_results = self.client.search(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            query_vector=query_vector,
            query_filter=filters,
            limit=top_k
        )

    def scroll_with_text_filter(
        self,
        text_pattern: str,
        limit: int = 100
    ) -> List[Dict]:
        """텍스트 패턴 매칭 (에러 코드 등)"""
        # Qdrant scroll API 사용
```

### TextTools 구조

```python
class TextTools:
    def __init__(self, vector_repo: VectorRepository):
        self.vector_repo = vector_repo

    def search_by_error_code(self, error_code: str):
        # Semantic + post-filter

    def search_by_keyword(self, keyword: str, brand: Optional[str]):
        # Semantic + payload filter

    def search_recent_logs(self, query: str, limit: int):
        # Semantic with source_type filter

    def search_redmine(self, keyword: str):
        # Semantic with redmine filter
```

---

## ⚠️ 주의사항 및 고려사항

### 1. 데이터 마이그레이션
- **확인 필요**: Qdrant에 이미 모든 문서 저장되어 있는지?
- **Payload 구조**: `sentence`, `brand`, `source_type` 필드 존재 여부
- **누락 데이터**: Q&A logs, Redmine 데이터 Qdrant 저장 여부

### 2. 성능 고려
- **Semantic search**: MariaDB LIKE보다 느릴 수 있음
- **Post-filtering**: 추가 필터링으로 오버헤드 발생
- **캐싱**: 자주 검색되는 에러 코드 캐싱 고려

### 3. 정확도 검증
- **에러 코드**: Exact match 정확도 테스트 필요
- **키워드**: Semantic vs Keyword 정확도 비교
- **A/B 테스트**: MariaDB vs Qdrant 결과 비교

### 4. Fallback 전략
- Qdrant 실패 시 MariaDB fallback 유지? (선택적)
- 초기에는 MariaDB 병렬 실행 후 비교 가능

---

## 📊 성공 기준

### 기능 요구사항
- ✅ 4개 검색 도구 모두 Qdrant에서 동작
- ✅ 에러 코드 exact match 정확도 95% 이상
- ✅ 키워드 검색 정확도 MariaDB 대비 90% 이상
- ✅ 브랜드 필터링 정상 동작

### 성능 요구사항
- ✅ 평균 검색 속도 2초 이하
- ✅ Qdrant connection 안정성 99% 이상

### 코드 품질
- ✅ 단위 테스트 커버리지 80% 이상
- ✅ 통합 테스트 통과
- ✅ 레거시 코드 제거 완료

---

## 📅 구현 일정

| Phase | 작업 | 예상 시간 | 상태 |
|-------|------|----------|------|
| Phase 1 | VectorRepository 확장 | 30분 | ⏳ Pending |
| Phase 2 | TextTools 구현 | 45분 | ⏳ Pending |
| Phase 3 | SearchAgent 업데이트 | 30분 | ⏳ Pending |
| Phase 4 | 정리 및 테스트 | 30분 | ⏳ Pending |
| **Total** | | **~2.5시간** | |

---

## 🚀 실행 계획

### Step 1: VectorRepository 확장
```bash
# repositories/vector_repository.py 편집
- search_with_filter() 추가
- scroll_with_text_filter() 추가
```

### Step 2: TextTools 생성
```bash
# agents/tools/text_tools.py 생성
- TextTools 클래스 구현
- 4개 검색 메서드 구현
- Tool registry 등록
```

### Step 3: SearchAgent 통합
```bash
# agents/search_agent.py 편집
- Import 변경
- 초기화 로직 변경
- Fallback chain 업데이트
- System prompt 업데이트
```

### Step 4: 정리
```bash
# 레거시 제거
rm agents/tools/mariadb_tools.py
# 테스트 실행
python test_agent.py
```

---

## 🔍 검증 계획

### 단위 테스트
```python
# test_text_tools.py
def test_search_by_error_code():
    assert "50001" in results[0]['text']

def test_search_by_keyword_with_brand():
    assert all(r['metadata']['brand'] == 'rvs' for r in results)
```

### 통합 테스트
```python
# test_agent.py
def test_agent_with_error_code():
    response = agent.search("50001 에러 해결 방법")
    assert response['answer'] is not None
```

### 성능 테스트
```python
# benchmark.py
def compare_mariadb_vs_qdrant():
    # 동일 쿼리로 속도/정확도 비교
```

---

## 📚 참고 자료

### Qdrant 문서
- [Filtering](https://qdrant.tech/documentation/concepts/filtering/)
- [Scroll API](https://qdrant.tech/documentation/concepts/points/#scroll-points)
- [Payload](https://qdrant.tech/documentation/concepts/payload/)

### 내부 문서
- `/rsupport/software/R-agent/.env` - Qdrant 설정
- `repositories/vector_repository.py` - 현재 구현
- `agents/tools/mariadb_tools.py` - 레거시 구현

---

## ✅ 승인 및 시작

**계획 검토**: ✅ 완료
**시작 승인**: 대기 중
**구현 시작일**: 사용자 승인 후 즉시

---

**작성자**: Claude (R-Agent Migration Team)
**버전**: 1.0
**최종 수정**: 2025-11-07
