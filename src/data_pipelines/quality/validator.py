"""
Data quality validation using LLM judges.

Validates extracted data for completeness, accuracy, and consistency
using an LLM-as-judge approach.
"""

import anthropic
from data_pipelines.config.settings import get_settings


class QualityValidator:
    """Validates extracted data quality using LLM judges."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = anthropic.AsyncAnthropic(api_key=self._settings.anthropic_api_key, timeout=60)

    async def validate(self, extracted: dict, source_text: str) -> dict:
        """
        Validate extracted data against source text.

        Args:
            extracted: The extracted structured data.
            source_text: Original source text.

        Returns:
            Validation result with completeness and accuracy scores.
        """
        prompt = (
            f"Evaluate the quality of this data extraction.\n\n"
            f"Source text:\n{source_text[:2000]}\n\n"
            f"Extracted data:\n{extracted}\n\n"
            f"Score on:\n"
            f"1. COMPLETENESS (0-1): Are all relevant fields captured?\n"
            f"2. ACCURACY (0-1): Are extracted values correct?\n"
            f"3. ISSUES: List any problems found.\n\n"
            f"Format:\nCOMPLETENESS: 0.X\nACCURACY: 0.X\nISSUES: list"
        )

        response = await self._client.messages.create(
            model=self._settings.llm.model, max_tokens=512, temperature=0.1,
            messages=[{"role": "user", "content": prompt}],
        )

        return self._parse_validation(response.content[0].text if response.content else "")

    def check_thresholds(self, validation: dict) -> bool:
        """Check if validation scores meet configured thresholds."""
        completeness = validation.get("completeness", 0.0)
        accuracy = validation.get("accuracy", 0.0)
        return (
            completeness >= self._settings.quality.completeness_threshold
            and accuracy >= self._settings.quality.accuracy_threshold
        )

    def _parse_validation(self, content: str) -> dict:
        """Parse validation response."""
        result = {"completeness": 0.5, "accuracy": 0.5, "issues": [], "passed": False}
        for line in content.split("\n"):
            upper = line.strip().upper()
            if upper.startswith("COMPLETENESS:"):
                try:
                    result["completeness"] = float(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
            elif upper.startswith("ACCURACY:"):
                try:
                    result["accuracy"] = float(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
            elif upper.startswith("ISSUES:"):
                result["issues"] = [line.split(":", 1)[1].strip()]
        result["passed"] = self.check_thresholds(result)
        return result
