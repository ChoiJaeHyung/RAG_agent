# 답변 품질 평가 시스템 설계

## 🚨 현재 시스템의 치명적 한계

### 문제 진단

**현재 "성공" 정의**:
```python
# tool_performance_log.success = (문서 개수 > 0)
success = (doc_count > 0)  # 문서만 찾으면 성공!
```

**실제 문제 사례**:
```
질문: "Docker 설치 방법"
검색: "Docker" 키워드로 10개 문서 찾음
결과: "Docker란 무엇인가?" 개념 설명 문서들
기록: success=True ✅ (문서 10개 찾았으니 성공!)

실제: ❌ 완전히 엉뚱한 답변!
  - 사용자는 "설치 방법"을 원함
  - 시스템은 "개념 설명"만 제공
  - 하지만 DB에는 "성공"으로 기록됨
```

**학습 왜곡 위험**:
```
1,000회 검색 후 tool_performance_stats:

tool_name: search_elasticsearch_bm25
question_type: how_to
success_rate: 0.95  ← 95% 성공!

실제 사용자 만족도: 40%  ← 엉뚱한 답변 다수!

→ use_learning=True 활성화 시 엉뚱한 도구를 계속 추천하게 됨!
```

---

## ✅ 해결 방안: 3단계 품질 평가 시스템

### Phase 1: 사용자 피드백 수집 (즉시 구현 가능)

#### 1-1. 간단한 만족도 수집

**API 응답에 피드백 URL 추가**:
```python
# main.py (FastAPI)
@app.post("/search")
def search(request: SearchRequest):
    # ... 기존 검색 로직 ...

    return {
        'answer': answer,
        'sources': sources,
        'session_id': session_id,  # 피드백용 ID
        'feedback_url': f'/feedback/{session_id}'  # 피드백 링크
    }

@app.post("/feedback/{session_id}")
def submit_feedback(session_id: str, feedback: FeedbackRequest):
    """
    답변 품질 피드백 수집

    Args:
        session_id: 검색 세션 ID
        feedback: {
            'satisfaction': 1-5,  # 1=매우 불만족 ~ 5=매우 만족
            'is_relevant': True/False,  # 답변이 질문에 맞는가?
            'comment': '...'  # 선택적 코멘트
        }
    """
    repo = SessionContextRepository()

    # session_context.avg_satisfaction 업데이트
    repo.update_satisfaction(
        session_id=session_id,
        satisfaction=feedback['satisfaction'],
        is_relevant=feedback['is_relevant'],
        comment=feedback.get('comment')
    )

    # tool_performance_log에 실제 성공 여부 업데이트
    if not feedback['is_relevant']:
        # 문서는 찾았지만 답변이 엉뚱함 → 실패로 수정
        tool_repo = ToolPerformanceRepository()
        tool_repo.update_actual_success(
            session_id=session_id,
            actual_success=False
        )

    return {'message': '피드백 감사합니다!'}
```

**session_context_repository.py 추가 메서드**:
```python
def update_satisfaction(
    self,
    session_id: str,
    satisfaction: int,  # 1-5
    is_relevant: bool,
    comment: Optional[str] = None
) -> bool:
    """대화 만족도 업데이트"""
    try:
        conn = self._get_connection()
        cursor = conn.cursor(dictionary=True)

        # 현재 평균 만족도 조회
        cursor.execute('''
            SELECT avg_satisfaction, total_questions
            FROM session_context
            WHERE session_id = %s
        ''', (session_id,))

        row = cursor.fetchone()

        if row:
            current_avg = row['avg_satisfaction'] or 0
            total_q = row['total_questions']

            # 새로운 평균 계산 (누적 평균)
            new_avg = ((current_avg * (total_q - 1)) + satisfaction) / total_q

            # 업데이트
            cursor.execute('''
                UPDATE session_context
                SET avg_satisfaction = %s
                WHERE session_id = %s
            ''', (new_avg, session_id))

            # conversation_history JSON에 피드백 추가
            cursor.execute('''
                SELECT conversation_history FROM session_context
                WHERE session_id = %s
            ''', (session_id,))

            history_str = cursor.fetchone()['conversation_history']
            history = json.loads(history_str) if history_str else []

            if history:
                # 마지막 턴에 피드백 추가
                history[-1]['feedback'] = {
                    'satisfaction': satisfaction,
                    'is_relevant': is_relevant,
                    'comment': comment,
                    'timestamp': datetime.now().isoformat()
                }

                cursor.execute('''
                    UPDATE session_context
                    SET conversation_history = %s
                    WHERE session_id = %s
                ''', (json.dumps(history, ensure_ascii=False), session_id))

            conn.commit()
            cursor.close()
            conn.close()

            logger.info(f"✓ Satisfaction updated: {session_id} (score: {satisfaction}/5)")
            return True

    except Exception as e:
        logger.error(f"Failed to update satisfaction: {e}")
        return False
```

