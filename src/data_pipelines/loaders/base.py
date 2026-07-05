"""
Base loader interface.

Defines the contract that all loader implementations must follow.
"""

from abc import ABC, abstractmethod
from typing import Any

from data_pipelines.models.schemas import LoadResult


class BaseLoader(ABC):
    """Abstract base class for all data loaders."""

    @abstractmethod
    async def load(self, data: dict[str, Any], document_id: str) -> LoadResult:
        """
        Load a single record to the target destination.

        Args:
            data: Processed data to load.
            document_id: Source document identifier.

        Returns:
            LoadResult indicating success/failure.
        """
        ...

    @abstractmethod
    async def load_batch(self, records: list[dict[str, Any]], document_ids: list[str]) -> list[LoadResult]:
        """
        Load multiple records to the target destination.

        Args:
            records: List of processed data records.
            document_ids: Corresponding document identifiers.

        Returns:
            List of LoadResult for each record.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check connectivity to the target destination."""
        ...
