# Chat UI 아키텍처 설명

## 🤔 질문: 웹은 Streamlit으로 떠있는데 에이전트는 어떻게 실행되고 있는거야?

## 📐 아키텍처 구조

### 1. 단일 프로세스 구조

```
┌─────────────────────────────────────────────────────────┐
│  Streamlit 프로세스 (python chat_ui.py)                   │
│                                                           │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Streamlit 웹 서버 (http://localhost:8501)       │    │
│  │  - HTML/CSS/JavaScript 렌더링                    │    │
│  │  - 브라우저 ↔ 서버 통신                           │    │
│  └─────────────────────────────────────────────────┘    │
│                        ↓                                 │
│  ┌─────────────────────────────────────────────────┐    │
│  │  st.session_state (세션 메모리)                   │    │
│  │  - messages: 대화 히스토리                         │    │
│  │  - agent: SearchAgent 인스턴스 ← 여기!            │    │
│  │  - search_count: 검색 카운트                       │    │
│  └─────────────────────────────────────────────────┘    │
│                        ↓                                 │
│  ┌─────────────────────────────────────────────────┐    │
│  │  SearchAgent (같은 프로세스 내에서 실행)           │    │
│  │  - search() 메서드 호출                           │    │
│  │  - 도구 선택 및 실행                               │    │
│  │  - 답변 생성                                       │    │
│  └─────────────────────────────────────────────────┘    │
│                        ↓                                 │
│  ┌─────────────────────────────────────────────────┐    │
│  │  외부 서비스 (네트워크 통신)                        │    │
│  │  - MySQL DB (127.0.0.1:9443)                     │    │
│  │  - Qdrant (localhost:6333)                       │    │
│  │  - Elasticsearch (localhost:9200)                │    │
│  │  - OpenAI API (api.openai.com)                   │    │
│  └─────────────────────────────────────────────────┘    │
│                                                           │
└─────────────────────────────────────────────────────────┘
```

### 2. 코드 흐름

#### Step 1: Streamlit 시작 시
```python
# chat_ui.py

def initialize_session_state():
    if 'agent' not in st.session_state:
        st.session_state.agent = SearchAgent()  # ← 여기서 에이전트 생성!
```

**설명**:
- Streamlit이 시작되면 `initialize_session_state()` 호출
- `SearchAgent()` 인스턴스 생성
- `st.session_state.agent`에 저장 (세션 메모리에 유지)
- **별도의 서버가 아님 - 같은 프로세스 내에서 객체로 존재**

#### Step 2: 사용자가 질문 입력
```python
# 사용자 입력
if prompt := st.chat_input("질문을 입력하세요..."):
```

**설명**:
- 브라우저에서 질문 입력 → Streamlit 서버로 전송
- Streamlit은 이벤트 핸들러 실행

#### Step 3: SearchAgent 실행
```python
# Agent 검색 실행
with st.spinner("🔍 검색 중..."):
    result = st.session_state.agent.search(  # ← 동기적으로 실행!
        question=prompt,
        max_iterations=max_iterations,
        debug=True
    )

    answer = result['answer']
    sources = result['sources']
```

**설명**:
- `st.session_state.agent.search()` 직접 호출
- **동기적 실행**: SearchAgent가 작업 완료할 때까지 대기
- 같은 스레드에서 실행 (블로킹)
- 브라우저에는 "🔍 검색 중..." 스피너 표시

#### Step 4: 결과 표시
```python
# 검색 성공 후 화면 새로고침
st.rerun()
```

**설명**:
- 검색 완료 후 화면 새로고침
- 새로운 답변이 대화 히스토리에 추가되어 표시

## 🔍 상세 분석

### Q1: 에이전트는 별도의 서버로 실행되나요?
**A**: 아니요! SearchAgent는 Streamlit 프로세스 내부에서 **객체**로 존재합니다.

```python
# 별도 서버가 아님!
st.session_state.agent = SearchAgent()  # ← 단순 객체 생성
```

### Q2: 에이전트는 언제 초기화되나요?
**A**: 사용자가 처음 웹페이지에 접속할 때 1회 초기화됩니다.

```python
def initialize_session_state():
    if 'agent' not in st.session_state:
        # 세션에 없으면 생성 (첫 접속 시)
        st.session_state.agent = SearchAgent()
```

### Q3: 여러 사용자가 동시 접속하면?
**A**: 각 사용자마다 **별도의 session_state**를 가지므로 각자의 SearchAgent 인스턴스를 갖습니다.

