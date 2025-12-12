"""
R-Agent Chat UI Production - Dual Mode (API + Direct Agent)
Supports both API mode and direct agent mode with automatic fallback
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
import traceback

# Suppress warnings
warnings.filterwarnings('ignore', message='.*torch.classes.*')

from config.settings import settings


# ===========================================
# Configuration
# ===========================================

API_BASE_URL = f"http://127.0.0.1:{settings.PORT}"
API_TIMEOUT = 120.0
MAX_RETRIES = 2
RETRY_DELAY = 0.5


# ===========================================
# Page Config
# ===========================================

st.set_page_config(
    page_title="R-Agent Chat",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed"
)


# ===========================================
# Custom CSS
# ===========================================

st.markdown("""
<style>
    /* Base styles */
    .main .block-container {
        padding-top: 1rem;
        padding-left: 1rem;
        padding-right: 1rem;
        max-width: 1200px;
    }

    .stChatMessage {
        padding: 0.75rem;
        border-radius: 10px;
        margin-bottom: 0.5rem;
    }

    .stButton > button {
        border-radius: 20px;
        transition: all 0.3s ease;
    }

    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }

    .mode-indicator {
        padding: 0.5rem 1rem;
        border-radius: 5px;
        font-weight: bold;
        margin-bottom: 1rem;
        text-align: center;
    }

    .api-mode {
        background-color: #e3f2fd;
        color: #1976d2;
    }

    .direct-mode {
        background-color: #fff3e0;
        color: #f57c00;
    }

    /* Mobile responsive styles */
    @media (max-width: 768px) {
        .main .block-container {
            padding-top: 3.5rem;
            padding-left: 0.5rem;
            padding-right: 0.5rem;
        }

        /* Hide sidebar by default on mobile */
        [data-testid="stSidebar"] {
            min-width: 0 !important;
            max-width: 100% !important;
        }

        [data-testid="stSidebar"][aria-expanded="true"] {
            min-width: 280px !important;
        }

        /* Adjust chat message padding */
        .stChatMessage {
            padding: 0.5rem;
        }

        /* Smaller title on mobile */
        h1 {
            font-size: 1.5rem !important;
        }

        /* Full width buttons */
        .stButton > button {
            width: 100%;
            padding: 0.5rem;
            font-size: 0.9rem;
        }

        /* Adjust expander content */
        .streamlit-expanderContent {
            padding: 0.5rem !important;
        }

        /* Feedback buttons smaller */
        .stButton > button[kind="secondary"] {
            padding: 0.3rem 0.5rem;
            font-size: 1.2rem;
        }

        /* Adjust columns spacing */
        [data-testid="column"] {
            padding: 0.25rem !important;
        }

        /* Chat input full width */
        [data-testid="stChatInput"] {
            padding: 0 !important;
        }

        /* Metrics smaller */
        [data-testid="stMetricValue"] {
            font-size: 1rem !important;
        }

        [data-testid="stMetricLabel"] {
            font-size: 0.8rem !important;
        }
    }

    /* Small mobile (under 480px) */
    @media (max-width: 480px) {
        h1 {
            font-size: 1.3rem !important;
        }

        .stChatMessage {
            font-size: 0.9rem;
        }

        /* Stack feedback buttons */
        .feedback-row {
            flex-wrap: wrap;
        }
    }

    /* Tablet responsive */
    @media (min-width: 769px) and (max-width: 1024px) {
        .main .block-container {
            max-width: 100%;
            padding-left: 1.5rem;
            padding-right: 1.5rem;
        }
    }
