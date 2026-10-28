import json
from typing import Iterator
from parser.record import Record, RecordType


def parse_json(data: bytes) -> Iterator[Record]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        yield Record(type=RecordType.ERROR, format="json", reason=f"Decode error: {e}", offset=e.start)
        return
    yield from _stream_json(text)


def _stream_json(text: str) -> Iterator[Record]:
    decoder = json.JSONDecoder()
    pos = 0
    n = len(text)

    while pos < n:
        while pos < n and text[pos] in " \t\n\r":
            pos += 1
        if pos >= n:
            break

        try:
            obj, end_pos = decoder.raw_decode(text, pos)
            yield Record(
                type=RecordType.DATA,
                format="json",
                content=obj,
                offset=pos,
            )
            pos = end_pos
        except json.JSONDecodeError as e:
            error_offset = pos + (e.pos if hasattr(e, "pos") else 0)
            yield Record(
                type=RecordType.ERROR,
                format="json",
                reason=f"JSON decode error: {e.msg}",
                offset=error_offset,
            )
            skip = _find_next_start(text, pos + 1)
            if skip is None:
                break
            pos = skip


def _find_next_start(text: str, from_pos: int) -> int | None:
    for i in range(from_pos, len(text)):
        if text[i] in "{[\"0123456789tfn-":
            return i
    return None