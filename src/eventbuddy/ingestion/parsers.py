"""File parsers for document ingestion (architecture §5.5, §7.2).

`parse(filename, content)` dispatches by extension to xlsx/docx/pdf. Each backend import is
**guarded**: a missing library (or a parse error) degrades that file to `kind="unsupported"`
with whatever was extracted — never an exception. The pipeline can then upsert the document
row with a `failed`/`parsed` status and skip structuring rather than crashing the webhook."""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO

from eventbuddy.common.logging import get_logger

log = get_logger("ingestion.parsers")


@dataclass
class ParsedDoc:
    # "xlsx" | "csv" | "docx" | "pdf" | "image" | "image_pdf" | "unsupported"
    kind: str
    filename: str
    text: str = ""
    rows: list[dict] = field(default_factory=list)  # tabular rows (xlsx/csv), header-keyed
    # Image kinds (Impl 5) carry the raw bytes + mime for a vision model to read; text kinds
    # leave these empty. `image_pdf` is a PDF that yielded ~no extractable text (likely scanned).
    raw_bytes: bytes | None = None
    mime: str = ""


# Image extensions → mime, for routing uploads to the vision model (Impl 5).
_IMAGE_MIMES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
}


def parse(filename: str, content: bytes) -> ParsedDoc:
    name = (filename or "").lower()
    if name.endswith(".xlsx"):
        return _parse_xlsx(filename, content)
    if name.endswith(".csv"):
        return _parse_csv(filename, content)
    if name.endswith(".tsv"):
        return _parse_csv(filename, content, delimiter="\t")
    if name.endswith(".docx"):
        return _parse_docx(filename, content)
    if name.endswith(".pdf"):
        return _parse_pdf(filename, content)
    if name.endswith((".txt", ".md", ".text")):
        return _parse_text(filename, content)
    for ext, mime in _IMAGE_MIMES.items():
        if name.endswith(ext):
            return ParsedDoc(kind="image", filename=filename, raw_bytes=content, mime=mime)
    return ParsedDoc(kind="unsupported", filename=filename)


def _parse_xlsx(filename: str, content: bytes) -> ParsedDoc:
    try:
        import openpyxl  # guarded — missing lib degrades this MIME type only
    except ImportError:
        log.warning("openpyxl not installed — .xlsx parsing unavailable")
        return ParsedDoc(kind="unsupported", filename=filename)
    try:
        wb = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        grid = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
    except Exception as e:  # noqa: BLE001
        log.warning(f"xlsx parse failed for {filename} ({type(e).__name__}: {e})")
        return ParsedDoc(kind="unsupported", filename=filename)
    if not grid:
        return ParsedDoc(kind="xlsx", filename=filename)
    headers = [str(h).strip() if h is not None else f"col{i}" for i, h in enumerate(grid[0])]
    rows: list[dict] = []
    for raw in grid[1:]:
        if all(c is None or str(c).strip() == "" for c in raw):
            continue
        rows.append({headers[i]: raw[i] for i in range(min(len(headers), len(raw)))})
    text = "\n".join(", ".join(f"{k}={v}" for k, v in r.items()) for r in rows)
    return ParsedDoc(kind="xlsx", filename=filename, text=text, rows=rows)


