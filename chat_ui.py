"""
R-Agent Chat UI with Feedback System
Streamlit 기반 대화형 UI + 답변 품질 피드백 수집
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
from datetime import datetime
from typing import Dict, Any
import json
import warnings

# Suppress PyTorch/Streamlit file watcher warning (cosmetic only)
warnings.filterwarnings('ignore', message='.*torch.classes.*')

from agents.search_agent import SearchAgent
from repositories.session_context_repository import SessionContextRepository


# 페이지 설정
st.set_page_config(
    page_title="R-Agent Chat",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)


def initialize_session_state():
    """세션 상태 초기화"""
    if 'messages' not in st.session_state:
        st.session_state.messages = []

    if 'agent' not in st.session_state:
        st.session_state.agent = SearchAgent()

    if 'search_count' not in st.session_state:
        st.session_state.search_count = 0

    if 'feedback_given' not in st.session_state:
        st.session_state.feedback_given = set()  # session_id set


def display_message(role: str, content: str, session_id: str = None,
                   sources: list = None, debug: Dict = None):
    """메시지 표시"""

    with st.chat_message(role):
        st.markdown(content)

        # 답변인 경우 추가 정보 표시
        if role == "assistant" and session_id:

            # 디버그 정보 (접을 수 있게)
            if debug:
                with st.expander("🔍 검색 상세 정보"):
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("반복 횟수", debug['iterations'])
                    with col2:
                        st.metric("문서 수", debug['total_documents'])
                    with col3:
                        st.metric("실행 시간", f"{debug['execution_time']}s")
                    with col4:
                        st.metric("사용 도구", len(debug['tools_used']))

                    st.caption(f"**도구**: {', '.join(debug['tools_used'])}")

            # 출처 문서 (접을 수 있게)
            if sources and len(sources) > 0:
                with st.expander(f"📚 출처 문서 ({len(sources)}개)"):
                    for i, doc in enumerate(sources, 1):
                        score = doc.get('score', 0)
                        file_name = doc.get('metadata', {}).get('file_name', 'Unknown')
                        text_preview = doc.get('text', '')[:150].replace('\n', ' ')

                        st.markdown(f"""
