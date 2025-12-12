# 신규 Agent 기능 제안 분석

## 📋 제안된 기능

사용자가 제안한 두 가지 새로운 tool:

### 1. Document Full Content Tool
**목적**: 문서 전체 내용을 보여주는 tool
- 제목과 쿼리를 매칭
- 해당 문서 전체 내용을 요약하거나 표로 표시
- **Use Case**: "서비스 방화벽 정보 리스트 전체", "RVS 이슈 전체 목록"

### 2. Database Schema Tool
**목적**: DB 테이블 정의서를 찾아서 SQL 쿼리 생성
- Excel 형식의 테이블 정의서 검색
- 테이블 구조 분석
- SQL 쿼리 자동 생성
- **Use Case**: "user 테이블 스키마 보여줘", "session 테이블에서 활성 사용자 조회 쿼리"

---

## 🔍 현재 시스템 분석

### DB 구조
```
documents (13개 문서)
├─ doc_id (PK)
├─ file_name
├─ file_path
├─ file_type
└─ created_at

sentences (117,272개 청크)
├─ sentence_id (PK)
├─ doc_id (FK → documents)
├─ chunk_id (문서 내 순서)
├─ sentence (텍스트 내용, 평균 500자)
└─ created_at
```

### 문서 현황
```
파일 타입별 분포:
- CSV  : 6개 (에러 코드, Q&A 데이터)
- PDF  : 3개 (사용자 매뉴얼)
- DOCX : 2개 (트러블슈팅 가이드)
- XLSX : 1개 (RVS_issue.xlsx)
- Redmine: 1개 (이슈 데이터 114,951개 청크)

청크 분포:
- redmine_issues: 114,951 청크 (98%)
- RemoteView_error_codes.csv: 874 청크
- RemoteCall_Error_code.csv: 461 청크
- 기타: < 400 청크
```

### 스키마/테이블 관련 문서 검색 결과
```sql
SELECT * FROM documents
WHERE file_name LIKE '%테이블%'
   OR file_name LIKE '%스키마%'
   OR file_name LIKE '%정의서%'
   OR file_type LIKE '%xlsx%'
   OR file_type LIKE '%xls%';
```
**결과**: 1개만 발견 (RVS_issue.xlsx)

### 방화벽/리스트 관련 문서 검색 결과
```sql
SELECT * FROM documents
WHERE file_name LIKE '%방화벽%'
   OR file_name LIKE '%포트%'
   OR file_name LIKE '%리스트%';
```
**결과**: 0개

---

## 💡 분석 및 평가

### Tool 1: Document Full Content Tool

#### 현재 문제점
1. **청크 기반 검색의 한계**
   ```
   User: "RVS_issue.xlsx 전체 내용 보여줘"

   현재 시스템:
   → search_mariadb_by_keyword("RVS issue")
   → 38개 청크 중 일부만 반환 (예: 10개)
   → 문서 일부만 표시됨

   문제:
   ❌ 전체 문서 내용을 볼 수 없음
   ❌ 청크 순서가 섞여서 맥락 파악 어려움
   ❌ 표 형태 정보를 텍스트로만 제공
   ```

2. **리스트/표 요청 처리 부족**
   ```
   User: "방화벽 포트 리스트 전체 보여줘"

   현재 시스템:
   → 관련 문서가 없으면 "찾을 수 없음"
   → 있어도 청크로 쪼개져서 일부만 표시

   필요:
   ✅ 문서 전체를 표 형태로 정리
   ✅ Excel/CSV 데이터를 구조화된 표로 표시
   ```

#### 필요성 평가
**우선순위**: 🟡 **중간**

**이유**:
1. ✅ **실제 Use Case 존재**
   - RVS_issue.xlsx (38개 청크) - 전체 이슈 목록 확인 필요
   - RemoteView_error_codes.csv (874개 청크) - 에러 코드 전체 리스트
   - RemoteCall_Error_code.csv (461개 청크) - 에러 코드 전체 리스트

2. ⚠️ **빈도는 낮을 것으로 예상**
   - 총 13개 문서만 존재
   - 대부분의 질문은 특정 정보 검색 (현재 시스템으로 충분)
   - 전체 문서가 필요한 경우는 10-20% 정도로 추정

3. ✅ **품질 개선 가능**
   - 에러 코드 전체 목록 요청 시 유용
   - CSV/Excel 데이터를 표로 보여주면 가독성 향상

