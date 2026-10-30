"""eSCL scan settings serialisation."""

from __future__ import annotations

import pytest

from hp_printer.escl import ScanSettings
from hp_printer.xml_utils import parse_xml


def test_default_settings_xml() -> None:
    xml = ScanSettings().to_xml(2550, 3508)
    node = parse_xml(xml)
    assert node.tag == "ScanSettings"
    assert node.get("Version") == "2.63"
    assert node.get("ScanRegions/ScanRegion/Width") == "2550"
    assert node.get("ScanRegions/ScanRegion/Height") == "3508"
    assert node.get("ScanRegions/ScanRegion/ContentRegionUnits") == (
        "escl:ThreeHundredthsOfInches"
    )
    assert node.get("InputSource") == "Platen"
    assert node.get("ColorMode") == "RGB24"
    assert node.get("XResolution") == "300" and node.get("YResolution") == "300"
    assert node.get("DocumentFormat") == "image/jpeg"
    assert node.get("DocumentFormatExt") == "image/jpeg"
    assert node.get("Intent") == "Document"
    assert node.find("Duplex") is None
    assert 'xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03"' in xml
    assert 'xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm"' in xml


def test_page_size_and_clamping() -> None:
    settings = ScanSettings.for_page("letter", resolution=600, color_mode="Grayscale8")
    assert settings.width == 2550 and settings.height == 3300
    node = parse_xml(settings.to_xml(2480, 3508))
    assert node.get("ScanRegions/ScanRegion/Width") == "2480"  # clamped to platen
    assert node.get("ScanRegions/ScanRegion/Height") == "3300"
    assert node.get("ColorMode") == "Grayscale8"
    maxed = ScanSettings.for_page("max")
    assert maxed.width is None and maxed.height is None
    node = parse_xml(maxed.to_xml(None, None))
    assert node.get("ScanRegions/ScanRegion/Width") == "2550"
    with pytest.raises(KeyError):
        ScanSettings.for_page("tabloid")


def test_feeder_duplex_and_adjustments() -> None:
    settings = ScanSettings(
        source="adf",
        duplex=True,
        document_format="application/pdf",
        intent=None,
        brightness=1200,
        contrast=900,
        threshold=100,
        x_offset=10,
        y_offset=20,
    )
    assert settings.extension == "pdf"
    node = parse_xml(settings.to_xml(2550, 4200))
    assert node.get("InputSource") == "Feeder"
    assert node.get("Duplex") == "true"
    assert node.find("Intent") is None
    assert node.get("Brightness") == "1200"
    assert node.get("Contrast") == "900"
    assert node.get("Threshold") == "100"
    assert node.get("ScanRegions/ScanRegion/XOffset") == "10"
    assert ScanSettings().extension == "jpg"
    platen_duplex = ScanSettings(duplex=True)
    assert parse_xml(platen_duplex.to_xml(1, 1)).find("Duplex") is None