**[{i}] {file_name}**
점수: `{score:.2f}` | 미리보기: {text_preview}...
                        """)

            # 피드백 버튼
            if session_id not in st.session_state.feedback_given:
                st.markdown("---")
                st.markdown("**이 답변이 도움이 되었나요?**")

                col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 3])

                with col1:
                    if st.button("👍 매우 만족", key=f"fb5_{session_id}"):
                        submit_feedback(session_id, 5, True, "매우 만족")

                with col2:
                    if st.button("🙂 만족", key=f"fb4_{session_id}"):
                        submit_feedback(session_id, 4, True, "만족")

                with col3:
                    if st.button("😐 보통", key=f"fb3_{session_id}"):
                        submit_feedback(session_id, 3, True, "보통")

                with col4:
                    if st.button("👎 불만족", key=f"fb2_{session_id}"):
                        submit_feedback(session_id, 2, False, "불만족")

                with col5:
                    if st.button("😡 매우 불만족", key=f"fb1_{session_id}"):
                        submit_feedback(session_id, 1, False, "매우 불만족")

            else:
                st.success("✅ 피드백 감사합니다!")


def submit_feedback(session_id: str, satisfaction: int, is_relevant: bool, comment: str):
    """피드백 제출"""
    try:
        repo = SessionContextRepository()
        success = repo.update_satisfaction(
            session_id=session_id,
            satisfaction=satisfaction,
            is_relevant=is_relevant,
            comment=comment
        )

        if success:
            st.session_state.feedback_given.add(session_id)
            st.success(f"✅ 피드백 저장 완료! (만족도: {satisfaction}/5)")
        else:
            st.error("❌ 피드백 저장 실패")
            st.stop()  # 실패 시 중단

    except Exception as e:
        st.error(f"❌ 에러: {e}")
        st.stop()  # 에러 시 중단

    # 피드백 저장 성공 후 화면 새로고침
    st.rerun()


def get_usage_stats():
    """사용 통계 조회"""
    import mysql.connector
    from config.settings import settings

    try:
        conn = mysql.connector.connect(
            host=settings.LEARNING_DB_HOST,
            port=settings.LEARNING_DB_PORT,
            user=settings.LEARNING_DB_USER,
            password=settings.LEARNING_DB_PASSWORD,
            database=settings.LEARNING_DB_NAME
        )

        cursor = conn.cursor(dictionary=True)

        # 총 검색 수
        cursor.execute('SELECT COUNT(DISTINCT session_id) as total FROM tool_performance_log')
        total = cursor.fetchone()['total']

        # 피드백 수
        cursor.execute('SELECT COUNT(*) as feedback_count FROM session_context WHERE avg_satisfaction IS NOT NULL')
        feedback = cursor.fetchone()['feedback_count']

        # 평균 만족도
        cursor.execute('SELECT AVG(avg_satisfaction) as avg_sat FROM session_context WHERE avg_satisfaction IS NOT NULL')
        avg_sat = cursor.fetchone()['avg_sat'] or 0

        cursor.close()
        conn.close()

        return {
            'total_searches': total,
            'feedback_count': feedback,
            'avg_satisfaction': round(avg_sat, 2),
            'feedback_rate': round(feedback / total * 100, 1) if total > 0 else 0,
            'progress_to_1000': round(total / 1000 * 100, 1)
        }

    except Exception as e:
        return {
            'total_searches': 0,
            'feedback_count': 0,
            'avg_satisfaction': 0,
            'feedback_rate': 0,
            'progress_to_1000': 0
        }


def main():
    """메인 UI"""

    initialize_session_state()

    # 사이드바
    with st.sidebar:
        st.title("🤖 R-Agent")
        st.caption("RAG 기반 문서 검색 에이전트")

        st.markdown("---")

        # 사용 통계
        stats = get_usage_stats()

        st.subheader("📊 사용 통계")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("총 검색", f"{stats['total_searches']}회")
            st.metric("피드백", f"{stats['feedback_count']}개")

        with col2:
            st.metric("평균 만족도", f"{stats['avg_satisfaction']}/5")
            st.metric("피드백률", f"{stats['feedback_rate']}%")

        st.progress(stats['progress_to_1000'] / 100)
        st.caption(f"1,000회 달성: {stats['progress_to_1000']}%")

        st.markdown("---")

        # 설정
        st.subheader("⚙️ 검색 설정")

        max_iterations = st.slider(
            "최대 반복 횟수",
            min_value=1,
            max_value=10,
            value=5,
            help="Agent가 검색을 반복할 최대 횟수"
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

        # 세션 초기화
        if st.button("🔄 새 대화 시작", type="secondary"):
            st.session_state.messages = []
            st.session_state.feedback_given = set()
            st.rerun()

        # 통계 새로고침
        if st.button("📊 통계 새로고침"):
            st.rerun()

    # 메인 영역
    st.title("💬 R-Agent Chat")
    st.caption("질문하시면 사내 문서에서 답변을 찾아드립니다.")

    # 대화 히스토리 표시
    for msg in st.session_state.messages:
        display_message(
            role=msg['role'],
            content=msg['content'],
            session_id=msg.get('session_id'),
            sources=msg.get('sources') if show_sources else None,
            debug=msg.get('debug') if show_debug else None
        )

    # 입력창
    if prompt := st.chat_input("질문을 입력하세요..."):

        # 사용자 메시지 추가
        st.session_state.messages.append({
            'role': 'user',
            'content': prompt
        })

        # 사용자 메시지 표시
        display_message('user', prompt)

        # Agent 검색 실행
        with st.spinner("🔍 검색 중..."):
            try:
                result = st.session_state.agent.search(
                    question=prompt,
                    max_iterations=max_iterations,
                    debug=True
                )

                answer = result['answer']
                sources = result['sources']
                debug_info = result.get('debug', {})
                session_id = st.session_state.agent.session_id

                # 검색 카운트 증가
                st.session_state.search_count += 1

                # Assistant 메시지 추가
                st.session_state.messages.append({
                    'role': 'assistant',
                    'content': answer,
                    'session_id': session_id,
                    'sources': sources if show_sources else None,
                    'debug': debug_info if show_debug else None
                })

            except Exception as e:
                st.error(f"❌ 검색 실패: {e}")
                st.stop()  # 에러 발생 시 여기서 중단

        # 검색 성공 후 화면 새로고침 (메시지 히스토리 표시)
        st.rerun()

    # 하단 정보
    st.markdown("---")
    st.caption(f"현재 세션 검색: {st.session_state.search_count}회 | "
              f"총 검색: {stats['total_searches']}회 | "
              f"use_learning: {'✅ ON' if st.session_state.agent.use_learning else '❌ OFF'}")


if __name__ == "__main__":
    main()
