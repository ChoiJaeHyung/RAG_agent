#!/usr/bin/env python3
"""
검색 사용 횟수 확인 스크립트
1,000회 도달 시 use_learning 활성화 권장
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from repositories.tool_performance_repository import ToolPerformanceRepository
from datetime import datetime, timedelta


def check_usage_count():
    """사용 횟수 확인 및 활성화 권장"""
    print("\n" + "=" * 80)
    print("  🔍 R-Agent 사용 횟수 확인")
    print("=" * 80)

    repo = ToolPerformanceRepository()

    try:
        conn = repo._get_connection()
        cursor = conn.cursor(dictionary=True)

        # 전체 세션 수 (검색 횟수)
        cursor.execute("""
            SELECT COUNT(DISTINCT session_id) as total_sessions
            FROM tool_performance_log
        """)
        result = cursor.fetchone()
        total_sessions = result['total_sessions'] if result else 0

        # 오늘 세션 수
        cursor.execute("""
            SELECT COUNT(DISTINCT session_id) as today_sessions
            FROM tool_performance_log
            WHERE DATE(created_at) = CURDATE()
        """)
        result = cursor.fetchone()
        today_sessions = result['today_sessions'] if result else 0

        # 이번 주 세션 수
        cursor.execute("""
            SELECT COUNT(DISTINCT session_id) as week_sessions
            FROM tool_performance_log
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        """)
        result = cursor.fetchone()
        week_sessions = result['week_sessions'] if result else 0

        # 일일 평균 (최근 7일)
        cursor.execute("""
            SELECT
                DATE(created_at) as date,
                COUNT(DISTINCT session_id) as sessions
            FROM tool_performance_log
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            GROUP BY DATE(created_at)
            ORDER BY date DESC
        """)
        daily_stats = cursor.fetchall()

        print(f"\n📊 사용 통계:")
        print(f"  - 전체 검색 횟수: {total_sessions:,}회")
        print(f"  - 오늘 검색 횟수: {today_sessions:,}회")
        print(f"  - 이번 주 검색 횟수: {week_sessions:,}회")

        if daily_stats:
            avg_daily = sum(s['sessions'] for s in daily_stats) / len(daily_stats)
            print(f"  - 일일 평균 (최근 7일): {avg_daily:.1f}회")

            # 1,000회 도달 예상일 계산
            if avg_daily > 0:
                remaining = max(0, 1000 - total_sessions)
                days_to_target = remaining / avg_daily
                target_date = datetime.now() + timedelta(days=days_to_target)

                print(f"\n🎯 1,000회 달성 예상:")
                print(f"  - 남은 검색 횟수: {remaining:,}회")
                print(f"  - 예상 소요 일수: {days_to_target:.1f}일")
                print(f"  - 예상 달성일: {target_date.strftime('%Y-%m-%d')}")

        print(f"\n📅 최근 7일 일별 통계:")
        for stat in daily_stats:
            date_str = stat['date'].strftime('%Y-%m-%d')
            sessions = stat['sessions']
            bar = "█" * min(50, sessions)
            print(f"  {date_str}: {sessions:3d}회 {bar}")

        # 활성화 권장
        print(f"\n" + "=" * 80)
        if total_sessions >= 1000:
            print("  ✅ 1,000회 달성! use_learning 활성화 권장")
            print("")
            print("  다음 명령으로 활성화:")
            print("  1. agents/search_agent.py 편집")
            print("  2. self.use_learning = False → True 변경")
            print("  3. 서버 재시작")
        elif total_sessions >= 500:
            progress = (total_sessions / 1000) * 100
            print(f"  🔄 진행 중: {progress:.1f}% ({total_sessions:,}/1,000회)")
            print(f"  - 곧 활성화 가능합니다!")
        else:
            progress = (total_sessions / 1000) * 100
            print(f"  ⏳ 데이터 수집 중: {progress:.1f}% ({total_sessions:,}/1,000회)")
            print(f"  - use_learning은 비활성화 상태 유지")

        print("=" * 80)

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        return


if __name__ == "__main__":
    check_usage_count()
