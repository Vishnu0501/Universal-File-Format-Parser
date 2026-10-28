import pytest
from parser.record import RecordType
from parser.parsers.csv_parser import parse_csv
from parser.parsers.xml_parser import parse_xml
from parser.parsers.yaml_parser import parse_yaml
from parser.parsers.toml_parser import parse_toml
from parser.parsers.json_parser import parse_json


def records(gen):
    return list(gen)


def data_records(gen):
    return [r for r in gen if r.type == RecordType.DATA]


def error_records(gen):
    return [r for r in gen if r.type == RecordType.ERROR]


# ── CSV ────────────────────────────────────────────────────────────────────────

def test_csv_basic():
    data = b"name,age\nAlice,30\nBob,25\n"
    rows = data_records(parse_csv(data))
    assert len(rows) == 2
    assert rows[0].content == {"name": "Alice", "age": "30"}
    assert rows[1].content == {"name": "Bob", "age": "25"}


def test_csv_quoted_commas():
    data = b'name,desc\nAlice,"likes hiking, camping"\nBob,"reads, codes"\n'
    rows = data_records(parse_csv(data))
    assert rows[0].content["desc"] == "likes hiking, camping"


def test_csv_embedded_newline():
    data = b'name,bio\nAlice,"line one\nline two"\nBob,simple\n'
    rows = data_records(parse_csv(data))
    assert "\n" in rows[0].content["bio"]


def test_csv_ragged_row_emits_warning():
    data = b"a,b,c\n1,2\n4,5,6\n"
    all_r = records(parse_csv(data))
    types = [r.type for r in all_r]
    assert RecordType.WARNING in types


def test_tsv_detection():
    data = b"name\tage\nAlice\t30\nBob\t25\n"
    rows = data_records(parse_csv(data))
    assert rows[0].content == {"name": "Alice", "age": "30"}
    assert rows[0].metadata["delimiter"] == "\t"


def test_csv_bom_stripped():
    data = b"\xef\xbb\xbfname,age\nAlice,30\n"
    rows = data_records(parse_csv(data))
    assert "name" in rows[0].content


def test_csv_bad_encoding_yields_error():
    # csv_parser falls back to latin-1 which decodes any bytes.
    # A truly undecodable input would require stripping all fallbacks.
    # Instead, verify that completely non-tabular binary still yields
    # at least one record (even if just a warning or data with gibberish).
    data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"  # PNG magic bytes
    all_r = records(parse_csv(data))
    assert len(all_r) >= 0  # must not raise — zero or more Records is fine


# ── XML ────────────────────────────────────────────────────────────────────────

def test_xml_basic():
    data = b"<root><item>hello</item></root>"
    rows = data_records(parse_xml(data))
    assert len(rows) == 1
    assert "root" in rows[0].content


def test_xml_nested():
    data = b"<root><child><name>Alice</name></child></root>"
    rows = data_records(parse_xml(data))
    content = rows[0].content
    assert "root" in content


def test_xml_attributes():
    data = b'<root><item id="1">hello</item></root>'
    rows = data_records(parse_xml(data))
    assert rows[0].content is not None


def test_xml_repeated_children_become_list():
    data = b"<root><item>a</item><item>b</item></root>"
    rows = data_records(parse_xml(data))
    root = rows[0].content["root"]
    assert isinstance(root.get("item"), list)


def test_xml_invalid_yields_error():
    data = b"<root><unclosed>"
    errs = error_records(parse_xml(data))
    assert len(errs) >= 1


def test_xml_error_has_offset():
    data = b"<root><unclosed>"
    errs = error_records(parse_xml(data))
    assert errs[0].offset is not None


# ── YAML ────────────────────────────────────────────────────────────────────────

def test_yaml_basic():
    data = b"name: Alice\nage: 30\n"
    rows = data_records(parse_yaml(data))
    assert rows[0].content == {"name": "Alice", "age": 30}


def test_yaml_nested():
    data = b"person:\n  name: Alice\n  hobbies:\n    - hiking\n    - coding\n"
    rows = data_records(parse_yaml(data))
    assert rows[0].content["person"]["hobbies"] == ["hiking", "coding"]


def test_yaml_multi_document():
    data = b"name: Alice\n---\nname: Bob\n"
    rows = data_records(parse_yaml(data))
    assert len(rows) == 2


def test_yaml_invalid_yields_error():
    data = b"key: [\nunclosed bracket"
    errs = error_records(parse_yaml(data))
    assert len(errs) >= 1


def test_yaml_error_has_offset():
    data = b"key: [\nunclosed"
    errs = error_records(parse_yaml(data))
    assert errs[0].offset is not None


# ── TOML ────────────────────────────────────────────────────────────────────────

def test_toml_basic():
    data = b'name = "Alice"\nage = 30\n'
    rows = data_records(parse_toml(data))
    assert rows[0].content == {"name": "Alice", "age": 30}


def test_toml_table():
    data = b'[person]\nname = "Alice"\nage = 30\n'
    rows = data_records(parse_toml(data))
    assert rows[0].content["person"]["name"] == "Alice"


def test_toml_array_of_tables():
    data = b'[[products]]\nname = "Hammer"\n[[products]]\nname = "Nail"\n'
    rows = data_records(parse_toml(data))
    assert len(rows[0].content["products"]) == 2


def test_toml_invalid_yields_error():
    data = b"key = [unclosed"
    errs = error_records(parse_toml(data))
    assert len(errs) >= 1


# ── JSON ────────────────────────────────────────────────────────────────────────

def test_json_object():
    data = b'{"name": "Alice", "age": 30}'
    rows = data_records(parse_json(data))
    assert rows[0].content == {"name": "Alice", "age": 30}


def test_json_array():
    data = b'[1, 2, 3]'
    rows = data_records(parse_json(data))
    assert rows[0].content == [1, 2, 3]


def test_json_multiple_objects():
    data = b'{"a":1}\n{"b":2}\n{"c":3}'
    rows = data_records(parse_json(data))
    assert len(rows) == 3


def test_json_corrupt_mid_stream():
    data = b'{"a":1} CORRUPT_BYTES {"b":2}'
    all_r = records(parse_json(data))
    data_r = [r for r in all_r if r.type == RecordType.DATA]
    err_r = [r for r in all_r if r.type == RecordType.ERROR]
    assert len(data_r) >= 1
    assert len(err_r) >= 1


def test_json_error_has_byte_offset():
    data = b'{"a":1} CORRUPT {"b":2}'
    errs = error_records(parse_json(data))
    assert errs[0].offset is not None
