from io import BytesIO

from eventbuddy.ingestion.parsers import parse


def _xlsx_bytes(rows):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _docx_bytes(paragraphs):
    import docx

    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    buf = BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_parse_xlsx_headers_to_rows():
    content = _xlsx_bytes([["Email", "Rating", "Comment"],
                           ["a@x.com", 5, "great"],
                           ["b@x.com", 2, "long"]])
    doc = parse("responses.xlsx", content)
    assert doc.kind == "xlsx"
    assert len(doc.rows) == 2
    assert doc.rows[0] == {"Email": "a@x.com", "Rating": 5, "Comment": "great"}
    assert "a@x.com" in doc.text


def test_parse_xlsx_skips_blank_rows():
    content = _xlsx_bytes([["A", "B"], [None, None], ["x", "y"]])
    doc = parse("f.xlsx", content)
    assert len(doc.rows) == 1


def test_parse_docx_extracts_text():
    doc = parse("plan.docx", _docx_bytes(["Hello world", "Second line"]))
    assert doc.kind == "docx"
    assert "Hello world" in doc.text
    assert "Second line" in doc.text


def test_parse_unsupported_extension():
    assert parse("image.png", b"\x89PNG").kind == "unsupported"


def test_parse_pdf_garbage_degrades_to_unsupported():
    # Not a real PDF — the guarded parser must degrade, not raise.
    assert parse("broken.pdf", b"not a pdf").kind == "unsupported"
