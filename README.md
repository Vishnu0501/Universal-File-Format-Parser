# Universal File & Format Parser

A single Python library that auto-detects any file format from raw bytes, extracts structured data, recovers from corruption, and scans for malware — all through one consistent `Record` stream.

## Requirements

- Python 3.11+
- ffmpeg (required by Whisper for audio decoding) — install with `winget install ffmpeg` on Windows

## Install

```bash
pip install -r requirements.txt
```

## Usage

```python
from parser import parse, RecordType

with open("report.pdf", "rb") as f:
    for record in parse(f.read(), filename="report.pdf"):
        if record.type == RecordType.DATA:
            print(record.content)
        else:
            print(f"[{record.type}] offset={record.offset} → {record.reason}")
```

## Corruption Recovery

```python
from parser import recover_pdf, recover_xlsx, recover_json

for record in recover_pdf(open("damaged.pdf", "rb").read()):
    print(record)
```

## Malware Scanning

```python
from parser import scan, RecordType

for record in scan(open("suspicious.zip", "rb").read()):
    print(f"[{record.severity}] {record.reason}")
```

## Parallel Processing (PDF / Audio)

```python
from parser.concurrency.pool_executor import parse_pdf_parallel, parse_audio_parallel

for record in parse_pdf_parallel(open("large.pdf", "rb").read(), max_workers=4):
    print(f"Page {record.metadata['page']}: {record.content[:80]}")
```

## Supported Formats

| Format | Parse | Detect | Recover |
|--------|-------|--------|---------|
| PDF | ✅ (per-page) | ✅ | ✅ (xref damage) |
| DOCX | ✅ | ✅ | — |
| PPTX | ✅ (per-slide) | ✅ | — |
| XLSX | ✅ (per-sheet 2D) | ✅ | ✅ (truncation) |
| CSV / TSV | ✅ | ✅ | — |
| XML | ✅ | ✅ | — |
| YAML | ✅ | ✅ | — |
| TOML | ✅ | ✅ | — |
| JSON | ✅ | ✅ | ✅ (mid-stream) |
| MP3 / WAV / FLAC / OGG | ✅ (Whisper) | ✅ | — |

## Project Structure

```
parser/
├── record.py              # Record, RecordType, Severity
├── parser.py              # parse() entry point + _PARSERS registry
├── detector/
│   └── format_detector.py # Magic-byte + heuristic format detection
├── parsers/               # One file per format
├── concurrency/
│   └── pool_executor.py   # ProcessPoolExecutor + reorder buffer
├── recovery/
│   └── corruption_handler.py
└── scanner/
    └── malware_scanner.py
```
