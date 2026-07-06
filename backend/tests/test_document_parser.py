"""Smoke tests for the resume text-extraction layer.

These tests exercise the pure-python `document.parser` module — no LLM,
no DB, no network. They validate format detection, unsupported-format
rejection, and basic text extraction from a synthetic docx / txt payload.

PDF generation requires a heavier dep (reportlab) so we only exercise
the "invalid PDF" rejection path here; end-to-end PDF parsing is covered
in manual smoke tests via curl.
"""
from __future__ import annotations

import io

import pytest
from docx import Document as DocxDocument

from app.document.parser import (
    DocumentParseError,
    extract_resume_text,
)


def _build_docx_bytes(paragraphs: list[str]) -> bytes:
    doc = DocxDocument()
    for p in paragraphs:
        doc.add_paragraph(p)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def test_extract_txt_utf8() -> None:
    data = "张三\n后端工程师\n5 年经验".encode()
    result = extract_resume_text(data=data, filename="cv.txt", content_type="text/plain")
    assert result.format == "txt"
    assert "张三" in result.text
    assert "5 年经验" in result.text


def test_extract_txt_gb18030_fallback() -> None:
    # Simulate a legacy Windows Chinese resume export
    data = "李四 高级工程师".encode("gb18030")
    result = extract_resume_text(data=data, filename="cv.txt", content_type=None)
    assert "李四" in result.text


def test_extract_docx() -> None:
    data = _build_docx_bytes(["张三", "邮箱: zhang@example.com", "  ", "5 年后端经验"])
    result = extract_resume_text(
        data=data,
        filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert result.format == "docx"
    assert "张三" in result.text
    assert "zhang@example.com" in result.text


def test_extract_rejects_empty_file() -> None:
    with pytest.raises(DocumentParseError, match="empty_file"):
        extract_resume_text(data=b"", filename="x.pdf", content_type="application/pdf")


def test_extract_rejects_unknown_format() -> None:
    with pytest.raises(DocumentParseError, match="unsupported_format"):
        extract_resume_text(
            data=b"junk",
            filename="resume.rtf",
            content_type="application/rtf",
        )


def test_extract_rejects_invalid_pdf() -> None:
    with pytest.raises(DocumentParseError, match="pdf_read_failed"):
        extract_resume_text(
            data=b"not-a-real-pdf",
            filename="fake.pdf",
            content_type="application/pdf",
        )
