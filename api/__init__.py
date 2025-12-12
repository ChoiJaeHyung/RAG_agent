"""
R-Agent API Package.
FastAPI-based external API for R-Agent RAG search service.
All searches are asynchronous with webhook callbacks.
"""

from api.main import app
from api.schemas import (
    SearchRequest, SearchResponse, AsyncSearchResponse,
    TaskStatusResponse, FeedbackRequest, FeedbackResponse,
    HealthResponse, ErrorResponse, SearchStatus,
    DocumentSource, DebugInfo, ValidationInfo,
    WebhookRegistration, WebhookPayload, WebhookEventType
)

__all__ = [
    'app',
    'SearchRequest', 'SearchResponse', 'AsyncSearchResponse',
    'TaskStatusResponse', 'FeedbackRequest', 'FeedbackResponse',
    'HealthResponse', 'ErrorResponse', 'SearchStatus',
    'DocumentSource', 'DebugInfo', 'ValidationInfo',
    'WebhookRegistration', 'WebhookPayload', 'WebhookEventType'
]
