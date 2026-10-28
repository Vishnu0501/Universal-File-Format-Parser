import io
import json
from typing import Iterator
from parser.record import Record, RecordType, Severity


# ── XLSX: truncated file ───────────────────────────────────────────────────────

def recover_xlsx(data: bytes) -> Iterator[Record]:
    try:
        import openpyxl
        from openpyxl.utils.exceptions import InvalidFileException
    except ImportError:
        yield Record(type=RecordType.ERROR, format="xlsx", reason="openpyxl not installed")
        return

    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except InvalidFileException as e:
        yield Record(type=RecordType.ERROR, format="xlsx", reason=f"XLSX unreadable: {e}", offset=0)
        return
    except Exception as e:
        yield Record(type=RecordType.ERROR, format="xlsx", reason=f"XLSX open failed: {e}", offset=0)
        return

    try:
        sheet_names = wb.sheetnames
    except Exception as e:
        yield Record(type=RecordType.ERROR, format="xlsx", reason=f"Could not list sheets: {e}")
        return

    for sheet_index, sheet_name in enumerate(sheet_names):
        grid = []
        row_num = 0
        truncated = False

        try:
            ws = wb[sheet_name]
            for row in ws.iter_rows():
                try:
                    grid.append([_safe_cell(cell) for cell in row])
                    row_num += 1
                except Exception as e:
                    yield Record(
                        type=RecordType.ERROR,
                        format="xlsx",
                        reason=f"Sheet '{sheet_name}' row {row_num + 1} corrupt: {e}",
                        metadata={"sheet": sheet_name, "row": row_num + 1},
                    )
                    truncated = True
                    break

        except Exception as e:
            yield Record(
                type=RecordType.ERROR,
                format="xlsx",
                reason=f"Sheet '{sheet_name}' read failed mid-stream: {e}",
                metadata={"sheet": sheet_name},
            )
            truncated = True

        if grid:
            yield Record(
                type=RecordType.DATA,
                format="xlsx",
                content=grid,
                metadata={
                    "sheet": sheet_name,
                    "sheet_index": sheet_index,
                    "rows": len(grid),
                    "cols": len(grid[0]) if grid else 0,
                    "truncated": truncated,
                },
            )

        if truncated:
            yield Record(
                type=RecordType.WARNING,
                format="xlsx",
                reason=f"Sheet '{sheet_name}' was truncated; partial data recovered",
                severity=Severity.MEDIUM,
                metadata={"sheet": sheet_name, "recovered_rows": row_num},
            )

    try:
        wb.close()
    except Exception:
        pass


def _safe_cell(cell) -> object:
    val = cell.value
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val


# ── PDF: damaged xref table ───────────────────────────────────────────────────

def recover_pdf(data: bytes) -> Iterator[Record]:
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTTextContainer, LAParams
        from pdfminer.pdfdocument import PDFEncryptionError
        from pdfminer.pdfparser import PDFSyntaxError
    except ImportError:
        yield Record(type=RecordType.ERROR, format="pdf", reason="pdfminer.six not installed")
        return

    page_num = 0
    recovered = 0
    try:
        for page_num, page_layout in enumerate(
            extract_pages(io.BytesIO(data), laparams=LAParams()), start=1
        ):
            try:
                texts = [
                    el.get_text().strip()
                    for el in page_layout
                    if isinstance(el, LTTextContainer) and el.get_text().strip()
                ]
                yield Record(
                    type=RecordType.DATA,
                    format="pdf",
                    content="\n".join(texts),
                    metadata={"page": page_num},
                )
                recovered += 1
            except Exception as e:
                yield Record(
                    type=RecordType.ERROR,
                    format="pdf",
                    reason=f"Page {page_num} corrupt: {e}",
                    metadata={"page": page_num},
                )

    except PDFEncryptionError:
        yield Record(
            type=RecordType.WARNING,
            format="pdf",
            reason="PDF is encrypted; cannot recover text",
            severity=Severity.MEDIUM,
        )
    except PDFSyntaxError as e:
        yield Record(
            type=RecordType.ERROR,
            format="pdf",
            reason=f"PDF xref/syntax damaged: {e}; recovered {recovered} pages before failure",
            metadata={"recovered_pages": recovered, "failed_at_page": page_num + 1},
        )
    except Exception as e:
        yield Record(
            type=RecordType.ERROR,
            format="pdf",
            reason=f"PDF recovery failed at page {page_num + 1}: {e}",
            metadata={"recovered_pages": recovered},
        )

    if recovered > 0 and page_num > recovered:
        yield Record(
            type=RecordType.WARNING,
            format="pdf",
            reason=f"PDF partially recovered: {recovered} of ~{page_num} pages extracted",
            severity=Severity.MEDIUM,
            metadata={"recovered_pages": recovered},
        )


# ── JSON: mid-stream corruption ───────────────────────────────────────────────

def recover_json(data: bytes) -> Iterator[Record]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        yield Record(
            type=RecordType.ERROR,
            format="json",
            reason=f"Cannot decode bytes as UTF-8 at offset {e.start}: {e.reason}",
            offset=e.start,
        )
        return

    decoder = json.JSONDecoder()
    pos = 0
    n = len(text)
    recovered = 0

    while pos < n:
        while pos < n and text[pos] in " \t\n\r":
            pos += 1
        if pos >= n:
            break

        try:
            obj, end_pos = decoder.raw_decode(text, pos)
            yield Record(
                type=RecordType.DATA,
                format="json",
                content=obj,
                offset=_char_to_byte_offset(text, pos, data),
                metadata={"object_index": recovered},
            )
            recovered += 1
            pos = end_pos
        except json.JSONDecodeError as e:
            byte_offset = _char_to_byte_offset(text, pos + e.pos, data)
            yield Record(
                type=RecordType.ERROR,
                format="json",
                reason=f"Corrupt JSON at char {pos + e.pos}: {e.msg}",
                offset=byte_offset,
            )
            skip = _find_next_start(text, pos + 1)
            if skip is None:
                break
            pos = skip


def _char_to_byte_offset(text: str, char_pos: int, original: bytes) -> int:
    try:
        return len(text[:char_pos].encode("utf-8"))
    except Exception:
        return char_pos


def _find_next_start(text: str, from_pos: int) -> int | None:
    for i in range(from_pos, len(text)):
        if text[i] in '{["0123456789tfn-':
            return i
    return None



'''XLSX: "We wrap each row's read in a try/except inside iter_rows().
 A corrupt row breaks that loop but not the sheet iteration. 
 We collect whatever rows we got, yield the partial DATA record with truncated: true in metadata
 , then continue to the next sheet."

PDF: "We wrap the extract_pages() loop at page level. PDFSyntaxError catches a damaged xref table.
 Any pages extracted before the error are already yielded as DATA records. 
 The exception itself becomes an ERROR record with recovered_pages count in metadata."

JSON: "We use json.JSONDecoder().raw_decode() — it decodes one JSON value at a position and returns 
where it stopped. On failure, we scan forward for the next valid JSON start character and try again. 
Both the ERROR record and any recovered DATA records are emitted — nothing is silently dropped." '''