</style>
""", unsafe_allow_html=True)


# ===========================================
# Async Helpers
# ===========================================

def get_or_create_eventloop():
    """Get or create event loop."""
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
# Search Backends
# ===========================================

class APIBackend:
    """API-based search backend."""

    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url
        self.timeout = httpx.Timeout(API_TIMEOUT)
        self._available = None

    async def check_availability(self) -> bool:
        """Check if API is available."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                response = await client.get(f"{self.base_url}/health")
                data = response.json()
                return data.get('status') == 'healthy'
        except Exception:
            return False

    def is_available(self) -> bool:
        """Check availability synchronously."""
        if self._available is None:
            self._available = run_async(self.check_availability())
        return self._available

    def refresh_status(self):
        """Refresh availability status."""
        self._available = None

    async def search(
        self,
        question: str,
        session_id: Optional[str] = None,
        max_iterations: int = 5,
        debug: bool = True,
        poll_interval: float = 1.0,
        max_wait: int = 120
    ) -> Dict:
        """Execute search via async API with polling for result."""
        payload = {
            "question": question,
            "session_id": session_id,
            "max_iterations": max_iterations,
            "debug": debug
        }

        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    # Submit search request
                    response = await client.post(
                        f"{self.base_url}/api/v1/search",
                        json=payload
                    )

                    if response.status_code != 200:
                        continue

                    data = response.json()
                    task_id = data.get("task_id")

                    if not task_id:
                        return data  # Unexpected response

                    # Poll for result
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
                                result = status_data.get("result", {})
                                result["task_id"] = task_id
                                return result
                            elif status == "failed":
                                return {
                                    "success": False,
                                    "error": status_data.get("error", "Search failed"),
                                    "answer": f"검색 실패: {status_data.get('error', 'Unknown error')}"
                                }

                    # Timeout
                    return {
                        "success": False,
                        "error": "Timeout",
                        "answer": "검색 시간이 초과되었습니다."
                    }

            except Exception as e:
                if attempt == MAX_RETRIES - 1:
                    raise e
                await asyncio.sleep(RETRY_DELAY)

        return {"success": False, "error": "API request failed"}

    async def submit_feedback(
        self,
        session_id: str,
        satisfaction: int,
        is_relevant: bool,
        comment: str = ""
    ) -> Dict:
        """Submit feedback via API."""
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


class DirectBackend:
    """Direct SearchAgent backend (fallback)."""

    def __init__(self):
        self._agent = None
        self._available = None

    def _get_agent(self):
        """Get or create SearchAgent instance."""
        if self._agent is None:
            try:
                from agents.search_agent import SearchAgent
                self._agent = SearchAgent()
            except Exception as e:
                raise RuntimeError(f"Failed to initialize SearchAgent: {e}")
        return self._agent

    def is_available(self) -> bool:
        """Check if direct mode is available."""
        if self._available is None:
            try:
                self._get_agent()
                self._available = True
            except Exception:
                self._available = False
        return self._available

    def search(
        self,
        question: str,
        session_id: Optional[str] = None,
        max_iterations: int = 5,
        debug: bool = True
    ) -> Dict:
        """Execute search via direct agent."""
        agent = self._get_agent()

        try:
            result = agent.search(
                question=question,
                max_iterations=max_iterations,
                debug=debug
            )

            # Convert to API-compatible format
            return {
                "success": True,
                "answer": result.get('answer', ''),
                "confidence": result.get('confidence', 0.5),
                "sources": result.get('sources', []),
                "session_id": agent.session_id,
                "debug": result.get('debug')
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "answer": f"검색 중 오류가 발생했습니다: {str(e)}"
            }

    def submit_feedback(
        self,
        session_id: str,
        satisfaction: int,
        is_relevant: bool,
        comment: str = ""
    ) -> Dict:
        """Submit feedback directly to database."""
        try:
            from repositories.session_context_repository import SessionContextRepository
            repo = SessionContextRepository()
            success = repo.update_satisfaction(
                session_id=session_id,
                satisfaction=satisfaction,
                is_relevant=is_relevant,
                comment=comment
            )
            return {"success": success}
        except Exception as e:
            return {"success": False, "error": str(e)}


# ===========================================
# Unified Backend Manager
# ===========================================

