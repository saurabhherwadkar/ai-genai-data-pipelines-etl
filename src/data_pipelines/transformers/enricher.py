"""
Data enrichment transformations.

Adds computed fields, derived values, and external data lookups
to enhance extracted records before loading.
"""

import hashlib
import re
from datetime import datetime
from typing import Any, Callable

from data_pipelines.utils.logger import get_logger

logger = get_logger(__name__)


class DataEnricher:
    """
    Enriches extracted data with computed and derived fields.

    Adds metadata, computed values, and derived fields that enhance
    the extracted data for downstream consumption.
    """

    def __init__(
        self,
        computed_fields: dict[str, Callable[[dict], Any]] | None = None,
        enrichment_rules: list[dict[str, Any]] | None = None,
    ) -> None:
        """
        Initialize enricher.

        Args:
            computed_fields: Dict of field_name -> function(record) -> value.
            enrichment_rules: List of rule configurations for conditional enrichment.
        """
        self._computed_fields = computed_fields or {}
        self._enrichment_rules = enrichment_rules or []

    def enrich(self, data: dict[str, Any], source_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Enrich a data record with computed fields and metadata.

        Args:
            data: Extracted and cleaned data dictionary.
            source_metadata: Original document metadata for context.

        Returns:
            Enriched data dictionary.
        """
        enriched = dict(data)

        # Add processing metadata
        enriched["_enrichment"] = {
            "processed_at": datetime.utcnow().isoformat(),
            "record_hash": self._compute_hash(data),
            "field_count": len(data),
            "completeness": self._compute_completeness(data),
        }

        # Add source metadata if provided
        if source_metadata:
            enriched["_source"] = {
                "format": source_metadata.get("parser", "unknown"),
                "ingested_at": source_metadata.get("ingested_at", ""),
            }

        # Apply computed fields
        for field_name, compute_fn in self._computed_fields.items():
            try:
                enriched[field_name] = compute_fn(data)
            except Exception as e:
                logger.warning("Computed field failed", field=field_name, error=str(e))

        # Apply conditional enrichment rules
        for rule in self._enrichment_rules:
            enriched = self._apply_rule(enriched, rule)

        # Add text analytics for string fields
        enriched = self._add_text_analytics(enriched)

        return enriched

    def enrich_batch(
        self, records: list[dict[str, Any]], metadata_list: list[dict] | None = None
    ) -> list[dict[str, Any]]:
        """Enrich a batch of records."""
        metadata_list = metadata_list or [{}] * len(records)
        results = []
        for record, meta in zip(records, metadata_list):
            try:
                results.append(self.enrich(record, meta))
            except Exception as e:
                logger.error("Enrichment failed", error=str(e))
                results.append(record)
        return results

    def _compute_hash(self, data: dict[str, Any]) -> str:
        """Compute a deterministic hash of the record for deduplication."""
        import json

        serialized = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()[:16]

    def _compute_completeness(self, data: dict[str, Any]) -> float:
        """Compute field completeness ratio."""
        if not data:
            return 0.0
        filled = sum(1 for v in data.values() if v is not None and v != "" and v != [])
        return round(filled / len(data), 3)

    def _apply_rule(self, data: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
        """Apply a conditional enrichment rule."""
        condition_field = rule.get("if_field")
        condition_value = rule.get("equals")
        then_set = rule.get("then_set", {})

        if condition_field and condition_field in data:
            if data[condition_field] == condition_value:
                data.update(then_set)
        return data

    def _add_text_analytics(self, data: dict[str, Any]) -> dict[str, Any]:
        """Add basic text analytics for string fields."""
        text_stats = {}
        for key, value in data.items():
            if isinstance(value, str) and len(value) > 50 and not key.startswith("_"):
                text_stats[key] = {
                    "length": len(value),
                    "word_count": len(value.split()),
                    "has_email": bool(re.search(r"[\w.-]+@[\w.-]+\.\w+", value)),
                    "has_phone": bool(re.search(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", value)),
                    "has_url": bool(re.search(r"https?://\S+", value)),
                }
        if text_stats:
            data["_text_analytics"] = text_stats
        return data
