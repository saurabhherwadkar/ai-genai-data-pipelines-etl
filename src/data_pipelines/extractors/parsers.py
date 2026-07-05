"""
Multi-format document parsers.

Normalizes diverse input sources (PDF, email, HTML, CSV) into a unified
Document model for downstream LLM extraction.
"""

import csv
import email
import io
import re
import uuid
from abc import ABC, abstractmethod
from email import policy
from pathlib import Path
from typing import Optional

from data_pipelines.models.schemas import Document, DocumentFormat
from data_pipelines.utils.logger import get_logger

logger = get_logger(__name__)


class DocumentParser(ABC):
    """Base class for document parsers."""

    @abstractmethod
    def parse(self, content: bytes | str, metadata: Optional[dict] = None) -> Document:
        """Parse raw content into a Document model."""
        ...

    @abstractmethod
    def supports(self, format_type: DocumentFormat) -> bool:
        """Check if this parser supports the given format."""
        ...

    def _generate_id(self) -> str:
        return str(uuid.uuid4())


class PDFParser(DocumentParser):
    """
    Parses PDF documents into plain text.

    Uses PyPDF2 for text extraction. Falls back to raw byte decoding
    if PyPDF2 is not available (for environments without the dependency).
    """

    def supports(self, format_type: DocumentFormat) -> bool:
        return format_type == DocumentFormat.PDF

    def parse(self, content: bytes | str, metadata: Optional[dict] = None) -> Document:
        """Extract text from PDF bytes."""
        text = self._extract_text(content)
        doc_metadata = metadata or {}
        doc_metadata["parser"] = "pdf"
        doc_metadata["pages"] = text.count("\f") + 1 if text else 0

        return Document(
            id=self._generate_id(),
            format=DocumentFormat.PDF,
            raw_content=text if text.strip() else "(empty PDF)",
            metadata=doc_metadata,
            size_bytes=len(content) if isinstance(content, bytes) else len(content.encode()),
        )

    def _extract_text(self, content: bytes | str) -> str:
        """Attempt PDF text extraction with PyPDF2, fallback to raw decode."""
        try:
            import PyPDF2

            if isinstance(content, str):
                content = content.encode("latin-1")
            reader = PyPDF2.PdfReader(io.BytesIO(content))
            pages = []
            for page in reader.pages:
                page_text = page.extract_text() or ""
                pages.append(page_text)
            return "\f".join(pages)
        except ImportError:
            logger.warning("PyPDF2 not installed, using fallback text extraction")
            raw = content if isinstance(content, str) else content.decode("utf-8", errors="replace")
            # Basic extraction of readable strings from PDF bytes
            return re.sub(r"[^\x20-\x7E\n\t]", " ", raw)
        except Exception as e:
            logger.error("PDF parsing failed", error=str(e))
            return ""


class EmailParser(DocumentParser):
    """
    Parses email messages (RFC 2822 / MIME) into plain text.

    Extracts headers, body text, and attachment metadata.
    """

    def supports(self, format_type: DocumentFormat) -> bool:
        return format_type == DocumentFormat.EMAIL

    def parse(self, content: bytes | str, metadata: Optional[dict] = None) -> Document:
        """Parse email content into a Document."""
        raw = content if isinstance(content, str) else content.decode("utf-8", errors="replace")
        msg = email.message_from_string(raw, policy=policy.default)

        # Extract headers
        headers = {
            "from": str(msg.get("From", "")),
            "to": str(msg.get("To", "")),
            "subject": str(msg.get("Subject", "")),
            "date": str(msg.get("Date", "")),
            "cc": str(msg.get("Cc", "")),
        }

        # Extract body
        body = self._extract_body(msg)

        # Build structured text representation
        text_parts = [
            f"From: {headers['from']}",
            f"To: {headers['to']}",
            f"Subject: {headers['subject']}",
            f"Date: {headers['date']}",
            "",
            body,
        ]

        # Attachment info
        attachments = self._extract_attachments(msg)
        if attachments:
            text_parts.append(f"\n[Attachments: {', '.join(attachments)}]")

        doc_metadata = metadata or {}
        doc_metadata.update(headers)
        doc_metadata["parser"] = "email"
        doc_metadata["attachment_count"] = len(attachments)

        return Document(
            id=self._generate_id(),
            format=DocumentFormat.EMAIL,
            raw_content="\n".join(text_parts),
            metadata=doc_metadata,
            size_bytes=len(raw.encode()),
        )

    def _extract_body(self, msg: email.message.Message) -> str:
        """Extract plain text body from email message."""
        body_parts = []
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        body_parts.append(payload.decode("utf-8", errors="replace"))
                elif content_type == "text/html" and not body_parts:
                    payload = part.get_payload(decode=True)
                    if payload:
                        html_text = payload.decode("utf-8", errors="replace")
                        body_parts.append(self._strip_html(html_text))
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body_parts.append(payload.decode("utf-8", errors="replace"))
            elif isinstance(msg.get_payload(), str):
                body_parts.append(msg.get_payload())
        return "\n".join(body_parts)

    def _extract_attachments(self, msg: email.message.Message) -> list[str]:
        """Extract attachment filenames."""
        attachments = []
        if msg.is_multipart():
            for part in msg.walk():
                filename = part.get_filename()
                if filename:
                    attachments.append(filename)
        return attachments

    def _strip_html(self, html: str) -> str:
        """Basic HTML tag removal."""
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        return text.strip()


