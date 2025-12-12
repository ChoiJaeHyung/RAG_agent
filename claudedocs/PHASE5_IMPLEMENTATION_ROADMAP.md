# Phase 5 개선 로드맵 구현 가이드

**작성일**: 2025-11-12
**목표**: 응답 시간 22.78s → 6s (73% 단축)
**최신 기술 활용**: 2024-2025 최신 라이브러리 및 패턴

---

## 📋 Executive Summary

Phase 4 분석 결과를 바탕으로 3단계 개선 로드맵을 최신 기술 스택으로 구현합니다.

### 개선 단계별 목표

| 단계 | 구현 내용 | 예상 개선 | 목표 시간 | 구현 기간 |
|-----|----------|---------|---------|---------|
| **Step 1** | 캐시 확대 + 조기 종료 | 30% | 15.9s | 1주 |
| **Step 2** | 답변 최적화 + Rule-based | 56% | 12.9s | 2주 |
| **Step 3** | 병렬 실행 + 고급 최적화 | 72% | 6.0s | 1개월 |

---

## 🔧 Step 1: 캐시 확대 + 조기 종료 (1주)

### 목표
- 캐시 적중률: 20.6% → 40%+
- 평균 Iteration: 5회 → 3회
- 예상 응답 시간: 22.78s → 15.9s (30% 개선)

---

### 1.1 Redis 기반 분산 캐시 (최신 기술)

**현재 문제점**:
- 메모리 기반 OrderedDict (프로세스 재시작 시 손실)
- 단일 프로세스 내에서만 캐시 공유
- 캐시 적중률 20.6% (낮음)

**최신 솔루션**: **Redis Stack + RedisJSON + RediSearch**

#### 기술 선택 이유
```yaml
Redis Stack (2024):
  - RedisJSON: 네이티브 JSON 지원, 복잡한 문서 구조 저장
  - RediSearch: 캐시 키 검색 및 유사 쿼리 매칭
  - Redis Bloom: 캐시 존재 여부 빠른 확인 (False Positive 최소화)
  - Redis TimeSeries: 캐시 히트율 실시간 모니터링

대안 고려:
  - Memcached: JSON 구조 지원 부족 ❌
  - DragonflyDB: Redis 호환, 10배 빠름, 하지만 안정성 검증 중 ⚠️
  - KeyDB: Redis 포크, Multi-thread, 고려 가능 ✅
```

#### 구현 코드

**requirements.txt 추가**:
```python
# Cache (최신 버전)
redis==5.0.1           # 2024년 최신, async 지원 강화
hiredis==2.3.2         # C 기반 파서, 10배 빠른 직렬화
redis-om==0.2.1        # ORM-like interface, Pydantic 통합
```

