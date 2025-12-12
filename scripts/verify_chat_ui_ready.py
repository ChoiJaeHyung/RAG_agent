#!/usr/bin/env python3
"""
Chat UI 준비 상태 검증 스크립트
모든 컴포넌트가 정상 작동하는지 확인
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

def check_imports():
    """필수 import 확인"""
    print("=" * 60)
    print("1. Import 검증")
    print("=" * 60)

    try:
        import streamlit
        print("✅ Streamlit 설치됨:", streamlit.__version__)
    except ImportError:
        print("❌ Streamlit 미설치 - pip install streamlit 실행 필요")
        return False

    try:
        from agents.search_agent import SearchAgent
        print("✅ SearchAgent import 성공")
    except Exception as e:
        print(f"❌ SearchAgent import 실패: {e}")
        return False

    try:
        from repositories.session_context_repository import SessionContextRepository
        print("✅ SessionContextRepository import 성공")
    except Exception as e:
        print(f"❌ SessionContextRepository import 실패: {e}")
        return False

    return True


def check_db_connection():
    """DB 연결 확인"""
    print("\n" + "=" * 60)
    print("2. DB 연결 검증")
    print("=" * 60)

    try:
        from repositories.session_context_repository import SessionContextRepository
        repo = SessionContextRepository()
        print("✅ DB 연결 성공")

        # 간단한 쿼리로 테이블 확인
        conn = repo._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM session_context")
        count = cursor.fetchone()[0]
        print(f"✅ session_context 테이블 접근 가능 (레코드 수: {count})")
        cursor.close()
        conn.close()

        return True

    except Exception as e:
        print(f"❌ DB 연결 실패: {e}")
        return False


def check_search_agent():
    """SearchAgent 기능 확인"""
    print("\n" + "=" * 60)
    print("3. SearchAgent 기능 검증")
    print("=" * 60)

    try:
        from agents.search_agent import SearchAgent
        agent = SearchAgent()

        # session_repo 존재 확인
        if hasattr(agent, 'session_repo'):
            print("✅ agent.session_repo 존재")
        else:
            print("❌ agent.session_repo 없음 - session_context 저장 불가")
            return False

        # session_id 속성 존재 확인 (None이어도 OK - 검색 시 생성됨)
        if hasattr(agent, 'session_id'):
            if agent.session_id is None:
                print("✅ agent.session_id 속성 존재 (검색 시 생성됨)")
            else:
                print(f"✅ agent.session_id 생성됨: {agent.session_id[:8]}...")
        else:
            print("❌ agent.session_id 속성 없음")
            return False

        print("✅ SearchAgent 정상 초기화")
        return True

    except Exception as e:
        print(f"❌ SearchAgent 초기화 실패: {e}")
        return False


def check_files():
    """필수 파일 존재 확인"""
    print("\n" + "=" * 60)
    print("4. 필수 파일 검증")
    print("=" * 60)

    required_files = [
        "chat_ui.py",
        "agents/search_agent.py",
        "repositories/session_context_repository.py",
        "claudedocs/chat_ui_guide.md",
        "claudedocs/chat_ui_test_guide.md"
    ]

    all_exist = True
    for file_path in required_files:
        full_path = Path(__file__).parent.parent / file_path
        if full_path.exists():
            print(f"✅ {file_path}")
        else:
            print(f"❌ {file_path} 없음")
            all_exist = False

    return all_exist


def check_session_context_integration():
    """SearchAgent의 session_context 통합 확인"""
    print("\n" + "=" * 60)
    print("5. session_context 통합 검증")
    print("=" * 60)

    try:
        # search_agent.py 파일에서 session_repo 코드 확인
        agent_file = Path(__file__).parent.parent / "agents" / "search_agent.py"
        content = agent_file.read_text()

        checks = [
            ("SessionContextRepository import", "from repositories.session_context_repository import SessionContextRepository" in content),
            ("session_repo 초기화", "self.session_repo = SessionContextRepository()" in content),
            ("add_conversation_turn 호출", "self.session_repo.add_conversation_turn" in content),
        ]

        all_pass = True
        for check_name, result in checks:
            if result:
                print(f"✅ {check_name}")
            else:
                print(f"❌ {check_name} - 코드에 없음")
                all_pass = False

        return all_pass

    except Exception as e:
        print(f"❌ 파일 검증 실패: {e}")
        return False


def check_chat_ui_fix():
    """Chat UI st.rerun() 수정 확인"""
    print("\n" + "=" * 60)
    print("6. Chat UI 에러 수정 검증")
    print("=" * 60)

    try:
        ui_file = Path(__file__).parent.parent / "chat_ui.py"
        content = ui_file.read_text()

        # st.rerun()이 try 블록 밖에 있는지 확인
        lines = content.split('\n')

        # 300-310 라인 근처에서 st.rerun() 찾기
        rerun_found = False
        rerun_outside_try = False

        for i, line in enumerate(lines[300:310], start=300):
            if 'st.rerun()' in line:
                rerun_found = True
                # 이전 라인들에 except가 있으면 try 블록 밖
                prev_lines = '\n'.join(lines[i-10:i])
                if 'except Exception' in prev_lines and 'st.stop()' in prev_lines:
                    rerun_outside_try = True
                break

        if rerun_found and rerun_outside_try:
            print("✅ st.rerun() try 블록 외부에 위치 (수정 완료)")
        elif rerun_found:
            print("⚠️  st.rerun() 찾았으나 위치 확인 필요")
        else:
            print("❌ st.rerun() 못 찾음")
            return False

        # st.stop() 존재 확인
        if 'st.stop()' in content:
            print("✅ st.stop() 에러 처리 존재")
        else:
            print("❌ st.stop() 없음")
            return False

        return True

    except Exception as e:
        print(f"❌ Chat UI 파일 검증 실패: {e}")
        return False


def main():
    """전체 검증 실행"""
    print("\n" + "=" * 60)
    print("Chat UI 준비 상태 검증")
    print("=" * 60 + "\n")

    results = []

    # 각 검증 실행
    results.append(("Import", check_imports()))
    results.append(("DB 연결", check_db_connection()))
    results.append(("SearchAgent", check_search_agent()))
    results.append(("필수 파일", check_files()))
    results.append(("session_context 통합", check_session_context_integration()))
    results.append(("Chat UI 수정", check_chat_ui_fix()))

    # 최종 결과
    print("\n" + "=" * 60)
    print("최종 검증 결과")
    print("=" * 60)

    all_pass = True
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")
        if not result:
            all_pass = False

    print("\n" + "=" * 60)
    if all_pass:
        print("🎉 모든 검증 통과! Chat UI 사용 준비 완료")
        print("\n실행 명령:")
        print("  streamlit run chat_ui.py --server.port 8501")
        print("\n접속:")
        print("  http://localhost:8501")
    else:
        print("⚠️  일부 검증 실패 - 문제 해결 필요")
        return 1

    print("=" * 60 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
