"""
Async MariaDB Repository for RAG Agent.
Provides async read-only access to the existing system's database.
Uses aiomysql for async database operations.
"""

import asyncio
from typing import List, Dict, Optional
from contextlib import asynccontextmanager
import aiomysql

from config.settings import settings
from utils.logger import logger


class AsyncDatabaseRepository:
    """Async repository for MariaDB operations with connection pooling."""

    def __init__(self):
        """Initialize (pool created lazily on first use)."""
        self._pool: Optional[aiomysql.Pool] = None
        self._pool_lock = asyncio.Lock()
        logger.info(f"AsyncDatabaseRepository initialized (pool pending)")

    async def _get_pool(self) -> aiomysql.Pool:
        """Get or create connection pool (lazy initialization)."""
        if self._pool is None:
            async with self._pool_lock:
                if self._pool is None:
                    self._pool = await aiomysql.create_pool(
                        host=settings.DB_HOST,
                        port=settings.DB_PORT,
                        user=settings.DB_USER,
                        password=settings.DB_PASSWORD,
                        db=settings.DB_NAME,
                        charset='utf8mb4',
                        minsize=5,
                        maxsize=30,
                        autocommit=True,
                        cursorclass=aiomysql.DictCursor
                    )
                    logger.info(f"✓ Async DB Pool initialized: {settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")
        return self._pool

    @asynccontextmanager
    async def _get_connection(self):
        """Get connection from pool with context manager."""
        pool = await self._get_pool()
        conn = await pool.acquire()
        try:
            yield conn
        finally:
            pool.release(conn)

    async def _execute_query(self, sql: str, params: tuple = None, retry_count: int = 3) -> List[Dict]:
        """
        Execute SQL query with retry logic.

        Args:
            sql: SQL query string
            params: Query parameters (tuple)
            retry_count: Number of retries

        Returns:
            List of result dictionaries
        """
        last_error = None
        for attempt in range(retry_count):
            try:
                async with self._get_connection() as conn:
                    async with conn.cursor() as cursor:
                        await cursor.execute(sql, params or ())
                        results = await cursor.fetchall()
                        logger.debug(f"Query executed: {sql[:100]}... | Results: {len(results)}")
                        return results
            except Exception as e:
                last_error = e
                logger.warning(f"Query attempt {attempt + 1} failed: {e}")
                if attempt < retry_count - 1:
                    await asyncio.sleep(1 * (attempt + 1))  # Exponential backoff

        logger.error(f"Query failed after {retry_count} attempts: {sql[:100]}... | Error: {last_error}")
        raise last_error

    async def search_by_error_code(self, error_code: str) -> List[Dict]:
        """Search documents by error code pattern in sentence text."""
        sql = """
            SELECT * FROM sentences
            WHERE sentence LIKE %s
            LIMIT 100
        """
        try:
            pattern = f"%{error_code}%"
            results = await self._execute_query(sql, (pattern,))
            logger.info(f"🔍 Async Error code search: {error_code} → {len(results)} documents")
            return results
        except Exception as e:
            logger.error(f"Error code search failed: {e}")
            return []

    async def search_by_keyword(self, keyword: str, brand: Optional[str] = None) -> List[Dict]:
        """Search documents by keyword with optional brand filter."""
        if brand:
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

        results = await self._execute_query(sql, params)
        logger.info(f"🔍 Async Keyword search: '{keyword}' (brand={brand}) → {len(results)} documents")
        return results

    async def get_document_by_id(self, doc_id: int) -> Optional[Dict]:
        """Get document by ID."""
        sql = "SELECT * FROM sentences WHERE sentence_id = %s"
        results = await self._execute_query(sql, (doc_id,))
        if results:
            logger.debug(f"🔍 Document by ID: {doc_id} → Found")
            return results[0]
        logger.debug(f"🔍 Document by ID: {doc_id} → Not found")
        return None

    async def search_recent_logs(self, query: str, limit: int = 5) -> List[Dict]:
        """Search recent Q&A logs."""
        sql = """
            SELECT * FROM qa_logs
            WHERE user_question LIKE %s
            ORDER BY created_at DESC
            LIMIT %s
        """
        pattern = f"%{query}%"
        results = await self._execute_query(sql, (pattern, limit))
        logger.info(f"🔍 Async Log search: '{query}' → {len(results)} past Q&As")
        return results

    async def search_redmine_tables(self, keyword: str) -> List[Dict]:
        """Search redmine-specific tables for keyword."""
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
            issues = await self._execute_query(sql_issues, (pattern, pattern))
            results.extend(issues)

            # Search redmine_journals
            try:
                sql_journals = """
                    SELECT 'redmine_journals' as source_table, journal_id, notes
                    FROM redmine_journals
                    WHERE notes LIKE %s
                    LIMIT 25
                """
                journals = await self._execute_query(sql_journals, (pattern,))
                results.extend(journals)
            except Exception:
                pass

            # Search redmine_relations
            try:
                sql_relations = """
                    SELECT 'redmine_relations' as source_table, relation_id, issue_from, issue_to
                    FROM redmine_relations
                    WHERE CAST(issue_from AS CHAR) LIKE %s OR CAST(issue_to AS CHAR) LIKE %s
                    LIMIT 25
                """
                relations = await self._execute_query(sql_relations, (pattern, pattern))
                results.extend(relations)
            except Exception:
                pass

            # Search redmine_sync_log
            try:
                sql_sync = """
                    SELECT 'redmine_sync_log' as source_table, sync_id, status, error_message
                    FROM redmine_sync_log
                    WHERE status LIKE %s OR error_message LIKE %s
                    LIMIT 25
                """
                sync = await self._execute_query(sql_sync, (pattern, pattern))
                results.extend(sync)
            except Exception:
                pass

            logger.info(f"🔍 Async Redmine search: '{keyword}' → {len(results)} documents")
            return results
        except Exception as e:
            logger.error(f"Redmine search failed: {e}")
            return []

    async def is_connected(self) -> bool:
        """Check if database connection is alive."""
        try:
            await self._execute_query("SELECT 1")
            return True
        except Exception:
            return False

    async def get_statistics(self) -> Dict:
        """Get database statistics."""
        try:
            sentences_count = (await self._execute_query("SELECT COUNT(*) as count FROM sentences"))[0]['count']
            logs_count = (await self._execute_query("SELECT COUNT(*) as count FROM qa_logs"))[0]['count']
            return {
                "sentences": sentences_count,
                "logs": logs_count,
                "status": "connected"
            }
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {"status": "error", "error": str(e)}

    async def close(self):
        """Close connection pool."""
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
            logger.info("Async DB Pool closed")
