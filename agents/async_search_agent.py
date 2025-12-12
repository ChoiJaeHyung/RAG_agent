"""
AsyncSearchAgent - Async RAG Agent with ReAct loop.
Non-blocking implementation for API and concurrent request handling.
"""

import asyncio
from typing import List, Dict, Any, Optional, Tuple
import json
import time
import uuid
import tiktoken
from openai import AsyncOpenAI

from config.settings import settings
from repositories.async_db_repository import AsyncDatabaseRepository
from repositories.async_vector_repository import AsyncVectorRepository
from repositories.async_es_repository import AsyncElasticsearchRepository
from agents.tools.async_tools import (
    async_tool_registry,
    AsyncMariaDBTools,
    AsyncVectorTools,
    AsyncElasticsearchTools
)
from utils.logger import logger


class AsyncSearchAgent:
    """
    Async autonomous search agent using ReAct pattern.
    Designed for concurrent request handling and API integration.
    """

    def __init__(self):
        """Initialize AsyncSearchAgent with async repositories."""
        # Initialize async OpenAI client
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.MODEL_NAME
        self.temperature = settings.TEMPERATURE

        # Lazy initialization flags
        self._initialized = False
        self._init_lock = asyncio.Lock()

        # Repositories (initialized lazily)
        self._db_repo: Optional[AsyncDatabaseRepository] = None
        self._vector_repo: Optional[AsyncVectorRepository] = None
        self._es_repo: Optional[AsyncElasticsearchRepository] = None

        # Token counter
        try:
            self.encoding = tiktoken.encoding_for_model(self.model)
        except KeyError:
            self.encoding = tiktoken.get_encoding("cl100k_base")

        logger.info("AsyncSearchAgent created (lazy initialization)")

    async def _initialize(self):
        """Lazy initialization of repositories and tools."""
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            logger.info("Initializing AsyncSearchAgent repositories...")

            # Initialize repositories
            self._db_repo = AsyncDatabaseRepository()
            self._vector_repo = AsyncVectorRepository(db_repo=self._db_repo)
            self._es_repo = AsyncElasticsearchRepository()

            # Initialize async tools
            logger.info("📋 Tool configuration from .env:")
            enabled_tools = settings.get_enabled_tools()
            for tool_name, is_enabled in enabled_tools.items():
                status = "✅ enabled" if is_enabled else "❌ disabled"
                logger.info(f"   {tool_name}: {status}")

            AsyncMariaDBTools(self._db_repo)
            AsyncVectorTools(self._vector_repo)
            AsyncElasticsearchTools(self._es_repo, self._db_repo)

            self._initialized = True
            logger.info(f"✓ AsyncSearchAgent initialized with {len(async_tool_registry.get_tool_names())} tools")

    async def search(
        self,
        question: str,
        session_id: Optional[str] = None,
        max_iterations: Optional[int] = None,
        debug: bool = False
    ) -> Dict[str, Any]:
        """
        Execute async autonomous search using ReAct loop.

        Args:
            question: User's question
            session_id: Session ID (auto-generated if None)
            max_iterations: Maximum ReAct iterations
            debug: Include debug information

        Returns:
            Search result with answer, sources, and optional debug info
        """
        await self._initialize()

        session_id = session_id or str(uuid.uuid4())
        max_iterations = max_iterations or settings.MAX_ITERATIONS
        start_time = time.time()

        # Analyze question type
        question_analysis = self._analyze_question_type(question)
        is_list_request = question_analysis['is_list_request']

        if is_list_request:
            max_iterations = min(max_iterations + 3, 10)
            logger.info(f"📋 List request detected - increasing max_iterations to {max_iterations}")

        # Initialize tracking
        all_documents = []
        thought_process = []
        tools_used = []
        iteration_count = 0

        # Tool failure tracking
        tool_failure_tracker = {}
        last_tool_name = None
        fallback_chain = ['search_mariadb_by_keyword', 'search_qdrant_semantic', 'search_elasticsearch_bm25']
        fallback_attempted = set()

        logger.info(f"\n{'='*60}")
        logger.info(f"[ASYNC] Starting search for: {question[:100]}...")
        logger.info(f"Session: {session_id}")
        logger.info(f"{'='*60}")

        # ReAct loop
        for iteration in range(1, max_iterations + 1):
            iteration_count = iteration
            logger.info(f"\n--- Iteration {iteration}/{max_iterations} ---")

            # Get agent decision
            decision = await self._get_agent_decision(
                question=question,
                iteration=iteration,
                collected_docs=all_documents,
                previous_thoughts=thought_process
            )

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
                break

            # Execute tool
            logger.info(f"Executing: {tool_name}({json.dumps(tool_args, ensure_ascii=False)})")

            new_docs, success = await self._execute_tool(
                tool_name=tool_name,
                tool_args=tool_args
            )

            doc_count = len(new_docs)

            if success:
                # Track failures for smart switching
                if doc_count == 0:
                    if tool_name == last_tool_name:
                        tool_failure_tracker[tool_name] = tool_failure_tracker.get(tool_name, 0) + 1

                        if tool_failure_tracker[tool_name] >= 2:
                            # Auto fallback
                            for fallback_tool in fallback_chain:
                                if fallback_tool not in fallback_attempted and fallback_tool != tool_name:
                                    logger.info(f"🔄 Auto-fallback: {tool_name} → {fallback_tool}")

                                    fallback_args = self._build_fallback_args(tool_args, question, fallback_tool)
                                    fallback_docs, _ = await self._execute_tool(fallback_tool, fallback_args)
                                    fallback_attempted.add(fallback_tool)

                                    if fallback_docs:
                                        new_docs.extend(fallback_docs)
                                        doc_count = len(new_docs)
                                        if fallback_tool not in tools_used:
                                            tools_used.append(fallback_tool)
                                        break
                    else:
                        tool_failure_tracker[tool_name] = 1
                else:
                    tool_failure_tracker[tool_name] = 0

                last_tool_name = tool_name

                # Validate and add documents
                validation = self._validate_results(question, new_docs, all_documents, iteration)
                all_documents.extend(new_docs)

                if tool_name not in tools_used:
                    tools_used.append(tool_name)

                # Early stop if sufficient
                if validation['sufficiency'] and validation['quality'] > 0.7:
                    logger.info(f"✓ Sufficient documents collected ({len(all_documents)} docs)")
                    break

            else:
                # Tool failed - try fallback
                for fallback_tool in fallback_chain:
                    if fallback_tool not in fallback_attempted and fallback_tool != tool_name:
                        logger.info(f"🔄 Fallback after failure: {tool_name} → {fallback_tool}")

                        fallback_args = self._build_fallback_args(tool_args, question, fallback_tool)
                        fallback_docs, fallback_success = await self._execute_tool(fallback_tool, fallback_args)
                        fallback_attempted.add(fallback_tool)

                        if fallback_success and fallback_docs:
                            all_documents.extend(fallback_docs)
                            if fallback_tool not in tools_used:
                                tools_used.append(fallback_tool)
                            break

        # Compile documents
        compiled_docs = self._compile_documents(all_documents, is_list_request)
        logger.info(f"\n✓ Document compilation: {len(all_documents)} → {len(compiled_docs)}")

        # Generate answer
        answer, validation = await self._generate_answer(
            question,
            compiled_docs,
            is_list_request
        )

        execution_time = time.time() - start_time

        # Build response
        source_limit = 20 if is_list_request else 10
        response = {
            'answer': answer,
            'sources': compiled_docs[:source_limit],
            'confidence': validation['confidence'],
            'session_id': session_id
        }

        if debug:
            response['debug'] = {
                'iterations': iteration_count,
                'tools_used': tools_used,
                'thought_process': thought_process,
                'total_documents': len(compiled_docs),
                'execution_time': round(execution_time, 2),
                'validation': validation
            }

        logger.info(f"\n{'='*60}")
        logger.info(f"[ASYNC] Search completed in {execution_time:.2f}s")
        logger.info(f"{'='*60}\n")

        return response

    async def _get_agent_decision(
        self,
        question: str,
        iteration: int,
        collected_docs: List[Dict],
        previous_thoughts: List[str]
    ) -> Dict[str, Any]:
        """Get agent's thought and action decision using async LLM."""
        try:
            system_prompt = self._build_system_prompt(len(collected_docs), iteration)

            user_message = f"""Question: {question}

Current status:
- Iteration: {iteration}/{settings.MAX_ITERATIONS}
- Documents collected: {len(collected_docs)}
- Target: 5-10 relevant documents

Previous thoughts:
{chr(10).join([f"{i+1}. {t}" for i, t in enumerate(previous_thoughts[-3:])]) if previous_thoughts else "None"}

What should I do next?"""

            tool_choice_mode = "required" if iteration == 1 else "auto"

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                tools=async_tool_registry.get_tool_definitions(),
                tool_choice=tool_choice_mode,
                temperature=self.temperature
            )

            message = response.choices[0].message
            thought = message.content or "Continuing search..."

            if message.tool_calls:
                tool_call = message.tool_calls[0]
                return {
                    'success': True,
                    'thought': thought,
                    'action': tool_call.function.name,
                    'tool_name': tool_call.function.name,
                    'tool_args': json.loads(tool_call.function.arguments)
                }
            else:
                return {
                    'success': True,
                    'thought': thought,
                    'action': 'FINISH',
                    'tool_name': None,
                    'tool_args': {}
                }

        except Exception as e:
            logger.error(f"Agent decision failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'thought': '',
                'action': 'FINISH',
                'tool_name': None,
                'tool_args': {}
            }

    def _build_system_prompt(self, current_doc_count: int, iteration: int) -> str:
        """Build system prompt for tool selection."""
        return f"""당신은 IT 서버, 네트워크, 개발 전문가 AI Agent입니다.

🎯 도구 선택 전략:

1️⃣ **에러 코드 최우선**
   질문에 4-5자리 숫자 → search_mariadb_by_error_code 먼저

2️⃣ **브랜드 감지 → 필터링**
   RVS, RCMP, RemoteCall 등 → search_elasticsearch_bm25(brand_filter)

3️⃣ **질문 유형별 도구**
   방법/절차: search_qdrant_semantic
   정확한 용어: search_mariadb_by_keyword
   과거 케이스: search_recent_logs

4️⃣ **종료 기준**
   - 5-10개 관련 문서 수집 시
   - 3번 시도해도 새 정보 없으면

📋 현재 문서: {current_doc_count}개
🎯 목표: 5-10개
🔄 반복: {iteration}/{settings.MAX_ITERATIONS}"""

    async def _execute_tool(
        self,
        tool_name: str,
        tool_args: Dict
    ) -> Tuple[List[Dict], bool]:
        """Execute tool asynchronously."""
        try:
            result = await async_tool_registry.execute_tool(tool_name, tool_args)

            if result['success']:
                docs = result['result'] if isinstance(result['result'], list) else []
                return docs, len(docs) > 0
            else:
                logger.warning(f"Tool {tool_name} failed: {result.get('error')}")
                return [], False

        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return [], False

    def _build_fallback_args(self, original_args: Dict, question: str, fallback_tool: str) -> Dict:
        """Build arguments for fallback tool."""
        query = original_args.get("keyword") or original_args.get("query", question)

        if fallback_tool == 'search_mariadb_by_keyword':
            return {"keyword": query}
        else:
            return {"query": query, "top_k": 10}

    def _validate_results(
        self,
        question: str,
        new_docs: List[Dict],
        existing_docs: List[Dict],
        iteration: int
    ) -> Dict[str, Any]:
        """Validate search results quality."""
        relevance = len(new_docs) > 0

        existing_ids = {doc.get('id') for doc in existing_docs}
        new_ids = {doc.get('id') for doc in new_docs}
        novel_count = len(new_ids - existing_ids)
        novelty = novel_count > 0

        total_docs = len(existing_docs) + novel_count
        sufficiency = total_docs >= 5

        scores = [doc.get('score', 0.5) for doc in new_docs if 'score' in doc]
        avg_quality = sum(scores) / len(scores) if scores else 0.5

        return {
            'relevance': relevance,
            'novelty': novelty,
            'sufficiency': sufficiency,
            'quality': avg_quality
        }

    def _compile_documents(self, documents: List[Dict], is_list_request: bool = False) -> List[Dict]:
        """Compile and deduplicate documents."""
        seen_ids = set()
        unique_docs = []

        sorted_docs = sorted(documents, key=lambda x: x.get('score', 0), reverse=True)

        for doc in sorted_docs:
            doc_id = doc.get('id')
            if doc_id not in seen_ids:
                unique_docs.append(doc)
                seen_ids.add(doc_id)

        max_docs = 100 if is_list_request else settings.MAX_DOCUMENTS
        return unique_docs[:max_docs]

    def _analyze_question_type(self, question: str) -> Dict[str, Any]:
        """Analyze if question is a list request."""
        list_keywords = ['전부', '모두', '모든', '리스트', '목록', '전체', 'list', 'all']
        question_lower = question.lower()

        found = [k for k in list_keywords if k in question_lower]
        return {
            'is_list_request': len(found) > 0,
            'keywords_found': found
        }

    async def _generate_answer(
        self,
        question: str,
        documents: List[Dict],
        is_list_request: bool = False
    ) -> Tuple[str, Dict[str, Any]]:
        """Generate final answer using async LLM."""
        # Build context
        context_parts = []
        for i, doc in enumerate(documents[:10], 1):
            text = doc.get('text', '')[:1000]
            source = doc.get('metadata', {}).get('file_name', 'Unknown')
            score = doc.get('score', 0)
            context_parts.append(f"[문서 {i}] (출처: {source}, 관련도: {score:.2f})\n{text}\n")

        context = "\n".join(context_parts)
        context = self._truncate_context(context, max_tokens=6000)

        system_prompt = """당신은 IT 서버, 네트워크, 개발 전문가입니다.
제공된 사내 문서를 바탕으로 질문에 정확하게 답변하세요.

핵심 원칙:
1. 모든 답변은 사내 문서 기반
2. 출처 문서 번호 명시
3. 문서에 없는 내용은 "확인되지 않음" 표시"""

        if is_list_request:
            system_prompt += "\n\n목록 요청입니다. 표 형식이나 번호 목록으로 정리하세요."

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"질문: {question}\n\n문서:\n{context}"}
                ],
                temperature=self.temperature,
                max_tokens=1000
            )

            answer = response.choices[0].message.content or ""

            # Simple validation
            validation = {
                'confidence': 0.8 if len(documents) >= 3 else 0.5,
                'relevance_score': 0.8,
                'grounding_score': 0.8,
                'completeness_score': 0.8,
                'warnings': []
            }

            if len(documents) < 3:
                validation['warnings'].append("문서 수가 적어 답변 신뢰도가 낮을 수 있습니다.")

            return answer, validation

        except Exception as e:
            logger.error(f"Answer generation failed: {e}")
            return f"답변 생성 오류: {str(e)}", {
                'confidence': 0.0,
                'relevance_score': 0.0,
                'grounding_score': 0.0,
                'completeness_score': 0.0,
                'warnings': ['답변 생성 실패']
            }

    def _truncate_context(self, context: str, max_tokens: int) -> str:
        """Truncate context to fit token limit."""
        tokens = self.encoding.encode(context)
        if len(tokens) <= max_tokens:
            return context

        truncated = self.encoding.decode(tokens[:max_tokens])
        logger.warning(f"Context truncated: {len(tokens)} → {max_tokens} tokens")
        return truncated

    async def health_check(self) -> Dict[str, Any]:
        """Check health of all components."""
        await self._initialize()

        results = {}

        # Check DB
        try:
            results['database'] = await self._db_repo.is_connected()
        except Exception as e:
            results['database'] = False
            results['database_error'] = str(e)

        # Check Vector DB
        try:
            results['vector_db'] = await self._vector_repo.is_loaded()
        except Exception as e:
            results['vector_db'] = False
            results['vector_error'] = str(e)

        # Check ES
        try:
            results['elasticsearch'] = await self._es_repo.is_connected()
        except Exception as e:
            results['elasticsearch'] = False
            results['es_error'] = str(e)

        results['healthy'] = all([
            results.get('database', False),
            results.get('vector_db', False),
            results.get('elasticsearch', False)
        ])

        return results

    async def close(self):
        """Close all connections."""
        if self._db_repo:
            await self._db_repo.close()
        if self._vector_repo:
            await self._vector_repo.close()
        if self._es_repo:
            await self._es_repo.close()

        self._initialized = False
        logger.info("AsyncSearchAgent closed")