**agents/distributed_cache.py** (새 파일):
```python
"""
Distributed Result Cache with Redis Stack

Features:
- RedisJSON for complex document storage
- Semantic cache key matching with RediSearch
- Bloom filter for fast existence checks
- TTL with intelligent expiration
- Session-based namespacing
"""

from typing import Dict, Any, Optional, List, Tuple
import json
import hashlib
import time
from redis import Redis
from redis.commands.json.path import Path
from redis.commands.search.query import Query
from redis.commands.search.field import TextField, NumericField
from redis.commands.search.indexDefinition import IndexDefinition, IndexType
from utils.logger import logger
import asyncio
from functools import lru_cache


class DistributedCache:
    """Redis-based distributed cache with semantic matching."""

    def __init__(
        self,
        host: str = 'localhost',
        port: int = 6379,
        db: int = 0,
        default_ttl: int = 3600,
        max_memory: str = '2gb',
        eviction_policy: str = 'allkeys-lru'
    ):
        """
        Args:
            host: Redis 호스트
            port: Redis 포트
            db: Redis DB 번호
            default_ttl: 기본 만료 시간 (초)
            max_memory: 최대 메모리 (Redis config)
            eviction_policy: 제거 정책 (allkeys-lru 권장)
        """
        self.default_ttl = default_ttl

        # Redis 연결 (connection pool 자동 관리)
        self.redis = Redis(
            host=host,
            port=port,
            db=db,
            decode_responses=False,  # bytes로 받아서 직접 제어
            max_connections=50,      # Connection pool size
            socket_keepalive=True,
            socket_connect_timeout=5,
            retry_on_timeout=True
        )

        # Redis 설정 최적화
        self.redis.config_set('maxmemory', max_memory)
        self.redis.config_set('maxmemory-policy', eviction_policy)

        # RediSearch 인덱스 생성 (캐시 키 검색용)
        self._create_search_index()

        # Bloom filter 초기화 (빠른 존재 여부 확인)
        self.bloom_key = 'cache:bloom'
        try:
            self.redis.execute_command('BF.RESERVE', self.bloom_key, 0.01, 100000)
        except:
            pass  # 이미 존재하면 무시

        # 통계
        self.stats = {
            'hits': 0,
            'misses': 0,
            'semantic_matches': 0
        }

        logger.info(f"✓ DistributedCache initialized: {host}:{port}")

    def _create_search_index(self):
        """RediSearch 인덱스 생성 (캐시 키 검색 및 유사 쿼리 매칭)."""
        try:
            # 인덱스 정의
            schema = (
                TextField('$.tool_name', as_name='tool_name'),
                TextField('$.query_text', as_name='query_text'),
                NumericField('$.timestamp', as_name='timestamp'),
                NumericField('$.hit_count', as_name='hit_count')
            )

            definition = IndexDefinition(
                prefix=['cache:key:'],
                index_type=IndexType.JSON
            )

            # 인덱스 생성
            self.redis.ft('cache_idx').create_index(
                schema,
                definition=definition
            )
            logger.info("✓ RediSearch index created for cache")
        except Exception as e:
            if 'Index already exists' not in str(e):
                logger.warning(f"Failed to create search index: {e}")

    def _generate_cache_key(
        self,
        session_id: str,
        tool_name: str,
        tool_args: Dict[str, Any]
    ) -> str:
        """
        캐시 키 생성 (세션별 네임스페이스).

        Returns:
            cache:key:{session_id}:{tool_name}:{args_hash}
        """
        # Args 정규화 (순서 무관)
        normalized = json.dumps(tool_args, sort_keys=True, ensure_ascii=False)
        args_hash = hashlib.md5(normalized.encode()).hexdigest()[:16]

        return f"cache:key:{session_id}:{tool_name}:{args_hash}"

    def _bloom_check(self, cache_key: str) -> bool:
        """Bloom filter로 빠른 존재 여부 확인 (False Positive 가능)."""
        try:
            exists = self.redis.execute_command('BF.EXISTS', self.bloom_key, cache_key)
            return bool(exists)
        except:
            return True  # Bloom 실패 시 실제 조회 시도

    def _bloom_add(self, cache_key: str):
        """Bloom filter에 키 추가."""
        try:
            self.redis.execute_command('BF.ADD', self.bloom_key, cache_key)
        except Exception as e:
            logger.debug(f"Bloom add failed: {e}")

    async def get(
        self,
        session_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        semantic_match: bool = True
    ) -> Optional[Tuple[List[Dict], bool]]:
        """
        캐시에서 결과 조회 (semantic matching 지원).

        Args:
            session_id: 세션 ID
            tool_name: 도구 이름
            tool_args: 도구 인자
            semantic_match: 유사 쿼리 매칭 활성화

        Returns:
            (결과, 성공 여부) 또는 None
        """
        cache_key = self._generate_cache_key(session_id, tool_name, tool_args)

        # Bloom filter 빠른 체크
        if not self._bloom_check(cache_key):
            self.stats['misses'] += 1
            return None

        # Redis에서 조회
        try:
            cache_data = self.redis.json().get(cache_key)

            if cache_data:
                # TTL 확인
                if time.time() > cache_data.get('expires_at', 0):
                    self.redis.delete(cache_key)
                    self.stats['misses'] += 1
                    logger.debug(f"🕒 Cache expired: {cache_key}")
                    return None

                # 히트 카운트 증가
                self.redis.json().numincrby(cache_key, Path('.hit_count'), 1)

                self.stats['hits'] += 1
                exec_time = cache_data.get('execution_time', 0)
                logger.info(f"✨ Cache HIT: {tool_name} (saved {exec_time:.2f}s)")

                return cache_data['result'], cache_data['success']

            # Semantic matching 시도 (query_text 유사도 검색)
            if semantic_match and 'query' in tool_args:
                similar_result = await self._semantic_match(
                    session_id, tool_name, tool_args.get('query', '')
                )
                if similar_result:
                    self.stats['semantic_matches'] += 1
                    logger.info(f"🔍 Semantic cache match: {tool_name}")
                    return similar_result

            self.stats['misses'] += 1
            return None

        except Exception as e:
            logger.error(f"Cache get error: {e}")
            self.stats['misses'] += 1
            return None

    async def _semantic_match(
        self,
        session_id: str,
        tool_name: str,
        query_text: str,
        threshold: float = 0.85
    ) -> Optional[Tuple[List[Dict], bool]]:
        """
        RediSearch로 유사 쿼리 매칭.

        Args:
            session_id: 세션 ID
            tool_name: 도구 이름
            query_text: 검색 쿼리
            threshold: 유사도 임계값 (0~1)

        Returns:
            유사한 캐시 결과 또는 None
        """
        try:
            # RediSearch 쿼리 (같은 세션 + 같은 도구 + 유사 쿼리)
            search_query = Query(f"@tool_name:{tool_name} {query_text}") \
                .return_fields('$') \
                .sort_by('hit_count', asc=False) \
                .paging(0, 1)

            results = self.redis.ft('cache_idx').search(search_query)

            if results.total > 0:
                doc = results.docs[0]
                cache_data = json.loads(doc['$'])

                # 유사도 체크 (간단한 Jaccard similarity)
                similarity = self._calculate_similarity(
                    query_text,
                    cache_data.get('query_text', '')
                )

                if similarity >= threshold:
                    logger.info(f"Semantic match similarity: {similarity:.2f}")
                    return cache_data['result'], cache_data['success']

            return None

        except Exception as e:
            logger.debug(f"Semantic match failed: {e}")
            return None

    @lru_cache(maxsize=1000)
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Jaccard similarity (단어 기반)."""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union)

    async def set(
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
        캐시에 결과 저장 (RedisJSON 사용).

        Args:
            session_id: 세션 ID
            tool_name: 도구 이름
            tool_args: 도구 인자
            result: 실행 결과
            success: 성공 여부
            execution_time: 실행 시간
            ttl: TTL (초)
        """
        cache_key = self._generate_cache_key(session_id, tool_name, tool_args)
        ttl = ttl or self._get_smart_ttl(tool_name, tool_args)

        # 캐시 데이터 구성
        cache_data = {
            'tool_name': tool_name,
            'query_text': tool_args.get('query', ''),
            'result': result,
            'success': success,
            'execution_time': execution_time,
            'cached_at': time.time(),
            'expires_at': time.time() + ttl,
            'hit_count': 0,
            'timestamp': time.time()
        }

        try:
            # RedisJSON으로 저장
            self.redis.json().set(cache_key, Path.root_path(), cache_data)

            # TTL 설정
            self.redis.expire(cache_key, ttl)

            # Bloom filter에 추가
            self._bloom_add(cache_key)

            logger.debug(f"💾 Cache SET: {tool_name} (TTL={ttl}s)")

        except Exception as e:
            logger.error(f"Cache set error: {e}")

    def _get_smart_ttl(self, tool_name: str, tool_args: Dict[str, Any]) -> int:
        """
        도구 타입과 쿼리 특성에 따라 지능적 TTL 결정.

        전략:
        - 에러코드 검색: 2시간 (자주 검색됨)
        - 프로젝트 검색: 30분 (자주 변경됨)
        - 일반 검색: 1시간
        """
        if tool_name == 'search_mariadb_by_error_code':
            return 7200  # 2시간
        elif tool_name == 'search_mariadb_by_project':
            return 1800  # 30분
        elif 'semantic' in tool_name:
            # 쿼리 길이 기반 (긴 쿼리 = 구체적 = 오래 보관)
            query_len = len(tool_args.get('query', ''))
            if query_len > 50:
                return 7200  # 2시간
            else:
                return 3600  # 1시간
        else:
            return self.default_ttl

    def clear_session(self, session_id: str):
        """세션별 캐시 클리어."""
        pattern = f"cache:key:{session_id}:*"

        cursor = 0
        count = 0
        while True:
            cursor, keys = self.redis.scan(cursor, match=pattern, count=100)
            if keys:
                self.redis.delete(*keys)
                count += len(keys)
            if cursor == 0:
                break

        logger.info(f"🧹 Cache cleared for session {session_id} ({count} items)")

    def get_stats(self) -> Dict[str, Any]:
        """캐시 통계."""
        total_requests = self.stats['hits'] + self.stats['misses']
        hit_rate = (
            self.stats['hits'] / total_requests
            if total_requests > 0
            else 0.0
        )

        # Redis 메모리 정보
        info = self.redis.info('memory')

        return {
            'hits': self.stats['hits'],
            'misses': self.stats['misses'],
            'semantic_matches': self.stats['semantic_matches'],
            'hit_rate': round(hit_rate, 3),
            'total_requests': total_requests,
            'memory_used': info.get('used_memory_human', 'N/A'),
            'memory_peak': info.get('used_memory_peak_human', 'N/A')
        }


# Global instance
distributed_cache = DistributedCache()
```

#### Docker Compose 설정

**docker-compose.yml** (프로젝트 루트):
```yaml
version: '3.8'

services:
  redis-stack:
    image: redis/redis-stack:latest  # Redis Stack (JSON, Search, Bloom 포함)
    container_name: rag_redis_cache
    ports:
      - "6379:6379"      # Redis
      - "8001:8001"      # RedisInsight (GUI)
    volumes:
      - redis_data:/data
    environment:
      - REDIS_ARGS=--maxmemory 2gb --maxmemory-policy allkeys-lru
    command: >
      redis-stack-server
      --loadmodule /opt/redis-stack/lib/redisearch.so
      --loadmodule /opt/redis-stack/lib/rejson.so
      --loadmodule /opt/redis-stack/lib/redisbloom.so
    restart: unless-stopped

volumes:
  redis_data:
    driver: local
```

#### 통합 코드

**agents/search_agent.py** 수정:
```python
# 기존
from agents.result_cache import result_cache

# 변경
from agents.distributed_cache import distributed_cache

# Tool 실행 전
cached_result = await distributed_cache.get(
    session_id=self.session_id,
    tool_name=tool_name,
    tool_args=tool_args,
    semantic_match=True  # 유사 쿼리 매칭 활성화
)

# Tool 실행 후
await distributed_cache.set(
    session_id=self.session_id,
    tool_name=tool_name,
    tool_args=tool_args,
    result=result_docs,
    success=success,
    execution_time=execution_time
)
```