#### 구현 방안

**Option 1: 간단한 Full Document Retrieval Tool**
```python
def get_full_document(file_name_query: str) -> Dict:
    """
    파일명으로 문서를 찾아서 전체 청크를 반환

    Args:
        file_name_query: 파일명 검색어 (예: "RVS_issue", "방화벽")

    Returns:
        {
            'file_name': 'RVS_issue.xlsx',
            'doc_id': 5,
            'chunk_count': 38,
            'full_content': "청크1\n청크2\n...\n청크38",
            'chunks': [
                {'chunk_id': 0, 'text': '...'},
                {'chunk_id': 1, 'text': '...'},
                ...
            ]
        }
    """
```

**실행 흐름**:
```
1. documents 테이블에서 file_name LIKE '%query%' 검색
2. 매칭된 doc_id로 sentences 테이블에서 모든 청크 조회
3. chunk_id 순서로 정렬
4. 전체 텍스트 재구성
5. (Optional) CSV/Excel이면 표 형태로 파싱
```

**장점**:
- ✅ 구현 간단 (1-2시간)
- ✅ 기존 DB 구조 그대로 사용
- ✅ 전체 문서 내용 제공 가능

**단점**:
- ⚠️ 대용량 문서는 토큰 제한 (redmine_issues 114,951 청크는 불가능)
- ⚠️ 표 형태 파싱은 추가 작업 필요

---

**Option 2: Smart Document Summary Tool**
```python
def get_document_summary_or_table(
    file_name_query: str,
    format: str = "auto"  # "text", "table", "summary"
) -> Dict:
    """
    문서를 찾아서 적절한 형태로 표시

    - CSV/Excel: 표 형태로 파싱
    - 대용량: 요약 생성
    - 소량: 전체 텍스트
    """
```

**실행 흐름**:
```
1. 문서 검색 및 chunk_count 확인
2. 판단:
   - chunk_count < 50: 전체 텍스트 반환
   - chunk_count < 200: 요약 생성 (OpenAI로)
   - file_type == csv/xlsx: 표 형태로 파싱
   - chunk_count > 200: 에러 또는 샘플만 반환
3. 적절한 형태로 포맷팅
```

**장점**:
- ✅ 상황에 맞는 최적 표시
- ✅ 표 형태 지원
- ✅ 대용량 문서도 처리 가능 (요약)

**단점**:
- ⚠️ 구현 복잡 (3-5시간)
- ⚠️ 표 파싱 로직 필요
- ⚠️ 요약 품질 보장 어려움

---

### Tool 2: Database Schema Tool

#### 현재 문제점
```
User: "user 테이블 스키마 보여줘"

현재 시스템:
→ search_mariadb_by_keyword("user 테이블")
→ 관련 청크 반환 (있다면)
→ 스키마 정보 없음

문제:
❌ DB 스키마 문서가 거의 없음 (1개뿐)
❌ SQL 쿼리 생성 기능 없음
```

#### 필요성 평가
**우선순위**: 🔴 **낮음**

**이유**:
1. ❌ **데이터 부족**
   - 현재 DB 스키마 문서: 1개뿐 (RVS_issue.xlsx)
   - 테이블 정의서가 거의 없음
   - 검색 대상이 없으면 tool이 무용지물

2. ❌ **SQL 쿼리 생성의 한계**
   - DB 스키마 정보가 없으면 쿼리 생성 불가능
   - GPT-4o-mini가 이미 SQL 쿼리 생성 가능 (스키마만 주어지면)
   - 굳이 별도 tool로 만들 필요성 낮음

3. ⚠️ **우선순위 낮음**
   - 현재 use case가 거의 없음
   - 데이터 추가 후 재검토 필요

#### 구현 방안 (참고용)

**Option 1: Schema Document Search Tool**
```python
def search_table_schema(table_name: str) -> Dict:
    """
    테이블 스키마 문서 검색

    Args:
        table_name: 테이블명 (예: "user", "session")

    Returns:
        {
            'table_name': 'user',
            'schema_documents': [
                {
                    'file_name': 'DB_schema.xlsx',
                    'columns': [...],
                    'description': '...'
                }
            ]
        }
    """
```

