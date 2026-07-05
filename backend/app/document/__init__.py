"""Document processing package (v0.1: PDF + DOCX text extraction)."""
from app.document.parser import (  # noqa: F401
    DocumentParseError,
    ResumeText,
    extract_resume_text,
)
