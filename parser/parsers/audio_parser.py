import os
import tempfile
from typing import Iterator
from parser.record import Record, RecordType, Severity

try:
    import whisper
    _WHISPER = True
except ImportError:
    _WHISPER = False

WHISPER_MODEL = "base"


def parse_audio(data: bytes) -> Iterator[Record]:
    if not _WHISPER:
        yield Record(type=RecordType.ERROR, format="audio", reason="openai-whisper is not installed")
        return

    suffix = _detect_audio_suffix(data)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        try:
            model = whisper.load_model(WHISPER_MODEL)
        except Exception as e:
            yield Record(type=RecordType.ERROR, format="audio", reason=f"Failed to load Whisper model: {e}")
            return

        try:
            result = model.transcribe(tmp_path, verbose=False, word_timestamps=False)
        except Exception as e:
            yield Record(type=RecordType.ERROR, format="audio", reason=f"Whisper transcription failed: {e}")
            return

        segments = result.get("segments", [])
        if not segments:
            yield Record(
                type=RecordType.WARNING,
                format="audio",
                reason="Whisper returned no segments; audio may be silent or unrecognized",
                severity=Severity.LOW,
            )
            return

        for seg in segments:
            yield Record(
                type=RecordType.DATA,
                format="audio",
                content=seg.get("text", "").strip(),
                metadata={
                    "segment_id": seg.get("id"),
                    "start": seg.get("start"),
                    "end": seg.get("end"),
                    "language": result.get("language"),
                },
            )

    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _detect_audio_suffix(data: bytes) -> str:
    if data[:3] == b"ID3" or data[:2] == b"\xff\xfb":
        return ".mp3"
    if data[:4] == b"fLaC":
        return ".flac"
    if data[:4] == b"OggS":
        return ".ogg"
    if data[:4] in (b"RIFF",) and data[8:12] == b"WAVE":
        return ".wav"
    if data[:4] == b"ftyp" or data[4:8] == b"ftyp":
        return ".mp4"
    return ".mp3"