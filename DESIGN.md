# DESIGN.md — Universal File & Format Parser

## 1. The Record Schema

Everything the library produces — parsed data, errors, warnings, malware alerts — comes out as a `Record`.

```python
@dataclass
class Record:
    type:     RecordType          # "data" | "error" | "warning"
    format:   str                 # which parser produced this ("pdf", "csv", "xlsx", …)
    content:  Optional[Any]       # parsed payload; None for errors/warnings
    offset:   Optional[int]       # byte offset in the input where this record originates
    reason:   Optional[str]       # human-readable message for errors/warnings
    severity: Optional[Severity]  # "low" | "medium" | "high" | "critical" — warnings only
    metadata: dict                # format-specific extras (page, slide, sheet, timestamps…)
```

**Why a flat dataclass?**
A flat structure is directly JSON-serialisable, easy to filter (`record.type == RecordType.ERROR`), and requires no polymorphism. All fields are optional except `type` and `format`, so data records and error records share one schema without any `if isinstance(...)` checks downstream.

### 5-line usage example

```python
from parser import parse, RecordType

with open("report.pdf", "rb") as f:
    for record in parse(f.read(), filename="report.pdf"):
        if record.type == RecordType.DATA:
            print(record.content)
        else:
            print(f"[{record.type}] offset={record.offset} → {record.reason}")
```

---

## 2. Architecture

```
parse(bytes, filename)
    │
    ▼
format_detector.detect_format()   ← magic bytes only; filename is a tiebreaker
    │
    ▼ fmt string ("pdf", "xlsx", "csv", …)
_PARSERS[fmt](bytes)              ← registry lookup; unknown formats → error Record
    │
    ▼
Iterator[Record]                  ← lazy stream; never raises outside the library
```

Each parser module registers itself in `_PARSERS` at import time. Adding a new format never touches existing code — open/closed principle.

**Dependency justification:**

| Library | Used for | Why not reimplement |
|---------|----------|---------------------|
| `pdfminer.six` | PDF text + layout | Layout-aware extraction (LAParams) preserves reading order across columns |
| `python-docx` | DOCX text | Handles OPC/ZIP internals and XML namespaces correctly |
| `python-pptx` | PPTX text | Same OPC structure; shape geometry needed for ordering |
| `openpyxl` | XLSX 2D arrays | Shared-strings decompression and cell-type inference are non-trivial |
| `openai-whisper` | Audio → text | State-of-the-art speech recognition; reimplementing is out of scope |
| `pydub` | Audio chunking | ffmpeg wrapper; falls back gracefully when unavailable |
| `defusedxml` | Safe XML parsing | Blocks XXE/billion-laughs at the parser level as a defence-in-depth layer |
| `olefile` | OLE/legacy Office | Binary compound document format parsing |

---

## 3. Task 2 Write-up: Format Detection

### How do you tell XLSX vs DOCX vs PPTX apart — they are all ZIP files?

All three use the Open Packaging Convention (OPC): a ZIP archive with a `[Content_Types].xml` manifest. We open the ZIP and look for format-specific marker files:

| Marker file present | Format |
|--------------------|--------|
| `xl/workbook.xml` or `xl/workbook.bin` | XLSX |
| `word/document.xml` or `word/document.bin` | DOCX |
| `ppt/presentation.xml` or `ppt/presentation.bin` | PPTX |

If none of these markers are present, we fall back to `"zip"`. `EncryptedPackage` / `EncryptionInfo` entries indicate an encrypted Office file regardless of the specific application.

### If magic bytes and content sniffing disagree, how do you decide? Confidence score?

Magic bytes win. The detection pipeline is strictly ordered:

1. Check raw magic bytes first (no extension, no content sniffing).
2. If magic bytes say `zip_family`, inspect the ZIP contents to specialise further.
3. If no magic match, fall through to text heuristics (JSON/CSV/YAML/TOML detection from content).
4. Extension is checked **only** as the absolute last fallback inside `_detect_text()`.

No confidence scores are returned — the library commits to one format label. This makes the API deterministic (same input → same output) and avoids pushing ambiguity handling to callers. If detection is genuinely ambiguous (e.g., a plain-text file that could be YAML or TOML), the heuristic picks the most specific match and the caller can always override by passing `filename`.

### How do you detect "this is encrypted" without the password?

