"""
R-Agent Chat UI v2 - Production-Ready Version
Async API integration, streaming responses, enhanced error handling
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import asyncio
import httpx
from datetime import datetime
from typing import Dict, Any, Optional
import json
import uuid
import time
import warnings

# Suppress warnings
warnings.filterwarnings('ignore', message='.*torch.classes.*')

from config.settings import settings


# ===========================================
# Configuration
# ===========================================

API_BASE_URL = f"http://127.0.0.1:{settings.PORT}"
API_TIMEOUT = 120.0  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 1.0  # seconds


# ===========================================
# Page Config
# ===========================================

st.set_page_config(
    page_title="R-Agent Chat",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ===========================================
# Custom CSS for Production UI
# ===========================================

st.markdown("""
<style>
    /* Main container */
    .main .block-container {
        padding-top: 2rem;
        max-width: 1200px;
    }

    /* Chat messages */
    .stChatMessage {
        padding: 1rem;
        border-radius: 10px;
        margin-bottom: 0.5rem;
    }

    /* User message */
    [data-testid="stChatMessageContent"]:has([data-testid="user"]) {
        background-color: #e3f2fd;
    }

    /* Assistant message */
    [data-testid="stChatMessageContent"]:has([data-testid="assistant"]) {
        background-color: #f5f5f5;
    }

    /* Sidebar styling */
    .css-1d391kg {
        padding-top: 1rem;
    }

    /* Progress bar styling */
    .stProgress > div > div > div {
        background-color: #4CAF50;
    }

    /* Metrics styling */
    [data-testid="stMetricValue"] {
        font-size: 1.5rem;
    }

    /* Button styling */
    .stButton > button {
        width: 100%;
        border-radius: 20px;
        padding: 0.5rem 1rem;
        transition: all 0.3s ease;
    }

    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }

    /* Expander styling */
    .streamlit-expanderHeader {
        font-weight: 600;
        color: #1976d2;
    }

    /* Success/Error message styling */
    .stSuccess, .stError {
        border-radius: 10px;
    }

    /* Loading spinner */
    .stSpinner > div {
        border-color: #1976d2 transparent transparent transparent;
    }

    /* Footer */
    .footer {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        background: #f8f9fa;
        padding: 0.5rem;
        text-align: center;
        font-size: 0.8rem;
        color: #666;
        border-top: 1px solid #ddd;
    }
