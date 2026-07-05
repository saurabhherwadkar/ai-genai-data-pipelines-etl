"""
JSON file loader.

Writes processed records to JSON files on disk, supporting
both individual files per record and batch append to a single file.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from data_pipelines.models.schemas import LoadResult
from data_pipelines.loaders.base import BaseLoader
from data_pipelines.utils.logger import get_logger

logger = get_logger(__name__)


class JSONFileLoader(BaseLoader):
    """
    Loads processed data to JSON files.

    Supports two modes:
    - Individual: One JSON file per document (good for auditing)
    - Batch: Append to a single JSONL file (good for bulk processing)
    """

    def __init__(
        self,
        output_dir: str = "output",
        mode: str = "individual",
        batch_file: str = "extractions.jsonl",
    ) -> None:
        """
        Initialize JSON file loader.

        Args:
            output_dir: Directory for output files.
            mode: 'individual' for one file per record, 'batch' for JSONL.
            batch_file: Filename for batch mode output.
        """
        self._output_dir = Path(output_dir)
        self._mode = mode
        self._batch_file = batch_file
        self._output_dir.mkdir(parents=True, exist_ok=True)

    async def load(self, data: dict[str, Any], document_id: str) -> LoadResult:
        """Write a single record to JSON."""
        try:
            if self._mode == "individual":
                filepath = self._output_dir / f"{document_id}.json"
                record = {
                    "document_id": document_id,
                    "data": data,
                    "loaded_at": datetime.utcnow().isoformat(),
                }
                filepath.write_text(json.dumps(record, indent=2, default=str))
            else:
                filepath = self._output_dir / self._batch_file
                line = json.dumps(
                    {"document_id": document_id, "data": data, "loaded_at": datetime.utcnow().isoformat()},
                    default=str,
                )
                with open(filepath, "a") as f:
                    f.write(line + "\n")

            logger.info("Record loaded to JSON", document_id=document_id, path=str(filepath))
            return LoadResult(
                document_id=document_id,
                destination=str(filepath),
                success=True,
                records_written=1,
            )
        except Exception as e:
            logger.error("JSON load failed", document_id=document_id, error=str(e))
            return LoadResult(
                document_id=document_id,
                destination=str(self._output_dir),
                success=False,
                error=str(e),
            )

    async def load_batch(self, records: list[dict[str, Any]], document_ids: list[str]) -> list[LoadResult]:
        """Write multiple records."""
        results = []
        for data, doc_id in zip(records, document_ids):
            result = await self.load(data, doc_id)
            results.append(result)
        return results

    async def health_check(self) -> bool:
        """Check that output directory is writable."""
        try:
            test_file = self._output_dir / ".health_check"
            test_file.write_text("ok")
            test_file.unlink()
            return True
        except Exception:
            return False
