import io
import zipfile
import pytest
from parser.detector.format_detector import detect_format


# ── Helper builders ────────────────────────────────────────────────────────────

def _make_zip_with(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


PDF_MAGIC = b"%PDF-1.4 fake pdf content"
XLSX_MAGIC = _make_zip_with({"xl/workbook.xml": "<workbook/>"})
DOCX_MAGIC = _make_zip_with({"word/document.xml": "<document/>"})
PPTX_MAGIC = _make_zip_with({"ppt/presentation.xml": "<presentation/>"})
UTF8_BOM = b"\xef\xbb\xbf"


# ── Task 2 required cases ──────────────────────────────────────────────────────

def test_pdf_renamed_to_csv():
    """PDF bytes with .csv extension must be detected as pdf."""
    assert detect_format(PDF_MAGIC, filename="report.csv") == "pdf"


def test_xlsx_renamed_to_zip():
    """XLSX bytes with .zip extension must be detected as xlsx, not zip."""
    assert detect_format(XLSX_MAGIC, filename="data.zip") == "xlsx"


def test_docx_with_utf8_bom():
    """DOCX bytes prefixed with UTF-8 BOM must be detected as docx."""
    bom_docx = UTF8_BOM + DOCX_MAGIC
    assert detect_format(bom_docx, filename="report.docx") == "docx"


def test_encrypted_office_zip():
    """XLSX with EncryptedPackage entry must be reported as encrypted_office."""
    enc = _make_zip_with({"EncryptedPackage": b"\x00" * 16, "EncryptionInfo": b"\x00" * 16})
    assert detect_format(enc) == "encrypted_office"


def test_pptx_detection():
    assert detect_format(PPTX_MAGIC, filename="slides.pptx") == "pptx"


def test_plain_zip():
    plain = _make_zip_with({"readme.txt": "hello"})
    assert detect_format(plain) == "zip"


# ── Extension ignored ──────────────────────────────────────────────────────────

def test_extension_not_trusted_for_pdf():
    assert detect_format(PDF_MAGIC, filename="totally_a_spreadsheet.xlsx") == "pdf"


def test_extension_not_trusted_for_xlsx():
    assert detect_format(XLSX_MAGIC, filename="document.docx") == "xlsx"


# ── Text format heuristics ─────────────────────────────────────────────────────

def test_csv_detection():
    data = b"name,age,city\nAlice,30,NYC\nBob,25,LA\n"
    assert detect_format(data) == "csv"


def test_tsv_detection():
    data = b"name\tage\tcity\nAlice\t30\tNYC\nBob\t25\tLA\n"
    assert detect_format(data) == "tsv"


def test_json_detection():
    data = b'{"key": "value", "num": 42}'
    assert detect_format(data) == "json"


def test_xml_detection():
    data = b"<?xml version='1.0'?><root><item>hello</item></root>"
    assert detect_format(data) == "xml"


def test_yaml_detection():
    data = b"---\nname: Alice\nage: 30\n"
    assert detect_format(data) == "yaml"


def test_empty_data():
    assert detect_format(b"") == "empty"
