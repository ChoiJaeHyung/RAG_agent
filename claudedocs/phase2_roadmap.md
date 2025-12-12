# Phase 2 로드맵: 성능 최적화 및 학습 기반 개선

## 📋 Phase 2 개요

**목표**: 하이브리드 시스템의 성능 최적화 및 자동 학습 기능 구축
**기간**: 1-2개월 (단계별 진행)
**전제조건**: Phase 1 완료 (하이브리드 시스템 구축 ✅)

---

## 🎯 우선순위별 작업 항목

### 🔴 High Priority (즉시 시작)

#### 1. 프로덕션 모니터링 시스템 구축
**목표**: 실제 운영 데이터 수집 및 분석

**작업 항목**:
- [ ] 외부 지식 판단 로깅 강화
  - 판단 방식 (Fast Heuristic vs LLM Judgment)
  - LLM 판단 결과 (SUFFICIENT/PARTIAL/INSUFFICIENT)
  - 실제 외부 지식 사용 여부
  - 사용자 피드백 (만족도)

- [ ] 메트릭 수집 테이블 설계
  ```sql
  CREATE TABLE external_knowledge_metrics (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      session_id VARCHAR(50),
      question VARCHAR(500),
      document_count INT,
      avg_score DECIMAL(3,2),

      -- 판단 정보
      decision_method ENUM('fast_heuristic', 'llm_judgment'),
      sufficiency_level ENUM('SUFFICIENT', 'PARTIAL', 'INSUFFICIENT', 'N/A'),
      needs_external BOOLEAN,
      missing_topics TEXT,  -- JSON array

      -- 비용 추적
      llm_calls INT DEFAULT 0,
      tokens_used INT DEFAULT 0,

      -- 품질 지표
      answer_length INT,
      external_knowledge_used BOOLEAN,

      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      INDEX idx_session (session_id),
      INDEX idx_created (created_at)
  );
  ```

- [ ] 대시보드 구축
  - 일일/주간/월간 통계
  - Fast Heuristic vs LLM Judgment 비율
  - 외부 지식 사용률 추이
  - 비용 추적

**예상 기간**: 1주
**예상 비용 절감**: 모니터링을 통한 최적화로 5-10% 절감

---

#### 2. 학습 기반 휴리스틱 임계값 최적화
**목표**: 데이터 기반으로 Fast Heuristic 임계값 자동 조정

**현재 임계값 (하드코딩)**:
```python
if len(documents) >= 5 and avg_score > 0.8:
    # 외부 지식 불필요
```

**작업 항목**:
- [ ] 최적 임계값 분석 스크립트 작성
  ```python
  def analyze_optimal_thresholds(metrics_data):
      """
      수집된 데이터로 최적 임계값 계산

      분석 목표:
      1. False Positive 최소화 (외부 지식 불필요인데 필요 판단)
      2. False Negative 최소화 (외부 지식 필요인데 불필요 판단)
      3. LLM 호출 비율 최소화 (비용 절감)
      """
      # 문서 개수별 정확도 분석
      for doc_count in range(1, 20):
          for score_threshold in [0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9]:
              accuracy = calculate_accuracy(doc_count, score_threshold)

      return optimal_doc_count, optimal_score
  ```

- [ ] 동적 임계값 적용
  ```python
  # settings.py 추가
  HEURISTIC_DOC_COUNT_THRESHOLD = int(os.getenv("HEURISTIC_DOC_COUNT", "5"))
  HEURISTIC_SCORE_THRESHOLD = float(os.getenv("HEURISTIC_SCORE", "0.8"))

  # 주간 자동 재조정
  def update_thresholds_weekly():
      metrics = fetch_last_week_metrics()
      new_doc_count, new_score = analyze_optimal_thresholds(metrics)
      update_env_config(new_doc_count, new_score)
  ```

- [ ] A/B 테스트 프레임워크
  - 50% 트래픽: 현재 임계값 (5, 0.8)
  - 50% 트래픽: 새 임계값 (학습 기반)
  - 1주간 성능 비교 후 적용

**예상 기간**: 1-2주
**예상 효과**: LLM 호출 55% → 40% (비용 -15%)

---

### 🟡 Medium Priority (1개월 내)

#### 3. LLM 판단 결과 캐싱
**목표**: 유사 질문·문서 조합의 판단 결과 재사용

**작업 항목**:
- [ ] 캐시 키 설계
  ```python
  def generate_cache_key(question: str, documents: List[Dict]) -> str:
      """
      질문 + 문서 내용 해시로 캐시 키 생성
      """
      # 질문 정규화
      normalized_q = normalize_question(question)

      # 문서 요약 (상위 5개, 각 200자)
      doc_summary = ""
      for doc in documents[:5]:
          doc_summary += doc['text'][:200]

      # SHA256 해시
      cache_key = hashlib.sha256(
          f"{normalized_q}:{doc_summary}".encode()
      ).hexdigest()

      return cache_key
  ```

