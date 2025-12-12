# Tool Performance Tracking - SearchAgent 통합 가이드

## 📋 개요

SearchAgent에 도구 성능 추적 기능을 통합하여 학습 능력을 부여하는 가이드입니다.

## 🎯 통합 목표

1. **자동 로깅**: 모든 도구 실행을 자동으로 기록
2. **학습 기반 선택**: 과거 데이터를 활용한 최적 도구 선택
3. **성능 개선**: 불필요한 도구 호출 감소
4. **투명성**: 왜 특정 도구를 선택했는지 설명 가능

## 🔧 통합 단계

### 1단계: Repository 초기화

**파일**: `agents/search_agent.py`

```python
from repositories.tool_performance_repository import ToolPerformanceRepository
import uuid

class SearchAgent:
    def __init__(self):
        # 기존 코드...
        self.db_repo = DatabaseRepository()
        self.vector_repo = VectorRepository(self.db_repo)
        self.es_repo = ElasticsearchRepository()

        # 🆕 Performance tracking 추가
        self.perf_repo = ToolPerformanceRepository()
        self.session_id = str(uuid.uuid4())  # 세션 식별자
```

### 2단계: 도구 실행 래퍼 추가

**목적**: 모든 도구 실행을 추적하고 로깅

```python
def _execute_tool_with_tracking(
    self,
    tool_func,
    tool_name: str,
    args: Dict,
    execution_order: int,
    is_fallback: bool,
    question: str,
    question_type: str
) -> Tuple[Any, bool]:
    """
    도구 실행을 추적하며 실행.

    Args:
        tool_func: 실행할 도구 함수
        tool_name: 도구 이름
        args: 도구 인자
        execution_order: 실행 순서
        is_fallback: 폴백 여부
        question: 사용자 질문
        question_type: 질문 유형

    Returns:
        (결과, 성공여부) 튜플
    """
    import time

    start_time = time.time()
    success = False
    result = None
    error_message = None
    error_type = None

    try:
        # 도구 실행
        result = tool_func(**args)
        success = len(result) > 0 if result else False

        # 실행 시간 계산
        execution_time = time.time() - start_time

        # 문서 수와 평균 점수 계산
        doc_count = len(result) if result else 0
        avg_score = 0.0
        if result and doc_count > 0:
            scores = [doc.get('score', 0) for doc in result]
            avg_score = sum(scores) / len(scores) if scores else 0.0

        # 성능 로깅
        self.perf_repo.log_tool_execution(
            session_id=self.session_id,
            question=question,
            question_type=question_type,
            tool_name=tool_name,
            execution_order=execution_order,
            is_fallback=is_fallback,
            doc_count=doc_count,
            avg_score=avg_score,
            execution_time=execution_time,
            success=success
        )

        logger.info(
            f"📊 {tool_name}: docs={doc_count}, "
            f"score={avg_score:.2f}, time={execution_time:.3f}s"
        )

        return result, success

    except Exception as e:
        execution_time = time.time() - start_time
        error_message = str(e)
        error_type = type(e).__name__

        # 실패 로깅
        self.perf_repo.log_tool_execution(
            session_id=self.session_id,
            question=question,
            question_type=question_type,
            tool_name=tool_name,
            execution_order=execution_order,
            is_fallback=is_fallback,
            doc_count=0,
            avg_score=0.0,
            execution_time=execution_time,
            success=False,
            error_message=error_message,
            error_type=error_type
        )

        logger.error(f"❌ {tool_name} 실패: {error_message}")
        return None, False
```

### 3단계: 학습 기반 도구 선택

**목적**: 과거 데이터를 활용하여 최적 도구 선택

```python
def _get_optimal_tool_for_question(
    self,
    question_type: str,
    use_learning: bool = True
) -> Optional[str]:
    """
    질문 유형에 최적화된 도구 선택.

    Args:
        question_type: 질문 유형
        use_learning: 학습 데이터 사용 여부

    Returns:
        추천 도구명 또는 None (학습 데이터 부족)
    """
    if not use_learning:
        return None

    # 과거 데이터에서 최적 도구 찾기
    best_tool = self.perf_repo.get_best_tool_for_question_type(
        question_type=question_type,
        min_executions=10  # 최소 10회 이상 실행된 도구만
    )

    if best_tool:
        tool_name, success_rate = best_tool
        logger.info(
            f"💡 학습 추천: '{question_type}' → {tool_name} "
            f"(성공률 {success_rate:.2%})"
        )
        return tool_name

    logger.debug(f"⚠️ '{question_type}' 학습 데이터 부족, 기본 전략 사용")
    return None


def _get_learned_fallback_chain(
    self,
    question_type: str
) -> List[str]:
    """
    학습된 폴백 체인 가져오기.

    Args:
        question_type: 질문 유형

    Returns:
        추천 도구 리스트
    """
    chain = self.perf_repo.get_tool_fallback_chain(
        question_type=question_type,
        max_tools=3
    )

    if chain:
        logger.info(f"🔗 학습된 폴백 체인: {' → '.join(chain)}")

    return chain
```

### 4단계: search() 메서드 수정

**기존 로직에 통합**:

