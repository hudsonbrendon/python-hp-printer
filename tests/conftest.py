"""Shared fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hp_printer.xml_utils import Node, parse_xml

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> bytes:
    """Return the raw bytes of a fixture file."""
    return (FIXTURES / name).read_bytes()


def load_xml(name: str) -> Node:
    """Parse a fixture as a namespace-free node."""
    return parse_xml(load_fixture(name))


def load_json(name: str) -> Any:
    """Parse a JSON fixture."""
    return json.loads(load_fixture(name))


@pytest.fixture
def fixture_bytes():
    """Factory fixture returning raw fixture bytes."""
    return load_fixture
