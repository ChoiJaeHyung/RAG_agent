"""
Elasticsearch Tools for RAG Agent.
Provides BM25 keyword search and document retrieval.
"""

from typing import List, Dict, Optional
from repositories.es_repository import ElasticsearchRepository
from repositories.db_repository import DatabaseRepository
from agents.tools.tool_registry import tool_registry, create_parameter_schema
from config.settings import settings
from utils.logger import logger


class ElasticsearchTools:
    """Elasticsearch search tools for the agent."""

    def __init__(self, es_repo: ElasticsearchRepository, db_repo: DatabaseRepository):
        """
        Initialize Elasticsearch tools.

        Args:
            es_repo: Elasticsearch repository instance
            db_repo: Database repository for fallback document lookup
        """
        self.es_repo = es_repo
        self.db_repo = db_repo
        self._register_tools()

    def _register_tools(self) -> None:
        """Register all Elasticsearch tools with the registry (based on settings)."""
        registered_count = 0

        # Tool 4: search_elasticsearch_bm25
        if settings.TOOL_ES_BM25:
            tool_registry.register_tool(
                name="search_elasticsearch_bm25",
                function=self.search_bm25,
                description=(
                    "Perform BM25 keyword search using Elasticsearch. "
                    "Use this for keyword-focused searches with optional brand filtering. "
                    "Better than database LIKE search for: "
                    "1) Multiple keywords, 2) Fuzzy matching, 3) Ranked results. "
                    "Supports brand filters: rvs, rcmp, remotecall, remoteview,remotemeeting. "
                    "Returns documents ranked by BM25 relevance score."
                ),
                parameters=create_parameter_schema(
                    properties={
                        "query": {
                            "type": "string",
                            "description": "Search query for BM25 keyword matching"
                        },
                        "brand_filter": {
                            "type": "array",
                            "description": "Optional list of brands to filter (e.g., ['rvs', 'rcmp'])",
                            "items": {
                                "type": "string",
                                "enum": ["rvs", "remotecall", "rcmp", "remoteview", "remotemeeting","rcvp"]
                            }
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of top results to return (default: 10)",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 50
                        }
                    },
                    required=["query"]
                )
            )
            registered_count += 1
        else:
            logger.info("⏭️  Tool disabled: search_elasticsearch_bm25")

        # Tool 5: get_document_by_id
        if settings.TOOL_ES_GET_DOCUMENT:
            tool_registry.register_tool(
                name="get_document_by_id",
                function=self.get_document_by_id,
                description=(
                    "Get full document content by document ID. "
                    "Use this when you need complete details of a specific document "
                    "found in previous searches. Tries Elasticsearch first, "
                    "then falls back to database if not found. "
                    "Returns single document with full content."
                ),
                parameters=create_parameter_schema(
                    properties={
                        "doc_id": {
                            "type": "integer",
                            "description": "Document ID to retrieve"
                        }
                    },
                    required=["doc_id"]
                )
            )
            registered_count += 1
        else:
            logger.info("⏭️  Tool disabled: get_document_by_id")

        logger.info(f"✓ Elasticsearch tools registered: {registered_count}/2 tools")

    def search_bm25(
        self,
        query: str,
        brand_filter: Optional[List[str]] = None,
        top_k: int = 10
    ) -> List[Dict]:
        """
        Perform BM25 search using Elasticsearch.

        Args:
            query: Search query
            brand_filter: Optional brand filter list
            top_k: Number of results

        Returns:
            List of documents with BM25 scores
        """
        results = self.es_repo.search(query, brand_filter, top_k)

        # Results are already formatted by es_repo
        # Just add source identifier
        for result in results:
            result['source'] = 'elasticsearch_bm25'

        return results

    def get_document_by_id(self, doc_id: int) -> Optional[Dict]:
        """
        Get document by ID from Elasticsearch or database.

        Args:
            doc_id: Document ID

        Returns:
            Document dict or None if not found
        """
        # Try Elasticsearch first
        es_doc = self.es_repo.get_document_by_id(str(doc_id))

        if es_doc:
            es_doc['source'] = 'elasticsearch'
            return es_doc

        # Fallback to database
        db_doc = self.db_repo.get_document_by_id(doc_id)

        if db_doc:
            return {
                'id': db_doc.get('sentence_id'),
                'text': db_doc.get('sentence', ''),
                'metadata': {
                    'file_name': db_doc.get('file_name', ''),
                    'doc_id': db_doc.get('doc_id', ''),
                    'chunk_num': db_doc.get('chunk_num', 0)
                },
                'source': 'database'
            }

        logger.warning(f"Document not found: {doc_id}")
        return None
