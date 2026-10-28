import concurrent.futures
import io
import os
import tempfile
from typing import Iterator, List, Tuple, Any

from parser.record import Record, RecordType, Severity

WORKER_TIMEOUT = 120
MAX_WORKERS = 4
AUDIO_CHUNK_SECONDS = 30


# ── Top-level picklable worker functions ──────────────────────────────────────
# These must be module-level (not lambdas/closures) to be picklable by multiprocessing

def _pdf_page_worker(page_index: int, pdf_bytes: bytes) -> List[Record]:
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTTextContainer, LAParams

        layouts = list(extract_pages(io.BytesIO(pdf_bytes), laparams=LAParams()))

        if page_index >= len(layouts):
            return [Record(
                type=RecordType.ERROR, format="pdf",
                reason=f"Page index {page_index} out of range",
                metadata={"page": page_index + 1},
            )]

        texts = [
            el.get_text().strip()
            for el in layouts[page_index]
            if isinstance(el, LTTextContainer) and el.get_text().strip()
        ]
        return [Record(
            type=RecordType.DATA, format="pdf",
            content="\n".join(texts),
            metadata={"page": page_index + 1},
        )]
    except Exception as e:
        return [Record(
            type=RecordType.ERROR, format="pdf",
            reason=f"PDF page {page_index + 1} worker failed: {e}",
            metadata={"page": page_index + 1},
        )]


def _audio_chunk_worker(chunk_index: int, payload: Tuple) -> List[Record]:
    chunk_bytes, suffix, start_offset = payload
    tmp_path = None
    try:
        import whisper

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(chunk_bytes)
            tmp_path = tmp.name

        model = whisper.load_model("base")
        result = model.transcribe(tmp_path, verbose=False)

        records = []
        for seg in result.get("segments", []):
            records.append(Record(
                type=RecordType.DATA, format="audio",
                content=seg.get("text", "").strip(),
                metadata={
                    "chunk_index": chunk_index,
                    "segment_id": seg.get("id"),
                    "start": round(seg.get("start", 0) + start_offset, 3),
                    "end": round(seg.get("end", 0) + start_offset, 3),
                    "language": result.get("language"),
                },
            ))

        if not records:
            records.append(Record(
                type=RecordType.WARNING, format="audio",
                reason=f"Audio chunk {chunk_index} produced no transcript",
                severity=Severity.LOW,
                metadata={"chunk_index": chunk_index},
            ))
        return records

    except Exception as e:
        return [Record(
            type=RecordType.ERROR, format="audio",
            reason=f"Audio chunk {chunk_index} worker failed: {e}",
            metadata={"chunk_index": chunk_index},
        )]
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# ── Generic reorder buffer ─────────────────────────────────────────────────────

def parallel_ordered_stream(
    units: List[Tuple[int, Any]],
    worker_fn,
    max_workers: int = MAX_WORKERS,
    timeout: float = WORKER_TIMEOUT,
) -> Iterator[Record]:
    """
    Submit units to a ProcessPoolExecutor. Yield Records in index order.
    A hung or failed worker emits an error Record and never stalls the stream.

    Reorder buffer: a dict mapping index -> List[Record].
    We track `next_index` (next index to emit) and flush the buffer
    whenever the front of the queue is ready.

    Worst-case memory: if unit 0 finishes last, all other units' Records
    accumulate in the buffer before anything is emitted.
    """
    if not units:
        return

    pending: dict = {}
    next_index = 0
    total = len(units)

    executor = concurrent.futures.ProcessPoolExecutor(max_workers=max_workers)
    try:
        future_to_index = {
            executor.submit(worker_fn, idx, payload): idx
            for idx, payload in units
        }
        remaining = set(future_to_index)

        while remaining:
            done, remaining = concurrent.futures.wait(
                remaining,
                timeout=timeout,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )

            if not done:
                for f in list(remaining):
                    idx = future_to_index[f]
                    f.cancel()
                    pending[idx] = [Record(
                        type=RecordType.ERROR,
                        format="parallel",
                        reason=f"Worker for unit {idx} timed out after {timeout}s",
                        metadata={"unit_index": idx},
                    )]
                remaining = set()

            for f in done:
                idx = future_to_index[f]
                try:
                    pending[idx] = list(f.result())
                except Exception as e:
                    pending[idx] = [Record(
                        type=RecordType.ERROR,
                        format="parallel",
                        reason=f"Worker for unit {idx} raised {type(e).__name__}: {e}",
                        metadata={"unit_index": idx},
                    )]

            while next_index in pending:
                yield from pending.pop(next_index)
                next_index += 1

    finally:
        # wait=False so hung workers don't block the caller;
        # cancel_futures=True drops any queued-but-not-started tasks.
        executor.shutdown(wait=False, cancel_futures=True)

    while next_index < total:
        if next_index in pending:
            yield from pending.pop(next_index)
        next_index += 1


