"""
Async Tools for RAG Agent.
Provides async wrapper functions for all tools.
"""

from typing import List, Dict, Optional, Any, Callable
import asyncio
from functools import wraps

from config.settings import settings
from utils.logger import logger


class AsyncToolRegistry:
    """Registry for async tool functions."""

    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._sync_tools: Dict[str, Callable] = {}

    def register_tool(
        self,
        name: str,
        function: Callable,
        description: str,
        parameters: Dict
    ):
        """Register an async tool."""
        self._tools[name] = {
            'function': function,
            'description': description,
            'parameters': parameters
        }

    def register_sync_tool(
        self,
        name: str,
        function: Callable,
        description: str,
        parameters: Dict
    ):
        """Register a sync tool (will be wrapped for async execution)."""
        self._sync_tools[name] = function
        self._tools[name] = {
            'function': function,
            'description': description,
            'parameters': parameters,
            'is_sync': True
        }

    async def execute_tool(self, name: str, args: Dict) -> Dict[str, Any]:
        """Execute a tool by name with given arguments."""
        if name not in self._tools:
            return {
                'success': False,
                'error': f'Tool not found: {name}',
                'result': None
            }

        tool_info = self._tools[name]
        func = tool_info['function']

        try:
            # Check if it's a sync function that needs wrapping
            if tool_info.get('is_sync', False):
                # Run sync function in executor
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, lambda: func(**args))
            elif asyncio.iscoroutinefunction(func):
                result = await func(**args)
            else:
                # Regular sync function
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, lambda: func(**args))

            return {
                'success': True,
                'result': result,
                'error': None
            }
        except Exception as e:
            logger.error(f"Async tool execution failed: {name} - {e}")
            return {
                'success': False,
                'error': str(e),
                'result': None
            }

    def get_tool_names(self) -> List[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def get_tool_definitions(self) -> List[Dict]:
        """Get OpenAI-compatible tool definitions."""
        definitions = []
        for name, info in self._tools.items():
            definitions.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": info['description'],
                    "parameters": info['parameters']
                }
            })
        return definitions


# Global async tool registry
async_tool_registry = AsyncToolRegistry()


class AsyncMariaDBTools:
    """Async MariaDB tools."""

    def __init__(self, db_repo):
        self.db_repo = db_repo
        self._register_tools()

    def _register_tools(self):
        """Register async MariaDB tools."""
        if settings.TOOL_MARIADB_ERROR_CODE:
            async_tool_registry.register_tool(
                name="search_mariadb_by_error_code",
                function=self.search_by_error_code,
                description="Search documents by error code in MariaDB.",
                parameters={
                    "type": "object",
                    "properties": {
                        "error_code": {
                            "type": "string",
                            "description": "Error code to search"
                        }
                    },
                    "required": ["error_code"]
                }
            )

        if settings.TOOL_MARIADB_KEYWORD:
            async_tool_registry.register_tool(
                name="search_mariadb_by_keyword",
                function=self.search_by_keyword,
                description="Search documents by keyword in MariaDB.",
                parameters={
                    "type": "object",
                    "properties": {
                        "keyword": {
                            "type": "string",
                            "description": "Keyword to search"
                        },
                        "brand": {
                            "type": "string",
                            "description": "Optional brand filter",
                            "enum": ["rvs", "rcmp", "rcall", "rvcp", "saas"]
                        }
                    },
                    "required": ["keyword"]
                }
            )

        if settings.TOOL_MARIADB_LOGS:
            async_tool_registry.register_tool(
                name="search_recent_logs",
                function=self.search_recent_logs,
                description="Search past Q&A logs.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum results",
                            "default": 5
                        }
                    },
                    "required": ["query"]
                }
            )

        if settings.TOOL_MARIADB_REDMINE:
            async_tool_registry.register_tool(
                name="search_redmine",
                function=self.search_redmine,
                description="Search redmine tables.",
                parameters={
                    "type": "object",
                    "properties": {
                        "keyword": {
                            "type": "string",
                            "description": "Search keyword"
                        }
                    },
                    "required": ["keyword"]
                }
            )

    async def search_by_error_code(self, error_code: str) -> List[Dict]:
        """Search by error code."""
        results = await self.db_repo.search_by_error_code(error_code)
        return self._format_results(results, 'mariadb_error_code')

    async def search_by_keyword(self, keyword: str, brand: Optional[str] = None) -> List[Dict]:
        """Search by keyword."""
        results = await self.db_repo.search_by_keyword(keyword, brand)
        return self._format_results(results, 'mariadb_keyword')

    async def search_recent_logs(self, query: str, limit: int = 5) -> List[Dict]:
        """Search recent logs."""
        results = await self.db_repo.search_recent_logs(query, limit)
        return self._format_results(results, 'mariadb_logs')

    async def search_redmine(self, keyword: str) -> List[Dict]:
        """Search redmine tables."""
        results = await self.db_repo.search_redmine_tables(keyword)
        return self._format_results(results, 'mariadb_redmine')

    def _format_results(self, results: List[Dict], source: str) -> List[Dict]:
        """Format results with source info."""
        formatted = []
        for r in results:
            formatted.append({
                'id': r.get('sentence_id') or r.get('issue_id') or r.get('journal_id'),
                'text': r.get('sentence') or r.get('subject') or r.get('notes') or str(r),
                'score': 0.5,  # Default score for DB results
                'metadata': {
                    'file_name': r.get('source_table', source),
                    'file_type': 'database'
                },
                'source': source
            })
        return formatted