class BackendManager:
    """Manages API and Direct backends with automatic fallback."""

    def __init__(self):
        self.api_backend = APIBackend()
        self.direct_backend = DirectBackend()
        self._current_mode = None

    def get_mode(self) -> str:
        """Get current mode (api/direct)."""
        if self._current_mode is None:
            if self.api_backend.is_available():
                self._current_mode = 'api'
            elif self.direct_backend.is_available():
                self._current_mode = 'direct'
            else:
                self._current_mode = 'unavailable'
        return self._current_mode

    def refresh(self):
        """Refresh backend status."""
        self._current_mode = None
        self.api_backend.refresh_status()

    def search(
        self,
        question: str,
        session_id: Optional[str] = None,
        max_iterations: int = 5,
        debug: bool = True
    ) -> Dict:
        """Execute search using available backend."""
        mode = self.get_mode()

        if mode == 'api':
            try:
                return run_async(self.api_backend.search(
                    question, session_id, max_iterations, debug
                ))
            except Exception as e:
                # Fallback to direct mode
                if self.direct_backend.is_available():
                    self._current_mode = 'direct'
                    return self.direct_backend.search(
                        question, session_id, max_iterations, debug
                    )
                raise e

        elif mode == 'direct':
            return self.direct_backend.search(
                question, session_id, max_iterations, debug
            )

        else:
            return {
                "success": False,
                "error": "No backend available",
                "answer": "서비스를 사용할 수 없습니다. 시스템 관리자에게 문의하세요."
            }

    def submit_feedback(
        self,
        session_id: str,
        satisfaction: int,
        is_relevant: bool,
        comment: str = ""
    ) -> Dict:
        """Submit feedback using available backend."""
        mode = self.get_mode()

        if mode == 'api':
            try:
                return run_async(self.api_backend.submit_feedback(
                    session_id, satisfaction, is_relevant, comment
                ))
            except Exception:
                return self.direct_backend.submit_feedback(
                    session_id, satisfaction, is_relevant, comment
                )

        elif mode == 'direct':
            return self.direct_backend.submit_feedback(
                session_id, satisfaction, is_relevant, comment
            )

        return {"success": False, "error": "No backend available"}


# ===========================================
# Session State
# ===========================================

def initialize_session_state():
    """Initialize session state."""
    if 'messages' not in st.session_state:
        st.session_state.messages = []

    if 'session_id' not in st.session_state:
        st.session_state.session_id = f"ui-{uuid.uuid4().hex[:8]}"

    if 'feedback_given' not in st.session_state:
        st.session_state.feedback_given = set()

    if 'backend' not in st.session_state:
        st.session_state.backend = BackendManager()


# ===========================================
# UI Components
# ===========================================

def display_mode_indicator():
    """Display current mode indicator."""
    mode = st.session_state.backend.get_mode()

    if mode == 'api':
        st.markdown(
            '<div class="mode-indicator api-mode">🌐 API 모드</div>',
            unsafe_allow_html=True
        )
    elif mode == 'direct':
        st.markdown(
            '<div class="mode-indicator direct-mode">🔌 직접 연결 모드</div>',
            unsafe_allow_html=True
        )
    else:
        st.error("⚠️ 서비스 불가")


def display_message(
    role: str,
    content: str,
    msg_session_id: str = None, # type: ignore
    sources: list = None, # type: ignore
    debug: Dict = None # type: ignore
):
    """Display chat message."""
    with st.chat_message(role):
        st.markdown(content)

        if role == "assistant" and msg_session_id:
            # Debug info
            if debug:
                with st.expander("🔍 검색 상세", expanded=False):
                    cols = st.columns(4)
                    with cols[0]:
                        st.metric("반복", debug.get('iterations', 0))
                    with cols[1]:
                        st.metric("문서", debug.get('total_documents', 0))
                    with cols[2]:
                        exec_time = debug.get('execution_time', 0)
                        st.metric("시간", f"{exec_time:.1f}s" if exec_time else "-")
                    with cols[3]:
                        st.metric("도구", len(debug.get('tools_used', [])))

                    if debug.get('tools_used'):
                        st.caption(f"도구: {', '.join(debug['tools_used'])}")

            # Sources - 각 문서별 개별 expander (중첩 불가)
            if sources:
                st.markdown(f"**📚 출처 ({len(sources)}개)**")
                for i, doc in enumerate(sources, 1):
                    score = doc.get('score', 0)
                    file_name = doc.get('metadata', {}).get('file_name', 'Unknown')
                    source_type = doc.get('source', 'unknown')
                    text = doc.get('text', '')

                    with st.expander(f"[{i}] {file_name} ({source_type}, {score:.2f})", expanded=False):
                        st.markdown(text)

            # Feedback
            if msg_session_id not in st.session_state.feedback_given:
                st.markdown("---")
                st.markdown("**답변이 도움이 되었나요?**")

                cols = st.columns(5)
                feedbacks = [
                    ("👍", 5, True, "매우 만족"),
                    ("🙂", 4, True, "만족"),
                    ("😐", 3, True, "보통"),
                    ("😕", 2, False, "불만족"),
                    ("👎", 1, False, "매우 불만족")
                ]

                for i, (emoji, score, relevant, label) in enumerate(feedbacks):
                    with cols[i]:
                        if st.button(emoji, key=f"fb{score}_{msg_session_id}", help=label):
                            result = st.session_state.backend.submit_feedback(
                                msg_session_id, score, relevant, label
                            )
                            if result.get('success'):
                                st.session_state.feedback_given.add(msg_session_id)
                                st.toast(f"✅ 피드백 저장! ({score}/5)")
                            st.rerun()

            else:
                st.success("✅ 피드백 감사합니다!")