**tool_performance_log 스키마 수정**:
```sql
ALTER TABLE tool_performance_log
ADD COLUMN actual_success BOOLEAN DEFAULT NULL COMMENT '실제 성공 여부 (사용자 피드백 기반)',
ADD COLUMN user_feedback_score INT DEFAULT NULL COMMENT '사용자 만족도 (1-5)',
ADD COLUMN feedback_timestamp TIMESTAMP NULL;
```

**장점**:
- ✅ 구현 간단 (1-2일)
- ✅ 실제 사용자 만족도 수집
- ✅ 비용 없음

**단점**:
- ⚠️ 사용자가 피드백 제공해야 함 (수집률 낮을 수 있음)
- ⚠️ 초기에는 피드백 데이터 부족

---

#### 1-2. 암묵적 피드백 (Implicit Feedback)

**재질문 패턴 감지**:
```python
def detect_implicit_dissatisfaction(
    self,
    session_id: str,
    new_question: str
) -> bool:
    """
    같은 세션에서 유사한 질문 반복 = 불만족 신호

    예:
    1. "Docker 설치 방법" → 답변 A
    2. "Docker 어떻게 설치해?" → 재질문 (불만족!)
    """
    history = self.get_conversation_history(session_id, limit=5)

    if len(history) > 0:
        last_question = history[-1]['question']

        # 의미적 유사도 계산 (임베딩 기반)
        similarity = self._calculate_similarity(last_question, new_question)

        if similarity > 0.7:  # 70% 이상 유사
            # 이전 답변에 불만족한 것으로 간주
            logger.warning(
                f"⚠️ Implicit dissatisfaction detected: "
                f"'{last_question}' → '{new_question}' (similarity: {similarity:.2f})"
            )

            # 이전 답변의 만족도를 낮게 자동 설정
            self.update_satisfaction(
                session_id=session_id,
                satisfaction=2,  # 불만족
                is_relevant=False,
                comment='Implicit: User asked similar question again'
            )

            return True

    return False
```

**세션 지속 시간 분석**:
```python
def analyze_session_engagement(self, session_id: str) -> Dict:
    """
    세션 지속 시간으로 만족도 추정

    빠른 이탈 (< 10초) = 불만족 가능성
    긴 지속 (> 2분) = 답변 활용 중 = 만족 가능성
    """
    stats = self.get_session_stats(session_id)

    started = stats['started_at']
    last_activity = stats['last_activity']

    duration = (last_activity - started).total_seconds()

    if duration < 10:
        # 빠른 이탈 = 불만족 추정
        return {
            'estimated_satisfaction': 2,
            'confidence': 0.6,
            'reason': 'Quick exit (< 10s)'
        }
    elif duration > 120:
        # 긴 지속 = 만족 추정
        return {
            'estimated_satisfaction': 4,
            'confidence': 0.7,
            'reason': 'Long engagement (> 2min)'
        }
    else:
        return {
            'estimated_satisfaction': 3,
            'confidence': 0.4,
            'reason': 'Normal duration'
        }
```

---

### Phase 2: LLM 기반 자동 품질 평가 (선택적)

#### 2-1. 답변 관련성 자동 평가