class AsyncVectorTools:
    """Async vector search tools."""

    def __init__(self, vector_repo):
        self.vector_repo = vector_repo
        self._register_tools()

    def _register_tools(self):
        """Register async vector tools."""
        if settings.TOOL_QDRANT_SEMANTIC:
            async_tool_registry.register_tool(
                name="search_qdrant_semantic",
                function=self.search_semantic,
                description="Perform semantic search using Qdrant.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of results",
                            "default": 5
                        }
                    },
                    "required": ["query"]
                }
            )

    async def search_semantic(self, query: str, top_k: int = 5) -> List[Dict]:
        """Perform semantic search."""
        return await self.vector_repo.search(query, top_k)


class AsyncElasticsearchTools:
    """Async Elasticsearch tools."""

    def __init__(self, es_repo, db_repo):
        self.es_repo = es_repo
        self.db_repo = db_repo
        self._register_tools()

    def _register_tools(self):
        """Register async ES tools."""
        if settings.TOOL_ES_BM25:
            async_tool_registry.register_tool(
                name="search_elasticsearch_bm25",
                function=self.search_bm25,
                description="Perform BM25 keyword search.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query"
                        },
                        "brand_filter": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Brand filters"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of results",
                            "default": 10
                        }
                    },
                    "required": ["query"]
                }
            )

        if settings.TOOL_ES_GET_DOCUMENT:
            async_tool_registry.register_tool(
                name="get_document_by_id",
                function=self.get_document_by_id,
                description="Get document by ID.",
                parameters={
                    "type": "object",
                    "properties": {
                        "doc_id": {
                            "type": "integer",
                            "description": "Document ID"
                        }
                    },
                    "required": ["doc_id"]
                }
            )

    async def search_bm25(
        self,
        query: str,
        brand_filter: Optional[List[str]] = None,
        top_k: int = 10
    ) -> List[Dict]:
        """Perform BM25 search."""
        return await self.es_repo.search(query, brand_filter, top_k)

    async def get_document_by_id(self, doc_id: int) -> Optional[Dict]:
        """Get document by ID."""
        # Try ES first
        doc = await self.es_repo.get_document_by_id(str(doc_id))
        if doc:
            return doc

        # Fallback to DB
        doc = await self.db_repo.get_document_by_id(doc_id)
        if doc:
            return {
                'id': doc_id,
                'text': doc.get('sentence', ''),
                'metadata': {},
                'source': 'mariadb'
            }

        return None
