# FastAPI 마이그레이션 계획

## 🎯 현재 상황과 문제점

### 현재 구조 (Streamlit)
```
[브라우저] ↔ [Streamlit + SearchAgent (단일 프로세스)]
           ↔ [MySQL/Qdrant/ES/OpenAI]
```

### 문제점

1. **동기 블로킹**:
   - SearchAgent 실행 중 UI 완전 멈춤
   - 10-30초 동안 다른 작업 불가
   ```python
   result = agent.search(question)  # ← 블로킹
   ```

2. **동시성 제한**:
   - 사용자 A가 검색 중이면 사용자 B도 대기
   - 세션별로 분리되지만 프로세스는 공유

3. **확장성 부족**:
   - 수평 확장 어려움
   - 로드 밸런싱 불가
   - 트래픽 증가 시 성능 급격히 저하

4. **모니터링 어려움**:
   - API 엔드포인트 없음
   - 메트릭 수집 어려움
   - 에러 추적 복잡

5. **클라이언트 제한**:
   - 웹 브라우저만 가능
   - 모바일 앱, CLI 도구 등 통합 불가

## 🚀 FastAPI 목표 구조

### 비동기 API 서버 구조
```
[클라이언트]
    ↓
[Nginx/Load Balancer]
    ↓
[FastAPI Server 1] [FastAPI Server 2] [FastAPI Server N]
    ↓
[Redis Queue (Celery)]
    ↓
[SearchAgent Workers (비동기)]
    ↓
[MySQL/Qdrant/ES/OpenAI]
```

### 주요 개선점

1. **완전 비동기**:
   ```python
   @app.post("/api/search")
   async def search(request: SearchRequest):
       task = await celery_app.send_task(
           "search_agent.search",
           args=[request.question]
       )
       return {"task_id": task.id}

   @app.get("/api/search/{task_id}")
   async def get_result(task_id: str):
       result = await AsyncResult(task_id).get()
       return result
   ```

2. **동시성 처리**:
   - 100명이 동시에 검색해도 문제없음
   - 각 요청은 독립적인 워커에서 처리

3. **수평 확장**:
   - FastAPI 서버 N개 추가 가능
   - Worker 프로세스 동적 증설
   - 로드 밸런서로 트래픽 분산

4. **다양한 클라이언트**:
   - 웹 프론트엔드 (React, Vue)
   - 모바일 앱 (iOS, Android)
   - CLI 도구
   - 다른 서비스 통합 (Slack, Teams)

## 📐 FastAPI 아키텍처 설계

### 1. API 엔드포인트

#### 검색 API
```python
# POST /api/v1/search
{
    "question": "Docker란 무엇인가요?",
    "user_id": "user123",
    "max_iterations": 5,
    "options": {
        "debug": true
    }
}

# Response
{
    "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "status": "pending",
    "estimated_time": 15
}
```

#### 결과 조회 API
```python
# GET /api/v1/search/{task_id}

# Response (진행 중)
{
    "task_id": "a1b2c3d4...",
    "status": "processing",
    "progress": 60,
    "current_step": "Generating answer from 10 documents"
}

# Response (완료)
{
    "task_id": "a1b2c3d4...",
    "status": "completed",
    "result": {
        "answer": "Docker는...",
        "sources": [...],
        "debug": {...}
    },
    "execution_time": 18.5
}
```

#### 피드백 API
```python
# POST /api/v1/feedback
{
    "session_id": "9acf5035...",
    "satisfaction": 5,
    "is_relevant": true,
    "comment": "매우 만족"
}

# Response
{
    "success": true,
    "message": "Feedback saved"
}
```

#### 통계 API
```python
# GET /api/v1/stats

# Response
{
    "total_searches": 1250,
    "feedback_count": 380,
    "avg_satisfaction": 4.2,
    "feedback_rate": 30.4,
    "daily_searches": 45
}
```

#### WebSocket (실시간 진행 상황)
```python
# WebSocket /ws/search/{task_id}

# 실시간 메시지
{
    "type": "progress",
    "step": "Searching in Qdrant",
    "progress": 30
}

{
    "type": "progress",
    "step": "Found 15 documents",
    "progress": 60
}

{
    "type": "complete",
    "result": {...}
}
```

### 2. 디렉토리 구조

