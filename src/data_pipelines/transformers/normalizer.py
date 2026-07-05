"""
Data normalization transformations.

Handles schema alignment, field mapping, and data type conversion
to ensure extracted data conforms to target schemas.
"""

from typing import Any, Callable

from data_pipelines.utils.logger import get_logger

logger = get_logger(__name__)


class DataNormalizer:
    """
    Normalizes extracted data to conform to target schemas.

    Performs field mapping, type coercion, default value injection,
    and structural transformations to align diverse extraction outputs
    with a unified target schema.
    """

    def __init__(
        self,
        field_mapping: dict[str, str] | None = None,
        type_coercions: dict[str, str] | None = None,
        defaults: dict[str, Any] | None = None,
        custom_transforms: dict[str, Callable] | None = None,
    ) -> None:
        """
        Initialize normalizer with transformation rules.

        Args:
            field_mapping: Source-to-target field name mapping.
            type_coercions: Field name to target type mapping (int, float, str, bool, list).
            defaults: Default values for missing fields.
            custom_transforms: Field-specific transformation functions.
        """
        self._field_mapping = field_mapping or {}
        self._type_coercions = type_coercions or {}
        self._defaults = defaults or {}
        self._custom_transforms = custom_transforms or {}

    def normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Apply full normalization pipeline to a data record.

        Pipeline order:
        1. Apply field mapping (rename fields)
        2. Apply type coercions
        3. Apply custom transforms
        4. Inject defaults for missing fields
        5. Remove unknown fields (if strict mode)

        Args:
            data: Extracted data dictionary.

        Returns:
            Normalized data dictionary.
        """
        result = self._apply_field_mapping(data)
        result = self._apply_type_coercions(result)
        result = self._apply_custom_transforms(result)
        result = self._apply_defaults(result)
        return result

    def normalize_batch(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize a batch of records."""
        results = []
        for record in records:
            try:
                results.append(self.normalize(record))
            except Exception as e:
                logger.error("Normalization failed", error=str(e))
                results.append(record)
        return results

    def _apply_field_mapping(self, data: dict[str, Any]) -> dict[str, Any]:
        """Rename fields according to the mapping."""
        if not self._field_mapping:
            return dict(data)

        result = {}
        for key, value in data.items():
            mapped_key = self._field_mapping.get(key, key)
            result[mapped_key] = value
        return result

    def _apply_type_coercions(self, data: dict[str, Any]) -> dict[str, Any]:
        """Coerce field values to target types."""
        result = dict(data)
        for field, target_type in self._type_coercions.items():
            if field in result and result[field] is not None:
                result[field] = self._coerce_value(result[field], target_type)
        return result

    def _coerce_value(self, value: Any, target_type: str) -> Any:
        """Coerce a single value to the target type."""
        coercion_map: dict[str, Callable] = {
            "int": self._to_int,
            "float": self._to_float,
            "str": str,
            "bool": self._to_bool,
            "list": self._to_list,
        }
        coercer = coercion_map.get(target_type)
        if coercer is None:
            return value
        try:
            return coercer(value)
        except (ValueError, TypeError):
            logger.warning("Type coercion failed", value=str(value), target=target_type)
            return value

    def _to_int(self, value: Any) -> int:
        """Convert to int, handling string numbers with commas."""
        if isinstance(value, str):
            value = value.replace(",", "").replace(" ", "").strip()
        return int(float(value))

    def _to_float(self, value: Any) -> float:
        """Convert to float, handling formatted numbers."""
        if isinstance(value, str):
            value = value.replace(",", "").replace(" ", "").replace("$", "").strip()
        return float(value)

    def _to_bool(self, value: Any) -> bool:
        """Convert to bool with common string representations."""
        if isinstance(value, str):
            return value.lower().strip() in ("true", "yes", "1", "y", "on")
        return bool(value)

    def _to_list(self, value: Any) -> list:
        """Convert to list."""
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            # Split on common delimiters
            for delimiter in [",", ";", "|", "\n"]:
                if delimiter in value:
                    return [item.strip() for item in value.split(delimiter) if item.strip()]
            return [value]
        return [value]

    def _apply_custom_transforms(self, data: dict[str, Any]) -> dict[str, Any]:
        """Apply custom transformation functions."""
        result = dict(data)
        for field, transform_fn in self._custom_transforms.items():
            if field in result:
                try:
                    result[field] = transform_fn(result[field])
                except Exception as e:
                    logger.warning("Custom transform failed", field=field, error=str(e))
        return result

    def _apply_defaults(self, data: dict[str, Any]) -> dict[str, Any]:
        """Inject default values for missing fields."""
        result = dict(data)
        for field, default in self._defaults.items():
            if field not in result or result[field] is None:
                result[field] = default
        return result