**평가 프롬프트**:
```python
def evaluate_answer_quality(
    self,
    question: str,
    answer: str,
    sources: List[Dict]
) -> Dict:
    """
    LLM을 사용한 답변 품질 자동 평가

    비용: GPT-4o-mini 기준 ~100 토큰 = $0.00002 (0.002원)
    """

    evaluation_prompt = f"""
다음 질문에 대한 답변을 평가해주세요:

**질문**: {question}

**답변**: {answer}

**평가 기준**:
1. 관련성 (Relevance): 답변이 질문에 직접적으로 답하는가? (1-5)
2. 완전성 (Completeness): 질문에 필요한 정보를 충분히 제공하는가? (1-5)
3. 정확성 (Accuracy): 제공된 정보가 출처와 일치하는가? (1-5)

**출력 형식** (JSON):
{{
    "relevance": 1-5,
    "completeness": 1-5,
    "accuracy": 1-5,
    "overall_quality": 1-5,
    "issues": ["문제점1", "문제점2", ...],
    "is_acceptable": true/false
}}

출처 문서 수: {len(sources)}개
"""

    # GPT-4o-mini로 평가 (저렴하고 빠름)
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "답변 품질 평가 전문가"},
            {"role": "user", "content": evaluation_prompt}
        ],
        temperature=0.3,
        max_tokens=200
    )

    evaluation = json.loads(response.choices[0].message.content)

    # session_context에 평가 결과 저장
    # ...

    return evaluation
```

**통합 예시**:
```python
# search_agent.py:search() 메서드 끝부분

# 답변 생성 후
answer = self._generate_answer(...)

# 🆕 자동 품질 평가 (선택적)
if settings.ENABLE_AUTO_EVALUATION:
    evaluation = self._evaluate_answer_quality(
        question=question,
        answer=answer,
        sources=unique_documents
    )

    # 품질이 낮으면 경고 로그
    if evaluation['overall_quality'] < 3:
        logger.warning(
            f"⚠️ Low quality answer detected: "
            f"relevance={evaluation['relevance']}/5, "
            f"issues={evaluation['issues']}"
        )

    # 메타데이터에 평가 추가
    metadata['auto_evaluation'] = evaluation
```

**비용 분석**:
```
1회 평가: ~100 토큰 × GPT-4o-mini = $0.00002
1,000회: $0.02 (20원)
10,000회: $0.20 (200원)

→ 매우 저렴! 모든 답변 평가 가능
```

**장점**:
- ✅ 완전 자동화
- ✅ 비용 매우 저렴
- ✅ 일관된 평가 기준
- ✅ 즉시 피드백

**단점**:
- ⚠️ LLM 의존 (평가 자체도 오류 가능)
- ⚠️ 약간의 비용 발생
- ⚠️ 평가 시간 추가 (~0.5초)

---

#### 2-2. 출처-답변 일치성 검증

```python
def verify_answer_source_alignment(
    self,
    answer: str,
    sources: List[Dict]
) -> Dict:
    """
    답변이 실제 출처 문서에서 추출되었는지 검증

    Hallucination 방지
    """

    verification_prompt = f"""
다음 답변이 제공된 출처 문서들에서 실제로 추출된 내용인지 검증하세요:

**답변**: {answer}

**출처 문서들**:
{self._format_sources_for_verification(sources)}

**검증 사항**:
1. 답변의 각 주장이 출처에 근거하는가?
2. 환각(Hallucination) 의심 내용이 있는가?
3. 출처에 없는 정보를 추가했는가?

**출력 형식** (JSON):
{{
    "is_grounded": true/false,  # 출처에 근거함
    "hallucination_risk": 0.0-1.0,  # 환각 위험도
    "unsupported_claims": ["주장1", "주장2", ...],
    "confidence": 0.0-1.0
}}
"""

    # ...
```

---

### Phase 3: 통합 품질 점수 시스템

#### 3-1. 복합 품질 지표

