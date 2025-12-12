# 기존 시스템 vs 새로운 Agent 시스템 비교

## 📌 개요

`/faiss`의 기존 검색 파이프라인과 `/faiss-agent`의 새로운 Agent 시스템은 **완전히 다른 아키텍처**를 사용합니다.

---

## 🏗️ 아키텍처 비교

### 기존 시스템 (`/rsupport/software/faiss/`)

```
┌─────────────────────────────────────────┐
│  Web API (FastAPI)                      │
├─────────────────────────────────────────┤
│  recursive_rag.py                       │
│  - 단일 검색 함수                        │
│  - 고정된 로직                           │
├─────────────────────────────────────────┤
│  VectorDBHandler                        │
│  - hybrid_search() 고정 메서드          │
│  - FAISS만 사용                          │
└─────────────────────────────────────────┘
```

**특징**:
- 하드코딩된 검색 로직
- FAISS 벡터 검색 중심
- 재귀적 RAG (follow-up 질문)

---

### 새로운 Agent 시스템 (`/rsupport/software/faiss-agent/`)

```
┌─────────────────────────────────────────┐
│  Web API (FastAPI)                      │
├─────────────────────────────────────────┤
│  SearchAgent (ReAct Pattern)           │
│  - LLM이 도구 선택                       │
│  - 동적 검색 전략                        │
├─────────────────────────────────────────┤
│  7개 검색 도구 (Tool Registry)          │
│  ┌──────────┬──────────┬──────────┐    │
│  │ MariaDB  │  FAISS   │   ES     │    │
│  │ (4 tools)│ (1 tool) │(2 tools) │    │
│  └──────────┴──────────┴──────────┘    │
└─────────────────────────────────────────┘
```

**특징**:
- **자율적 도구 선택** (LLM이 판단)
- **다중 검색 소스** (MariaDB, FAISS, ES)
- **ReAct 패턴** (Reasoning + Acting)
- **외부 지식 보강** (기술 용어 설명)

---

## 🔍 검색 로직 비교

### 기존 시스템: 고정된 Hybrid Search

```python
# /rsupport/software/faiss/noLangChain/recursive_rag.py

async def recursive_rag(query: str, ...):
    # 1. 항상 hybrid_search 사용 (고정)
    results = handler.hybrid_search(query, top_k=5)

    # 2. 결과 없으면 세션 히스토리 활용
    if not results and session_id in SESSION_DOC_HISTORY:
        # 최근 본 문서에서 가져오기
        history_results = get_from_history(...)

    # 3. GPT가 추가 정보 필요 여부 판단
    need_more, follow_up = await gpt_check_need_more_info(summary, query)

    # 4. 필요하면 재귀 호출 (follow-up 질문)
    if need_more and depth < max_depth:
        return await recursive_rag(follow_up, depth=depth+1, ...)
```

**검색 방식**:
- `hybrid_search()` **하나만** 사용
- FAISS 벡터 검색 + BM25 키워드 검색 혼합
- 항상 같은 로직 실행

**장점**:
- ✅ 단순하고 이해하기 쉬움
- ✅ 빠른 응답 (단일 검색)

**단점**:
- ❌ 유연성 부족 (검색 방식 변경 어려움)
- ❌ 에러 코드, 레드마인 같은 특수 케이스 처리 불가
- ❌ FAISS만 사용 (MariaDB, ES 활용 못함)
- ❌ 검색 실패 시 대안 없음

---

### 새로운 시스템: 자율적 도구 선택 (ReAct)

```python
# /rsupport/software/faiss-agent/agents/search_agent.py

def search(self, question: str):
    for iteration in range(max_iterations):
        # 1. LLM이 상황 분석 후 도구 선택
        decision = self._get_agent_decision(question, context)

        # 2. 선택된 도구 실행
        if decision.action == "search_mariadb_by_error_code":
            results = self.search_by_error_code(error_code)
        elif decision.action == "search_faiss_semantic":
            results = self.search_semantic(query)
        elif decision.action == "search_elasticsearch_bm25":
            results = self.search_bm25(query)
        # ... 7개 도구 중 선택

        # 3. 결과 검증 및 다음 액션 결정
        validation = self._validate_results(results)
        if validation.sufficient:
            break

        # 4. 충분하지 않으면 다른 도구 시도
        # C+A 개선: 2회 실패 시 자동 폴백
```

