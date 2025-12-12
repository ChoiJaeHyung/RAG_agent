"""
Qdrant Vector Tools for RAG Agent.
Provides semantic search using Qdrant vector similarity.
"""

from typing import List, Dict
from repositories.vector_repository import VectorRepository
from agents.tools.tool_registry import tool_registry, create_parameter_schema
from config.settings import settings
from utils.logger import logger
from utils.text_normalizer import generate_spacing_variants


class VectorTools:
    """Qdrant vector search tools for the agent."""

    def __init__(self, vector_repo: VectorRepository):
        """
        Initialize vector tools.

        Args:
            vector_repo: Vector repository instance
        """
        self.vector_repo = vector_repo
        self._register_tools()

    def _register_tools(self) -> None:
        """Register all vector search tools with the registry (based on settings)."""
        registered_count = 0

        # Tool 3: search_qdrant_semantic
        if settings.TOOL_QDRANT_SEMANTIC:
            tool_registry.register_tool(
                name="search_qdrant_semantic",
                function=self.search_semantic,
                description=(
                    "Perform semantic search using Qdrant vector similarity. "
                    "Use this for meaning-based searches when the question asks about concepts, "
                    "methods, or procedures (e.g., 'how to', 'what is', 'explain'). "
                    "This tool understands the semantic meaning beyond exact keywords. "
                    "Best for: '어떻게', '방법', '설명', '이란', '개념' type questions. "
                    "Returns documents ranked by semantic similarity score."
                ),
                parameters=create_parameter_schema(
                    properties={
                        "query": {
                            "type": "string",
                            "description": "Search query describing what to find semantically"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of top results to return (default: 5)",
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
            logger.info("⏭️  Tool disabled: search_qdrant_semantic")

        logger.info(f"✓ Vector tools registered: {registered_count}/1 tools")

    def search_semantic(self, query: str, top_k: int = 5) -> List[Dict]:
        """
        Perform semantic search using Qdrant.
        Tries multiple spacing variants to maximize recall.

        Args:
            query: Search query
            top_k: Number of top results

        Returns:
            List of documents with similarity scores
        """
        # Generate spacing variants
        variants = generate_spacing_variants(query)
        logger.info(f"🔍 Vector search with variants: {variants}")

        # Search with all variants and combine results
        all_results = []
        seen_ids = set()

        for variant in variants:
            results = self.vector_repo.search(variant, top_k)

            # Deduplicate by id
            for result in results:
                result_id = result.get('id')
                if result_id not in seen_ids:
                    seen_ids.add(result_id)
                    result['source'] = 'qdrant_semantic'
                    all_results.append(result)

        # Sort by score (highest first) and return top_k
        all_results.sort(key=lambda x: x.get('score', 0), reverse=True)
        final_results = all_results[:top_k]

        logger.info(f"✅ Vector search: {len(all_results)} total → {len(final_results)} returned")
        return final_results