```python
def search(
    self,
    question: str,
    max_iterations: int = 5,
    debug: bool = False
) -> Dict:
    """검색 실행 (성능 추적 통합)."""

    start_time = time.time()

    # 세션 ID 생성 (새 검색마다)
    self.session_id = str(uuid.uuid4())

    # 질문 유형 감지
    question_type = self._detect_question_type(question)

    # 🆕 학습 기반 도구 선택 시도
    optimal_tool = self._get_optimal_tool_for_question(question_type)

    if optimal_tool:
        # 학습된 최적 도구로 먼저 시도
        logger.info(f"🎯 학습 기반 선택: {optimal_tool}")
        tool_func = self._get_tool_function(optimal_tool)

        result, success = self._execute_tool_with_tracking(
            tool_func=tool_func,
            tool_name=optimal_tool,
            args={'query': question, 'top_k': 10},
            execution_order=1,
            is_fallback=False,
            question=question,
            question_type=question_type
        )

        if success:
            # 성공 시 바로 반환
            return self._format_response(result, question, ...)

    # 학습 데이터 없거나 실패 시 기존 ReAct 루프 실행
    # ... 기존 코드 ...
```

### 5단계: 폴백 체인에 학습 적용

```python
# ReAct 루프 내부에서 폴백 체인 사용 시
learned_chain = self._get_learned_fallback_chain(question_type)

if learned_chain:
    fallback_chain = learned_chain
else:
    # 기존 하드코딩 폴백 체인
    fallback_chain = [
        'search_mariadb_by_keyword',
        'search_qdrant_semantic',
        'search_elasticsearch_bm25'
    ]
```

## 📊 학습 데이터 축적 전략

### 초기 단계 (0-100회 쿼리)
- **전략**: 기존 휴리스틱 사용 + 모든 실행 로깅
- **목적**: 데이터 수집 및 베이스라인 확립
- **학습**: 비활성화 (`use_learning=False`)

### 중간 단계 (100-1000회 쿼리)
- **전략**: 일부 질문 유형에 학습 적용
- **목적**: 학습 효과 검증
- **학습**: 부분 활성화 (충분한 데이터가 있는 질문 유형만)

### 성숙 단계 (1000회+ 쿼리)
- **전략**: 모든 질문 유형에 학습 우선 적용
- **목적**: 최적화된 도구 선택
- **학습**: 완전 활성화 (`use_learning=True`)

## 🔄 통계 업데이트 스케줄

### 실시간 로깅
```python
# 도구 실행 직후 즉시 로깅
self.perf_repo.log_tool_execution(...)
```

### 집계 통계 업데이트
```python
# 매일 자정 실행 (cron job 또는 스케줄러)
from repositories.tool_performance_repository import ToolPerformanceRepository

repo = ToolPerformanceRepository()
repo.update_aggregated_stats(days_back=30)
```

**Cron 설정 예시**:
```bash
# 매일 새벽 2시 통계 업데이트
0 2 * * * cd /rsupport/software/R-agent && python -c "from repositories.tool_performance_repository import ToolPerformanceRepository; ToolPerformanceRepository().update_aggregated_stats()"
```

## 📈 성과 측정

### 추적할 지표

1. **도구 선택 정확도**
   - 첫 시도 성공률 (학습 전 vs 후)
   - 평균 폴백 횟수 감소율

2. **성능 개선**
   - 평균 응답 시간 단축
   - 불필요한 도구 호출 감소

3. **품질 향상**
   - 평균 문서 관련성 점수
   - 사용자 만족도

### 대시보드 쿼리 예시

```sql
-- 질문 유형별 도구 성능 비교
SELECT
    question_type,
    tool_name,
    total_executions,
    success_rate,
    avg_execution_time
FROM tool_performance_stats
WHERE total_executions >= 10
ORDER BY question_type, success_rate DESC;

-- 시간 경과에 따른 성능 추이
SELECT
    DATE(created_at) as date,
    AVG(CASE WHEN execution_order = 1 AND success THEN 1 ELSE 0 END) as first_try_success_rate,
    AVG(execution_order) as avg_fallback_depth
FROM tool_performance_log
WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
GROUP BY DATE(created_at)
ORDER BY date;
```

## ⚠️ 주의사항

### 1. 성능 영향 최소화
- 로깅은 비동기로 처리 권장
- 통계 조회는 캐싱 활용
- DB 연결 풀 사용

### 2. 데이터 품질
- 에러 케이스도 정확히 로깅
- 실패 원인 명확히 기록
- 이상치 데이터 필터링

### 3. 개인정보 보호
- 질문 내용은 익명화 고려
- user_id는 해시 처리 권장
- 민감 정보 로깅 제외

## 🚀 배포 체크리스트

- [ ] Learning DB 설치 완료
- [ ] ToolPerformanceRepository 테스트 통과
- [ ] SearchAgent에 tracking 코드 통합
- [ ] 기존 기능 회귀 테스트
- [ ] 학습 기능 비활성화 상태로 배포 (`use_learning=False`)
- [ ] 100회 쿼리 후 데이터 검증
- [ ] 학습 기능 단계적 활성화
- [ ] 성능 모니터링 대시보드 구축

## 📚 다음 단계

1. **Phase 2**: Session Context Manager 구현
2. **Phase 3**: Semantic Relevance Scoring 추가
3. **Phase 4**: Decision Explanation Generator
4. **Phase 5**: Parallel Tool Execution

이 문서는 Tool Performance Tracking의 기초입니다. 이후 고도화 기능들이 이 기반 위에 구축됩니다.