- [ ] Redis 캐싱 레이어 추가
  ```python
  # repositories/cache_repository.py
  class AssessmentCacheRepository:
      def __init__(self):
          self.redis = redis.Redis(
              host=settings.REDIS_HOST,
              port=settings.REDIS_PORT,
              decode_responses=True
          )

      def get_cached_assessment(self, cache_key: str) -> Optional[Dict]:
          """캐시된 판단 결과 조회"""
          cached = self.redis.get(f"assessment:{cache_key}")
          if cached:
              return json.loads(cached)
          return None

      def cache_assessment(
          self,
          cache_key: str,
          assessment: Dict,
          ttl: int = 86400  # 24시간
      ):
          """판단 결과 캐싱"""
          self.redis.setex(
              f"assessment:{cache_key}",
              ttl,
              json.dumps(assessment)
          )
  ```

- [ ] SearchAgent 통합
  ```python
  def _assess_document_sufficiency(self, question, documents):
      # 캐시 확인
      cache_key = generate_cache_key(question, documents)
      cached = self.cache_repo.get_cached_assessment(cache_key)

      if cached:
          logger.info(f"✅ Cache hit: {cache_key[:16]}...")
          return cached

      # LLM 호출
      assessment = self._llm_assess(question, documents)

      # 캐싱
      self.cache_repo.cache_assessment(cache_key, assessment)

      return assessment
  ```

- [ ] 캐시 효율 모니터링
  - Cache hit rate
  - 절감된 LLM 호출 수
  - 절감된 비용

**예상 기간**: 1주
**예상 효과**: Cache hit 20-30% → 비용 추가 -10% 절감

---

#### 4. 외부 지식 품질 개선
**목표**: LLM이 생성하는 외부 지식 설명의 품질 향상

**작업 항목**:
- [ ] 설명 템플릿 개선
  ```python
  # 현재
  prompt = f"""다음 기술 용어들에 대해 간단하고 명확하게 설명해주세요.
  각 용어당 2-3문장으로 핵심만 설명하세요.

  용어: {', '.join(terms)}"""

  # 개선
  prompt = f"""다음 기술 용어들을 IT 서버/네트워크 관리자 관점에서 설명해주세요.

  용어: {', '.join(topics)}

  각 용어마다 다음 형식으로 설명:
  **[용어]**:
  - 정의: [1문장으로 핵심 개념]
  - 사용 사례: [실무에서 어떻게 사용되는지]
  - 관련 기술: [연관된 다른 기술]

  예시:
  **Docker**:
  - 정의: 애플리케이션을 컨테이너로 패키징하여 일관된 실행 환경을 제공하는 플랫폼
  - 사용 사례: 개발 환경 통일, CI/CD 파이프라인, 마이크로서비스 배포
  - 관련 기술: Kubernetes, Docker Compose, 컨테이너 오케스트레이션
  """
  ```

- [ ] Few-shot learning 적용
  - 좋은 설명 예시 수집 (5-10개)
  - 프롬프트에 예시 포함
  - 일관된 품질 유지

- [ ] 설명 길이 최적화
  - 너무 짧음: 정보 부족
  - 너무 김: 토큰 낭비, 가독성 저하
  - 최적 길이: 용어당 150-250 tokens

**예상 기간**: 3-5일
**예상 효과**: 사용자 만족도 +10-15%

---

### 🟢 Low Priority (2개월 내)

#### 5. 다국어 지원
**목표**: 영어, 일본어 질문 패턴 지원

**작업 항목**:
- [ ] 영어 패턴 추가
  ```python
  definition_patterns = [
      # 한국어
      r'(.+?)란\s*무엇',
      r'(.+?)는\s*뭔가',

      # 영어
      r'what\s+is\s+(.+)',
      r'explain\s+(.+)',
      r'what\s+are\s+(.+)',
      r'define\s+(.+)',

      # 일본어
      r'(.+?)とは何',
      r'(.+?)って何',
  ]
  ```

- [ ] 다국어 기술 용어 사전
  ```python
  TECH_TERMS_MULTILANG = {
      'en': ['SSO', 'API', 'OAuth', ...],
      'ja': ['SSO', 'API', 'OAuth', ...],
      'ko': ['SSO', 'API', 'OAuth', ...]
  }
  ```

**예상 기간**: 3-5일
**예상 효과**: 글로벌 사용자 지원

---

#### 6. 실시간 외부 지식 업데이트
**목표**: 최신 기술 트렌드 자동 반영

**작업 항목**:
- [ ] 기술 용어 자동 확장
  - 새로운 기술 용어 자동 감지
  - 빈도 기반 하드코딩 리스트 업데이트

- [ ] 외부 지식 소스 연동
  - Wikipedia API
  - Stack Overflow API
  - 공식 문서 크롤링

**예상 기간**: 1-2주
**예상 효과**: 최신 기술 대응력 향상

---

