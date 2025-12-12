"""
Reranking Engine using Cohere Rerank API.

재순위화를 통한 검색 정확도 향상:
- Top-K 문서를 Cross-Encoder로 재정렬
- 의미적 관련성 기반 정밀 순위
- Precision 향상 (+15% 기대)
"""

from typing import List, Dict, Any, Optional
import cohere
from config.settings import settings
from utils.logger import logger


class Reranker:
    """
    Cohere Rerank API를 사용한 문서 재정렬.

    Features:
    - Cross-encoder 기반 정밀 순위
    - Top-K 문서 재정렬
    - Relevance score 정규화
    - Fallback to original order
    """

    def __init__(self, client=None, model: str = "rerank-english-v3.0"):
        """
        Args:
            client: Cohere client (테스트용)
            model: Rerank model name
        """
        self.client = client or cohere.Client(api_key=settings.COHERE_API_KEY)
        self.model = model

    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_n: Optional[int] = None,
        return_documents: bool = True
    ) -> List[Dict[str, Any]]:
        """
        문서를 query와의 관련성 기준으로 재정렬.

        Args:
            query: 검색 쿼리
            documents: 재정렬할 문서 리스트
            top_n: 반환할 상위 N개 (None이면 모두 반환)
            return_documents: True면 문서 포함, False면 index만

        Returns:
            재정렬된 문서 리스트 (relevance_score 추가됨)
        """
        if not documents:
            logger.warning("No documents to rerank")
            return []

        if len(documents) == 1:
            logger.info("Only 1 document, skipping rerank")
            # Add relevance_score field
            documents[0]['relevance_score'] = 1.0
            return documents

        logger.info(f"🔄 Reranking {len(documents)} documents with query: '{query[:50]}...'")

        try:
            # Extract text content from documents
            texts = self._extract_texts(documents)

            # Call Cohere Rerank API
            results = self.client.rerank(
                model=self.model,
                query=query,
                documents=texts,
                top_n=top_n,
                return_documents=return_documents
            )

            # Map reranked results back to original documents
            reranked_docs = self._map_results_to_documents(
                results=results.results,
                original_documents=documents
            )

            logger.info(f"✓ Reranked to {len(reranked_docs)} documents")

            # Log top 3 relevance scores
            if len(reranked_docs) >= 3:
                top_3_scores = [doc.get('relevance_score', 0) for doc in reranked_docs[:3]]
                logger.debug(f"  Top 3 relevance scores: {top_3_scores}")

            return reranked_docs

        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            logger.info("Falling back to original order")

            # Add default relevance_score to original documents
            for i, doc in enumerate(documents):
                doc['relevance_score'] = 1.0 - (i * 0.01)  # Slight decay

            return documents[:top_n] if top_n else documents

    def _extract_texts(self, documents: List[Dict[str, Any]]) -> List[str]:
        """
        문서에서 텍스트 추출.

        Args:
            documents: 문서 리스트

        Returns:
            텍스트 리스트
        """
        texts = []

        for doc in documents:
            # Try different content fields
            text = (
                doc.get('content') or
                doc.get('text') or
                doc.get('page_content') or
                doc.get('body') or
                str(doc)
            )

            # Truncate to reasonable length (Cohere limit: 512 tokens)
            if len(text) > 2000:
                text = text[:2000]

            texts.append(text)

        return texts

    def _map_results_to_documents(
        self,
        results: List[Any],
        original_documents: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Rerank 결과를 원본 문서에 매핑.

        Args:
            results: Cohere rerank results
            original_documents: 원본 문서 리스트

        Returns:
            재정렬된 문서 리스트 (relevance_score 추가)
        """
        reranked_docs = []

        for result in results:
            index = result.index
            relevance_score = result.relevance_score

            # Get original document
            if 0 <= index < len(original_documents):
                doc = original_documents[index].copy()
                doc['relevance_score'] = relevance_score
                doc['rerank_position'] = len(reranked_docs) + 1
                reranked_docs.append(doc)
            else:
                logger.warning(f"Invalid index {index} in rerank results")

        return reranked_docs

    def rerank_with_threshold(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        threshold: float = 0.5,
        min_docs: int = 3
    ) -> List[Dict[str, Any]]:
        """
        임계값 기반 재정렬 (낮은 관련성 문서 필터링).

        Args:
            query: 검색 쿼리
            documents: 재정렬할 문서 리스트
            threshold: 최소 relevance_score
            min_docs: 최소 반환 문서 수

        Returns:
            필터링 및 재정렬된 문서 리스트
        """
        # First rerank all documents
        reranked = self.rerank(query=query, documents=documents, top_n=None)

        # Filter by threshold
        filtered = [
            doc for doc in reranked
            if doc.get('relevance_score', 0) >= threshold
        ]

        # Ensure minimum number of documents
        if len(filtered) < min_docs and len(reranked) > 0:
            logger.warning(
                f"Only {len(filtered)} docs above threshold {threshold}, "
                f"returning top {min_docs} instead"
            )
            return reranked[:min_docs]

        logger.info(
            f"Filtered {len(reranked)} → {len(filtered)} documents "
            f"(threshold: {threshold})"
        )

        return filtered

    def get_rerank_stats(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Rerank 통계 계산.

        Args:
            documents: 재정렬된 문서 리스트 (relevance_score 포함)

        Returns:
            통계 딕셔너리
        """
        if not documents:
            return {
                'count': 0,
                'avg_relevance': 0.0,
                'max_relevance': 0.0,
                'min_relevance': 0.0
            }

        relevance_scores = [
            doc.get('relevance_score', 0)
            for doc in documents
        ]

        return {
            'count': len(documents),
            'avg_relevance': sum(relevance_scores) / len(relevance_scores),
            'max_relevance': max(relevance_scores),
            'min_relevance': min(relevance_scores),
            'top_3_avg': (
                sum(relevance_scores[:3]) / 3
                if len(relevance_scores) >= 3
                else sum(relevance_scores) / len(relevance_scores)
            )
        }


# Global instance
reranker = Reranker()
