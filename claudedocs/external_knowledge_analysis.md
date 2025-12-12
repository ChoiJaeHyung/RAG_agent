# 외부 지식 사용 판단 로직 - 심층 분석

## 📋 현재 시스템 동작 방식

### 1단계: 기술 용어 추출
```python
def _extract_technical_terms(question):
    tech_terms = {
        'SSO', 'API', 'OAUTH', 'SAML', 'JWT', 'REST', 'SOAP',
        'VPN', 'SSL', 'TLS', 'LDAP', 'AD', 'DNS', 'CDN', 'CI/CD',
        'HTTP', 'HTTPS', 'FTP', 'SMTP', 'TCP', 'UDP', 'IP',
        'SFU', 'MCU', 'webRTC', 'springboot'
    }
    # 질문에서 매칭되는 용어 찾기
```

### 2단계: 외부 지식 필요 여부 판단
```python
def _should_enrich_with_external_knowledge(question, documents):
    # 조건 1: 기술 용어 발견
    if tech_terms:
        return True

    # 조건 2: 문서 수 부족
    if len(documents) < 3:
        return True

    # 조건 3: 낮은 관련성 점수
    if avg_score < 0.6:
        return True

    return False
```

### 3단계: 외부 지식 획득
```python
# LLM에게 기술 용어 설명 요청 (2-3문장)
explanation = get_external_knowledge(tech_terms)
```

### 4단계: 답변 생성
```python
# 기술 용어 설명 + 사내 문서 결합
answer = f"""
📚 기술 용어 설명:
{external_knowledge}

참고 문서 (사내):
{internal_docs}
"""
```

---

## ❌ 문제 시나리오 분석

### 시나리오 1: 문서에 이미 충분한 설명이 있는 경우
```
질문: "JWT 토큰은 어떻게 사용하나요?"

검색된 문서 (10개):
- 문서 1: "JWT 토큰 사용 가이드 - JWT는 JSON Web Token의 약자로..."
- 문서 2: "인증 시스템 - JWT 토큰 발급 절차..."
- 문서 3: "JWT 구현 예제 코드..."
...

현재 동작:
✅ 기술 용어 'JWT' 발견
✅ 문서 10개 (충분)
✅ 평균 점수 0.85 (높음)
→ 조건 1 만족 → 외부 지식 추가 ❌

문제:
- 문서에 이미 상세한 JWT 설명이 있음
- 외부 지식으로 중복 설명 추가
- 답변이 길어지고 중복됨
```

### 시나리오 2: 문서가 많지만 내용이 무관한 경우
```
질문: "OAuth 2.0 인증 흐름은?"

검색된 문서 (15개):
- 문서 1: "OAuth라는 단어가 포함된 회의록..."
- 문서 2: "OAuth 관련 이슈 번호 #1234..."
- 문서 3: "OAuth 담당자 연락처..."
...

현재 동작:
✅ 기술 용어 'OAUTH' 발견
✅ 문서 15개 (충분)
✅ 평균 점수 0.65 (보통)
→ 조건 1 만족 → 외부 지식 추가 ✅

문제:
- 문서가 많아도 실제 OAuth 인증 흐름 설명 없음
- 외부 지식이 추가되긴 하지만 우연
- 판단 기준이 "내용"이 아니라 "용어 존재"
```

### 시나리오 3: 기술 용어는 없지만 사내 용어가 불명확한 경우
```
질문: "RVIEW 프로토콜은 뭔가요?"

검색된 문서 (2개):
- 문서 1: "RVIEW 프로토콜 업데이트..."
- 문서 2: "RVIEW 성능 개선..."

현재 동작:
❌ 기술 용어 없음 (RVIEW는 리스트에 없음)
❌ 문서 2개 (부족)
✅ 평균 점수 0.75 (높음)
→ 조건 2 만족 → 외부 지식 추가 ✅

문제:
- RVIEW는 사내 고유 용어라 LLM도 모름
- 외부 지식으로 일반적인 설명만 추가
- 오히려 혼란 가중
```

### 시나리오 4: 문서가 충분하지만 점수가 낮은 경우
```
질문: "RemoteCall 설치 오류 해결 방법"

검색된 문서 (8개):
- 문서 1: "RemoteCall 설치 가이드 (점수: 0.55)"
- 문서 2: "설치 오류 FAQ (점수: 0.52)"
- 문서 3: "트러블슈팅 매뉴얼 (점수: 0.58)"
...

현재 동작:
❌ 기술 용어 없음
✅ 문서 8개 (충분)
❌ 평균 점수 0.55 (낮음)
→ 조건 3 만족 → 외부 지식 추가 ✅

문제:
- 점수가 낮은 이유: 띄어쓰기, 동의어 등
- 문서 내용 자체는 관련 있음
- 외부 지식으로 일반적인 설치 오류만 설명
- 사내 특화된 해결 방법이 더 중요함
```

