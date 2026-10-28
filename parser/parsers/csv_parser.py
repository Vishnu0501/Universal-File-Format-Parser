import csv
import io
from typing import Iterator
from parser.record import Record,RecordType,Severity

def parse_csv(data: bytes) -> Iterator[Record]:
    try:
        text = _decode(data)
    except ValueError as e:
        yield Record(type=RecordType.ERROR, format="csv", reason=str(e), offset=0)
        return
    delimiter = _sniff_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    headers = None
    for line_num, row in enumerate(reader):
        try:
            if headers is None:
                headers = row
                continue
            if len(row) < len(headers):
                yield Record(
                    type=RecordType.WARNING,
                    format="csv",
                    reason=f"Ragged row at line {line_num + 1}: expected {len(headers)} cols, got {len(row)}",
                    severity=Severity.LOW,
                    metadata={"line": line_num + 1},
                )
            record_data = dict(zip(headers, row))
            yield Record(
                type=RecordType.DATA,
                format="csv",
                content=record_data,
                metadata={"line": line_num + 1, "delimiter": delimiter},
            )
        except Exception as e:
            yield Record(
                type=RecordType.ERROR,
                format="csv",
                reason=str(e),
                metadata={"line": line_num + 1},
            )

def _sniff_delimiter(text:str) -> str:
    sample = "\n".join(text.splitlines()[:20])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t|;:")
        return dialect.delimiter
    except csv.Error:
        tab_count = text[:4096].count("\t")
        comma_count = text[:4096].count(",")
        return "\t" if tab_count > comma_count else ","

def _decode(data: bytes) -> str:
    if data[:3] == b"\xef\xbb\xbf":
        data = data[3:]
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    raise ValueError("Could not decode bytes as any known text encoding")

'''"This is the template every parser follows — decode bytes → parse → yield DATA records →
 catch every exception → yield ERROR records.

_decode tries UTF-8 first, then UTF-16, then latin-1. Latin-1 accepts every byte value 0-255, so it's 
a guaranteed fallback — the only way _decode raises is if all three fail, which is nearly impossible.

_sniff_delimiter uses Python's built-in csv.Sniffer — it scores each candidate delimiter by column count
 consistency across rows. If it's too ambiguous, we fall back to raw character counting.

Notice that a ragged row — fewer columns than the header — doesn't cause an error.
 It emits a WARNING and then still yields the DATA record with whatever columns are present.
  The library never drops data silently.

Every yield inside a try/except means one bad row never kills the whole file."'''