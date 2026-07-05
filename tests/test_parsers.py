"""Tests for document parsers."""

import pytest

from data_pipelines.extractors.parsers import (
    CSVParser,
    EmailParser,
    HTMLParser,
    PDFParser,
    get_parser,
)
from data_pipelines.models.schemas import DocumentFormat


class TestHTMLParser:
    """Tests for HTML document parsing."""

    def test_basic_html_parsing(self) -> None:
        html = "<html><head><title>Test</title></head><body><p>Hello world</p></body></html>"
        parser = HTMLParser()
        doc = parser.parse(html)

        assert doc.format == DocumentFormat.HTML
        assert "Hello world" in doc.raw_content
        assert doc.metadata["title"] == "Test"
        assert doc.metadata["parser"] == "html"

    def test_strips_scripts_and_styles(self) -> None:
        html = """
        <html><body>
            <script>var x = 1;</script>
            <style>.foo { color: red; }</style>
            <p>Visible content</p>
        </body></html>
        """
        parser = HTMLParser()
        doc = parser.parse(html)

        assert "var x = 1" not in doc.raw_content
        assert "color: red" not in doc.raw_content
        assert "Visible content" in doc.raw_content

    def test_preserves_block_structure(self) -> None:
        html = "<div>First</div><div>Second</div><p>Third</p>"
        parser = HTMLParser()
        doc = parser.parse(html)

        assert "First" in doc.raw_content
        assert "Second" in doc.raw_content
        assert "Third" in doc.raw_content

    def test_empty_html(self) -> None:
        parser = HTMLParser()
        doc = parser.parse("<html><body></body></html>")
        assert doc.raw_content == "(empty HTML)"


class TestCSVParser:
    """Tests for CSV document parsing."""

    def test_basic_csv(self) -> None:
        csv_content = "name,age,city\nAlice,30,NYC\nBob,25,LA"
        parser = CSVParser()
        doc = parser.parse(csv_content)

        assert doc.format == DocumentFormat.CSV
        assert "name" in doc.raw_content
        assert "Alice" in doc.raw_content
        assert doc.metadata["row_count"] == 2
        assert doc.metadata["column_count"] == 3

    def test_large_csv_truncation(self) -> None:
        lines = ["col1,col2"] + [f"val{i},data{i}" for i in range(100)]
        csv_content = "\n".join(lines)
        parser = CSVParser()
        doc = parser.parse(csv_content)

        assert "50 more rows" in doc.raw_content
        assert doc.metadata["row_count"] == 100

    def test_empty_csv(self) -> None:
        parser = CSVParser()
        doc = parser.parse("")
        assert doc.raw_content == "(empty CSV)"


class TestEmailParser:
    """Tests for email document parsing."""

    def test_basic_email(self) -> None:
        email_content = (
            "From: sender@example.com\r\n"
            "To: recipient@example.com\r\n"
            "Subject: Test Email\r\n"
            "Date: Mon, 1 Jan 2024 12:00:00 +0000\r\n"
            "\r\n"
            "Hello, this is a test email body."
        )
        parser = EmailParser()
        doc = parser.parse(email_content)

        assert doc.format == DocumentFormat.EMAIL
        assert "sender@example.com" in doc.raw_content
        assert "Test Email" in doc.raw_content
        assert "test email body" in doc.raw_content
        assert doc.metadata["subject"] == "Test Email"

    def test_email_with_headers(self) -> None:
        email_content = (
            "From: a@b.com\r\nTo: c@d.com\r\nSubject: Hi\r\nCc: e@f.com\r\n\r\nBody"
        )
        parser = EmailParser()
        doc = parser.parse(email_content)

        assert doc.metadata["from"] == "a@b.com"
        assert doc.metadata["to"] == "c@d.com"


class TestPDFParser:
    """Tests for PDF document parsing."""

    def test_supports_pdf_format(self) -> None:
        parser = PDFParser()
        assert parser.supports(DocumentFormat.PDF) is True
        assert parser.supports(DocumentFormat.HTML) is False

    def test_fallback_parsing(self) -> None:
        # Without PyPDF2, it should fallback to basic text extraction
        parser = PDFParser()
        doc = parser.parse("Some plain text that looks like a PDF")
        assert doc.format == DocumentFormat.PDF


class TestParserFactory:
    """Tests for the parser factory function."""

    def test_get_html_parser(self) -> None:
        parser = get_parser(DocumentFormat.HTML)
        assert isinstance(parser, HTMLParser)

    def test_get_csv_parser(self) -> None:
        parser = get_parser(DocumentFormat.CSV)
        assert isinstance(parser, CSVParser)

    def test_get_email_parser(self) -> None:
        parser = get_parser(DocumentFormat.EMAIL)
        assert isinstance(parser, EmailParser)

    def test_unsupported_format(self) -> None:
        with pytest.raises(ValueError, match="No parser available"):
            get_parser(DocumentFormat.TEXT)