#### 7. 개인화된 설명 수준
**목표**: 사용자 프로필 기반 설명 깊이 조절

**작업 항목**:
- [ ] 사용자 프로필 테이블
  ```sql
  CREATE TABLE user_profiles (
      user_id VARCHAR(50) PRIMARY KEY,
      expertise_level ENUM('beginner', 'intermediate', 'expert'),
      preferred_detail ENUM('concise', 'detailed'),
      last_updated TIMESTAMP
  );
  ```

- [ ] 프로필 기반 설명 생성
  ```python
  def _get_external_knowledge(self, topics, user_profile):
      if user_profile['expertise_level'] == 'beginner':
          prompt = "초보자도 이해할 수 있도록 쉽게 설명..."
      elif user_profile['expertise_level'] == 'expert':
          prompt = "전문가 관점에서 기술적 세부사항 포함..."
  ```

**예상 기간**: 1주
**예상 효과**: 사용자별 맞춤 답변

---

## 📊 Phase 2 예상 효과 종합

### 비용 절감 효과

| 개선 항목 | 현재 비용 | 절감 효과 | 개선 후 비용 |
|----------|----------|----------|------------|
| **Phase 1 (현재)** | $45.45/월 | - | $45.45/월 |
| + 학습 기반 임계값 최적화 | $45.45 | -15% | $38.63 |
| + LLM 캐싱 | $38.63 | -10% | $34.77 |
| **Phase 2 합계** | $45.45 | **-23.5%** | **$34.77/월** |

### 품질 개선 효과

| 지표 | Phase 1 | Phase 2 목표 | 총 개선 |
|------|---------|------------|---------|
| 답변 정확도 | +35% | +45% | **+80%** |
| 사용자 만족도 | +30% | +45% | **+75%** |
| 응답 속도 | 기준 | -20% | **-20%** |

### ROI 분석

```
Phase 1 투자: $1.49/월 증가
Phase 2 투자: $10.68/월 절감

순 이익: $12.17/월
연간 이익: $146.04
ROI: 무한대 (비용 감소)
```

---

## 🗓️ 구현 일정

### Week 1-2: High Priority 시작
- ✅ Week 1: 모니터링 시스템 구축
- ✅ Week 2: 학습 기반 임계값 분석

### Week 3-4: High Priority 완료
- ✅ Week 3: 동적 임계값 적용 및 A/B 테스트
- ✅ Week 4: 결과 분석 및 최적화

### Week 5-6: Medium Priority
- ✅ Week 5: LLM 캐싱 구현
- ✅ Week 6: 외부 지식 품질 개선

### Week 7-8: Low Priority (Optional)
- 🔄 Week 7: 다국어 지원
- 🔄 Week 8: 실시간 업데이트, 개인화

---

## 📈 성공 지표 (KPI)

### 필수 지표
1. **비용 효율성**
   - LLM 호출 비율: 55% → 40% 이하
   - 월 비용: $45.45 → $35 이하

2. **품질 지표**
   - 답변 정확도: 기준 +35% → +45% 이상
   - 사용자 만족도: 기준 +30% → +45% 이상

3. **성능 지표**
   - 캐시 적중률: 20% 이상
   - 평균 응답 시간: 20% 단축

### 부가 지표
- 불필요한 외부 지식: -60% → -70%
- 재질문 비율: -8% → -12%

---

## 🚨 리스크 및 대응

### 리스크 1: 학습 데이터 부족
**대응**:
- 최소 1,000회 검색 데이터 수집 후 분석
- 초기 1개월은 현재 임계값 유지

### 리스크 2: 캐시 메모리 부족
**대응**:
- TTL 24시간 → 12시간 단축
- LRU 정책으로 오래된 캐시 자동 삭제

### 리스크 3: 성능 저하
**대응**:
- 캐시 조회는 1ms 이하로 최적화
- Redis 클러스터링 고려

---

## 🎯 Phase 2 우선순위 요약

### 즉시 시작 (이번 주)
1. ⭐⭐⭐ 프로덕션 모니터링 시스템
2. ⭐⭐⭐ 학습 기반 임계값 최적화

### 1개월 내
3. ⭐⭐ LLM 캐싱
4. ⭐⭐ 외부 지식 품질 개선

### 2개월 내 (선택)
5. ⭐ 다국어 지원
6. ⭐ 실시간 업데이트
7. ⭐ 개인화

---

## 📝 다음 단계

1. **Phase 2 착수 결정**
   - 우선순위 검토 및 승인
   - 리소스 할당 (개발자, 인프라)

2. **모니터링 시스템 구축 시작**
   - 테이블 생성
   - 로깅 강화
   - 대시보드 기획

3. **1개월 후 중간 점검**
   - 수집된 데이터 분석
   - 임계값 최적화 실행
   - 효과 측정 및 보고

---

**작성일**: 2025-11-07
**상태**: Phase 2 계획 수립 완료
**다음 액션**: Phase 2 착수 승인 대기
