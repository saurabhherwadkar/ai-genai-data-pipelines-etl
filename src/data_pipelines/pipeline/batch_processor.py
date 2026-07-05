"""
Batch processor with configurable concurrency.

Handles large-scale document ingestion with:
- Configurable batch sizes and concurrency limits
- Progress tracking and reporting
- Error isolation (one document failure doesn't stop the batch)
- Memory-efficient streaming for large document sets
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from data_pipelines.config.settings import get_settings
from data_pipelines.models.schemas import DocumentFormat, ExtractionSchema, PipelineResult
from data_pipelines.pipeline.orchestrator import PipelineOrchestrator
from data_pipelines.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class BatchProgress:
    """Tracks progress of batch processing."""

    total_documents: int = 0
    processed: int = 0
    successful: int = 0
    failed: int = 0
    current_batch: int = 0
    total_batches: int = 0
    elapsed_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def progress_percent(self) -> float:
        if self.total_documents == 0:
            return 0.0
        return round((self.processed / self.total_documents) * 100, 1)

    @property
    def documents_per_second(self) -> float:
        if self.elapsed_seconds == 0:
            return 0.0
        return round(self.processed / self.elapsed_seconds, 2)


class BatchProcessor:
    """
    Processes large document sets in configurable batches.

    Splits input into manageable chunks, processes them with
    controlled concurrency, and aggregates results. Provides
    progress tracking and error isolation.
    """

    def __init__(
        self,
        batch_size: int | None = None,
        max_concurrency: int = 5,
        schema: ExtractionSchema | None = None,
        orchestrator: PipelineOrchestrator | None = None,
        on_progress: Any = None,
    ) -> None:
        """
        Initialize batch processor.

        Args:
            batch_size: Documents per batch (defaults to settings).
            max_concurrency: Maximum concurrent batches.
            schema: Extraction schema for all documents.
            orchestrator: Pipeline orchestrator instance.
            on_progress: Optional callback(BatchProgress) for progress updates.
        """
        settings = get_settings()
        self._batch_size = batch_size or settings.extraction.batch_size
        self._max_concurrency = max_concurrency
        self._schema = schema
        self._orchestrator = orchestrator or PipelineOrchestrator(extraction_schema=schema)
        self._on_progress = on_progress
        self._progress = BatchProgress()

    async def process(
        self,
        documents: list[tuple[bytes | str, DocumentFormat]],
        schema: Optional[ExtractionSchema] = None,
    ) -> list[PipelineResult]:
        """
        Process all documents in batches with controlled concurrency.

        Args:
            documents: Full list of (content, format) tuples.
            schema: Override extraction schema.

        Returns:
            List of PipelineResult, one per batch.
        """
        extraction_schema = schema or self._schema
        start_time = time.time()

        # Split into batches
        batches = self._create_batches(documents)
        self._progress = BatchProgress(
            total_documents=len(documents),
            total_batches=len(batches),
        )

        logger.info(
            "Batch processing started",
            total_docs=len(documents),
            batch_size=self._batch_size,
            num_batches=len(batches),
            max_concurrency=self._max_concurrency,
        )

        # Process batches with concurrency limit
        semaphore = asyncio.Semaphore(self._max_concurrency)
        results = []

        async def process_batch(batch_idx: int, batch: list[tuple[bytes | str, DocumentFormat]]) -> PipelineResult:
            async with semaphore:
                try:
                    result = await self._orchestrator.run(batch, extraction_schema)
                    self._progress.processed += len(batch)
                    self._progress.successful += result.successful_extractions
                    self._progress.failed += result.failed_extractions
                    self._progress.current_batch = batch_idx + 1
                    self._progress.elapsed_seconds = time.time() - start_time
                    self._report_progress()
                    return result
                except Exception as e:
                    logger.error("Batch failed", batch_idx=batch_idx, error=str(e))
                    self._progress.processed += len(batch)
                    self._progress.failed += len(batch)
                    self._progress.errors.append(f"Batch {batch_idx}: {str(e)}")
                    return PipelineResult(
                        pipeline_id=f"batch-{batch_idx}-error",
                        total_documents=len(batch),
                        failed_extractions=len(batch),
                        status="failed",
                        errors=[str(e)],
                    )

        tasks = [process_batch(i, batch) for i, batch in enumerate(batches)]
        results = await asyncio.gather(*tasks)

        self._progress.elapsed_seconds = time.time() - start_time
        logger.info(
            "Batch processing completed",
            total_processed=self._progress.processed,
            successful=self._progress.successful,
            failed=self._progress.failed,
            elapsed=f"{self._progress.elapsed_seconds:.1f}s",
            throughput=f"{self._progress.documents_per_second} docs/s",
        )

        return list(results)

    def _create_batches(
        self, documents: list[tuple[bytes | str, DocumentFormat]]
    ) -> list[list[tuple[bytes | str, DocumentFormat]]]:
        """Split documents into batches of configured size."""
        batches = []
        for i in range(0, len(documents), self._batch_size):
            batches.append(documents[i : i + self._batch_size])
        return batches

    def _report_progress(self) -> None:
        """Report progress via callback if configured."""
        if self._on_progress:
            try:
                self._on_progress(self._progress)
            except Exception:
                pass

    @property
    def progress(self) -> BatchProgress:
        """Get current processing progress."""
        return self._progress
