"""
Session Context Repository - 대화 히스토리 및 답변 저장
"""

import json
from typing import Optional, List, Dict, Any
import mysql.connector
from mysql.connector import pooling
from config.settings import settings
from utils.logger import setup_logger

logger = setup_logger("session_context")


class SessionContextRepository:
    """세션 컨텍스트 관리 Repository"""

    def __init__(self):
        """Initialize repository with connection pool"""
        self.pool = mysql.connector.pooling.MySQLConnectionPool(
            pool_name="session_context_pool",
            pool_size=5,
            host=settings.LEARNING_DB_HOST,
            user=settings.LEARNING_DB_USER,
            password=settings.LEARNING_DB_PASSWORD,
            database=settings.LEARNING_DB_NAME,
            port=settings.LEARNING_DB_PORT,
            charset='utf8mb4',
            collation='utf8mb4_unicode_ci'
        )
        logger.info("✓ SessionContextRepository initialized")

    def _get_connection(self):
        """Get connection from pool"""
        return self.pool.get_connection()

    def create_session(
        self,
        session_id: str,
        user_id: Optional[str] = None
    ) -> bool:
        """
        새 세션 생성

        Args:
            session_id: 세션 식별자
            user_id: 사용자 식별자 (선택)

        Returns:
            성공 여부
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO session_context (
                    session_id,
                    user_id,
                    conversation_history,
                    total_questions,
                    successful_answers
                ) VALUES (
                    %s, %s, %s, 0, 0
                )
                ON DUPLICATE KEY UPDATE
                    last_activity = CURRENT_TIMESTAMP
            """, (
                session_id,
                user_id,
                json.dumps([])  # 빈 대화 히스토리
            ))

            conn.commit()
            cursor.close()
            conn.close()

            logger.info(f"✓ Session created: {session_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            return False

    def add_conversation_turn(
        self,
        session_id: str,
        question: str,
        answer: str,
        sources: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        대화 턴 추가 (질문 + 답변 쌍)

        Args:
            session_id: 세션 식별자
            question: 사용자 질문
            answer: 시스템 답변
            sources: 답변 출처 문서 (선택)
            metadata: 추가 메타데이터 (선택)

        Returns:
            성공 여부
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)

            # 기존 히스토리 조회
            cursor.execute("""
                SELECT conversation_history, total_questions, successful_answers
                FROM session_context
                WHERE session_id = %s
            """, (session_id,))

            row = cursor.fetchone()

            if not row:
                # 세션 없으면 생성
                self.create_session(session_id)
                conversation_history = []
                total_questions = 0
                successful_answers = 0
            else:
                history_str = row['conversation_history']
                conversation_history = json.loads(history_str) if history_str else []
                total_questions = row['total_questions']
                successful_answers = row['successful_answers']

            # 새 턴 추가
            from datetime import datetime
            new_turn = {
                'question': question,
                'answer': answer,
                'timestamp': datetime.now().isoformat(),
                'sources_count': len(sources) if sources else 0,
            }

            if sources:
                new_turn['sources'] = [
                    {
                        'file_name': s.get('metadata', {}).get('file_name', 'Unknown'),
                        'score': s.get('score', 0)
                    }
                    for s in sources[:5]  # 상위 5개만
                ]

            if metadata:
                new_turn['metadata'] = metadata

            conversation_history.append(new_turn)

            # 최근 50개만 유지 (메모리 관리)
            if len(conversation_history) > 50:
                conversation_history = conversation_history[-50:]

            # 업데이트
            cursor.execute("""
                UPDATE session_context
                SET
                    conversation_history = %s,
                    total_questions = %s,
                    successful_answers = %s,
                    last_activity = CURRENT_TIMESTAMP
                WHERE session_id = %s
            """, (
                json.dumps(conversation_history, ensure_ascii=False),
                total_questions + 1,
                successful_answers + 1,
                session_id
            ))

            conn.commit()
            cursor.close()
            conn.close()

            logger.info(f"✓ Conversation turn added: {session_id} (total: {total_questions + 1})")
            return True

        except Exception as e:
            logger.error(f"Failed to add conversation turn: {e}")
            return False

    def get_conversation_history(
        self,
        session_id: str,
        limit: int = 10
    ) -> List[Dict]:
        """
        대화 히스토리 조회

        Args:
            session_id: 세션 식별자
            limit: 반환할 최근 대화 수

        Returns:
            대화 히스토리 리스트
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)

            cursor.execute("""
                SELECT conversation_history
                FROM session_context
                WHERE session_id = %s
            """, (session_id,))

            row = cursor.fetchone()
            cursor.close()
            conn.close()

            if not row:
                return []

            history_str = row['conversation_history']
            history = json.loads(history_str) if history_str else []

            # 최근 limit개만 반환
            return history[-limit:]

        except Exception as e:
            logger.error(f"Failed to get conversation history: {e}")
            return []

    def get_session_stats(self, session_id: str) -> Optional[Dict]:
        """
        세션 통계 조회

        Args:
            session_id: 세션 식별자

        Returns:
            세션 통계 딕셔너리
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)

            cursor.execute("""
                SELECT
                    session_id,
                    user_id,
                    total_questions,
                    successful_answers,
                    avg_satisfaction,
                    started_at,
                    last_activity
                FROM session_context
                WHERE session_id = %s
            """, (session_id,))

            row = cursor.fetchone()
            cursor.close()
            conn.close()

            return row

        except Exception as e:
            logger.error(f"Failed to get session stats: {e}")
            return None

    def delete_old_sessions(self, days: int = 365) -> int:
        """
        오래된 세션 삭제

        Args:
            days: 삭제할 기준 일수 (기본 365일 = 1년)

        Returns:
            삭제된 세션 수
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                DELETE FROM session_context
                WHERE last_activity < DATE_SUB(NOW(), INTERVAL %s DAY)
            """, (days,))

            deleted = cursor.rowcount
            conn.commit()
            cursor.close()
            conn.close()

            logger.info(f"✓ Deleted {deleted} old sessions (>{days} days)")
            return deleted

        except Exception as e:
            logger.error(f"Failed to delete old sessions: {e}")
            return 0

    def update_satisfaction(
        self,
        session_id: str,
        satisfaction: int,
        is_relevant: bool,
        comment: Optional[str] = None
    ) -> bool:
        """
        대화 만족도 업데이트

        Args:
            session_id: 세션 식별자
            satisfaction: 만족도 (1-5)
            is_relevant: 답변이 질문에 맞는가
            comment: 선택적 코멘트

        Returns:
            성공 여부
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)

            # 현재 평균 만족도 조회
            cursor.execute("""
                SELECT avg_satisfaction, total_questions, conversation_history
                FROM session_context
                WHERE session_id = %s
            """, (session_id,))

            row = cursor.fetchone()

            if not row:
                logger.warning(f"Session not found: {session_id}")
                cursor.close()
                conn.close()
                return False

            current_avg = row['avg_satisfaction'] or 0
            total_q = row['total_questions'] or 1
            history_str = row['conversation_history']

            # 새로운 평균 계산 (누적 평균)
            if current_avg == 0:
                new_avg = satisfaction
            else:
                new_avg = ((current_avg * (total_q - 1)) + satisfaction) / total_q

            # conversation_history JSON에 피드백 추가
            history = json.loads(history_str) if history_str else []

            if history:
                from datetime import datetime
                # 마지막 턴에 피드백 추가
                history[-1]['feedback'] = {
                    'satisfaction': satisfaction,
                    'is_relevant': is_relevant,
                    'comment': comment,
                    'timestamp': datetime.now().isoformat()
                }

            # 업데이트
            cursor.execute("""
                UPDATE session_context
                SET
                    avg_satisfaction = %s,
                    conversation_history = %s,
                    last_activity = CURRENT_TIMESTAMP
                WHERE session_id = %s
            """, (
                new_avg,
                json.dumps(history, ensure_ascii=False),
                session_id
            ))

            conn.commit()
            cursor.close()
            conn.close()

            logger.info(f"✓ Satisfaction updated: {session_id} (score: {satisfaction}/5, avg: {new_avg:.2f})")
            return True

        except Exception as e:
            logger.error(f"Failed to update satisfaction: {e}")
            return False
