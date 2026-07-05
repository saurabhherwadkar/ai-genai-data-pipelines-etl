"""Tests for Pydantic data models."""

import pytest
from pydantic import ValidationError

from data_pipelines.models.schemas import (
    Document,
    DocumentFormat,
    ExtractionResult,
    ExtractionSchema,
    QualityReport,
    ValidationResult,
)


class TestDocumentModel:
    """Tests for the Document model."""

    def test_valid_document(self) -> None:
        doc = Document(
            id="test-001",
            format=DocumentFormat.HTML,
            raw_content="Hello world",
        )
        assert doc.id == "test-001"
        assert doc.format == DocumentFormat.HTML
        assert doc.raw_content == "Hello world"
        assert doc.ingested_at is not None

    def test_empty_content_raises(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            Document(id="test", format=DocumentFormat.HTML, raw_content="   ")

    def test_metadata_defaults_to_empty(self) -> None:
        doc = Document(id="test", format=DocumentFormat.PDF, raw_content="content")
        assert doc.metadata == {}


class TestExtractionSchema:
    """Tests for the ExtractionSchema model."""

    def test_schema_creation(self) -> None:
        schema = ExtractionSchema(
            name="invoice",
            fields={"vendor": {"type": "string"}, "amount": {"type": "number"}},
            instructions="Extract invoice fields",
        )
        assert schema.name == "invoice"
        assert schema.version == "1.0"
        assert "vendor" in schema.fields

    def test_schema_with_examples(self) -> None:
        schema = ExtractionSchema(
            name="resume",
            fields={"name": {"type": "string"}},
            few_shot_examples=[{"input": "John Doe", "output": {"name": "John Doe"}}],
        )
        assert len(schema.few_shot_examples) == 1


class TestValidationResult:
    """Tests for the ValidationResult model."""

    def test_score_bounds(self) -> None:
        vr = ValidationResult(
            document_id="doc1",
            completeness_score=0.95,
            accuracy_score=0.88,
            overall_score=0.91,
            passed=True,
        )
        assert vr.completeness_score == 0.95
        assert vr.passed is True

    def test_score_out_of_bounds_raises(self) -> None:
        with pytest.raises(ValidationError):
            ValidationResult(
                document_id="doc1",
                completeness_score=1.5,  # Out of bounds
            )


class TestQualityReport:
    """Tests for the QualityReport model."""

    def test_pass_rate_calculation(self) -> None:
        report = QualityReport(
            total_documents=10,
            passed_count=8,
            failed_count=2,
        )
        assert report.pass_rate == 0.8

    def test_empty_report_pass_rate(self) -> None:
        report = QualityReport()
        assert report.pass_rate == 0.0


class TestExtractionResult:
    """Tests for the ExtractionResult model."""

    def test_successful_extraction(self) -> None:
        result = ExtractionResult(
            document_id="doc1",
            schema_name="invoice",
            extracted_data={"vendor": "ACME", "amount": 150.00},
            extraction_time_ms=1234.5,
            success=True,
        )
        assert result.success is True
        assert result.extracted_data["vendor"] == "ACME"

    def test_failed_extraction(self) -> None:
        result = ExtractionResult(
            document_id="doc1",
            schema_name="invoice",
            success=False,
            error="LLM timeout",
        )
        assert result.success is False
        assert result.error == "LLM timeout"
