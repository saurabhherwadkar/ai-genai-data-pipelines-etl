"""
Pipeline orchestrator.

Coordinates the end-to-end ETL flow:
  Parse -> Extract -> Transform -> Validate -> Route -> Load

Manages stage transitions, error handling, and pipeline state.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from data_pipelines.config.settings import get_settings
from data_pipelines.extractors.llm_extractor import LLMExtractor
from data_pipelines.extractors.parsers import get_parser
from data_pipelines.loaders.json_loader import JSONFileLoader
from data_pipelines.models.schemas import (
    Document,
    DocumentFormat,
    ExtractionResult,
    ExtractionSchema,
    LoadResult,
    PipelineResult,
    QualityReport,
    ValidationResult,
)
from data_pipelines.quality.validator import QualityValidator
from data_pipelines.transformers.cleaner import DataCleaner
from data_pipelines.transformers.enricher import DataEnricher
from data_pipelines.transformers.normalizer import DataNormalizer
from data_pipelines.utils.logger import get_logger

logger = get_logger(__name__)


class PipelineOrchestrator:
    """
    Orchestrates the full ETL pipeline from ingestion to loading.

    The pipeline follows this flow:
    1. PARSE: Convert raw documents into normalized text (Document model)
    2. EXTRACT: Use LLM to extract structured data from text
    3. TRANSFORM: Clean, normalize, and enrich extracted data
    4. VALIDATE: Score data quality using LLM-as-judge
    5. ROUTE: Pass/fail/flag based on quality thresholds
    6. LOAD: Write validated data to target destination

    Supports configurable stages, error recovery, and detailed reporting.
    """

    def __init__(
        self,
        extraction_schema: ExtractionSchema | None = None,
        loader: Any | None = None,
        cleaner_rules: dict[str, Any] | None = None,
        field_mapping: dict[str, str] | None = None,
        skip_validation: bool = False,
    ) -> None:
        """
        Initialize the pipeline orchestrator.

        Args:
            extraction_schema: Schema defining the extraction target.
            loader: Data loader instance (defaults to JSONFileLoader).
            cleaner_rules: Rules for the data cleaning stage.
            field_mapping: Field mapping for normalization.
            skip_validation: Skip the LLM quality validation stage.
        """
        self._settings = get_settings()
        self._schema = extraction_schema
        self._extractor = LLMExtractor()
        self._validator = QualityValidator()
        self._cleaner = DataCleaner(rules=cleaner_rules)
        self._normalizer = DataNormalizer(field_mapping=field_mapping)
        self._enricher = DataEnricher()
        self._loader = loader or JSONFileLoader()
        self._skip_validation = skip_validation

    async def run(
        self,
        documents: list[tuple[bytes | str, DocumentFormat]],
        schema: Optional[ExtractionSchema] = None,
    ) -> PipelineResult:
        """
        Execute the full pipeline on a batch of documents.

        Args:
            documents: List of (content, format) tuples to process.
            schema: Override extraction schema for this run.

        Returns:
            PipelineResult with full execution details.
        """
        pipeline_id = str(uuid.uuid4())
        started_at = datetime.utcnow()
        extraction_schema = schema or self._schema

        if not extraction_schema:
            return PipelineResult(
                pipeline_id=pipeline_id,
                started_at=started_at,
                status="failed",
                errors=["No extraction schema provided"],
            )

        logger.info("Pipeline started", pipeline_id=pipeline_id, doc_count=len(documents))

        result = PipelineResult(
            pipeline_id=pipeline_id,
            started_at=started_at,
            total_documents=len(documents),
            status="running",
        )

        # Stage 1: Parse documents
        parsed_docs = await self._stage_parse(documents)

        # Stage 2: Extract structured data
        extractions = await self._stage_extract(parsed_docs, extraction_schema)
        result.successful_extractions = sum(1 for e in extractions if e.success)
        result.failed_extractions = sum(1 for e in extractions if not e.success)

        # Stage 3: Transform (clean, normalize, enrich)
        transformed = await self._stage_transform(extractions, parsed_docs)

        # Stage 4: Validate quality
        validation_results = await self._stage_validate(transformed, parsed_docs)
        result.quality_report = self._build_quality_report(validation_results)

        # Stage 5: Route and Load
        load_results = await self._stage_load(transformed, validation_results)
        result.load_results = load_results

        result.completed_at = datetime.utcnow()
        result.status = "completed"
        logger.info(
            "Pipeline completed",
            pipeline_id=pipeline_id,
            successful=result.successful_extractions,
            failed=result.failed_extractions,
        )

        return result

    async def _stage_parse(self, documents: list[tuple[bytes | str, DocumentFormat]]) -> list[Document]:
        """Stage 1: Parse raw documents into Document models."""
        parsed = []
        for content, format_type in documents:
            try:
                parser = get_parser(format_type)
                doc = parser.parse(content)
                parsed.append(doc)
            except Exception as e:
                logger.error("Parse failed", format=format_type, error=str(e))
                # Create a minimal document for error tracking
                parsed.append(
                    Document(
                        id=str(uuid.uuid4()),
                        format=format_type,
                        raw_content=f"(parse error: {str(e)})",
                        metadata={"error": str(e)},
                    )
                )
        return parsed

    async def _stage_extract(
        self, documents: list[Document], schema: ExtractionSchema
    ) -> list[ExtractionResult]:
        """Stage 2: LLM extraction from parsed documents."""
        results = []
        schema_dict = schema.fields

        for doc in documents:
            try:
                import time

                start = time.time()
                extracted = await self._extractor.extract(
                    text=doc.raw_content,
                    schema=schema_dict,
                    instructions=schema.instructions,
                )
                elapsed = (time.time() - start) * 1000

                results.append(
                    ExtractionResult(
                        document_id=doc.id,
                        schema_name=schema.name,
                        extracted_data=extracted,
                        extraction_time_ms=elapsed,
                        success=bool(extracted),
                    )
                )
            except Exception as e:
                logger.error("Extraction failed", document_id=doc.id, error=str(e))
                results.append(
                    ExtractionResult(
                        document_id=doc.id,
                        schema_name=schema.name,
                        success=False,
                        error=str(e),
                    )
                )
        return results

    async def _stage_transform(
        self, extractions: list[ExtractionResult], documents: list[Document]
    ) -> list[dict[str, Any]]:
        """Stage 3: Clean, normalize, and enrich extracted data."""
        transformed = []
        for extraction, doc in zip(extractions, documents):
            if not extraction.success:
                transformed.append({})
                continue

            data = extraction.extracted_data
            # Clean
            data = self._cleaner.clean(data)
            # Normalize
            data = self._normalizer.normalize(data)
            # Enrich
            data = self._enricher.enrich(data, source_metadata=doc.metadata)
            transformed.append(data)

        return transformed

    async def _stage_validate(
        self, transformed: list[dict[str, Any]], documents: list[Document]
    ) -> list[ValidationResult]:
        """Stage 4: Quality validation using LLM-as-judge."""
        if self._skip_validation:
            return [
                ValidationResult(document_id=doc.id, passed=True, overall_score=1.0)
                for doc in documents
            ]

        results = []
        for data, doc in zip(transformed, documents):
            if not data:
                results.append(
                    ValidationResult(
                        document_id=doc.id, passed=False, flagged_for_review=True
                    )
                )
                continue

            try:
                validation = await self._validator.validate(data, doc.raw_content)
                completeness = validation.get("completeness", 0.0)
                accuracy = validation.get("accuracy", 0.0)
                overall = (completeness + accuracy) / 2
                passed = self._validator.check_thresholds(validation)

                results.append(
                    ValidationResult(
                        document_id=doc.id,
                        completeness_score=completeness,
                        accuracy_score=accuracy,
                        overall_score=overall,
                        issues=validation.get("issues", []),
                        passed=passed,
                        flagged_for_review=not passed and overall > 0.5,
                    )
                )
            except Exception as e:
                logger.error("Validation failed", document_id=doc.id, error=str(e))
                results.append(
                    ValidationResult(
                        document_id=doc.id, passed=False, flagged_for_review=True
                    )
                )
        return results

    async def _stage_load(
        self, transformed: list[dict[str, Any]], validations: list[ValidationResult]
    ) -> list[LoadResult]:
        """Stage 5: Load validated data to target destination."""
        results = []
        for data, validation in zip(transformed, validations):
            if not validation.passed:
                results.append(
                    LoadResult(
                        document_id=validation.document_id,
                        destination="skipped",
                        success=False,
                        error="Quality validation failed",
                    )
                )
                continue

            try:
                load_result = await self._loader.load(data, validation.document_id)
                results.append(load_result)
            except Exception as e:
                results.append(
                    LoadResult(
                        document_id=validation.document_id,
                        destination="error",
                        success=False,
                        error=str(e),
                    )
                )
        return results

    def _build_quality_report(self, validations: list[ValidationResult]) -> QualityReport:
        """Build aggregate quality report from individual validations."""
        total = len(validations)
        passed = sum(1 for v in validations if v.passed)
        failed = sum(1 for v in validations if not v.passed and not v.flagged_for_review)
        flagged = sum(1 for v in validations if v.flagged_for_review)

        avg_completeness = (
            sum(v.completeness_score for v in validations) / total if total > 0 else 0.0
        )
        avg_accuracy = (
            sum(v.accuracy_score for v in validations) / total if total > 0 else 0.0
        )

        return QualityReport(
            total_documents=total,
            passed_count=passed,
            failed_count=failed,
            flagged_count=flagged,
            average_completeness=round(avg_completeness, 3),
            average_accuracy=round(avg_accuracy, 3),
            validation_results=validations,
        )