#### 예상 효과
```
현재 캐시 적중률: 20.6%
개선 후 예상:
  - Exact match: 30%
  - Semantic match: 15%
  - 총 적중률: 45%+

캐시 히트 시 시간 단축:
  - 17s → 0.001s (99.99% 개선)

전체 평균 개선:
  - 45% × 99.99% = 평균 30% 시간 단축
```

---

### 1.2 조기 종료 강화 (Early Stopping)

**현재 문제점**:
- 평균 5회 Iteration (과도한 LLM 호출)
- 충분한 문서 수집 후에도 계속 검색

**개선 전략**: **Rule-based Early Stopping + Confidence Threshold**

#### 구현 코드

**agents/early_stopping.py** (새 파일):
```python
"""
Early Stopping Strategy for ReAct Loop

Strategies:
1. Document Sufficiency Check
2. Confidence Threshold
3. Tool-specific Rules
4. Diminishing Returns Detection
"""

from typing import List, Dict, Any
from utils.logger import logger


class EarlyStoppingStrategy:
    """조기 종료 전략."""

    def __init__(
        self,
        min_docs: int = 10,
        target_docs: int = 20,
        confidence_threshold: float = 0.8,
        relevance_threshold: float = 0.7
    ):
        self.min_docs = min_docs
        self.target_docs = target_docs
        self.confidence_threshold = confidence_threshold
        self.relevance_threshold = relevance_threshold

    def should_stop(
        self,
        iteration: int,
        collected_docs: List[Dict],
        last_tool: str,
        last_result: List[Dict],
        avg_relevance: float
    ) -> tuple[bool, str]:
        """
        조기 종료 여부 판단.

        Returns:
            (종료 여부, 종료 사유)
        """
        # 1. 에러코드 검색 성공 시 즉시 종료
        if last_tool == 'search_mariadb_by_error_code' and len(last_result) > 0:
            logger.info("✅ 에러코드 검색 성공 → 즉시 종료")
            return True, "error_code_found"

        # 2. 충분한 고품질 문서 확보
        if len(collected_docs) >= self.target_docs and avg_relevance >= self.relevance_threshold:
            logger.info(f"✅ 충분한 문서 확보 ({len(collected_docs)}개, 관련성 {avg_relevance:.2f}) → 조기 종료")
            return True, "sufficient_high_quality_docs"

        # 3. Minimum 문서 확보 + 높은 신뢰도
        if len(collected_docs) >= self.min_docs and avg_relevance >= self.confidence_threshold:
            logger.info(f"✅ 최소 문서 + 높은 신뢰도 → 조기 종료")
            return True, "min_docs_high_confidence"

        # 4. 최근 검색이 결과 없음 (Diminishing Returns)
        if iteration > 2 and len(last_result) == 0:
            if len(collected_docs) >= self.min_docs:
                logger.info("⚠️ 추가 검색 결과 없음 + 최소 문서 확보 → 조기 종료")
                return True, "diminishing_returns"

        # 5. Iteration 제한 도달 전 문서 충분
        if iteration >= 3 and len(collected_docs) >= self.min_docs:
            logger.info(f"⏱️ Iteration {iteration}, 최소 문서 확보 → 조기 종료")
            return True, "iteration_limit_with_min_docs"

        # 계속 진행
        return False, ""

    def get_next_tool_suggestion(
        self,
        query: str,
        collected_docs: List[Dict],
        used_tools: List[str]
    ) -> Optional[str]:
        """
        다음 도구 제안 (Rule-based).

        Returns:
            도구 이름 또는 None (LLM에게 위임)
        """
        # 에러코드 패턴
        import re
        error_code_pattern = r'\b\d{5}\b|\bRCXERR_\w+\b'

        if re.search(error_code_pattern, query):
            if 'search_mariadb_by_error_code' not in used_tools:
                return 'search_mariadb_by_error_code'

        # 제품명 패턴
        brands = ['RemoteView', 'RemoteCall', 'RemoteMeeting', 'RemoteWOL']
        query_lower = query.lower()

        for brand in brands:
            if brand.lower() in query_lower:
                if 'search_mariadb_by_brand' not in used_tools:
                    return 'search_mariadb_by_brand'

        # 기본: semantic search
        if 'search_qdrant_semantic' not in used_tools:
            return 'search_qdrant_semantic'

        # LLM에게 위임
        return None


# Global instance
early_stopping = EarlyStoppingStrategy()
```

#### SearchAgent 통합

**agents/search_agent.py** 수정:
```python
from agents.early_stopping import early_stopping

# ReAct loop 내부
for iteration in range(1, max_iterations + 1):
    # 조기 종료 체크
    if iteration > 1:
        should_stop, reason = early_stopping.should_stop(
            iteration=iteration,
            collected_docs=collected_docs,
            last_tool=last_tool_name,
            last_result=last_result_docs,
            avg_relevance=self._calculate_avg_relevance(collected_docs)
        )

        if should_stop:
            logger.info(f"🛑 Early stopping: {reason}")
            self.decision_logger.log_early_stop(iteration, reason)
            break

    # Tool 선택 (Rule-based 우선)
    suggested_tool = early_stopping.get_next_tool_suggestion(
        query=resolved_query,
        collected_docs=collected_docs,
        used_tools=[log['tool_name'] for log in self.decision_logger.decision_log]
    )

    if suggested_tool:
        logger.info(f"📍 Rule-based tool selection: {suggested_tool}")
        tool_name = suggested_tool
        tool_args = self._build_tool_args(suggested_tool, resolved_query)
    else:
        # LLM에게 도구 선택 위임
        decision = self._get_agent_decision(...)
        tool_name = decision['tool_name']
        tool_args = decision['tool_args']
```

#### 예상 효과
```
현재 평균 Iteration: 5회
개선 후 예상:
  - 에러코드 질문: 1회 (즉시 종료)
  - 일반 질문: 2-3회 (조기 종료)
  - 복잡한 질문: 4회

평균 Iteration: 2.5회 (50% 감소)

LLM 호출 감소:
  - 5회 → 2.5회 (50% 감소)
  - 시간: 9.4s → 4.7s
```

---

## 🚀 Step 2: 답변 생성 최적화 + Rule-based 도구 선택 (2주)

### 목표
- 답변 생성 시간: 12.89s → 9.0s (30% 개선)
- LLM 호출 횟수: 5회 → 2.5회 (50% 감소)
- 예상 응답 시간: 15.9s → 12.9s (추가 19% 개선)

---

### 2.1 LLM 프롬프트 최적화 (최신 기술)

**현재 문제점**:
- 답변 생성이 전체 시간의 56.6% 차지 (12.89s)
- 긴 프롬프트, 불필요한 예시 포함
- 모든 질문에 동일한 컨텍스트 크기 사용

**최신 솔루션**: **DSPy + 프롬프트 최적화**