**검색 방식**:
- **7개 도구** 중 LLM이 **동적 선택**
- 에러 코드 → MariaDB
- 의미 기반 → FAISS
- 복잡한 키워드 → Elasticsearch
- 레드마인 → 전용 테이블

**장점**:
- ✅ **유연한 검색 전략** (상황에 맞는 도구 선택)
- ✅ **다중 데이터 소스** (DB, Vector, ES)
- ✅ **실패 시 자동 폴백** (C+A 개선)
- ✅ **특수 케이스 처리** (에러 코드, 레드마인)

**단점**:
- ❌ 복잡한 구조
- ❌ LLM 호출 비용 증가
- ❌ 응답 시간 증가 (여러 도구 시도)

---

## 📊 기능 비교표

| 기능 | 기존 시스템 | 새로운 Agent 시스템 |
|------|-----------|------------------|
| **검색 방식** | 고정 (hybrid_search) | 동적 (7개 도구 선택) |
| **데이터 소스** | FAISS만 | MariaDB + FAISS + ES |
| **에러 코드 검색** | ❌ 불가 | ✅ 전용 도구 |
| **레드마인 검색** | ❌ 일반 검색만 | ✅ 4개 테이블 전용 |
| **과거 로그 검색** | ❌ 불가 | ✅ qa_logs 검색 |
| **키워드 검색** | BM25만 | ✅ SQL LIKE + BM25 |
| **의미 검색** | ✅ FAISS | ✅ FAISS |
| **재귀 검색** | ✅ follow-up | ❌ 없음 |
| **세션 히스토리** | ✅ 활용 | ❌ 없음 |
| **실패 시 폴백** | ❌ 없음 | ✅ 자동 체인 |
| **외부 지식** | ❌ 없음 | ✅ 기술 용어 설명 |
| **브랜드 필터** | ❌ 없음 | ✅ 5개 브랜드 |
| **응답 시간** | 빠름 (1-3초) | 중간 (3-7초) |
| **유연성** | 낮음 | 높음 |
| **LLM 호출** | 2-3회 | 3-5회 |

---

## 🔄 검색 흐름 비교

### 기존 시스템 흐름

```
사용자 질문
    ↓
hybrid_search (FAISS + BM25)
    ↓
결과 있음? ─── NO ──→ 세션 히스토리 검색
    ↓ YES              ↓
문맥 요약            유사도 재계산
    ↓                  ↓
추가 정보 필요? ──────┘
    ↓ YES
follow-up 질문 생성
    ↓
recursive_rag (재귀)
    ↓
최종 답변
```

**특징**:
- 선형적 흐름
- 항상 같은 경로
- 재귀로 심화 검색

---

### 새로운 Agent 시스템 흐름

```
사용자 질문
    ↓
질문 분석 (LLM)
    ↓
┌─────────────────────┐
│ 도구 선택 (ReAct)   │
├─────────────────────┤
│ - 에러 코드?        │ → MariaDB 에러 코드 검색
│ - 레드마인?         │ → Redmine 전용 검색
│ - 의미 기반?        │ → FAISS 벡터 검색
│ - 키워드 리스트?    │ → Elasticsearch BM25
│ - 과거 질문?        │ → qa_logs 검색
└─────────────────────┘
    ↓
도구 실행
    ↓
결과 검증
    ↓
충분? ─── NO ──→ 다른 도구 시도
  ↓ YES           (C+A 폴백 체인)
외부 지식 필요?
  ↓ YES
기술 용어 설명 추가
  ↓
최종 답변 생성
```

**특징**:
- 분기형 흐름
- 상황별 최적 경로
- 실패 시 자동 폴백

---

## 💻 코드 구조 비교

### 기존 시스템 구조

```
/rsupport/software/faiss/
├── noLangChain/
│   ├── recursive_rag.py          # 145줄 - 단일 검색 로직
│   ├── db_handler.py             # DB + FAISS 통합
│   ├── llm_handler.py            # OpenAI 호출
│   └── config/settings.py        # 설정
└── web/
    └── app.py                    # FastAPI 서버
```

