"""
답변 품질 검증 모듈 (환각 방지)

생성된 답변의 품질을 평가하여 환각(Hallucination)을 방지하고
신뢰도를 측정합니다.

검증 항목:
- 관련성: 질문과 답변의 연관성
- 근거성: 답변이 문서에 근거하는가 (환각 방지)
- 완전성: 질문의 모든 부분에 답했는가
"""

from typing import List, Dict, Any
from openai import OpenAI
from utils.logger import logger
import re


class AnswerValidator:
    """
    생성된 답변의 품질 검증

    환각 방지를 위한 근거성 검증에 중점을 둠
    """

    def __init__(self, client: OpenAI):
        """
        Args:
            client: OpenAI 클라이언트 (향후 LLM 기반 검증에 사용 가능)
        """
        self.client = client

    def validate_answer(
        self,
        question: str,
        answer: str,
        source_docs: List[Dict]
    ) -> Dict[str, Any]:
        """
        답변 품질 종합 평가

        Args:
            question: 사용자 질문
            answer: 생성된 답변
            source_docs: 답변 생성에 사용된 문서들

        Returns:
            {
                'confidence': float (0-1),  # 종합 신뢰도
                'relevance_score': float,    # 관련성
                'grounding_score': float,    # 근거성 (환각 방지)
                'completeness_score': float, # 완전성
                'is_acceptable': bool,       # 신뢰도 >= 0.6
                'warnings': List[str]        # 경고 메시지
            }
        """
        # 1. 관련성 체크 (키워드 중복 기반)
        relevance = self._check_relevance(question, answer)

        # 2. 근거성 체크 (문서 내용과 답변 비교)
        grounding = self._check_grounding(answer, source_docs)

        # 3. 완전성 체크 (질문 키워드 커버리지)
        completeness = self._check_completeness(question, answer)

        # 종합 신뢰도 (가중 평균)
        confidence = (
            relevance * 0.3 +
            grounding * 0.4 +  # 환각 방지 가장 중요
            completeness * 0.3
        )

        # 경고 생성
        warnings = self._generate_warnings(
            relevance, grounding, completeness
        )

        logger.info(
            f"📊 답변 검증: 신뢰도 {confidence:.2%} "
            f"(관련성 {relevance:.2f}, 근거성 {grounding:.2f}, 완전성 {completeness:.2f})"
        )

        return {
            'confidence': confidence,
            'relevance_score': relevance,
            'grounding_score': grounding,
            'completeness_score': completeness,
            'is_acceptable': confidence >= 0.6,
            'warnings': warnings
        }

    def _check_relevance(self, question: str, answer: str) -> float:
        """
        질문-답변 관련성 체크 (키워드 중복 기반)

        Args:
            question: 사용자 질문
            answer: 생성된 답변

        Returns:
            관련성 점수 (0.0 - 1.0)
        """
        # 키워드 추출 (조사 제거 및 불용어 필터링 적용)
        q_keywords = self._extract_keywords(question)
        a_keywords = self._extract_keywords(answer)

        q_words = set(q_keywords)
        a_words = set(a_keywords)

        if not q_words:
            return 1.0

        # Precision 기반 관련성 (질문 키워드가 답변에 포함된 비율)
        # RAG 시스템에서는 답변이 질문의 모든 키워드를 다루는지가 중요
        overlap = len(q_words & a_words)

        if len(q_words) == 0:
            return 0.0

        return overlap / len(q_words)

    def _check_grounding(self, answer: str, docs: List[Dict]) -> float:
        """
        답변이 문서에 근거하는지 확인 (환각 방지)

        전략:
        1. 답변을 문장으로 분리
        2. 각 문장의 주장이 문서에서 지지되는지 확인
        3. 지지되는 문장 비율 계산

        Args:
            answer: 생성된 답변
            docs: 참조 문서들

        Returns:
            근거성 점수 (0.0 - 1.0)
        """
        if not docs:
            logger.warning("⚠️ 문서 없음 - 근거성 낮음")
            return 0.3

        # 답변 문장 분리
        claims = self._extract_claims(answer)

        if not claims:
            return 0.5  # 주장이 없으면 중립

        # 각 주장이 문서에서 지지되는지 확인
        grounded_count = 0
        for claim in claims:
            if self._is_claim_supported(claim, docs):
                grounded_count += 1

        grounding_score = grounded_count / len(claims)

        if grounding_score < 0.5:
            logger.warning(
                f"⚠️ 환각 가능성: {len(claims)}개 주장 중 "
                f"{grounded_count}개만 문서에서 확인됨"
            )

        return grounding_score

    def _extract_claims(self, answer: str) -> List[str]:
        """
        답변에서 검증 가능한 주장 추출

        Args:
            answer: 생성된 답변

        Returns:
            사실 주장 문장 리스트
        """
        # 문장 분리 (. 기준)
        sentences = [
            s.strip()
            for s in answer.split('.')
            if len(s.strip()) > 10
        ]

        # 추측/의견 필터링 (사실 주장만)
        opinion_markers = [
            '것 같', '추측', '아마', '예상', '생각합니다',
            '것으로 보입니다', '가능성', '추정'
        ]

        # 순수 메타 문장 패턴 (구조적 문장만, 내용 없음)
        pure_meta_patterns = [
            '다음과 같습니다', '다음과 같이', '아래와 같습니다', '아래와 같이',
            '정리하면', '요약하면', '결론적으로',
            '살펴보겠습니다', '설명하겠습니다', '알려드리겠습니다'
        ]

        claims = []
        for sent in sentences:
            # 의견 표현 포함 시 제외
            if any(marker in sent for marker in opinion_markers):
                continue

            # 순수 메타 문장 제외 (내용 없이 구조만 있는 문장)
            is_pure_meta = any(pattern in sent for pattern in pure_meta_patterns)
            # 키워드 추출하여 실제 내용이 있는지 확인
            keywords = self._extract_keywords(sent)
            has_content = len(keywords) >= 4  # 최소 4개 이상의 의미 있는 단어가 있으면 내용 있음

            # 순수 메타이고 내용이 부족하면 제외
            if is_pure_meta and not has_content:
                continue

            # 너무 짧거나 질문 문장 제외
            if len(sent) < 10 or '?' in sent:
                continue

            claims.append(sent)

        return claims

    def _is_claim_supported(self, claim: str, docs: List[Dict]) -> bool:
        """
        주장이 문서에서 지지되는지 확인

        전략:
        - 주장의 주요 키워드가 문서에 50% 이상 포함되면 지지됨

        Args:
            claim: 검증할 주장 문장
            docs: 참조 문서들

        Returns:
            지지 여부
        """
        # 주장에서 키워드 추출 (조사 제거 적용)
        claim_keywords = self._extract_keywords(claim)
        claim_words = set(claim_keywords)

        if not claim_words:
            return True  # 키워드 없으면 중립

        # 상위 5개 문서에서 확인
        for doc in docs[:5]:
            doc_text = doc.get('content', doc.get('text', ''))
            # 문서에서도 키워드 추출 (조사 제거 적용)
            doc_keywords = self._extract_keywords(doc_text)
            doc_words = set(doc_keywords)

            # 키워드 중복 비율
            overlap = len(claim_words & doc_words)
            coverage = overlap / len(claim_words)

            if coverage >= 0.7:  # 70% 이상 매칭 (더 엄격한 기준)
                return True

        return False

    def _check_completeness(self, question: str, answer: str) -> float:
        """
        질문의 모든 부분에 답했는지 확인

        Args:
            question: 사용자 질문
            answer: 생성된 답변

        Returns:
            완전성 점수 (0.0 - 1.0)
        """
        # 질문에서 키워드 추출
        q_keywords = self._extract_keywords(question)

        if not q_keywords:
            return 1.0

        # 답변에 키워드 포함 여부
        covered = sum(1 for kw in q_keywords if kw in answer)

        completeness = covered / len(q_keywords)

        if completeness < 0.6:
            missing = [kw for kw in q_keywords if kw not in answer]
            logger.warning(f"⚠️ 답변 불완전: 미포함 키워드 {missing}")

        return completeness

    def _strip_postpositions(self, word: str) -> str:
        """
        한글 조사 및 어미 제거

        Args:
            word: 입력 단어

        Returns:
            조사/어미가 제거된 단어
        """
        # 한글 조사 및 동사 어미 목록 (가장 긴 것부터 체크)
        suffixes = [
            # 조사
            '에서는', '에서도', '에게는', '에게도', '으로는', '으로도',
            '에서', '에게', '으로', '로는', '로도', '부터', '까지', '마저', '조차',
            '은', '는', '이', '가', '을', '를', '에', '의', '와', '과', '도', '만',
            # 동사 어미 (긴 것부터)
            '했습니다', '합니다', '합니까', '했습니까', '습니다',
            '하세요', '하십시오', '하시오', '세요', '십시오',
            '하고', '하며', '하거나', '하지만', '하면', '하면서',
            '되면', '되고', '되며', '됩니다', '입니다'
        ]

        for suffix in suffixes:
            if word.endswith(suffix) and len(word) > len(suffix):
                return word[:-len(suffix)]

        return word

    def _extract_keywords(self, text: str) -> List[str]:
        """
        텍스트에서 주요 키워드 추출

        Args:
            text: 입력 텍스트

        Returns:
            키워드 리스트
        """
        # 불용어
        stopwords = {
            '은', '는', '이', '가', '을', '를', '에', '의', '와', '과',
            '어떻게', '무엇', '왜', '언제', '어디', '누가',
            '알려', '주세요', '해주세요', '알려주세요', '좀', '뭐', '것', '알려줘',
            # 메타 단어 (구조적 표현)
            '다음', '아래', '위', '같', '다르', '이런', '저런', '그런'
        }

        # 2글자 이상 단어만 (한글 특성상 2글자도 의미 있음)
        words = []
        for w in text.split():
            if len(w) >= 2:
                # 조사 제거 먼저
                cleaned = self._strip_postpositions(w)
                # 조사 제거 후 불용어 체크
                if cleaned and len(cleaned) >= 2 and cleaned not in stopwords:
                    words.append(cleaned)

        return words

    def _generate_warnings(
        self,
        relevance: float,
        grounding: float,
        completeness: float
    ) -> List[str]:
        """
        경고 메시지 생성

        Args:
            relevance: 관련성 점수
            grounding: 근거성 점수
            completeness: 완전성 점수

        Returns:
            경고 메시지 리스트
        """
        warnings = []

        if relevance < 0.5:
            warnings.append(
                "⚠️ 답변이 질문과 관련성이 낮을 수 있습니다"
            )

        if grounding < 0.5:
            warnings.append(
                "⚠️ 답변의 일부 내용이 제공된 문서에서 확인되지 않습니다 (환각 가능성)"
            )

        if completeness < 0.6:
            warnings.append(
                "⚠️ 질문의 일부 내용에 대한 답변이 부족할 수 있습니다"
            )

        return warnings