```python
class AnswerQualityMetrics:
    """답변 품질 통합 평가"""

    def calculate_composite_score(
        self,
        session_id: str
    ) -> Dict:
        """
        여러 지표를 종합한 최종 품질 점수

        가중치:
        - 사용자 피드백: 50% (가장 중요)
        - LLM 자동 평가: 30%
        - 암묵적 신호: 20% (재질문, 세션 지속 시간)
        """

        # 1. 사용자 피드백 (명시적)
        user_feedback = self._get_user_feedback(session_id)
        user_score = user_feedback['satisfaction'] / 5.0 if user_feedback else None

        # 2. LLM 자동 평가
        auto_eval = self._get_auto_evaluation(session_id)
        auto_score = auto_eval['overall_quality'] / 5.0 if auto_eval else None

        # 3. 암묵적 신호
        implicit = self._get_implicit_signals(session_id)
        implicit_score = implicit['estimated_satisfaction'] / 5.0

        # 가중 평균
        scores = []
        weights = []

        if user_score is not None:
            scores.append(user_score)
            weights.append(0.5)

        if auto_score is not None:
            scores.append(auto_score)
            weights.append(0.3)

        scores.append(implicit_score)
        weights.append(0.2)

        # 정규화된 가중치 합
        total_weight = sum(weights)
        composite_score = sum(s * w for s, w in zip(scores, weights)) / total_weight

        return {
            'composite_score': composite_score,  # 0.0 - 1.0
            'user_feedback_score': user_score,
            'auto_eval_score': auto_score,
            'implicit_score': implicit_score,
            'confidence': self._calculate_confidence(user_score, auto_score),
            'data_sources': {
                'has_user_feedback': user_score is not None,
                'has_auto_eval': auto_score is not None,
                'has_implicit': True
            }
        }
```

#### 3-2. 실제 성공률 재계산

```python
def recalculate_tool_performance_with_quality(self):
    """
    품질 점수를 반영한 실제 도구 성공률 재계산

    기존: success = (문서 개수 > 0)
    개선: success = (문서 개수 > 0) AND (품질 점수 >= 0.6)
    """

    # tool_performance_stats 재집계
    query = """
        INSERT INTO tool_performance_stats_v2 (
            tool_name,
            question_type,
            total_executions,
            quality_success_count,  -- 🆕 품질 기준 성공
            quality_success_rate,   -- 🆕 품질 기반 성공률
            avg_quality_score,      -- 🆕 평균 품질 점수
            ...
        )
        SELECT
            t.tool_name,
            t.question_type,
            COUNT(*) as total_executions,
            SUM(CASE
                WHEN t.success = TRUE
                AND q.composite_score >= 0.6
                THEN 1 ELSE 0
            END) as quality_success_count,
            AVG(CASE
                WHEN t.success = TRUE
                THEN q.composite_score
                ELSE NULL
            END) as avg_quality_score,
            ...
        FROM tool_performance_log t
        LEFT JOIN answer_quality_scores q
            ON t.session_id = q.session_id
        GROUP BY t.tool_name, t.question_type
    """
```

---

## 📊 새로운 테이블 스키마

### answer_quality_scores (품질 평가 테이블)

```sql
CREATE TABLE answer_quality_scores (
    id INT PRIMARY KEY AUTO_INCREMENT,
    session_id VARCHAR(36) NOT NULL,

    -- 사용자 피드백 (명시적)
    user_satisfaction INT,              -- 1-5
    user_is_relevant BOOLEAN,
    user_comment TEXT,
    user_feedback_at TIMESTAMP,

    -- LLM 자동 평가
    auto_relevance INT,                 -- 1-5
    auto_completeness INT,              -- 1-5
    auto_accuracy INT,                  -- 1-5
    auto_overall_quality INT,           -- 1-5
    auto_is_acceptable BOOLEAN,
    auto_issues JSON,                   -- ["issue1", "issue2"]
    auto_evaluated_at TIMESTAMP,

    -- 암묵적 신호
    has_re_question BOOLEAN,            -- 재질문 발생
    session_duration_sec FLOAT,         -- 세션 지속 시간
    estimated_satisfaction INT,         -- 추정 만족도 1-5

    -- 통합 점수
    composite_score FLOAT,              -- 0.0-1.0 종합 품질 점수
    confidence_level FLOAT,             -- 0.0-1.0 신뢰도

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    KEY idx_session (session_id),
    KEY idx_composite (composite_score),
    FOREIGN KEY (session_id) REFERENCES session_context(session_id)
);
```

---

## 🚀 구현 우선순위 및 로드맵

### 즉시 구현 (Week 1-2)

**1. 사용자 피드백 API 추가**
```bash
# main.py에 피드백 엔드포인트 추가
POST /api/feedback/{session_id}
  - satisfaction: 1-5
  - is_relevant: true/false
  - comment: string

# session_context_repository.py에 메서드 추가
update_satisfaction()
```

