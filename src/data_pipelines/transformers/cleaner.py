"""
Data cleaning transformations.

Applies rule-based cleaning to extracted data before loading:
- Whitespace normalization
- Null/empty field handling
- Type coercion
- Pattern-based sanitization
"""

import re
from datetime import datetime
from typing import Any

from data_pipelines.utils.logger import get_logger

logger = get_logger(__name__)


class DataCleaner:
    """
    Cleans and sanitizes extracted data fields.

    Applies a pipeline of cleaning rules to ensure data consistency
    before it reaches the loading stage.
    """

    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        """
        Initialize cleaner with optional custom rules.

        Args:
            rules: Dictionary of field-specific cleaning rules.
                   Keys are field names, values are rule configs.
        """
        self._rules = rules or {}

    def clean(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Apply all cleaning transformations to extracted data.

        Args:
            data: Raw extracted data dictionary.

        Returns:
            Cleaned data dictionary.
        """
        cleaned = {}
        for key, value in data.items():
            cleaned_value = self._clean_field(key, value)
            if cleaned_value is not None:
                cleaned[key] = cleaned_value
        return cleaned

    def clean_batch(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Clean a batch of extracted records."""
        results = []
        for record in records:
            try:
                results.append(self.clean(record))
            except Exception as e:
                logger.error("Cleaning failed for record", error=str(e))
                results.append(record)  # Pass through on failure
        return results

    def _clean_field(self, key: str, value: Any) -> Any:
        """Apply cleaning rules to a single field."""
        if value is None:
            return None

        # String cleaning
        if isinstance(value, str):
            value = self._clean_string(value)
            # Apply field-specific rules
            rule = self._rules.get(key, {})
            if rule.get("strip_html"):
                value = self._strip_html(value)
            if rule.get("lowercase"):
                value = value.lower()
            if rule.get("uppercase"):
                value = value.upper()
            if rule.get("date_format"):
                value = self._parse_date(value, rule["date_format"])
            if rule.get("pattern"):
                value = self._apply_pattern(value, rule["pattern"])
            # Return None for empty strings after cleaning
            return value if value else None

        # Nested dict cleaning
        if isinstance(value, dict):
            return self.clean(value)

        # List cleaning
        if isinstance(value, list):
            return [self._clean_field(key, item) for item in value if item is not None]

        return value

    def _clean_string(self, text: str) -> str:
        """Normalize whitespace and trim strings."""
        # Replace various whitespace characters
        text = re.sub(r"[\t\r\x0b\x0c]+", " ", text)
        # Collapse multiple spaces
        text = re.sub(r" {2,}", " ", text)
        # Strip leading/trailing whitespace
        text = text.strip()
        # Remove null bytes and control characters
        text = re.sub(r"[\x00-\x08\x0e-\x1f\x7f]", "", text)
        return text

    def _strip_html(self, text: str) -> str:
        """Remove HTML tags from a string."""
        return re.sub(r"<[^>]+>", "", text).strip()

    def _parse_date(self, text: str, target_format: str) -> str:
        """Attempt to parse and reformat a date string."""
        common_formats = [
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%d/%m/%Y",
            "%B %d, %Y",
            "%b %d, %Y",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
        ]
        for fmt in common_formats:
            try:
                dt = datetime.strptime(text.strip(), fmt)
                return dt.strftime(target_format)
            except ValueError:
                continue
        return text  # Return original if no format matches

    def _apply_pattern(self, text: str, pattern: str) -> str:
        """Extract value matching a regex pattern."""
        match = re.search(pattern, text)
        return match.group(0) if match else text
