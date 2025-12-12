"""
MariaDB Tools for RAG Agent.
Provides database search tools (error code, keyword, logs).
"""

from typing import List, Dict, Optional
from repositories.db_repository import DatabaseRepository
from agents.tools.tool_registry import tool_registry, create_parameter_schema
from config.settings import settings
from utils.logger import logger
from utils.text_normalizer import generate_spacing_variants


class MariaDBTools:
    """MariaDB search tools for the agent."""

    def __init__(self, db_repo: DatabaseRepository):
        """
        Initialize MariaDB tools.

        Args:
            db_repo: Database repository instance
        """
        self.db_repo = db_repo
        self._register_tools()

    def _register_tools(self) -> None:
        """Register all MariaDB tools with the registry (based on settings)."""
        registered_count = 0

        # Tool 1: search_mariadb_by_error_code
        if settings.TOOL_MARIADB_ERROR_CODE:
            tool_registry.register_tool(
                name="search_mariadb_by_error_code",
                function=self.search_by_error_code,
                description=(
                    "Search documents by error code in MariaDB. "
                    "Use this when the question contains 4-5 digit error codes like '50001', '6789', '10234'. "
                    "This tool searches for the error code pattern in document text. "
                    "Returns list of matching documents from the database."
                ),
                parameters=create_parameter_schema(
                    properties={
                        "error_code": {
                            "type": "string",
                            "description": "Error code to search (e.g., '50001', '6789')"
                        }
                    },
                    required=["error_code"]
                )
            )
            registered_count += 1
        else:
            logger.info("⏭️  Tool disabled: search_mariadb_by_error_code")

        # Tool 2: search_mariadb_by_keyword
        if settings.TOOL_MARIADB_KEYWORD:
            tool_registry.register_tool(
                name="search_mariadb_by_keyword",
                function=self.search_by_keyword,
                description=(
                    "Search documents by keyword using SQL LIKE in MariaDB. "
                    "Use this for exact keyword matching when you need specific terms. "
                    "Supports optional brand filtering (rvs, rcmp, rcall, rvcp, saas). "
                    "Returns list of documents containing the keyword."
                ),
                parameters=create_parameter_schema(
                    properties={
                        "keyword": {
                            "type": "string",
                            "description": "Keyword to search (e.g., '설치', '오류', '연결')"
                        },
                        "brand": {
                            "type": "string",
                            "description": "Optional brand filter (e.g., 'rvs', 'rcmp', 'rcall')",
                            "enum": ["rvs", "rcmp", "rcall", "rvcp", "saas"]
                        }
                    },
                    required=["keyword"]
                )
            )
            registered_count += 1
        else:
            logger.info("⏭️  Tool disabled: search_mariadb_by_keyword")

        # Tool 6: search_recent_logs
        if settings.TOOL_MARIADB_LOGS:
            tool_registry.register_tool(
                name="search_recent_logs",
                function=self.search_recent_logs,
                description=(
                    "Search past Q&A logs in MariaDB to find similar questions. "
                    "Use this to learn from previous successful answers. "
                    "Helpful for questions like 'similar to previous', 'before', 'past cases'. "
                    "Returns recent Q&A entries sorted by timestamp."
                ),
                parameters=create_parameter_schema(
                    properties={
                        "query": {
                            "type": "string",
                            "description": "Search query to find similar past questions"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of past Q&As to return (default: 5)",
                            "default": 5,
                            "minimum": 1,
                            "maximum": 20
                        }
                    },
                    required=["query"]
                )
            )
            registered_count += 1
        else:
            logger.info("⏭️  Tool disabled: search_recent_logs")

        # Tool 7: search_redmine
        if settings.TOOL_MARIADB_REDMINE:
            tool_registry.register_tool(
                name="search_redmine",
                function=self.search_redmine,
                description=(
                    "Search redmine-specific tables in MariaDB. "
                    "Use this when the question contains '레드마인' or 'redmine' keywords. "
                    "Searches across redmine_issues, redmine_journals, redmine_relations, redmine_sync_log tables. "
                    "Returns all matching redmine documents."
                ),
                parameters=create_parameter_schema(
                    properties={
                        "keyword": {
                            "type": "string",
                            "description": "Search keyword for redmine tables"
                        }
                    },
                    required=["keyword"]
                )
            )
            registered_count += 1
        else:
            logger.info("⏭️  Tool disabled: search_redmine")

        logger.info(f"✓ MariaDB tools registered: {registered_count}/4 tools")

    def search_by_error_code(self, error_code: str) -> List[Dict]:
        """
        Search documents by error code.

        Args:
            error_code: Error code string (e.g., "50001")

        Returns:
            List of matching documents
        """
        results = self.db_repo.search_by_error_code(error_code)

        # Format results for agent
        formatted_results = []
        for doc in results:
            formatted_results.append({
                'id': doc.get('sentence_id'),
                'text': doc.get('sentence', '')[:500],  # Limit text length
                'score': 1.0,  # Exact match
                'metadata': {
                    'file_name': doc.get('file_name', ''),
                    'doc_id': doc.get('doc_id', ''),
                    'chunk_num': doc.get('chunk_num', 0)
                },
                'source': 'mariadb_error_code'
            })

        return formatted_results

    def search_by_keyword(self, keyword: str, brand: Optional[str] = None) -> List[Dict]:
        """
        Search documents by keyword with optional brand filter.
        Handles spacing variations automatically.

        Args:
            keyword: Search keyword
            brand: Optional brand filter

        Returns:
            List of matching documents
        """
        # Generate spacing variants to handle both "픽코 파트너스" and "픽코파트너스"
        variants = generate_spacing_variants(keyword)
        logger.info(f"🔍 Searching with variants: {variants}")

        # Search with all variants and combine results
        all_results = []
        seen_ids = set()

        for variant in variants:
            results = self.db_repo.search_by_keyword(variant, brand)

            # Deduplicate by sentence_id
            for doc in results:
                sentence_id = doc.get('sentence_id')
                if sentence_id not in seen_ids:
                    seen_ids.add(sentence_id)
                    all_results.append(doc)

        logger.info(f"✅ Found {len(all_results)} unique documents across all variants")
        results = all_results

        # Format results for agent
        formatted_results = []
        for doc in results:
            formatted_results.append({
                'id': doc.get('sentence_id'),
                'text': doc.get('sentence', '')[:500],  # Limit text length
                'score': 0.9,  # High relevance for keyword match
                'metadata': {
                    'file_name': doc.get('file_name', ''),
                    'doc_id': doc.get('doc_id', ''),
                    'chunk_num': doc.get('chunk_num', 0),
                    'brand': brand or 'unknown'
                },
                'source': 'mariadb_keyword'
            })

        return formatted_results

    def search_recent_logs(self, query: str, limit: int = 5) -> List[Dict]:
        """
        Search recent Q&A logs.

        Args:
            query: Search query
            limit: Maximum number of results

        Returns:
            List of past Q&A entries
        """
        results = self.db_repo.search_recent_logs(query, limit)

        # Format results for agent
        formatted_results = []
        for log in results:
            formatted_results.append({
                'id': log.get('qa_id'),
                'question': log.get('user_question', ''),
                'answer': log.get('ai_answer', '')[:300],  # Limit answer length
                'created_at': str(log.get('created_at', '')),
                'metadata': {
                    'user_id': log.get('user_id', ''),
                    'session_id': log.get('session_id', ''),
                    'score': log.get('score', 0.0),
                    'is_relevant': log.get('is_relevant', False)
                },
                'source': 'qa_logs'
            })

        return formatted_results

    def search_redmine(self, keyword: str) -> List[Dict]:
        """
        Search redmine-specific tables.

        Args:
            keyword: Search keyword

        Returns:
            List of matching redmine documents
        """
        results = self.db_repo.search_redmine_tables(keyword)

        # Format results for agent
        formatted_results = []
        for doc in results:
            source_table = doc.get('source_table', 'unknown')

            # Extract text and ID based on source table
            if source_table == 'redmine_issues':
                text = f"{doc.get('subject', '')} | {doc.get('description', '')}"
                doc_id = doc.get('issue_id', 0)
            elif source_table == 'redmine_journals':
                text = doc.get('notes', '')
                doc_id = doc.get('journal_id', 0)
            elif source_table == 'redmine_relations':
                text = f"Relation: {doc.get('issue_from', '')} → {doc.get('issue_to', '')}"
                doc_id = doc.get('relation_id', 0)
            elif source_table == 'redmine_sync_log':
                status = doc.get('status', '')
                error_msg = doc.get('error_message', '')
                text = f"Status: {status} | Error: {error_msg}" if error_msg else f"Status: {status}"
                doc_id = doc.get('sync_id', 0)
            else:
                text = str(doc)
                doc_id = 0

            formatted_results.append({
                'id': doc_id,
                'text': text[:500],  # Limit text length
                'score': 1.0,  # Exact match
                'metadata': {
                    'source_table': source_table,
                    'raw_data': {k: v for k, v in doc.items() if k != 'source_table'}
                },
                'source': 'mariadb_redmine'
            })

        return formatted_results
