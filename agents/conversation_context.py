"""
대화 컨텍스트 관리 및 참조 해석

다중 턴 대화에서 대명사와 상대어를 이전 대화 내용으로 치환하여
사용자가 "그거", "이전에", "아까" 등의 표현을 사용해도
정확한 검색이 가능하도록 합니다.

모든 기능은 session_id 기반으로 세션별로 격리됩니다.
"""

from typing import Dict, Any, List, Optional
import re
from repositories.session_context_repository import SessionContextRepository
from utils.logger import logger


class ConversationContext:
    """
    세션별 대화 컨텍스트 관리 및 참조 해석

    기능:
    - 세션별 대화 히스토리 관리
    - 대명사/상대어 참조 해석
    - 컨텍스트 윈도우 관리
    """

    # 참조 패턴 정의
    REFERENCE_PATTERNS = {
        # 대명사
        'pronouns': ['그거', '저거', '이거', '그것', '저것', '이것', '그놈', '저놈'],
        # 상대어
        'relative': ['이전에', '앞에서', '전에', '아까', '방금', '조금 전'],
        # 지시어
        'demonstrative': ['위의', '위에', '그', '저', '해당']
    }

    def __init__(self, session_id: str, window_size: int = 5):
        """
        Args:
            session_id: 세션 식별자 (필수 - 세션별 격리)
            window_size: 참조 해석에 사용할 최근 대화 수 (기본 5개)
        """
        self.session_id = session_id
        self.window_size = window_size
        self.session_repo = SessionContextRepository()

        logger.debug(f"ConversationContext initialized for session: {session_id}")

    def resolve_references(self, question: str) -> Dict[str, Any]:
        """
        질문의 참조를 이전 대화에서 찾아서 해석

        Args:
            question: 사용자 질문 (참조 포함 가능)

        Returns:
            {
                'resolved_question': str,  # 참조가 해석된 질문
                'has_reference': bool,     # 참조 감지 여부
                'original_question': str,  # 원본 질문
                'context_used': int,       # 사용한 컨텍스트 수
                'references_found': List[str]  # 발견된 참조 표현
            }
        """
        # 1. 참조 감지
        references_found = self._detect_references(question)

        if not references_found:
            return {
                'resolved_question': question,
                'has_reference': False,
                'original_question': question,
                'context_used': 0,
                'references_found': []
            }

        logger.info(f"🔗 References detected in question: {references_found}")

        # 2. 히스토리 조회 (세션별)
        history = self.session_repo.get_conversation_history(
            session_id=self.session_id,
            limit=self.window_size
        )

        if not history:
            logger.warning(f"⚠️ No conversation history for session: {self.session_id}")
            return {
                'resolved_question': question,
                'has_reference': True,
                'original_question': question,
                'context_used': 0,
                'references_found': references_found,
                'warning': 'No conversation history available'
            }

        # 3. 참조 해석
        resolved_question = self._resolve_with_history(question, history, references_found)

        logger.info(f"✓ Reference resolved: '{question}' → '{resolved_question}'")

        return {
            'resolved_question': resolved_question,
            'has_reference': True,
            'original_question': question,
            'context_used': len(history),
            'references_found': references_found
        }

    def _detect_references(self, question: str) -> List[str]:
        """
        질문에서 참조 표현 감지

        Args:
            question: 사용자 질문

        Returns:
            발견된 참조 표현 리스트
        """
        found = []

        # 대명사 검사
        for pronoun in self.REFERENCE_PATTERNS['pronouns']:
            if pronoun in question:
                found.append(pronoun)

        # 상대어 검사
        for relative in self.REFERENCE_PATTERNS['relative']:
            if relative in question:
                found.append(relative)

        # 지시어 검사
        for demo in self.REFERENCE_PATTERNS['demonstrative']:
            # 단독으로 나타나는 경우만 (예: "그 설치 방법")
            if re.search(rf'\b{demo}\s+\w+', question):
                found.append(demo)

        return found

    def _resolve_with_history(
        self,
        question: str,
        history: List[Dict],
        references: List[str]
    ) -> str:
        """
        히스토리를 사용하여 참조 해석

        Args:
            question: 원본 질문
            history: 대화 히스토리
            references: 발견된 참조 표현들

        Returns:
            해석된 질문
        """
        resolved = question

        # 최근 대화에서 키워드 추출
        recent_keywords = self._extract_keywords_from_history(history)

        if not recent_keywords:
            logger.warning("No keywords extracted from history")
            return question

        # 참조 유형별 처리
        for ref in references:
            if ref in self.REFERENCE_PATTERNS['pronouns']:
                # 대명사: 가장 최근 대화의 주요 키워드로 치환
                resolved = self._replace_pronoun(resolved, ref, recent_keywords)

            elif ref in self.REFERENCE_PATTERNS['relative']:
                # 상대어: 이전 질문으로 치환
                resolved = self._replace_relative(resolved, ref, history)

            elif ref in self.REFERENCE_PATTERNS['demonstrative']:
                # 지시어: 컨텍스트 키워드 추가
                resolved = self._enhance_with_context(resolved, ref, recent_keywords)

        return resolved

    def _extract_keywords_from_history(self, history: List[Dict]) -> List[str]:
        """
        히스토리에서 중요 키워드 추출

        최근 대화의 질문과 답변에서 명사, 고유명사 추출

        Args:
            history: 대화 히스토리

        Returns:
            추출된 키워드 리스트 (중요도 순)
        """
        keywords = []

        # 최근 대화부터 역순 탐색
        for turn in reversed(history):
            question = turn.get('question', '')
            answer = turn.get('answer', '')

            # 브랜드명 추출 (고유명사)
            brands = self._extract_brand_names(question + ' ' + answer)
            keywords.extend(brands)

            # 기술 용어 추출
            tech_terms = self._extract_technical_terms(question + ' ' + answer)
            keywords.extend(tech_terms)

            # 일반 명사 추출 (한글 2글자 이상)
            nouns = re.findall(r'[가-힣]{2,}', question)
            keywords.extend(nouns[:3])  # 상위 3개만

        # 중복 제거 (순서 유지)
        seen = set()
        unique_keywords = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique_keywords.append(kw)

        return unique_keywords[:10]  # 상위 10개만

    def _extract_brand_names(self, text: str) -> List[str]:
        """브랜드명 추출 (고유명사)"""
        brands = [
            'RemoteCall', 'RemoteView', 'RemoteMeeting',
            'RVS', 'RCMP', 'SAAS', 'SFU', 'MCU'
        ]
        found = []
        for brand in brands:
            if brand in text:
                found.append(brand)
        return found

    def _extract_technical_terms(self, text: str) -> List[str]:
        """기술 용어 추출"""
        tech_terms = [
            'API', 'SDK', 'OAuth', 'JWT', 'SSL', 'TLS',
            'HTTP', 'HTTPS', 'REST', 'WebRTC',
            '설치', '인증', '연동', '배포', '설정'
        ]
        found = []
        for term in tech_terms:
            if term in text:
                found.append(term)
        return found

    def _replace_pronoun(
        self,
        question: str,
        pronoun: str,
        keywords: List[str]
    ) -> str:
        """
        대명사를 키워드로 치환

        예: "그거 버전은?" + keywords=['RemoteCall'] → "RemoteCall 버전은?"
        """
        if not keywords:
            return question

        # 가장 최근 키워드 사용 (첫 번째)
        main_keyword = keywords[0]

        # 대명사를 키워드로 치환
        resolved = question.replace(pronoun, main_keyword)

        logger.debug(f"Pronoun '{pronoun}' → '{main_keyword}'")

        return resolved

    def _replace_relative(
        self,
        question: str,
        relative: str,
        history: List[Dict]
    ) -> str:
        """
        상대어를 이전 질문으로 치환

        예: "이전에 물어본 거 다시 알려줘" → "RemoteCall 설치 방법 다시 알려줘"
        """
        if not history:
            return question

        # 가장 최근 질문 가져오기
        last_question = history[-1].get('question', '')

        # "이전에 물어본 것" 같은 표현을 실제 질문으로 치환
        patterns = [
            (r'이전에\s*물어본\s*\w*', last_question),
            (r'아까\s*\w*', last_question),
            (r'전에\s*\w*', last_question),
        ]

        resolved = question
        for pattern, replacement in patterns:
            if re.search(pattern, resolved):
                # 부분 치환: "이전에 물어본 거 다시" → "RemoteCall 설치 방법 다시"
                resolved = re.sub(pattern, replacement, resolved)
                break

        return resolved

    def _enhance_with_context(
        self,
        question: str,
        demonstrative: str,
        keywords: List[str]
    ) -> str:
        """
        지시어에 컨텍스트 키워드 추가

        예: "그 설치 방법은?" + keywords=['RemoteCall'] → "RemoteCall 설치 방법은?"
        """
        if not keywords:
            return question

        main_keyword = keywords[0]

        # "그 XXX" → "키워드 XXX"
        pattern = rf'\b{demonstrative}\s+(\w+)'

        def replacer(match):
            return f"{main_keyword} {match.group(1)}"

        resolved = re.sub(pattern, replacer, question)

        return resolved

    def add_turn(
        self,
        question: str,
        answer: str,
        sources: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        대화 턴 추가 (세션별)

        Args:
            question: 사용자 질문
            answer: 시스템 답변
            sources: 답변 출처 문서
            metadata: 추가 메타데이터

        Returns:
            성공 여부
        """
        return self.session_repo.add_conversation_turn(
            session_id=self.session_id,
            question=question,
            answer=answer,
            sources=sources,
            metadata=metadata
        )

    def get_history(self, limit: Optional[int] = None) -> List[Dict]:
        """
        대화 히스토리 조회 (세션별)

        Args:
            limit: 반환할 최근 대화 수 (None이면 window_size 사용)

        Returns:
            대화 히스토리 리스트
        """
        actual_limit = limit if limit is not None else self.window_size
        return self.session_repo.get_conversation_history(
            session_id=self.session_id,
            limit=actual_limit
        )

    def clear_session(self) -> bool:
        """
        현재 세션 초기화

        Returns:
            성공 여부
        """
        return self.session_repo.create_session(
            session_id=self.session_id
        )