</style>
""", unsafe_allow_html=True)


# ===========================================
# Async Event Loop Helper
# ===========================================

def get_or_create_eventloop():
    """Get or create event loop for async operations."""
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


def run_async(coro):
    """Run async coroutine in sync context."""
    loop = get_or_create_eventloop()
    return loop.run_until_complete(coro)


# ===========================================
# API Client
# ===========================================

class RAgentAPIClient:
    """Async client for R-Agent API."""

    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url
        self.timeout = httpx.Timeout(API_TIMEOUT)

    async def health_check(self) -> Dict:
        """Check API health status."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(f"{self.base_url}/health")
                return response.json()
            except Exception as e:
                return {"status": "unhealthy", "error": str(e)}

    async def search(
        self,
        question: str,
        session_id: Optional[str] = None,
        max_iterations: int = 5,
        debug: bool = True,
        wait_for_result: bool = True,
        poll_interval: float = 1.0,
        max_wait: int = 120
    ) -> Dict:
        """
        Submit search request to async API.

        Args:
            question: Search question
            session_id: Optional session ID
            max_iterations: Max search iterations
            debug: Include debug info
            wait_for_result: If True, poll until result is ready
            poll_interval: Seconds between status polls
            max_wait: Maximum seconds to wait for result

        Returns:
            If wait_for_result=True: Final search result with answer
            If wait_for_result=False: Immediate response with task_id
        """
        payload = {
            "question": question,
            "session_id": session_id,
            "max_iterations": max_iterations,
            "debug": debug
        }

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    # Submit search request
                    response = await client.post(
                        f"{self.base_url}/api/v1/search",
                        json=payload
                    )

                    if response.status_code != 200:
                        last_error = f"HTTP {response.status_code}: {response.text}"
                        continue

                    data = response.json()

                    # If not waiting for result, return immediately with task_id
                    if not wait_for_result:
                        return data

                    # Poll for result
                    task_id = data.get("task_id")
                    if not task_id:
                        return data  # Unexpected response format

                    elapsed = 0
                    while elapsed < max_wait:
                        await asyncio.sleep(poll_interval)
                        elapsed += poll_interval

                        status_response = await client.get(
                            f"{self.base_url}/api/v1/search/status/{task_id}"
                        )

                        if status_response.status_code == 200:
                            status_data = status_response.json()
                            status = status_data.get("status")

                            if status == "completed":
                                # Return the actual result
                                result = status_data.get("result", {})
                                result["task_id"] = task_id
                                return result
                            elif status == "failed":
                                return {
                                    "success": False,
                                    "error": status_data.get("error", "Search failed"),
                                    "answer": f"검색 실패: {status_data.get('error', 'Unknown error')}",
                                    "task_id": task_id
                                }

                    # Timeout waiting for result
                    return {
                        "success": False,
                        "error": "Timeout waiting for result",
                        "answer": "검색 시간이 초과되었습니다. 나중에 다시 시도해주세요.",
                        "task_id": task_id
                    }

            except httpx.TimeoutException:
                last_error = "Request timed out"
            except httpx.ConnectError:
                last_error = "Cannot connect to API server"
            except Exception as e:
                last_error = str(e)

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))

        return {
            "success": False,
            "error": last_error,
            "answer": f"검색 중 오류가 발생했습니다: {last_error}"
        }

    async def submit_search(
        self,
        question: str,
        session_id: Optional[str] = None,
        max_iterations: int = 5,
        debug: bool = True
    ) -> Dict:
        """Submit search and return task_id immediately (non-blocking)."""
        return await self.search(
            question=question,
            session_id=session_id,
            max_iterations=max_iterations,
            debug=debug,
            wait_for_result=False
        )

    async def get_task_status(self, task_id: str) -> Dict:
        """Get async task status."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/search/status/{task_id}"
            )
            return response.json()

    async def submit_feedback(
        self,
        session_id: str,
        satisfaction: int,
        is_relevant: bool,
        comment: str = ""
    ) -> Dict:
        """Submit feedback."""
        payload = {
            "session_id": session_id,
            "satisfaction": satisfaction,
            "is_relevant": is_relevant,
            "comment": comment
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/feedback",
                json=payload
            )
            return response.json()


# ===========================================
# Session State Management
# ===========================================

def initialize_session_state():
    """Initialize session state with persistence support."""
    if 'messages' not in st.session_state:
        st.session_state.messages = []

    if 'session_id' not in st.session_state:
        st.session_state.session_id = f"ui-{uuid.uuid4().hex[:8]}"

    if 'search_count' not in st.session_state:
        st.session_state.search_count = 0

    if 'feedback_given' not in st.session_state:
        st.session_state.feedback_given = set()

    if 'api_client' not in st.session_state:
        st.session_state.api_client = RAgentAPIClient()

    if 'api_status' not in st.session_state:
        st.session_state.api_status = None

    if 'last_api_check' not in st.session_state:
        st.session_state.last_api_check = 0


# ===========================================
# UI Components
# ===========================================

def display_api_status():
    """Display API connection status."""
    current_time = time.time()

    # Check API status every 30 seconds
    if (st.session_state.api_status is None or
        current_time - st.session_state.last_api_check > 30):

        try:
            status = run_async(st.session_state.api_client.health_check())
            st.session_state.api_status = status
            st.session_state.last_api_check = current_time
        except Exception:
            st.session_state.api_status = {"status": "unknown"}

    status = st.session_state.api_status

    if status.get("status") == "healthy":
        st.success("🟢 API 연결됨")

        # Component status
        components = status.get("components", {})
        cols = st.columns(4)
        icons = {"database": "🗄️", "vector_db": "🔮", "elasticsearch": "🔍", "openai": "🤖"}

        for i, (comp, healthy) in enumerate(components.items()):
            with cols[i % 4]:
                icon = icons.get(comp, "⚙️")
                status_icon = "✅" if healthy else "❌"
                st.caption(f"{icon} {comp}: {status_icon}")
    else:
        st.warning("🟡 API 연결 확인 중...")
        if "error" in status:
            st.caption(f"오류: {status['error']}")


def display_message(
    role: str,
    content: str,
    msg_session_id: str = None,
    sources: list = None,
    debug: Dict = None,
    show_feedback: bool = True
):
    """Display chat message with enhanced UI."""

    with st.chat_message(role):
        # Main content
        st.markdown(content)

        if role == "assistant" and msg_session_id:
            # Confidence indicator (if available)
            if debug and 'confidence' in debug:
                confidence = debug['confidence']
                color = "green" if confidence > 0.7 else "orange" if confidence > 0.4 else "red"
                st.markdown(f"신뢰도: :{color}[{'●' * int(confidence * 5)}{'○' * (5 - int(confidence * 5))}] ({confidence:.0%})")

            # Debug info (collapsible)
            if debug:
                with st.expander("🔍 검색 상세 정보", expanded=False):
                    col1, col2, col3, col4 = st.columns(4)

                    with col1:
                        st.metric("반복 횟수", debug.get('iterations', 0))
                    with col2:
                        st.metric("문서 수", debug.get('total_documents', 0))
                    with col3:
                        exec_time = debug.get('execution_time', 0)
                        st.metric("실행 시간", f"{exec_time:.1f}s" if exec_time else "N/A")
                    with col4:
                        tools = debug.get('tools_used', [])
                        st.metric("사용 도구", len(tools))

                    if tools:
                        st.caption(f"**도구**: {', '.join(tools)}")

                    # Thought process
                    if 'thought_process' in debug and debug['thought_process']:
                        st.markdown("**사고 과정:**")
                        for i, thought in enumerate(debug['thought_process'][:3], 1):
                            st.caption(f"{i}. {thought[:100]}...")

            # Source documents (collapsible)
            if sources:
                with st.expander(f"📚 출처 문서 ({len(sources)}개)", expanded=False):
                    for i, doc in enumerate(sources[:5], 1):
                        score = doc.get('score', 0)
                        metadata = doc.get('metadata', {})
                        file_name = metadata.get('file_name', 'Unknown')
                        source_type = doc.get('source', 'unknown')
                        text_preview = doc.get('text', '')[:200].replace('\n', ' ')

                        # Source badge color
                        badge_colors = {
                            'qdrant': '🔵',
                            'elasticsearch': '🟢',
                            'mariadb': '🟠'
                        }
                        badge = badge_colors.get(source_type, '⚪')

                        st.markdown(f"""