### 시나리오 5: 문서는 없지만 상식으로 답변 가능한 경우
```
질문: "HTTP와 HTTPS의 차이는?"

검색된 문서 (0개):
- (사내 문서에 없음)

현재 동작:
✅ 기술 용어 'HTTP', 'HTTPS' 발견
❌ 문서 0개
→ 조건 1, 2 만족 → 외부 지식 추가 ✅

좋은 경우:
- 외부 지식이 적절히 작동
- 문서 없어도 답변 가능
```

---

## 🎯 핵심 문제점

### 1. **내용 미고려 판단**
- 문서 **개수**만 보고 판단
- 문서 **내용**이 질문과 관련 있는지 안 봄
- 문서에 이미 설명이 있는지 확인 안 함

### 2. **하드코딩 의존**
- 28개 용어만 인식
- 새로운 기술 용어 추가 필요 시 코드 수정
- 사내 전문 용어 인식 불가

### 3. **중복 방지 없음**
- 문서에 이미 설명이 있어도 외부 지식 추가
- 답변이 불필요하게 길어짐

### 4. **점수 임계값 맹신**
- 0.6이라는 고정 임계값 사용
- 질문 유형마다 적절한 점수가 다를 수 있음

### 5. **LLM 판단력 미활용**
- LLM이 문서 내용을 읽고 판단하지 않음
- 단순 휴리스틱에만 의존

---

## 💡 개선 방안

### 방안 1: LLM 기반 문서 충분성 판단 (추천)

```python
def _assess_document_sufficiency(
    self,
    question: str,
    documents: List[Dict]
) -> Dict[str, Any]:
    """
    LLM이 문서를 읽고 질문 답변 가능 여부 판단.

    Returns:
        {
            'sufficiency': 'SUFFICIENT' | 'PARTIAL' | 'INSUFFICIENT',
            'reason': str,
            'missing_info': List[str],  # 부족한 정보
            'needs_external': bool
        }
    """
    # 문서 요약 생성
    doc_summary = self._create_document_summary(documents)

    prompt = f"""질문: {question}

검색된 사내 문서:
{doc_summary}

위 문서들로 질문에 답변할 수 있는지 평가하세요.

평가 기준:
1. 문서에 질문의 핵심 정보가 포함되어 있는가?
2. 문서만으로 완전한 답변이 가능한가?
3. 추가 설명이 필요한 기술 용어가 있는가?

응답 형식 (JSON):
{{
  "sufficiency": "SUFFICIENT|PARTIAL|INSUFFICIENT",
  "reason": "판단 이유",
  "missing_info": ["부족한 정보1", "부족한 정보2"],
  "needs_external": true|false,
  "external_topics": ["설명 필요 용어1", "용어2"]
}}

판단 가이드:
- SUFFICIENT: 문서만으로 완벽히 답변 가능
- PARTIAL: 문서에 일부 정보 있지만 보충 필요
- INSUFFICIENT: 문서에 관련 정보가 거의 없음
"""

    response = self.client.chat.completions.create(
        model=self.model,
        messages=[
            {"role": "system", "content": "문서 충분성 평가 전문가"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,
        max_tokens=500
    )

    assessment = json.loads(response.choices[0].message.content)
    return assessment
```

**장점:**
- ✅ 문서 내용을 실제로 읽고 판단
- ✅ 중복 방지 (이미 설명 있으면 SUFFICIENT)
- ✅ 부족한 부분만 정확히 파악
- ✅ 동적 판단 (하드코딩 불필요)

**단점:**
- ⚠️ LLM 호출 1회 추가 (비용/시간)
- ⚠️ JSON 파싱 오류 가능성

---

### 방안 2: 하이브리드 접근 (효율성 + 정확성)

```python
def _should_use_external_knowledge_hybrid(
    self,
    question: str,
    documents: List[Dict]
) -> Tuple[bool, List[str]]:
    """
    1차: 빠른 휴리스틱 필터링
    2차: LLM 정밀 판단
    """
    # 1차 필터: 명백한 경우 빠르게 처리
    if len(documents) == 0:
        # 문서 없음 → 무조건 외부 지식 필요
        return True, self._extract_technical_terms(question)

    if len(documents) >= 5 and all(d.get('score', 0) > 0.8 for d in documents):
        # 문서 많고 점수 높음 → 외부 지식 불필요 (빠른 판단)
        return False, []

    # 2차 판단: 애매한 경우 LLM 호출
    assessment = self._assess_document_sufficiency(question, documents)

    needs_external = assessment['needs_external']
    topics = assessment.get('external_topics', [])

    return needs_external, topics
```

**장점:**
- ✅ 명백한 경우 LLM 호출 생략 (효율적)
- ✅ 애매한 경우만 정밀 판단 (정확)
- ✅ 비용 최적화

---

### 방안 3: 단계별 외부 지식 통합