# ===========================================
# Main Application
# ===========================================

def main():
    """Main application."""
    initialize_session_state()

    # Sidebar
    with st.sidebar:
        st.title("🤖 R-Agent")
        st.caption("RAG 문서 검색 에이전트")

        st.markdown("---")

        # Mode indicator
        st.subheader("📡 연결 상태")
        display_mode_indicator()

        if st.button("🔄 연결 새로고침"):
            st.session_state.backend.refresh()
            st.rerun()

        st.markdown("---")

        # Settings
        st.subheader("⚙️ 설정")

        max_iterations = st.slider("최대 반복", 1, 10, 5)
        show_debug = st.checkbox("디버그 표시", True)
        show_sources = st.checkbox("출처 표시", True)

        st.markdown("---")

        # Controls
        if st.button("🔄 새 대화", type="secondary", use_container_width=True):
            st.session_state.messages = []
            st.session_state.feedback_given = set()
            st.session_state.session_id = f"ui-{uuid.uuid4().hex[:8]}"
            st.rerun()

        st.markdown("---")
        st.caption(f"세션: `{st.session_state.session_id[:12]}...`")
        st.caption(f"모드: `{st.session_state.backend.get_mode()}`")

    # Main area
    st.title("💬 R-Agent Chat")
    st.caption("질문하시면 답변을 찾아드립니다.")

    # Messages
    for msg in st.session_state.messages:
        display_message(
            role=msg['role'],
            content=msg['content'],
            msg_session_id=msg.get('session_id'),
            sources=msg.get('sources') if show_sources else None, # type: ignore
            debug=msg.get('debug') if show_debug else None # type: ignore
        )

    # Input
    if prompt := st.chat_input("질문을 입력하세요..."):
        # Add user message
        st.session_state.messages.append({
            'role': 'user',
            'content': prompt
        })

        display_message('user', prompt)

        # Search
        with st.spinner("🔍 검색 중..."):
            start_time = time.time()

            try:
                result = st.session_state.backend.search(
                    question=prompt,
                    session_id=st.session_state.session_id,
                    max_iterations=max_iterations,
                    debug=show_debug
                )

                elapsed = time.time() - start_time

                if result.get('success', False):
                    answer = result.get('answer', '')
                    sources = result.get('sources', [])
                    debug_info = result.get('debug')
                    response_session_id = result.get('session_id', st.session_state.session_id)

                    if debug_info:
                        debug_info['execution_time'] = elapsed

                    st.session_state.messages.append({
                        'role': 'assistant',
                        'content': answer,
                        'session_id': response_session_id,
                        'sources': sources if show_sources else None,
                        'debug': debug_info if show_debug else None
                    })
                else:
                    error = result.get('error', result.get('answer', '검색 실패'))
                    st.session_state.messages.append({
                        'role': 'assistant',
                        'content': f"⚠️ {error}",
                        'session_id': None
                    })

            except Exception as e:
                st.error(f"❌ 오류: {e}")
                st.session_state.messages.append({
                    'role': 'assistant',
                    'content': f"⚠️ 오류: {str(e)}",
                    'session_id': None
                })

        st.rerun()



if __name__ == "__main__":
    main()