**특징**:
- 단순한 파일 구조
- 모놀리식 설계
- 145줄의 핵심 로직

---

### 새로운 Agent 시스템 구조

```
/rsupport/software/faiss-agent/
├── agents/
│   ├── search_agent.py           # 788줄 - ReAct 패턴 Agent
│   └── tools/                    # 도구 모음
│       ├── mariadb_tools.py      # MariaDB 4개 도구
│       ├── vector_tools.py       # FAISS 1개 도구
│       ├── es_tools.py           # ES 2개 도구
│       └── tool_registry.py      # 도구 등록 시스템
├── repositories/                 # 데이터 접근 계층
│   ├── db_repository.py          # MariaDB 쿼리
│   ├── vector_repository.py      # FAISS 벡터 검색
│   └── es_repository.py          # Elasticsearch 검색
├── config/
│   └── settings.py               # 설정 관리
└── web/
    └── app.py                    # FastAPI 서버
```

**특징**:
- 계층적 구조
- 도구 기반 설계 (Tool Registry)
- Repository 패턴
- 788줄의 Agent 로직 (5배 증가)

---

## 🎯 사용 사례별 비교

### 케이스 1: 에러 코드 질문

**질문**: "RVS 설치 시 50001 에러 발생"

#### 기존 시스템
```python
# hybrid_search로 검색
results = handler.hybrid_search("RVS 설치 시 50001 에러 발생", top_k=5)
# → FAISS 벡터 유사도로 검색
# → "50001" 정확히 매칭 못할 수 있음
# → 관련 없는 문서도 포함 가능
```
❌ **결과**: 에러 코드를 정확히 찾지 못할 가능성

#### 새로운 Agent 시스템
```python
# LLM이 에러 코드 감지
# → search_mariadb_by_error_code("50001") 선택
results = SELECT * FROM sentences WHERE sentence LIKE '%50001%'
# → 정확한 에러 코드 매칭
```
✅ **결과**: 에러 코드 포함 문서 6개 정확히 발견

---

### 케이스 2: 레드마인 일감 검색

**질문**: "레드마인에서 국민은행 SSO 관련 일감 찾아줘"

#### 기존 시스템
```python
# hybrid_search로 검색
results = handler.hybrid_search("레드마인 국민은행 SSO", top_k=5)
# → sentences 테이블만 검색
# → redmine_issues, redmine_journals 같은 전용 테이블 활용 못함
```
❌ **결과**: 일반 문서만 검색, 레드마인 정보 부족

#### 새로운 Agent 시스템
```python
# LLM이 "레드마인" 키워드 감지
# → search_redmine("국민은행 SSO") 선택
# → 4개 테이블 검색:
#   - redmine_issues (일감)
#   - redmine_journals (코멘트)
#   - redmine_relations (관계)
#   - redmine_sync_log (로그)
```
✅ **결과**: 레드마인 전용 테이블에서 관련 일감 발견

---

### 케이스 3: 검색 결과 없을 때

**질문**: "레드마인 SSO 연동"

#### 기존 시스템
```python
# hybrid_search 실패 (0개)
results = handler.hybrid_search("레드마인 SSO 연동", top_k=5)
# → []

# 세션 히스토리 활용
if session_id in SESSION_DOC_HISTORY:
    # 최근 본 문서에서 가져오기
    history_results = get_from_history(session_id)
    # → 유사도 재계산
```
✅ **세션 히스토리 폴백** 있음

#### 새로운 Agent 시스템
```python
# 1차: search_mariadb_by_keyword("레드마인 SSO") → 0개
# 2차: C+A 폴백 자동 발동
#      → search_faiss_semantic("레드마인 SSO 연동") → 3개
# 3차: 외부 지식 보강
#      → SSO 개념 설명 추가
```
✅ **자동 폴백 체인 + 외부 지식** 있음

---

## 🔑 핵심 차이점

### 1. 검색 전략

