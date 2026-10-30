"""Namespace-agnostic XML helpers."""

from __future__ import annotations

import pytest

from hp_printer.exceptions import HPPrinterResponseError
from hp_printer.xml_utils import escape, parse_xml, xml_document

DOC = """<?xml version="1.0"?>
<a:Root xmlns:a="urn:a" xmlns:b="urn:b" b:attr="1">
  <a:Child><b:Leaf>  one </b:Leaf><b:Leaf/><b:Num>12.0</b:Num><b:Flag>enabled</b:Flag>
  <b:Bad>x</b:Bad><b:Nan>NaN</b:Nan></a:Child>
  <a:Child><b:Leaf>two</b:Leaf></a:Child>
  <a:Other><a:Deep><b:Leaf>three</b:Leaf></a:Deep></a:Other>
</a:Root>"""


def test_navigation() -> None:
    root = parse_xml(DOC)
    assert root.tag == "Root"
    assert root.attrib == {"attr": "1"}
    assert root.get("Child/Leaf") == "one"
    assert root.texts("Child/Leaf") == ["one", "two"]  # every parent is followed
    assert [n.text for n in root.findall("//Leaf")] == ["one", None, "two", "three"]
    assert root.texts("//Leaf") == ["one", "two", "three"]
    assert root.find("Nope") is None and root.get("Nope", "d") == "d"
    assert root.findall("Nope/Leaf") == []
    assert root.find("") is root
    assert root.get_int("Child/Num") == 12
    assert root.get_int("Child/Bad", 7) == 7
    assert root.get_float("Child/Num") == 12.0
    assert root.get_float("Child/Nan", 1.5) == 1.5
    assert root.get_float("Child/Bad") is None
    assert root.get_bool("Child/Flag") is True
    assert root.get_bool("Child/Bad", False) is False
    assert root.get_bool("Child/Nope") is None
    assert [c.tag for c in root.children] == ["Child", "Child", "Other"]
    assert len(list(root.iter("Child"))) == 2
    first_leaf = root.find("Child/Leaf")
    assert first_leaf is not None and first_leaf.children == []
    data = root.to_dict()
    assert isinstance(data["Root"], dict)
    assert data["Root"]["Other"] == {"Deep": {"Leaf": "three"}}
    assert isinstance(data["Root"]["Child"], list)


def test_parse_errors_and_builders() -> None:
    with pytest.raises(HPPrinterResponseError):
        parse_xml(b"<not xml")
    doc = xml_document("p:Root", {"p": "urn:p", "dd": "urn:dd"}, "<dd:X>1</dd:X>")
    assert doc.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert 'xmlns:p="urn:p" xmlns:dd="urn:dd"' in doc
    assert parse_xml(doc).get("X") == "1"
    assert escape('a<b>&"c"') == "a&lt;b&gt;&amp;&quot;c&quot;"
