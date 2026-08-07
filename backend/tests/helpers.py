"""Builders for real document files used in tests.

These produce genuine PDF/DOCX bytes rather than mocks, so the parsers are
exercised the same way they will be in production.
"""

import io


def make_pdf(lines: list[str]) -> bytes:
    """Build a minimal single-page PDF containing `lines` as text."""
    content = (
        "BT /F1 12 Tf 72 720 Td 14 TL\n"
        + "\n".join(f"({line}) Tj T*" for line in lines)
        + "\nET"
    )
    objects = [
        "<</Type/Catalog/Pages 2 0 R>>",
        "<</Type/Pages/Kids[3 0 R]/Count 1>>",
        "<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        "/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        f"<</Length {len(content)}>>\nstream\n{content}\nendstream",
        "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]

    out = "%PDF-1.4\n"
    offsets = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n{obj}\nendobj\n"

    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    out += "".join(f"{offset:010d} 00000 n \n" for offset in offsets)
    out += (
        f"trailer\n<</Size {len(objects) + 1}/Root 1 0 R>>\n"
        f"startxref\n{xref_offset}\n%%EOF"
    )
    return out.encode("latin-1")


def make_empty_pdf() -> bytes:
    """A structurally valid PDF with no text layer, like a scan."""
    return make_pdf([])


def make_docx(paragraphs: list[str], table_rows: list[list[str]] | None = None) -> bytes:
    """Build a real .docx file with the given paragraphs and optional table."""
    import docx

    document = docx.Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)

    if table_rows:
        table = document.add_table(rows=len(table_rows), cols=len(table_rows[0]))
        for row_index, row in enumerate(table_rows):
            for cell_index, value in enumerate(row):
                table.cell(row_index, cell_index).text = value

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
