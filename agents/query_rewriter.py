"""
Query Rewriting Engine

쿼리 다변화를 통한 검색 정확도 향상:
- 1개 쿼리 → 5개 변형 생성
- 다양한 재작성 전략 적용
- Recall 향상 (+20% 기대)
"""

from typing import List, Dict, Any
import openai
from config.settings import settings
from utils.logger import logger
import re


class QueryRewriter:
    """
    쿼리 재작성 엔진.

    Features:
    - 키워드 추출 및 확장
    - 유사어 변환
    - 질문 형태 다변화
    - 기술 용어 변환
    - 에러코드 강조
    """

    def __init__(self, client=None):
        """
        Args:
            client: OpenAI client (테스트용)
        """
        self.client = client or openai.OpenAI(api_key=settings.OPENAI_API_KEY)

        # 재작성 전략
        self.strategies = [
            "keyword_extraction",      # 핵심 키워드 중심
            "semantic_expansion",       # 유사어/동의어 확장
            "technical_reformulation",  # 기술 용어 변환
            "question_decomposition",   # 하위 질문 분해
            "error_code_emphasis"       # 에러코드 강조
        ]

    def rewrite_query(
        self,
        original_query: str,
        num_variants: int = 4,
        session_id: str = None # type: ignore
    ) -> List[str]:
        """
        쿼리를 여러 방식으로 재작성.

        Args:
            original_query: 원본 쿼리
            num_variants: 생성할 변형 개수 (기본 4개)
            session_id: 세션 ID (로깅용)

        Returns:
            [원본, 변형1, 변형2, 변형3, 변형4] (총 5개)
        """
        logger.info(f"🔄 Query Rewriting: '{original_query[:50]}...'")

        try:
            # 1. 원본 쿼리 포함
            all_queries = [original_query]

            # 2. GPT로 다양한 변형 생성
            variants = self._generate_variants_with_gpt(original_query, num_variants)

            # 3. 중복 제거 및 품질 필터링
            unique_variants = self._filter_variants(variants, original_query)

            # 4. 최대 num_variants개만 선택
            all_queries.extend(unique_variants[:num_variants])

            logger.info(f"✓ Generated {len(all_queries)} query variants")
            for i, query in enumerate(all_queries):
                logger.debug(f"  [{i}] {query}")

            return all_queries

        except Exception as e:
            logger.error(f"Query rewriting failed: {e}")
            # 실패 시 원본만 반환
            return [original_query]

    def _generate_variants_with_gpt(
        self,
        query: str,
        num_variants: int
    ) -> List[str]:
        """
        GPT를 사용한 쿼리 변형 생성.

        Args:
            query: 원본 쿼리
            num_variants: 생성할 변형 개수

        Returns:
            변형 쿼리 리스트
        """
        prompt = f"""다음 사용자 질문을 {num_variants}가지 다른 방식으로 재작성하세요.

원본 질문: "{query}"

재작성 전략:
1. 핵심 키워드 중심으로 간결하게
2. 유사어/동의어를 사용하여 의미 확장
3. 기술 용어를 일반 용어로 또는 그 반대로
4. 질문을 더 구체적으로 또는 더 일반적으로

각 변형은 원본과 같은 의미를 유지하되 표현을 다르게 하세요.
에러코드나 제품명이 있다면 반드시 포함하세요.

재작성된 질문 (각 줄에 하나씩, 번호 없이):"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",  # 빠르고 저렴한 모델
                messages=[
                    {"role": "system", "content": "당신은 검색 쿼리 최적화 전문가입니다."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,  # 다양성을 위해 약간 높게
                max_tokens=300
            )

            content = response.choices[0].message.content.strip() # type: ignore

            # 줄바꿈으로 분리
            variants = [
                line.strip()
                for line in content.split('\n')
                if line.strip() and not line.strip().startswith(('#', '-', '*', '1.', '2.', '3.', '4.'))
            ]

            return variants

        except Exception as e:
            logger.error(f"GPT variant generation failed: {e}")

            # Fallback: 간단한 규칙 기반 변형
            return self._generate_simple_variants(query, num_variants)

    def _generate_simple_variants(
        self,
        query: str,
        num_variants: int
    ) -> List[str]:
        """
        GPT 실패 시 간단한 규칙 기반 변형.

        Args:
            query: 원본 쿼리
            num_variants: 생성할 변형 개수

        Returns:
            변형 쿼리 리스트
        """
        variants = []

        # 1. 키워드 추출 (명사만)
        keywords = self._extract_keywords(query)
        if keywords:
            variant1 = ' '.join(keywords)
            variants.append(variant1)

        # 2. 질문형 → 서술형
        if '?' in query:
            variant2 = query.replace('?', '').strip()
            variants.append(variant2)

        # 3. 에러코드 강조
        error_codes = re.findall(r'\b\d{5}\b|\bRCXERR_\w+\b', query)
        if error_codes:
            variant3 = f"에러 {error_codes[0]}"
            variants.append(variant3)

        # 4. 제품명 강조
        brands = ['RemoteView', 'RemoteCall', 'RemoteMeeting', 'RemoteWOL']
        for brand in brands:
            if brand.lower() in query.lower():
                variant4 = f"{brand} {query.replace(brand, '').strip()}"
                variants.append(variant4)
                break

        return variants[:num_variants]

    def _extract_keywords(self, text: str) -> List[str]:
        """
        간단한 키워드 추출 (명사 추정).

        Args:
            text: 입력 텍스트

        Returns:
            키워드 리스트
        """
        # 불용어 제거
        stopwords = {'을', '를', '이', '가', '은', '는', '에', '의', '로', '으로', '와', '과',
                     '어떻게', '무엇', '왜', '언제', '어디서', '누가', '하나요', '인가요',
                     '알려주세요', '해주세요', '주세요', '요'}

        # 공백으로 분리
        words = text.split()

        # 불용어 제거 및 짧은 단어 제거
        keywords = [
            word
            for word in words
            if word not in stopwords and len(word) > 1
        ]

        return keywords

    def _filter_variants(
        self,
        variants: List[str],
        original: str
    ) -> List[str]:
        """
        변형 쿼리 품질 필터링.

        Args:
            variants: 생성된 변형 리스트
            original: 원본 쿼리

        Returns:
            필터링된 변형 리스트
        """
        filtered = []
        seen = {original.lower()}

        for variant in variants:
            # 공백 정리
            variant = variant.strip()

            # 유효성 검사
            if not variant:
                continue

            if len(variant) < 3:  # 너무 짧음
                continue

            if len(variant) > 200:  # 너무 김
                continue

            # 중복 제거 (대소문자 무시)
            variant_lower = variant.lower()
            if variant_lower in seen:
                continue

            # 원본과 너무 유사한지 체크 (Jaccard similarity)
            similarity = self._calculate_similarity(original, variant)
            if similarity > 0.9:  # 90% 이상 유사하면 스킵
                continue

            seen.add(variant_lower)
            filtered.append(variant)

        return filtered

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """
        Jaccard similarity 계산.

        Args:
            text1: 첫 번째 텍스트
            text2: 두 번째 텍스트

        Returns:
            유사도 (0~1)
        """
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union)

    def get_best_variant(
        self,
        variants: List[str],
        retrieval_results: Dict[str, List[Dict]]
    ) -> str:
        """
        검색 결과를 기반으로 최적 변형 선택.

        Args:
            variants: 변형 쿼리 리스트
            retrieval_results: 각 변형별 검색 결과

        Returns:
            최적 변형 쿼리
        """
        # 각 변형별 검색 결과 수와 평균 score
        scores = {}

        for variant in variants:
            results = retrieval_results.get(variant, [])

            if not results:
                scores[variant] = 0.0
                continue

            # 결과 수 + 평균 score
            avg_score = sum(doc.get('score', 0) for doc in results) / len(results)
            scores[variant] = len(results) * avg_score

        # 가장 높은 점수의 변형 선택
        best_variant = max(scores, key=scores.get, default=variants[0]) # type: ignore

        logger.info(f"✓ Best variant selected: '{best_variant}' (score: {scores[best_variant]:.2f})")

        return best_variant


# Global instance
query_rewriter = QueryRewriter()
