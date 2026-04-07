"""
R-Agent FastAPI Application
External API for integration with other systems.
"""

import asyncio
import uuid
import hmac
import hashlib
from datetime import datetime
from typing import Dict, Optional
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx

from api.schemas import (
    SearchRequest, SearchResponse, AsyncSearchResponse,
    TaskStatusResponse, FeedbackRequest, FeedbackResponse,
    HealthResponse, ErrorResponse, SearchStatus,
    DocumentSource, DebugInfo, ValidationInfo,
    WebhookRegistration, WebhookPayload, WebhookEventType
)
from api.chat_router import router as chat_router, close_db_pool, start_timeout_checker, stop_timeout_checker
from agents.async_search_agent import AsyncSearchAgent
from config.settings import settings
from utils.logger import logger


# ===========================================
# Global State
# ===========================================

# Async search agent (singleton)
_agent: Optional[AsyncSearchAgent] = None

# Task storage (in production, use Redis or database)
_tasks: Dict[str, Dict] = {}

# Webhook subscriptions
_webhooks: Dict[str, WebhookRegistration] = {}


# ===========================================
# Lifespan Management
# ===========================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    global _agent

    # Startup
    logger.info("🚀 Starting R-Agent API server...")
    _agent = AsyncSearchAgent()

    # Pre-initialize to warm up connections
    try:
        await _agent._initialize()
        logger.info("✅ R-Agent API ready")
    except Exception as e:
        logger.error(f"❌ Initialization failed: {e}")
        # Continue anyway - will retry on first request

    # Start session timeout checker
    await start_timeout_checker()

    yield

    # Shutdown
    logger.info("🛑 Shutting down R-Agent API...")
    await stop_timeout_checker()  # Stop timeout checker
    if _agent:
        await _agent.close()
    await close_db_pool()  # Close chat DB pool
    logger.info("👋 R-Agent API shutdown complete")


# ===========================================
# FastAPI App
# ===========================================

app = FastAPI(
    title="R-Agent API",
    description="""
## R-Agent RAG Search API

AI-powered document search API for enterprise integration.

### Features
- **Asynchronous Search**: Submit search request and receive results via webhook
- **Webhook Callbacks**: Receive results via callback URL when search completes
- **Status Polling**: Check search progress via status endpoint
- **Session Context**: Multi-turn conversation support
- **Feedback Loop**: Improve answers with user feedback

### Workflow
1. Submit search request to `/api/v1/search` with `callback_url`
2. Receive `task_id` immediately
3. Search runs in background
4. Results delivered via webhook to `callback_url`
5. Or poll `/api/v1/search/status/{task_id}` for status

### Authentication
API Key authentication via `X-API-Key` header (configurable).

### Rate Limits
- 100 requests/minute per API key
- 10 concurrent searches per session
    """,
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include chat router
app.include_router(chat_router)

# Mount static files for customer chat UI
STATIC_DIR = Path(__file__).parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    logger.info(f"📁 Static files mounted from: {STATIC_DIR}")


# ===========================================
# Dependencies
# ===========================================

async def get_agent() -> AsyncSearchAgent:
    """Dependency to get the search agent."""
    global _agent
    if _agent is None:
        _agent = AsyncSearchAgent()
    return _agent


async def verify_api_key(x_api_key: Optional[str] = Header(None)) -> str:
    """Verify API key (optional, configurable)."""
    # TODO: Implement actual API key verification
    # For now, just return a default value
    return x_api_key or "default"


# ===========================================
# Exception Handlers
# ===========================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=f"HTTP_{exc.status_code}",
            message=exc.detail,
            timestamp=datetime.utcnow()
        ).model_dump(mode='json')
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="INTERNAL_ERROR",
            message="An internal error occurred",
            detail=str(exc) if settings.LOG_LEVEL == "DEBUG" else None,
            timestamp=datetime.utcnow()
        ).model_dump(mode='json')
    )


# ===========================================
# Health & Status Endpoints
# ===========================================

@app.get("/", tags=["Status"])
async def root():
    """Root endpoint."""
    return {
        "service": "R-Agent API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs"
    }