class HTMLParser(DocumentParser):
    """
    Parses HTML documents into clean text.

    Removes scripts, styles, and tags while preserving meaningful structure.
    """

    def supports(self, format_type: DocumentFormat) -> bool:
        return format_type == DocumentFormat.HTML

    def parse(self, content: bytes | str, metadata: Optional[dict] = None) -> Document:
        """Parse HTML content into a Document."""
        raw = content if isinstance(content, str) else content.decode("utf-8", errors="replace")
        text = self._html_to_text(raw)
        title = self._extract_title(raw)

        doc_metadata = metadata or {}
        doc_metadata["parser"] = "html"
        doc_metadata["title"] = title
        doc_metadata["links_count"] = len(re.findall(r"<a\s", raw, re.IGNORECASE))

        return Document(
            id=self._generate_id(),
            format=DocumentFormat.HTML,
            raw_content=text if text.strip() else "(empty HTML)",
            metadata=doc_metadata,
            size_bytes=len(raw.encode()),
        )

    def _html_to_text(self, html: str) -> str:
        """Convert HTML to readable text."""
        # Remove script and style blocks
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        # Convert block elements to newlines
        text = re.sub(r"<(?:p|div|br|h[1-6]|li|tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
        # Remove remaining tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Decode common entities
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&nbsp;", " ").replace("&quot;", '"')
        # Normalize whitespace
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _extract_title(self, html: str) -> str:
        """Extract page title from HTML."""
        match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else ""


class CSVParser(DocumentParser):
    """
    Parses CSV files into a text representation suitable for LLM extraction.

    Converts tabular data into a structured text format with headers and rows.
    """

    def supports(self, format_type: DocumentFormat) -> bool:
        return format_type == DocumentFormat.CSV

    def parse(self, content: bytes | str, metadata: Optional[dict] = None) -> Document:
        """Parse CSV content into a Document."""
        raw = content if isinstance(content, str) else content.decode("utf-8", errors="replace")
        text, row_count, col_count = self._csv_to_text(raw)

        doc_metadata = metadata or {}
        doc_metadata["parser"] = "csv"
        doc_metadata["row_count"] = row_count
        doc_metadata["column_count"] = col_count

        return Document(
            id=self._generate_id(),
            format=DocumentFormat.CSV,
            raw_content=text if text.strip() else "(empty CSV)",
            metadata=doc_metadata,
            size_bytes=len(raw.encode()),
        )

    def _csv_to_text(self, raw: str) -> tuple[str, int, int]:
        """Convert CSV to structured text representation."""
        reader = csv.reader(io.StringIO(raw))
        rows = list(reader)

        if not rows:
            return "", 0, 0

        headers = rows[0]
        col_count = len(headers)
        data_rows = rows[1:]
        row_count = len(data_rows)

        # Build text representation
        lines = [f"Columns: {', '.join(headers)}", f"Total rows: {row_count}", ""]

        # Include up to 50 rows in text representation
        for i, row in enumerate(data_rows[:50]):
            row_parts = []
            for j, val in enumerate(row):
                if j < len(headers):
                    row_parts.append(f"{headers[j]}: {val}")
                else:
                    row_parts.append(f"col_{j}: {val}")
            lines.append(f"Row {i + 1}: {' | '.join(row_parts)}")

        if row_count > 50:
            lines.append(f"... ({row_count - 50} more rows)")

        return "\n".join(lines), row_count, col_count


def get_parser(format_type: DocumentFormat) -> DocumentParser:
    """Factory function to get the appropriate parser for a document format."""
    parsers: dict[DocumentFormat, DocumentParser] = {
        DocumentFormat.PDF: PDFParser(),
        DocumentFormat.EMAIL: EmailParser(),
        DocumentFormat.HTML: HTMLParser(),
        DocumentFormat.CSV: CSVParser(),
    }
    parser = parsers.get(format_type)
    if parser is None:
        raise ValueError(f"No parser available for format: {format_type}")
    return parser
