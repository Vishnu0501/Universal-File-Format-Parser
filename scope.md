# Scope Note

## What is Fully Done

- **Task 1 — Record & API**: `Record` dataclass with `type`, `format`, `content`, `offset`, `reason`, `severity`, `metadata`. Single `parse(bytes, filename)` entry point yielding a stream of Records. `_PARSERS` registry for zero-change extensibility.
- **Task 2 — Format Detector**: Magic-byte detection for all required formats. Handles PDF renamed to `.csv`, XLSX renamed to `.zip`, DOCX with UTF-8 BOM, encrypted Office files (ZIP-based and OLE). Extension used only as last-resort tiebreaker.
- **Task 3 — Text Parsers**: CSV/TSV (auto-delimiter sniffing, quoted fields, embedded newlines, ragged rows), XML (defusedxml, nested dict), YAML (safe_load_all, multi-document), TOML (stdlib tomllib / tomli fallback).
- **Task 4 — Document Parsers**: PDF (pdfminer.six, one Record per page with page number), DOCX (paragraphs + tables), PPTX (one Record per slide, shapes sorted top-to-bottom).
- **Task 5 — XLSX**: openpyxl read-only + data-only, one Record per sheet, full 2D array with None for empty cells, dates converted to ISO strings.
- **Task 6 — Audio → Text**: openai-whisper, temp-file approach, one Record per Whisper segment with start/end timestamps and language.
- **Task 7 — Concurrency + Reorder Buffer**: `ProcessPoolExecutor` with top-level picklable worker functions (`_pdf_page_worker`, `_audio_chunk_worker`). Dict-based reorder buffer tracks `next_index` and flushes in order. Hung workers detected via `concurrent.futures.wait(timeout=...)` — cancelled and replaced with error Records. pydub used for audio splitting with fallback to single-chunk if unavailable.
- **Task 8 — Corruption Recovery**: `recover_xlsx` (row-level try/except, partial sheet recovery), `recover_pdf` (page-level try/except, `PDFSyntaxError` catch for xref damage), `recover_json` (`raw_decode` scan with re-sync to next valid JSON start character, byte-accurate offsets).
- **Task 9 — Malware Scanner**: Zip bomb (ratio, size, entry count, depth limits), XML XXE (SYSTEM/PUBLIC entity regex on raw bytes), billion-laughs (entity definition count + total reference count), VBA macros (ZIP: `vbaProject.bin` detection; OLE: `olefile` stream scan), path traversal in archives (`..` component detection), PDF embedded JS/launch (`/JS`, `/JavaScript`, `/Launch`, `/OpenAction`, `eval()`, `app.launchURL` patterns).

## What is Partial

- **Audio chunking**: `pydub` splits audio into 30-second chunks for parallel processing. If `ffmpeg` is not installed on the system, pydub falls back to treating the entire audio as one chunk (single-process transcription). Whisper itself still requires `ffmpeg` for decoding.
- **DOCX reading order**: Paragraphs are extracted in document order (correct for most files), but text boxes and floating shapes are not extracted — only body paragraphs and tables.
- **PPTX reading order**: Shapes are sorted by `(top, left)` position. This is a best-effort approximation; slide masters and notes are not extracted.

## What Was Cut and Why

- **JSON parser in Task 3**: JSON was not listed in the Task 3 requirements (CSV/TSV, XML, YAML, TOML only). A JSON parser was added in Task 8 as part of the corruption-recovery requirement for mid-stream corrupt JSON.
- **OCR (Tesseract)**: Audio → text (Whisper) was chosen for Task 6 instead. Whisper produces richer timestamped output which maps naturally to the reorder buffer in Task 7. Tesseract OCR would have required image extraction from PDFs as a preprocessing step.
- **Video transcription**: Not implemented. Would require `ffmpeg` frame extraction + OCR on keyframes + audio transcription — significantly more setup for the same grading credit as audio-only.
- **Streaming XLSX write-back**: Recovery produces a complete grid per sheet. For very large truncated files, all recovered rows are held in memory before yielding. A true streaming approach would require a different output structure.
- **Word-level timestamps from Whisper**: `word_timestamps=False` for speed. Segment-level timestamps are sufficient for Task 7 ordering.
- **`.doc` / `.xls` / `.ppt` (legacy OLE formats) full parsing**: OLE format detection is implemented (Task 2), but full text extraction from legacy `.doc`/`.xls`/`.ppt` files is not — only modern DOCX/XLSX/PPTX are parsed. Adding `python-docx2txt` or `xlrd` would cover these.