**Option 2: SQL Query Generator Tool**
```python
def generate_sql_query(
    table_name: str,
    operation: str,  # "select", "insert", "update", "delete"
    conditions: str = None
) -> str:
    """
    스키마 정보를 기반으로 SQL 쿼리 생성

    전제조건: 스키마 문서가 존재해야 함
    """
```

**현실적 판단**:
- ⚠️ **지금 구현할 필요 없음**
- 📌 **나중에 DB 스키마 문서가 추가되면 재검토**

---

## 🎯 최종 권장사항

### 우선순위 1: Document Full Content Tool (권장 ✅)

**이유**:
1. ✅ 실제 use case 존재 (RVS_issue.xlsx, 에러 코드 리스트)
2. ✅ 현재 시스템의 명확한 한계 해결
3. ✅ 구현 난이도 낮음 (1-2시간)
4. ✅ 즉시 활용 가능

**추천 구현**:
- **Option 1 (간단한 Full Document Retrieval)** 먼저 구현
- 나중에 필요하면 표 파싱 기능 추가

**예상 효과**:
```
Before:
User: "RVS 이슈 전체 목록 보여줘"
Agent: "10개 청크 중 일부만 표시... (불완전)"

After:
User: "RVS 이슈 전체 목록 보여줘"
Agent: "RVS_issue.xlsx 전체 38개 이슈:
        1. 이슈 A
        2. 이슈 B
        ...
        38. 이슈 Z"
```

**구현 계획**:
1. `agents/tools/document_tools.py` 생성
2. `get_full_document(file_name_query)` 함수 구현
3. Tool registry에 등록
4. 테스트 (RVS_issue.xlsx, error_codes.csv)

---

### 우선순위 2: Database Schema Tool (보류 ⏸️)

**이유**:
1. ❌ 현재 DB 스키마 문서가 거의 없음 (1개뿐)
2. ❌ 즉시 활용 가능한 use case 부족
3. ⚠️ 구현해도 사용 빈도 매우 낮을 것으로 예상

**권장사항**:
- 🔄 **보류** - 데이터 추가 후 재검토
- 📌 DB 스키마 문서가 10개 이상 추가되면 재평가
- 💡 현재는 GPT-4o-mini에게 직접 SQL 생성 요청하는 것으로 충분

---

## 📊 구현 비교표

| Tool | 우선순위 | 구현 난이도 | 예상 시간 | 즉시 효과 | 사용 빈도 |
|------|---------|------------|----------|----------|----------|
| **Document Full Content** | 🟢 **높음** | 🟢 낮음 | 1-2시간 | ✅ 높음 | 10-20% |
| **Database Schema** | 🔴 **낮음** | 🟡 중간 | 3-4시간 | ❌ 거의 없음 | <5% |

---

## 💬 사용자 피드백 필요 사항

### 질문 1: Document Full Content Tool
**Q**: "RVS 이슈 전체 목록", "에러 코드 전체 리스트" 같은 요청이 실제로 얼마나 있을까요?
- **많다** (주 1회 이상) → 즉시 구현 권장 ✅
- **가끔** (월 1-2회) → 구현 권장 (우선순위 낮춤)
- **거의 없다** → 보류

### 질문 2: Database Schema Tool
**Q**: 앞으로 DB 테이블 정의서, 스키마 문서를 추가할 계획이 있나요?
- **있다** (10개 이상 추가 예정) → 나중에 구현 고려
- **있다** (5개 미만) → 보류 유지
- **없다** → 구현 불필요 ❌

### 질문 3: 표 형태 표시
**Q**: CSV/Excel 데이터를 표 형태로 보여주는 기능이 필요한가요?
- **필요** → Option 2 (Smart Summary) 구현
- **불필요** → Option 1 (Simple Retrieval) 구현

---

## 🚀 다음 단계

### 즉시 실행 가능
1. ✅ **Document Full Content Tool 구현** (1-2시간)
   - `agents/tools/document_tools.py` 생성
   - `get_full_document()` 함수 작성
   - Tool registry 등록
   - 테스트

### 나중에 검토
2. ⏸️ **Database Schema Tool** - 데이터 추가 후 재검토
3. 📋 **표 형태 파싱** - 사용자 피드백 후 결정

---

**작성일**: 2025-11-08
**분석자**: Claude Code
**결론**: Document Full Content Tool은 즉시 구현 권장, Database Schema Tool은 보류