#### 기술 선택 이유
```yaml
DSPy (2024 Stanford):
  장점:
    - 프롬프트 자동 최적화 (MIPRO, BootstrapFewShot)
    - 체계적 프롬프트 엔지니어링 (선언적 프로그래밍)
    - 메트릭 기반 자동 튜닝
  단점:
    - 학습 곡선 존재
    - 초기 설정 복잡

대안:
  - LangChain PromptTemplate: 간단하지만 최적화 부족 ⚠️
  - Guidance (Microsoft): 구조화된 출력, 고려 가능 ✅
  - 수동 최적화: 빠르지만 체계적이지 않음 ⚠️
```

#### 구현 코드

**requirements.txt 추가**:
```python
# Prompt Optimization (최신)
dspy-ai==2.4.9         # 2024 최신, 프롬프트 자동 최적화
guidance==0.1.14       # Microsoft, 구조화된 LLM 출력
```

**agents/optimized_prompts.py** (새 파일):
```python
"""
Optimized Prompts with DSPy

Features:
- Question-type specific prompts
- Dynamic context sizing
- Automatic prompt optimization with MIPRO
"""

import dspy
from typing import Dict, Any, List
from utils.logger import logger


class AnswerGenerator(dspy.Signature):
    """DSPy Signature for answer generation."""

    question: str = dspy.InputField(desc="사용자 질문")
    documents: str = dspy.InputField(desc="검색된 관련 문서")
    question_type: str = dspy.InputField(desc="질문 타입 (error_code, how_to, etc)")
    context: str = dspy.InputField(desc="대화 문맥 (있을 경우)")

    answer: str = dspy.OutputField(desc="자연스럽고 정확한 답변")
    confidence: float = dspy.OutputField(desc="답변 신뢰도 (0-1)")


class OptimizedAnswerGenerator:
    """질문 타입별 최적화된 답변 생성기."""

    def __init__(self, model_name: str = "gpt-4"):
        # DSPy LM 초기화
        self.lm = dspy.OpenAI(model=model_name, max_tokens=2000)
        dspy.settings.configure(lm=self.lm)

        # Chain of Thought 모듈
        self.cot = dspy.ChainOfThought(AnswerGenerator)

        # 질문 타입별 최적화된 프롬프트
        self.prompts = {
            'error_code': self._get_error_code_prompt(),
            'how_to': self._get_how_to_prompt(),
            'troubleshooting': self._get_troubleshooting_prompt(),
            'general': self._get_general_prompt()
        }

    def _get_error_code_prompt(self) -> str:
        """에러코드 질문용 간결한 프롬프트."""
        return """에러코드에 대해 간결하게 답변하세요:
1. 에러 의미 (1줄)
2. 발생 원인 (1-2줄)
3. 해결 방법 (2-3줄)

문서에 없는 내용은 추측하지 마세요."""

    def _get_how_to_prompt(self) -> str:
        """사용 방법 질문용 상세 프롬프트."""
        return """기능 사용 방법을 단계별로 설명하세요:
1. 기능 개요 (1-2줄)
2. 상세 절차 (단계별 번호)
3. 주의사항 (있을 경우)

문서 내용을 기반으로만 답변하세요."""

    def _get_troubleshooting_prompt(self) -> str:
        """문제 해결 질문용 프롬프트."""
        return """문제 해결 방법을 체계적으로 제시하세요:
1. 문제 진단
2. 해결 단계 (우선순위순)
3. 추가 확인 사항

문서에 근거한 방법만 제시하세요."""

    def _get_general_prompt(self) -> str:
        """일반 질문용 프롬프트."""
        return """질문에 정확하고 자연스럽게 답변하세요.
문서에 없는 내용은 "문서에서 확인되지 않습니다"라고 명시하세요."""

    def generate(
        self,
        question: str,
        documents: List[Dict],
        question_type: str = 'general',
        context: str = ''
    ) -> Dict[str, Any]:
        """
        최적화된 답변 생성.

        Args:
            question: 사용자 질문
            documents: 검색 문서 리스트
            question_type: 질문 타입
            context: 대화 문맥

        Returns:
            {
                'answer': str,
                'confidence': float,
                'tokens_used': int
            }
        """
        # 문서 압축 (질문 타입별 다른 크기)
        doc_text = self._compress_documents(documents, question_type)

        # DSPy로 답변 생성
        try:
            result = self.cot(
                question=question,
                documents=doc_text,
                question_type=question_type,
                context=context or '없음'
            )

            return {
                'answer': result.answer,
                'confidence': float(result.confidence) if hasattr(result, 'confidence') else 0.8,
                'tokens_used': self.lm.history[-1]['usage']['total_tokens'] if self.lm.history else 0
            }

        except Exception as e:
            logger.error(f"Answer generation failed: {e}")
            return {
                'answer': '답변 생성 중 오류가 발생했습니다.',
                'confidence': 0.0,
                'tokens_used': 0
            }

    def _compress_documents(
        self,
        documents: List[Dict],
        question_type: str
    ) -> str:
        """
        질문 타입별 문서 압축 전략.

        - error_code: 최대 3개 문서, 각 200자
        - how_to: 최대 5개 문서, 각 400자
        - troubleshooting: 최대 5개 문서, 각 400자
        - general: 최대 10개 문서, 각 300자
        """
        limits = {
            'error_code': (3, 200),
            'how_to': (5, 400),
            'troubleshooting': (5, 400),
            'general': (10, 300)
        }

        max_docs, max_chars = limits.get(question_type, (10, 300))

        compressed = []
        for i, doc in enumerate(documents[:max_docs]):
            content = doc.get('content', '')[:max_chars]
            source = doc.get('source', 'Unknown')
            compressed.append(f"[문서 {i+1}] ({source})\n{content}")

        return '\n\n'.join(compressed)

    def optimize_prompts(self, training_examples: List[Dict]):
        """
        MIPRO로 프롬프트 자동 최적화 (옵션).

        Args:
            training_examples: [{'question': ..., 'answer': ..., 'documents': ...}]
        """
        from dspy.teleprompt import MIPRO

        # 메트릭 정의 (답변 품질 평가)
        def answer_quality_metric(example, prediction, trace=None):
            # 실제 답변과 예측 답변 비교
            # 여기서는 간단히 길이와 키워드 매칭으로 평가
            gold_answer = example.answer
            pred_answer = prediction.answer

            # 키워드 매칭 점수
            gold_keywords = set(gold_answer.lower().split())
            pred_keywords = set(pred_answer.lower().split())

            if not gold_keywords:
                return 0.0

            overlap = len(gold_keywords & pred_keywords)
            score = overlap / len(gold_keywords)

            return score

        # MIPRO 최적화
        optimizer = MIPRO(
            metric=answer_quality_metric,
            num_candidates=10,
            init_temperature=1.0
        )

        optimized_cot = optimizer.compile(
            self.cot,
            trainset=training_examples,
            num_trials=20
        )

        self.cot = optimized_cot
        logger.info("✓ Prompts optimized with MIPRO")


# Global instance
answer_generator = OptimizedAnswerGenerator()
```

#### SearchAgent 통합

**agents/search_agent.py** 수정:
```python
from agents.optimized_prompts import answer_generator

# 기존 _generate_final_answer 대체
def _generate_final_answer_optimized(
    self,
    question: str,
    documents: List[Dict],
    question_type: str,
    context: str = ''
) -> Dict[str, Any]:
    """최적화된 답변 생성."""

    self.profiler.start_timer('answer_generation', {'phase': 'optimized'})

    result = answer_generator.generate(
        question=question,
        documents=documents,
        question_type=question_type,
        context=context
    )

    self.profiler.end_timer('answer_generation')

    logger.info(f"✓ Answer generated: {result['tokens_used']} tokens, confidence {result['confidence']:.2f}")

    return result
```