**For modern Office (OOXML):** Open the ZIP. Encrypted files contain `EncryptedPackage` and `EncryptionInfo` entries instead of the normal `word/`, `xl/`, or `ppt/` directories. No password is needed to detect this — the container structure alone reveals it.

**For legacy Office (OLE/CFB):** The file starts with the OLE magic bytes `\xD0\xCF\x11\xE0`. Using `olefile`, we look for an `EncryptionInfo` stream. Alternatively, a specific CLSID at bytes 8–24 identifies the encryption wrapper.

**For PDFs:** `pdfminer` raises `PDFEncryptionError` when it encounters a password-protected PDF. We catch this and emit a `WARNING` Record with severity `MEDIUM` rather than letting it propagate.

---

## 4. Task 3 Write-up: CSV Delimiter Guessing

### Logic

1. Take the first 20 lines of the file as a sample.
2. Pass to `csv.Sniffer().sniff(sample, delimiters=",\t|;:")`.
3. The Sniffer scores each candidate delimiter by consistency — it picks the one with the most uniform column count across rows.
4. If `Sniffer` raises `csv.Error` (ambiguous sample), fall back: count raw `\t` vs `,` occurrences in the first 4 KB and pick the more frequent one.

### One input where it would guess wrong

```
name,description
Alice,"Likes hiking, camping, and coffee"
Bob,"Reads books, codes, and cooks"
```

The Sniffer sees many commas — some inside quotes, some as delimiters. On short samples where quoted commas outnumber delimiter commas, the Sniffer may misidentify the quotechar or fail entirely and fall back to the raw-count heuristic, which would still pick comma (correct here). However, if the file were:

```
Alice	"hello, world"	42
Bob	"foo, bar"	99
```

A TSV file with commas inside quoted fields — the raw-count fallback would see more commas than tabs and guess comma, producing a broken parse. The correct delimiter is tab.

---

## 5. Task 7 Write-up: Concurrency & Reorder Buffer

### How does the reorder buffer work?

The buffer is a plain `dict[int, List[Record]]`. We assign each unit of work a sequential index (0, 1, 2, …) before submission. A `next_index` counter tracks the next index to emit.

When a future completes, its results are stored as `pending[index] = records`. After every completion batch, we flush: while `next_index` is a key in `pending`, yield all records for that index and increment `next_index`.

This guarantees output order regardless of which workers finish first.

**Worst-case memory:** If unit 0 is the last to finish, all records for units 1…N-1 accumulate in `pending` before anything is emitted. With 20 pages and N records per page, that is `(20-1) × N` records in memory simultaneously.

### A worker hangs forever — how do you avoid blocking everything?

We use `concurrent.futures.wait(remaining_futures, timeout=WORKER_TIMEOUT, return_when=FIRST_COMPLETED)`. If no future completes within `WORKER_TIMEOUT` seconds (default 120 s), `done` is empty. We then:

1. Call `f.cancel()` on every remaining future — this terminates the process if it hasn't started yet, or marks it for cancellation.
2. Insert an `ERROR` Record into `pending` for each cancelled unit.
3. Clear `remaining_futures` so the loop exits.

The hung page appears in the ordered output as an error Record at its correct position — no gap, no hang, no crash.

**Caveat:** `ProcessPoolExecutor` on CPython does not support forcibly killing a *running* worker. `cancel()` only prevents a *queued* task from starting. A truly hung running worker will be cleaned up when the `with` block exits and the executor shuts down (which calls `shutdown(wait=True)`, joining all worker processes). To avoid this, `WORKER_TIMEOUT` should be set conservatively.

### Why ProcessPoolExecutor and not threads?

Whisper and pdfminer are CPU-bound (matrix operations, PDF rendering). Python's Global Interpreter Lock (GIL) prevents true parallelism for CPU-bound threads — only one thread runs Python bytecode at a time. Processes have separate memory spaces and separate GIL instances, so they run truly in parallel on multiple cores.

**How this changes data passing:** Everything sent to a worker — arguments and return values — must be picklable (serialised via `pickle` across the process boundary). This means:
- Worker functions must be module-level functions (not lambdas or closures — they are not picklable).
- `Record` dataclasses must contain only picklable types (strings, dicts, enums — all fine).
- Large inputs (e.g., full PDF bytes) are copied to each worker process — this is memory-intensive but unavoidable without shared memory.