| | 기존 | 새로운 |
|---|---|---|
| **방식** | 고정 (hybrid_search) | 동적 (7개 도구 선택) |
| **유연성** | 낮음 | 높음 |
| **특수 케이스** | 처리 불가 | 전용 도구 |

### 2. 데이터 활용

| | 기존 | 새로운 |
|---|---|---|
| **FAISS** | ✅ 사용 | ✅ 사용 |
| **MariaDB** | ❌ 직접 활용 안함 | ✅ 4개 전용 도구 |
| **Elasticsearch** | ❌ 사용 안함 | ✅ BM25 랭킹 |
| **세션 히스토리** | ✅ 활용 | ❌ 없음 |
| **과거 로그** | ❌ 없음 | ✅ qa_logs 검색 |

### 3. 실패 처리

| | 기존 | 새로운 |
|---|---|---|
| **검색 실패 시** | 세션 히스토리 | C+A 폴백 체인 |
| **재귀 검색** | ✅ follow-up | ❌ 없음 |
| **외부 지식** | ❌ 없음 | ✅ 기술 용어 |

### 4. 아키텍처

| | 기존 | 새로운 |
|---|---|---|
| **패턴** | 재귀 RAG | ReAct Agent |
| **설계** | 모놀리식 | 계층적 (Repository) |
| **확장성** | 어려움 | 쉬움 (도구 추가) |
| **복잡도** | 낮음 (145줄) | 높음 (788줄) |

---

## 🤔 어느 것이 더 나은가?

### 기존 시스템의 장점

✅ **간단함**: 코드가 단순하고 이해하기 쉬움
✅ **빠름**: 단일 검색으로 빠른 응답
✅ **세션 기억**: 사용자 히스토리 활용
✅ **심화 검색**: 재귀로 follow-up 질문

**적합한 경우**:
- 단순한 Q&A
- 빠른 응답 필요
- 세션 컨텍스트 중요

---

### 새로운 Agent 시스템의 장점

✅ **유연함**: 상황별 최적 도구 선택
✅ **정확함**: 에러 코드, 레드마인 등 특수 케이스 처리
✅ **완전함**: 다중 데이터 소스 활용
✅ **회복력**: 실패 시 자동 폴백
✅ **지능형**: LLM이 검색 전략 결정

**적합한 경우**:
- 복잡한 질문
- 다양한 데이터 소스 필요
- 특수 케이스 많음 (에러 코드, 레드마인)
- 검색 정확도 중요

---

## 🔮 결론

### 기존 시스템 (`/faiss/`)
```
재귀 RAG 패턴
- FAISS 벡터 검색 중심
- 단순하고 빠름
- 세션 히스토리 활용
```

### 새로운 Agent 시스템 (`/faiss-agent/`)
```
ReAct Agent 패턴
- 7개 도구 자율 선택
- 복잡하지만 강력함
- 다중 데이터 소스 + 외부 지식
```

### 병행 운영 가능?

**YES!** 두 시스템은 독립적입니다:

```
/faiss/              → 기존 사용자용 (빠른 응답)
/faiss-agent/        → 새로운 고급 검색용 (정확한 답변)

공유 자원:
- MariaDB (sentences, qa_logs, redmine 테이블)
- FAISS 인덱스 (embedding_save/)
- Elasticsearch 인덱스
```

**권장사항**:
1. **기존 시스템** 유지 → 일반 Q&A용
2. **새로운 Agent** 추가 → 복잡한 질문, 관리자용
3. 사용자 피드백으로 점진적 마이그레이션

---

## 📝 요약

| 측면 | 기존 | 새로운 Agent |
|------|------|------------|
| **검색 방식** | 고정 hybrid | 동적 7개 도구 |
| **데이터 소스** | FAISS | DB+FAISS+ES |
| **특수 케이스** | ❌ | ✅ |
| **응답 속도** | 빠름 | 중간 |
| **정확도** | 중간 | 높음 |
| **복잡도** | 낮음 | 높음 |
| **적용 대상** | 일반 Q&A | 복잡한 검색 |

**완전히 다른 접근 방식이지만, 상황에 맞게 병행 사용 가능합니다!** 🎯

---

**작성일**: 2025-11-03
**작성자**: Claude Code
**버전**: 1.0