#### 예상 효과
```
현재 답변 생성 시간: 12.89s
개선 후 예상:
  - error_code: 6s (간결한 프롬프트 + 작은 컨텍스트)
  - how_to: 9s (상세 프롬프트 + 중간 컨텍스트)
  - general: 8s (일반 프롬프트)

평균 답변 생성 시간: 9.0s (30% 개선)

토큰 사용량:
  - error_code: 1500 토큰 (현재 4000)
  - how_to: 2500 토큰 (현재 8000)
  - general: 2000 토큰 (현재 6000)

평균 50% 토큰 절감 + 비용 절감
```

---

### 2.2 LLM 라우팅 (최신 기술)

**문제점**:
- 모든 작업에 GPT-4 사용 (비싸고 느림)
- 간단한 도구 선택도 GPT-4 호출

**최신 솔루션**: **LiteLLM + 모델 라우팅**

#### 기술 선택 이유
```yaml
LiteLLM (2024):
  장점:
    - 100+ LLM 통합 API (OpenAI, Anthropic, Cohere, local models)
    - 자동 폴백, 로드 밸런싱, 비용 추적
    - 간단한 설정으로 모델 전환
  대안:
    - 직접 OpenAI SDK: 수동 관리 필요 ⚠️
    - LangChain LLM Router: 복잡한 설정 ⚠️
```

#### 구현 코드

**requirements.txt 추가**:
```python
# LLM Routing (최신)
litellm==1.35.8        # 2024 최신, 100+ LLM 통합
anthropic==0.25.0      # Claude (대안 LLM)
```

**agents/llm_router.py** (새 파일):
```python
"""
LLM Router with LiteLLM

Strategies:
- Simple tasks → GPT-3.5 Turbo (fast, cheap)
- Complex tasks → GPT-4 (accurate, slow)
- Fallback to Claude if OpenAI fails
"""

from litellm import completion, acompletion
from typing import Dict, Any, List, Optional
from utils.logger import logger
import time


class LLMRouter:
    """지능적 LLM 라우팅."""

    # 모델 비용 (입력 1M 토큰당 USD)
    COSTS = {
        'gpt-3.5-turbo': 0.50,
        'gpt-4-turbo': 10.00,
        'gpt-4o': 5.00,
        'claude-3-haiku': 0.25,
        'claude-3-sonnet': 3.00
    }

    # 모델 속도 (상대적)
    SPEEDS = {
        'gpt-3.5-turbo': 1.0,
        'gpt-4-turbo': 0.3,
        'gpt-4o': 0.5,
        'claude-3-haiku': 1.2,
        'claude-3-sonnet': 0.4
    }

    def __init__(self):
        self.usage_stats = {
            'total_tokens': 0,
            'total_cost': 0.0,
            'model_usage': {}
        }

    def select_model(
        self,
        task_type: str,
        complexity: str = 'medium',
        budget_priority: bool = False
    ) -> str:
        """
        작업 타입과 복잡도에 따라 최적 모델 선택.

        Args:
            task_type: 'tool_selection', 'answer_generation', 'validation'
            complexity: 'simple', 'medium', 'complex'
            budget_priority: True면 비용 우선, False면 품질 우선

        Returns:
            모델 이름
        """
        # 도구 선택: 간단한 작업
        if task_type == 'tool_selection':
            if complexity == 'simple':
                return 'gpt-3.5-turbo'  # 에러코드 패턴 매칭
            else:
                return 'gpt-4o'  # 복잡한 도구 조합

        # 답변 생성: 품질 중요
        elif task_type == 'answer_generation':
            if budget_priority:
                return 'gpt-4o'  # 가성비 좋은 최신 모델
            else:
                return 'gpt-4-turbo'  # 최고 품질

        # 검증: 빠른 모델
        elif task_type == 'validation':
            return 'gpt-3.5-turbo'

        # 기본값
        return 'gpt-4o'

    async def call_llm(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        task_type: str = 'general',
        complexity: str = 'medium',
        temperature: float = 0.0,
        max_tokens: int = 2000,
        fallback_models: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        LLM 호출 (자동 폴백 지원).

        Args:
            messages: OpenAI 형식 메시지
            model: 모델 이름 (None이면 자동 선택)
            task_type: 작업 타입
            complexity: 복잡도
            temperature: 온도
            max_tokens: 최대 토큰
            fallback_models: 폴백 모델 리스트

        Returns:
            {
                'content': str,
                'model_used': str,
                'tokens': int,
                'cost': float,
                'latency': float
            }
        """
        # 모델 자동 선택
        if model is None:
            model = self.select_model(task_type, complexity)

        # 폴백 모델 기본값
        if fallback_models is None:
            fallback_models = ['gpt-4o', 'claude-3-sonnet', 'gpt-3.5-turbo']

        models_to_try = [model] + [m for m in fallback_models if m != model]

        start_time = time.time()

        for try_model in models_to_try:
            try:
                # LiteLLM 비동기 호출
                response = await acompletion(
                    model=try_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=60.0
                )

                latency = time.time() - start_time

                # 토큰 및 비용 계산
                tokens = response.usage.total_tokens
                cost = self._calculate_cost(try_model, tokens)

                # 통계 업데이트
                self._update_stats(try_model, tokens, cost)

                logger.info(f"✓ LLM call: {try_model} ({tokens} tokens, ${cost:.4f}, {latency:.2f}s)")

                return {
                    'content': response.choices[0].message.content,
                    'model_used': try_model,
                    'tokens': tokens,
                    'cost': cost,
                    'latency': latency
                }

            except Exception as e:
                logger.warning(f"LLM call failed ({try_model}): {e}")
                if try_model == models_to_try[-1]:
                    raise Exception(f"All LLM models failed: {e}")
                continue

    def _calculate_cost(self, model: str, tokens: int) -> float:
        """토큰 수에 따른 비용 계산."""
        cost_per_million = self.COSTS.get(model, 10.0)
        return (tokens / 1_000_000) * cost_per_million

    def _update_stats(self, model: str, tokens: int, cost: float):
        """사용 통계 업데이트."""
        self.usage_stats['total_tokens'] += tokens
        self.usage_stats['total_cost'] += cost

        if model not in self.usage_stats['model_usage']:
            self.usage_stats['model_usage'][model] = {
                'calls': 0,
                'tokens': 0,
                'cost': 0.0
            }

        self.usage_stats['model_usage'][model]['calls'] += 1
        self.usage_stats['model_usage'][model]['tokens'] += tokens
        self.usage_stats['model_usage'][model]['cost'] += cost

    def get_stats(self) -> Dict[str, Any]:
        """비용 통계."""
        return self.usage_stats


# Global instance
llm_router = LLMRouter()
```

#### SearchAgent 통합

