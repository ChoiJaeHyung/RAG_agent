"""
Elasticsearch Repository for RAG Agent.
Provides BM25 keyword search with brand filtering.
"""

from typing import List, Dict, Optional
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ConnectionError, NotFoundError

from config.settings import settings
from utils.logger import logger


class ElasticsearchRepository:
    """Repository for Elasticsearch BM25 keyword search."""

    def __init__(self):
        """Initialize Elasticsearch client (read-only access)."""
        try:
            self.client = Elasticsearch([settings.ES_HOST])
            self.index_name = settings.ES_INDEX_NAME

            # Check connection
            if self.client.ping():
                logger.info(f"✓ Elasticsearch connected: {settings.ES_HOST}/{self.index_name}")
            else:
                logger.error(f"❌ Elasticsearch ping failed: {settings.ES_HOST}")
        except Exception as e:
            logger.error(f"❌ Elasticsearch initialization failed: {e}")
            raise

    def search(
        self,
        query: str,
        brand_filter: Optional[List[str]] = None,
        top_k: int = 10
    ) -> List[Dict]:
        """
        Perform BM25 keyword search with optional brand filtering.

        Args:
            query: Search query string
            brand_filter: Optional list of brands to filter (e.g., ["rvs", "rcmp"])
            top_k: Number of top results to return

        Returns:
            List of documents with BM25 scores

        Example result:
            [
                {
                    'id': 123,
                    'text': 'document content...',
                    'score': 8.5,
                    'metadata': {...},
                    'source': 'elasticsearch'
                }
            ]
        """
        try:
            # Build query
            es_query = {
                "query": {
                    "bool": {
                        "must": [
                            {
                                "match": {
                                    "text": {
                                        "query": query,
                                        "fuzziness": "AUTO"
                                    }
                                }
                            }
                        ]
                    }
                },
                "size": top_k
            }

            # Add brand filter if specified
            if brand_filter and len(brand_filter) > 0:
                # Normalize brands to lowercase (as per existing system)
                normalized_brands = [b.lower() for b in brand_filter]
                es_query["query"]["bool"]["filter"] = [
                    {"terms": {"brand": normalized_brands}}
                ]

            # Execute search
            response = self.client.search(
                index=self.index_name,
                body=es_query
            )

            # Format results
            results = []
            hits = response.get('hits', {}).get('hits', [])

            for hit in hits:
                source = hit.get('_source', {})
                doc = {
                    'id': source.get('id', hit.get('_id')),
                    'text': source.get('text', source.get('sentence', '')),
                    'score': hit.get('_score', 0.0),
                    'metadata': source.get('metadata', {}),
                    'source': 'elasticsearch'
                }

                # Add brand info if available
                if 'brand' in source:
                    doc['metadata']['brand'] = source['brand']

                results.append(doc)

            logger.info(f"🔍 ES search: '{query[:50]}...' (brands={brand_filter}) → {len(results)} documents")

            if len(results) == 0 and brand_filter:
                logger.warning(f"⚠️ BM25 filter returned 0 results (brands={brand_filter})")

            return results

        except NotFoundError:
            logger.error(f"❌ Index not found: {self.index_name}")
            return []
        except ConnectionError as e:
            logger.error(f"❌ Elasticsearch connection error: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ Elasticsearch search failed: {e}")
            return []

    def get_document_by_id(self, doc_id: str) -> Optional[Dict]:
        """
        Get document by Elasticsearch ID.

        Args:
            doc_id: Elasticsearch document ID

        Returns:
            Document dict or None if not found
        """
        try:
            response = self.client.get(
                index=self.index_name,
                id=doc_id
            )

            source = response.get('_source', {})
            doc = {
                'id': doc_id,
                'text': source.get('text', source.get('sentence', '')),
                'metadata': source.get('metadata', {}),
                'source': 'elasticsearch'
            }

            logger.debug(f"🔍 ES get by ID: {doc_id} → Found")
            return doc

        except NotFoundError:
            logger.debug(f"🔍 ES get by ID: {doc_id} → Not found")
            return None
        except Exception as e:
            logger.error(f"❌ ES get by ID failed: {e}")
            return None

    def is_connected(self) -> bool:
        """
        Check if Elasticsearch is connected.

        Returns:
            True if connected, False otherwise
        """
        try:
            return self.client.ping()
        except Exception:
            return False

    def get_statistics(self) -> Dict:
        """
        Get Elasticsearch index statistics.

        Returns:
            Dictionary with index info
        """
        try:
            stats = self.client.indices.stats(index=self.index_name)
            doc_count = stats['_all']['primaries']['docs']['count']

            return {
                "index": self.index_name,
                "documents": doc_count,
                "status": "connected"
            }
        except Exception as e:
            logger.error(f"Failed to get ES statistics: {e}")
            return {"status": "error", "error": str(e)}
