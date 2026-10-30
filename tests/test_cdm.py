"""CDM JSON parsing (fixtures from a Smart Tank 580 via kou147258/ha-hp-printers)."""

from __future__ import annotations

from hp_printer import cdm
from hp_printer.const import PrinterState

from .conftest import load_json


def test_identity() -> None:
    info = cdm.parse_identity(load_json("cdm/cdm_system_v1_identity.json"))
    assert info.make_and_model == "Smart Tank 580-590 series"
    assert info.model_family == "Smart Tank 580-590 series"
    assert info.firmware_version == "LWP1CN2630CR"
    assert info.firmware_date is not None and info.firmware_date.year == 2026
    assert info.manufacture_date is not None and info.manufacture_date.month == 3
    assert info.languages == ["zh-CN"]
    assert info.manufacturer == "HP"
    string_model = cdm.parse_identity({"makeAndModel": "HP LaserJet", "serviceId": 5})
    assert (
        string_model.make_and_model == "HP LaserJet" and string_model.service_id == "5"
    )


def test_status_and_alerts() -> None:
    status = cdm.parse_status(
        load_json("cdm/cdm_system_v1_status.json"),
        load_json("cdm/cdm_alert_v1_alerts.json"),
        load_json("cdm/cdm_print_v2_status.json"),
    )
    assert status.categories[0] in ("inPowerSave", "ready")
    assert status.alerts
    first = status.alerts[0]
    assert first.id == "genuineHPsupply" and first.severity == "Info"
    assert first.details.get("supplyType") == "inkTank"
    assert status.state in (PrinterState.SLEEPING, PrinterState.IDLE)
    printing = cdm.parse_status(
        {"status": "ready"},
        None,
        {"printerState": "processing", "printerStateReasons": ["none", "media-low"]},
    )
    assert printing.state is PrinterState.PRINTING
    assert "media-low" in printing.categories
    assert cdm.cdm_state({"status": "inPowerSave"}) is PrinterState.SLEEPING
    assert cdm.cdm_state(None) is PrinterState.UNKNOWN


def test_supplies() -> None:
    info = cdm.parse_supplies(load_json("cdm/cdm_supply_v1_suppliesPublic.json"))
    assert info.consumables
    head = info.consumables[0]
    assert head.type == "inkCartridge" and head.label_code == "CMY"
    assert head.color == "tri_color" and head.is_genuine_hp is True
    assert head.is_refilled is False and head.selectability_number == "M0H50A"
    assert head.manufacture_date is not None
    tanks = [c for c in info.consumables if c.type == "inkTank"]
    assert tanks and tanks[0].level == 100 and tanks[0].measured_state == "ok"
    laser = cdm.parse_supplies(
        {
            "suppliesList": [
                {
                    "slot": 2,
                    "supplyType": "tonerCartridge",
                    "supplyColorCode": "C",
                    "supplyState": "low",
                    "levelState": "low",
                    "percentLifeDisplay": 9,
                    "approximatePagesRemainingDisplay": 200,
                    "capacity": 2200,
                    "capacityUnit": "pages",
                    "orderPartNumber": "W2121X",
                    "isGenuineHP": "true",
                }
            ]
        }
    )
    toner = laser.consumables[0]
    assert toner.level == 9 and toner.is_low and not toner.is_empty
    assert toner.estimated_pages_remaining == 200
    assert toner.selectability_number == "W2121X"
    assert toner.color == "cyan"


def test_usage() -> None:
    usage = cdm.parse_usage(
        load_json("cdm/cdm_deviceUsage_v1_lifetimeCounters.json"),
        load_json("cdm/cdm_deviceUsage_v1_serviceCounters.json"),
    )
    assert usage.total_impressions == 10531
    assert usage.monochrome_impressions == 647 and usage.color_impressions == 722
    assert usage.copy_impressions == 110
    assert usage.simplex_sheets == 1369
    assert usage.jam_events == 3 and usage.mispick_events == 15
    assert usage.impressions_by_media_size["na_letter_8.5x11in"] == 1372
    assert cdm.parse_usage(None).total_impressions is None


def test_settings_firmware_media_network() -> None:
    settings = cdm.parse_settings(
        load_json("cdm/cdm_power_v1_configuration.json"),
        load_json("cdm/cdm_system_v1_configuration.json"),
        load_json("cdm/cdm_print_v2_configuration.json"),
        None,
        None,
    )
    assert settings.power_save_timeout == "5minutes"
    assert settings.quiet_mode is False
    assert settings.device_language == "zh-CN" and settings.country == "CN"
    with_mode = cdm.parse_settings(
        {"sleepTimeout": 10, "shutdownTimeoutInMinutes": 120},
        None,
        None,
        {"quietPrintModeEnabled": "true"},
        {"deviceLanguage": "pt"},
    )
    assert with_mode.quiet_mode is True and with_mode.auto_off_time == "2hours"
    assert with_mode.device_language == "pt"
    firmware = cdm.parse_firmware(
        load_json("cdm/cdm_firmwareUpdate_v2_configuration.json"),
        load_json("cdm/cdm_firmwareUpdate_v2_updateStatus.json"),
        load_json("cdm/cdm_firmwareUpdate_v2_updateCheck.json"),
    )
    assert firmware.auto_update is True and firmware.status == "idle"
    assert firmware.target_version is None and not firmware.update_available
    media = cdm.parse_media(load_json("cdm/cdm_media_v1_configuration.json"))
    assert media.default_tray == "main"
    assert media.trays[0].media_size == "iso_a4_210x297mm"
    assert media.current_media_type == "stationery"
    network = cdm.parse_network(
        load_json("cdm/cdm_network_v1_discoveryServices.json"),
        load_json("cdm/cdm_network_v1_printServices.json"),
        load_json("cdm/cdm_network_v1_nameResolverServices.json"),
        load_json("cdm/cdm_network_v1_snmpConfig.json"),
    )
    assert network.mdns_enabled is True and network.mdns_name
    assert network.ipp_enabled and network.ipps_enabled and network.airprint_enabled
    assert network.llmnr_enabled is True and network.snmp_enabled is True
    assert network.snmp_access == "readOnly"
    assert cdm.parse_network(None, None, None, None).mdns_name is None
