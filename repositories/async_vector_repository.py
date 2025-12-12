"""
Async Qdrant Vector Repository for RAG Agent.
Provides async semantic search using Qdrant vector database.
"""

import asyncio
from typing import List, Dict, Optional, TYPE_CHECKING
from qdrant_client import AsyncQdrantClient
from sentence_transformers import SentenceTransformer
from concurrent.futures import ThreadPoolExecutor

from config.settings import settings
from utils.logger import logger

if TYPE_CHECKING:
    from repositories.async_db_repository import AsyncDatabaseRepository


class AsyncVectorRepository:
    """Async repository for Qdrant vector similarity search."""

    def __init__(self, db_repo: 'AsyncDatabaseRepository' = None):
        """
        Initialize async Qdrant client and embedding model.

        Args:
            db_repo: Async database repository for fetching sentence text
        """
        self.db_repo = db_repo
        self._client: Optional[AsyncQdrantClient] = None
        self._model: Optional[SentenceTransformer] = None
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def _initialize(self):
        """Lazy initialization of client and model."""
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            # Initialize async Qdrant client
            try:
                self._client = AsyncQdrantClient(
                    host=settings.QDRANT_HOST,
                    port=settings.QDRANT_PORT
                )

                # Verify connection and collection exists
                collections = await self._client.get_collections()
                collection_names = [c.name for c in collections.collections]

                if settings.QDRANT_COLLECTION_NAME not in collection_names:
                    logger.warning(
                        f"Collection '{settings.QDRANT_COLLECTION_NAME}' not found. "
                        f"Available collections: {collection_names}"
                    )
                else:
                    collection_info = await self._client.get_collection(settings.QDRANT_COLLECTION_NAME)
                    logger.info(
                        f"✓ Async Qdrant connected: {collection_info.points_count} vectors "
                        f"in collection '{settings.QDRANT_COLLECTION_NAME}'"
                    )
            except Exception as e:
                logger.error(f"❌ Failed to connect to Qdrant: {e}")
                raise

            # Load embedding model (blocking operation, run in executor)
            try:
                loop = asyncio.get_event_loop()
                self._model = await loop.run_in_executor(
                    self._executor,
                    lambda: SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
                )
                logger.info(f"✓ Embedding model loaded: {settings.EMBEDDING_MODEL_NAME}")
            except Exception as e:
                logger.error(f"❌ Failed to load embedding model: {e}")
                raise

            self._initialized = True

    async def _encode_query(self, query: str) -> List[float]:
        """Encode query to embedding vector (runs in thread pool)."""
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(
            self._executor,
            lambda: self._model.encode([query], normalize_embeddings=True)
        )
        return embedding[0].tolist()

    async def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """
        Perform async semantic search using Qdrant.

        Args:
            query: Search query string
            top_k: Number of top results to return

        Returns:
            List of documents with similarity scores
        """
        await self._initialize()

        try:
            # Generate query embedding (async via executor)
            query_vector = await self._encode_query(query)

            # Search in Qdrant (native async)
            search_results = await self._client.search(
                collection_name=settings.QDRANT_COLLECTION_NAME,
                query_vector=query_vector,
                limit=top_k
            )

            # Format results
            results = []
            for hit in search_results:
                payload = hit.payload or {}
                sentence_id = payload.get('sentence_id', hit.id)

                # Get sentence text from payload or DB
                sentence_text = payload.get('sentence', '')
                if not sentence_text and self.db_repo:
                    try:
                        db_doc = await self.db_repo.get_document_by_id(sentence_id)
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
                f"🔍 Async Qdrant search: '{query[:50]}...' → {len(results)} documents "
                f"(avg score: {avg_score:.2f})"
            )
            return results

        except Exception as e:
            logger.error(f"Async Qdrant search failed: {e}")
            return []

    async def get_vector_count(self) -> int:
        """Get total number of vectors in collection."""
        await self._initialize()
        try:
            collection_info = await self._client.get_collection(settings.QDRANT_COLLECTION_NAME)
            return collection_info.points_count
        except Exception as e:
            logger.error(f"Failed to get vector count: {e}")
            return 0

    async def is_loaded(self) -> bool:
        """Check if Qdrant collection is accessible."""
        try:
            await self._initialize()
            collection_info = await self._client.get_collection(settings.QDRANT_COLLECTION_NAME)
            return collection_info.points_count > 0
        except:
            return False

    async def close(self):
        """Close client and executor."""
        if self._client:
            await self._client.close()
            self._client = None
        self._executor.shutdown(wait=False)
        self._initialized = False
        logger.info("Async Qdrant client closed")