@app.get("/health", response_model=HealthResponse, tags=["Status"])
async def health_check(agent: AsyncSearchAgent = Depends(get_agent)):
    """
    Health check endpoint.

    Returns status of all components:
    - Database connection
    - Vector database connection
    - Elasticsearch connection
    - OpenAI API availability
    """
    try:
        health = await agent.health_check()

        # Check OpenAI (simple ping)
        try:
            # Just check if client is configured
            openai_ok = bool(settings.OPENAI_API_KEY)
        except Exception:
            openai_ok = False

        components = {
            "database": health.get("database", False),
            "vector_db": health.get("vector_db", False),
            "elasticsearch": health.get("elasticsearch", False),
            "openai": openai_ok
        }

        status = "healthy" if all(components.values()) else "unhealthy"

        return HealthResponse(
            status=status,
            version="1.0.0",
            components=components,
            timestamp=datetime.utcnow()
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthResponse(
            status="unhealthy",
            version="1.0.0",
            components={
                "database": False,
                "vector_db": False,
                "elasticsearch": False,
                "openai": False
            },
            timestamp=datetime.utcnow()
        )


# ===========================================
# Search Endpoints
# ===========================================

@app.post("/api/v1/search", response_model=AsyncSearchResponse, tags=["Search"])
async def search(
    request: SearchRequest,
    background_tasks: BackgroundTasks,
    agent: AsyncSearchAgent = Depends(get_agent),
    api_key: str = Depends(verify_api_key)
):
    """
    Asynchronous search endpoint.

    Submits search request and returns immediately with task ID.
    Results are delivered via webhook to `callback_url` when search completes.

    **Workflow:**
    1. Submit request with `callback_url` (required for production use)
    2. Receive `task_id` immediately
    3. Search runs in background
    4. Results delivered via webhook to `callback_url`
    5. Or poll `/api/v1/search/status/{task_id}` for status

    **Webhook Payload:**
    ```json
    {
        "event": "search.completed",
        "task_id": "task-xxx",
        "session_id": "session-xxx",
        "timestamp": "2024-01-15T10:30:00Z",
        "data": {
            "success": true,
            "answer": "...",
            "confidence": 0.85,
            "sources": [...]
        }
    }
    ```
    """
    task_id = f"task-{uuid.uuid4().hex[:12]}"
    session_id = request.session_id or str(uuid.uuid4())

    # Store task
    _tasks[task_id] = {
        "status": SearchStatus.PENDING,
        "session_id": session_id,
        "request": request,
        "result": None,
        "error": None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    # Schedule background task
    background_tasks.add_task(
        _execute_async_search,
        task_id=task_id,
        request=request,
        agent=agent
    )

    logger.info(f"📥 Async search submitted: {task_id}")

    return AsyncSearchResponse(
        task_id=task_id,
        status=SearchStatus.PROCESSING,
        session_id=session_id,
        message="Search request accepted and processing",
        estimated_time=15
    )


@app.get("/api/v1/search/status/{task_id}", response_model=TaskStatusResponse, tags=["Search"])
async def get_search_status(task_id: str):
    """
    Get status of async search task.

    Returns current status and result if completed.
    """
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    task = _tasks[task_id]

    return TaskStatusResponse(
        task_id=task_id,
        status=task["status"],
        progress=_calculate_progress(task),
        result=task.get("result"),
        error=task.get("error"),
        created_at=task["created_at"],
        updated_at=task["updated_at"]
    )


# ===========================================
# Feedback Endpoint
# ===========================================

@app.post("/api/v1/feedback", response_model=FeedbackResponse, tags=["Feedback"])
async def submit_feedback(
    request: FeedbackRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    Submit feedback on search result quality.

    Feedback is used to improve the search system over time.
    """
    try:
        # Save feedback to database (like direct mode)
        from repositories.session_context_repository import SessionContextRepository
        repo = SessionContextRepository()

        saved = repo.update_satisfaction(
            session_id=request.session_id,
            satisfaction=request.satisfaction,
            is_relevant=request.is_relevant,
            comment=request.comment
        )

        if saved:
            logger.info(
                f"📝 Feedback saved: session={request.session_id}, "
                f"satisfaction={request.satisfaction}, relevant={request.is_relevant}"
            )
            return FeedbackResponse(
                success=True,
                message="Feedback recorded successfully",
                session_id=request.session_id
            )
        else:
            logger.warning(f"⚠️ Feedback not saved (session not found): {request.session_id}")
            return FeedbackResponse(
                success=False,
                message="Session not found",
                session_id=request.session_id
            )

    except Exception as e:
        logger.error(f"Feedback submission failed: {e}")
        raise HTTPException(status_code=500, detail=f"Feedback submission failed: {str(e)}")


# ===========================================
# Webhook Management
# ===========================================

@app.post("/api/v1/webhooks", tags=["Webhooks"])
async def register_webhook(
    registration: WebhookRegistration,
    api_key: str = Depends(verify_api_key)
):
    """
    Register a webhook endpoint for async search notifications.

    Webhooks will receive POST requests with search results.
    """
    webhook_id = f"wh-{uuid.uuid4().hex[:8]}"
    _webhooks[webhook_id] = registration

    logger.info(f"🔗 Webhook registered: {webhook_id} -> {registration.url}")

    return {
        "webhook_id": webhook_id,
        "url": registration.url,
        "events": registration.events,
        "message": "Webhook registered successfully"
    }


@app.delete("/api/v1/webhooks/{webhook_id}", tags=["Webhooks"])
async def unregister_webhook(webhook_id: str, api_key: str = Depends(verify_api_key)):
    """Unregister a webhook."""
    if webhook_id not in _webhooks:
        raise HTTPException(status_code=404, detail=f"Webhook not found: {webhook_id}")

    del _webhooks[webhook_id]
    logger.info(f"🔗 Webhook unregistered: {webhook_id}")

    return {"message": "Webhook unregistered successfully"}


# ===========================================
# Helper Functions
# ===========================================

async def _execute_async_search(
    task_id: str,
    request: SearchRequest,
    agent: AsyncSearchAgent
):
    """Execute search in background and update task status."""
    try:
        _tasks[task_id]["status"] = SearchStatus.PROCESSING
        _tasks[task_id]["updated_at"] = datetime.utcnow()

        result = await agent.search(
            question=request.question,
            session_id=request.session_id,
            max_iterations=request.max_iterations,
            debug=request.debug
        )

        # Convert to response format
        sources = [
            DocumentSource(
                id=s.get('id'),
                text=s.get('text', '')[:500],
                score=s.get('score', 0),
                metadata=s.get('metadata', {}),
                source=s.get('source', 'unknown')
            )
            for s in result.get('sources', [])
        ]

        search_response = SearchResponse(
            success=True,
            answer=result['answer'],
            confidence=result.get('confidence', 0.5),
            sources=sources,
            session_id=result.get('session_id', request.session_id or str(uuid.uuid4())),
            metadata=request.metadata,
            timestamp=datetime.utcnow()
        )

        _tasks[task_id]["status"] = SearchStatus.COMPLETED
        _tasks[task_id]["result"] = search_response
        _tasks[task_id]["updated_at"] = datetime.utcnow()

        logger.info(f"✅ Async search completed: {task_id}")

        # Send webhook if callback_url provided
        if request.callback_url:
            await _send_webhook(
                url=request.callback_url,
                event=WebhookEventType.SEARCH_COMPLETED,
                task_id=task_id,
                session_id=search_response.session_id,
                data=search_response,
                metadata=request.metadata
            )

    except Exception as e:
        logger.error(f"❌ Async search failed: {task_id} - {e}", exc_info=True)
        _tasks[task_id]["status"] = SearchStatus.FAILED
        _tasks[task_id]["error"] = str(e)
        _tasks[task_id]["updated_at"] = datetime.utcnow()

        # Send failure webhook
        if request.callback_url:
            await _send_webhook(
                url=request.callback_url,
                event=WebhookEventType.SEARCH_FAILED,
                task_id=task_id,
                session_id=request.session_id or "",
                data=None,
                metadata={"error": str(e)}
            )


async def _send_webhook(
    url: str,
    event: WebhookEventType,
    task_id: str,
    session_id: str,
    data: Optional[SearchResponse],
    metadata: Optional[Dict] = None
):
    """Send webhook notification."""
    try:
        payload = {
            "event": event.value,
            "task_id": task_id,
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data.model_dump(mode='json') if data else None,
            "metadata": metadata
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)

            if response.status_code >= 400:
                logger.warning(f"Webhook failed: {url} - {response.status_code}")
            else:
                logger.info(f"📤 Webhook sent: {url} - {event.value}")

    except Exception as e:
        logger.error(f"Webhook error: {url} - {e}")


def _calculate_progress(task: Dict) -> int:
    """Calculate task progress percentage."""
    status = task.get("status")
    if status == SearchStatus.PENDING:
        return 0
    elif status == SearchStatus.PROCESSING:
        # Estimate based on time elapsed
        elapsed = (datetime.utcnow() - task["created_at"]).total_seconds()
        return min(int(elapsed / 15 * 100), 95)  # Max 95% until complete
    elif status == SearchStatus.COMPLETED:
        return 100
    else:
        return 0


# ===========================================
# Run Server
# ===========================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
        log_level="info"
    )
