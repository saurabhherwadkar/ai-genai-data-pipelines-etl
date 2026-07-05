"""
Database loader.

Writes processed records to a SQL database using async SQLAlchemy.
Supports PostgreSQL and SQLite backends.
"""

import json
from datetime import datetime
from typing import Any, Optional

from data_pipelines.loaders.base import BaseLoader
from data_pipelines.models.schemas import LoadResult
from data_pipelines.utils.logger import get_logger

logger = get_logger(__name__)


class DatabaseLoader(BaseLoader):
    """
    Loads processed data to a SQL database.

    Uses async SQLAlchemy for database operations. Supports both
    PostgreSQL (production) and SQLite (development/testing) backends.
    Records are stored in a configurable table with JSON data column.
    """

    def __init__(
        self,
        connection_string: str = "sqlite+aiosqlite:///data/extractions.db",
        table_name: str = "extractions",
    ) -> None:
        """
        Initialize database loader.

        Args:
            connection_string: SQLAlchemy async connection string.
            table_name: Target table name for storing records.
        """
        self._connection_string = connection_string
        self._table_name = table_name
        self._engine = None
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        """Lazy initialization of database engine and table."""
        if self._initialized:
            return

        try:
            from sqlalchemy.ext.asyncio import create_async_engine
            from sqlalchemy import text

            self._engine = create_async_engine(self._connection_string, echo=False)

            # Create table if it doesn't exist
            create_sql = f"""
                CREATE TABLE IF NOT EXISTS {self._table_name} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL,
                    data JSON NOT NULL,
                    schema_name TEXT DEFAULT '',
                    quality_score REAL DEFAULT 0.0,
                    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata JSON DEFAULT '{{}}'
                )
            """
            async with self._engine.begin() as conn:
                await conn.execute(text(create_sql))

            self._initialized = True
            logger.info("Database loader initialized", table=self._table_name)

        except ImportError:
            logger.warning("SQLAlchemy not available, database loader disabled")
            self._initialized = False

    async def load(self, data: dict[str, Any], document_id: str) -> LoadResult:
        """Insert a single record into the database."""
        try:
            await self._ensure_initialized()
            if not self._engine:
                return LoadResult(
                    document_id=document_id,
                    destination=self._table_name,
                    success=False,
                    error="Database engine not initialized",
                )

            from sqlalchemy import text

            insert_sql = f"""
                INSERT INTO {self._table_name} (document_id, data, loaded_at)
                VALUES (:doc_id, :data, :loaded_at)
            """

            async with self._engine.begin() as conn:
                await conn.execute(
                    text(insert_sql),
                    {
                        "doc_id": document_id,
                        "data": json.dumps(data, default=str),
                        "loaded_at": datetime.utcnow().isoformat(),
                    },
                )

            logger.info("Record loaded to database", document_id=document_id)
            return LoadResult(
                document_id=document_id,
                destination=f"{self._table_name}@{self._connection_string.split('@')[-1] if '@' in self._connection_string else 'local'}",
                success=True,
                records_written=1,
            )

        except Exception as e:
            logger.error("Database load failed", document_id=document_id, error=str(e))
            return LoadResult(
                document_id=document_id,
                destination=self._table_name,
                success=False,
                error=str(e),
            )

    async def load_batch(self, records: list[dict[str, Any]], document_ids: list[str]) -> list[LoadResult]:
        """Insert multiple records in a single transaction."""
        try:
            await self._ensure_initialized()
            if not self._engine:
                return [
                    LoadResult(document_id=doc_id, destination=self._table_name, success=False, error="Not initialized")
                    for doc_id in document_ids
                ]

            from sqlalchemy import text

            insert_sql = f"""
                INSERT INTO {self._table_name} (document_id, data, loaded_at)
                VALUES (:doc_id, :data, :loaded_at)
            """

            results = []
            async with self._engine.begin() as conn:
                for data, doc_id in zip(records, document_ids):
                    try:
                        await conn.execute(
                            text(insert_sql),
                            {
                                "doc_id": doc_id,
                                "data": json.dumps(data, default=str),
                                "loaded_at": datetime.utcnow().isoformat(),
                            },
                        )
                        results.append(LoadResult(document_id=doc_id, destination=self._table_name, success=True, records_written=1))
                    except Exception as e:
                        results.append(LoadResult(document_id=doc_id, destination=self._table_name, success=False, error=str(e)))

            return results

        except Exception as e:
            logger.error("Batch database load failed", error=str(e))
            return [
                LoadResult(document_id=doc_id, destination=self._table_name, success=False, error=str(e))
                for doc_id in document_ids
            ]

    async def health_check(self) -> bool:
        """Check database connectivity."""
        try:
            await self._ensure_initialized()
            if not self._engine:
                return False
            from sqlalchemy import text

            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
