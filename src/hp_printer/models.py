"""Data models parsed from LEDM, eSCL, CDM and IPP documents."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
import json
from typing import Any, Self

from .const import (
    BUSY_CATEGORIES,
    CONSUMABLE_COLORS,
    ERROR_CATEGORIES,
    INFO_CATEGORIES,
    IPP_JOB_STATES,
    IPP_PRINTER_STATES,
    MARKER_COLOR_TO_LABEL,
    SLEEP_CATEGORIES,
    PrinterState,
)
from .xml_utils import Node


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _decode_hex_string(value: str | None) -> str | None:
    """Decode hex-encoded SSIDs (``434153415f...`` -> ``CASA_...``)."""
    if not value:
        return None
    stripped = value.strip()
    if len(stripped) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in stripped):
        try:
            decoded = bytes.fromhex(stripped).decode("utf-8")
        except ValueError, UnicodeDecodeError:
            return stripped
        if decoded.isprintable():
            return decoded
    return stripped


def _format_mac(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.replace(":", "").replace("-", "").lower()
    if len(raw) != 12:
        return value
    return ":".join(raw[i : i + 2] for i in range(0, 12, 2))


class _Model:
    """Mixin providing ``as_dict``/``as_json`` for every dataclass model."""

    def as_dict(self) -> dict[str, Any]:
        """Return the model as plain dictionaries (dates become ISO strings)."""
        result: dict[str, Any] = json.loads(self.as_json())
        return result

    def as_json(self) -> str:
        """Return the model serialised as JSON."""
        return json.dumps(asdict(self), default=_json_default)  # type: ignore[call-overload]


def _json_default(value: object) -> object:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (set, frozenset)):
        return sorted(str(v) for v in value)
    return str(value)


# --------------------------------------------------------------------------- #
# Capabilities / discovery
# --------------------------------------------------------------------------- #
@dataclass(slots=True, kw_only=True)
class Capabilities(_Model):
    """What the printer exposes, derived from the LEDM discovery tree and CDM."""

    ledm_resources: set[str] = field(default_factory=set)
    ledm_manifests: set[str] = field(default_factory=set)
    cdm_services: set[str] = field(default_factory=set)
    cdm_links: dict[str, str] = field(default_factory=dict)
    has_ledm: bool = False
    has_cdm: bool = False
    has_escl: bool = False
    has_ipp: bool = True
    has_scanner: bool = False
    has_copy: bool = False
    has_fax: bool = False
    has_firmware_update: bool = False
    has_internal_print: bool = False
    has_calibration: bool = False
    has_product_actions: bool = False
    has_eprint: bool = False
    has_event_mgmt: bool = False
    has_jobs: bool = False
    has_io_mgmt: bool = False

    @classmethod
    def from_discovery(cls, tree: Node | None, services: dict[str, Any] | None) -> Self:
        """Build from ``/DevMgmt/DiscoveryTree.xml`` and ``/cdm/servicesDiscovery``."""
        caps = cls()
        if tree is not None:
            caps.has_ledm = True
            caps.ledm_resources = set(tree.texts("//ResourceURI"))
            caps.ledm_manifests = set(tree.texts("//ManifestURI"))
            manifests = " ".join(caps.ledm_manifests).lower()
            caps.has_escl = "/escl/" in manifests
            caps.has_scanner = caps.has_escl or "/scan/" in manifests
            caps.has_copy = "/copy/" in manifests
            caps.has_fax = "/fax/" in manifests
            caps.has_firmware_update = "/firmwareupdate/" in manifests
            caps.has_internal_print = "internalprint" in manifests
            caps.has_calibration = "/calibration/" in manifests
            caps.has_product_actions = "/productactions/" in manifests
            caps.has_eprint = "/eprint/" in manifests
            caps.has_event_mgmt = "/eventmgmt/" in manifests
            caps.has_jobs = "/jobs/" in manifests
            caps.has_io_mgmt = "/iomgmt/" in manifests
            caps.has_ipp = any("ipp" in r.lower() for r in caps.ledm_resources) or True
        if services:
            caps.has_cdm = True
            for service in services.get("services", []):
                gun = str(service.get("serviceGun", ""))
                caps.cdm_services.add(gun)
                for link in service.get("links", []):
                    rel = link.get("rel")
                    href = link.get("href")
                    if rel and href and link.get("state") != "unavailable":
                        caps.cdm_links[f"{gun}#{rel}"] = href
        return caps

    def has_resource(self, path: str) -> bool:
        """Return True when the LEDM discovery tree lists the resource."""
        return path in self.ledm_resources or not self.ledm_resources

    def cdm_href(self, service_fragment: str, rel: str) -> str | None:
        """Return the href of a CDM service link (``print`` + ``configuration``)."""
        for key, href in self.cdm_links.items():
            gun, _, link_rel = key.partition("#")
            if service_fragment in gun and link_rel == rel:
                return href
        return None


# --------------------------------------------------------------------------- #
# Device information & settings (ProductConfigDyn / Cap)
# --------------------------------------------------------------------------- #
@dataclass(slots=True, kw_only=True)
class DeviceInfo(_Model):
    """Static identification of the printer."""

    make_and_model: str | None = None
    model_family: str | None = None
    sku: str | None = None
    uuid: str | None = None
    serial_number: str | None = None
    product_number: str | None = None
    service_id: str | None = None
    firmware_version: str | None = None
    firmware_date: date | None = None
    manufacturer: str | None = None
    manufacture_date: date | None = None
    password_set: bool | None = None
    languages: list[str] = field(default_factory=list)
    region_id: int | None = None
    total_memory_kb: int | None = None
    available_memory_kb: int | None = None
    control_panel_display: str | None = None

    @classmethod
    def from_node(cls, root: Node) -> Self:
        """Parse ``ProductConfigDyn``."""
        info = root.find("ProductInformation")
        if info is None:
            info = root
        return cls(
            make_and_model=info.get("MakeAndModel"),
            model_family=info.get("MakeAndModelFamily"),
            sku=info.get("SKUIdentifier"),
            uuid=info.get("UUID"),
            serial_number=info.get("SerialNumber"),
            product_number=info.get("ProductNumber"),
            service_id=info.get("ServiceID"),
            firmware_version=info.get("Version/Revision"),
            firmware_date=_parse_date(info.get("Version/Date")),
            manufacturer=info.get("Manufacturer/Name"),
            manufacture_date=_parse_date(info.get("Manufacturer/Date")),
            password_set=(info.get("PasswordStatus") or "").lower() == "set"
            if info.get("PasswordStatus")
            else None,
            languages=info.texts("AvailableLanguages/Language"),
            region_id=info.get_int("RegionInformation/RegionIdentifier"),
            total_memory_kb=root.get_int("Memory/TotalMemory"),
            available_memory_kb=root.get_int("Memory/AvailableMemory"),
            control_panel_display=root.get("ProductSettings/ControlPanel/Display"),
        )

    @property
    def name(self) -> str:
        """Best human readable name."""
        return self.model_family or self.make_and_model or "HP Printer"


@dataclass(slots=True, kw_only=True)
class Settings(_Model):
    """User-changeable product settings (``ProductSettings``)."""

    power_save_timeout: str | None = None
    auto_off_time: str | None = None
    device_language: str | None = None
    preferred_language: str | None = None
    country: str | None = None
    timestamp: str | None = None
    time_format: str | None = None
    date_format: str | None = None
    quiet_mode: bool | None = None
    ews_enabled: bool | None = None
    ews_urls: list[str] = field(default_factory=list)
    power_save_enabled: bool | None = None
    oobe_phase: str | None = None
    description: str | None = None
    location: str | None = None

    @classmethod
    def from_node(cls, root: Node) -> Self:
        """Parse the ``ProductSettings`` block of ``ProductConfigDyn``."""
        s = root.find("ProductSettings") or root
        return cls(
            power_save_timeout=s.get("PowerSaveTimeout"),
            auto_off_time=s.get("AutoOffTime"),
            device_language=s.get("ProductLanguage/DeviceLanguage"),
            preferred_language=s.get("ProductLanguage/PreferredLanguage"),
            country=s.get("CountryAndRegionName"),
            timestamp=s.get("TimeStamp"),
            time_format=s.get("TimeFormat"),
            date_format=s.get("DateFormat"),
            quiet_mode=s.get_bool("QuietPrintMode"),
            ews_enabled=s.get_bool("EWS/EnableDisable"),
            ews_urls=s.texts("EWS/ResourceURI"),
            power_save_enabled=s.get_bool("PowerSave"),
            oobe_phase=s.get("OobePhase"),
            description=s.get("DeviceInformation/Description"),
            location=s.get("DeviceInformation/DeviceLocation"),
        )


@dataclass(slots=True, kw_only=True)
class SettingsCapabilities(_Model):
    """Allowed values for the writable settings (``ProductConfigCap``)."""

    power_save_timeouts: list[str] = field(default_factory=list)
    auto_off_times: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    time_formats: list[str] = field(default_factory=list)
    date_formats: list[str] = field(default_factory=list)
    quiet_mode_supported: bool = False
    pages_per_minute: int | None = None
    max_color_quality: str | None = None
    max_mono_quality: str | None = None
    color_printing: bool | None = None
    document_formats: list[str] = field(default_factory=list)

    @classmethod
    def from_node(cls, root: Node) -> Self:
        """Parse ``ProductConfigCap``."""
        settings = root.find("ProductSettingsCap") or root
        info = root.find("ProductInformationCap") or root
        return cls(
            power_save_timeouts=settings.texts(
                "PowerSaveTimerSupport/PowerSaveTimeout"
            ),
            auto_off_times=settings.texts("AutoOffTimeSupport/AutoOffTime"),
            languages=settings.texts(
                "ProductLanguageSupport/DeviceLanguageSupport/DeviceLanguage"
            ),
            countries=settings.texts(
                "CountryAndRegionNameSupport/CountryAndRegionName"
            ),
            time_formats=settings.texts("TimeFormatSupport/TimeFormat"),
            date_formats=settings.texts("DateFormatSupport/DateFormat"),
            quiet_mode_supported=bool(
                settings.texts("QuietPrintModeSupport/QuietPrintMode")
            ),
            pages_per_minute=info.get_int("PrintEnginePPM"),
            max_color_quality=info.get("MaxColorPrintQuality"),
            max_mono_quality=info.get("MaxMonoPrintQuality"),
            color_printing=info.get_bool("ColorPrinting"),
            document_formats=info.texts(
                "PersonalitySupport/Interpreter/DocumentFormat"
            ),
        )


# --------------------------------------------------------------------------- #
# Status & alerts (ProductStatusDyn)
# --------------------------------------------------------------------------- #
@dataclass(slots=True, kw_only=True)
class Alert(_Model):
    """One row of the LEDM alert table."""

    id: str
    severity: str | None = None
    priority: int | None = None
    string_id: str | None = None
    sequence: int | None = None
    marker_color: str | None = None
    consumable_type: str | None = None
    marker_location: int | None = None
    user_action: str | None = None
    resource_uri: str | None = None
    details: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_node(cls, node: Node) -> Self:
        """Parse an ``Alert`` element."""
        details_node = node.find("AlertDetails")
        details = {}
        if details_node is not None:
            details = {c.tag: c.text or "" for c in details_node.children}
        return cls(
            id=node.get("ProductStatusAlertID") or "unknown",
            severity=node.get("Severity"),
            priority=node.get_int("AlertPriority"),
            string_id=node.get("StringId"),
            sequence=node.get_int("SequenceNumber"),
            marker_color=node.get("AlertDetails/AlertDetailsMarkerColor"),
            consumable_type=node.get("AlertDetails/AlertDetailsConsumableTypeEnum"),
            marker_location=node.get_int("AlertDetails/AlertDetailsMarkerLocation"),
            user_action=node.get("AlertDetails/AlertDetailsUserAction"),
            resource_uri=node.get("ResourceURI"),
            details=details,
        )

    @property
    def is_error(self) -> bool:
        """True for Error/StrictWarning severities or known error ids."""
        if self.severity in ("Error", "StrictWarning"):
            return True
        return self.id in ERROR_CATEGORIES

    @property
    def is_warning(self) -> bool:
        """True for Warning severity."""
        return self.severity == "Warning"


@dataclass(slots=True, kw_only=True)
class Status(_Model):
    """Live printer status."""

    categories: list[str] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    alert_table_modification: int | None = None

    @classmethod
    def from_node(cls, root: Node) -> Self:
        """Parse ``ProductStatusDyn``."""
        return cls(
            categories=root.texts("Status/StatusCategory"),
            alerts=[Alert.from_node(a) for a in root.findall("AlertTable/Alert")],
            alert_table_modification=root.get_int("AlertTable/ModificationNumber"),
        )

    @property
    def state(self) -> PrinterState:
        """Normalised state. Busy > error > attention > sleeping > idle."""
        for category in self.categories:
            if category in BUSY_CATEGORIES:
                return BUSY_CATEGORIES[category]
        if self.has_error:
            return PrinterState.ERROR
        if self.has_warning:
            return PrinterState.ATTENTION
        if any(c in SLEEP_CATEGORIES for c in self.categories):
            return PrinterState.SLEEPING
        if self.categories:
            return PrinterState.IDLE
        return PrinterState.UNKNOWN

    @property
    def has_error(self) -> bool:
        """True when an error alert or error category is present."""
        if any(a.is_error for a in self.alerts):
            return True
        return any(c in ERROR_CATEGORIES for c in self.categories)

    @property
    def has_warning(self) -> bool:
        """True when a warning alert or non-informational category is present."""
        if any(a.is_warning for a in self.alerts):
            return True
        return any(
            c not in INFO_CATEGORIES and c not in ERROR_CATEGORIES
            for c in self.categories
        )

    @property
    def problems(self) -> list[str]:
        """Alert ids / categories that need attention, most severe first."""
        problems = [a.id for a in self.alerts if a.is_error]
        problems += [a.id for a in self.alerts if a.is_warning and a.id not in problems]
        for category in self.categories:
            if category not in INFO_CATEGORIES and category not in problems:
                problems.append(category)
        return problems

    @property
    def is_sleeping(self) -> bool:
        """True while in power save."""
        return any(c in SLEEP_CATEGORIES for c in self.categories)

    @property
    def is_busy(self) -> bool:
        """True while printing, scanning, copying, calibrating..."""
        return any(c in BUSY_CATEGORIES for c in self.categories)


# --------------------------------------------------------------------------- #
# Consumables (ConsumableConfigDyn + ProductUsageDyn/ConsumableSubunit)
# --------------------------------------------------------------------------- #
@dataclass(slots=True, kw_only=True)
class Consumable(_Model):
    """An ink cartridge, toner, printhead or ink tank."""

    station: int | None = None
    label_code: str | None = None
    color: str | None = None
    css_color: str | None = None
    type: str | None = None
    level: int | None = None
    raw_level: int | None = None
    state: str | None = None
    measured_state: str | None = None
    brand: str | None = None
    is_genuine_hp: bool | None = None
    is_refilled: bool | None = None
    is_setup: bool | None = None
    is_trial: bool | None = None
    selectability_number: str | None = None
    supported_numbers: list[str] = field(default_factory=list)
    unique_id: str | None = None
    consumable_id: str | None = None
    family: str | None = None
    capacity: int | None = None
    capacity_unit: str | None = None
    installation_date: date | None = None
    manufacture_date: date | None = None
    warranty_expiration: date | None = None
    serial_number: str | None = None
    product_number: str | None = None
    estimated_pages_remaining: int | None = None
    counterfeit_refills: int | None = None
    genuine_refills: int | None = None
    insertions: int | None = None
    marking_agent_used: float | None = None
    marking_agent_unit: str | None = None

    @classmethod
    def from_node(cls, node: Node, supported: dict[str, list[str]]) -> Self:
        """Parse a ``ConsumableInfo`` element."""
        label = node.get("ConsumableLabelCode")
        marker = node.get("MarkerColor")
        if label is None and marker is not None:
            label = MARKER_COLOR_TO_LABEL.get(marker, marker)
        color, css = CONSUMABLE_COLORS.get(label or "", (None, None))
        if color is None and marker:
            color = marker
        state = node.get("ConsumableLifeState/ConsumableState") or node.get(
            "ConsumableState"
        )
        brand = node.get("ConsumableLifeState/Brand") or node.get("Brand")
        genuine: bool | None = None
        if state:
            genuine = "genuinehp" in state.lower() or (brand or "").upper() == "HP"
        icon_fill = node.find("ConsumableIcon/FillColor")
        if icon_fill is not None and label not in CONSUMABLE_COLORS:
            r, g, b = (
                icon_fill.get_int("Red", 0) or 0,
                icon_fill.get_int("Green", 0) or 0,
                icon_fill.get_int("Blue", 0) or 0,
            )
            css = f"#{r:02X}{g:02X}{b:02X}"
        return cls(
            station=node.get_int("ConsumableStation"),
            label_code=label,
            color=color,
            css_color=css,
            type=node.get("ConsumableTypeEnum"),
            level=node.get_int("ConsumablePercentageLevelRemaining"),
            raw_level=node.get_int("ConsumableRawPercentageLevelRemaining"),
            state=state,
            measured_state=node.get("ConsumableLifeState/MeasuredQuantityState"),
            brand=brand,
            is_genuine_hp=genuine,
            is_refilled=node.get_bool("ConsumableLifeState/IsRefilled"),
            is_setup=node.get_bool("ConsumableLifeState/IsSETUP"),
            is_trial=node.get_bool("ConsumableLifeState/IsTrial"),
            selectability_number=node.get("ConsumableSelectibilityNumber"),
            supported_numbers=supported.get(label or "", []),
            unique_id=node.get("ConsumableUniqueID"),
            consumable_id=node.get("ConsumableID"),
            family=node.get("ConsumableFamilyName"),
            capacity=node.get_int("Capacity/MaxCapacity"),
            capacity_unit=node.get("Capacity/Unit"),
            installation_date=_parse_date(node.get("Installation/Date")),
            manufacture_date=_parse_date(node.get("Manufacturer/Date")),
            warranty_expiration=_parse_date(node.get("Warranty/ExpirationDate")),
            serial_number=node.get("SerialNumber"),
            product_number=node.get("ProductNumber"),
            estimated_pages_remaining=node.get_int("EstimatedPagesRemaining"),
        )

    def merge_usage(self, node: Node) -> None:
        """Merge the matching ``ConsumableSubunit/Consumable`` usage element."""
        self.raw_level = node.get_int(
            "ConsumableRawPercentageLevelRemaining", self.raw_level
        )
        self.counterfeit_refills = node.get_int(
            "RefilledCount/CounterfeitRefilledCount"
        )
        self.genuine_refills = node.get_int("RefilledCount/GenuineRefilledCount")
        self.insertions = node.get_int("PenInsertionTriggerSnapshotCounter")
        self.marking_agent_used = node.get_float(
            "CumulativeMarkingAgentUsed/ValueFloat"
        )
        self.marking_agent_unit = node.get("CumulativeMarkingAgentUsed/Unit")
        if self.estimated_pages_remaining is None:
            self.estimated_pages_remaining = node.get_int("EstimatedPagesRemaining")
        if self.level is None:
            self.level = node.get_int("ConsumablePercentageLevelRemaining")

    @property
    def is_low(self) -> bool:
        """True when the cartridge reports a low/very low state."""
        if self.measured_state and self.measured_state.lower() not in ("ok", "unknown"):
            return True
        return bool(self.state and "low" in self.state.lower())

    @property
    def is_empty(self) -> bool:
        """True when the cartridge is depleted."""
        if self.level == 0:
            return True
        return bool(self.state and self.state.lower() in ("depleted", "empty"))


@dataclass(slots=True, kw_only=True)
class ConsumablesInfo(_Model):
    """Printer-level consumable configuration."""

    consumables: list[Consumable] = field(default_factory=list)
    user_replaceable: int | None = None
    alignment_mode: str | None = None
    single_cartridge_mode: bool | None = None
    genuine_hp_only: bool | None = None
    anti_theft: bool | None = None
    slot_direction: str | None = None

    @classmethod
    def from_node(cls, root: Node) -> Self:
        """Parse ``ConsumableConfigDyn``."""
        product = root.find("ProductConsumableInfo")
        supported: dict[str, list[str]] = {}
        if product is not None:
            for sup in product.findall("SupportedConsumables/SupportedConsumable"):
                label = sup.get("ConsumableLabelCode") or ""
                supported[label] = sup.texts(
                    "SupportedConsumableInfo/ConsumableSelectibilityNumber"
                )
        consumables = [
            Consumable.from_node(c, supported) for c in root.findall("ConsumableInfo")
        ]
        consumables.sort(key=lambda c: c.station if c.station is not None else 99)
        if product is None:
            return cls(consumables=consumables)
        return cls(
            consumables=consumables,
            user_replaceable=product.get_int("NumOfUserReplaceableConsumables"),
            alignment_mode=product.get("AlignmentMode"),
            single_cartridge_mode=product.get_bool("SingleCartridgeMode"),
            genuine_hp_only=product.get_bool("GenuineHPSuppliesOnly"),
            anti_theft=product.get_bool("AntiTheftMode"),
            slot_direction=product.get("ConsumableSlotDirection"),
        )

    def merge_usage(self, usage_root: Node) -> None:
        """Merge ``ProductUsageDyn/ConsumableSubunit`` into the consumables."""
        for node in usage_root.findall("ConsumableSubunit/Consumable"):
            station = node.get_int("ConsumableStation")
            marker = node.get("MarkerColor")
            label = MARKER_COLOR_TO_LABEL.get(marker or "", marker)
            for consumable in self.consumables:
                if (station is not None and consumable.station == station) or (
                    label and consumable.label_code == label
                ):
                    consumable.merge_usage(node)
                    if consumable.color is None and marker:
                        consumable.color = marker
                    break


# --------------------------------------------------------------------------- #
# Usage counters (ProductUsageDyn)
# --------------------------------------------------------------------------- #
@dataclass(slots=True, kw_only=True)
class Usage(_Model):
    """Lifetime counters."""

    total_impressions: int | None = None
    monochrome_impressions: int | None = None
    color_impressions: int | None = None
    simplex_sheets: int | None = None
    duplex_sheets: int | None = None
    jam_events: int | None = None
    mispick_events: int | None = None
    front_panel_cancel_presses: int | None = None
    ink_used_ml: float | None = None
    hp_ink_used_ml: float | None = None
    ink_inserted_ml: float | None = None
    network_impressions: int | None = None
    wireless_impressions: int | None = None
    usb_impressions: int | None = None
    quiet_mode_impressions: int | None = None
    ews_access_count: int | None = None
    impressions_by_media_type: dict[str, int] = field(default_factory=dict)
    impressions_by_media_size: dict[str, int] = field(default_factory=dict)
    impressions_by_quality: dict[str, int] = field(default_factory=dict)
    jobs_by_duration: dict[str, int] = field(default_factory=dict)
    impressions_by_data_path: dict[str, int] = field(default_factory=dict)
    mobile_impressions: dict[str, int] = field(default_factory=dict)
    scan_images: int | None = None
    scan_flatbed_images: int | None = None
    scan_adf_images: int | None = None
    scan_to_host_images: int | None = None
    scan_jam_events: int | None = None
    scan_mispick_events: int | None = None
    copy_impressions: int | None = None
    copy_color_impressions: int | None = None
    copy_monochrome_impressions: int | None = None
    copy_flatbed_images: int | None = None
    copy_adf_images: int | None = None
    fax_impressions: int | None = None
    print_application_impressions: int | None = None
    setup_by_os: str | None = None
    setup_by_app: str | None = None

    @classmethod
    def from_node(cls, root: Node) -> Self:
        """Parse ``ProductUsageDyn``."""
        p = root.find("PrinterSubunit") or root
        scanner = root.find("ScannerEngineSubunit")
        scan_app = root.find("ScanApplicationSubunit")
        copy = root.find("CopyApplicationSubunit")
        fax = root.find("FaxApplicationSubunit")
        print_app = root.find("PrintApplicationSubunit")
        mobile = root.find("MobileApplicationSubunit")

        by_media_type: dict[str, int] = {}
        by_quality: dict[str, int] = {"normal": 0, "draft": 0, "better": 0}
        for entry in p.findall("UsageByMediaType"):
            media = entry.get("MediaType")
            total = entry.get_int("TotalImpressions")
            if media and total is not None:
                by_media_type[media] = by_media_type.get(media, 0) + total
            quality = entry.find("UsageByQuality")
            if quality is not None:
                by_quality["normal"] += quality.get_int("NormalImpressions", 0) or 0
                by_quality["draft"] += quality.get_int("DraftImpressions", 0) or 0
                by_quality["better"] += quality.get_int("BetterImpressions", 0) or 0
        by_media_size = {}
        for entry in p.findall("UsageByMedia"):
            size = entry.get("MediaSizeName")
            total = entry.get_int("TotalImpressions")
            if size and total:
                by_media_size[size] = total
        by_duration = {}
        for entry in p.findall("UsageByTimeInterval"):
            name = entry.get("JobDuration")
            count = entry.get_int("JobCount")
            if name and count is not None:
                by_duration[name] = count
        by_path = {}
        for entry in p.findall("UsageByDataPath/ImpressionsByDataPathID"):
            name = entry.get("DataPathID")
            count = entry.get_int("TotalImpressions")
            if name and count is not None:
                by_path[name] = count
        mobile_counts: dict[str, int] = {}
        if mobile is not None:
            for entry in mobile.findall("TotalUsage"):
                key = f"{entry.get('RemoteDeviceType')}/{entry.get('DriverType')}"
                count = entry.get_int("Counter/TotalImpressions")
                if count:
                    mobile_counts[key] = count

        return cls(
            total_impressions=p.get_int("TotalImpressions"),
            monochrome_impressions=p.get_int("MonochromeImpressions"),
            color_impressions=p.get_int("ColorImpressions"),
            simplex_sheets=p.get_int("SimplexSheets"),
            duplex_sheets=p.get_int("DuplexSheets"),
            jam_events=p.get_int("JamEvents"),
            mispick_events=p.get_int("MispickEvents"),
            front_panel_cancel_presses=p.get_int("TotalFrontPanelCancelPresses"),
            ink_used_ml=p.get_float(
                "UsageByMarkingAgent/CumulativeMarkingAgentUsed/ValueFloat"
            ),
            hp_ink_used_ml=p.get_float(
                "UsageByMarkingAgent/CumulativeHPMarkingAgentUsed/ValueFloat"
            ),
            ink_inserted_ml=p.get_float(
                "UsageByMarkingAgent/CumulativeHPMarkingAgentInserted/ValueFloat"
            ),
            network_impressions=p.get_int("NetworkImpressions"),
            wireless_impressions=p.get_int("WirelessNetworkImpressions"),
            usb_impressions=p.get_int("UsbImpressions"),
            quiet_mode_impressions=p.get_int("QuietModeImpressions/TotalImpressions"),
            ews_access_count=p.get_int("EWSAccessCount"),
            impressions_by_media_type=by_media_type,
            impressions_by_media_size=by_media_size,
            impressions_by_quality=by_quality if by_media_type else {},
            jobs_by_duration=by_duration,
            impressions_by_data_path=by_path,
            mobile_impressions=mobile_counts,
            scan_images=scanner.get_int("ScanImages") if scanner else None,
            scan_flatbed_images=scanner.get_int("FlatbedImages") if scanner else None,
            scan_adf_images=scanner.get_int("AdfImages") if scanner else None,
            scan_jam_events=scanner.get_int("JamEvents") if scanner else None,
            scan_mispick_events=scanner.get_int("MispickEvents") if scanner else None,
            scan_to_host_images=scan_app.get_int("ScanToHostImages")
            if scan_app
            else None,
            copy_impressions=copy.get_int("TotalImpressions") if copy else None,
            copy_color_impressions=copy.get_int("ColorImpressions") if copy else None,
            copy_monochrome_impressions=copy.get_int("MonochromeImpressions")
            if copy
            else None,
            copy_flatbed_images=copy.get_int("FlatbedImages") if copy else None,
            copy_adf_images=copy.get_int("AdfImages") if copy else None,
            fax_impressions=fax.get_int("TotalImpressions") if fax else None,
            print_application_impressions=print_app.get_int("TotalImpressions")
            if print_app
            else None,
            setup_by_os=p.get("OOBESetupBy/SetupByOS"),
            setup_by_app=p.get("OOBESetupBy/SetupByApp"),
        )


# --------------------------------------------------------------------------- #
# Print / copy configuration
# --------------------------------------------------------------------------- #
@dataclass(slots=True, kw_only=True)
class PrintConfig(_Model):
    """Default print settings (``PrintConfigDyn``)."""

    default_copies: int | None = None
    quality: str | None = None
    resolution: str | None = None
    borderless: bool | None = None
    colorlok: bool | None = None
    jam_recovery: str | None = None
    job_timeout_seconds: int | None = None
    courier: str | None = None
    orientation: str | None = None
    ink_sliders: bool | None = None
    bits_per_pixel: int | None = None
    quality_options: list[str] = field(default_factory=list)
    resolution_options: list[str] = field(default_factory=list)
    copies_max: int | None = None

    @classmethod
    def from_node(cls, root: Node, cap: Node | None = None) -> Self:
        """Parse ``PrintConfigDyn`` (+ optional ``PrintConfigCap``)."""
        config = cls(
            default_copies=root.get_int("DefaultPrintCopies"),
            quality=root.get("PrintQuality"),
            resolution=root.get("ResolutionSetting"),
            borderless=root.get_bool("BorderlessPrinting"),
            colorlok=root.get_bool("ColorLok"),
            jam_recovery=root.get("JamRecovery"),
            job_timeout_seconds=root.get_int("JobTimeout/LeaseTime"),
            courier=root.get("DefaultCourier"),
            orientation=root.get("DefaultPDLInterpreterOrientation"),
            ink_sliders=root.get_bool("InkSliders"),
            bits_per_pixel=root.get_int("BitsPerPixel"),
        )
        if cap is not None:
            config.quality_options = cap.texts(
                "DefaultPrintQualitySettingSupport/PrintQuality"
            )
            config.resolution_options = cap.texts(
                "ResolutionSettingSupport/ResolutionSetting"
            )
            copies = cap.find("DefaultPrintCopies")
            if copies is not None:
                try:
                    config.copies_max = int(copies.attrib.get("max", ""))
                except ValueError:
                    config.copies_max = None
        return config


@dataclass(slots=True, kw_only=True)
class CopyConfig(_Model):
    """Default copy settings (``CopyConfigDyn``)."""

    lighter_darker: int | None = None
    media_size: str | None = None
    media_type: str | None = None
    copies: int | None = None
    reduce_enlarge: str | None = None
    reduce_enlarge_custom: int | None = None
    tray: str | None = None
    quality: str | None = None
    margin_off: bool | None = None
    sides: str | None = None
    output_type: str | None = None
    input_source: str | None = None
    media_size_options: list[str] = field(default_factory=list)
    media_type_options: list[str] = field(default_factory=list)
    quality_options: list[str] = field(default_factory=list)
    output_type_options: list[str] = field(default_factory=list)
    reduce_enlarge_options: list[str] = field(default_factory=list)
    copies_max: int | None = None
    lighter_darker_max: int | None = None

    @classmethod
    def from_node(cls, root: Node, cap: Node | None = None) -> Self:
        """Parse ``CopyConfigDyn`` (+ optional ``CopyConfigCap``)."""
        config = cls(
            lighter_darker=root.get_int("DefaultLighterDarker"),
            media_size=root.get("DefaultMediaSizeName"),
            media_type=root.get("DefaultMediaType"),
            copies=root.get_int("DefaultNumberOfCopies"),
            reduce_enlarge=root.get("DefaultReduceEnlarge"),
            reduce_enlarge_custom=root.get_int("DefaultReduceEnlargeCustom"),
            tray=root.get("DefaultTraySelect"),
            quality=root.get("DefaultCopyQuality"),
            margin_off=root.get_bool("DefaultMarginOff"),
            sides=root.get("CopySides"),
            output_type=root.get("DefaultOutputType"),
            input_source=root.get("DefaultInputSource"),
        )
        if cap is not None:
            config.media_size_options = cap.texts(
                "DefaultMediaSizeNameSupport/MediaSizeName"
            )
            config.media_type_options = cap.texts("DefaultMediaTypeSupport/MediaType")
            config.quality_options = cap.texts("DefaultCopyQuality/DefaultCopyQuality")
            config.output_type_options = cap.texts(
                "DefaultOutputTypeSupport/DefaultOutputType"
            )
            config.reduce_enlarge_options = cap.texts(
                "DefaultReduceEnlargeSupport/DefaultReduceEnlarge"
            )
            for tag, attr in (
                ("DefaultNumberOfCopiesSupport", "copies_max"),
                ("DefaultLighterDarkerSupport", "lighter_darker_max"),
            ):
                node = cap.find(tag)
                if node is not None and node.attrib.get("max", "").isdigit():
                    setattr(config, attr, int(node.attrib["max"]))
        return config


# --------------------------------------------------------------------------- #
# Media / trays
# --------------------------------------------------------------------------- #
@dataclass(slots=True, kw_only=True)
class Tray(_Model):
    """An input tray."""

    name: str | None = None
    state: str | None = None
    media_type: str | None = None
    media_size: str | None = None
    location: str | None = None
    tray_type: str | None = None
    feeder_type: str | None = None
    plex: str | None = None
    orientation: str | None = None
    locked: bool | None = None

    @classmethod
    def from_node(cls, node: Node) -> Self:
        """Parse an ``InputTray`` element."""
        return cls(
            name=node.get("InputBin"),
            state=node.get("TrayState"),
            media_type=node.get("MediaType"),
            media_size=node.get("MediaSizeName"),
            location=node.get("InputTrayLocation"),
            tray_type=node.get("TrayType"),
            feeder_type=node.get("FeederType"),
            plex=node.get("Plex"),
            orientation=node.get("PageOrientation"),
            locked=node.get_bool("TrayLock"),
        )


@dataclass(slots=True, kw_only=True)
class MediaHandling(_Model):
    """Trays and output bins (``MediaHandlingDyn`` + ``MediaDyn``)."""

    trays: list[Tray] = field(default_factory=list)
    default_tray: str | None = None
    default_output_bin: str | None = None
    media_out_action: str | None = None
    output_bins: list[str] = field(default_factory=list)
    current_media_type: str | None = None
    current_media_size: str | None = None

    @classmethod
    def from_node(cls, root: Node, media: Node | None = None) -> Self:
        """Parse ``MediaHandlingDyn`` (+ optional ``MediaDyn``)."""
        info = root.find("MediaHandlingInfo") or root
        model = cls(
            trays=[Tray.from_node(t) for t in root.findall("InputTray")],
            default_tray=info.get("DefaultInputTray"),
            default_output_bin=info.get("DefaultOutputBin"),
            media_out_action=info.get("MediaOutActionType"),
            output_bins=root.texts("OutputBin/HPOutputBin"),
        )
        if media is not None:
            model.current_media_type = media.get("MediaType")
            model.current_media_size = media.get("MediaSizeName")
        elif model.trays:
            model.current_media_type = model.trays[0].media_type
            model.current_media_size = model.trays[0].media_size
        return model


# --------------------------------------------------------------------------- #
# Network
# --------------------------------------------------------------------------- #
@dataclass(slots=True, kw_only=True)
class Adapter(_Model):
    """A network adapter (Wi-Fi station, Wi-Fi Direct AP, Ethernet, USB)."""

    name: str
    adapter_type: str | None = None
    port_type: str | None = None
    mac: str | None = None
    power_on: bool | None = None
    connected: bool | None = None
    is_current: bool | None = None
    ssid: str | None = None
    bssid: str | None = None
    signal_strength: int | None = None
    rssi_dbm: int | None = None
    encryption: str | None = None
    authentication: str | None = None
    communication_mode: str | None = None
    wps_supported: bool | None = None
    ipv4_address: str | None = None
    subnet_mask: str | None = None
    gateway: str | None = None
    dns_server: str | None = None
    secondary_dns_server: str | None = None
    dhcp_server: str | None = None
    ipv4_config_method: str | None = None
    ipv6_addresses: list[str] = field(default_factory=list)
    packets_received: int | None = None
    packets_transmitted: int | None = None
    bad_packets_received: int | None = None

    @classmethod
    def from_node(cls, node: Node) -> Self:
        """Parse an ``Adapter`` element of ``/IoMgmt/Adapters``."""
        hw = node.find("HardwareConfig") or node
        wifi = hw.find("WifiNetwork")
        adapter = cls(
            name=hw.get("Name") or "adapter",
            adapter_type=node.get("ResourceNode/ResourceType/IoMgmtResourceType"),
            port_type=hw.get("DeviceConnectivityPortType"),
            mac=_format_mac(hw.get("MacAddress")),
            power_on=hw.get_bool("Power"),
            connected=hw.get_bool("IsConnected"),
            is_current=hw.get_bool("IsCurrentRequestInterface"),
        )
        if wifi is not None:
            adapter.ssid = _decode_hex_string(wifi.get("SSID"))
            adapter.bssid = _format_mac(wifi.get("BSSID"))
            adapter.signal_strength = wifi.get_int("SignalInfo/SignalStrength")
            adapter.rssi_dbm = wifi.get_int("SignalInfo/dBm")
            adapter.encryption = wifi.get("EncryptionType")
            adapter.authentication = wifi.get("AuthenticationMode")
            adapter.communication_mode = wifi.get("CommunicationMode")
            adapter.wps_supported = wifi.get_bool("WpsSupport")
        return adapter

    def merge_protocols(self, root: Node) -> None:
        """Merge ``/IoMgmt/Adapters/<name>/Protocols``."""
        for proto in root.findall("Protocol"):
            if proto.get("IPVersionSupport") == "ipv4":
                addr = proto.find("Addresses/IPv4Addresses/IPv4Address")
                if addr is not None:
                    self.ipv4_address = addr.get("IPv4Address")
                    self.subnet_mask = addr.get("SubnetMask")
                    self.gateway = addr.get("DefaultGateway")
                    self.ipv4_config_method = addr.get("ConfigMethod")
                self.dns_server = proto.get("DNSServerIPAddress")
                self.secondary_dns_server = proto.get("SecondaryDNSServerIPAddress")
                self.dhcp_server = proto.get("DHCPServerIPAddress")
            elif proto.get("IPVersionSupport") == "ipv6":
                self.ipv6_addresses = proto.texts(
                    "Addresses/IPv6Addresses/IPv6Address/IPv6Address"
                )

    def merge_stats(self, root: Node) -> None:
        """Merge ``/IoMgmt/Adapters/<name>/NetworkStats``."""
        stats = root.find("NetworkStatistics") or root
        self.packets_received = stats.get_int("TotalPacketsReceived")
        self.packets_transmitted = stats.get_int("TotalPacketsTransmitted")
        self.bad_packets_received = stats.get_int("BadPacketsReceived")


@dataclass(slots=True, kw_only=True)
class Network(_Model):
    """Network configuration: adapters, hostname, protocols, Wi-Fi Direct."""

    adapters: list[Adapter] = field(default_factory=list)
    hostname: str | None = None
    default_hostname: str | None = None
    mdns_name: str | None = None
    mdns_domain: str | None = None
    mdns_enabled: bool | None = None
    preferred_print_service: str | None = None
    ipp_enabled: bool | None = None
    port9100_enabled: bool | None = None
    snmp_enabled: bool | None = None
    snmp_access: str | None = None
    ws_discovery_enabled: bool | None = None
    ws_print_enabled: bool | None = None
    ws_scan_enabled: bool | None = None
    llmnr_enabled: bool | None = None
    dhcpv6_enabled: bool | None = None
    https_redirect_enabled: bool | None = None
    webscan_enabled: bool | None = None
    direct_print_enabled: bool | None = None
    wifi_direct_ssid_prefix: str | None = None
    wifi_direct_show_passphrase: bool | None = None
    wifi_direct_hide_ssid: bool | None = None
    wifi_direct_connection_method: str | None = None
    airprint_enabled: bool | None = None
    ipps_enabled: bool | None = None
    wpad_enabled: bool | None = None
    bluetooth_enabled: bool | None = None
    remote_scans_enabled: bool | None = None
    auto_wireless_config_state: str | None = None

    @classmethod
    def from_nodes(
        cls,
        adapters: Node | None,
        io_config: Node | None,
        net_apps: Node | None,
        net_apps_secure: Node | None,
    ) -> Self:
        """Build from the four LEDM network resources (any may be None)."""
        model = cls()
        if adapters is not None:
            model.adapters = [Adapter.from_node(a) for a in adapters.findall("Adapter")]
        if io_config is not None:
            model.hostname = io_config.get("IoDeviceConfig/Hostname")
            model.default_hostname = io_config.get("IoDeviceConfig/DefaultHostname")
        if net_apps is not None:
            dnssd = net_apps.find("DNSSDConfig")
            if dnssd is not None:
                model.mdns_enabled = dnssd.get_bool("MDNSSupport")
                model.mdns_name = dnssd.get("ApplicationServiceName")
                model.mdns_domain = dnssd.get("DomainName")
                model.preferred_print_service = dnssd.get("DNSSDPrintPreferredService")
            snmp = net_apps.find("SNMPConfigWithVersion")
            if snmp is not None:
                model.snmp_enabled = snmp.get_bool("SNMP")
                model.snmp_access = snmp.get("AccessOption")
            ws = net_apps.find("WebServicesConfig")
            if ws is not None:
                model.ws_discovery_enabled = ws.get_bool("WSDiscovery")
                model.ws_print_enabled = ws.get_bool("WSPrint")
                model.ws_scan_enabled = ws.get_bool("WSScan")
            model.ipp_enabled = net_apps.get_bool("IPPSupport")
            model.port9100_enabled = net_apps.get_bool("Port9100PrintingSupport")
            model.llmnr_enabled = net_apps.get_bool("LLMNR")
            model.dhcpv6_enabled = net_apps.get_bool("DHCPv6")
            model.https_redirect_enabled = net_apps.get_bool("HTTPSRedirection")
            model.webscan_enabled = net_apps.get_bool("WebScan")
            model.direct_print_enabled = net_apps.get_bool("DirectPrint")
        if net_apps_secure is not None:
            wd = net_apps_secure.find("WirelessDirectConfig")
            if wd is not None:
                model.wifi_direct_ssid_prefix = wd.get("SSIDPrefix")
                model.wifi_direct_show_passphrase = wd.get_bool("ShowPassPhrase")
                model.wifi_direct_hide_ssid = wd.get_bool("HideSSID")
                model.wifi_direct_connection_method = wd.get("ConnectionMethod")
            model.airprint_enabled = net_apps_secure.get_bool("AirPrintConfig/State")
            model.ipps_enabled = net_apps_secure.get_bool("IPPSConfig/State")
            model.wpad_enabled = net_apps_secure.get_bool("WPADConfig/State")
            model.bluetooth_enabled = net_apps_secure.get_bool(
                "BluetoothSmartConfig/State"
            )
            model.remote_scans_enabled = net_apps_secure.get_bool(
                "RemotelyInitiatedScans"
            )
            model.auto_wireless_config_state = net_apps_secure.get(
                "AutoWirelessConfig/State"
            )
        return model

    @property
    def wifi(self) -> Adapter | None:
        """The active Wi-Fi station adapter, if any."""
        for adapter in self.adapters:
            if adapter.adapter_type == "WifiAdapter" or (
                adapter.ssid and adapter.adapter_type != "AccessPointAdapter"
            ):
                return adapter
        return None

    @property
    def active(self) -> Adapter | None:
        """The adapter the printer is currently reached through."""
        for adapter in self.adapters:
            if adapter.is_current:
                return adapter
        return self.wifi or (self.adapters[0] if self.adapters else None)

    @property
    def mac(self) -> str | None:
        """MAC address of the active adapter."""
        active = self.active
        return active.mac if active else None


# --------------------------------------------------------------------------- #
# Firmware / calibration / ePrint / logs / events
# --------------------------------------------------------------------------- #
@dataclass(slots=True, kw_only=True)
class Firmware(_Model):
    """Web firmware update configuration and state."""

    auto_check: bool | None = None
    auto_update: bool | None = None
    status: str | None = None
    target_version: str | None = None
    target_date: date | None = None
    progress: int | None = None
    error: str | None = None
    reason: str | None = None
    update_type: str | None = None

    @classmethod
    def from_node(cls, root: Node) -> Self:
        """Parse ``/FirmwareUpdate/WebFWUpdate`` (or the ``WebFWUpdate`` class)."""
        node = root
        for candidate in root.findall("FirmwareUpdate"):
            if candidate.get("Class") == "WebFWUpdate":
                node = candidate
                break
        state = node.find("State") or node
        return cls(
            auto_check=node.get_bool("Config/AutomaticCheck"),
            auto_update=node.get_bool("Config/AutomaticUpdate"),
            status=state.get("Status"),
            target_version=state.get("TargetFWVersion/Revision"),
            target_date=_parse_date(state.get("TargetFWVersion/Date")),
            progress=state.get_int("ProgressPercentage"),
            error=state.get("Error"),
            reason=state.get("Reason"),
            update_type=state.get("Type"),
        )

    @property
    def update_available(self) -> bool:
        """True when the printer found a newer firmware."""
        return self.status in ("available", "downloading", "installReady") or bool(
            self.target_version
        )

    @property
    def in_progress(self) -> bool:
        """True while checking, downloading or installing."""
        return self.status in (
            "checking",
            "downloading",
            "installPreparation",
            "installing",
            "cancelling",
        )


@dataclass(slots=True, kw_only=True)
class EPrint(_Model):
    """HP web services / ePrint registration."""

    email_service: bool | None = None
    mobile_apps_service: bool | None = None
    registration_state: str | None = None
    connection_state: str | None = None
    cloud_services_enabled: bool | None = None
    platform: str | None = None
    printer_id: str | None = None
    email_address: str | None = None

    @classmethod
    def from_node(cls, root: Node) -> Self:
        """Parse ``ePrintConfigDyn``."""
        return cls(
            email_service=root.get_bool("CloudConfiguration/EmailService"),
            mobile_apps_service=root.get_bool("CloudConfiguration/MobileAppsService"),
            registration_state=root.get("RegistrationState"),
            connection_state=root.get("SignalingConnectionState"),
            cloud_services_enabled=root.get_bool("CloudServicesSwitch/Status"),
            platform=root.get("RegistrationDetails/PlatformIdentifier"),
            printer_id=root.get("PrinterID"),
            email_address=root.get("EmailAddress"),
        )

    @property
    def registered(self) -> bool:
        """True when the printer is registered to HP cloud."""
        return (self.registration_state or "").lower() == "registered"


@dataclass(slots=True, kw_only=True)
class EventLogEntry(_Model):
    """One entry of the product event log."""

    sequence: int | None = None
    occurrences: int | None = None
    code: str | None = None
    total_impressions: int | None = None
    detail: str | None = None

    @classmethod
    def from_node(cls, node: Node) -> Self:
        """Parse an ``Event`` element of ``ProductLogsDyn``."""
        return cls(
            sequence=node.get_int("SequenceNumber"),
            occurrences=node.get_int("EventOccurrences"),
            code=node.get("EventCode"),
            total_impressions=node.get_int("TotalImpressions"),
            detail=node.get("EventDetail"),
        )


@dataclass(slots=True, kw_only=True)
class ProductLogs(_Model):
    """Event log and raw error log."""

    events: list[EventLogEntry] = field(default_factory=list)
    error_log: str | None = None

    @classmethod
    def from_node(cls, root: Node) -> Self:
        """Parse ``ProductLogsDyn``."""
        return cls(
            events=[EventLogEntry.from_node(e) for e in root.findall("EventLog/Event")],
            error_log=root.get("ErrorLog"),
        )


@dataclass(slots=True, kw_only=True)
class DeviceEvent(_Model):
    """One row of ``/EventMgmt/EventTable``."""

    category: str
    aging_stamp: str | None = None

    @classmethod
    def from_node(cls, node: Node) -> Self:
        """Parse an ``Event`` element."""
        return cls(
            category=node.get("UnqualifiedEventCategory") or "unknown",
            aging_stamp=node.get("AgingStamp"),
        )


# --------------------------------------------------------------------------- #
# Scanner (eSCL)
# --------------------------------------------------------------------------- #
@dataclass(slots=True, kw_only=True)
class ScanJobInfo(_Model):
    """A scan job listed by ``ScannerStatus``."""

    uri: str | None = None
    uuid: str | None = None
    age: int | None = None
    images_completed: int | None = None
    images_to_transfer: int | None = None
    state: str | None = None
    reasons: list[str] = field(default_factory=list)

    @classmethod
    def from_node(cls, node: Node) -> Self:
        """Parse a ``JobInfo`` element."""
        return cls(
            uri=node.get("JobUri"),
            uuid=node.get("JobUuid"),
            age=node.get_int("Age"),
            images_completed=node.get_int("ImagesCompleted"),
            images_to_transfer=node.get_int("ImagesToTransfer"),
            state=node.get("JobState"),
            reasons=node.texts("JobStateReasons/JobStateReason"),
        )


@dataclass(slots=True, kw_only=True)
class ScannerStatus(_Model):
    """Live scanner state."""

    version: str | None = None
    state: str | None = None
    adf_state: str | None = None
    jobs: list[ScanJobInfo] = field(default_factory=list)

    @classmethod
    def from_node(cls, root: Node) -> Self:
        """Parse ``/eSCL/ScannerStatus``."""
        return cls(
            version=root.get("Version"),
            state=root.get("State"),
            adf_state=root.get("AdfState"),
            jobs=[ScanJobInfo.from_node(j) for j in root.findall("Jobs/JobInfo")],
        )

    @property
    def is_scanning(self) -> bool:
        """True while a scan is in progress."""
        return (self.state or "").lower() == "processing"


@dataclass(slots=True, kw_only=True)
class ScanSourceCapabilities(_Model):
    """Capabilities of one input source (platen or ADF)."""

    min_width: int | None = None
    max_width: int | None = None
    min_height: int | None = None
    max_height: int | None = None
    max_optical_x_resolution: int | None = None
    max_optical_y_resolution: int | None = None
    resolutions: list[int] = field(default_factory=list)
    color_modes: list[str] = field(default_factory=list)
    content_types: list[str] = field(default_factory=list)
    document_formats: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    risky_margins: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_node(cls, node: Node) -> Self:
        """Parse a ``PlatenInputCaps`` / ``AdfSimplexInputCaps`` element."""
        profile = node.find("SettingProfiles/SettingProfile")
        caps = cls(
            min_width=node.get_int("MinWidth"),
            max_width=node.get_int("MaxWidth"),
            min_height=node.get_int("MinHeight"),
            max_height=node.get_int("MaxHeight"),
            max_optical_x_resolution=node.get_int("MaxOpticalXResolution"),
            max_optical_y_resolution=node.get_int("MaxOpticalYResolution"),
            intents=node.texts("SupportedIntents/Intent"),
            risky_margins={
                k: v
                for k, v in (
                    ("left", node.get_int("RiskyLeftMargin")),
                    ("right", node.get_int("RiskyRightMargin")),
                    ("top", node.get_int("RiskyTopMargin")),
                    ("bottom", node.get_int("RiskyBottomMargin")),
                )
                if v is not None
            },
        )
        if profile is not None:
            caps.color_modes = profile.texts("ColorModes/ColorMode")
            caps.content_types = profile.texts("ContentTypes/ContentType")
            formats = profile.texts(
                "DocumentFormats/DocumentFormatExt"
            ) or profile.texts("DocumentFormats/DocumentFormat")
            caps.document_formats = list(dict.fromkeys(formats))
            resolutions = []
            for res in profile.findall(
                "SupportedResolutions/DiscreteResolutions/DiscreteResolution"
            ):
                value = res.get_int("XResolution")
                if value is not None:
                    resolutions.append(value)
            caps.resolutions = sorted(set(resolutions))
        return caps


@dataclass(slots=True, kw_only=True)
class ScannerCapabilities(_Model):
    """``/eSCL/ScannerCapabilities``."""

    version: str | None = None
    make_and_model: str | None = None
    serial_number: str | None = None
    manufacturer: str | None = None
    uuid: str | None = None
    admin_uri: str | None = None
    platen: ScanSourceCapabilities | None = None
    adf: ScanSourceCapabilities | None = None
    adf_duplex: ScanSourceCapabilities | None = None
    brightness: dict[str, int] = field(default_factory=dict)
    contrast: dict[str, int] = field(default_factory=dict)
    threshold: dict[str, int] = field(default_factory=dict)
    certifications: list[str] = field(default_factory=list)

    @classmethod
    def from_node(cls, root: Node) -> Self:
        """Parse the capabilities document."""

        def rng(tag: str) -> dict[str, int]:
            node = root.find(tag)
            if node is None:
                return {}
            return {
                k: v
                for k, v in (
                    ("min", node.get_int("Min")),
                    ("max", node.get_int("Max")),
                    ("normal", node.get_int("Normal")),
                    ("step", node.get_int("Step")),
                )
                if v is not None
            }

        platen = root.find("Platen/PlatenInputCaps")
        adf = root.find("Adf/AdfSimplexInputCaps")
        adf_duplex = root.find("Adf/AdfDuplexInputCaps")
        return cls(
            version=root.get("Version"),
            make_and_model=root.get("MakeAndModel"),
            serial_number=root.get("SerialNumber"),
            manufacturer=root.get("Manufacturer"),
            uuid=root.get("UUID"),
            admin_uri=root.get("AdminURI"),
            platen=ScanSourceCapabilities.from_node(platen) if platen else None,
            adf=ScanSourceCapabilities.from_node(adf) if adf else None,
            adf_duplex=ScanSourceCapabilities.from_node(adf_duplex)
            if adf_duplex
            else None,
            brightness=rng("BrightnessSupport"),
            contrast=rng("ContrastSupport"),
            threshold=rng("ThresholdSupport"),
            certifications=[
                f"{c.get('Name')} {c.get('Version')}".strip()
                for c in root.findall("Certifications/Certification")
            ],
        )

    @property
    def has_adf(self) -> bool:
        """True when an automatic document feeder is present."""
        return self.adf is not None

    @property
    def sources(self) -> list[str]:
        """Supported eSCL input sources."""
        sources = []
        if self.platen is not None:
            sources.append("Platen")
        if self.adf is not None:
            sources.append("Feeder")
        return sources


# --------------------------------------------------------------------------- #
# IPP
# --------------------------------------------------------------------------- #
@dataclass(slots=True, kw_only=True)
class IppJob(_Model):
    """A print job reported by IPP ``Get-Jobs``."""

    id: int
    name: str | None = None
    state: str | None = None
    state_reasons: list[str] = field(default_factory=list)
    user: str | None = None
    impressions: int | None = None
    impressions_completed: int | None = None
    media_sheets_completed: int | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None

    @classmethod
    def from_attributes(cls, attrs: dict[str, Any]) -> Self:
        """Build from a parsed IPP job attribute group."""
        state = attrs.get("job-state")
        reasons = attrs.get("job-state-reasons") or []
        if isinstance(reasons, str):
            reasons = [reasons]
        return cls(
            id=int(attrs.get("job-id", 0)),
            name=attrs.get("job-name"),
            state=IPP_JOB_STATES.get(int(state), str(state))
            if state is not None
            else None,
            state_reasons=[str(r) for r in reasons],
            user=attrs.get("job-originating-user-name"),
            impressions=attrs.get("job-impressions"),
            impressions_completed=attrs.get("job-impressions-completed"),
            media_sheets_completed=attrs.get("job-media-sheets-completed"),
            created_at=_ipp_datetime(attrs.get("date-time-at-creation")),
            completed_at=_ipp_datetime(attrs.get("date-time-at-completed")),
        )

    @property
    def is_active(self) -> bool:
        """True for pending/processing jobs."""
        return self.state in (
            "pending",
            "pending_held",
            "processing",
            "processing_stopped",
        )


def _ipp_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return _parse_datetime(value)
    return None


@dataclass(slots=True, kw_only=True)
class IppStatus(_Model):
    """Subset of IPP printer attributes useful for monitoring."""

    state: str | None = None
    state_reasons: list[str] = field(default_factory=list)
    state_message: str | None = None
    accepting_jobs: bool | None = None
    queued_jobs: int | None = None
    uptime_seconds: int | None = None
    wifi_ssid: str | None = None
    wifi_state: int | None = None
    firmware_version: str | None = None
    make_and_model: str | None = None
    uuid: str | None = None
    media_ready: list[str] = field(default_factory=list)
    media_default: str | None = None
    document_formats: list[str] = field(default_factory=list)
    identify_actions: list[str] = field(default_factory=list)
    operations: list[int] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    supplies: list[str] = field(default_factory=list)
    icons: list[str] = field(default_factory=list)
    strings_uri: str | None = None

    @classmethod
    def from_attributes(cls, attrs: dict[str, Any]) -> Self:
        """Build from a parsed IPP printer attribute group."""

        def as_list(value: Any) -> list[Any]:
            if value is None:
                return []
            return list(value) if isinstance(value, (list, tuple)) else [value]

        state = attrs.get("printer-state")
        return cls(
            state=IPP_PRINTER_STATES.get(int(state), str(state))
            if state is not None
            else None,
            state_reasons=[str(r) for r in as_list(attrs.get("printer-state-reasons"))],
            state_message=attrs.get("printer-state-message") or None,
            accepting_jobs=attrs.get("printer-is-accepting-jobs"),
            queued_jobs=attrs.get("queued-job-count"),
            uptime_seconds=attrs.get("printer-up-time"),
            wifi_ssid=attrs.get("printer-wifi-ssid"),
            wifi_state=attrs.get("printer-wifi-state"),
            firmware_version=attrs.get("printer-firmware-string-version")
            or attrs.get("printer-firmware-version"),
            make_and_model=attrs.get("printer-make-and-model"),
            uuid=attrs.get("printer-uuid"),
            media_ready=[str(m) for m in as_list(attrs.get("media-ready"))],
            media_default=attrs.get("media-default"),
            document_formats=[
                str(f) for f in as_list(attrs.get("document-format-supported"))
            ],
            identify_actions=[
                str(a) for a in as_list(attrs.get("identify-actions-supported"))
            ],
            operations=[int(o) for o in as_list(attrs.get("operations-supported"))],
            alerts=[str(a) for a in as_list(attrs.get("printer-alert-description"))],
            supplies=[str(s) for s in as_list(attrs.get("printer-supply"))],
            icons=[str(i) for i in as_list(attrs.get("printer-icons"))],
            strings_uri=attrs.get("printer-strings-uri"),
        )

    @property
    def supports_identify(self) -> bool:
        """True when Identify-Printer (0x3C) is supported."""
        return 0x3C in self.operations or bool(self.identify_actions)

    @property
    def supports_print_job(self) -> bool:
        """True when Print-Job (0x02) is supported."""
        return 0x02 in self.operations


# --------------------------------------------------------------------------- #
# Aggregate
# --------------------------------------------------------------------------- #
@dataclass(slots=True, kw_only=True)
class PrinterData(_Model):
    """Everything :meth:`hp_printer.HPPrinter.update` could fetch."""

    capabilities: Capabilities = field(default_factory=Capabilities)
    device: DeviceInfo | None = None
    settings: Settings | None = None
    settings_capabilities: SettingsCapabilities | None = None
    status: Status | None = None
    consumables: ConsumablesInfo | None = None
    usage: Usage | None = None
    print_config: PrintConfig | None = None
    copy_config: CopyConfig | None = None
    media: MediaHandling | None = None
    network: Network | None = None
    firmware: Firmware | None = None
    eprint: EPrint | None = None
    calibration_state: str | None = None
    internet_connection_state: str | None = None
    logs: ProductLogs | None = None
    events: list[DeviceEvent] = field(default_factory=list)
    scanner: ScannerStatus | None = None
    scanner_capabilities: ScannerCapabilities | None = None
    ipp: IppStatus | None = None
    jobs: list[IppJob] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def state(self) -> PrinterState:
        """Normalised state combining LEDM status, eSCL scanner and IPP."""
        if self.scanner is not None and self.scanner.is_scanning:
            return PrinterState.SCANNING
        if self.status is not None:
            state = self.status.state
            if (
                state is PrinterState.IDLE
                and self.ipp
                and self.ipp.state == "processing"
            ):
                return PrinterState.PRINTING
            if state in (PrinterState.IDLE, PrinterState.SLEEPING) and any(
                j.state == "processing" for j in self.jobs
            ):
                return PrinterState.PRINTING
            return state
        if self.ipp is not None:
            if self.ipp.state == "processing":
                return PrinterState.PRINTING
            if self.ipp.state == "stopped":
                return PrinterState.ERROR
            if self.ipp.state == "idle":
                return PrinterState.IDLE
        return PrinterState.UNKNOWN

    @property
    def current_job(self) -> IppJob | None:
        """The job being processed, if any."""
        for job in self.jobs:
            if job.state == "processing":
                return job
        for job in self.jobs:
            if job.is_active:
                return job
        return None
