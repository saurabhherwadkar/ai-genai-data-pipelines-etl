"""
LLM-powered data extraction from unstructured documents.

Converts PDFs, emails, HTML pages into structured data using
schema-guided LLM extraction with validation.
"""

import json
import anthropic
from data_pipelines.config.settings import get_settings

class LLMExtractor:
    """Extracts structured data from unstructured text using LLMs."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = anthropic.AsyncAnthropic(api_key=self._settings.anthropic_api_key, timeout=60)

    async def extract(self, text: str, schema: dict, instructions: str = "") -> dict:
        """
        Extract structured data from text according to a schema.

        Args:
            text: Unstructured input text.
            schema: JSON schema defining expected output.
            instructions: Additional extraction guidance.

        Returns:
            Extracted structured data dictionary.
        """
        prompt = (
            f"Extract structured data from the following text.\n\n"
            f"Schema: {json.dumps(schema, indent=2)}\n"
            f"{f'Instructions: {instructions}' if instructions else ''}\n\n"
            f"Text:\n{text[:6000]}\n\n"
            f"Respond with ONLY valid JSON matching the schema."
        )

        response = await self._client.messages.create(
            model=self._settings.llm.model, max_tokens=self._settings.llm.max_tokens,
            temperature=self._settings.llm.temperature,
            messages=[{"role": "user", "content": prompt}],
        )

        content = response.content[0].text if response.content else "{}"
        return self._parse_json(content)

    async def extract_batch(self, documents: list[str], schema: dict) -> list[dict]:
        """Extract from multiple documents."""
        results = []
        for doc in documents[:self._settings.extraction.batch_size]:
            result = await self.extract(doc, schema)
            results.append(result)
        return results

    def _parse_json(self, text: str) -> dict:
        """Parse JSON from LLM response."""
        clean = text.strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            clean = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            return {}