**agents/search_agent.py** 수정:
```python
from agents.llm_router import llm_router

# 도구 선택 (간단한 작업)
async def _get_agent_decision_with_routing(
    self,
    query: str,
    context: str,
    iteration: int
) -> Dict[str, Any]:
    """LLM 라우팅으로 도구 선택."""

    # 복잡도 판단
    complexity = 'simple' if iteration == 1 else 'medium'

    messages = self._build_decision_messages(query, context)

    result = await llm_router.call_llm(
        messages=messages,
        task_type='tool_selection',
        complexity=complexity,
        temperature=0.0,
        max_tokens=500
    )

    # JSON 파싱
    decision = json.loads(result['content'])

    return decision

# 답변 생성 (품질 중요)
async def _generate_final_answer_with_routing(
    self,
    question: str,
    documents: List[Dict]
) -> str:
    """LLM 라우팅으로 답변 생성."""

    messages = self._build_answer_messages(question, documents)

    result = await llm_router.call_llm(
        messages=messages,
        task_type='answer_generation',
        complexity='complex',
        temperature=0.3,
        max_tokens=2000
    )

    return result['content']
```

#### 예상 효과
```
현재 LLM 호출 시간: 9.4s (GPT-4만 사용)
개선 후 예상:
  - Tool 선택 (Iter 1): 0.8s (GPT-3.5 Turbo)
  - Tool 선택 (Iter 2+): 1.2s (GPT-4o)
  - 답변 생성: 7.0s (GPT-4 Turbo)

평균 LLM 호출 시간: 3.0s (68% 개선!)

비용 절감:
  - Tool 선택: 95% 절감 (GPT-4 → GPT-3.5)
  - 답변 생성: 50% 절감 (GPT-4 → GPT-4o)

총 비용: 약 70% 절감
```

---

## ⚡ Step 3: 병렬 실행 + 고급 최적화 (1개월)

### 목표
- Tool 실행 시간: 0.47s → 0.19s (60% 개선)
- 병렬 검색으로 처리량 증가
- 예상 응답 시간: 12.9s → 6.0s (최종 목표 달성)

---

### 3.1 비동기 병렬 Tool 실행 (최신 기술)

**현재 문제점**:
- 모든 Tool이 순차 실행 (sync)
- 독립적인 검색도 하나씩 처리
- 평균 5회 × 95ms = 475ms

**최신 솔루션**: **AsyncIO + HTTPX + Asyncio Pool**

#### 기술 선택 이유
```yaml
AsyncIO (Python 3.11+):
  - 네이티브 async/await 지원
  - asyncio.gather로 병렬 실행
  - Task groups (3.11+) 예외 처리 개선

HTTPX (최신):
  - requests의 비동기 버전
  - HTTP/2 지원, connection pooling
  - Timeout, retry 자동 관리

Qdrant Async Client:
  - 비동기 벡터 검색
  - Batch 검색 지원
```

#### 구현 코드

**requirements.txt 추가**:
```python
# Async Libraries (최신)
httpx==0.26.0          # 2024 최신, async HTTP client
aiomysql==0.2.0        # Async MySQL
aioredis==2.0.1        # Async Redis (deprecated, Redis 5.0+ 사용)
asyncio-pool==0.6.0    # Async task pool
```

**agents/async_tools.py** (새 파일):
```python
"""
Async Tool Execution Engine

Features:
- Parallel tool execution with asyncio
- Connection pooling for DB and vector stores
- Intelligent batching and deduplication
"""

import asyncio
from typing import List, Dict, Any, Optional
import time
from utils.logger import logger


class AsyncToolExecutor:
    """비동기 병렬 도구 실행기."""

    def __init__(
        self,
        max_concurrent: int = 5,
        timeout: float = 30.0
    ):
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def execute_parallel(
        self,
        tools: List[Dict[str, Any]],
        dedup: bool = True
    ) -> List[Dict[str, Any]]:
        """
        여러 도구를 병렬 실행.

        Args:
            tools: [{'name': ..., 'args': ...}, ...]
            dedup: 중복 도구 호출 제거

        Returns:
            [{'tool': ..., 'result': ..., 'success': ...}, ...]
        """
        # 중복 제거
        if dedup:
            tools = self._deduplicate_tools(tools)

        # 병렬 실행
        tasks = [
            self._execute_single(tool['name'], tool['args'])
            for tool in tools
        ]

        start_time = time.time()

        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            latency = time.time() - start_time

            logger.info(f"✓ Parallel execution: {len(tools)} tools in {latency:.2f}s")

            # 예외 처리
            processed_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Tool {tools[i]['name']} failed: {result}")
                    processed_results.append({
                        'tool': tools[i]['name'],
                        'result': [],
                        'success': False,
                        'error': str(result)
                    })
                else:
                    processed_results.append(result)

            return processed_results

        except Exception as e:
            logger.error(f"Parallel execution failed: {e}")
            return []

    async def _execute_single(
        self,
        tool_name: str,
        tool_args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """단일 도구 실행 (Semaphore로 동시 실행 제한)."""

        async with self.semaphore:
            try:
                # 도구 타입별 실행
                if tool_name == 'search_qdrant_semantic':
                    result = await self._search_qdrant_async(tool_args)
                elif tool_name == 'search_mariadb_by_error_code':
                    result = await self._search_mariadb_async(tool_args)
                elif tool_name == 'search_elasticsearch_bm25':
                    result = await self._search_es_async(tool_args)
                else:
                    # Fallback: sync 도구를 async로 래핑
                    result = await self._execute_sync_tool(tool_name, tool_args)

                return {
                    'tool': tool_name,
                    'result': result,
                    'success': True
                }

            except asyncio.TimeoutError:
                logger.error(f"Tool {tool_name} timeout")
                return {
                    'tool': tool_name,
                    'result': [],
                    'success': False,
                    'error': 'timeout'
                }
            except Exception as e:
                logger.error(f"Tool {tool_name} error: {e}")
                return {
                    'tool': tool_name,
                    'result': [],
                    'success': False,
                    'error': str(e)
                }

    async def _search_qdrant_async(self, args: Dict[str, Any]) -> List[Dict]:
        """Qdrant 비동기 검색."""
        from repositories.vector_repository import VectorRepository

        # Async Qdrant client 사용
        # 실제 구현은 VectorRepository를 async로 변환 필요
        # 여기서는 간단히 sync 호출을 thread pool에서 실행
        loop = asyncio.get_event_loop()
        vector_repo = VectorRepository()

        result = await loop.run_in_executor(
            None,
            vector_repo.search_semantic,
            args.get('query', ''),
            args.get('top_k', 10)
        )

        return result

    async def _search_mariadb_async(self, args: Dict[str, Any]) -> List[Dict]:
        """MariaDB 비동기 검색 (aiomysql 사용)."""
        import aiomysql
        from config.settings import settings

        # Connection pool (재사용)
        if not hasattr(self, '_db_pool'):
            self._db_pool = await aiomysql.create_pool(
                host=settings.DB_HOST,
                port=settings.DB_PORT,
                user=settings.DB_USER,
                password=settings.DB_PASSWORD,
                db=settings.DB_NAME,
                maxsize=10
            )

        async with self._db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # 에러코드 검색 예시
                error_code = args.get('error_code', '')

                await cursor.execute(
                    "SELECT * FROM error_codes WHERE code = %s",
                    (error_code,)
                )

                results = await cursor.fetchall()

                return list(results)

    async def _search_es_async(self, args: Dict[str, Any]) -> List[Dict]:
        """Elasticsearch 비동기 검색 (HTTPX 사용)."""
        import httpx
        from config.settings import settings

        # HTTPX async client (connection pooling)
        if not hasattr(self, '_http_client'):
            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                limits=httpx.Limits(max_connections=50)
            )

        # BM25 검색
        query = args.get('query', '')

        response = await self._http_client.post(
            f"{settings.ES_URL}/rag_documents/_search",
            json={
                "query": {
                    "match": {
                        "content": query
                    }
                },
                "size": args.get('top_k', 10)
            }
        )

        data = response.json()
        hits = data.get('hits', {}).get('hits', [])

        return [hit['_source'] for hit in hits]

    async def _execute_sync_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any]
    ) -> List[Dict]:
        """Sync 도구를 thread pool에서 실행."""
        from agents.tools.tool_registry import tool_registry

        tool_func = tool_registry.get_tool(tool_name)

        if tool_func is None:
            raise ValueError(f"Tool not found: {tool_name}")

        loop = asyncio.get_event_loop()

        result = await loop.run_in_executor(
            None,
            tool_func,
            **tool_args
        )

        return result

    def _deduplicate_tools(
        self,
        tools: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """중복 도구 호출 제거."""
        seen = set()
        unique_tools = []

        for tool in tools:
            # 도구 이름 + args hash
            import json
            import hashlib

            tool_signature = f"{tool['name']}:{hashlib.md5(json.dumps(tool['args'], sort_keys=True).encode()).hexdigest()}"

            if tool_signature not in seen:
                seen.add(tool_signature)
                unique_tools.append(tool)

        if len(unique_tools) < len(tools):
            logger.info(f"🔄 Deduplication: {len(tools)} → {len(unique_tools)} tools")

        return unique_tools


# Global instance
async_executor = AsyncToolExecutor(max_concurrent=5)
```

