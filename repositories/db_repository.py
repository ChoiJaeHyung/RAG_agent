"""
MariaDB Repository for RAG Agent.
Provides read-only access to the existing system's database.
Uses DBUtils connection pooling for efficiency.
"""

from typing import List, Dict, Optional
from dbutils.pooled_db import PooledDB
import pymysql
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from utils.logger import logger


class DatabaseRepository:
    """Repository for MariaDB operations with connection pooling."""

    def __init__(self):
        """Initialize database connection pool."""
        self.pool = PooledDB(
            creator=pymysql,
            maxconnections=30,
            mincached=5,
            maxcached=20,
            blocking=True,
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            database=settings.DB_NAME,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        logger.info(f"✓ DB Pool initialized: {settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4))
    def _execute_query(self, sql: str, params: tuple = None) -> List[Dict]:
        """
        Execute SQL query with retry logic.

        Args:
            sql: SQL query string
            params: Query parameters (tuple)

        Returns:
            List of result dictionaries

        Raises:
            Exception: If query fails after retries
        """
        conn = self.pool.connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params or ())
            results = cursor.fetchall()
            logger.debug(f"Query executed: {sql[:100]}... | Results: {len(results)}")
            return results
        except Exception as e:
            logger.error(f"Query failed: {sql[:100]}... | Error: {e}")
            raise
        finally:
            conn.close()

    def search_by_error_code(self, error_code: str) -> List[Dict]:
        """
        Search documents by error code pattern in sentence text.

        Note: error_code column doesn't exist, searching in sentence text instead.

        Args:
            error_code: Error code string (e.g., "50001")

        Returns:
            List of matching documents
        """
        # Search for error code pattern in sentence text
        sql = """
            SELECT * FROM sentences
            WHERE sentence LIKE %s
            LIMIT 100
        """
        try:
            pattern = f"%{error_code}%"
            results = self._execute_query(sql, (pattern,))
            logger.info(f"🔍 Error code search: {error_code} → {len(results)} documents")
            return results
        except Exception as e:
            logger.error(f"Error code search failed: {e}")
            return []

    def search_by_keyword(self, keyword: str, brand: Optional[str] = None) -> List[Dict]:
        """
        Search documents by keyword with optional brand filter.

        Note: brand column doesn't exist in sentences table.
        Brand filtering will be done by matching brand name in sentence text.

        Args:
            keyword: Search keyword
            brand: Optional brand filter (e.g., "rvs", "rcmp")

        Returns:
            List of matching documents
        """
        if brand:
            # Filter by both keyword and brand name in sentence text
            sql = """
                SELECT * FROM sentences
                WHERE sentence LIKE %s
                AND sentence LIKE %s
                LIMIT 100
            """
            keyword_pattern = f"%{keyword}%"
            brand_pattern = f"%{brand}%"
            params = (keyword_pattern, brand_pattern)
        else:
            sql = """
                SELECT * FROM sentences
                WHERE sentence LIKE %s
                LIMIT 100
            """
            keyword_pattern = f"%{keyword}%"
            params = (keyword_pattern,)

        results = self._execute_query(sql, params)
        logger.info(f"🔍 Keyword search: '{keyword}' (brand={brand}) → {len(results)} documents")
        return results

    def get_document_by_id(self, doc_id: int) -> Optional[Dict]:
        """
        Get document by ID.

        Args:
            doc_id: Document ID (sentences table primary key is sentence_id)

        Returns:
            Document dict or None if not found
        """
        sql = "SELECT * FROM sentences WHERE sentence_id = %s"
        results = self._execute_query(sql, (doc_id,))
        if results:
            logger.debug(f"🔍 Document by ID: {doc_id} → Found")
            return results[0]
        logger.debug(f"🔍 Document by ID: {doc_id} → Not found")
        return None

    def search_recent_logs(self, query: str, limit: int = 5) -> List[Dict]:
        """
        Search recent Q&A logs.

        Args:
            query: Search query
            limit: Maximum number of results

        Returns:
            List of past Q&A entries
        """
        sql = """
            SELECT * FROM qa_logs
            WHERE user_question LIKE %s
            ORDER BY created_at DESC
            LIMIT %s
        """
        pattern = f"%{query}%"
        results = self._execute_query(sql, (pattern, limit))
        logger.info(f"🔍 Log search: '{query}' → {len(results)} past Q&As")
        return results

    def search_redmine_tables(self, keyword: str) -> List[Dict]:
        """
        Search redmine-specific tables for keyword.

        Searches across 4 redmine tables:
        - redmine_issues
        - redmine_journals
        - redmine_relations
        - redmine_sync_log

        Args:
            keyword: Search keyword

        Returns:
            List of matching documents from all redmine tables
        """
        # Query each table separately due to different column structures
        results = []
        pattern = f"%{keyword}%"

        try:
            # Search redmine_issues
            sql_issues = """
                SELECT 'redmine_issues' as source_table, issue_id, subject, description
                FROM redmine_issues
                WHERE subject LIKE %s OR description LIKE %s
                LIMIT 25
            """
            issues = self._execute_query(sql_issues, (pattern, pattern))
            results.extend(issues)

            # Search redmine_journals (if exists)
            try:
                sql_journals = """
                    SELECT 'redmine_journals' as source_table, journal_id, notes
                    FROM redmine_journals
                    WHERE notes LIKE %s
                    LIMIT 25
                """
                journals = self._execute_query(sql_journals, (pattern,))
                results.extend(journals)
            except Exception:
                pass  # Skip if table doesn't exist

            # Search redmine_relations (if exists)
            try:
                sql_relations = """
                    SELECT 'redmine_relations' as source_table, relation_id, issue_from, issue_to
                    FROM redmine_relations
                    WHERE CAST(issue_from AS CHAR) LIKE %s OR CAST(issue_to AS CHAR) LIKE %s
                    LIMIT 25
                """
                relations = self._execute_query(sql_relations, (pattern, pattern))
                results.extend(relations)
            except Exception:
                pass  # Skip if table doesn't exist

            # Search redmine_sync_log (if exists)
            try:
                sql_sync = """
                    SELECT 'redmine_sync_log' as source_table, sync_id, status, error_message
                    FROM redmine_sync_log
                    WHERE status LIKE %s OR error_message LIKE %s
                    LIMIT 25
                """
                sync = self._execute_query(sql_sync, (pattern, pattern))
                results.extend(sync)
            except Exception:
                pass  # Skip if table doesn't exist

            logger.info(f"🔍 Redmine search: '{keyword}' → {len(results)} documents")
            return results
        except Exception as e:
            logger.error(f"Redmine search failed: {e}")
            return []

    def is_connected(self) -> bool:
        """
        Check if database connection is alive.

        Returns:
            True if connected, False otherwise
        """
        try:
            self._execute_query("SELECT 1")
            return True
        except Exception:
            return False

    def get_statistics(self) -> Dict:
        """
        Get database statistics.

        Returns:
            Dictionary with table counts
        """
        try:
            sentences_count = self._execute_query("SELECT COUNT(*) as count FROM sentences")[0]['count']
            logs_count = self._execute_query("SELECT COUNT(*) as count FROM qa_logs")[0]['count']
            return {
                "sentences": sentences_count,
                "logs": logs_count,
                "status": "connected"
            }
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {"status": "error", "error": str(e)}
