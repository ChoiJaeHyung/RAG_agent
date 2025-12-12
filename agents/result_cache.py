"""
Result Cache for Tool Execution

Tool 실행 결과 캐싱으로 성능 최적화:
- 동일한 쿼리에 대한 중복 검색 방지
- 세션별 캐시 관리
- LRU 기반 메모리 제한
"""

from typing import Dict, Any, Optional, List, Tuple
import hashlib
import json
import time
from collections import OrderedDict
from utils.logger import logger


class ResultCache:
    """
    Tool 실행 결과 캐싱

    Features:
    - 세션별 캐시 격리
    - LRU eviction policy
    - TTL (Time To Live) 지원
    - 캐시 적중률 추적
    """

    def __init__(
        self,
        max_size: int = 100,
        default_ttl: int = 3600  # 1 hour
    ):
        """
        Args:
            max_size: 최대 캐시 항목 수 (LRU)
            default_ttl: 기본 TTL (초)
        """
        self.max_size = max_size
        self.default_ttl = default_ttl

        # Session별 캐시: {session_id: OrderedDict}
        self.session_caches: Dict[str, OrderedDict] = {}

        # 통계
        self.stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0
        }

    def _generate_cache_key(
        self,
        tool_name: str,
        tool_args: Dict[str, Any]
    ) -> str:
        """
        캐시 키 생성

        Args:
            tool_name: 도구 이름
            tool_args: 도구 인자

        Returns:
            캐시 키 (tool_name + args hash)
        """
        # Args를 정규화 (순서 무관)
        normalized = json.dumps(tool_args, sort_keys=True, ensure_ascii=False)

        # Hash 생성
        args_hash = hashlib.md5(normalized.encode()).hexdigest()[:16]

        return f"{tool_name}:{args_hash}"

    def get(
        self,
        session_id: str,
        tool_name: str,
        tool_args: Dict[str, Any]
    ) -> Optional[Tuple[List[Dict], bool]]:
        """
        캐시에서 결과 조회

        Args:
            session_id: 세션 ID
            tool_name: 도구 이름
            tool_args: 도구 인자

        Returns:
            (결과, 성공 여부) 또는 None (캐시 미스)
        """
        cache_key = self._generate_cache_key(tool_name, tool_args)

        # 세션 캐시 확인
        if session_id not in self.session_caches:
            self.stats['misses'] += 1
            return None

        session_cache = self.session_caches[session_id]

        # 캐시 항목 확인
        if cache_key not in session_cache:
            self.stats['misses'] += 1
            return None

        cache_entry = session_cache[cache_key]

        # TTL 확인
        if time.time() > cache_entry['expires_at']:
            # 만료된 항목 제거
            del session_cache[cache_key]
            self.stats['misses'] += 1
            logger.debug(f"🕒 Cache expired: {cache_key}")
            return None

        # LRU: 최근 사용으로 이동
        session_cache.move_to_end(cache_key)

        self.stats['hits'] += 1
        logger.info(f"✨ Cache HIT: {tool_name} (saved {cache_entry['execution_time']:.2f}s)")

        return cache_entry['result'], cache_entry['success']

    def set(
        self,
        session_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: List[Dict],
        success: bool,
        execution_time: float,
        ttl: Optional[int] = None
    ):
        """
        캐시에 결과 저장

        Args:
            session_id: 세션 ID
            tool_name: 도구 이름
            tool_args: 도구 인자
            result: 실행 결과
            success: 성공 여부
            execution_time: 실행 시간
            ttl: TTL (초), None이면 기본값 사용
        """
        cache_key = self._generate_cache_key(tool_name, tool_args)

        # 세션 캐시 초기화
        if session_id not in self.session_caches:
            self.session_caches[session_id] = OrderedDict()

        session_cache = self.session_caches[session_id]

        # LRU: 최대 크기 초과 시 가장 오래된 항목 제거
        if len(session_cache) >= self.max_size and cache_key not in session_cache:
            oldest_key, oldest_entry = session_cache.popitem(last=False)
            self.stats['evictions'] += 1
            logger.debug(f"🗑️  Cache evicted (LRU): {oldest_key}")

        # 캐시 항목 저장
        ttl = ttl or self.default_ttl
        cache_entry = {
            'result': result,
            'success': success,
            'execution_time': execution_time,
            'cached_at': time.time(),
            'expires_at': time.time() + ttl
        }

        session_cache[cache_key] = cache_entry
        logger.debug(f"💾 Cache SET: {tool_name} (TTL={ttl}s)")

    def clear_session(self, session_id: str):
        """
        특정 세션의 캐시 클리어

        Args:
            session_id: 세션 ID
        """
        if session_id in self.session_caches:
            count = len(self.session_caches[session_id])
            del self.session_caches[session_id]
            logger.info(f"🧹 Cache cleared for session {session_id} ({count} items)")

    def clear_all(self):
        """모든 캐시 클리어"""
        total_items = sum(len(cache) for cache in self.session_caches.values())
        self.session_caches.clear()
        logger.info(f"🧹 All cache cleared ({total_items} items)")

    def get_stats(self) -> Dict[str, Any]:
        """
        캐시 통계

        Returns:
            {
                'hits': int,
                'misses': int,
                'evictions': int,
                'hit_rate': float,
                'total_items': int,
                'sessions': int
            }
        """
        total_requests = self.stats['hits'] + self.stats['misses']
        hit_rate = (
            self.stats['hits'] / total_requests
            if total_requests > 0
            else 0.0
        )

        total_items = sum(
            len(cache) for cache in self.session_caches.values()
        )

        return {
            'hits': self.stats['hits'],
            'misses': self.stats['misses'],
            'evictions': self.stats['evictions'],
            'hit_rate': round(hit_rate, 3),
            'total_requests': total_requests,
            'total_items': total_items,
            'sessions': len(self.session_caches)
        }

    def log_stats(self):
        """캐시 통계 로그 출력"""
        stats = self.get_stats()

        logger.info("=" * 60)
        logger.info("💾 Cache Statistics")
        logger.info("=" * 60)
        logger.info(f"  Hit Rate:      {stats['hit_rate']:.1%} ({stats['hits']}/{stats['total_requests']})")
        logger.info(f"  Misses:        {stats['misses']}")
        logger.info(f"  Evictions:     {stats['evictions']}")
        logger.info(f"  Total Items:   {stats['total_items']}")
        logger.info(f"  Sessions:      {stats['sessions']}")
        logger.info("=" * 60)

    def should_cache(
        self,
        tool_name: str,
        result: List[Dict],
        success: bool
    ) -> bool:
        """
        캐싱 여부 판단

        Args:
            tool_name: 도구 이름
            result: 실행 결과
            success: 성공 여부

        Returns:
            캐싱 여부
        """
        # 실패한 결과는 캐싱하지 않음
        if not success:
            return False

        # 빈 결과는 캐싱하지 않음 (다음에 다른 결과가 나올 수 있음)
        if not result or len(result) == 0:
            return False

        # 캐싱 대상 tool
        cacheable_tools = [
            'search_qdrant_semantic',
            'search_qdrant_by_error_code',
            'search_mariadb_by_keyword',
            'search_elasticsearch_bm25'
        ]

        if tool_name not in cacheable_tools:
            return False

        return True


# Global cache instance (세션별로 관리됨)
result_cache = ResultCache(max_size=100, default_ttl=3600)
