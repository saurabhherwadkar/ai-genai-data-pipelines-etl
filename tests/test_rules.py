"""Tests for rule-based data quality validation."""

import pytest

from data_pipelines.quality.rules import RuleBasedValidator, RuleSeverity, ValidationRule


class TestRuleBasedValidator:
    """Tests for rule-based validation."""

    def test_required_field_present(self) -> None:
        validator = RuleBasedValidator()
        validator.add_required_field("name")
        result = validator.validate({"name": "Alice"})
        assert result["valid"] is True
        assert result["error_count"] == 0

    def test_required_field_missing(self) -> None:
        validator = RuleBasedValidator()
        validator.add_required_field("name")
        result = validator.validate({"age": 30})
        assert result["valid"] is False
        assert result["error_count"] == 1

    def test_required_field_empty_string(self) -> None:
        validator = RuleBasedValidator()
        validator.add_required_field("name")
        result = validator.validate({"name": "   "})
        assert result["valid"] is False

    def test_format_validation_email(self) -> None:
        validator = RuleBasedValidator()
        validator.add_format_rule("email", r"^[\w.-]+@[\w.-]+\.\w+$")

        assert validator.validate({"email": "user@example.com"})["valid"] is True
        assert validator.validate({"email": "not-an-email"})["valid"] is False

    def test_format_validation_skips_missing(self) -> None:
        validator = RuleBasedValidator()
        validator.add_format_rule("email", r"^[\w.-]+@[\w.-]+\.\w+$")
        result = validator.validate({"name": "Alice"})
        assert result["valid"] is True  # Missing field not checked

    def test_range_validation(self) -> None:
        validator = RuleBasedValidator()
        validator.add_range_rule("age", min_val=0, max_val=150)

        assert validator.validate({"age": 30})["valid"] is True
        assert validator.validate({"age": -1})["valid"] is False
        assert validator.validate({"age": 200})["valid"] is False

    def test_custom_validation(self) -> None:
        rule = ValidationRule(
            name="even_check",
            field="count",
            check_type="custom",
            custom_fn=lambda x: x is not None and x % 2 == 0,
            message="Count must be even",
        )
        validator = RuleBasedValidator(rules=[rule])

        assert validator.validate({"count": 4})["valid"] is True
        assert validator.validate({"count": 3})["valid"] is False

    def test_cross_field_validation(self) -> None:
        rule = ValidationRule(
            name="zip_required_if_city",
            field="city",
            check_type="cross_field",
            params={"dependent_field": "zip", "condition": "not_empty_if"},
            message="ZIP code required when city is provided",
        )
        validator = RuleBasedValidator(rules=[rule])

        assert validator.validate({"city": "NYC", "zip": "10001"})["valid"] is True
        assert validator.validate({"city": "NYC"})["valid"] is False

    def test_multiple_rules(self) -> None:
        validator = RuleBasedValidator()
        validator.add_required_field("name")
        validator.add_required_field("email")
        validator.add_format_rule("email", r"^[\w.-]+@[\w.-]+\.\w+$")
        validator.add_range_rule("age", min_val=0, max_val=150)

        data = {"name": "Alice", "email": "alice@example.com", "age": 30}
        assert validator.validate(data)["valid"] is True

        data = {"email": "bad", "age": -5}
        result = validator.validate(data)
        assert result["valid"] is False
        assert result["error_count"] >= 2

    def test_warning_severity(self) -> None:
        rule = ValidationRule(
            name="prefer_phone",
            field="phone",
            check_type="required",
            severity=RuleSeverity.WARNING,
            message="Phone number recommended",
        )
        validator = RuleBasedValidator(rules=[rule])
        result = validator.validate({"name": "Alice"})

        # Warnings don't make it invalid
        assert result["valid"] is True
        assert result["warning_count"] == 1

    def test_batch_validation(self) -> None:
        validator = RuleBasedValidator()
        validator.add_required_field("id")

        records = [{"id": "1"}, {"name": "no-id"}, {"id": "3"}]
        results = validator.validate_batch(records)
        assert results[0]["valid"] is True
        assert results[1]["valid"] is False
        assert results[2]["valid"] is True
