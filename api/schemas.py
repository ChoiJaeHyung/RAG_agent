"""
API Schemas - Pydantic models for request/response validation.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from enum import Enum


# ===========================================
# Enums
# ===========================================

class SearchStatus(str, Enum):
    """Search request status."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class WebhookEventType(str, Enum):
    """Webhook event types."""
    SEARCH_COMPLETED = "search.completed"
    SEARCH_FAILED = "search.failed"


# ===========================================
# Request Schemas
# ===========================================

class SearchRequest(BaseModel):
    """Search request from external system."""
    question: str = Field(..., min_length=1, max_length=2000, description="User's question")
    session_id: Optional[str] = Field(None, description="Session ID for conversation context")
    max_iterations: Optional[int] = Field(None, ge=1, le=10, description="Max search iterations")
    debug: bool = Field(False, description="Include debug information in response")
    callback_url: Optional[str] = Field(None, description="Webhook URL for async callback")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Custom metadata to include in response")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "question": "RemoteCall 설치 방법을 알려주세요",
            "session_id": "user-123-session-456",
            "max_iterations": 5,
            "debug": False,
            "callback_url": "https://your-system.com/webhook/r-agent",
            "metadata": {"user_id": "user123", "ticket_id": "TICKET-001"}
        }
    })


class FeedbackRequest(BaseModel):
    """User feedback on answer quality."""
    session_id: str = Field(..., description="Session ID of the search")
    satisfaction: int = Field(..., ge=1, le=5, description="Satisfaction score 1-5")
    is_relevant: bool = Field(..., description="Whether the answer was relevant")
    comment: Optional[str] = Field(None, max_length=1000, description="Optional feedback comment")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "session_id": "abc123-def456",
            "satisfaction": 4,
            "is_relevant": True,
            "comment": "답변이 도움이 되었습니다"
        }
    })


class WebhookRegistration(BaseModel):
    """Webhook registration request."""
    url: str = Field(..., description="Webhook endpoint URL")
    events: List[WebhookEventType] = Field(..., description="Events to subscribe to")
    secret: Optional[str] = Field(None, description="Secret for webhook signature verification")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "url": "https://your-system.com/webhook",
            "events": ["search.completed", "search.failed"],
            "secret": "your-webhook-secret"
        }
    })


# ===========================================
# Response Schemas
# ===========================================

class DocumentSource(BaseModel):
    """Source document in search results."""
    id: Any = Field(..., description="Document ID")
    text: str = Field(..., description="Document content")
    score: float = Field(..., description="Relevance score")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Document metadata")
    source: str = Field(..., description="Source type (qdrant, elasticsearch, mariadb)")


class ValidationInfo(BaseModel):
    """Answer validation information."""
    relevance_score: float = Field(..., description="Relevance score 0-1")
    grounding_score: float = Field(..., description="Grounding score 0-1")
    completeness_score: float = Field(..., description="Completeness score 0-1")
    warnings: List[str] = Field(default_factory=list, description="Validation warnings")


class DebugInfo(BaseModel):
    """Debug information for troubleshooting."""
    iterations: int = Field(..., description="Number of iterations executed")
    tools_used: List[str] = Field(..., description="Tools used during search")
    thought_process: List[str] = Field(..., description="Agent thought process")
    total_documents: int = Field(..., description="Total documents found")
    execution_time: float = Field(..., description="Total execution time in seconds")
    validation: Optional[ValidationInfo] = Field(None, description="Answer validation")


class SearchResponse(BaseModel):
    """Synchronous search response."""
    success: bool = Field(..., description="Whether search was successful")
    answer: str = Field(..., description="Generated answer")
    confidence: float = Field(..., ge=0, le=1, description="Confidence score 0-1")
    sources: List[DocumentSource] = Field(default_factory=list, description="Source documents")
    session_id: str = Field(..., description="Session ID for follow-up")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Request metadata echoed back")
    debug: Optional[DebugInfo] = Field(None, description="Debug information if requested")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "success": True,
            "answer": "RemoteCall 설치 방법은 다음과 같습니다...",
            "confidence": 0.85,
            "sources": [
                {
                    "id": 123,
                    "text": "RemoteCall 설치 가이드...",
                    "score": 0.92,
                    "metadata": {"file_name": "install_guide.pdf"},
                    "source": "qdrant"
                }
            ],
            "session_id": "abc123-def456",
            "timestamp": "2024-01-15T10:30:00Z"
        }
    })


class AsyncSearchResponse(BaseModel):
    """Async search response - returned immediately."""
    task_id: str = Field(..., description="Task ID for status checking")
    status: SearchStatus = Field(..., description="Current task status")
    session_id: str = Field(..., description="Session ID")
    message: str = Field(..., description="Status message")
    estimated_time: Optional[int] = Field(None, description="Estimated completion time in seconds")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "task_id": "task-abc123",
            "status": "processing",
            "session_id": "session-xyz",
            "message": "Search request accepted and processing",
            "estimated_time": 10
        }
    })


class TaskStatusResponse(BaseModel):
    """Task status check response."""
    task_id: str
    status: SearchStatus
    progress: Optional[int] = Field(None, ge=0, le=100, description="Progress percentage")
    result: Optional[SearchResponse] = Field(None, description="Result if completed")
    error: Optional[str] = Field(None, description="Error message if failed")
    created_at: datetime
    updated_at: datetime


class FeedbackResponse(BaseModel):
    """Feedback submission response."""
    success: bool
    message: str
    session_id: str


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Overall status: healthy/unhealthy")
    version: str = Field(..., description="API version")
    components: Dict[str, bool] = Field(..., description="Component health status")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "status": "healthy",
            "version": "1.0.0",
            "components": {
                "database": True,
                "vector_db": True,
                "elasticsearch": True,
                "openai": True
            },
            "timestamp": "2024-01-15T10:30:00Z"
        }
    })


class ErrorResponse(BaseModel):
    """Error response."""
    success: bool = Field(False)
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Detailed error information")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class WebhookPayload(BaseModel):
    """Webhook callback payload."""
    event: WebhookEventType
    task_id: str
    session_id: str
    timestamp: datetime
    data: SearchResponse
    metadata: Optional[Dict[str, Any]] = None