#### SearchAgent 통합 (비동기 변환)

**agents/search_agent.py** 대대적 수정:
```python
class SearchAgent:
    """비동기 SearchAgent."""

    # ... (초기화는 동일)

    async def search(
        self,
        question: str,
        session_id: Optional[str] = None,
        debug: bool = False
    ) -> Dict[str, Any]:
        """비동기 검색 (메인 엔트리)."""

        # ... (초기화 로직)

        # ReAct loop (비동기)
        for iteration in range(1, max_iterations + 1):
            # 병렬 실행 전략 결정
            if iteration == 1:
                # 첫 iteration: 여러 도구 병렬 실행
                tools_to_run = [
                    {'name': 'search_qdrant_semantic', 'args': {'query': query, 'top_k': 10}},
                    {'name': 'search_elasticsearch_bm25', 'args': {'query': query, 'top_k': 10}}
                ]

                # 에러코드 패턴 감지 시 추가
                if self._has_error_code(query):
                    tools_to_run.append({
                        'name': 'search_mariadb_by_error_code',
                        'args': {'error_code': self._extract_error_code(query)}
                    })

                # 병렬 실행
                results = await async_executor.execute_parallel(tools_to_run)

                # 결과 병합
                for result in results:
                    if result['success']:
                        collected_docs.extend(result['result'])

            else:
                # 이후 iteration: LLM 기반 도구 선택
                decision = await self._get_agent_decision_async(...)

                # 단일 도구 실행
                tool_result = await async_executor._execute_single(
                    decision['tool_name'],
                    decision['tool_args']
                )

                if tool_result['success']:
                    collected_docs.extend(tool_result['result'])

            # 조기 종료 체크
            should_stop, reason = early_stopping.should_stop(...)
            if should_stop:
                break

        # 답변 생성 (비동기)
        answer = await self._generate_final_answer_async(...)

        return {
            'answer': answer,
            'documents': collected_docs,
            ...
        }


# FastAPI 엔드포인트도 async로 변경
@app.post("/search")
async def search_endpoint(request: SearchRequest):
    """비동기 검색 엔드포인트."""

    result = await search_agent.search(
        question=request.question,
        session_id=request.session_id,
        debug=request.debug
    )

    return result
```

#### 예상 효과
```
현재 Tool 실행 시간: 474ms (순차)
개선 후 예상:
  - Iteration 1 (3개 병렬): 211ms (가장 느린 도구 기준)
  - Iteration 2+ (1개): 95ms

평균 Tool 실행 시간: 190ms (60% 개선!)

전체 응답 시간:
  - 현재: 22.78s
  - Step 1 후: 15.9s
  - Step 2 후: 12.9s
  - Step 3 후: 6.0s ✅ 목표 달성!
```

---

### 3.2 벡터 인덱스 최적화 (HNSW 튜닝)

**현재**: Qdrant 기본 설정
**개선**: HNSW 파라미터 최적화

#### 구현 코드

**scripts/optimize_qdrant_index.py** (새 파일):
```python
"""
Qdrant HNSW Index Optimization

HNSW Parameters:
- m: 연결 수 (default 16, 높을수록 정확하지만 느림)
- ef_construct: 인덱스 빌드 시 탐색 깊이 (default 100)
- ef: 검색 시 탐색 깊이 (default 64, 높을수록 정확하지만 느림)
"""

from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, HnswConfigDiff
from config.settings import settings


def optimize_qdrant_index():
    """Qdrant 인덱스 최적화."""

    client = QdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT
    )

    # 현재 인덱스 설정 확인
    collection_info = client.get_collection(settings.QDRANT_COLLECTION)

    print(f"Current HNSW config:")
    print(f"  m: {collection_info.config.hnsw_config.m}")
    print(f"  ef_construct: {collection_info.config.hnsw_config.ef_construct}")
    print(f"  ef: {collection_info.config.hnsw_config.full_scan_threshold}")

    # 최적화된 설정으로 업데이트
    client.update_collection(
        collection_name=settings.QDRANT_COLLECTION,
        hnsw_config=HnswConfigDiff(
            m=32,              # 16 → 32 (더 많은 연결, 정확도 증가)
            ef_construct=200,  # 100 → 200 (인덱스 빌드 품질 향상)
            full_scan_threshold=20000  # 전체 스캔 임계값
        )
    )

    # 검색 시 ef 조정 (검색 코드에서 설정)
    # search(..., search_params={'ef': 128})  # 64 → 128

    print("✓ HNSW index optimized")
    print("  Recommendation: Use ef=128 for search queries")


if __name__ == '__main__':
    optimize_qdrant_index()
```

**예상 효과**:
```
검색 정확도: 90% → 95% (Recall@10)
검색 시간: 211ms → 180ms (최적화된 인덱스)
```

---

### 3.3 FAQ 캐시 (사전 계산)

**아이디어**: 자주 묻는 질문은 미리 답변 생성

#### 구현 코드

