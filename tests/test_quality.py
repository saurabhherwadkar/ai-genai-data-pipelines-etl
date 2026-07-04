"""Tests for data quality validation."""
import pytest
from data_pipelines.quality.validator import QualityValidator

@pytest.fixture
def validator() -> QualityValidator:
    return QualityValidator()

class TestQualityValidator:
    def test_check_thresholds_passes(self, validator: QualityValidator) -> None:
        validation = {"completeness": 0.9, "accuracy": 0.95}
        assert validator.check_thresholds(validation) is True

    def test_check_thresholds_fails_completeness(self, validator: QualityValidator) -> None:
        validation = {"completeness": 0.5, "accuracy": 0.95}
        assert validator.check_thresholds(validation) is False

    def test_check_thresholds_fails_accuracy(self, validator: QualityValidator) -> None:
        validation = {"completeness": 0.9, "accuracy": 0.5}
        assert validator.check_thresholds(validation) is False
