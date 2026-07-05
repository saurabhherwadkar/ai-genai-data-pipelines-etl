"""
Rule-based data quality validation.

Complements LLM-as-judge with deterministic, configurable validation rules
that can check extracted data without LLM calls. Useful for:
- Required field presence
- Format validation (email, phone, date patterns)
- Range checks (numeric bounds)
- Cross-field consistency
- Custom business logic
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from data_pipelines.utils.logger import get_logger

logger = get_logger(__name__)


class RuleSeverity(str, Enum):
    """Severity levels for validation rule failures."""

    ERROR = "error"  # Blocks loading
    WARNING = "warning"  # Flags for review
    INFO = "info"  # Informational only


@dataclass
class ValidationRule:
    """
    A single validation rule definition.

    Rules are composable: combine multiple rules to build
    complex validation logic without LLM calls.
    """

    name: str
    field: str
    check_type: str  # required, format, range, custom, cross_field
    severity: RuleSeverity = RuleSeverity.ERROR
    params: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    custom_fn: Optional[Callable[[Any], bool]] = None


@dataclass
class RuleViolation:
    """Records a rule violation found during validation."""

    rule_name: str
    field: str
    severity: RuleSeverity
    message: str
    actual_value: Any = None


class RuleBasedValidator:
    """
    Validates extracted data against a set of configurable rules.

    Provides fast, deterministic validation without LLM calls.
    Use in combination with QualityValidator for comprehensive
    quality assessment.
    """

    def __init__(self, rules: list[ValidationRule] | None = None) -> None:
        """
        Initialize with a set of validation rules.

        Args:
            rules: List of ValidationRule definitions.
        """
        self._rules = rules or []

    def add_rule(self, rule: ValidationRule) -> None:
        """Add a validation rule."""
        self._rules.append(rule)

    def add_required_field(self, field: str, message: str = "") -> None:
        """Convenience: add a required field rule."""
        self._rules.append(
            ValidationRule(
                name=f"required_{field}",
                field=field,
                check_type="required",
                message=message or f"Field '{field}' is required",
            )
        )

    def add_format_rule(self, field: str, pattern: str, message: str = "") -> None:
        """Convenience: add a regex format validation rule."""
        self._rules.append(
            ValidationRule(
                name=f"format_{field}",
                field=field,
                check_type="format",
                params={"pattern": pattern},
                message=message or f"Field '{field}' does not match expected format",
            )
        )

    def add_range_rule(
        self, field: str, min_val: float | None = None, max_val: float | None = None, message: str = ""
    ) -> None:
        """Convenience: add a numeric range validation rule."""
        self._rules.append(
            ValidationRule(
                name=f"range_{field}",
                field=field,
                check_type="range",
                params={"min": min_val, "max": max_val},
                message=message or f"Field '{field}' is out of expected range",
            )
        )

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Validate data against all configured rules.

        Args:
            data: Extracted data dictionary to validate.

        Returns:
            Dict with 'valid', 'violations', 'error_count', 'warning_count' keys.
        """
        violations: list[RuleViolation] = []

        for rule in self._rules:
            violation = self._check_rule(rule, data)
            if violation:
                violations.append(violation)

        errors = [v for v in violations if v.severity == RuleSeverity.ERROR]
        warnings = [v for v in violations if v.severity == RuleSeverity.WARNING]

        return {
            "valid": len(errors) == 0,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "violations": [
                {
                    "rule": v.rule_name,
                    "field": v.field,
                    "severity": v.severity.value,
                    "message": v.message,
                    "actual_value": v.actual_value,
                }
                for v in violations
            ],
        }

    def validate_batch(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Validate a batch of records."""
        return [self.validate(record) for record in records]

    def _check_rule(self, rule: ValidationRule, data: dict[str, Any]) -> Optional[RuleViolation]:
        """Check a single rule against the data."""
        checkers = {
            "required": self._check_required,
            "format": self._check_format,
            "range": self._check_range,
            "custom": self._check_custom,
            "cross_field": self._check_cross_field,
        }
        checker = checkers.get(rule.check_type)
        if checker is None:
            logger.warning("Unknown rule check type", check_type=rule.check_type)
            return None
        return checker(rule, data)

    def _check_required(self, rule: ValidationRule, data: dict[str, Any]) -> Optional[RuleViolation]:
        """Check that a required field is present and non-empty."""
        value = data.get(rule.field)
        if value is None or (isinstance(value, str) and not value.strip()):
            return RuleViolation(
                rule_name=rule.name,
                field=rule.field,
                severity=rule.severity,
                message=rule.message,
                actual_value=value,
            )
        return None

    def _check_format(self, rule: ValidationRule, data: dict[str, Any]) -> Optional[RuleViolation]:
        """Check that a field matches a regex pattern."""
        value = data.get(rule.field)
        if value is None:
            return None  # Format check only applies to present fields

        pattern = rule.params.get("pattern", "")
        if not re.match(pattern, str(value)):
            return RuleViolation(
                rule_name=rule.name,
                field=rule.field,
                severity=rule.severity,
                message=rule.message,
                actual_value=value,
            )
        return None

    def _check_range(self, rule: ValidationRule, data: dict[str, Any]) -> Optional[RuleViolation]:
        """Check that a numeric field is within bounds."""
        value = data.get(rule.field)
        if value is None:
            return None

        try:
            num_value = float(value)
        except (TypeError, ValueError):
            return RuleViolation(
                rule_name=rule.name,
                field=rule.field,
                severity=rule.severity,
                message=f"Field '{rule.field}' is not numeric",
                actual_value=value,
            )

        min_val = rule.params.get("min")
        max_val = rule.params.get("max")

        if min_val is not None and num_value < min_val:
            return RuleViolation(
                rule_name=rule.name,
                field=rule.field,
                severity=rule.severity,
                message=rule.message or f"Value {num_value} below minimum {min_val}",
                actual_value=value,
            )
        if max_val is not None and num_value > max_val:
            return RuleViolation(
                rule_name=rule.name,
                field=rule.field,
                severity=rule.severity,
                message=rule.message or f"Value {num_value} above maximum {max_val}",
                actual_value=value,
            )
        return None

    def _check_custom(self, rule: ValidationRule, data: dict[str, Any]) -> Optional[RuleViolation]:
        """Check using a custom validation function."""
        if not rule.custom_fn:
            return None

        value = data.get(rule.field)
        try:
            if not rule.custom_fn(value):
                return RuleViolation(
                    rule_name=rule.name,
                    field=rule.field,
                    severity=rule.severity,
                    message=rule.message,
                    actual_value=value,
                )
        except Exception as e:
            return RuleViolation(
                rule_name=rule.name,
                field=rule.field,
                severity=RuleSeverity.WARNING,
                message=f"Custom validation error: {str(e)}",
                actual_value=value,
            )
        return None

    def _check_cross_field(self, rule: ValidationRule, data: dict[str, Any]) -> Optional[RuleViolation]:
        """Check cross-field consistency."""
        dependent_field = rule.params.get("dependent_field")
        condition = rule.params.get("condition")  # "equals", "greater_than", "not_empty_if"

        if not dependent_field or not condition:
            return None

        source_value = data.get(rule.field)
        dependent_value = data.get(dependent_field)

        if condition == "equals" and source_value != dependent_value:
            return RuleViolation(
                rule_name=rule.name,
                field=rule.field,
                severity=rule.severity,
                message=rule.message or f"'{rule.field}' must equal '{dependent_field}'",
                actual_value=f"{source_value} vs {dependent_value}",
            )
        elif condition == "not_empty_if" and source_value and not dependent_value:
            return RuleViolation(
                rule_name=rule.name,
                field=rule.field,
                severity=rule.severity,
                message=rule.message or f"'{dependent_field}' required when '{rule.field}' is set",
                actual_value=dependent_value,
            )
        return None
