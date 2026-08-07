"""Tests for document text extraction."""

import pytest

from app.documents import (
    DocumentParseError,
    UnsupportedDocumentError,
    extension_of,
    extract_text,
    is_supported,
)
from tests.helpers import make_docx, make_empty_pdf, make_pdf


# --- Type detection --------------------------------------------------------


def test_extension_detection():
    assert extension_of("notes.PDF") == ".pdf"
    assert extension_of("archive.tar.gz") == ".gz"
    assert extension_of("noextension") == ""


def test_supported_types():
    assert is_supported("a.pdf") and is_supported("b.DOCX") and is_supported("c.md")
    assert not is_supported("d.doc") and not is_supported("e.png")


def test_unsupported_type_rejected_with_helpful_message():
    with pytest.raises(UnsupportedDocumentError) as exc:
        extract_text("photo.png", b"data")
    assert ".pdf" in str(exc.value), "error should list supported types"


def test_legacy_doc_rejected():
    # .doc is a different binary format python-docx cannot read.
    with pytest.raises(UnsupportedDocumentError):
        extract_text("old.doc", b"data")


def test_empty_file_rejected():
    with pytest.raises(DocumentParseError):
        extract_text("empty.txt", b"")


# --- Plain text ------------------------------------------------------------


def test_txt_extraction():
    assert extract_text("a.txt", b"Hello world.") == "Hello world."


def test_markdown_is_treated_as_text():
    assert "Heading" in extract_text("a.md", b"# Heading\n\nBody.")


def test_non_utf8_text_is_decoded():
    # latin-1 encoded accents must not raise.
    result = extract_text("a.txt", "café résumé".encode("latin-1"))
    assert "caf" in result


def test_utf16_text_is_decoded():
    assert "wide" in extract_text("a.txt", "wide chars".encode("utf-16"))


# --- PDF -------------------------------------------------------------------


def test_pdf_extraction():
    data = make_pdf(["First line of the document.", "Second line follows."])
    text = extract_text("notes.pdf", data)

    assert "First line of the document." in text
    assert "Second line follows." in text


def test_scanned_pdf_yields_empty_text():
    # A valid PDF with no text layer must return "" rather than raise, so the
    # route can give a specific "no readable text" message.
    assert extract_text("scan.pdf", make_empty_pdf()).strip() == ""


def test_corrupt_pdf_raises_parse_error():
    with pytest.raises(DocumentParseError):
        extract_text("broken.pdf", b"%PDF-1.4 this is not really a pdf")


# --- DOCX ------------------------------------------------------------------


def test_docx_extraction():
    data = make_docx(["Opening paragraph.", "Closing paragraph."])
    text = extract_text("notes.docx", data)

    assert "Opening paragraph." in text
    assert "Closing paragraph." in text


def test_docx_skips_blank_paragraphs():
    text = extract_text("a.docx", make_docx(["Real content.", "", "   ", "More."]))
    assert "\n\n\n" not in text


def test_docx_includes_table_content():
    data = make_docx(["Intro."], table_rows=[["Name", "Value"], ["speed", "fast"]])
    text = extract_text("a.docx", data)

    assert "Name | Value" in text
    assert "speed | fast" in text


def test_corrupt_docx_raises_parse_error():
    with pytest.raises(DocumentParseError) as exc:
        extract_text("broken.docx", b"not a zip archive at all")
    assert ".doc" in str(exc.value), "should hint about legacy .doc files"