# ── Public parallel parse helpers ─────────────────────────────────────────────

def parse_pdf_parallel(pdf_bytes: bytes, max_workers: int = MAX_WORKERS) -> Iterator[Record]:
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LAParams
        page_count = sum(1 for _ in extract_pages(io.BytesIO(pdf_bytes), laparams=LAParams()))
    except Exception as e:
        yield Record(type=RecordType.ERROR, format="pdf", reason=f"Could not count PDF pages: {e}")
        return

    units = [(i, pdf_bytes) for i in range(page_count)]
    yield from parallel_ordered_stream(units, _pdf_page_worker, max_workers=max_workers)


def parse_audio_parallel(
    audio_bytes: bytes,
    suffix: str = ".mp3",
    max_workers: int = MAX_WORKERS,
) -> Iterator[Record]:
    chunks = _split_audio(audio_bytes, suffix)
    if not chunks:
        yield Record(type=RecordType.ERROR, format="audio", reason="Audio produced no chunks")
        return

    units = [(i, (chunk_bytes, suffix, start_sec)) for i, (chunk_bytes, start_sec) in enumerate(chunks)]
    yield from parallel_ordered_stream(units, _audio_chunk_worker, max_workers=max_workers)


def _split_audio(audio_bytes: bytes, suffix: str) -> List[Tuple[bytes, float]]:
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        chunk_ms = AUDIO_CHUNK_SECONDS * 1000
        chunks = []
        for start in range(0, len(audio), chunk_ms):
            segment = audio[start: start + chunk_ms]
            buf = io.BytesIO()
            segment.export(buf, format=suffix.lstrip("."))
            chunks.append((buf.getvalue(), start / 1000.0))
        return chunks
    except ImportError:
        return [(audio_bytes, 0.0)]
    except Exception:
        return [(audio_bytes, 0.0)]



'''Units submitted:   [0] [1] [2] [3] [4]
                    ↓   ↓   ↓   ↓   ↓
                   Workers finish in random order: 2, 4, 1, 3, 0
pending dict after each completion:
  {2: [...]}         next_index=0 → 0 not ready, hold
  {2: [...], 4: [...]}              0 not ready, hold
  {1: [...], 2: [...], 4: [...]}    0 not ready, hold
  {1,2,3,4 all ready}               0 not ready, hold


"The reorder buffer is a plain dict. Every completed future stores its records at pending[index]. 
The next_index pointer only advances when the exact next index is ready. 
So output always comes out in submission order — 0, 1, 2, 3, 4 — regardless of what order workers finish.

Timeout: wait(timeout=120) with FIRST_COMPLETED. If nothing completes in 120 seconds, 
done is empty — that means at least one worker is hung. We cancel remaining futures, 
insert ERROR records, and the stream continues.

Why shutdown(wait=False) instead of a with block? On Windows, with ProcessPoolExecutor blocks 
on exit until all workers finish — including hung ones. shutdown(wait=False) returns immediately 
and lets the OS handle cleanup."'''