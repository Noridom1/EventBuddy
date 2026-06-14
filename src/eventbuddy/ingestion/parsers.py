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
    kind: str                            # "xlsx" | "csv" | "docx" | "pdf" | "unsupported"
    filename: str
    text: str = ""
    rows: list[dict] = field(default_factory=list)  # tabular rows (xlsx/csv), header-keyed


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
    return ParsedDoc(kind="pdf", filename=filename, text=text)
