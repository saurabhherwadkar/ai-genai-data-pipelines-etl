"""
Core Pydantic models defining data contracts between pipeline stages.

These schemas enforce strict typing at each boundary:
  Source Document -> Extraction -> Validation -> Loading
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class DocumentFormat(str, Enum):
    """Supported input document formats."""

    PDF = "pdf"
    EMAIL = "email"
    HTML = "html"
    CSV = "csv"
    TEXT = "text"


class Document(BaseModel):
    """Represents an ingested document ready for extraction."""

    id: str = Field(..., description="Unique document identifier")
    format: DocumentFormat = Field(..., description="Source format type")
    raw_content: str = Field(..., description="Raw text content after parsing")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Source metadata")
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    size_bytes: int = Field(default=0, description="Original document size")

    @field_validator("raw_content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Document raw_content must not be empty")
        return v


class ExtractionSchema(BaseModel):
    """Defines the target schema for LLM extraction."""

    name: str = Field(..., description="Schema name, e.g. 'invoice', 'resume'")
    version: str = Field(default="1.0")
    fields: dict[str, Any] = Field(..., description="JSON Schema definition of output fields")
    instructions: str = Field(default="", description="Additional extraction guidance")
    few_shot_examples: list[dict[str, Any]] = Field(
        default_factory=list, description="Few-shot examples for the LLM"
    )


class ExtractionResult(BaseModel):
    """Result of LLM extraction for a single document."""

    document_id: str
    schema_name: str
    extracted_data: dict[str, Any] = Field(default_factory=dict)
    raw_llm_response: str = Field(default="", description="Raw LLM output before parsing")
    extraction_time_ms: float = Field(default=0.0)
    success: bool = Field(default=True)
    error: Optional[str] = None
    token_usage: dict[str, int] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    """Result of quality validation for a single extraction."""

    document_id: str
    completeness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    accuracy_score: float = Field(default=0.0, ge=0.0, le=1.0)
    consistency_score: float = Field(default=0.0, ge=0.0, le=1.0)
    overall_score: float = Field(default=0.0, ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list)
    passed: bool = Field(default=False)
    flagged_for_review: bool = Field(default=False)


class QualityReport(BaseModel):
    """Aggregate quality report for a batch of extractions."""

    total_documents: int = 0
    passed_count: int = 0
    failed_count: int = 0
    flagged_count: int = 0
    average_completeness: float = 0.0
    average_accuracy: float = 0.0
    average_consistency: float = 0.0
    validation_results: list[ValidationResult] = Field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        if self.total_documents == 0:
            return 0.0
        return self.passed_count / self.total_documents


class LoadResult(BaseModel):
    """Result of loading data to a target destination."""

    document_id: str
    destination: str
    success: bool = True
    records_written: int = 0
    error: Optional[str] = None
    loaded_at: datetime = Field(default_factory=datetime.utcnow)


class PipelineResult(BaseModel):
    """End-to-end pipeline result for a batch run."""

    pipeline_id: str
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    total_documents: int = 0
    successful_extractions: int = 0
    failed_extractions: int = 0
    quality_report: Optional[QualityReport] = None
    load_results: list[LoadResult] = Field(default_factory=list)
    status: str = Field(default="pending")
    errors: list[str] = Field(default_factory=list)