**2. session_context 활용 강화**
```python
# avg_satisfaction 필드 활용 시작
# conversation_history JSON에 피드백 저장
```

**3. 암묵적 피드백 감지**
```python
# 재질문 패턴 감지
# 세션 지속 시간 분석
```

---

### 단기 구현 (Week 3-4)

**4. LLM 자동 평가 (선택적)**
```python
# settings.py에 플래그 추가
ENABLE_AUTO_EVALUATION = False  # 비용 고려해서 선택적 활성화

# 저렴한 GPT-4o-mini 사용 (~$0.00002/회)
```

**5. answer_quality_scores 테이블 생성**
```sql
CREATE TABLE answer_quality_scores ...
```

---

### 중기 구현 (Month 2)

**6. 품질 점수 기반 학습**
```python
# tool_performance_stats_v2 테이블
# 품질 점수를 반영한 실제 성공률 계산
```

**7. 모니터링 대시보드 통합**
```python
# 품질 지표 시각화
# 도구별 품질 비교
# 시간대별 품질 추이
```

---

## 💡 권장 전략

### 초기 (0-1,000회)

**목표**: 사용자 피드백 수집 기반 구축

```yaml
활성화:
  - 피드백 API ✅
  - 암묵적 신호 감지 ✅
  - avg_satisfaction 활용 ✅

비활성화:
  - LLM 자동 평가 ❌ (비용 절감)
  - use_learning ❌ (데이터 수집 중)

목표:
  - 피드백 수집률 20% 이상
  - 200개 이상 피드백 확보
```

---

### 중기 (1,000-5,000회)

**목표**: 품질 기반 학습 시작

```yaml
활성화:
  - use_learning = True ✅
  - LLM 자동 평가 (샘플링 10%) ✅
  - 품질 점수 기반 성공률 ✅

개선:
  - 품질 낮은 도구 필터링
  - 고품질 답변 패턴 학습
  - 폴백 전략 품질 기반 조정
```

---

### 장기 (5,000회+)

**목표**: 완전 자동화된 품질 관리

```yaml
완성:
  - 모든 답변 자동 평가 ✅
  - 품질 임계값 동적 조정 ✅
  - A/B 테스트 (품질 vs 속도) ✅
  - 실시간 품질 알림 ✅
```

---

## 📈 기대 효과

### Before (현재)
```
성공 기준: 문서 개수 > 0

질문: "Docker 설치 방법"
결과: "Docker 개념 설명" 10개 문서
기록: success=True (95% 성공률!)
실제: 사용자 불만족 ❌

→ 1,000회 후 use_learning=True
→ 계속 엉뚱한 도구 추천!
```

### After (품질 평가 적용)
```
성공 기준: (문서 개수 > 0) AND (품질 점수 >= 0.6)

질문: "Docker 설치 방법"
결과: "Docker 개념 설명" 10개 문서
피드백: satisfaction=2/5, is_relevant=False
기록: success=False (품질 부족!)

→ 1,000회 후 use_learning=True
→ 실제로 좋은 도구만 추천! ✅
```

**개선 지표**:
- 🎯 정확도: 40% → 85%
- 😊 사용자 만족도: 2.5/5 → 4.2/5
- ⚡ 재질문 비율: 35% → 8%
- 💰 비용 효율: 불필요한 재검색 감소

---

## 🎯 결론

**핵심 메시지**:
> "문서를 찾았다" ≠ "올바른 답변"
>
> 품질 평가 없는 학습 = 잘못된 패턴 강화

**즉시 조치**:
1. ✅ 피드백 API 구현 (1-2일)
2. ✅ session_context.avg_satisfaction 활용
3. ✅ 재질문 패턴 감지

**선택적 조치**:
- LLM 자동 평가 (비용 vs 효과 검토)
- answer_quality_scores 테이블 추가

**장기 목표**:
- 품질 기반 학습 시스템 완성
- 실시간 품질 모니터링
- 자동 품질 관리

---

**작성일**: 2025-11-07
**우선순위**: 🔴 HIGH (use_learning 활성화 전 필수)
**예상 구현 기간**: 1-2주 (Phase 1), 1개월 (Phase 2)
