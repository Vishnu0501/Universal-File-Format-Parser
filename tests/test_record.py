import pytest
from parser.record import Record, RecordType, Severity


def test_data_record():
    r = Record(type=RecordType.DATA, format="csv", content={"name": "Alice"})
    assert r.type == RecordType.DATA
    assert r.format == "csv"
    assert r.content == {"name": "Alice"}
    assert r.offset is None
    assert r.reason is None
    assert r.severity is None
    assert r.metadata == {}


def test_error_record():
    r = Record(type=RecordType.ERROR, format="pdf", reason="corrupt xref", offset=1024)
    assert r.type == RecordType.ERROR
    assert r.reason == "corrupt xref"
    assert r.offset == 1024
    assert r.content is None


def test_warning_record():
    r = Record(
        type=RecordType.WARNING,
        format="zip",
        reason="zip bomb",
        severity=Severity.CRITICAL,
        metadata={"ratio": 200},
    )
    assert r.type == RecordType.WARNING
    assert r.severity == Severity.CRITICAL
    assert r.metadata["ratio"] == 200


def test_record_type_values():
    assert RecordType.DATA == "data"
    assert RecordType.ERROR == "error"
    assert RecordType.WARNING == "warning"


def test_severity_ordering():
    levels = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
    assert all(isinstance(s, str) for s in levels)


def test_metadata_default_is_independent():
    r1 = Record(type=RecordType.DATA, format="csv")
    r2 = Record(type=RecordType.DATA, format="csv")
    r1.metadata["key"] = "val"
    assert "key" not in r2.metadata
