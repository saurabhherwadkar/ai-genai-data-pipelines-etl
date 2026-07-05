"""Tests for data loaders."""

import json
import tempfile
from pathlib import Path

import pytest

from data_pipelines.loaders.json_loader import JSONFileLoader


class TestJSONFileLoader:
    """Tests for the JSON file loader."""

    @pytest.fixture
    def tmp_dir(self, tmp_path: Path) -> str:
        return str(tmp_path / "output")

    @pytest.mark.asyncio
    async def test_individual_mode_creates_file(self, tmp_dir: str) -> None:
        loader = JSONFileLoader(output_dir=tmp_dir, mode="individual")
        data = {"name": "Alice", "age": 30}
        result = await loader.load(data, "doc-001")

        assert result.success is True
        assert result.records_written == 1

        filepath = Path(tmp_dir) / "doc-001.json"
        assert filepath.exists()

        saved = json.loads(filepath.read_text())
        assert saved["document_id"] == "doc-001"
        assert saved["data"]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_batch_mode_appends_jsonl(self, tmp_dir: str) -> None:
        loader = JSONFileLoader(output_dir=tmp_dir, mode="batch")
        await loader.load({"name": "Alice"}, "doc-001")
        await loader.load({"name": "Bob"}, "doc-002")

        filepath = Path(tmp_dir) / "extractions.jsonl"
        assert filepath.exists()

        lines = filepath.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["document_id"] == "doc-001"
        assert json.loads(lines[1])["document_id"] == "doc-002"

    @pytest.mark.asyncio
    async def test_batch_load(self, tmp_dir: str) -> None:
        loader = JSONFileLoader(output_dir=tmp_dir, mode="individual")
        records = [{"a": 1}, {"b": 2}, {"c": 3}]
        ids = ["d1", "d2", "d3"]
        results = await loader.load_batch(records, ids)

        assert len(results) == 3
        assert all(r.success for r in results)

    @pytest.mark.asyncio
    async def test_health_check(self, tmp_dir: str) -> None:
        loader = JSONFileLoader(output_dir=tmp_dir)
        assert await loader.health_check() is True