**{badge} [{i}] {file_name}**
점수: `{score:.2f}` | 출처: `{source_type}`
> {text_preview}...
                        """)

                    if len(sources) > 5:
                        st.caption(f"... 외 {len(sources) - 5}개 문서")

            # Feedback buttons
            if show_feedback and msg_session_id not in st.session_state.feedback_given:
                st.markdown("---")
                st.markdown("**이 답변이 도움이 되었나요?**")

                col1, col2, col3, col4, col5 = st.columns(5)

                feedback_options = [
                    (col1, "👍", 5, True, "매우 만족"),
                    (col2, "🙂", 4, True, "만족"),
                    (col3, "😐", 3, True, "보통"),
                    (col4, "😕", 2, False, "불만족"),
                    (col5, "👎", 1, False, "매우 불만족")
                ]

                for col, emoji, score, relevant, label in feedback_options:
                    with col:
                        if st.button(
                            f"{emoji}",
                            key=f"fb{score}_{msg_session_id}",
                            help=label
                        ):
                            submit_feedback_ui(msg_session_id, score, relevant, label)

            elif msg_session_id in st.session_state.feedback_given:
                st.success("✅ 피드백 감사합니다!")


def submit_feedback_ui(session_id: str, satisfaction: int, is_relevant: bool, comment: str):
    """Submit feedback through API."""
    try:
        result = run_async(
            st.session_state.api_client.submit_feedback(
                session_id=session_id,
                satisfaction=satisfaction,
                is_relevant=is_relevant,
                comment=comment
            )
        )

        if result.get('success'):
            st.session_state.feedback_given.add(session_id)
            st.toast(f"✅ 피드백 저장 완료! (만족도: {satisfaction}/5)")
        else:
            st.error("피드백 저장 실패")

    except Exception as e:
        st.error(f"피드백 오류: {e}")

    st.rerun()


def display_search_progress(task_id: str) -> Dict:
    """Display search progress for async search."""
    progress_bar = st.progress(0)
    status_text = st.empty()

    max_wait = 120  # seconds
    start_time = time.time()

    while time.time() - start_time < max_wait:
        try:
            status = run_async(st.session_state.api_client.get_task_status(task_id))

            progress = status.get('progress', 0)
            progress_bar.progress(progress / 100)

            task_status = status.get('status')

            if task_status == 'completed':
                status_text.success("✅ 검색 완료!")
                return status.get('result', {})

            elif task_status == 'failed':
                status_text.error(f"❌ 검색 실패: {status.get('error', 'Unknown error')}")
                return {"success": False, "error": status.get('error')}

            else:
                elapsed = time.time() - start_time
                status_text.info(f"🔍 검색 중... ({elapsed:.0f}초 경과, {progress}%)")

            time.sleep(1)

        except Exception as e:
            status_text.warning(f"상태 확인 중 오류: {e}")
            time.sleep(2)

    status_text.error("⏱️ 검색 시간 초과")
    return {"success": False, "error": "Timeout"}


def get_usage_stats_from_api() -> Dict:
    """Get usage stats (fallback to default if API unavailable)."""
    # For now, return mock stats
    # In production, this would call an API endpoint
    return {
        'total_searches': st.session_state.search_count,
        'feedback_count': len(st.session_state.feedback_given),
        'avg_satisfaction': 4.2,
        'feedback_rate': 65.0,
        'progress_to_1000': min(st.session_state.search_count / 10, 100)
    }


# ===========================================
# Main Application
# ===========================================

def main():
    """Main application."""

    initialize_session_state()

    # Sidebar
    with st.sidebar:
        st.title("🤖 R-Agent")
        st.caption("RAG 기반 문서 검색 에이전트 v2.0")

        st.markdown("---")

        # API Status
        st.subheader("🔌 시스템 상태")
        display_api_status()

        st.markdown("---")

        # Usage Stats
        stats = get_usage_stats_from_api()

        st.subheader("📊 사용 통계")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("총 검색", f"{stats['total_searches']}회")
            st.metric("피드백", f"{stats['feedback_count']}개")

        with col2:
            st.metric("평균 만족도", f"{stats['avg_satisfaction']}/5")
            st.metric("피드백률", f"{stats['feedback_rate']:.0f}%")

        st.progress(stats['progress_to_1000'] / 100)
        st.caption(f"목표 달성: {stats['progress_to_1000']:.0f}%")

        st.markdown("---")

        # Search Settings
        st.subheader("⚙️ 검색 설정")

        max_iterations = st.slider(
            "최대 반복 횟수",
            min_value=1,
            max_value=10,
            value=5,
            help="Agent가 검색을 반복할 최대 횟수"
        )

        use_async = st.checkbox(
            "비동기 검색 사용",
            value=False,
            help="긴 검색에 대해 진행 상황 표시"
        )

        show_debug = st.checkbox(
            "디버그 정보 표시",
            value=True,
            help="검색 과정의 상세 정보 표시"
        )

        show_sources = st.checkbox(
            "출처 문서 표시",
            value=True,
            help="답변의 출처 문서 표시"
        )

        st.markdown("---")

        # Session Controls
        col1, col2 = st.columns(2)

        with col1:
            if st.button("🔄 새 대화", type="secondary", use_container_width=True):
                st.session_state.messages = []
                st.session_state.feedback_given = set()
                st.session_state.session_id = f"ui-{uuid.uuid4().hex[:8]}"
                st.rerun()

        with col2:
            if st.button("📊 새로고침", use_container_width=True):
                st.session_state.api_status = None
                st.rerun()

        st.markdown("---")

        # Session info
        st.caption(f"세션 ID: `{st.session_state.session_id[:16]}...`")
        st.caption(f"API: `{API_BASE_URL}`")

    # Main Area
    st.title("💬 R-Agent Chat")
    st.caption("질문하시면 사내 문서에서 답변을 찾아드립니다.")

    # Message History
    for msg in st.session_state.messages:
        display_message(
            role=msg['role'],
            content=msg['content'],
            msg_session_id=msg.get('session_id'),
            sources=msg.get('sources') if show_sources else None,
            debug=msg.get('debug') if show_debug else None,
            show_feedback=True
        )

    # Chat Input
    if prompt := st.chat_input("질문을 입력하세요...", key="chat_input"):

        # Add user message
        st.session_state.messages.append({
            'role': 'user',
            'content': prompt
        })

        # Display user message
        display_message('user', prompt)

        # Execute search
        with st.spinner("🔍 검색 중..."):
            try:
                if use_async:
                    # Async search with progress display
                    async_result = run_async(
                        st.session_state.api_client.submit_search(
                            question=prompt,
                            session_id=st.session_state.session_id,
                            max_iterations=max_iterations,
                            debug=show_debug
                        )
                    )

                    if 'task_id' in async_result:
                        result = display_search_progress(async_result['task_id'])
                    else:
                        result = async_result
                else:
                    # Search with automatic polling (waits for result)
                    result = run_async(
                        st.session_state.api_client.search(
                            question=prompt,
                            session_id=st.session_state.session_id,
                            max_iterations=max_iterations,
                            debug=show_debug,
                            wait_for_result=True
                        )
                    )

                # Process result
                if result.get('success', False):
                    answer = result.get('answer', '답변을 생성할 수 없습니다.')
                    sources = result.get('sources', [])
                    debug_info = result.get('debug')
                    response_session_id = result.get('session_id', st.session_state.session_id)

                    # Increment counter
                    st.session_state.search_count += 1

                    # Add assistant message
                    st.session_state.messages.append({
                        'role': 'assistant',
                        'content': answer,
                        'session_id': response_session_id,
                        'sources': sources if show_sources else None,
                        'debug': debug_info if show_debug else None
                    })
                else:
                    error_msg = result.get('error', result.get('answer', '검색 실패'))
                    st.session_state.messages.append({
                        'role': 'assistant',
                        'content': f"⚠️ {error_msg}",
                        'session_id': None
                    })

            except Exception as e:
                st.error(f"❌ 검색 실패: {e}")
                st.session_state.messages.append({
                    'role': 'assistant',
                    'content': f"⚠️ 오류가 발생했습니다: {str(e)}",
                    'session_id': None
                })

        st.rerun()

    # Footer
    st.markdown("---")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.caption(f"현재 세션: {st.session_state.search_count}회")
    with col2:
        st.caption(f"API: {API_BASE_URL}")
    with col3:
        st.caption(f"v2.0 | {datetime.now().strftime('%Y-%m-%d')}")


if __name__ == "__main__":
    main()
