import zipfile
import io
from typing import Optional

MAGIC_BYTES = [
    (b"%PDF",                    "pdf"),
    (b"\xD0\xCF\x11\xE0",       "ole"),
    (b"PK\x03\x04",             "zip_family"),
    (b"\xEF\xBB\xBF",           "bom_prefix"),
    (b"<?xml",                   "xml"),
    (b"<",                       "xml_likely"),
    (b"RIFF",                    "riff"),
    (b"\x1f\x8b",               "gzip"),
    (b"\x89PNG",                 "png"),
    (b"\xFF\xD8\xFF",            "jpeg"),
    (b"GIF87a",                  "gif"),
    (b"GIF89a",                  "gif"),
    (b"ID3",                     "mp3"),
    (b"fLaC",                    "flac"),
    (b"OggS",                    "ogg"),
    (b"\x1aE\xdf\xa3",          "mkv"),
    (b"WAVE",                    "wav"),
]

ZIP_FAMILY_MARKERS = {
    "xl/workbook.xml":        "xlsx",
    "xl/workbook.bin":        "xlsx",
    "word/document.xml":      "docx",
    "word/document.bin":      "docx",
    "ppt/presentation.xml":   "pptx",
    "ppt/presentation.bin":   "pptx",
}

OLE_ENCRYPTED_CLSID = b"\x06\x09\x02\x00\x00\x00\x00\x00\xc0\x00\x00\x00\x00\x00\x00\x46"

def detect_format(data: bytes, filename: str = "") -> str:
    if not data:
        return "empty"

    magic_hit = _match_magic(data)

    if magic_hit == "bom_prefix":
        inner_data = data[3:]
        inner_hit = _match_magic(inner_data)
        if inner_hit == "zip_family":
            return _detect_zip_family(inner_data)
        return _detect_text(inner_data, filename)

    raw = _strip_bom(data)

    if magic_hit == "pdf":
        return "pdf"

    if magic_hit == "ole":
        return _detect_ole(raw)

    if magic_hit == "zip_family":
        return _detect_zip_family(raw)

    if magic_hit in ("xml", "xml_likely"):
        return "xml"
    if magic_hit in ("png", "jpeg", "gif"):
        return magic_hit
    if magic_hit in ("mp3", "flac", "ogg", "wav", "riff"):
        return magic_hit
    if magic_hit == "mkv":
        return "mkv"
    if magic_hit == "gzip":
        return "gzip"
    return _detect_text(raw, filename)


def _strip_bom(data: bytes) -> bytes:
    if data[:3] == b"\xEF\xBB\xBF":
        return data[3:]
    return data

def _match_magic(data: bytes) -> Optional[str]:
    for magic, label in MAGIC_BYTES:
        if data[:len(magic)] == magic:
            return label
    return None

def _detect_zip_family(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())

            for marker, fmt in ZIP_FAMILY_MARKERS.items():
                if marker in names:
                    return fmt

            if "EncryptedPackage" in names or "EncryptionInfo" in names:
                return "encrypted_office"

            if _is_zip_bomb(zf):
                return "zip_bomb"

            return "zip"
    except zipfile.BadZipFile:
        return "corrupted_zip"
    except Exception:
        return "zip"

def _detect_ole(data: bytes) -> str:
    if len(data) >= 32 and data[8:24] == OLE_ENCRYPTED_CLSID:
        return "encrypted_office"
    try:
        import olefile
        if olefile.isOleFile(io.BytesIO(data)):
            ole = olefile.OleFileIO(io.BytesIO(data))
            if ole.exists("EncryptionInfo"):
                return "encrypted_office"
            if ole.exists("WordDocument"):
                return "doc"
            if ole.exists("Workbook"):
                return "xls"
            if ole.exists("PowerPoint Document"):
                return "ppt"

    except Exception:
        pass

    return "ole"


def _is_zip_bomb(zf: zipfile.ZipFile) -> bool:
    MAX_UNCOMPRESSED = 500 * 1024 * 1024
    MAX_RATIO = 100
    total_uncompressed = sum(i.file_size for i in zf.infolist())
    total_compressed = sum(i.compress_size for i in zf.infolist()) or 1
    if total_uncompressed > MAX_UNCOMPRESSED:
        return True
    if total_uncompressed / total_compressed > MAX_RATIO:
        return True
    return False

def _detect_text(data: bytes, filename: str) -> str:
    sample = data[:4096]
    try:
        text = sample.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        try:
            text = sample.decode("latin-1")
        except Exception:
            return "binary"
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return "json"
    if "\t" in text and _looks_tabular(text, "\t"):
        return "tsv"
    if "," in text and _looks_tabular(text, ","):
        return "csv"
    if stripped.startswith("---") or ":" in text:
        return "yaml"
    if "[" in text and "=" in text:
        return "toml"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    fallback_map = {
        "csv": "csv", "tsv": "tsv", "yaml": "yaml", "yml": "yaml",
        "toml": "toml", "json": "json", "xml": "xml", "txt": "text",
    }
    return fallback_map.get(ext, "text")


def _looks_tabular(text: str, delimiter:str) -> bool:
    lines = [l for l in text.splitlines() if l.strip()][:5]
    if not lines:
        return False
    counts = [line.count(delimiter) for line in lines]
    return counts[0] > 0 and max(counts) - min(counts) <=1



'''
"This is where the 'never trust the extension' rule lives. The flow is strictly ordered — 
magic bytes always win.

MAGIC_BYTES is a list of (signature, label) tuples. We check the first few bytes against each 
signature in order. PDF always starts with %PDF. ZIP-based files always start with PK\x03\x04 — 
that includes XLSX, DOCX, and PPTX.

The tricky case is BOM — a UTF-8 BOM is \xEF\xBB\xBF, 3 bytes prepended to the file. 
A DOCX with BOM starts with those 3 bytes, then immediately the ZIP magic bytes. 
So we handle BOM first: strip the 3 bytes, re-run magic matching on the inner data, 
and detect accordingly.

For ZIP-family files, we open the archive and check which marker files are present — 
xl/workbook.xml means XLSX, word/document.xml means DOCX. Extension is completely ignored."'''

'''"Inside the with block — important — we check entry names. 
EncryptedPackage and EncryptionInfo entries mean the file is password-protected. 
We report that as encrypted_office without crashing. BadZipFile means the archive is corrupt — 
that becomes corrupted_zip. The outer except Exception is a safety net — nothing escapes."'''