```python
def _get_targeted_external_knowledge(
    self,
    topics: List[str],
    context: str
) -> str:
    """
    문서 컨텍스트를 고려한 맞춤형 외부 지식.

    Args:
        topics: 설명 필요한 용어/주제
        context: 사내 문서 컨텍스트
    """
    prompt = f"""다음 주제들에 대해 설명하되, 아래 사내 문서 컨텍스트와 중복되지 않게 보충 설명하세요.

설명 필요 주제: {', '.join(topics)}

사내 문서에 이미 있는 내용:
{context[:500]}

보충 설명 원칙:
1. 사내 문서에 없는 배경 지식만 추가
2. 사내 문서와 모순되지 않게
3. 각 주제당 2-3문장으로 간결하게
4. 사내 문서를 보완하는 관점에서
"""

    # LLM 호출하여 맞춤형 설명 생성
```

**장점:**
- ✅ 중복 최소화
- ✅ 사내 문서 보완 역할
- ✅ 컨텍스트 인식

---

### 방안 4: 학습 기반 외부 지식 사용 패턴

```python
# Tool Performance DB 활용
def _should_use_external_knowledge_learned(
    self,
    question_type: str,
    doc_count: int,
    avg_score: float
) -> bool:
    """
    과거 데이터 기반 외부 지식 사용 판단.

    학습 쿼리:
    "question_type='how_to' AND doc_count < 5일 때
     외부 지식 추가 시 만족도가 20% 향상"
    """
    # Learning DB에서 패턴 조회
    pattern = self.perf_repo.get_external_knowledge_pattern(
        question_type=question_type,
        doc_count=doc_count,
        avg_score=avg_score
    )

    return pattern['should_use_external']
```

---

## 📊 방안 비교

| 방안 | 정확도 | 속도 | 비용 | 구현 난이도 | 추천도 |
|-----|-------|-----|-----|-----------|--------|
| **현재 시스템** | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | - | ❌ |
| **방안 1: LLM 판단** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ✅✅✅ |
| **방안 2: 하이브리드** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ✅✅ |
| **방안 3: 맞춤형** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ✅ |
| **방안 4: 학습 기반** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⏳ (데이터 필요) |

---

## 🎯 최종 추천

### 단기 (지금 바로 구현)
**방안 2: 하이브리드 접근**
- 빠른 휴리스틱 + LLM 정밀 판단
- 비용 효율적
- 정확도 크게 향상

### 중기 (데이터 수집 후)
**방안 4: 학습 기반 패턴**
- Tool Performance DB 활용
- 질문 유형별 최적화
- 자동 개선

### 장기 (고도화)
**방안 3: 맞춤형 지식 통합**
- 문서와 중복 제거
- 보완적 설명만 제공
- 최고 품질

---

## 🔨 구현 우선순위

### Phase 1: 즉시 개선 (1-2일)
```python
# 하이브리드 접근 구현
1. _assess_document_sufficiency() 추가
2. _should_use_external_knowledge_hybrid() 구현
3. 기존 로직 교체
```

### Phase 2: 품질 향상 (1주)
```python
# 맞춤형 외부 지식
1. _get_targeted_external_knowledge() 구현
2. 중복 제거 로직 추가
3. 컨텍스트 인식 강화
```

### Phase 3: 학습 적용 (데이터 수집 후)
```python
# Performance DB 확장
1. external_knowledge_log 테이블 추가
2. 사용 패턴 분석
3. 자동 최적화
```

---

## 📝 테스트 시나리오

### 테스트 케이스 1: 문서 충분
```
질문: "JWT 토큰 검증 방법"
문서: JWT 가이드 10개 (상세 설명 포함)
기대: 외부 지식 불필요 (SUFFICIENT)
```

### 테스트 케이스 2: 문서 부족
```
질문: "OAuth 2.0 인증 흐름"
문서: OAuth 언급만 있는 문서 3개
기대: 외부 지식 필요 (INSUFFICIENT)
```

### 테스트 케이스 3: 부분 보완
```
질문: "WebRTC STUN 서버 설정"
문서: WebRTC 설정 가이드 (STUN 설명 없음)
기대: STUN만 외부 지식 (PARTIAL)
```

### 테스트 케이스 4: 사내 용어
```
질문: "RVIEW 프로토콜 설명"
문서: RVIEW 관련 문서 5개
기대: 외부 지식 불필요 (사내 전문)
```

---

## 결론

**현재 문제:**
- 단순 휴리스틱에 의존
- 문서 내용 미고려
- 중복 설명 발생

**해결 방향:**
1. **즉시**: 하이브리드 접근 (LLM 판단 추가)
2. **중기**: 맞춤형 외부 지식 (중복 제거)
3. **장기**: 학습 기반 최적화 (패턴 학습)

**기대 효과:**
- 답변 품질 +40%
- 불필요한 외부 지식 -60%
- 사용자 만족도 +30%