**agents/faq_cache.py** (새 파일):
```python
"""
FAQ Pre-computation Cache

Features:
- Pre-generate answers for common questions
- Store in Redis with high TTL (24 hours)
- Periodic refresh based on query frequency
"""

from typing import Dict, Any, List
import json
from agents.distributed_cache import distributed_cache
from utils.logger import logger


class FAQCache:
    """FAQ 사전 답변 캐시."""

    FAQ_QUESTIONS = [
        "RemoteView 설치 방법 알려주세요",
        "RemoteCall 연결이 안 돼요",
        "에러코드 31161이 뭔가요",
        "화면 공유 어떻게 하나요",
        # ... 자주 묻는 100개 질문
    ]

    async def precompute_faqs(self, search_agent):
        """FAQ 답변 사전 생성."""

        logger.info(f"🔄 Precomputing {len(self.FAQ_QUESTIONS)} FAQ answers...")

        for i, question in enumerate(self.FAQ_QUESTIONS):
            try:
                # 답변 생성
                result = await search_agent.search(
                    question=question,
                    session_id='faq_cache',
                    debug=False
                )

                # Redis에 24시간 캐시
                cache_key = f"faq:cache:{question}"
                await distributed_cache.redis.setex(
                    cache_key,
                    86400,  # 24시간
                    json.dumps(result, ensure_ascii=False)
                )

                logger.info(f"✓ FAQ {i+1}/{len(self.FAQ_QUESTIONS)}: {question[:30]}...")

            except Exception as e:
                logger.error(f"FAQ precompute failed: {question} - {e}")

        logger.info("✓ FAQ precomputation completed")

    async def get_faq_answer(self, question: str) -> Optional[Dict[str, Any]]:
        """FAQ 답변 조회."""

        cache_key = f"faq:cache:{question}"

        cached = await distributed_cache.redis.get(cache_key)

        if cached:
            logger.info(f"✨ FAQ cache HIT: {question[:30]}...")
            return json.loads(cached)

        return None


# Global instance
faq_cache = FAQCache()
```

**Cron Job 설정** (매일 새벽 2시 갱신):
```bash
# crontab -e
0 2 * * * cd /rsupport/software/R-agent && python scripts/refresh_faq_cache.py
```

**예상 효과**:
```
FAQ 질문 비율: 30% (전체 질문 중)
FAQ 답변 시간: 0.001s (캐시 히트)
전체 평균 개선: 30% × 22.78s = 6.8s 절감
```

---

## 📊 최종 성능 예상

### 단계별 누적 개선

| 단계 | 개선 내용 | 응답 시간 | 개선율 | 구현 기간 |
|-----|----------|---------|-------|---------|
| **현재** | Phase 4 상태 | 22.78s | - | - |
| **Step 1** | Redis 캐시 + 조기 종료 | 15.9s | 30% | 1주 |
| **Step 2** | DSPy 최적화 + LLM 라우팅 | 9.0s | 43% | 2주 |
| **Step 3** | 병렬 실행 + HNSW + FAQ | 6.0s | 33% | 1개월 |
| **총계** | - | **6.0s** | **74%** | **1개월** |

### 비용 절감

| 항목 | 현재 | 개선 후 | 절감율 |
|-----|------|--------|-------|
| LLM 호출 횟수 | 5회 | 2.5회 | 50% |
| 모델 비용 (Tool 선택) | GPT-4 | GPT-3.5 | 95% |
| 모델 비용 (답변 생성) | GPT-4 | GPT-4o | 50% |
| 토큰 사용량 | 8000 | 4000 | 50% |
| **총 비용 절감** | - | - | **~70%** |

---

## 🛠️ 구현 우선순위 및 로드맵

### Week 1-2: Step 1 구현
```yaml
우선순위 1 (즉시):
  - Redis Stack 설치 및 설정
  - DistributedCache 구현
  - EarlyStoppingStrategy 구현
  - SearchAgent 통합 및 테스트

예상 산출물:
  - distributed_cache.py (완성)
  - early_stopping.py (완성)
  - docker-compose.yml (Redis)
  - 통합 테스트 (30개 질문)

성공 기준:
  - 캐시 적중률 40%+
  - 평균 Iteration 3회 이하
  - 응답 시간 15.9s 달성
```

### Week 3-4: Step 2 구현
```yaml
우선순위 2 (단기):
  - DSPy 설치 및 프롬프트 최적화
  - LiteLLM 설치 및 라우팅 구현
  - 질문 타입별 프롬프트 분리
  - 비용 모니터링 대시보드

예상 산출물:
  - optimized_prompts.py (DSPy)
  - llm_router.py (LiteLLM)
  - 프롬프트 최적화 보고서
  - 비용 절감 대시보드

성공 기준:
  - 답변 생성 시간 9.0s 이하
  - LLM 호출 2.5회 평균
  - 비용 70% 절감
  - 응답 시간 12.9s 달성
```

### Week 5-8: Step 3 구현
```yaml
우선순위 3 (중기):
  - AsyncIO 전면 도입 (agents/async_tools.py)
  - Qdrant HNSW 최적화
  - FAQ 사전 계산 시스템
  - 종합 성능 테스트

예상 산출물:
  - async_tools.py (비동기 실행)
  - optimize_qdrant_index.py (HNSW 튜닝)
  - faq_cache.py (FAQ 시스템)
  - 최종 성능 보고서

성공 기준:
  - 병렬 실행 시간 190ms 이하
  - FAQ 답변 0.001s
  - **최종 응답 시간 6.0s 달성** ✅
```

---

## 📚 참고 라이브러리 및 문서

### 핵심 라이브러리 (2024-2025 최신)

| 라이브러리 | 버전 | 용도 | 문서 |
|----------|------|------|------|
| **redis** | 5.0.1 | 분산 캐시 | https://redis.io/docs/latest/develop/clients/python/ |
| **redis-om** | 0.2.1 | Redis ORM | https://github.com/redis/redis-om-python |
| **dspy-ai** | 2.4.9 | 프롬프트 최적화 | https://dspy-docs.vercel.app/ |
| **litellm** | 1.35.8 | LLM 라우팅 | https://docs.litellm.ai/ |
| **httpx** | 0.26.0 | Async HTTP | https://www.python-httpx.org/ |
| **aiomysql** | 0.2.0 | Async MySQL | https://aiomysql.readthedocs.io/ |
| **guidance** | 0.1.14 | 구조화 출력 | https://github.com/guidance-ai/guidance |

### 대안 기술 고려사항

```yaml
DragonflyDB vs Redis:
  DragonflyDB: 10배 빠르지만 안정성 검증 중
  Redis Stack: 안정적, 광범위한 생태계
  → Redis Stack 선택 권장

Claude vs GPT:
  Claude 3 Haiku: 매우 빠르고 저렴
  GPT-4o: 균형잡힌 성능과 비용
  → 하이브리드 사용 (LiteLLM 라우팅)

Async Framework:
  AsyncIO: 네이티브, 학습 곡선
  Trio: 더 간단한 API
  → AsyncIO 선택 (표준 라이브러리)
```

---

## ✅ 체크리스트

### Step 1 완료 조건
- [ ] Redis Stack 설치 및 연결 확인
- [ ] DistributedCache 단위 테스트 통과
- [ ] Semantic cache matching 정확도 85%+
- [ ] 캐시 적중률 40%+ 달성
- [ ] Early stopping 평균 3회 iteration
- [ ] 통합 테스트 30개 질문 통과
- [ ] 응답 시간 15.9s 이하

### Step 2 완료 조건
- [ ] DSPy 프롬프트 최적화 완료
- [ ] 질문 타입별 프롬프트 분리
- [ ] LiteLLM 라우팅 구현
- [ ] 비용 모니터링 대시보드
- [ ] 답변 생성 시간 9.0s 이하
- [ ] LLM 호출 2.5회 평균
- [ ] 응답 시간 12.9s 이하

### Step 3 완료 조건
- [ ] AsyncIO 전면 전환 완료
- [ ] 병렬 Tool 실행 테스트 통과
- [ ] Qdrant HNSW 최적화 완료
- [ ] FAQ 사전 계산 100개 완료
- [ ] Tool 실행 시간 190ms 이하
- [ ] 최종 응답 시간 6.0s 이하 ✅
- [ ] 전체 비용 70% 절감 확인

---

**End of Implementation Roadmap**
