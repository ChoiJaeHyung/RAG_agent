"""
Tool Performance Tracking Repository.
학습 및 데이터 기반 도구 선택을 위한 성능 추적.
"""

from typing import Dict, List, Optional, Tuple
import mysql.connector
from mysql.connector import Error
from datetime import datetime, timedelta
import json
from utils.logger import logger
from config.settings import settings


class ToolPerformanceRepository:
    """도구 성능 추적 및 학습을 위한 Repository."""

    def __init__(self):
        """
        Tool Performance Repository 초기화.
        r_agent_db에 연결합니다.
        """
        self.db_config = {
            'host': settings.LEARNING_DB_HOST,
            'port': settings.LEARNING_DB_PORT,
            'user': settings.LEARNING_DB_USER,
            'password': settings.LEARNING_DB_PASSWORD,
            'database': settings.LEARNING_DB_NAME,
            'charset': 'utf8mb4',
            'collation': 'utf8mb4_unicode_ci'
        }

    def _get_connection(self):
        """데이터베이스 연결 가져오기."""
        try:
            return mysql.connector.connect(**self.db_config)
        except Error as e:
            logger.error(f"❌ Learning DB 연결 실패: {e}")
            raise

    def log_tool_execution(
        self,
        session_id: str,
        question: str,
        question_type: str,
        tool_name: str,
        execution_order: int,
        is_fallback: bool,
        doc_count: int,
        avg_score: float,
        execution_time: float,
        success: bool,
        error_message: Optional[str] = None,
        error_type: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> int:
        """
        도구 실행 이벤트 로깅.

        Args:
            session_id: 세션 식별자
            question: 사용자 질문
            question_type: 질문 유형 (list, qa, error_code, how_to, keyword, concept)
            tool_name: 실행된 도구 이름
            execution_order: 실행 순서 (1=primary, 2+=fallback)
            is_fallback: 폴백 실행 여부
            doc_count: 반환된 문서 수
            avg_score: 평균 관련성 점수
            execution_time: 실행 시간 (초)
            success: 성공 여부
            error_message: 에러 메시지
            error_type: 에러 유형
            user_id: 사용자 식별자

        Returns:
            로그 항목 ID
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            query = """
                INSERT INTO tool_performance_log (
                    session_id, user_id, question, question_type,
                    tool_name, execution_order, is_fallback,
                    doc_count, avg_score, execution_time, success,
                    error_message, error_type
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """

            cursor.execute(query, (
                session_id, user_id, question, question_type,
                tool_name, execution_order, is_fallback,
                doc_count, avg_score, execution_time, success,
                error_message, error_type
            ))

            conn.commit()
            log_id = cursor.lastrowid

            cursor.close()
            conn.close()

            logger.debug(f"📊 도구 실행 로깅: {tool_name} (id={log_id}, success={success})")
            return log_id

        except Error as e:
            logger.error(f"❌ 도구 실행 로깅 실패: {e}")
            return -1

    def update_aggregated_stats(self, days_back: int = 30) -> None:
        """
        모든 도구에 대한 집계 통계 업데이트.

        Args:
            days_back: 통계 집계 기간 (일)
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 날짜 임계값 계산
            threshold_date = datetime.now() - timedelta(days=days_back)

            # 집계 쿼리
            query = """
                INSERT INTO tool_performance_stats (
                    tool_name, question_type,
                    total_executions, successful_executions, failed_executions,
                    success_rate, avg_doc_count, avg_execution_time
                )
                SELECT
                    tool_name,
                    question_type,
                    COUNT(*) as total_executions,
                    SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) as successful_executions,
                    SUM(CASE WHEN success = FALSE THEN 1 ELSE 0 END) as failed_executions,
                    AVG(CASE WHEN success = TRUE THEN 1.0 ELSE 0.0 END) as success_rate,
                    AVG(doc_count) as avg_doc_count,
                    AVG(execution_time) as avg_execution_time
                FROM tool_performance_log
                WHERE created_at >= %s
                GROUP BY tool_name, question_type
                ON DUPLICATE KEY UPDATE
                    total_executions = VALUES(total_executions),
                    successful_executions = VALUES(successful_executions),
                    failed_executions = VALUES(failed_executions),
                    success_rate = VALUES(success_rate),
                    avg_doc_count = VALUES(avg_doc_count),
                    avg_execution_time = VALUES(avg_execution_time),
                    updated_at = CURRENT_TIMESTAMP
            """

            cursor.execute(query, (threshold_date,))
            conn.commit()

            logger.info(f"✅ 집계 통계 업데이트 완료 (최근 {days_back}일)")

            cursor.close()
            conn.close()

        except Error as e:
            logger.error(f"❌ 집계 통계 업데이트 실패: {e}")

    def get_best_tool_for_question_type(
        self,
        question_type: str,
        min_executions: int = 10
    ) -> Optional[Tuple[str, float]]:
        """
        질문 유형에 가장 적합한 도구 찾기.

        Args:
            question_type: 질문 유형
            min_executions: 최소 실행 횟수 (신뢰도 확보)

        Returns:
            (도구명, 성공률) 튜플 또는 None
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)

            query = """
                SELECT tool_name, success_rate, total_executions
                FROM tool_performance_stats
                WHERE question_type = %s
                  AND total_executions >= %s
                ORDER BY success_rate DESC, avg_execution_time ASC
                LIMIT 1
            """

            cursor.execute(query, (question_type, min_executions))
            result = cursor.fetchone()

            cursor.close()
            conn.close()

            if result:
                logger.info(
                    f"🎯 '{question_type}' 최적 도구: {result['tool_name']} "
                    f"(성공률 {result['success_rate']:.2%}, 실행 {result['total_executions']}회)"
                )
                return (result['tool_name'], result['success_rate'])

            logger.debug(f"⚠️ '{question_type}' 유형에 대한 통계 부족 (최소 {min_executions}회 필요)")
            return None

        except Error as e:
            logger.error(f"❌ 최적 도구 조회 실패: {e}")
            return None

    def get_tool_fallback_chain(
        self,
        question_type: str,
        max_tools: int = 3
    ) -> List[str]:
        """
        질문 유형에 대한 추천 폴백 체인 가져오기.

        Args:
            question_type: 질문 유형
            max_tools: 체인에 포함할 최대 도구 수

        Returns:
            추천 순서대로 정렬된 도구명 리스트
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)

            query = """
                SELECT tool_name, success_rate, total_executions
                FROM tool_performance_stats
                WHERE question_type = %s
                  AND total_executions >= 5
                ORDER BY success_rate DESC, avg_execution_time ASC
                LIMIT %s
            """

            cursor.execute(query, (question_type, max_tools))
            results = cursor.fetchall()

            cursor.close()
            conn.close()

            chain = [r['tool_name'] for r in results]
            if chain:
                logger.info(f"🔗 '{question_type}' 폴백 체인: {' → '.join(chain)}")
            else:
                logger.debug(f"⚠️ '{question_type}' 유형에 대한 폴백 체인 데이터 부족")

            return chain

        except Error as e:
            logger.error(f"❌ 폴백 체인 조회 실패: {e}")
            return []

    def get_tool_performance_summary(self) -> Dict:
        """
        전체 도구 성능 요약 가져오기.

        Returns:
            모든 도구에 대한 요약 통계
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)

            query = """
                SELECT
                    tool_name,
                    SUM(total_executions) as total_uses,
                    AVG(success_rate) as avg_success_rate,
                    AVG(avg_execution_time) as avg_time
                FROM tool_performance_stats
                GROUP BY tool_name
                ORDER BY total_uses DESC
            """

            cursor.execute(query)
            results = cursor.fetchall()

            cursor.close()
            conn.close()

            summary = {
                'tools': results,
                'total_tools': len(results),
                'timestamp': datetime.now().isoformat()
            }

            logger.info(f"📊 성능 요약: {len(results)}개 도구")
            return summary

        except Error as e:
            logger.error(f"❌ 성능 요약 조회 실패: {e}")
            return {'tools': [], 'total_tools': 0}

    def learn_pattern(
        self,
        pattern_name: str,
        question_pattern: str,
        question_type: str,
        primary_tool: str,
        fallback_tools: List[str],
        confidence_score: float = 0.5
    ) -> int:
        """
        학습된 도구 선택 패턴 저장.

        Args:
            pattern_name: 패턴 이름
            question_pattern: 질문 매칭 패턴 (키워드 또는 정규식)
            question_type: 질문 유형
            primary_tool: 1차 추천 도구
            fallback_tools: 폴백 도구 리스트
            confidence_score: 패턴 신뢰도 (0-1)

        Returns:
            패턴 ID
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            fallback_json = json.dumps(fallback_tools, ensure_ascii=False)

            query = """
                INSERT INTO tool_selection_patterns (
                    pattern_name, question_pattern, question_type,
                    primary_tool, fallback_tools, confidence_score
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    primary_tool = VALUES(primary_tool),
                    fallback_tools = VALUES(fallback_tools),
                    confidence_score = VALUES(confidence_score)
            """

            cursor.execute(query, (
                pattern_name, question_pattern, question_type,
                primary_tool, fallback_json, confidence_score
            ))

            conn.commit()
            pattern_id = cursor.lastrowid

            cursor.close()
            conn.close()

            logger.info(f"💡 패턴 학습: {pattern_name} → {primary_tool} (id={pattern_id})")
            return pattern_id

        except Error as e:
            logger.error(f"❌ 패턴 학습 실패: {e}")
            return -1

    def get_performance_trends(
        self,
        tool_name: str,
        days: int = 7
    ) -> List[Dict]:
        """
        도구의 시간 경과에 따른 성능 추이 가져오기.

        Args:
            tool_name: 도구명
            days: 분석 기간 (일)

        Returns:
            일별 성능 지표 리스트
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)

            threshold_date = datetime.now() - timedelta(days=days)

            query = """
                SELECT
                    DATE(created_at) as date,
                    COUNT(*) as executions,
                    AVG(CASE WHEN success = TRUE THEN 1.0 ELSE 0.0 END) as success_rate,
                    AVG(doc_count) as avg_docs,
                    AVG(execution_time) as avg_time
                FROM tool_performance_log
                WHERE tool_name = %s
                  AND created_at >= %s
                GROUP BY DATE(created_at)
                ORDER BY date DESC
            """

            cursor.execute(query, (tool_name, threshold_date))
            results = cursor.fetchall()

            cursor.close()
            conn.close()

            logger.info(f"📈 '{tool_name}' 추이: 최근 {days}일간 {len(results)}개 데이터 포인트")
            return results

        except Error as e:
            logger.error(f"❌ 성능 추이 조회 실패: {e}")
            return []

    def health_check(self) -> bool:
        """
        Learning DB 연결 상태 확인.

        Returns:
            연결 성공 여부
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            conn.close()
            logger.info("✅ Learning DB 연결 정상")
            return True
        except Error as e:
            logger.error(f"❌ Learning DB 연결 실패: {e}")
            return False
