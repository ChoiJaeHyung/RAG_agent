"""
Performance Profiler for SearchAgent

병목 지점 파악 및 성능 측정 시스템
"""

from typing import Dict, Any, List, Optional
import time
from dataclasses import dataclass, field
from collections import defaultdict
import json
from utils.logger import logger


@dataclass
class TimingRecord:
    """개별 작업 타이밍 기록"""
    operation: str
    start_time: float
    end_time: float
    duration: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        """밀리초 단위 실행 시간"""
        return self.duration * 1000


class PerformanceProfiler:
    """
    SearchAgent 성능 프로파일링

    병목 지점:
    1. LLM API 호출 (ReAct loop)
    2. Tool 실행 (Qdrant/MariaDB/ES)
    3. 문서 검증 및 컴파일
    4. 최종 답변 생성
    """

    def __init__(self, enabled: bool = True):
        """
        Args:
            enabled: 프로파일링 활성화 여부
        """
        self.enabled = enabled
        self.timings: List[TimingRecord] = []
        self.active_timers: Dict[str, float] = {}
        self.session_start: Optional[float] = None

    def start_session(self):
        """세션 시작 (전체 search() 실행)"""
        if self.enabled:
            self.session_start = time.time()
            self.timings.clear()
            self.active_timers.clear()

    def start_timer(self, operation: str, metadata: Optional[Dict[str, Any]] = None):
        """
        타이머 시작

        Args:
            operation: 작업 이름 (예: "llm_call", "tool_execution", "document_validation")
            metadata: 추가 정보 (예: tool_name, query 등)
        """
        if not self.enabled:
            return

        timer_key = f"{operation}_{len(self.timings)}"
        self.active_timers[timer_key] = time.time()

        # Metadata 저장
        if metadata:
            self.active_timers[f"{timer_key}_meta"] = metadata

    def end_timer(self, operation: str, metadata: Optional[Dict[str, Any]] = None) -> float:
        """
        타이머 종료 및 기록

        Args:
            operation: 작업 이름
            metadata: 추가 정보 (종료 시점에 추가할 데이터)

        Returns:
            실행 시간 (초)
        """
        if not self.enabled:
            return 0.0

        timer_key = f"{operation}_{len(self.timings)}"

        if timer_key not in self.active_timers:
            logger.warning(f"Timer not found: {timer_key}")
            return 0.0

        start_time = self.active_timers.pop(timer_key)
        end_time = time.time()
        duration = end_time - start_time

        # 시작 시점 metadata 가져오기
        start_metadata = self.active_timers.pop(f"{timer_key}_meta", {})

        # 종료 시점 metadata 병합
        if metadata:
            start_metadata.update(metadata)

        # 기록 저장
        record = TimingRecord(
            operation=operation,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            metadata=start_metadata
        )
        self.timings.append(record)

        return duration

    def get_summary(self) -> Dict[str, Any]:
        """
        프로파일링 요약

        Returns:
            {
                'total_time': float,
                'breakdown': {
                    'operation_name': {
                        'count': int,
                        'total_time': float,
                        'avg_time': float,
                        'min_time': float,
                        'max_time': float
                    }
                },
                'bottlenecks': List[str],  # 가장 느린 작업들
                'details': List[Dict]  # 전체 타이밍 상세
            }
        """
        if not self.enabled or not self.session_start:
            return {}

        total_time = time.time() - self.session_start

        # Operation별 통계
        breakdown = defaultdict(lambda: {
            'count': 0,
            'total_time': 0.0,
            'times': []
        })

        for record in self.timings:
            stats = breakdown[record.operation]
            stats['count'] += 1
            stats['total_time'] += record.duration
            stats['times'].append(record.duration)

        # 통계 계산
        for op, stats in breakdown.items():
            times = stats.pop('times')
            stats['avg_time'] = stats['total_time'] / stats['count']
            stats['min_time'] = min(times)
            stats['max_time'] = max(times)
            stats['percentage'] = (stats['total_time'] / total_time) * 100

        # Bottleneck 식별 (전체 시간의 20% 이상 차지하는 작업)
        bottlenecks = [
            f"{op} ({stats['percentage']:.1f}%)"
            for op, stats in breakdown.items()
            if stats['percentage'] >= 20.0
        ]

        # 상세 타이밍 (큰 순서대로)
        details = sorted(
            [
                {
                    'operation': r.operation,
                    'duration_ms': round(r.duration_ms, 2),
                    'metadata': r.metadata
                }
                for r in self.timings
            ],
            key=lambda x: x['duration_ms'],
            reverse=True
        )[:10]  # 상위 10개만

        return {
            'total_time': round(total_time, 3),
            'total_time_ms': round(total_time * 1000, 2),
            'breakdown': {
                op: {
                    'count': stats['count'],
                    'total_time': round(stats['total_time'], 3),
                    'avg_time': round(stats['avg_time'], 3),
                    'min_time': round(stats['min_time'], 3),
                    'max_time': round(stats['max_time'], 3),
                    'percentage': round(stats['percentage'], 2)
                }
                for op, stats in breakdown.items()
            },
            'bottlenecks': bottlenecks,
            'top_slowest': details
        }

    def log_summary(self):
        """프로파일링 요약을 로그로 출력"""
        if not self.enabled:
            return

        summary = self.get_summary()

        if not summary:
            return

        logger.info("=" * 60)
        logger.info(f"⏱️  Performance Profile: {summary['total_time_ms']:.2f}ms")
        logger.info("=" * 60)

        # Breakdown
        logger.info("\n📊 Time Breakdown:")
        for op, stats in sorted(
            summary['breakdown'].items(),
            key=lambda x: x[1]['total_time'],
            reverse=True
        ):
            logger.info(
                f"  {op:30s}: {stats['total_time']*1000:6.2f}ms "
                f"({stats['percentage']:5.1f}%) "
                f"[count={stats['count']}, avg={stats['avg_time']*1000:.2f}ms]"
            )

        # Bottlenecks
        if summary['bottlenecks']:
            logger.info("\n🔴 Bottlenecks (>20% of total time):")
            for bottleneck in summary['bottlenecks']:
                logger.info(f"  • {bottleneck}")

        # Top slowest operations
        logger.info("\n🐌 Top 10 Slowest Operations:")
        for i, detail in enumerate(summary['top_slowest'], 1):
            meta_str = json.dumps(detail['metadata'], ensure_ascii=False)
            logger.info(f"  {i}. {detail['operation']}: {detail['duration_ms']:.2f}ms - {meta_str}")

        logger.info("=" * 60)

    def get_optimization_suggestions(self) -> List[str]:
        """
        최적화 제안

        Returns:
            최적화 가능한 부분에 대한 제안 리스트
        """
        if not self.enabled:
            return []

        summary = self.get_summary()
        suggestions = []

        breakdown = summary.get('breakdown', {})

        # LLM 호출이 많은 경우
        if 'llm_call' in breakdown:
            llm_stats = breakdown['llm_call']
            if llm_stats['percentage'] > 40:
                suggestions.append(
                    f"LLM 호출이 전체 시간의 {llm_stats['percentage']:.1f}%를 차지합니다. "
                    "ReAct loop 최적화 또는 tool 선택 개선이 필요합니다."
                )

        # Tool 실행이 많은 경우
        if 'tool_execution' in breakdown:
            tool_stats = breakdown['tool_execution']
            if tool_stats['count'] > 3:
                suggestions.append(
                    f"Tool 실행 횟수가 {tool_stats['count']}회입니다. "
                    "캐싱 또는 병렬 실행을 고려하세요."
                )
            if tool_stats['percentage'] > 30:
                suggestions.append(
                    f"Tool 실행이 전체 시간의 {tool_stats['percentage']:.1f}%를 차지합니다. "
                    "병렬 실행 또는 인덱스 최적화가 필요합니다."
                )

        # 문서 처리가 느린 경우
        if 'document_compile' in breakdown:
            doc_stats = breakdown['document_compile']
            if doc_stats['percentage'] > 15:
                suggestions.append(
                    f"문서 컴파일이 전체 시간의 {doc_stats['percentage']:.1f}%를 차지합니다. "
                    "중복 제거 알고리즘 최적화가 필요합니다."
                )

        return suggestions