```
r-agent-api/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI 앱 진입점
│   ├── config.py                  # 설정
│   ├── dependencies.py            # 의존성 주입
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── v1/
│   │   │   ├── __init__.py
│   │   │   ├── endpoints/
│   │   │   │   ├── search.py      # 검색 엔드포인트
│   │   │   │   ├── feedback.py    # 피드백 엔드포인트
│   │   │   │   ├── stats.py       # 통계 엔드포인트
│   │   │   │   └── websocket.py   # WebSocket 엔드포인트
│   │   │   └── router.py          # API 라우터
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── request.py             # Request 모델
│   │   ├── response.py            # Response 모델
│   │   └── task.py                # Task 모델
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── search_service.py      # 검색 서비스
│   │   ├── feedback_service.py    # 피드백 서비스
│   │   └── stats_service.py       # 통계 서비스
│   │
│   ├── workers/
│   │   ├── __init__.py
│   │   ├── celery_app.py          # Celery 설정
│   │   └── search_worker.py       # SearchAgent 워커
│   │
│   └── core/
│       ├── __init__.py
│       ├── cache.py               # Redis 캐시
│       ├── monitoring.py          # 모니터링
│       └── security.py            # 인증/인가
│
├── agents/                         # 기존 SearchAgent (재사용)
├── repositories/                   # 기존 Repository (재사용)
├── tools/                          # 기존 Tools (재사용)
├── tests/
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

### 3. 핵심 코드 예시

#### FastAPI 메인 앱
```python
# app/main.py

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import api_router
from app.core.monitoring import setup_monitoring

