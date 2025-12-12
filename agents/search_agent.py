"""
SearchAgent - RAG Agent with ReAct loop.
Autonomously selects and executes tools to find relevant documents,
then generates final answer using LLM.
"""

from typing import List, Dict, Any, Optional, Tuple
import json
import time
import tiktoken
from openai import OpenAI

from config.settings import settings
from repositories.db_repository import DatabaseRepository
from repositories.vector_repository import VectorRepository
from repositories.es_repository import ElasticsearchRepository
from repositories.tool_performance_repository import ToolPerformanceRepository
from repositories.session_context_repository import SessionContextRepository
from agents.tools.mariadb_tools import MariaDBTools
from agents.tools.vector_tools import VectorTools
from agents.tools.es_tools import ElasticsearchTools
from agents.tools.tool_registry import tool_registry
from agents.decision_logger import DecisionLogger
from agents.conversation_context import ConversationContext
from agents.answer_validator import AnswerValidator
from agents.performance_profiler import PerformanceProfiler
from agents.result_cache import result_cache
from utils.logger import logger, log_iteration, log_validation
import uuid


class SearchAgent:
    """
    Autonomous search agent using ReAct pattern.
    Iteratively selects tools, validates results, and compiles documents.
    """

    def __init__(self):
        """Initialize SearchAgent with repositories and tools."""
        # Initialize OpenAI client
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.MODEL_NAME
        self.temperature = settings.TEMPERATURE

        # Initialize repositories
        logger.info("Initializing SearchAgent repositories...")
        self.db_repo = DatabaseRepository()
        self.vector_repo = VectorRepository(db_repo=self.db_repo)
        self.es_repo = ElasticsearchRepository()
        self.perf_repo = ToolPerformanceRepository()
        self.session_repo = SessionContextRepository()

        # Initialize tools (registers them to tool_registry based on settings)
        # Log enabled/disabled tools status
        logger.info("📋 Tool configuration from .env:")
        enabled_tools = settings.get_enabled_tools()
        for tool_name, is_enabled in enabled_tools.items():
            status = "✅ enabled" if is_enabled else "❌ disabled"
            logger.info(f"   {tool_name}: {status}")

        MariaDBTools(self.db_repo)
        VectorTools(self.vector_repo)
        ElasticsearchTools(self.es_repo, self.db_repo)

        # Performance tracking settings
        self.session_id = None  # Will be set per search
        self.use_learning = False  # 스스로 학습

        # Decision logger (initialized per search)
        self.decision_logger = None  # Will be set per search

        # Answer validator for quality checks
        self.answer_validator = AnswerValidator(client=self.client)

        # Performance profiler
        self.profiler = PerformanceProfiler(enabled=True)

        # Token counter (use cl100k_base for gpt-4o models)
        try:
            self.encoding = tiktoken.encoding_for_model(self.model)
        except KeyError:
            # Fallback to cl100k_base for newer models like gpt-4o-mini
            self.encoding = tiktoken.get_encoding("cl100k_base")

        logger.info(f"✓ SearchAgent initialized with {len(tool_registry.get_tool_names())} tools")

    def search(
        self,
        question: str,
        session_id: Optional[str] = None,
        max_iterations: int = None, # type: ignore
        debug: bool = False
    ) -> Dict[str, Any]:
        """
        Execute autonomous search using ReAct loop.

        Args:
            question: User's question (may contain references like "그거", "이전에")
            session_id: Session ID for conversation context (auto-generated if None)
            max_iterations: Maximum ReAct iterations (default from settings)
            debug: Include debug information in response

        Returns:
            Search result with answer, sources, and optional debug info
        """
        # Generate or use provided session ID
        self.session_id = session_id if session_id else str(uuid.uuid4())

        # Initialize ConversationContext (세션별 관리)
        self.conversation_context = ConversationContext(session_id=self.session_id)

        # Initialize DecisionLogger
        self.decision_logger = DecisionLogger(debug=debug)

        # 🔗 Step 1: 참조 해석 (대화 컨텍스트)
        reference_resolution = self.conversation_context.resolve_references(question)
        original_question = question
        resolved_question = reference_resolution['resolved_question']

        if reference_resolution['has_reference']:
            logger.info(f"🔗 Reference resolved:")
            logger.info(f"   Original: {original_question}")
            logger.info(f"   Resolved: {resolved_question}")
            logger.info(f"   Context used: {reference_resolution.get('context_used', 0)} previous turns")

        # Use resolved question for search
        question = resolved_question

        # Analyze question type to determine strategy
        question_analysis = self._analyze_question_type(question)
        is_list_request = question_analysis['is_list_request']

        # Detect question type for learning
        question_type = self._detect_question_type(question, is_list_request)

        # Adjust parameters based on question type
        max_iterations = max_iterations or settings.MAX_ITERATIONS
        if is_list_request:
            max_iterations = min(max_iterations + 3, 10)  # Allow more iterations for list requests
            logger.info(f"📋 List request detected - increasing max_iterations to {max_iterations}")

        start_time = time.time()

        # Start performance profiling
        self.profiler.start_session()

        # Initialize tracking
        all_documents = []
        thought_process = []
        tools_used = []
        iteration_count = 0

        # C: Smart tool switching - track consecutive failures
        tool_failure_tracker = {}  # {tool_name: consecutive_zero_count}
        last_tool_name = None

        # A: Automatic tool fallback chain
        fallback_chain = [
            'search_mariadb_by_keyword',
            'search_qdrant_semantic',
            'search_elasticsearch_bm25'
        ]
        fallback_attempted = set()  # Track which fallback tools were already tried

        logger.info(f"\n{'='*60}")
        logger.info(f"Starting search for: {question[:100]}...")
        logger.info(f"Question type: {'LIST' if is_list_request else 'Q&A'}")
        logger.info(f"{'='*60}")

        # ReAct loop
        for iteration in range(1, max_iterations + 1):
            iteration_count = iteration

            logger.info(f"\n--- Iteration {iteration}/{max_iterations} ---")

            # Get agent decision (thought + action)
            self.profiler.start_timer('llm_call', {'iteration': iteration, 'phase': 'agent_decision'})
            decision = self._get_agent_decision(
                question=question,
                iteration=iteration,
                collected_docs=all_documents,
                previous_thoughts=thought_process
            )
            self.profiler.end_timer('llm_call')

            if not decision['success']:
                logger.error(f"Agent decision failed: {decision.get('error')}")
                break

            thought = decision['thought']
            action = decision['action']
            tool_name = decision['tool_name']
            tool_args = decision['tool_args']

            thought_process.append(thought)

            # Check for FINISH
            if action == "FINISH":
                logger.info(f"Agent decided to FINISH with {len(all_documents)} documents")
                # Log early stop decision
                self.decision_logger.log_early_stop(
                    iteration=iteration,
                    reason=f"Agent 자체 판단으로 종료 ({len(all_documents)}개 문서 확보)"
                )
                break

            # Log tool selection decision
            self.decision_logger.log_tool_selection(
                iteration=iteration,
                question=question,
                selected_tool=tool_name,
                tool_args=tool_args,
                thought=thought,
                context={
                    'iteration': iteration,
                    'doc_count': len(all_documents),
                    'avg_quality': self._calculate_avg_quality(all_documents),
                    'previous_tool': last_tool_name
                }
            )

            # Execute tool with tracking
            logger.info(f"Executing: {tool_name}({json.dumps(tool_args, ensure_ascii=False)})")

            # 일반 검색
            self.profiler.start_timer('tool_execution', {'tool_name': tool_name, 'iteration': iteration})
            new_docs, success = self._execute_tool_with_tracking(
                tool_name=tool_name,
                tool_args=tool_args,
                execution_order=iteration,
                is_fallback=False,
                question=question,
                question_type=question_type
            )
            self.profiler.end_timer('tool_execution', {'doc_count': len(new_docs)})

            doc_count = len(new_docs)

            if success:

                # Log iteration
                log_iteration(iteration, thought, f"{tool_name}({tool_args})", doc_count)

                # C: Track consecutive zero-result failures
                if doc_count == 0:
                    if tool_name == last_tool_name:
                        tool_failure_tracker[tool_name] = tool_failure_tracker.get(tool_name, 0) + 1
                        consecutive_failures = tool_failure_tracker[tool_name]

                        logger.warning(f"⚠️  Tool {tool_name} returned 0 results ({consecutive_failures}회 연속)")

                        # Force tool switch after 2 consecutive failures
                        if consecutive_failures >= 2:
                            logger.info(f"🔄 Forcing tool switch after {consecutive_failures} consecutive 0-result attempts")

                            # A: Attempt automatic fallback
                            for fallback_tool in fallback_chain:
                                if fallback_tool not in fallback_attempted and fallback_tool != tool_name:
                                    logger.info(f"🔄 Auto-fallback: {tool_name} → {fallback_tool}")

                                    # Execute fallback tool with same query
                                    fallback_args = {"query": tool_args.get("keyword") or tool_args.get("query", question), "top_k": 10}
                                    if fallback_tool == 'search_mariadb_by_keyword':
                                        fallback_args = {"keyword": tool_args.get("keyword") or tool_args.get("query", question)}

                                    fallback_docs, fallback_success = self._execute_tool_with_tracking(
                                        tool_name=fallback_tool,
                                        tool_args=fallback_args,
                                        execution_order=iteration,
                                        is_fallback=True,
                                        question=question,
                                        question_type=question_type
                                    )
                                    fallback_attempted.add(fallback_tool)

                                    if fallback_success and len(fallback_docs) > 0:
                                        logger.info(f"✅ Fallback successful: {len(fallback_docs)} docs from {fallback_tool}")
                                        new_docs.extend(fallback_docs)
                                        doc_count = len(new_docs)
                                        if fallback_tool not in tools_used:
                                            tools_used.append(fallback_tool)
                                        break
                    else:
                        # Different tool, reset counter
                        tool_failure_tracker[tool_name] = 1
                else:
                    # Success, reset counter
                    tool_failure_tracker[tool_name] = 0

                last_tool_name = tool_name

                # Validate results
                self.profiler.start_timer('document_validation', {'iteration': iteration})
                validation = self._validate_results(
                    question=question,
                    new_docs=new_docs,
                    existing_docs=all_documents,
                    iteration=iteration
                )
                self.profiler.end_timer('document_validation')

                # Add new documents
                all_documents.extend(new_docs)
                if tool_name not in tools_used:
                    tools_used.append(tool_name)

                # Log validation
                log_validation(
                    iteration=iteration,
                    relevance=validation['relevance'],
                    novelty=validation['novelty'],
                    sufficiency=validation['sufficiency'],
                    quality=validation['quality'],
                    decision=validation['decision']
                )

                # Log validation result to decision logger
                self.decision_logger.log_validation_result(
                    iteration=iteration,
                    validation=validation
                )

                # Early stop if sufficient
                if validation['sufficiency'] and validation['quality'] > 0.7:
                    logger.info(f"✓ Sufficient documents collected ({len(all_documents)} docs)")
                    # Log early stop decision
                    self.decision_logger.log_early_stop(
                        iteration=iteration,
                        reason=f"검증 통과: 충분성 {validation['sufficiency']}, 품질 {validation['quality']:.2f}, 문서 {len(all_documents)}개"
                    )
                    break

            else:
                logger.warning(f"Tool execution failed")
                thought_process.append(f"Tool {tool_name} failed")

                # A: Attempt automatic fallback on tool failure
                for fallback_tool in fallback_chain:
                    if fallback_tool not in fallback_attempted and fallback_tool != tool_name:
                        logger.info(f"🔄 Auto-fallback after failure: {tool_name} → {fallback_tool}")

                        fallback_args = {"query": question, "top_k": 10}
                        if fallback_tool == 'search_mariadb_by_keyword':
                            fallback_args = {"keyword": question}

                        fallback_docs, fallback_success = self._execute_tool_with_tracking(
                            tool_name=fallback_tool,
                            tool_args=fallback_args,
                            execution_order=iteration,
                            is_fallback=True,
                            question=question,
                            question_type=question_type
                        )
                        fallback_attempted.add(fallback_tool)

                        if fallback_success and len(fallback_docs) > 0:
                            logger.info(f"✅ Fallback successful: {len(fallback_docs)} docs from {fallback_tool}")
                            all_documents.extend(fallback_docs)
                            if fallback_tool not in tools_used:
                                tools_used.append(fallback_tool)
                            break

        # Compile and deduplicate documents (with dynamic limit based on question type)
        self.profiler.start_timer('document_compile', {'doc_count': len(all_documents)})
        compiled_docs = self._compile_documents(all_documents, is_list_request=is_list_request)
        self.profiler.end_timer('document_compile', {'compiled_count': len(compiled_docs)})
        logger.info(f"\n✓ Document compilation: {len(all_documents)} → {len(compiled_docs)} (after dedup)")

        # Use compiled documents directly for answer generation (reranking removed)
        final_docs = compiled_docs
        logger.info(f"✓ Using {len(final_docs)} documents for answer generation")

        # Generate final answer with quality validation
        self.profiler.start_timer('answer_generation', {'phase': 'final_answer'})
        answer, validation = self._generate_answer(
            question,
            final_docs,
            is_list_request=is_list_request,
            question_type=question_type
        )
        self.profiler.end_timer('answer_generation')

        execution_time = time.time() - start_time

        # Save conversation to session context (always, regardless of use_learning)
        try:
            self.conversation_context.add_turn(
                question=original_question,  # 원본 질문 저장 (참조 포함)
                answer=answer,
                sources=compiled_docs[:10],  # Top 10 sources
                metadata={
                    'is_list_request': is_list_request,
                    'question_type': question_type,
                    'iterations': iteration_count,
                    'execution_time': round(execution_time, 2),
                    'tools_used': tools_used,
                    'total_documents': len(compiled_docs),
                    # 참조 해석 정보
                    'reference_resolved': reference_resolution['has_reference'],
                    'resolved_question': resolved_question if reference_resolution['has_reference'] else None,
                    # 답변 품질 정보
                    'answer_confidence': validation['confidence']
                }
            )
            logger.info(f"✓ Conversation saved to session: {self.session_id}")
        except Exception as e:
            logger.warning(f"Failed to save conversation: {e}")
            # Don't fail the whole search if saving fails

        # Build response (20 sources for list mode, 10 for Q&A)
        source_limit = 20 if is_list_request else 10
        response = {
            'answer': answer,
            'sources': compiled_docs[:source_limit],
            'confidence': validation['confidence']  # Always include confidence score
        }

        # Get performance profile
        perf_summary = self.profiler.get_summary()
        perf_suggestions = self.profiler.get_optimization_suggestions()

        if debug:
            response['debug'] = {
                'iterations': iteration_count,
                'tools_used': tools_used,
                'thought_process': thought_process,
                'total_documents': len(compiled_docs),
                'execution_time': round(execution_time, 2),
                # 🆕 추가: 검색 과정 설명
                'search_summary': self.decision_logger.get_search_summary(),
                'decision_timeline': self.decision_logger.get_decision_timeline(),
                # 🆕 답변 품질 검증 정보
                'validation': {
                    'relevance_score': validation['relevance_score'],
                    'grounding_score': validation['grounding_score'],
                    'completeness_score': validation['completeness_score'],
                    'warnings': validation['warnings']
                },
                # 🆕 Phase 4: 성능 프로파일링
                'performance': perf_summary,
                'optimization_suggestions': perf_suggestions
            }

        # Log performance profile
        self.profiler.log_summary()

        # 🆕 Phase 4: Log cache statistics
        result_cache.log_stats()

        # Log optimization suggestions
        if perf_suggestions:
            logger.info("\n💡 Optimization Suggestions:")
            for suggestion in perf_suggestions:
                logger.info(f"  • {suggestion}")

        logger.info(f"\n{'='*60}")
        logger.info(f"Search completed in {execution_time:.2f}s")
        logger.info(f"{'='*60}\n")

        return response

    def _get_agent_decision(
        self,
        question: str,
        iteration: int,
        collected_docs: List[Dict],
        previous_thoughts: List[str]
    ) -> Dict[str, Any]:
        """
        Get agent's thought and action decision using LLM.

        Returns:
            {
                'success': bool,
                'thought': str,
                'action': str,  # tool name or "FINISH"
                'tool_name': str,
                'tool_args': dict
            }
        """
        try:
            # Build system prompt
            system_prompt = self._build_system_prompt(
                current_doc_count=len(collected_docs),
                iteration=iteration
            )

            # Build user message
            user_message = f"""Question: {question}

Current status:
- Iteration: {iteration}/{settings.MAX_ITERATIONS}
- Documents collected: {len(collected_docs)}
- Target: 5-10 relevant documents

Previous thoughts:
{chr(10).join([f"{i+1}. {t}" for i, t in enumerate(previous_thoughts[-3:])]) if previous_thoughts else "None"}

What should I do next? Provide your thought process and select a tool to use."""

            # Call LLM with function calling
            # First iteration: require tool usage to ensure search happens
            # Later iterations: allow LLM to decide when to finish
            tool_choice_mode = "required" if iteration == 1 else "auto"

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                tools=tool_registry.get_tool_definitions(), # type: ignore
                tool_choice=tool_choice_mode,
                temperature=self.temperature
            )

            message = response.choices[0].message

            # Extract thought from content
            thought = message.content or "Continuing search..."

            # Check if agent wants to use a tool
            if message.tool_calls:
                tool_call = message.tool_calls[0]
                tool_name = tool_call.function.name # type: ignore
                tool_args = json.loads(tool_call.function.arguments) # type: ignore

                return {
                    'success': True,
                    'thought': thought,
                    'action': tool_name,
                    'tool_name': tool_name,
                    'tool_args': tool_args
                }
            else:
                # No tool call = FINISH
                return {
                    'success': True,
                    'thought': thought,
                    'action': 'FINISH',
                    'tool_name': None,
                    'tool_args': {}
                }

        except Exception as e:
            logger.error(f"Agent decision failed: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'thought': '',
                'action': 'FINISH',
                'tool_name': None,
                'tool_args': {}
            }

    def _build_system_prompt(self, current_doc_count: int, iteration: int) -> str:
        """Build system prompt with tool selection strategy."""
        return f"""당신은 IT 서버, 네트워크, 개발 전문가 AI Agent입니다.

🎯 도구 선택 전략:

1️⃣ **에러 코드 최우선**
   질문에 4-5자리 숫자 → search_mariadb_by_error_code 먼저 실행
   예: "50001", "6789", "10234"

2️⃣ **브랜드 감지 → 필터링**
   키워드: RVS, RCMP, RemoteCall, RemoteView, Remotemeeting, SAAS
   → search_elasticsearch_bm25(brand_filter=[detected_brands])

3️⃣ **질문 유형별 최적 도구**
   방법/절차: "어떻게", "방법", "설정", "설치"
   → search_qdrant_semantic (의미 검색)

   정확한 용어: 제품명, 기능명, 기술 용어
   → search_mariadb_by_keyword (정확 매칭)

   과거 케이스: "전에", "이전에", "유사한"
   → search_recent_logs (로그 검색)

   리스트/목록 요청: "전부", "모두", "다", "리스트"
   → search_mariadb_by_keyword (LIMIT 100) + 여러 번 반복

4️⃣ **복합 전략**
   - 여러 도구 조합 가능
   - 같은 도구 2회 연속 금지
   - 다른 검색어로는 재시도 가능

5️⃣ **검색 결과 품질 검증** (매 Iteration 후 필수)
   평가 기준:
   ✓ 관련성: 질문의 핵심 키워드가 결과에 포함되어 있는가?
   ✓ 새로움: 이전 검색과 중복되지 않는가?
   ✓ 충분성: 답변 작성에 필요한 정보가 충분한가?
   ✓ 품질: 검색 점수가 0.5 이상인가?

   판단 패턴:
   ✅ "관련 문서 5개 확보, 질문에 직접 답변 가능" → FINISH
   ⚠️ "결과는 많지만 질문과 관련성 낮음" → 다른 도구/검색어 시도
   ⚠️ "이전 검색과 중복 많음, 새 정보 1-2개뿐" → 다른 각도 시도
   ❌ "결과 0개 또는 모두 무관" → 검색어 변경 or 다른 도구

6️⃣ **종료 기준**
   - 5-10개 관련 문서 수집 시
   - 검증 결과 "충분함" 판단 시
   - 3번 시도해도 새 정보 없으면
   - max_iterations 도달 시

📋 현재까지 수집한 문서: {current_doc_count}개
🎯 목표: 5-10개 관련 문서
🔄 반복: {iteration}/{settings.MAX_ITERATIONS}
💡 매 iteration마다 결과 품질 검증 필수!

도구를 선택하거나 FINISH 하려면 응답을 제공하세요."""

    def _validate_results(
        self,
        question: str,
        new_docs: List[Dict],
        existing_docs: List[Dict],
        iteration: int
    ) -> Dict[str, Any]:
        """
        Validate search results quality.

        Returns:
            {
                'relevance': bool,
                'novelty': bool,
                'sufficiency': bool,
                'quality': float,
                'decision': str
            }
        """
        # Relevance: Check if results contain question keywords
        relevance = len(new_docs) > 0

        # Novelty: Check for duplicates
        existing_ids = {doc.get('id') for doc in existing_docs}
        new_ids = {doc.get('id') for doc in new_docs}
        novel_count = len(new_ids - existing_ids)
        novelty = novel_count > 0

        # Sufficiency: Check total document count
        total_docs = len(existing_docs) + novel_count
        sufficiency = total_docs >= 5

        # Quality: Average score
        scores = [doc.get('score', 0.5) for doc in new_docs if 'score' in doc]
        avg_quality = sum(scores) / len(scores) if scores else 0.5

        # Decision
        if sufficiency and avg_quality > 0.7:
            decision = "충분한 문서 확보. 종료 권장"
        elif relevance and novelty:
            decision = "관련 문서 발견. 계속 진행"
        elif not novelty:
            decision = "중복 많음. 다른 각도 시도"
        else:
            decision = "관련성 낮음. 전략 변경 필요"

        return {
            'relevance': relevance,
            'novelty': novelty,
            'sufficiency': sufficiency,
            'quality': avg_quality,
            'decision': decision
        }

    def _deduplicate_documents(self, documents: List[Dict]) -> List[Dict]:
        """
        중복 문서 제거 (doc_id 기준).

        Args:
            documents: 문서 리스트

        Returns:
            중복 제거된 문서 리스트
        """
        seen_ids = set()
        unique_docs = []

        for doc in documents:
            doc_id = doc.get('id') or doc.get('doc_id') or doc.get('document_id')

            if doc_id and doc_id not in seen_ids:
                seen_ids.add(doc_id)
                unique_docs.append(doc)
            elif not doc_id:
                # ID가 없는 경우 content hash 사용
                content = doc.get('content', '')
                content_hash = hash(content[:200])  # 처음 200자로 해시

                if content_hash not in seen_ids:
                    seen_ids.add(content_hash)
                    unique_docs.append(doc)

        return unique_docs

    def _calculate_avg_quality(self, documents: List[Dict]) -> float:
        """
        Calculate average quality score from documents.

        Args:
            documents: List of documents with 'score' field

        Returns:
            Average quality score (0.0 if no documents)
        """
        if not documents:
            return 0.0

        scores = [doc.get('score', 0.5) for doc in documents if 'score' in doc]
        return sum(scores) / len(scores) if scores else 0.0

    def _compile_documents(self, documents: List[Dict], is_list_request: bool = False) -> List[Dict]:
        """
        Compile and deduplicate documents, sort by relevance.

        Args:
            documents: List of all documents
            is_list_request: Whether this is a list/catalog request

        Returns:
            Deduplicated and sorted document list
        """
        # Deduplicate by ID
        seen_ids = set()
        unique_docs = []

        # Sort by score first (highest first)
        sorted_docs = sorted(
            documents,
            key=lambda x: x.get('score', 0),
            reverse=True
        )

        for doc in sorted_docs:
            doc_id = doc.get('id')
            if doc_id not in seen_ids:
                unique_docs.append(doc)
                seen_ids.add(doc_id)

        # Dynamic limit based on question type
        if is_list_request:
            # For list requests: return more documents (up to 100)
            max_docs = min(len(unique_docs), 100)
            logger.info(f"📋 List request: returning up to {max_docs} documents")
        else:
            # For Q&A requests: use standard limit
            max_docs = settings.MAX_DOCUMENTS

        return unique_docs[:max_docs]

    def _extract_technical_terms(self, question: str) -> List[str]:
        """
        Extract technical terms from question that may need external context.
        Uses hardcoded list + intelligent term extraction from question.
        """
        # Known technical terms (hardcoded)
        tech_terms = {
            'SSO', 'API', 'OAUTH', 'SAML', 'JWT', 'REST', 'SOAP',
            'VPN', 'SSL', 'TLS', 'LDAP', 'AD', 'DNS', 'CDN', 'CI/CD',
            'HTTP', 'HTTPS', 'FTP', 'SMTP', 'TCP', 'UDP', 'IP','SFU','MCU','webRTC','springboot'
        }

        found_terms = []
        question_upper = question.upper()

        # Stage 1: Check hardcoded technical terms
        for term in tech_terms:
            if term in question_upper:
                # Preserve original casing for display
                if term == 'OAUTH':
                    found_terms.append('OAuth')
                else:
                    found_terms.append(term)

        # Stage 2: If nothing found, extract from "무엇" / "뭔가" type questions
        if not found_terms:
            import re

            # Pattern: "XXX란 무엇" or "XXX는 뭔가" → extract XXX
            definition_patterns = [
                r'(.+?)란\s*무엇',
                r'(.+?)는\s*뭔가',
                r'(.+?)이란\s*무엇',
                r'(.+?)\s*무엇',
                r'what\s+is\s+(.+)',
                r'explain\s+(.+)',
            ]

            for pattern in definition_patterns:
                match = re.search(pattern, question, re.IGNORECASE)
                if match:
                    term = match.group(1).strip()
                    # Clean up common Korean particles
                    term = re.sub(r'[은는이가을를에]$', '', term)
                    if term:
                        found_terms.append(term)
                        logger.info(f"📝 Extracted term from definition question: '{term}'")
                        break

            # Stage 3: If still nothing, extract capitalized words (likely product names)
            if not found_terms:
                capitalized_words = re.findall(r'\b[A-Z][a-zA-Z0-9]*\b', question)
                # Filter out common short words
                capitalized_words = [w for w in capitalized_words if len(w) > 2]
                if capitalized_words:
                    found_terms.extend(capitalized_words)
                    logger.info(f"📝 Extracted capitalized terms: {capitalized_words}")

        return found_terms

    def _get_external_knowledge(self, terms: List[str]) -> str:
        """Get external knowledge explanation for technical terms."""
        if not terms:
            return ""

        try:
            prompt = f"""다음 기술 용어들에 대해 간단하고 명확하게 설명해주세요.
각 용어당 2-3문장으로 핵심만 설명하세요.

용어: {', '.join(terms)}

형식:
**{terms[0]}**: [설명]
"""

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "system",
                    "content": "당신은 기술 용어를 쉽고 정확하게 설명하는 IT 서버, 네트워크, 개발 전문가입니다."
                }, {
                    "role": "user",
                    "content": prompt
                }],
                temperature=0.3,
                max_tokens=500
            )

            explanation = response.choices[0].message.content
            logger.info(f"📚 External knowledge fetched for: {', '.join(terms)}")
            return explanation # type: ignore

        except Exception as e:
            logger.warning(f"Failed to fetch external knowledge: {e}")
            return ""

    def _assess_document_sufficiency(
        self,
        question: str,
        documents: List[Dict]
    ) -> Dict[str, Any]:
        """
        LLM이 문서를 읽고 질문 답변 충분성을 판단.

        Args:
            question: 사용자 질문
            documents: 검색된 문서 리스트

        Returns:
            {
                'sufficiency': 'SUFFICIENT' | 'PARTIAL' | 'INSUFFICIENT',
                'reason': str,
                'needs_external': bool,
                'missing_topics': List[str]  # 설명 필요한 주제/용어
            }
        """
        try:
            # 문서 요약 생성 (상위 5개, 각 200자)
            doc_summary = ""
            for i, doc in enumerate(documents[:5], 1):
                text = doc.get('text', '')[:200]
                score = doc.get('score', 0)
                doc_summary += f"[문서{i}] (관련도: {score:.2f})\n{text}\n\n"

            if not doc_summary:
                doc_summary = "(검색된 문서 없음)"

            prompt = f"""질문: {question}

검색된 사내 문서:
{doc_summary}

위 문서들로 질문에 답변할 수 있는지 평가하세요.

평가 기준:
1. 문서에 질문의 핵심 정보가 포함되어 있는가?
2. 문서만으로 완전하고 정확한 답변이 가능한가?
3. 추가 설명이 필요한 기술 용어나 개념이 있는가?
4. 문서 내용이 질문과 실제로 관련이 있는가?

응답 형식 (반드시 JSON):
{{
  "sufficiency": "SUFFICIENT 또는 PARTIAL 또는 INSUFFICIENT",
  "reason": "1-2문장으로 판단 이유",
  "needs_external": true 또는 false,
  "missing_topics": ["설명 필요 용어1", "용어2"]
}}

판단 가이드:
- SUFFICIENT: 문서에 충분한 정보, 외부 지식 불필요
- PARTIAL: 문서에 일부 정보, 보충 설명 필요
- INSUFFICIENT: 문서에 관련 정보 거의 없음, 외부 지식 필요

⚠️ 중요: missing_topics는 **기술 용어/IT 개념만** 포함하세요.
   예시:
   - ✅ 포함: "API", "Docker", "Kubernetes", "REST", "JWT"
   - ❌ 제외: "문제 해결 방법", "원인", "절차", "이슈 해결", "로그 분석"

   해결책/방법론은 사내 문서에서 찾아야 하므로 missing_topics에 포함하지 마세요."""

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "당신은 문서 충분성을 평가하는 전문가입니다. 문서 내용을 정확히 읽고 판단하세요. 반드시 유효한 JSON만 응답하세요."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.1,
                max_tokens=400
            )

            result_text = response.choices[0].message.content.strip() # type: ignore

            # JSON 파싱 (마크다운 코드블록 제거)
            if result_text.startswith("```json"):
                result_text = result_text[7:]
            if result_text.startswith("```"):
                result_text = result_text[3:]
            if result_text.endswith("```"):
                result_text = result_text[:-3]
            result_text = result_text.strip()

            assessment = json.loads(result_text)

            logger.info(
                f"📋 문서 충분성 판단: {assessment['sufficiency']} - {assessment['reason']}"
            )

            return assessment

        except json.JSONDecodeError as e:
            logger.warning(f"⚠️ JSON 파싱 실패, 기본값 사용: {e}")
            return {
                'sufficiency': 'PARTIAL',
                'reason': 'JSON 파싱 오류로 기본 판단',
                'needs_external': True,
                'missing_topics': self._extract_technical_terms(question)
            }
        except Exception as e:
            logger.error(f"❌ 문서 충분성 판단 실패: {e}")
            return {
                'sufficiency': 'PARTIAL',
                'reason': '평가 실패로 기본 판단',
                'needs_external': True,
                'missing_topics': []
            }

    def _should_enrich_with_external_knowledge(
        self,
        question: str,
        documents: List[Dict]
    ) -> Tuple[bool, List[str]]:
        """
        하이브리드 접근: 빠른 휴리스틱 + LLM 정밀 판단.

        Returns:
            (외부 지식 필요 여부, 설명 필요 주제 리스트)
        """
        # ============================================
        # 1단계: 빠른 휴리스틱 필터링
        # ============================================

        # 명백한 경우 1: 문서 없음 → 외부 지식 필요
        if len(documents) == 0:
            logger.info("📉 문서 없음 → 외부 지식 필요 (즉시 판단)")
            tech_terms = self._extract_technical_terms(question)
            return True, tech_terms

        # 명백한 경우 2: 문서 충분하고 고품질 → 외부 지식 불필요
        if len(documents) >= 5:
            avg_score = sum(d.get('score', 0) for d in documents) / len(documents)
            if avg_score > 0.8:
                logger.info(
                    f"✅ 문서 충분 (개수={len(documents)}, 평균점수={avg_score:.2f}) "
                    f"→ 외부 지식 불필요 (즉시 판단)"
                )
                return False, []

        # ============================================
        # 2단계: 애매한 경우 → LLM 정밀 판단
        # ============================================
        logger.info("🤔 애매한 경우 → LLM 정밀 판단 실행")

        assessment = self._assess_document_sufficiency(question, documents)

        needs_external = assessment['needs_external']
        topics = assessment.get('missing_topics', [])

        # SUFFICIENT면 외부 지식 불필요
        if assessment['sufficiency'] == 'SUFFICIENT':
            logger.info("✅ LLM 판단: 문서만으로 충분 → 외부 지식 불필요")
            return False, []

        # PARTIAL이나 INSUFFICIENT: missing_topics 기준으로 판단
        # - topics 있음 → 설명 필요한 용어 있음 → 외부 지식 필요
        # - topics 없음 → 단순 합성만 필요 → 외부 지식 불필요
        if topics:
            logger.info(
                f"💡 LLM 판단: {assessment['sufficiency']} "
                f"→ 외부 지식 필요 (주제: {topics})"
            )
            return True, topics
        else:
            logger.info(
                f"💡 LLM 판단: {assessment['sufficiency']} "
                f"→ 외부 지식 불필요 (문서 합성만 필요)"
            )
            return False, []

    def _generate_answer(
        self,
        question: str,
        documents: List[Dict],
        is_list_request: bool = False,
        question_type: str = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate final answer using LLM with compiled documents and validate quality.

        Args:
            question: User's question
            documents: Compiled and deduplicated documents
            is_list_request: Whether to format as a list/catalog
            question_type: Type of question for dynamic context sizing

        Returns:
            Tuple of (final answer string, validation dict)
        """
        # Build context from documents
        context_parts = []
        for i, doc in enumerate(documents, 1):
            text = doc.get('text', '')[:1000]  # Limit per document
            source = doc.get('metadata', {}).get('file_name', 'Unknown')
            score = doc.get('score', 0)
            context_parts.append(
                f"[문서 {i}] (출처: {source}, 관련도: {score:.2f})\n{text}\n"
            )

        context = "\n".join(context_parts)

        # Check if external knowledge enrichment is needed (Hybrid approach)
        external_knowledge = ""
        needs_external, topics = self._should_enrich_with_external_knowledge(question, documents)
        if needs_external and topics:
            logger.info(f"🧠 Targeted external knowledge for topics: {topics}")
            external_knowledge = self._get_external_knowledge(topics)

        # Dynamic context sizing based on question type (performance optimization)
        if question_type == 'error_code':
            max_context_tokens = 4000  # Simple error explanations
        elif question_type == 'keyword':
            max_context_tokens = 4000  # Specific product info
        elif question_type == 'concept':
            max_context_tokens = 5000  # Concept definitions
        elif question_type == 'qa':
            max_context_tokens = 6000  # General Q&A
        elif question_type == 'list':
            max_context_tokens = 7000  # List requests
        elif question_type == 'how_to':
            max_context_tokens = 8000  # Complex procedures
        else:
            max_context_tokens = 6000  # Default

        # Truncate if too long
        context = self._truncate_context(context, max_tokens=max_context_tokens)

        if question_type:
            logger.info(f"📐 Dynamic context: {question_type} → {max_context_tokens} tokens")

        # Build prompt (different format for list vs Q&A)
        if is_list_request:
            system_prompt = """당신은 IT 서버, 네트워크, 개발 전문가입니다.
사용자가 목록/리스트를 요청했습니다. 제공된 사내 문서를 바탕으로 표 형식이나 번호 매긴 목록으로 답변하세요.

🔴 핵심 원칙:
1. **모든 항목은 사내 문서에서만** 추출
2. 기술 용어 설명은 용어 이해를 돕는 배경 지식으로만 활용
3. 사내 문서에 없는 항목은 추가하지 말 것

답변 형식:
1. 마크다운 표 또는 번호 매긴 목록으로 사내 문서 정리
2. 각 항목: 제목, 간단한 설명, 출처 포함
3. 날짜나 ID가 있다면 포함
4. 모든 관련 항목을 빠짐없이 나열
5. 항목이 많으면 중요도/시간 순으로 정렬

예시 형식:
| 번호 | 제목 | 설명 | 출처 |
|------|------|------|------|
| 1    | ... | ... | 문서1 |
| 2    | ... | ... | 문서3 |"""

            user_prompt = f"""질문: {question}

📄 사내 문서 (주 자료, 총 {len(documents)}개):
{context}
"""
            if external_knowledge:
                user_prompt += f"""
📚 기술 용어 배경 지식 (보조 참고):
{external_knowledge}

⚠️ 주의: 기술 용어 설명은 배경 지식입니다. 모든 항목은 사내 문서에서만 추출하세요.
"""
            user_prompt += """
위 사내 문서에서 찾은 항목만 표 형식이나 목록으로 정리해주세요."""
        else:
            system_prompt = """당신은 IT 서버, 네트워크, 개발 전문가입니다.
제공된 사내 문서를 바탕으로 사용자의 질문에 정확하고 상세하게 답변하세요.

🔴 핵심 원칙:
1. **모든 답변은 사내 문서 기반**으로 작성
2. 해결책, 방법, 절차, 원인 분석 등은 **반드시 사내 문서에서만** 추출
3. 기술 용어 설명은 **용어 이해를 돕는 배경 지식**으로만 사용
4. 사내 문서에 없는 내용은 추측하거나 일반 지식으로 보충하지 말 것
5. 출처 문서 번호를 명시하여 답변 근거 제시

답변 작성 방법:
1. 구체적인 절차/방법이 있다면 사내 문서 기준으로 단계별 설명
2. 에러 코드는 사내 문서의 원인/해결책으로 설명
3. 기술 용어는 배경 지식으로 간단히 설명 후, 사내 문서 정보 중심 답변
4. 사내 문서에 정보가 없으면 "문서에서 확인되지 않음" 명시"""

            user_prompt = f"""질문: {question}

📄 사내 문서 (주 자료):
{context}
"""
            if external_knowledge:
                user_prompt += f"""
📚 기술 용어 배경 지식 (보조 참고):
{external_knowledge}

⚠️ 주의: 위 기술 용어 설명은 사내 문서를 이해하기 위한 배경 지식입니다.
답변은 반드시 사내 문서를 중심으로 작성하고, 해결책/방법/절차는 사내 문서에서만 추출하세요.
"""
            user_prompt += """
위 사내 문서를 바탕으로 질문에 답변해주세요.
사내 문서에 없는 내용은 "사내 문서에서 확인되지 않음"이라고 명시하세요."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=self.temperature,
                max_tokens=1000  # Reduced from 1500 for speed optimization
            )

            answer = response.choices[0].message.content
            logger.info(f"✓ Answer generated ({len(answer)} chars)") # type: ignore

            # Validate answer quality
            validation = self.answer_validator.validate_answer(
                question=question,
                answer=answer, # type: ignore
                source_docs=documents
            )

            # Add warnings based on confidence
            if validation['confidence'] < 0.5:
                # Very low confidence - prominent warning
                warning_text = "\n\n".join([
                    "⚠️ **답변 신뢰도가 낮습니다**",
                    "이유: " + ", ".join(validation['warnings']),
                    f"신뢰도: {validation['confidence']:.0%}",
                    "",
                    "---",
                    ""
                ])
                answer = warning_text + answer # type: ignore
            elif validation['confidence'] < 0.7:
                # Moderate confidence - brief warning
                if validation['warnings']:
                    warning_text = "\n\n💡 참고: " + validation['warnings'][0] + "\n\n"
                    answer = warning_text + answer # type: ignore

            return answer, validation # type: ignore

        except Exception as e:
            logger.error(f"Answer generation failed: {e}", exc_info=True)
            error_answer = f"죄송합니다. 답변 생성 중 오류가 발생했습니다: {str(e)}"
            # Return empty validation on error
            empty_validation = {
                'confidence': 0.0,
                'relevance_score': 0.0,
                'grounding_score': 0.0,
                'completeness_score': 0.0,
                'is_acceptable': False,
                'warnings': ['답변 생성 오류']
            }
            return error_answer, empty_validation

    def _truncate_context(self, context: str, max_tokens: int) -> str:
        """
        Truncate context to fit within token limit.

        Args:
            context: Context string
            max_tokens: Maximum tokens allowed

        Returns:
            Truncated context
        """
        tokens = self.encoding.encode(context)

        if len(tokens) <= max_tokens:
            return context

        # Truncate to max_tokens
        truncated_tokens = tokens[:max_tokens]
        truncated_text = self.encoding.decode(truncated_tokens)

        logger.warning(f"Context truncated: {len(tokens)} → {max_tokens} tokens")
        return truncated_text

    def _analyze_question_type(self, question: str) -> Dict[str, Any]:
        """
        Analyze question to determine if it's a list request or Q&A.

        Args:
            question: User's question

        Returns:
            Dictionary with analysis results:
            {
                'is_list_request': bool,
                'keywords_found': List[str]
            }
        """
        # List request keywords (Korean and English)
        list_keywords = [
            # Korean
            '전부', '전체', '모두', '모든', '다', '리스트', '목록', '찾아줘', '보여줘',
            '나열', '정리', '일람', '조회', '검색해줘', '추출','싹 다',
            # With particles
            '전부다', '모두다', '전체를', '모든걸', '다찾아', '리스트업',
            # English
            'list', 'all', 'every', 'show all', 'find all', 'search all',
            'catalog', 'enumerate', 'summary of all'
        ]

        question_lower = question.lower()
        found_keywords = []

        for keyword in list_keywords:
            if keyword in question_lower:
                found_keywords.append(keyword)

        is_list_request = len(found_keywords) > 0

        # Additional heuristic: if question contains "몇 개" or "개수" it's likely asking for count/list
        count_keywords = ['몇 개', '몇개', '개수', '수량', 'how many', 'count', '전체 수','전체 개수']
        for keyword in count_keywords:
            if keyword in question_lower:
                is_list_request = True
                found_keywords.append(keyword)
                break

        if is_list_request:
            logger.info(f"📋 List request detected - keywords: {found_keywords}")

        return {
            'is_list_request': is_list_request,
            'keywords_found': found_keywords
        }

    def _detect_question_type(self, question: str, is_list_request: bool) -> str:
        """
        Detect question type for performance tracking.

        Args:
            question: User's question
            is_list_request: Whether this is a list request

        Returns:
            Question type: 'list', 'qa', 'error_code', 'how_to', 'keyword', 'concept'
        """
        question_lower = question.lower()

        # Check for error code
        import re
        if re.search(r'\b\d{4,5}\b', question):
            return 'error_code'

        # Check if list request
        if is_list_request:
            return 'list'

        # Check for how-to questions
        how_to_keywords = ['어떻게', '방법', '설정', '설치', 'how', 'setup', 'configure', 'install']
        if any(keyword in question_lower for keyword in how_to_keywords):
            return 'how_to'

        # Check for keyword search (specific terms like product names)
        brands = ['rvs', 'rcmp', 'remotecall', 'remoteview', 'remotemeeting', 'saas']
        if any(brand in question_lower for brand in brands):
            return 'keyword'

        # Check for concept questions
        concept_keywords = ['이란', '무엇', '뭐', '설명', 'what', 'explain', 'definition']
        if any(keyword in question_lower for keyword in concept_keywords):
            return 'concept'

        # Default to Q&A
        return 'qa'

    def _execute_tool_with_tracking(
        self,
        tool_name: str,
        tool_args: Dict,
        execution_order: int,
        is_fallback: bool,
        question: str,
        question_type: str
    ) -> Tuple[List[Dict], bool]:
        """
        Execute tool with performance tracking.

        Args:
            tool_name: Name of tool to execute
            tool_args: Tool arguments
            execution_order: Order in execution chain (1=primary, 2+=fallback)
            is_fallback: Whether this is a fallback execution
            question: User question
            question_type: Type of question

        Returns:
            Tuple of (results, success)
        """
        start_time = time.time()
        success = False
        result_docs = []
        error_message = None
        error_type = None

        # 🆕 Phase 4: Check cache first
        cached_result = result_cache.get(
            session_id=self.session_id,  # type: ignore
            tool_name=tool_name,
            tool_args=tool_args
        )

        if cached_result is not None:
            result_docs, success = cached_result
            execution_time = 0.001  # Minimal time for cache hit

            # Log to performance tracking (mark as cached)
            self.perf_repo.log_tool_execution(
                session_id=self.session_id,  # type: ignore
                question=question[:200],
                question_type=question_type,
                tool_name=tool_name,
                execution_order=execution_order,
                is_fallback=is_fallback,
                doc_count=len(result_docs),
                avg_score=0.0,  # Not calculated for cached results
                execution_time=execution_time,
                success=success
            )

            return result_docs, success

        try:
            # Execute tool
            result = tool_registry.execute_tool(tool_name, tool_args)

            if result['success']:
                result_docs = result['result'] if isinstance(result['result'], list) else []
                success = len(result_docs) > 0

                # Calculate metrics
                execution_time = time.time() - start_time
                doc_count = len(result_docs)
                avg_score = 0.0

                if result_docs and doc_count > 0:
                    scores = [doc.get('score', 0) for doc in result_docs]
                    avg_score = sum(scores) / len(scores) if scores else 0.0

                # Log to performance tracking
                self.perf_repo.log_tool_execution(
                    session_id=self.session_id, # type: ignore
                    question=question[:200],  # Truncate long questions
                    question_type=question_type,
                    tool_name=tool_name,
                    execution_order=execution_order,
                    is_fallback=is_fallback,
                    doc_count=doc_count,
                    avg_score=avg_score,
                    execution_time=execution_time,
                    success=success
                )

                logger.debug(
                    f"📊 {tool_name}: docs={doc_count}, "
                    f"score={avg_score:.2f}, time={execution_time:.3f}s, "
                    f"fallback={is_fallback}"
                )

                # 🆕 Phase 4: Cache successful results
                if result_cache.should_cache(tool_name, result_docs, success):
                    result_cache.set(
                        session_id=self.session_id,  # type: ignore
                        tool_name=tool_name,
                        tool_args=tool_args,
                        result=result_docs,
                        success=success,
                        execution_time=execution_time
                    )

                return result_docs, success

            else:
                # Tool execution failed
                execution_time = time.time() - start_time
                error_message = result.get('error', 'Unknown error')
                error_type = 'ToolExecutionError'

                self.perf_repo.log_tool_execution(
                    session_id=self.session_id, # type: ignore
                    question=question[:200],
                    question_type=question_type,
                    tool_name=tool_name,
                    execution_order=execution_order,
                    is_fallback=is_fallback,
                    doc_count=0,
                    avg_score=0.0,
                    execution_time=execution_time,
                    success=False,
                    error_message=error_message[:500],
                    error_type=error_type
                )

                return [], False

        except Exception as e:
            execution_time = time.time() - start_time
            error_message = str(e)
            error_type = type(e).__name__

            self.perf_repo.log_tool_execution(
                session_id=self.session_id, # type: ignore
                question=question[:200],
                question_type=question_type,
                tool_name=tool_name,
                execution_order=execution_order,
                is_fallback=is_fallback,
                doc_count=0,
                avg_score=0.0,
                execution_time=execution_time,
                success=False,
                error_message=error_message[:500],
                error_type=error_type
            )

            logger.error(f"❌ {tool_name} 실행 실패: {error_message}")
            return [], False

    def _get_optimal_tool_for_question(
        self,
        question_type: str
    ) -> Optional[str]:
        """
        Get optimal tool based on learning data.

        Args:
            question_type: Type of question

        Returns:
            Recommended tool name or None
        """
        if not self.use_learning:
            return None

        best_tool = self.perf_repo.get_best_tool_for_question_type(
            question_type=question_type,
            min_executions=10
        )

        if best_tool:
            tool_name, success_rate = best_tool
            if success_rate >= 0.7:  # Only use if success rate is good
                logger.info(
                    f"💡 학습 추천: '{question_type}' → {tool_name} "
                    f"(성공률 {success_rate:.2%})"
                )
                return tool_name

        return None
