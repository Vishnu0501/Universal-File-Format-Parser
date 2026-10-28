from typing import Iterator
from parser.record import Record, RecordType

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


def parse_yaml(data: bytes) -> Iterator[Record]:
    if not _YAML_AVAILABLE:
        yield Record(
            type=RecordType.ERROR,
            format="yaml",
            reason="pyyaml is not installed",
        )
        return

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        yield Record(type=RecordType.ERROR, format="yaml", reason="Could not decode YAML as UTF-8", offset=0)
        return

    try:
        documents = list(yaml.safe_load_all(text))
        for i, doc in enumerate(documents):
            yield Record(
                type=RecordType.DATA,
                format="yaml",
                content=doc,
                metadata={"document_index": i},
            )
    except yaml.YAMLError as e:
        offset = _yaml_error_offset(e, data)
        yield Record(
            type=RecordType.ERROR,
            format="yaml",
            reason=f"YAML parse error: {e}",
            offset=offset,
        )
    except Exception as e:
        yield Record(type=RecordType.ERROR, format="yaml", reason=str(e))


def _yaml_error_offset(e, data: bytes) -> int:
    try:
        if hasattr(e, "problem_mark") and e.problem_mark:
            mark = e.problem_mark
            lines = data.split(b"\n")
            return sum(len(l) + 1 for l in lines[: mark.line]) + mark.column
    except Exception:
        pass
    return 0