def _parse_csv(filename: str, content: bytes, delimiter: str | None = None) -> ParsedDoc:
    """Parse a `.csv`/`.tsv` into header-keyed rows (same shape as `_parse_xlsx`). The
    delimiter is sniffed (`,`/`\\t`/`;`) unless forced (`.tsv` → tab). Stdlib only; a decode or
    parse error degrades to `unsupported` — never raises (architecture §5.5 guarded parsers)."""
    import csv as _csv
    from io import StringIO

    text_data = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text_data = content.decode(enc)
            break
        except (UnicodeDecodeError, AttributeError):
            continue
    if text_data is None:
        log.warning(f"csv decode failed for {filename}")
        return ParsedDoc(kind="unsupported", filename=filename)
    try:
        if delimiter is None:
            try:
                delimiter = _csv.Sniffer().sniff(text_data[:4096], delimiters=",\t;").delimiter
            except _csv.Error:
                delimiter = ","  # single-column / odd files → treat as plain comma CSV
        grid = list(_csv.reader(StringIO(text_data), delimiter=delimiter))
    except Exception as e:  # noqa: BLE001
        log.warning(f"csv parse failed for {filename} ({type(e).__name__}: {e})")
        return ParsedDoc(kind="unsupported", filename=filename)
    if not grid:
        return ParsedDoc(kind="csv", filename=filename)
    headers = [h.strip() if isinstance(h, str) and h.strip() else f"col{i}"
               for i, h in enumerate(grid[0])]
    rows: list[dict] = []
    for raw in grid[1:]:
        if all((c is None or str(c).strip() == "") for c in raw):
            continue
        rows.append({headers[i]: raw[i] for i in range(min(len(headers), len(raw)))})
    text = "\n".join(", ".join(f"{k}={v}" for k, v in r.items()) for r in rows)
    return ParsedDoc(kind="csv", filename=filename, text=text, rows=rows)


def _parse_text(filename: str, content: bytes) -> ParsedDoc:
    """Plain text / Markdown (Impl 5). Decode with a few common encodings; a decode error
    degrades to `unsupported` rather than raising."""
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return ParsedDoc(kind="txt", filename=filename, text=content.decode(enc))
        except (UnicodeDecodeError, AttributeError):
            continue
    log.warning(f"text decode failed for {filename}")
    return ParsedDoc(kind="unsupported", filename=filename)


def render_pdf_first_page(content: bytes) -> tuple[bytes, str] | None:
    """Render a PDF's first page to a PNG for the vision model (Impl 5, image-PDF path).
    Guarded on PyMuPDF — if it's not installed (or rendering fails) returns None and the
    caller degrades to a clean 'couldn't render this PDF' message. Keeps the text-PDF path
    dependency-free."""
    try:
        import fitz  # PyMuPDF — optional dependency
    except ImportError:
        log.warning("PyMuPDF not installed — image-PDF rendering unavailable")
        return None
    try:
        doc = fitz.open(stream=content, filetype="pdf")
        if doc.page_count == 0:
            return None
        pix = doc.load_page(0).get_pixmap(dpi=150)
        png = pix.tobytes("png")
        doc.close()
    except Exception as e:  # noqa: BLE001
        log.warning(f"pdf render failed ({type(e).__name__}: {e})")
        return None
    return png, "image/png"


def _parse_docx(filename: str, content: bytes) -> ParsedDoc:
    try:
        import docx  # python-docx
    except ImportError:
        log.warning("python-docx not installed — .docx parsing unavailable")
        return ParsedDoc(kind="unsupported", filename=filename)
    try:
        doc = docx.Document(BytesIO(content))
        text = "\n".join(p.text for p in doc.paragraphs if p.text)
    except Exception as e:  # noqa: BLE001
        log.warning(f"docx parse failed for {filename} ({type(e).__name__}: {e})")
        return ParsedDoc(kind="unsupported", filename=filename)
    return ParsedDoc(kind="docx", filename=filename, text=text)


def _parse_pdf(filename: str, content: bytes) -> ParsedDoc:
    try:
        from pypdf import PdfReader
    except ImportError:
        log.warning("pypdf not installed — .pdf parsing unavailable")
        return ParsedDoc(kind="unsupported", filename=filename)
    try:
        reader = PdfReader(BytesIO(content))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as e:  # noqa: BLE001
        log.warning(f"pdf parse failed for {filename} ({type(e).__name__}: {e})")
        return ParsedDoc(kind="unsupported", filename=filename)
    # A PDF that yields ~no text is likely scanned/image-only — flag it so the vision path
    # can render + read it (Impl 5). Keep the original bytes for rendering.
    if not text.strip():
        return ParsedDoc(kind="image_pdf", filename=filename,
                         raw_bytes=content, mime="application/pdf")
    return ParsedDoc(kind="pdf", filename=filename, text=text)
