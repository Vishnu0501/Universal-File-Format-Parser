from typing import Iterator
from parser.record import Record, RecordType

try:
    import tomllib
    _TOMLLIB = "stdlib"
except ImportError:
    try:
        import tomli as tomllib
        _TOMLLIB = "tomli"
    except ImportError:
        tomllib = None
        _TOMLLIB = None


def parse_toml(data: bytes) -> Iterator[Record]:
    if tomllib is None:
        yield Record(
            type=RecordType.ERROR,
            format="toml",
            reason="No TOML library available. Install tomli (pip install tomli) on Python < 3.11",
        )
        return

    try:
        content = tomllib.loads(data.decode("utf-8-sig"))
        yield Record(
            type=RecordType.DATA,
            format="toml",
            content=content,
            metadata={"parser": _TOMLLIB},
        )
    except UnicodeDecodeError:
        yield Record(type=RecordType.ERROR, format="toml", reason="Could not decode TOML as UTF-8", offset=0)
    except Exception as e:
        yield Record(type=RecordType.ERROR, format="toml", reason=f"TOML parse error: {e}")