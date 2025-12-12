"""
Agent 의사결정 기록 및 설명 생성 모듈

Agent의 도구 선택, 검증 결과, 종료 결정 등 모든 의사결정을
기록하고 사람이 이해할 수 있는 설명을 생성합니다.

debug=True일 때만 상세 로그를 저장하여 성능 오버헤드를 최소화합니다.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import json
from utils.logger import logger


class DecisionLogger:
    """
    Agent의 모든 의사결정을 기록하고 설명 생성.
    debug=True일 때만 상세 로그 저장.
    """

    def __init__(self, debug: bool = False):
        """
        Args:
            debug: True면 상세 로그 저장, False면 최소 로그만
        """
        self.debug = debug
        self.decisions: List[Dict] = []
        self.session_start = datetime.now()

    def log_tool_selection(
        self,
        iteration: int,
        question: str,
        selected_tool: str,
        tool_args: Dict,
        thought: str,
        context: Dict
    ) -> None:
        """
        도구 선택 결정 기록

        Args:
            iteration: 현재 반복 횟수
            question: 사용자 질문
            selected_tool: 선택된 도구명
            tool_args: 도구 실행 인자
            thought: Agent의 생각 (LLM 출력)
            context: 결정 시점의 컨텍스트
                - doc_count: 현재까지 수집된 문서 수
                - avg_quality: 평균 문서 품질
                - previous_tool: 이전에 사용한 도구
                - iteration: 현재 반복 횟수
        """
        # 설명 생성
        reason = self._explain_selection(
            question, selected_tool, context
        )

        decision = {
            'iteration': iteration,
            'type': 'tool_selection',
            'selected_tool': selected_tool,
            'tool_args': tool_args if self.debug else {},  # debug만 저장
            'thought': thought if self.debug else "",
            'reason': reason,
            'context': {
                'doc_count': context.get('doc_count', 0),
                'avg_quality': context.get('avg_quality', 0),
                'previous_tool': context.get('previous_tool'),
            },
            'timestamp': datetime.now().isoformat()
        }

        self.decisions.append(decision)

        # 로깅
        logger.info(f"🤔 Iteration {iteration}: {selected_tool} 선택")
        logger.info(f"   이유: {reason}")

    def log_validation_result(
        self,
        iteration: int,
        validation: Dict
    ) -> None:
        """
        검증 결과 기록

        Args:
            iteration: 현재 반복 횟수
            validation: 검증 결과
                - relevance: 관련성
                - novelty: 새로움
                - sufficiency: 충분성
                - quality: 품질 점수
                - decision: 판단 결과 텍스트
        """
        decision = {
            'iteration': iteration,
            'type': 'validation',
            'relevance': validation.get('relevance', False),
            'novelty': validation.get('novelty', False),
            'sufficiency': validation.get('sufficiency', False),
            'quality': validation.get('quality', 0),
            'decision': validation.get('decision', ''),
            'timestamp': datetime.now().isoformat()
        }

        self.decisions.append(decision)

        # debug 모드에서만 상세 로깅
        if self.debug:
            logger.debug(
                f"📋 검증 결과 (Iteration {iteration}): "
                f"관련성={validation.get('relevance')}, "
                f"새로움={validation.get('novelty')}, "
                f"충분성={validation.get('sufficiency')}, "
                f"품질={validation.get('quality', 0):.2f}"
            )

    def log_early_stop(
        self,
        iteration: int,
        reason: str
    ) -> None:
        """
        조기 종료 결정 기록

        Args:
            iteration: 종료 시점의 반복 횟수
            reason: 종료 이유
        """
        decision = {
            'iteration': iteration,
            'type': 'early_stop',
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        }

        self.decisions.append(decision)

        logger.info(f"🏁 조기 종료 (Iteration {iteration}): {reason}")

    def _explain_selection(
        self,
        question: str,
        tool: str,
        context: Dict
    ) -> str:
        """
        도구 선택 이유 설명 생성 (규칙 기반)

        Args:
            question: 사용자 질문
            tool: 선택된 도구명
            context: 결정 컨텍스트

        Returns:
            사람이 이해할 수 있는 선택 이유
        """
        iteration = context.get('iteration', 1)
        doc_count = context.get('doc_count', 0)
        previous_tool = context.get('previous_tool')

        # =========================================
        # Iteration 1: 초기 전략 설명
        # =========================================
        if iteration == 1:
            if 'error_code' in tool:
                return "질문에 에러 코드가 포함되어 있어 에러코드 DB를 우선 검색"

            elif 'elasticsearch' in tool:
                # 브랜드 키워드 감지 여부 확인
                brands = ['RVS', 'RCMP', 'RemoteCall', 'RemoteView', 'RemoteMeeting', 'SAAS']
                if any(brand in question for brand in brands):
                    return "브랜드 키워드 감지, BM25 필터링 검색 사용"
                else:
                    return "BM25 알고리즘으로 키워드 정확도 높은 검색"

            elif 'qdrant' in tool:
                # 절차/방법 질문 감지
                how_keywords = ['어떻게', '방법', '설정', '설치', 'how', 'setup']
                if any(keyword in question for keyword in how_keywords):
                    return "절차/방법 질문으로 의미 기반 검색이 효과적"
                else:
                    return "의미 기반 검색으로 관련 문서 탐색"

            elif 'mariadb' in tool and 'keyword' in tool:
                return "정확한 키워드 매칭이 필요한 질문"

            elif 'recent_logs' in tool:
                # 과거 케이스 감지
                past_keywords = ['전에', '이전에', '유사한', '같은']
                if any(keyword in question for keyword in past_keywords):
                    return "과거 유사 케이스 검색 요청"
                else:
                    return "최근 로그 검색"

            else:
                return f"질문 유형에 최적화된 도구: {tool}"

        # =========================================
        # Iteration 2+: 적응 전략 설명
        # =========================================
        else:
            if doc_count == 0:
                return f"이전 검색({previous_tool}) 결과 없음, 다른 전략({tool}) 시도"

            elif doc_count < 5:
                return f"문서 부족({doc_count}개), 추가 검색({tool})으로 보완"

            elif doc_count >= 5:
                return f"보완 검색: 다양한 출처 확보를 위한 {tool} 활용"

            else:
                return f"검색 전략 조정: {tool} 시도"

    def get_search_summary(self) -> str:
        """
        검색 과정 요약 생성 (사용자용)

        Returns:
            검색 과정을 요약한 텍스트
        """
        if not self.decisions:
            return "검색 기록 없음"

        summary_lines = ["🔍 검색 과정 요약:\n"]

        # 도구 선택 결정만 필터링
        tool_selections = [
            d for d in self.decisions
            if d['type'] == 'tool_selection'
        ]

        for i, decision in enumerate(tool_selections, 1):
            tool = decision['selected_tool']
            reason = decision['reason']
            doc_count = decision['context']['doc_count']

            summary_lines.append(
                f"{i}. {tool}\n"
                f"   └─ {reason}\n"
                f"   └─ 수집: {doc_count}개 문서\n"
            )

        # 최종 결정
        if self.decisions and self.decisions[-1]['type'] == 'early_stop':
            summary_lines.append(
                f"\n✓ 종료: {self.decisions[-1]['reason']}"
            )

        return '\n'.join(summary_lines)

    def get_decision_timeline(self) -> List[Dict]:
        """
        시간순 결정 타임라인 (debug용)

        Returns:
            모든 결정의 타임라인 (debug=True일 때만)
        """
        if not self.debug:
            return []

        return self.decisions

    def export_for_learning(self) -> Optional[Dict]:
        """
        학습용 데이터 추출 (debug=True일 때만)

        학습 메커니즘이 활성화되면 이 데이터를 사용하여
        도구 선택 패턴을 학습할 수 있습니다.

        Returns:
            학습용 데이터 딕셔너리 또는 None
        """
        if not self.debug:
            return None

        tool_sequence = [
            d['selected_tool']
            for d in self.decisions
            if d['type'] == 'tool_selection'
        ]

        return {
            'session_start': self.session_start.isoformat(),
            'total_decisions': len(self.decisions),
            'decisions': self.decisions,
            'tool_sequence': tool_sequence,
            'final_doc_count': self.decisions[-1].get('context', {}).get('doc_count', 0) if self.decisions else 0
        }

    def get_statistics(self) -> Dict[str, Any]:
        """
        결정 통계 생성 (분석용)

        Returns:
            통계 딕셔너리
        """
        tool_selections = [
            d for d in self.decisions
            if d['type'] == 'tool_selection'
        ]

        validations = [
            d for d in self.decisions
            if d['type'] == 'validation'
        ]

        # 도구별 사용 횟수
        tool_usage = {}
        for decision in tool_selections:
            tool = decision['selected_tool']
            tool_usage[tool] = tool_usage.get(tool, 0) + 1

        # 평균 품질
        quality_scores = [
            v['quality']
            for v in validations
            if 'quality' in v
        ]
        avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0

        return {
            'total_iterations': len(tool_selections),
            'unique_tools_used': len(tool_usage),
            'tool_usage': tool_usage,
            'avg_quality': avg_quality,
            'early_stopped': any(d['type'] == 'early_stop' for d in self.decisions)
        }

    def reset(self):
        """결정 기록 초기화 (새 검색 시작 시)"""
        self.decisions = []
        self.session_start = datetime.now()