```
사용자 A 브라우저
  ↓
Streamlit Session A
  ├─ st.session_state.agent → SearchAgent 인스턴스 #1
  └─ st.session_state.messages → A의 대화 히스토리

사용자 B 브라우저
  ↓
Streamlit Session B
  ├─ st.session_state.agent → SearchAgent 인스턴스 #2
  └─ st.session_state.messages → B의 대화 히스토리
```

### Q4: 검색 중에는 UI가 멈추나요?
**A**: 네, 동기적으로 실행되므로 SearchAgent가 작업 완료할 때까지 대기합니다.

```python
with st.spinner("🔍 검색 중..."):  # ← 스피너 표시
    result = st.session_state.agent.search(...)  # ← 블로킹 (10-30초)
    # 여기서 대기...
```

**장점**:
- 구현이 단순함
- 상태 관리가 쉬움

**단점**:
- 긴 검색 시간 동안 UI 블로킹
- 하지만 스피너가 표시되므로 사용자는 진행 중임을 알 수 있음

### Q5: 에이전트는 어떻게 DB/Qdrant/OpenAI와 통신하나요?
**A**: SearchAgent가 직접 네트워크 호출을 합니다.

```python
class SearchAgent:
    def __init__(self):
        # 같은 프로세스 내에서 연결
        self.db_repo = DatabaseRepository()  # → MySQL 연결
        self.vector_repo = VectorRepository()  # → Qdrant 연결
        self.es_repo = ElasticsearchRepository()  # → ES 연결
        self.client = OpenAI(api_key=...)  # → OpenAI 연결
```

## 🔄 전체 실행 흐름

```
1. 터미널: streamlit run chat_ui.py --server.port 8501
   ↓
2. Streamlit 프로세스 시작
   ↓
3. 웹 서버 시작 (http://localhost:8501)
   ↓
4. 사용자가 브라우저로 접속
   ↓
5. initialize_session_state() 실행
   ↓
6. SearchAgent() 인스턴스 생성 (10-15초)
   - MySQL 연결
   - Qdrant 연결 (117K 벡터 로드)
   - Embedding 모델 로드 (BAAI/bge-m3)
   - Elasticsearch 연결
   ↓
7. UI 렌더링 완료
   ↓
8. 사용자가 질문 입력
   ↓
9. st.session_state.agent.search() 호출 (동기적)
   ↓
10. SearchAgent가 도구 실행
    - Qdrant 검색
    - MariaDB 쿼리
    - Elasticsearch 검색
    - OpenAI API 호출 (답변 생성)
    ↓
11. 결과 반환 → UI 업데이트
    ↓
12. st.rerun() → 화면 새로고침
```

## 💡 핵심 정리

1. **단일 프로세스**: Streamlit과 SearchAgent는 같은 Python 프로세스에서 실행
2. **객체 기반**: SearchAgent는 별도 서버가 아닌 메모리 내 객체
3. **세션 분리**: 각 사용자는 독립적인 SearchAgent 인스턴스 사용
4. **동기 실행**: 검색 중에는 UI가 대기 (스피너 표시)
5. **직접 통신**: SearchAgent가 DB/Qdrant/OpenAI와 직접 통신

## 🆚 다른 아키텍처와 비교

### 현재 구조 (Streamlit 통합)
```
[브라우저] ↔ [Streamlit + SearchAgent (단일 프로세스)]
           ↔ [MySQL/Qdrant/ES/OpenAI]
```

**장점**:
- 구현 간단
- 상태 관리 쉬움
- 배포 단순 (1개 프로세스)

**단점**:
- UI 블로킹
- 동시 사용자 많으면 성능 저하 가능

### 분리된 API 구조 (대안)
```
[브라우저] ↔ [웹 서버] ↔ [API 서버 (FastAPI)]
                         ↔ [SearchAgent]
                         ↔ [MySQL/Qdrant/ES/OpenAI]
```

**장점**:
- 비동기 처리 가능
- 확장성 좋음
- 여러 클라이언트 지원

**단점**:
- 구현 복잡
- 배포/관리 복잡
- 네트워크 오버헤드

## 📝 현재 프로젝트에서 선택한 이유

현재는 **Streamlit 통합 구조**를 사용합니다:

1. **빠른 프로토타이핑**: 피드백 수집이 주 목적
2. **내부 사용**: 동시 사용자 수 적음 (1-3명)
3. **단순성**: 배포/관리 간편
4. **충분한 성능**: 검색 시간 10-30초는 허용 가능

향후 확장이 필요하면 FastAPI로 분리할 수 있습니다.

---

**작성일**: 2025-11-07
**질문**: "웹은 streamlit으로 떠있는데 에이전트는 어떻게 실행되고 있는거야?"
**답변**: Streamlit 프로세스 내부에서 SearchAgent 객체로 실행됨
