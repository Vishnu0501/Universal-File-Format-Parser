from typing import Iterator
from parser.record import Record, RecordType
from parser.detector.format_detector import detect_format
from parser.parsers.csv_parser import parse_csv
from parser.parsers.xml_parser import parse_xml
from parser.parsers.yaml_parser import parse_yaml
from parser.parsers.toml_parser import parse_toml
from parser.parsers.pdf_parser import parse_pdf
from parser.parsers.docx_parser import parse_docx
from parser.parsers.pptx_parser import parse_pptx
from parser.parsers.xlsx_parser import parse_xlsx
from parser.parsers.audio_parser import parse_audio
from parser.parsers.json_parser import parse_json

def parse(data: bytes,filename: str = "") -> Iterator[Record]:
    fmt = detect_format(data,filename)
    yield from _get_parser(fmt)(data)

def _get_parser(fmt: str):
    return _PARSERS.get(fmt,_unknown_parser)

def _unknown_parser(data: bytes) -> Iterator[Record]:
    yield Record(
        type= RecordType.ERROR,
        format="unknown",
        reason="Unsupported or unrecognized format"
    )

_PARSERS: dict = {
    "csv":  parse_csv,
    "tsv":  parse_csv,
    "xml":  parse_xml,
    "yaml": parse_yaml,
    "toml": parse_toml,
    "pdf":  parse_pdf,
    "docx": parse_docx,
    "pptx": parse_pptx,
    "xlsx": parse_xlsx,
    "mp3":  parse_audio,
    "wav":  parse_audio,
    "flac": parse_audio,
    "ogg":  parse_audio,
    "json": parse_json,
}

'''"parse() is the only function a user ever calls. It takes raw bytes and an optional filename hint.

Line 15 — detect format from bytes, not extension. Line 16 — look up the right parser from the 
registry and stream its output directly.

The registry pattern on lines 28-44 is the key extensibility decision. To add a new format — 
say Markdown — I create one file, write one function, and add one line to this dict. 
Zero changes anywhere else. parse() itself never changes.

_unknown_parser is the fallback — it yields an ERROR record instead of crashing. 
The library cannot throw an exception that escapes to the user."'''