---

## 6. Task 8 Write-up: Corruption Recovery

### After hitting a corrupt block, how do you find the next valid point to resume?

**Stream format (JSON):** After a `JSONDecodeError`, we scan forward character by character from the error position looking for any of `{`, `[`, `"`, digits, `t` (true), `f` (false), `n` (null), `-` (negative number). The first match is the candidate start of the next JSON value. We attempt `raw_decode()` there; if it fails again, we continue scanning.

**Container format (XLSX):** XLSX is a ZIP archive of independent XML streams. A corrupt byte range within one sheet's XML does not affect other sheets. We wrap each sheet's `iter_rows()` loop in a row-level `try/except`. When a row raises, we record the truncation, yield a warning Record, and `break` out of that sheet's loop — then continue with the next sheet normally.

**PDF:** pdfminer processes pages lazily. A corrupt xref table raises `PDFSyntaxError` during iteration. We wrap the `extract_pages()` loop in a `try/except PDFSyntaxError` — any pages successfully yielded before the exception are emitted as data Records; the exception itself becomes an error Record with the count of recovered pages.

### Risk of "recovering garbage"

Yes, this is real. After skipping a corrupt region in JSON, the next candidate start character might be inside a corrupt value (e.g., a stray `{` inside binary noise), and `raw_decode()` might parse it as a valid but semantically wrong object. We mitigate this by:

1. Tagging recovered Records with `"truncated": true` in metadata so consumers know the data may be incomplete.
2. Never silently discarding the error Record — both the partial data and the error are emitted, letting the caller decide which to trust.

---

## 7. Task 9 Write-up: Malware / Exploit Scanner

### How do you cap resources so a malicious file can't OOM or hang?

| Resource | Cap | Mechanism |
|----------|-----|-----------|
| ZIP uncompressed size | 500 MB | Sum `file_size` from `infolist()` — reads metadata only, never decompresses |
| ZIP compression ratio | 100:1 | `sum(file_size) / sum(compress_size)` from metadata |
| ZIP entry count | 10,000 | `len(infolist())` |
| ZIP nesting depth | 3 levels | Recursive `_scan_zip_bomb()` with depth counter; returns immediately at limit |
| XML entity definitions | 50 | Count `<!ENTITY` patterns in first 64 KB of raw bytes |
| XML entity references | 10,000 total | Count `&name;` occurrences in raw bytes |
| PDF scan | Regex on raw bytes | No parsing, no decompression, no execution |

Critically, **we never call `zf.extractall()` or `zf.read()` on suspected bomb entries**. All ZIP size information is read from the central directory (metadata) without decompressing.

### How do you stop the scanner itself from becoming the vulnerability?

The trust boundary is: **we only inspect metadata and raw bytes; we never execute, decompress, or interpret the payload**.

Specific protections:
- **Zip scanning**: metadata-only (`infolist()`) for size checks. `zf.read()` is only called on nested `.zip` entries smaller than 10 MB to check recursion depth.
- **XML scanning**: regex on raw bytes (`data[:65536]`). We never call an XML parser during scanning — `defusedxml` is the parser for Task 3, not for Task 9.
- **PDF scanning**: regex on raw bytes. We never call pdfminer during the scan phase.
- **VBA scanning**: we check ZIP entry names (strings) and OLE stream names (strings). We never decompress or execute VBA bytecode.
- **No subprocess calls**: nothing in the scanner spawns a process or shell.

### Corrupt vs malicious — what's the difference in reporting?

| | Corrupt | Malicious |
|---|---------|-----------|
| Intent | Accidental (truncation, hardware error, bad software) | Deliberate (crafted to exploit the reader) |
| Record type | `ERROR` | `WARNING` |
| Severity | — (errors have no severity field) | `HIGH` or `CRITICAL` |
| `metadata["attack"]` | Not present | Set (e.g., `"xxe_system_entity"`, `"zip_bomb"`, `"vba_macro"`) |
| Action | Re-sync and continue parsing | Emit warning and continue — never execute |

A corrupt file fails to conform to its format spec unintentionally. A malicious file may be perfectly valid according to the spec but contains payloads designed to exploit the parser or reader. Both are reported as Records; neither causes a crash.
