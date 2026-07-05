"""Tests for data transformation components."""

import pytest

from data_pipelines.transformers.cleaner import DataCleaner
from data_pipelines.transformers.normalizer import DataNormalizer
from data_pipelines.transformers.enricher import DataEnricher


class TestDataCleaner:
    """Tests for the data cleaning transformer."""

    def test_whitespace_normalization(self) -> None:
        cleaner = DataCleaner()
        data = {"name": "  John   Doe  ", "city": "\tNew York\t"}
        cleaned = cleaner.clean(data)
        assert cleaned["name"] == "John Doe"
        assert cleaned["city"] == "New York"

    def test_null_removal(self) -> None:
        cleaner = DataCleaner()
        data = {"name": "Alice", "empty": "", "none_val": None}
        cleaned = cleaner.clean(data)
        assert "name" in cleaned
        assert "empty" not in cleaned
        assert "none_val" not in cleaned

    def test_nested_dict_cleaning(self) -> None:
        cleaner = DataCleaner()
        data = {"person": {"name": "  Bob  ", "age": 30}}
        cleaned = cleaner.clean(data)
        assert cleaned["person"]["name"] == "Bob"

    def test_html_stripping_rule(self) -> None:
        cleaner = DataCleaner(rules={"description": {"strip_html": True}})
        data = {"description": "<b>Bold</b> text"}
        cleaned = cleaner.clean(data)
        assert cleaned["description"] == "Bold text"

    def test_date_format_rule(self) -> None:
        cleaner = DataCleaner(rules={"date": {"date_format": "%Y-%m-%d"}})
        data = {"date": "01/15/2024"}
        cleaned = cleaner.clean(data)
        assert cleaned["date"] == "2024-01-15"

    def test_batch_cleaning(self) -> None:
        cleaner = DataCleaner()
        records = [{"name": "  Alice  "}, {"name": "  Bob  "}]
        cleaned = cleaner.clean_batch(records)
        assert cleaned[0]["name"] == "Alice"
        assert cleaned[1]["name"] == "Bob"


class TestDataNormalizer:
    """Tests for the data normalization transformer."""

    def test_field_mapping(self) -> None:
        normalizer = DataNormalizer(field_mapping={"first_name": "name", "amt": "amount"})
        data = {"first_name": "Alice", "amt": "100"}
        result = normalizer.normalize(data)
        assert "name" in result
        assert "amount" in result
        assert "first_name" not in result

    def test_type_coercion_int(self) -> None:
        normalizer = DataNormalizer(type_coercions={"amount": "int"})
        data = {"amount": "1,234"}
        result = normalizer.normalize(data)
        assert result["amount"] == 1234

    def test_type_coercion_float(self) -> None:
        normalizer = DataNormalizer(type_coercions={"price": "float"})
        data = {"price": "$99.99"}
        result = normalizer.normalize(data)
        assert result["price"] == 99.99

    def test_type_coercion_bool(self) -> None:
        normalizer = DataNormalizer(type_coercions={"active": "bool"})
        data = {"active": "yes"}
        result = normalizer.normalize(data)
        assert result["active"] is True

    def test_type_coercion_list(self) -> None:
        normalizer = DataNormalizer(type_coercions={"tags": "list"})
        data = {"tags": "python, data, etl"}
        result = normalizer.normalize(data)
        assert result["tags"] == ["python", "data", "etl"]

    def test_defaults_injection(self) -> None:
        normalizer = DataNormalizer(defaults={"status": "active", "score": 0})
        data = {"name": "Test"}
        result = normalizer.normalize(data)
        assert result["status"] == "active"
        assert result["score"] == 0

    def test_custom_transform(self) -> None:
        normalizer = DataNormalizer(
            custom_transforms={"email": lambda x: x.lower().strip()}
        )
        data = {"email": "  USER@EXAMPLE.COM  "}
        result = normalizer.normalize(data)
        assert result["email"] == "user@example.com"

    def test_batch_normalization(self) -> None:
        normalizer = DataNormalizer(type_coercions={"age": "int"})
        records = [{"age": "30"}, {"age": "25"}]
        results = normalizer.normalize_batch(records)
        assert results[0]["age"] == 30
        assert results[1]["age"] == 25


class TestDataEnricher:
    """Tests for the data enrichment transformer."""

    def test_basic_enrichment(self) -> None:
        enricher = DataEnricher()
        data = {"name": "Alice", "email": "alice@example.com"}
        enriched = enricher.enrich(data)

        assert "_enrichment" in enriched
        assert "processed_at" in enriched["_enrichment"]
        assert "record_hash" in enriched["_enrichment"]
        assert enriched["_enrichment"]["field_count"] == 2

    def test_completeness_computation(self) -> None:
        enricher = DataEnricher()
        data = {"a": "value", "b": None, "c": "value", "d": ""}
        enriched = enricher.enrich(data)

        # 2 out of 4 fields are filled
        assert enriched["_enrichment"]["completeness"] == 0.5

    def test_computed_fields(self) -> None:
        enricher = DataEnricher(
            computed_fields={
                "full_name": lambda d: f"{d.get('first', '')} {d.get('last', '')}".strip()
            }
        )
        data = {"first": "John", "last": "Doe"}
        enriched = enricher.enrich(data)
        assert enriched["full_name"] == "John Doe"

    def test_conditional_enrichment_rules(self) -> None:
        enricher = DataEnricher(
            enrichment_rules=[
                {"if_field": "status", "equals": "premium", "then_set": {"tier": "gold"}}
            ]
        )
        data = {"status": "premium", "name": "VIP"}
        enriched = enricher.enrich(data)
        assert enriched["tier"] == "gold"

    def test_source_metadata(self) -> None:
        enricher = DataEnricher()
        data = {"name": "Test"}
        enriched = enricher.enrich(data, source_metadata={"parser": "html", "ingested_at": "2024-01-01"})
        assert enriched["_source"]["format"] == "html"

    def test_batch_enrichment(self) -> None:
        enricher = DataEnricher()
        records = [{"a": "1"}, {"b": "2"}]
        results = enricher.enrich_batch(records)
        assert len(results) == 2
        assert all("_enrichment" in r for r in results)