app = FastAPI(
    title="R-Agent API",
    description="RAG-based Search Agent API",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 모니터링 설정
setup_monitoring(app)

# API 라우터
app.include_router(api_router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "1.0.0"
    }
```

#### 검색 엔드포인트
```python
# app/api/v1/endpoints/search.py

from fastapi import APIRouter, HTTPException
from app.models.request import SearchRequest
from app.models.response import SearchResponse, TaskStatusResponse
from app.workers.celery_app import celery_app
from celery.result import AsyncResult

router = APIRouter()

@router.post("/search", response_model=SearchResponse)
async def create_search_task(request: SearchRequest):
    """검색 작업 생성 (비동기)"""

    # Celery 작업 큐에 추가
    task = celery_app.send_task(
        "search_agent.search",
        kwargs={
            "question": request.question,
            "user_id": request.user_id,
            "max_iterations": request.max_iterations,
            "debug": request.debug
        }
    )

    return SearchResponse(
        task_id=task.id,
        status="pending",
        estimated_time=15
    )


@router.get("/search/{task_id}", response_model=TaskStatusResponse)
async def get_search_status(task_id: str):
    """검색 작업 상태 조회"""

    task = AsyncResult(task_id, app=celery_app)

    if task.state == "PENDING":
        return TaskStatusResponse(
            task_id=task_id,
            status="pending",
            progress=0
        )

    elif task.state == "PROGRESS":
        return TaskStatusResponse(
            task_id=task_id,
            status="processing",
            progress=task.info.get("progress", 0),
            current_step=task.info.get("step", "")
        )

    elif task.state == "SUCCESS":
        return TaskStatusResponse(
            task_id=task_id,
            status="completed",
            result=task.result,
            execution_time=task.info.get("execution_time")
        )

    elif task.state == "FAILURE":
        raise HTTPException(
            status_code=500,
            detail=f"Task failed: {str(task.info)}"
        )

    return TaskStatusResponse(
        task_id=task_id,
        status=task.state.lower()
    )
```

#### Celery Worker
```python
# app/workers/search_worker.py

from celery import Task
from app.workers.celery_app import celery_app
from agents.search_agent import SearchAgent

class SearchTask(Task):
    """SearchAgent 작업 클래스"""

    _agent = None

    @property
    def agent(self):
        """워커 프로세스당 1개의 SearchAgent 인스턴스 재사용"""
        if self._agent is None:
            self._agent = SearchAgent()
        return self._agent


@celery_app.task(base=SearchTask, bind=True)
def search(self, question: str, user_id: str = None,
           max_iterations: int = 5, debug: bool = False):
    """검색 작업 실행"""

    # 진행 상황 업데이트
    self.update_state(
        state="PROGRESS",
        meta={"progress": 10, "step": "Initializing search"}
    )

    try:
        # SearchAgent 실행
        result = self.agent.search(
            question=question,
            max_iterations=max_iterations,
            debug=debug
        )

        # 진행 상황 업데이트
        self.update_state(
            state="PROGRESS",
            meta={"progress": 100, "step": "Completed"}
        )

        return result

    except Exception as e:
        # 에러 처리
        self.update_state(
            state="FAILURE",
            meta={"error": str(e)}
        )
        raise
```

#### WebSocket 실시간 진행 상황
```python
# app/api/v1/endpoints/websocket.py

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from celery.result import AsyncResult
import asyncio

router = APIRouter()

@router.websocket("/ws/search/{task_id}")
async def websocket_search_progress(websocket: WebSocket, task_id: str):
    """검색 진행 상황 실시간 스트리밍"""

    await websocket.accept()

    try:
        task = AsyncResult(task_id, app=celery_app)

        while True:
            if task.state == "PENDING":
                await websocket.send_json({
                    "type": "progress",
                    "step": "Queued",
                    "progress": 0
                })

            elif task.state == "PROGRESS":
                await websocket.send_json({
                    "type": "progress",
                    "step": task.info.get("step", "Processing"),
                    "progress": task.info.get("progress", 0)
                })

            elif task.state == "SUCCESS":
                await websocket.send_json({
                    "type": "complete",
                    "result": task.result
                })
                break

            elif task.state == "FAILURE":
                await websocket.send_json({
                    "type": "error",
                    "error": str(task.info)
                })
                break

            await asyncio.sleep(0.5)  # 0.5초마다 업데이트

    except WebSocketDisconnect:
        pass
```

## 🔄 마이그레이션 전략

### Phase 1: 기반 구축 (1-2주)
- [ ] FastAPI 프로젝트 구조 생성
- [ ] Celery + Redis 설정
- [ ] SearchAgent 워커 통합
- [ ] 기본 API 엔드포인트 구현

### Phase 2: 기능 이식 (2-3주)
- [ ] 검색 API 구현
- [ ] 피드백 API 구현
- [ ] 통계 API 구현
- [ ] WebSocket 실시간 진행 상황

### Phase 3: 프론트엔드 개발 (3-4주)
- [ ] React/Vue 웹 프론트엔드
- [ ] API 통신 계층
- [ ] 실시간 진행 상황 UI
- [ ] 피드백 UI

### Phase 4: 배포 및 모니터링 (1-2주)
- [ ] Docker 컨테이너화
- [ ] Kubernetes 배포
- [ ] 모니터링 (Prometheus, Grafana)
- [ ] 로깅 (ELK Stack)

### Phase 5: 전환 (1주)
- [ ] 병렬 운영 (Streamlit + FastAPI)
- [ ] 트래픽 점진적 이동
- [ ] Streamlit 서비스 종료

## 📊 성능 비교

### Streamlit (현재)
```
동시 사용자: 1-3명
응답 시간: 10-30초 (블로킹)
확장성: 수직 확장만 가능
비용: 낮음 (단일 서버)
```

### FastAPI (목표)
```
동시 사용자: 100+ 명
응답 시간: 10-30초 (비블로킹)
확장성: 수평 확장 가능
비용: 중간 (다중 서버 + Redis)
```

## 🛠️ 필요한 추가 기술 스택

### 새로 추가될 기술
1. **FastAPI**: REST API 프레임워크
2. **Celery**: 비동기 작업 큐
3. **Redis**: 메시지 브로커 + 캐시
4. **Nginx**: 로드 밸런서
5. **Docker/Kubernetes**: 컨테이너 오케스트레이션

### 유지되는 기술
1. **SearchAgent**: 기존 코드 재사용
2. **MySQL**: 기존 DB 유지
3. **Qdrant**: 기존 벡터 DB 유지
4. **Elasticsearch**: 기존 검색 엔진 유지

## 💰 비용 추정

### Streamlit (현재)
```
서버: 1대 (4 core, 16GB RAM)
월 비용: ~$50-100
```

### FastAPI (상용화)
```
API 서버: 2대 (4 core, 8GB RAM) = $100-200
Worker: 3대 (8 core, 16GB RAM) = $300-600
Redis: 1대 (2 core, 4GB RAM) = $50-100
Load Balancer: $20-50
----------------------------------------------
월 비용: ~$470-950
```

## ⚠️ 마이그레이션 시 주의사항

1. **SearchAgent 상태 관리**:
   - Streamlit: 세션별 인스턴스
   - FastAPI: 워커별 인스턴스 (재사용)
   - 주의: 상태 공유 방지

2. **데이터베이스 연결**:
   - 연결 풀 관리 필수
   - 워커별 독립적인 커넥션

3. **긴 작업 타임아웃**:
   - Celery 타임아웃 설정 (60초+)
   - HTTP 타임아웃 vs 작업 타임아웃 분리

4. **에러 처리**:
   - 작업 실패 시 재시도 로직
   - Dead Letter Queue 관리

## 🎯 우선순위

### 지금 당장 (Streamlit 유지)
- ✅ 피드백 수집 (200-1,000회)
- ✅ 데이터 분석 및 개선
- ✅ use_learning 활성화 검증

### 3-6개월 후 (FastAPI 전환 검토)
- 동시 사용자 수 > 10명
- 응답 속도 개선 필요
- 다양한 클라이언트 지원 필요

### 상용화 시 (FastAPI 필수)
- 외부 고객 서비스
- SLA 보장 필요
- 확장성 및 안정성 중요

## 📝 결론

**현재**: Streamlit은 프로토타입과 피드백 수집에 최적
**향후**: FastAPI는 상용화와 확장성에 필수

**권장 타임라인**:
1. 지금: Streamlit으로 피드백 1,000회 수집
2. 3개월 후: FastAPI 개발 시작
3. 6개월 후: 병렬 운영 후 전환
4. 9개월 후: 완전 전환 및 상용화

---

**작성일**: 2025-11-07
**현재 상태**: Streamlit 프로토타입 완성
**다음 단계**: 피드백 수집 → 6개월 후 FastAPI 전환 검토
