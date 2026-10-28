import io
import json
import pytest
import openpyxl
from parser.record import RecordType
from parser.recovery.corruption_handler import recover_xlsx, recover_pdf, recover_json


def data_records(gen):
    return [r for r in gen if r.type == RecordType.DATA]


def error_records(gen):
    return [r for r in gen if r.type == RecordType.ERROR]


def warning_records(gen):
    return [r for r in gen if r.type == RecordType.WARNING]


# ── XLSX truncation recovery ───────────────────────────────────────────────────

def _make_xlsx(sheets: dict) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for sheet_name, rows in sheets.items():
        ws = wb.create_sheet(sheet_name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_recover_xlsx_valid_file_yields_data():
    data = _make_xlsx({"Sheet1": [["a", "b"], [1, 2]]})
    rows = data_records(recover_xlsx(data))
    assert len(rows) == 1
    assert rows[0].content[0] == ["a", "b"]


def test_recover_xlsx_truncated_yields_partial_data():
    data = _make_xlsx({"Sheet1": [["a", "b"], [1, 2], [3, 4]]})
    truncated = data[:len(data) // 2]
    results = list(recover_xlsx(truncated))
    # Must never raise; must yield at least one Record (error or data)
    assert len(results) >= 1


def test_recover_xlsx_bad_bytes_yields_error():
    results = list(recover_xlsx(b"totally not xlsx"))
    errs = [r for r in results if r.type == RecordType.ERROR]
    assert len(errs) >= 1


def test_recover_xlsx_never_raises():
    for bad in [b"", b"\x00" * 100, b"PK\x03\x04garbage", b"randomgarbage"]:
        try:
            list(recover_xlsx(bad))
        except Exception as e:
            pytest.fail(f"recover_xlsx raised on input {bad!r}: {e}")


# ── PDF xref recovery ──────────────────────────────────────────────────────────

def test_recover_pdf_bad_bytes_yields_error():
    results = list(recover_pdf(b"%PDF-1.4 corrupted content"))
    assert len(results) >= 1
    errs = [r for r in results if r.type == RecordType.ERROR]
    assert len(errs) >= 1


def test_recover_pdf_never_raises():
    for bad in [b"", b"%PDF-1.4\nbroken", b"\x00" * 200, b"notpdf"]:
        try:
            list(recover_pdf(bad))
        except Exception as e:
            pytest.fail(f"recover_pdf raised on input {bad!r}: {e}")


# ── JSON mid-stream corruption recovery ───────────────────────────────────────

def test_recover_json_clean_input():
    data = b'{"a": 1}\n{"b": 2}\n{"c": 3}'
    rows = data_records(recover_json(data))
    assert len(rows) == 3
    assert rows[0].content == {"a": 1}


def test_recover_json_corrupt_middle():
    data = b'{"a": 1} THIS IS NOT JSON {"b": 2}'
    all_r = list(recover_json(data))
    data_r = data_records(iter(all_r))
    err_r = error_records(iter(all_r))
    assert len(data_r) >= 1
    assert len(err_r) >= 1


def test_recover_json_error_has_byte_offset():
    data = b'{"a": 1} CORRUPT {"b": 2}'
    errs = error_records(recover_json(data))
    assert errs[0].offset is not None
    assert errs[0].offset > 0


def test_recover_json_corrupt_at_start_then_valid():
    data = b'GARBAGE {"valid": true}'
    all_r = list(recover_json(data))
    data_r = [r for r in all_r if r.type == RecordType.DATA]
    assert len(data_r) >= 1
    assert data_r[0].content == {"valid": True}


def test_recover_json_only_garbage_yields_only_errors():
    data = b"@@@###$$$%%%"
    all_r = list(recover_json(data))
    assert all(r.type == RecordType.ERROR for r in all_r) or len(all_r) == 0


def test_recover_json_never_raises():
    for bad in [b"", b"\x00" * 50, b"[[[[[", b"null null null"]:
        try:
            list(recover_json(bad))
        except Exception as e:
            pytest.fail(f"recover_json raised on {bad!r}: {e}")


def test_recover_json_object_index_in_metadata():
    data = b'{"x":1}\n{"y":2}'
    rows = data_records(recover_json(data))
    assert rows[0].metadata["object_index"] == 0
    assert rows[1].metadata["object_index"] == 1
