"""eSCL (AirScan / Mopria Scan) request building."""

from __future__ import annotations

from dataclasses import dataclass

from .const import NS_ESCL, NS_PWG
from .xml_utils import escape

ESCL_UNITS = "escl:ThreeHundredthsOfInches"

# Common page sizes in 1/300 inch (width, height).
PAGE_SIZES: dict[str, tuple[int, int]] = {
    "a4": (2480, 3508),
    "letter": (2550, 3300),
    "legal": (2550, 4200),
    "a5": (1748, 2480),
    "a6": (1240, 1748),
    "photo_4x6": (1200, 1800),
    "photo_5x7": (1500, 2100),
    "max": (0, 0),
}

COLOR_MODES = ("BlackAndWhite1", "Grayscale8", "RGB24")
INPUT_SOURCES = ("Platen", "Feeder")
DOCUMENT_FORMATS = ("image/jpeg", "application/pdf")
INTENTS = ("Document", "Photo", "Preview", "TextAndGraphic")


@dataclass(slots=True, kw_only=True)
class ScanSettings:
    """Parameters of an eSCL scan job.

    Dimensions are expressed in 1/300 inch like the eSCL spec. When ``width``
    or ``height`` are ``None`` the full scan area advertised by the scanner is
    used.
    """

    source: str = "Platen"
    color_mode: str = "RGB24"
    resolution: int = 300
    document_format: str = "image/jpeg"
    intent: str | None = "Document"
    width: int | None = None
    height: int | None = None
    x_offset: int = 0
    y_offset: int = 0
    brightness: int | None = None
    contrast: int | None = None
    threshold: int | None = None
    duplex: bool = False
    version: str = "2.63"

    @classmethod
    def for_page(cls, size: str = "a4", **kwargs: object) -> ScanSettings:
        """Create settings sized for a well known page format."""
        width, height = PAGE_SIZES[size.lower()]
        settings = cls(**kwargs)  # type: ignore[arg-type]
        if width and height:
            settings.width = width
            settings.height = height
        return settings

    def to_xml(self, max_width: int | None, max_height: int | None) -> str:
        """Serialise to the ``scan:ScanSettings`` document the scanner expects."""
        width = self.width or max_width or 2550
        height = self.height or max_height or 3508
        if max_width:
            width = min(width, max_width)
        if max_height:
            height = min(height, max_height)
        source = "Feeder" if self.source.lower() in ("adf", "feeder") else "Platen"
        parts = [
            f"<pwg:Version>{escape(self.version)}</pwg:Version>",
            "<pwg:ScanRegions>",
            "<pwg:ScanRegion>",
            f"<pwg:ContentRegionUnits>{ESCL_UNITS}</pwg:ContentRegionUnits>",
            f"<pwg:XOffset>{self.x_offset}</pwg:XOffset>",
            f"<pwg:YOffset>{self.y_offset}</pwg:YOffset>",
            f"<pwg:Width>{width}</pwg:Width>",
            f"<pwg:Height>{height}</pwg:Height>",
            "</pwg:ScanRegion>",
            "</pwg:ScanRegions>",
            f"<pwg:InputSource>{source}</pwg:InputSource>",
            f"<scan:ColorMode>{escape(self.color_mode)}</scan:ColorMode>",
            f"<scan:XResolution>{self.resolution}</scan:XResolution>",
            f"<scan:YResolution>{self.resolution}</scan:YResolution>",
            f"<pwg:DocumentFormat>{escape(self.document_format)}</pwg:DocumentFormat>",
            (
                f"<scan:DocumentFormatExt>{escape(self.document_format)}"
                "</scan:DocumentFormatExt>"
            ),
        ]
        if self.intent:
            parts.append(f"<scan:Intent>{escape(self.intent)}</scan:Intent>")
        if source == "Feeder" and self.duplex:
            parts.append("<scan:Duplex>true</scan:Duplex>")
        if self.brightness is not None:
            parts.append(f"<scan:Brightness>{self.brightness}</scan:Brightness>")
        if self.contrast is not None:
            parts.append(f"<scan:Contrast>{self.contrast}</scan:Contrast>")
        if self.threshold is not None:
            parts.append(f"<scan:Threshold>{self.threshold}</scan:Threshold>")
        body = "".join(parts)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<scan:ScanSettings xmlns:scan="{NS_ESCL}" xmlns:pwg="{NS_PWG}">'
            f"{body}</scan:ScanSettings>"
        )

    @property
    def extension(self) -> str:
        """File extension matching ``document_format``."""
        return "pdf" if "pdf" in self.document_format else "jpg"
