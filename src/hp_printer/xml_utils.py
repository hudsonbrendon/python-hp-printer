"""Namespace-agnostic helpers around ``xml.etree.ElementTree``.

HP LEDM documents use a dozen namespaces (``dd``, ``dd2``, ``psdyn``,
``ccdyn``...) and the prefixes change between firmware generations. The data
model only cares about local names, so every tag and attribute is stripped of
its namespace right after parsing and paths are expressed as plain
``Parent/Child`` strings.
"""

from __future__ import annotations

from collections.abc import Iterator
import xml.etree.ElementTree as ET

from .exceptions import HPPrinterResponseError

_TRUE_VALUES = frozenset({"true", "enabled", "on", "yes", "1", "registered"})
_FALSE_VALUES = frozenset({"false", "disabled", "off", "no", "0", "unregistered"})


def localname(tag: str) -> str:
    """Return the local part of a possibly namespaced tag."""
    return tag.rsplit("}", 1)[-1]


class Node:
    """Thin wrapper around an element with namespace-free lookups."""

    __slots__ = ("_el",)

    def __init__(self, element: ET.Element) -> None:
        """Wrap an element whose tags were already stripped of namespaces."""
        self._el = element

    @property
    def tag(self) -> str:
        """Local tag name."""
        return self._el.tag

    @property
    def text(self) -> str | None:
        """Stripped text content, ``None`` when empty."""
        if self._el.text is None:
            return None
        text = self._el.text.strip()
        return text or None

    @property
    def attrib(self) -> dict[str, str]:
        """Attributes with namespace-free keys."""
        return dict(self._el.attrib)

    @property
    def children(self) -> list[Node]:
        """Direct child nodes."""
        return [Node(child) for child in self._el]

    def iter(self, tag: str) -> Iterator[Node]:
        """Iterate over every descendant with the given local name."""
        for element in self._el.iter(tag):
            if element is not self._el:
                yield Node(element)

    def find(self, path: str) -> Node | None:
        """Return the first node matching ``A/B/C`` or ``//C`` (any depth)."""
        results = self.findall(path)
        return results[0] if results else None

    def findall(self, path: str) -> list[Node]:
        """Return every node matching the path.

        Every step matches all children with that local name (so repeated
        parents such as ``Status/StatusCategory`` return every category). A
        leading ``//`` searches descendants at any depth.
        """
        if path.startswith("//"):
            return list(self.iter(path[2:]))
        parts = [part for part in path.split("/") if part and part != "."]
        if not parts:
            return [self]
        current: list[ET.Element] = [self._el]
        for part in parts:
            current = [child for el in current for child in el if child.tag == part]
            if not current:
                return []
        return [Node(el) for el in current]

    def get(self, path: str, default: str | None = None) -> str | None:
        """Text of the first node matching the path."""
        node = self.find(path)
        if node is None or node.text is None:
            return default
        return node.text

    def get_int(self, path: str, default: int | None = None) -> int | None:
        """Integer value of the first node matching the path."""
        value = self.get(path)
        if value is None:
            return default
        try:
            return int(float(value))
        except ValueError:
            return default

    def get_float(self, path: str, default: float | None = None) -> float | None:
        """Float value of the first node matching the path."""
        value = self.get(path)
        if value is None:
            return default
        try:
            result = float(value)
        except ValueError:
            return default
        return default if result != result else result  # noqa: PLR0124  (NaN)

    def get_bool(self, path: str, default: bool | None = None) -> bool | None:
        """Boolean value (true/enabled/on) of the first node matching the path."""
        value = self.get(path)
        if value is None:
            return default
        lowered = value.lower()
        if lowered in _TRUE_VALUES:
            return True
        if lowered in _FALSE_VALUES:
            return False
        return default

    def texts(self, path: str) -> list[str]:
        """Text of every node matching the path, skipping empty ones."""
        return [node.text for node in self.findall(path) if node.text is not None]

    def to_dict(self) -> dict[str, object]:
        """Recursively convert the subtree to plain dictionaries (debugging)."""
        children = self.children
        if not children:
            return {self.tag: self.text}
        result: dict[str, object] = {}
        for child in children:
            value = child.to_dict()[child.tag]
            if child.tag in result:
                existing = result[child.tag]
                if isinstance(existing, list):
                    existing.append(value)
                else:
                    result[child.tag] = [existing, value]
            else:
                result[child.tag] = value
        return {self.tag: result}


def parse_xml(data: bytes | str) -> Node:
    """Parse an XML document and strip every namespace from tags/attributes."""
    try:
        root = ET.fromstring(data)  # noqa: S314  LAN device payload, no DTD/entities
    except ET.ParseError as err:
        raise HPPrinterResponseError(f"Invalid XML from printer: {err}") from err
    for element in root.iter():
        element.tag = localname(element.tag)
        if element.attrib:
            element.attrib = {localname(k): v for k, v in element.attrib.items()}
    return Node(root)


def xml_document(root: str, namespaces: dict[str, str], body: str) -> str:
    """Build an XML document with the given root element and namespaces.

    ``root`` is the qualified root tag (``prefix:Tag``); ``namespaces`` maps
    prefixes to URIs; ``body`` is the already-serialised inner XML.
    """
    declarations = " ".join(
        f'xmlns:{prefix}="{uri}"' for prefix, uri in namespaces.items()
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<{root} {declarations}>{body}</{root}>"
    )


def escape(value: object) -> str:
    """Escape a value for use as XML text."""
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
