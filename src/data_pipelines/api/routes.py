"""
FastAPI routes for the ETL pipeline service.

Exposes REST endpoints for:
- Document submission and extraction
- Batch processing
- Quality validation
- Pipeline status and health checks
"""

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field

from data_pipelines.extractors.llm_extractor import LLMExtractor
from data_pipelines.extractors.parsers import get_parser
from data_pipelines.models.schemas import DocumentFormat, ExtractionSchema
from data_pipelines.pipeline.orchestrator import PipelineOrchestrator
from data_pipelines.quality.validator import QualityValidator
from data_pipelines.transformers.cleaner import DataCleaner
from data_pipelines.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["etl"])


# --- Request/Response Models ---


class ExtractionRequest(BaseModel):
    """Request body for single document extraction."""

    text: str = Field(..., description="Raw text to extract from")
    schema_fields: dict[str, Any] = Field(..., description="JSON Schema for extraction target")
    schema_name: str = Field(default="default", description="Name of the extraction schema")
    instructions: str = Field(default="", description="Additional extraction instructions")
    validate: bool = Field(default=True, description="Run quality validation after extraction")


class ExtractionResponse(BaseModel):
    """Response for extraction requests."""

    document_id: str
    extracted_data: dict[str, Any]
    quality_score: Optional[float] = None
    passed_validation: Optional[bool] = None
    issues: list[str] = Field(default_factory=list)


class BatchRequest(BaseModel):
    """Request body for batch document extraction."""

    documents: list[dict[str, str]] = Field(
        ..., description="List of {text, format} objects"
    )
    schema_fields: dict[str, Any] = Field(..., description="JSON Schema for extraction")
    schema_name: str = Field(default="default")
    instructions: str = Field(default="")


class BatchResponse(BaseModel):
    """Response for batch extraction requests."""

    pipeline_id: str
    total_documents: int
    successful: int
    failed: int
    results: list[ExtractionResponse] = Field(default_factory=list)
    quality_summary: Optional[dict[str, Any]] = None


class ValidationRequest(BaseModel):
    """Request body for standalone quality validation."""

    extracted_data: dict[str, Any] = Field(..., description="Data to validate")
    source_text: str = Field(..., description="Original source text")


class ValidationResponse(BaseModel):
    """Response for validation requests."""

    completeness: float
    accuracy: float
    passed: bool
    issues: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str = "1.0.0"
    services: dict[str, bool] = Field(default_factory=dict)


# --- Endpoints ---


@router.post("/extract", response_model=ExtractionResponse)
async def extract_document(request: ExtractionRequest) -> ExtractionResponse:
    """
    Extract structured data from a single document.

    Parses the input text, applies LLM extraction according to the provided
    schema, optionally validates quality, and returns structured results.
    """
    extractor = LLMExtractor()

    try:
        # Extract
        extracted = await extractor.extract(
            text=request.text,
            schema=request.schema_fields,
            instructions=request.instructions,
        )

        if not extracted:
            raise HTTPException(status_code=422, detail="Extraction produced no results")

        response = ExtractionResponse(
            document_id="single-extraction",
            extracted_data=extracted,
        )

        # Optionally validate
        if request.validate:
            validator = QualityValidator()
            validation = await validator.validate(extracted, request.text)
            response.quality_score = (
                validation.get("completeness", 0) + validation.get("accuracy", 0)
            ) / 2
            response.passed_validation = validator.check_thresholds(validation)
            response.issues = validation.get("issues", [])

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Extraction endpoint failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")


@router.post("/extract/batch", response_model=BatchResponse)
async def extract_batch(request: BatchRequest) -> BatchResponse:
    """
    Extract structured data from multiple documents in batch.

    Processes documents through the full pipeline: parse, extract,
    transform, validate, and returns aggregated results.
    """
    schema = ExtractionSchema(
        name=request.schema_name,
        fields=request.schema_fields,
        instructions=request.instructions,
    )

    # Convert to pipeline input format
    documents = []
    for doc in request.documents:
        text = doc.get("text", "")
        fmt = doc.get("format", "text")
        try:
            doc_format = DocumentFormat(fmt)
        except ValueError:
            doc_format = DocumentFormat.TEXT
        documents.append((text, doc_format))

    orchestrator = PipelineOrchestrator(extraction_schema=schema)

    try:
        result = await orchestrator.run(documents, schema)

        # Build individual responses
        extraction_responses = []
        if result.quality_report:
            for vr in result.quality_report.validation_results:
                extraction_responses.append(
                    ExtractionResponse(
                        document_id=vr.document_id,
                        extracted_data={},
                        quality_score=vr.overall_score,
                        passed_validation=vr.passed,
                        issues=vr.issues,
                    )
                )

        quality_summary = None
        if result.quality_report:
            quality_summary = {
                "average_completeness": result.quality_report.average_completeness,
                "average_accuracy": result.quality_report.average_accuracy,
                "pass_rate": result.quality_report.pass_rate,
            }

        return BatchResponse(
            pipeline_id=result.pipeline_id,
            total_documents=result.total_documents,
            successful=result.successful_extractions,
            failed=result.failed_extractions,
            results=extraction_responses,
            quality_summary=quality_summary,
        )

    except Exception as e:
        logger.error("Batch extraction failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Batch extraction failed: {str(e)}")


@router.post("/validate", response_model=ValidationResponse)
async def validate_extraction(request: ValidationRequest) -> ValidationResponse:
    """
    Validate extracted data quality against source text.

    Uses LLM-as-judge to score completeness and accuracy.
    """
    validator = QualityValidator()

    try:
        validation = await validator.validate(request.extracted_data, request.source_text)
        return ValidationResponse(
            completeness=validation.get("completeness", 0.0),
            accuracy=validation.get("accuracy", 0.0),
            passed=validation.get("passed", False),
            issues=validation.get("issues", []),
        )
    except Exception as e:
        logger.error("Validation endpoint failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Validation failed: {str(e)}")


@router.post("/parse")
async def parse_document(
    file: UploadFile = File(...),
    format_type: str = Form(default="text"),
) -> dict[str, Any]:
    """
    Parse an uploaded document into normalized text.

    Supports PDF, HTML, CSV, and email formats.
    """
    try:
        content = await file.read()
        doc_format = DocumentFormat(format_type)
        parser = get_parser(doc_format)
        document = parser.parse(content, metadata={"filename": file.filename})

        return {
            "document_id": document.id,
            "format": document.format.value,
            "text_length": len(document.raw_content),
            "preview": document.raw_content[:500],
            "metadata": document.metadata,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format_type}")
    except Exception as e:
        logger.error("Parse endpoint failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Parsing failed: {str(e)}")


@router.post("/transform/clean")
async def clean_data(data: dict[str, Any]) -> dict[str, Any]:
    """Apply data cleaning transformations to extracted data."""
    cleaner = DataCleaner()
    cleaned = cleaner.clean(data)
    return {"original_fields": len(data), "cleaned_fields": len(cleaned), "data": cleaned}


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Service health check endpoint."""
    return HealthResponse(
        status="healthy",
        services={
            "api": True,
            "extractor": True,
            "validator": True,
        },
    )
