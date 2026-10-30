"""Parsers for HP CDM (Cloud Device Model) JSON resources.

Newer HP printers (Smart Tank 5xx, DeskJet 28xx/42xx, LaserJet 3xxx/4xxx...)
drop LEDM entirely and only speak CDM. The functions here map the JSON
documents onto the same models used for LEDM so the integration layer does
not care which protocol the printer speaks.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .const import CONSUMABLE_COLORS, PrinterState
from .models import (
    Alert,
    Consumable,
    ConsumablesInfo,
    DeviceInfo,
    Firmware,
    MediaHandling,
    Network,
    Settings,
    Status,
    Tray,
    Usage,
)

CDM_STATE_MAP: dict[str, PrinterState] = {
    "ready": PrinterState.IDLE,
    "idle": PrinterState.IDLE,
    "inpowersave": PrinterState.SLEEPING,
    "sleep": PrinterState.SLEEPING,
    "processing": PrinterState.PRINTING,
    "printing": PrinterState.PRINTING,
    "scanning": PrinterState.SCANNING,
    "copying": PrinterState.COPYING,
    "initializing": PrinterState.INITIALIZING,
    "calibrating": PrinterState.CALIBRATING,
    "shuttingdown": PrinterState.SHUTTING_DOWN,
    "stopped": PrinterState.ERROR,
    "error": PrinterState.ERROR,
}

CDM_SEVERITY = {
    "information": "Info",
    "informational": "Info",
    "info": "Info",
    "notice": "Info",
    "warning": "Warning",
    "error": "Error",
    "critical": "Error",
    "fatal": "Error",
}


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in ("true", "enabled", "on", "yes"):
            return True
        if lowered in ("false", "disabled", "off", "no"):
            return False
    return None


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except TypeError, ValueError:
        return None


def _date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%Y%m%d%H%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()  # noqa: DTZ007
        except ValueError:
            continue
    return None


def parse_identity(data: dict[str, Any]) -> DeviceInfo:
    """``/cdm/system/v1/identity`` -> :class:`DeviceInfo`."""
    make = data.get("makeAndModel")
    if isinstance(make, dict):
        name = make.get("name") or make.get("base")
        family = make.get("family")
    else:
        name = make if isinstance(make, str) else None
        family = None
    fw_date = data.get("firmwareDateCode")
    return DeviceInfo(
        make_and_model=name,
        model_family=family or name,
        sku=data.get("skuIdentifier"),
        uuid=data.get("deviceUuid"),
        serial_number=data.get("serialNumber"),
        product_number=data.get("productNumber"),
        service_id=str(data["serviceId"]) if data.get("serviceId") else None,
        firmware_version=data.get("firmwareVersion"),
        firmware_date=_date(fw_date) if isinstance(fw_date, str) else None,
        manufacturer=data.get("manufacturer"),
        manufacture_date=_date(data.get("installDate")),
        languages=[data["deviceLanguage"]] if data.get("deviceLanguage") else [],
    )


def parse_status(
    status: dict[str, Any] | None,
    alerts: dict[str, Any] | None,
    print_status: dict[str, Any] | None = None,
) -> Status:
    """``system/v1/status`` + ``alert/v1/alerts`` (+ ``print/v2/status``)."""
    categories: list[str] = []
    if status and status.get("status"):
        categories.append(str(status["status"]))
    if print_status:
        state = str(print_status.get("printerState", "")).lower()
        if state == "processing":
            categories.append("processing")
        for reason in print_status.get("printerStateReasons") or []:
            if reason and reason != "none" and reason not in categories:
                categories.append(str(reason))
    parsed_alerts: list[Alert] = []
    for item in (alerts or {}).get("alerts") or []:
        details = {}
        for entry in item.get("data") or []:
            pointer = str(entry.get("propertyPointer", "")).rsplit("/", 1)[-1]
            value = entry.get("value") or {}
            details[pointer] = str(next(iter(value.values()), ""))
        parsed_alerts.append(
            Alert(
                id=str(item.get("category", "unknown")),
                severity=CDM_SEVERITY.get(str(item.get("severity", "")).lower()),
                priority=_int(item.get("priority")),
                string_id=str(item["stringId"]) if item.get("stringId") else None,
                sequence=_int(item.get("sequenceNum")),
                marker_color=details.get("colors"),
                consumable_type=details.get("supplyType"),
                details=details,
            )
        )
    return Status(categories=categories, alerts=parsed_alerts)


def parse_supplies(data: dict[str, Any]) -> ConsumablesInfo:
    """``/cdm/supply/v1/suppliesPublic`` -> :class:`ConsumablesInfo`."""
    consumables: list[Consumable] = []
    for item in data.get("suppliesList") or []:
        label = item.get("supplyColorCode")
        color, css = CONSUMABLE_COLORS.get(str(label or "").upper(), (None, None))
        level = _int(item.get("percentLifeDisplay"))
        state = item.get("supplyState")
        consumables.append(
            Consumable(
                station=_int(item.get("slot")),
                label_code=label,
                color=color or (label.lower() if isinstance(label, str) else None),
                css_color=css,
                type=item.get("supplyType"),
                level=level,
                raw_level=level,
                state=state,
                measured_state=item.get("levelState"),
                brand=item.get("brand"),
                is_genuine_hp=_bool(item.get("isGenuineHP")),
                is_refilled=_bool(item.get("isRefilled")),
                is_setup=_bool(item.get("isSetup")),
                is_trial=_bool(item.get("isTrial")),
                selectability_number=item.get("selectabilityNumber")
                or item.get("orderPartNumber")
                or item.get("productNumber"),
                supported_numbers=[
                    n
                    for n in (
                        item.get("orderSelectabilityNumber"),
                        item.get("orderPartNumber"),
                    )
                    if n
                ],
                unique_id=str(item["slotIdentifier"])
                if item.get("slotIdentifier") is not None
                else None,
                capacity=_int(item.get("capacity")),
                capacity_unit=item.get("capacityUnit"),
                manufacture_date=_date(item.get("manufactureDate")),
                serial_number=item.get("serialNumber"),
                product_number=item.get("productNumber"),
                estimated_pages_remaining=_int(
                    item.get("approximatePagesRemainingDisplay")
                ),
            )
        )
    consumables.sort(key=lambda c: c.station if c.station is not None else 99)
    return ConsumablesInfo(consumables=consumables, user_replaceable=len(consumables))


def parse_usage(
    counters: dict[str, Any] | None, service: dict[str, Any] | None = None
) -> Usage:
    """``deviceUsage/v1/lifetimeCounters`` (+ ``serviceCounters``) -> :class:`Usage`."""
    counters = counters or {}
    print_usage = counters.get("printUsage") or {}
    impressions = print_usage.get("impressions") or {}
    copy = print_usage.get("copyImpressions") or {}
    sheets = print_usage.get("sheets") or {}
    scan = counters.get("scanUsage") or {}
    by_size = {}
    for entry in print_usage.get("impressionsByMediaSize") or []:
        total = _int((entry.get("impressions") or {}).get("total"))
        if entry.get("mediaSizeId") and total:
            by_size[str(entry["mediaSizeId"])] = total
    hardware = (service or {}).get("hardwareEvents") or {}
    return Usage(
        total_impressions=_int(impressions.get("total")),
        monochrome_impressions=_int(impressions.get("monochrome")),
        color_impressions=_int(impressions.get("color")),
        simplex_sheets=_int(sheets.get("simplex")),
        duplex_sheets=_int(sheets.get("duplex")),
        jam_events=_int(hardware.get("jamEventCount")),
        mispick_events=_int(hardware.get("mispickEventCount")),
        impressions_by_media_size=by_size,
        copy_impressions=_int(copy.get("total")),
        copy_color_impressions=_int(copy.get("color")),
        copy_monochrome_impressions=_int(copy.get("monochrome")),
        scan_images=_int(scan.get("totalImages")),
        scan_adf_images=_int(scan.get("adfImages")),
        fax_impressions=_int(counters.get("faxInImpressions")),
    )


def parse_settings(
    power: dict[str, Any] | None,
    system_config: dict[str, Any] | None,
    print_config: dict[str, Any] | None,
    print_mode: dict[str, Any] | None,
    control_panel: dict[str, Any] | None,
) -> Settings:
    """Combine the CDM configuration resources into :class:`Settings`."""
    power = power or {}
    system_config = system_config or {}
    quiet = None
    if print_mode and "quietPrintModeEnabled" in print_mode:
        quiet = _bool(print_mode["quietPrintModeEnabled"])
    elif print_config and "quietModeEnabled" in print_config:
        quiet = _bool(print_config["quietModeEnabled"])
    timeout = _int(power.get("sleepTimeout") or power.get("inactivityTimeout"))
    shutdown = _int(power.get("shutdownTimeoutInMinutes"))
    return Settings(
        power_save_timeout=f"{timeout}minutes" if timeout is not None else None,
        auto_off_time=f"{shutdown // 60}hours"
        if shutdown and shutdown % 60 == 0
        else (f"{shutdown}minutes" if shutdown else None),
        power_save_enabled=_bool(power.get("autoShutdownEnabled")),
        device_language=(control_panel or {}).get("deviceLanguage")
        or system_config.get("deviceLanguage"),
        country=system_config.get("countryRegion"),
        quiet_mode=quiet,
        description=system_config.get("deviceDescription"),
        location=system_config.get("deviceLocation"),
    )


def parse_firmware(
    config: dict[str, Any] | None,
    status: dict[str, Any] | None,
    check: dict[str, Any] | None,
) -> Firmware:
    """``firmwareUpdate/v2/{configuration,updateStatus,updateCheck}``."""
    config = config or {}
    status = status or {}
    check = check or {}
    target = check.get("availableVersion") or status.get("toVersion") or None
    return Firmware(
        auto_check=_bool(config.get("autoUpdateEnabled")),
        auto_update=_bool(config.get("autoUpdateEnabled")),
        status=status.get("state") or check.get("state"),
        target_version=target or None,
        progress=_int(status.get("downloadProgressPercent")),
        error=status.get("failureReason"),
        reason=status.get("lastUpdateResult"),
        update_type=status.get("updateType"),
    )


def parse_media(config: dict[str, Any] | None) -> MediaHandling:
    """``media/v1/configuration`` -> :class:`MediaHandling`."""
    config = config or {}
    trays = [
        Tray(
            name=str(entry.get("mediaSourceId") or entry.get("deviceIdentifier")),
            media_type=entry.get("currentMediaType"),
            media_size=entry.get("currentMediaSize"),
            tray_type=entry.get("inputType"),
            state="installed",
        )
        for entry in config.get("inputs") or []
    ]
    model = MediaHandling(
        trays=trays,
        default_tray=config.get("defaultMediaSource"),
        output_bins=[
            str(o.get("mediaDestinationId")) for o in config.get("outputs") or []
        ],
    )
    if trays:
        model.current_media_type = trays[0].media_type
        model.current_media_size = trays[0].media_size
    return model


def parse_network(
    discovery: dict[str, Any] | None,
    print_services: dict[str, Any] | None,
    name_resolver: dict[str, Any] | None,
    snmp: dict[str, Any] | None,
) -> Network:
    """Combine ``network/v1/*`` resources into :class:`Network`."""
    network = Network()
    bonjour = (discovery or {}).get("bonjour") or {}
    if bonjour:
        network.mdns_enabled = _bool(bonjour.get("enabled"))
        network.mdns_name = bonjour.get("serviceName")
        network.mdns_domain = bonjour.get("domainName")
        network.preferred_print_service = bonjour.get("highestPriorityPrintService")
    wsd = (discovery or {}).get("wsDiscovery") or {}
    if wsd:
        network.ws_discovery_enabled = _bool(wsd.get("enabled"))
    ps = print_services or {}
    if ps:
        network.airprint_enabled = _bool((ps.get("airPrint") or {}).get("enabled"))
        network.ipp_enabled = _bool((ps.get("ipp") or {}).get("ipp"))
        network.ipps_enabled = _bool((ps.get("ipp") or {}).get("ippSecure"))
        network.port9100_enabled = _bool((ps.get("port9100") or {}).get("enabled"))
        network.ws_print_enabled = _bool((ps.get("wsPrint") or {}).get("enabled"))
    llmnr = (name_resolver or {}).get("llmnr") or {}
    if llmnr:
        network.llmnr_enabled = _bool(llmnr.get("enabled"))
    snmp_cfg = (snmp or {}).get("snmpV1V2Config") or {}
    if snmp_cfg:
        network.snmp_enabled = _bool(snmp_cfg.get("enabled"))
        network.snmp_access = snmp_cfg.get("accessOption")
    return network


def cdm_state(status: dict[str, Any] | None) -> PrinterState:
    """Map ``system/v1/status`` to :class:`PrinterState`."""
    if not status:
        return PrinterState.UNKNOWN
    return CDM_STATE_MAP.get(
        str(status.get("status", "")).lower(), PrinterState.UNKNOWN
    )
