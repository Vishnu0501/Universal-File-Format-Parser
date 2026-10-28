from typing import Iterator
from parser.record import Record, RecordType, Severity

try:
    import defusedxml.ElementTree as ET
    _DEFUSED = True
except ImportError:
    import xml.etree.ElementTree as ET
    _DEFUSED = False


def parse_xml(data: bytes) -> Iterator[Record]:
    if not _DEFUSED:
        yield Record(
            type=RecordType.WARNING,
            format="xml",
            reason="defusedxml not installed; XXE attacks are not blocked",
            severity=Severity.HIGH,
        )
    try:
        root = ET.fromstring(data)
        yield Record(
            type=RecordType.DATA,
            format="xml",
            content=_element_to_dict(root),
        )
    except ET.ParseError as e:
        yield Record(
            type=RecordType.ERROR,
            format="xml",
            reason=f"XML parse error: {e}",
            offset=_parse_error_offset(e, data),
        )
    except Exception as e:
        yield Record(type=RecordType.ERROR, format="xml", reason=str(e))


def _element_to_dict(element) -> dict:
    result: dict = {}
    if element.attrib:
        result["@attributes"] = dict(element.attrib)
    if element.text and element.text.strip():
        result["#text"] = element.text.strip()
    children: dict = {}
    for child in element:
        child_dict = _element_to_dict(child)
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag in children:
            if not isinstance(children[tag], list):
                children[tag] = [children[tag]]
            children[tag].append(child_dict)
        else:
            children[tag] = child_dict
    result.update(children)
    return {element.tag.split("}")[-1] if "}" in element.tag else element.tag: result}


def _parse_error_offset(e: Exception, data: bytes) -> int:
    try:
        msg = str(e)
        import re
        m = re.search(r"line (\d+), column (\d+)", msg)
        if m:
            line, col = int(m.group(1)), int(m.group(2))
            lines = data.split(b"\n")
            return sum(len(l) + 1 for l in lines[: line - 1]) + col
    except Exception:
        pass
    return 0