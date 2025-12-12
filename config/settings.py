"""
Settings module for RAG Agent system.
Loads and validates all environment variables from .env file.
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load .env file
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    """Application settings loaded from environment variables."""

    # OpenAI API
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # Cohere API (for Reranking)
    COHERE_API_KEY: str = os.getenv("COHERE_API_KEY", "")

    # Database (Read-only access to existing system)
    DB_HOST: str = os.getenv("DB_HOST", "127.0.0.1")
    DB_USER: str = os.getenv("DB_USER", "rsup")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_NAME: str = os.getenv("DB_NAME", "dc_db")
    DB_PORT: int = int(os.getenv("DB_PORT", "9443"))

    # R-Agent Learning Database (Performance tracking and learning)
    LEARNING_DB_HOST: str = os.getenv("LEARNING_DB_HOST", "127.0.0.1")
    LEARNING_DB_USER: str = os.getenv("LEARNING_DB_USER", "rsup")
    LEARNING_DB_PASSWORD: str = os.getenv("LEARNING_DB_PASSWORD", "")
    LEARNING_DB_NAME: str = os.getenv("LEARNING_DB_NAME", "r_agent_db")
    LEARNING_DB_PORT: int = int(os.getenv("LEARNING_DB_PORT", "9443"))

    # Qdrant Vector Database
    QDRANT_HOST: str = os.getenv("QDRANT_HOST", "localhost")
    QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", "6333"))
    QDRANT_COLLECTION_NAME: str = os.getenv("QDRANT_COLLECTION_NAME", "rag_documents")
    QDRANT_IMAGE_COLLECTION_NAME: str = os.getenv("QDRANT_IMAGE_COLLECTION_NAME", "rag_images")

    # Elasticsearch (Read-only - existing system)
    ES_HOST: str = os.getenv("ES_HOST", "http://localhost:9200")
    ES_INDEX_NAME: str = os.getenv("ES_INDEX_NAME", "qa_documents")

    # Embedding Model (for query embeddings only)
    EMBEDDING_MODEL_NAME: str = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-m3")

    # LLM Settings
    MODEL_NAME: str = os.getenv("MODEL_NAME", "gpt-4o-mini")
    TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.1"))

    # Agent Settings
    MAX_ITERATIONS: int = int(os.getenv("MAX_ITERATIONS", "5"))
    MAX_DOCUMENTS: int = int(os.getenv("MAX_DOCUMENTS", "10"))

    # Server
    PORT: int = int(os.getenv("PORT", "8001"))
    HOST: str = os.getenv("HOST", "0.0.0.0")

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: str = os.getenv("LOG_DIR", "logs")

    # Tool Enable/Disable Settings
    # MariaDB Tools
    TOOL_MARIADB_ERROR_CODE: bool = os.getenv("TOOL_MARIADB_ERROR_CODE", "true").lower() == "true"
    TOOL_MARIADB_KEYWORD: bool = os.getenv("TOOL_MARIADB_KEYWORD", "true").lower() == "true"
    TOOL_MARIADB_LOGS: bool = os.getenv("TOOL_MARIADB_LOGS", "true").lower() == "true"
    TOOL_MARIADB_REDMINE: bool = os.getenv("TOOL_MARIADB_REDMINE", "true").lower() == "true"

    # Vector Search Tools
    TOOL_QDRANT_SEMANTIC: bool = os.getenv("TOOL_QDRANT_SEMANTIC", "true").lower() == "true"

    # Elasticsearch Tools
    TOOL_ES_BM25: bool = os.getenv("TOOL_ES_BM25", "true").lower() == "true"
    TOOL_ES_GET_DOCUMENT: bool = os.getenv("TOOL_ES_GET_DOCUMENT", "true").lower() == "true"

    def get_enabled_tools(self) -> dict:
        """Get dictionary of tool enable/disable status."""
        return {
            'search_mariadb_by_error_code': self.TOOL_MARIADB_ERROR_CODE,
            'search_mariadb_by_keyword': self.TOOL_MARIADB_KEYWORD,
            'search_recent_logs': self.TOOL_MARIADB_LOGS,
            'search_redmine': self.TOOL_MARIADB_REDMINE,
            'search_qdrant_semantic': self.TOOL_QDRANT_SEMANTIC,
            'search_elasticsearch_bm25': self.TOOL_ES_BM25,
            'get_document_by_id': self.TOOL_ES_GET_DOCUMENT,
        }

    def is_tool_enabled(self, tool_name: str) -> bool:
        """Check if a specific tool is enabled."""
        enabled_tools = self.get_enabled_tools()
        return enabled_tools.get(tool_name, True)  # Default to enabled if not found

    def validate(self) -> None:
        """Validate critical settings."""
        if not self.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required")

        if not self.DB_PASSWORD:
            raise ValueError("DB_PASSWORD is required")

        if not self.LEARNING_DB_PASSWORD:
            raise ValueError("LEARNING_DB_PASSWORD is required")

        # Qdrant connection will be validated at runtime when connecting
        if not self.QDRANT_HOST:
            raise ValueError("QDRANT_HOST is required")

        if not self.QDRANT_COLLECTION_NAME:
            raise ValueError("QDRANT_COLLECTION_NAME is required")

    def __repr__(self) -> str:
        """String representation (hide sensitive data)."""
        return (
            f"Settings("
            f"DB={self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}, "
            f"LearningDB={self.LEARNING_DB_HOST}:{self.LEARNING_DB_PORT}/{self.LEARNING_DB_NAME}, "
            f"Qdrant={self.QDRANT_HOST}:{self.QDRANT_PORT}/{self.QDRANT_COLLECTION_NAME}, "
            f"ES={self.ES_HOST}, "
            f"Model={self.MODEL_NAME}, "
            f"Port={self.PORT})"
        )


# Global settings instance
settings = Settings()

# Validate on import (fail fast)
try:
    settings.validate()
    print(f"✓ Settings loaded: {settings}")
except Exception as e:
    print(f"❌ Settings validation failed: {e}")
    raise
