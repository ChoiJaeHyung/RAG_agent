"""
Qdrant Vector Repository for RAG Agent.
Connects to Qdrant vector database for semantic search.

Replaces FAISS implementation with Qdrant client.
"""

from typing import List, Dict, TYPE_CHECKING, Optional
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, SearchRequest
from sentence_transformers import SentenceTransformer

from config.settings import settings
from utils.logger import logger

if TYPE_CHECKING:
    from repositories.db_repository import DatabaseRepository


class VectorRepository:
    """Repository for Qdrant vector similarity search."""

    def __init__(self, db_repo: 'DatabaseRepository' = None):
        """
        Initialize Qdrant client and embedding model.
        Connects to existing Qdrant server.

        Args:
            db_repo: Database repository for fetching sentence text
        """
        self.db_repo = db_repo

        # Initialize Qdrant client
        try:
            self.client = QdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT
            )

            # Verify connection and collection exists
            collections = self.client.get_collections().collections
            collection_names = [c.name for c in collections]

            if settings.QDRANT_COLLECTION_NAME not in collection_names:
                logger.warning(
                    f"Collection '{settings.QDRANT_COLLECTION_NAME}' not found. "
                    f"Available collections: {collection_names}"
                )
            else:
                # Get collection info
                collection_info = self.client.get_collection(settings.QDRANT_COLLECTION_NAME)
                logger.info(
                    f"✓ Qdrant connected: {collection_info.points_count} vectors "
                    f"in collection '{settings.QDRANT_COLLECTION_NAME}'"
                )
        except Exception as e:
            logger.error(f"❌ Failed to connect to Qdrant: {e}")
            raise

        # Load embedding model for query embeddings
        try:
            self.model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
            logger.info(f"✓ Embedding model loaded: {settings.EMBEDDING_MODEL_NAME}")
        except Exception as e:
            logger.error(f"❌ Failed to load embedding model: {e}")
            raise

    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """
        Perform semantic search using Qdrant.

        Args:
            query: Search query string
            top_k: Number of top results to return

        Returns:
            List of documents with similarity scores

        Example result:
            [
                {
                    'id': 123,
                    'doc_id': 456,
                    'text': 'document content...',
                    'score': 0.95,
                    'metadata': {...},
                    'source': 'qdrant'
                }
            ]
        """
        try:
            # Generate query embedding
            query_embedding = self.model.encode([query], normalize_embeddings=True)
            query_vector = query_embedding[0].tolist()

            # Search in Qdrant
            search_results = self.client.search(
                collection_name=settings.QDRANT_COLLECTION_NAME,
                query_vector=query_vector,
                limit=top_k
            )

            # Format results
            results = []
            for hit in search_results:
                # Extract payload data
                payload = hit.payload or {}

                # Get sentence_id from payload
                sentence_id = payload.get('sentence_id', hit.id)

                # Fetch sentence text from DB if db_repo is available
                sentence_text = payload.get('sentence', '')
                if not sentence_text and self.db_repo:
                    try:
                        db_doc = self.db_repo.get_document_by_id(sentence_id)
                        if db_doc:
                            sentence_text = db_doc.get('sentence', '')
                    except Exception as e:
                        logger.warning(f"Failed to fetch sentence text for ID {sentence_id}: {e}")

                doc = {
                    'id': sentence_id,
                    'doc_id': payload.get('doc_id', sentence_id),
                    'text': sentence_text,
                    'score': float(hit.score),
                    'metadata': {
                        'file_name': payload.get('file_name', ''),
                        'file_type': payload.get('file_type', ''),
                        'chunk_num': payload.get('chunk_num', 0),
                        'pages': payload.get('pages', 0)
                    },
                    'source': 'qdrant'
                }

                results.append(doc)

            avg_score = (sum(r['score'] for r in results) / len(results)) if results else 0
            logger.info(
                f"🔍 Qdrant search: '{query[:50]}...' → {len(results)} documents "
                f"(avg score: {avg_score:.2f})"
            )
            return results

        except Exception as e:
            logger.error(f"Qdrant search failed: {e}")
            return []

    def get_vector_count(self) -> int:
        """
        Get total number of vectors in collection.

        Returns:
            Vector count
        """
        try:
            collection_info = self.client.get_collection(settings.QDRANT_COLLECTION_NAME)
            return collection_info.points_count
        except Exception as e:
            logger.error(f"Failed to get vector count: {e}")
            return 0

    def is_loaded(self) -> bool:
        """
        Check if Qdrant collection is accessible.

        Returns:
            True if accessible, False otherwise
        """
        try:
            collection_info = self.client.get_collection(settings.QDRANT_COLLECTION_NAME)
            return collection_info.points_count > 0
        except:
            return False
