"""Parsing of the LEDM fixtures captured from an HP DeskJet 2774."""

from __future__ import annotations

from datetime import date

from hp_printer.const import PrinterState
from hp_printer.models import (
    Capabilities,
    ConsumablesInfo,
    CopyConfig,
    DeviceEvent,
    DeviceInfo,
    EPrint,
    Firmware,
    MediaHandling,
    Network,
    PrintConfig,
    PrinterData,
    ProductLogs,
    ScannerCapabilities,
    ScannerStatus,
    Settings,
    SettingsCapabilities,
    Status,
    Usage,
)
from hp_printer.xml_utils import parse_xml

from .conftest import load_json, load_xml


def test_capabilities_from_discovery() -> None:
    caps = Capabilities.from_discovery(
        load_xml("DiscoveryTree.xml"), load_json("servicesDiscovery.json")
    )
    assert caps.has_ledm and caps.has_cdm and caps.has_escl and caps.has_scanner
    assert caps.has_copy and caps.has_firmware_update and caps.has_calibration
    assert not caps.has_fax
    assert "/DevMgmt/ProductStatusDyn.xml" in caps.ledm_resources
    assert caps.has_resource("/DevMgmt/ProductStatusDyn.xml")
    assert caps.cdm_href("print", "printModeConfiguration") == (
        "/cdm/print/v1/printModeConfiguration"
    )
    assert caps.cdm_href("print", "nope") is None
    # unavailable links are skipped
    assert caps.cdm_href("awc", "signedPublicKey") is None
    assert "cdm_services" in caps.as_dict()


def test_capabilities_cdm_only() -> None:
    caps = Capabilities.from_discovery(None, load_json("servicesDiscovery.json"))
    assert caps.has_cdm and not caps.has_ledm
    assert caps.has_resource("/anything")  # unknown tree: optimistic


def test_device_info() -> None:
    info = DeviceInfo.from_node(load_xml("ProductConfigDyn.xml"))
    assert info.make_and_model == "DeskJet Ink Advantage 2700 All-in-One Printer series"
    assert info.model_family == "DeskJet 2700 series"
    assert info.name == "DeskJet 2700 series"
    assert info.serial_number == "BR28BCB23H"
    assert info.product_number == "7FR22A"
    assert info.sku == "2774"
    assert info.uuid == "ab462181-f7b2-f0ee-b557-a0b7dbf0d250"
    assert info.firmware_version == "TWP1FN2550DR"
    assert info.firmware_date == date(2025, 12, 12)
    assert info.manufacture_date == date(2022, 8, 11)
    assert info.password_set is True
    assert info.languages == ["en", "es", "pt", "zh-CN"]
    assert info.total_memory_kb == 42854
    assert info.control_panel_display == "LED"


def test_settings_and_capabilities() -> None:
    settings = Settings.from_node(load_xml("ProductConfigDyn.xml"))
    assert settings.power_save_timeout == "5minutes"
    assert settings.auto_off_time == "2hours"
    assert settings.device_language == "pt"
    assert settings.country == "brazil"
    assert settings.quiet_mode is False
    assert settings.ews_enabled is True
    assert settings.power_save_enabled is True
    assert settings.ews_urls[0] == "http://192.168.31.12"
    caps = SettingsCapabilities.from_node(load_xml("ProductConfigCap.xml"))
    assert caps.power_save_timeouts == ["5minutes", "10minutes", "15minutes"]
    assert caps.auto_off_times == ["2hours"]
    assert "brazil" in caps.countries
    assert caps.time_formats == ["HR12", "HR24"]
    assert caps.quiet_mode_supported
    assert caps.pages_per_minute == 7
    assert caps.color_printing is True
    assert "PCL3GUI" in caps.document_formats


def test_status_idle_with_info_alerts() -> None:
    status = Status.from_node(load_xml("ProductStatusDyn.xml"))
    assert status.categories == ["genuineHP", "inPowerSave"]
    assert len(status.alerts) == 2
    assert status.alerts[0].id == "genuineHP"
    assert status.alerts[0].severity == "Info"
    assert status.alerts[0].marker_color == "CyanMagentaYellow"
    assert status.alerts[1].marker_location == 1
    assert status.state is PrinterState.SLEEPING
    assert status.is_sleeping
    assert not status.has_error and not status.has_warning
    assert status.problems == []


def test_status_state_machine() -> None:
    def status(*categories: str, alerts: str = "") -> Status:
        xml = (
            '<psdyn:ProductStatusDyn xmlns:psdyn="x" xmlns:pscat="y" xmlns:ad="z" xmlns:dd="d">'
            + "".join(
                f"<psdyn:Status><pscat:StatusCategory>{c}</pscat:StatusCategory></psdyn:Status>"
                for c in categories
            )
            + f"<psdyn:AlertTable>{alerts}</psdyn:AlertTable></psdyn:ProductStatusDyn>"
        )
        return Status.from_node(parse_xml(xml))

    assert status("ready").state is PrinterState.IDLE
    assert status("processing", "genuineHP").state is PrinterState.PRINTING
    assert status("scanProcessing").state is PrinterState.SCANNING
    assert status("copying").state is PrinterState.COPYING
    assert status("cancelJob").state is PrinterState.CANCELING
    assert status("inkSystemInitializing").state is PrinterState.INITIALIZING
    assert status("calibrating").state is PrinterState.CALIBRATING
    assert status("shuttingDown").state is PrinterState.SHUTTING_DOWN
    assert status().state is PrinterState.UNKNOWN
    jam = status("jamInPrinter")
    assert jam.state is PrinterState.ERROR and jam.has_error
    assert jam.problems == ["jamInPrinter"]
    low = status("ready", "cartridgeLow")
    assert low.state is PrinterState.ATTENTION
    assert low.problems == ["cartridgeLow"]
    alert = (
        "<psdyn:Alert><ad:ProductStatusAlertID>trayEmptyOrOpen</ad:ProductStatusAlertID>"
        "<ad:Severity>Error</ad:Severity><dd:SequenceNumber>1</dd:SequenceNumber></psdyn:Alert>"
        "<psdyn:Alert><ad:ProductStatusAlertID>cartridgeVeryLow</ad:ProductStatusAlertID>"
        "<ad:Severity>Warning</ad:Severity></psdyn:Alert>"
    )
    both = status("ready", alerts=alert)
    assert both.state is PrinterState.ERROR
    assert both.problems == ["trayEmptyOrOpen", "cartridgeVeryLow"]
    # busy wins over errors
    assert status("processing", alerts=alert).state is PrinterState.PRINTING


def test_consumables_with_usage() -> None:
    info = ConsumablesInfo.from_node(load_xml("ConsumableConfigDyn.xml"))
    assert info.user_replaceable == 2
    assert info.alignment_mode == "semiAutomatic"
    assert info.single_cartridge_mode is True
    assert info.genuine_hp_only is False
    assert [c.label_code for c in info.consumables] == ["CMY", "K"]
    cmy, black = info.consumables
    assert cmy.color == "tri_color" and cmy.css_color == "#00AEEF"
    assert cmy.level == 90 and black.level == 70
    assert black.color == "black" and black.css_color == "#000000"
    assert black.state == "newGenuineHP" and black.is_genuine_hp is True
    assert black.is_refilled is False and black.is_setup is False
    assert black.selectability_number == "667"
    assert black.supported_numbers == ["667XL", "667"]
    assert black.type == "inkCartridge"
    assert black.unique_id == "000000000000005f444c9b813bb29168"
    assert black.family == "TIJ2"
    assert not black.is_low and not black.is_empty
    assert black.raw_level is None
    info.merge_usage(load_xml("ProductUsageDyn.xml"))
    assert cmy.raw_level == 87 and black.raw_level == 65
    assert black.insertions == 4
    assert black.counterfeit_refills == 0 and black.genuine_refills == 0
    assert black.marking_agent_used == 2.0 and black.marking_agent_unit == "microliters"


def test_consumable_low_and_empty_flags() -> None:
    xml = (
        '<ccdyn:ConsumableConfigDyn xmlns:ccdyn="c" xmlns:dd="d"><ccdyn:ConsumableInfo>'
        "<dd:ConsumableLabelCode>C</dd:ConsumableLabelCode>"
        "<dd:ConsumablePercentageLevelRemaining>0</dd:ConsumablePercentageLevelRemaining>"
        "<dd:ConsumableLifeState><dd:ConsumableState>veryLow</dd:ConsumableState>"
        "<dd:MeasuredQuantityState>low</dd:MeasuredQuantityState></dd:ConsumableLifeState>"
        "<dd:ConsumableIcon><dd:FillColor><dd:Red>1</dd:Red><dd:Green>2</dd:Green>"
        "<dd:Blue>3</dd:Blue></dd:FillColor></dd:ConsumableIcon>"
        "</ccdyn:ConsumableInfo><ccdyn:ConsumableInfo>"
        "<dd:MarkerColor>PhotoBlack</dd:MarkerColor>"
        "<dd:ConsumableIcon><dd:FillColor><dd:Red>1</dd:Red><dd:Green>2</dd:Green>"
        "<dd:Blue>3</dd:Blue></dd:FillColor></dd:ConsumableIcon>"
        "</ccdyn:ConsumableInfo></ccdyn:ConsumableConfigDyn>"
    )
    info = ConsumablesInfo.from_node(parse_xml(xml))
    cyan, photo = info.consumables
    assert cyan.is_low and cyan.is_empty
    assert cyan.css_color == "#00AEEF"  # known label keeps the palette colour
    assert photo.label_code == "PK" and photo.color == "photo_black"


def test_usage_counters() -> None:
    usage = Usage.from_node(load_xml("ProductUsageDyn.xml"))
    assert usage.total_impressions == 66
    assert usage.jam_events == 0 and usage.mispick_events == 0
    assert usage.front_panel_cancel_presses == 8
    assert usage.ink_used_ml == 3.0 and usage.ink_inserted_ml == 12.0
    assert usage.network_impressions == 25 and usage.wireless_impressions == 25
    assert usage.quiet_mode_impressions == 0
    assert usage.ews_access_count == 11
    assert usage.impressions_by_media_type == {
        "plain": 64,
        "photoStandard": 2,
        "photoOther": 2,
    }
    assert usage.impressions_by_media_size == {
        "na_letter_8.5x11in": 66,
        "iso_a4_210x297mm": 66,
    }
    assert usage.impressions_by_quality == {"normal": 70, "draft": 0, "better": 1}
    assert usage.jobs_by_duration["lessthanTwoMinutes"] == 34
    assert usage.impressions_by_data_path == {"googleLocal": 0, "googleCloud": 0}
    assert usage.mobile_impressions == {"Windows/discrete": 25}
    assert usage.scan_images == 5 and usage.scan_flatbed_images == 5
    assert usage.scan_to_host_images == 2
    assert usage.copy_impressions == 3 and usage.copy_color_impressions == 3
    assert usage.copy_flatbed_images == 2
    assert usage.print_application_impressions == 65
    assert usage.setup_by_os == "iOS"
    assert usage.monochrome_impressions is None  # not reported by this model


def test_print_and_copy_config() -> None:
    cfg = PrintConfig.from_node(
        load_xml("PrintConfigDyn.xml"), load_xml("PrintConfigCap.xml")
    )
    assert cfg.default_copies == 1 and cfg.copies_max == 99
    assert cfg.quality == "Normal" and cfg.quality_options == [
        "Best",
        "Draft",
        "Normal",
    ]
    assert cfg.resolution == "fast600dpi"
    assert cfg.resolution_options == ["fast300dpi", "fast600dpi", "fast1200dpi"]
    assert cfg.borderless is False and cfg.colorlok is True
    assert cfg.job_timeout_seconds == 300
    copy = CopyConfig.from_node(
        load_xml("CopyConfigDyn.xml"), load_xml("CopyConfigCap.xml")
    )
    assert copy.copies == 1 and copy.copies_max == 9
    assert copy.lighter_darker == 4 and copy.lighter_darker_max == 8
    assert copy.quality == "normal" and copy.quality_options == ["best", "normal"]
    assert copy.output_type == "monochrome"
    assert copy.output_type_options == ["monochrome", "color"]
    assert "iso_a4_210x297mm" in copy.media_size_options
    assert copy.margin_off is True


def test_media_handling() -> None:
    media = MediaHandling.from_node(
        load_xml("MediaHandlingDyn.xml"), load_xml("MediaDyn.xml")
    )
    assert media.default_tray == "Tray1"
    assert media.media_out_action == "waitForPaperToBeLoaded"
    assert media.output_bins == ["OutputBin1"]
    assert len(media.trays) == 1
    tray = media.trays[0]
    assert tray.name == "Tray1" and tray.state == "installed"
    assert tray.media_size == "iso_a4_210x297mm" and tray.media_type == "plain"
    assert tray.locked is False
    assert media.current_media_size == "iso_a4_210x297mm"
    fallback = MediaHandling.from_node(load_xml("MediaHandlingDyn.xml"))
    assert fallback.current_media_type == "plain"


def test_network() -> None:
    network = Network.from_nodes(
        load_xml("Adapters.xml"),
        load_xml("IoConfig.xml"),
        load_xml("NetAppsDyn.xml"),
        load_xml("NetAppsSecureDyn.xml"),
    )
    assert network.hostname == "MiWiFi-RM1800-srv"
    assert network.default_hostname == "HP502472"
    assert network.mdns_name == "HP DeskJet 2700 series [502472]"
    assert network.mdns_domain == "HP5C60BA502472.local."
    assert network.ipp_enabled and network.port9100_enabled and network.snmp_enabled
    assert network.snmp_access == "readOnly"
    assert network.webscan_enabled is False
    assert network.wifi_direct_ssid_prefix == "DIRECT-72-HP"
    assert network.wifi_direct_show_passphrase is True
    assert (
        network.airprint_enabled and network.ipps_enabled and network.bluetooth_enabled
    )
    assert network.remote_scans_enabled is True
    assert [a.name for a in network.adapters] == ["Wifi0", "Wifi1", "Usb0"]
    wifi = network.wifi
    assert wifi is not None and wifi is network.active
    assert wifi.ssid == "CASA_396_5G"
    assert wifi.bssid == "9c:9d:7e:46:da:7d"
    assert wifi.mac == "5c:60:ba:50:24:72"
    assert network.mac == "5c:60:ba:50:24:72"
    assert wifi.rssi_dbm == -49 and wifi.signal_strength == 5
    assert wifi.encryption == "WPA2" and wifi.connected is True
    wifi.merge_protocols(load_xml("Wifi0Protocols.xml"))
    assert wifi.ipv4_address == "192.168.31.12"
    assert wifi.gateway == "192.168.31.1" and wifi.dns_server == "192.168.31.1"
    assert wifi.ipv4_config_method == "DHCPv4"
    assert len(wifi.ipv6_addresses) == 2
    wifi.merge_stats(load_xml("Wifi0NetworkStats.xml"))
    assert wifi.packets_received == 233910 and wifi.packets_transmitted == 4393
    usb = network.adapters[2]
    assert usb.adapter_type == "USBAdapter" and usb.connected is False
    empty = Network.from_nodes(None, None, None, None)
    assert empty.wifi is None and empty.active is None and empty.mac is None


def test_firmware_eprint_logs_events() -> None:
    fw = Firmware.from_node(load_xml("WebFWUpdate.xml"))
    assert fw.auto_check is True and fw.auto_update is True
    assert fw.status == "idle" and not fw.update_available and not fw.in_progress
    eprint = EPrint.from_node(load_xml("ePrintConfigDyn.xml"))
    assert eprint.registered and eprint.connection_state == "connected"
    assert eprint.cloud_services_enabled is True and eprint.platform == "gen2"
    logs = ProductLogs.from_node(load_xml("ProductLogsDyn.xml"))
    assert len(logs.events) == 5
    assert logs.events[0].code == "74740" and logs.events[0].occurrences == 6
    assert logs.error_log is not None and "B8210B08" in logs.error_log
    events = [
        DeviceEvent.from_node(e) for e in load_xml("EventTable.xml").findall("Event")
    ]
    assert [e.category for e in events] == [
        "DeviceCapabilitiesChanged",
        "PowerUpEvent",
        "ConsumableEvent",
        "AlertTableChanged",
    ]
    assert events[0].aging_stamp == "144-3"


def test_scanner_models() -> None:
    status = ScannerStatus.from_node(load_xml("ScannerStatus.xml"))
    assert status.version == "2.63" and status.state == "Idle"
    assert not status.is_scanning and status.jobs == []
    caps = ScannerCapabilities.from_node(load_xml("ScannerCapabilities.xml"))
    assert caps.make_and_model == "DeskJet Ink Advantage 2700 All-in-One Printer series"
    assert caps.serial_number == "BR28BCB23H"
    assert caps.platen is not None and caps.adf is None and not caps.has_adf
    assert caps.sources == ["Platen"]
    assert caps.platen.max_width == 2550 and caps.platen.max_height == 3508
    assert caps.platen.resolutions == [75, 100, 200, 300, 600, 1200]
    assert caps.platen.color_modes == ["BlackAndWhite1", "Grayscale8", "RGB24"]
    assert caps.platen.document_formats == [
        "application/octet-stream",
        "image/jpeg",
        "application/pdf",
    ]
    assert caps.platen.intents == ["Document", "Photo", "Preview", "TextAndGraphic"]
    assert caps.platen.risky_margins == {
        "left": 34,
        "right": 34,
        "top": 42,
        "bottom": 45,
    }
    assert caps.brightness == {"min": 0, "max": 2000, "normal": 1000, "step": 1}
    assert caps.certifications == ["mopria-certified-scan 1.3"]
    busy = parse_xml(
        '<scan:ScannerStatus xmlns:scan="s" xmlns:pwg="p"><pwg:State>Processing</pwg:State>'
        "<scan:AdfState>ScannerAdfEmpty</scan:AdfState><scan:Jobs><scan:JobInfo>"
        "<pwg:JobUri>/eSCL/ScanJobs/1</pwg:JobUri><pwg:JobState>Processing</pwg:JobState>"
        "<pwg:ImagesToTransfer>1</pwg:ImagesToTransfer></scan:JobInfo></scan:Jobs>"
        "</scan:ScannerStatus>"
    )
    busy_status = ScannerStatus.from_node(busy)
    assert busy_status.is_scanning and busy_status.adf_state == "ScannerAdfEmpty"
    assert busy_status.jobs[0].images_to_transfer == 1


def test_printer_data_state_combination() -> None:
    data = PrinterData()
    assert data.state is PrinterState.UNKNOWN
    data.status = Status.from_node(load_xml("ProductStatusDyn.xml"))
    assert data.state is PrinterState.SLEEPING
    data.scanner = ScannerStatus(state="Processing")
    assert data.state is PrinterState.SCANNING
    data.scanner = None
    data.status = Status(categories=["ready"])
    from hp_printer.models import IppJob, IppStatus

    data.ipp = IppStatus(state="processing")
    assert data.state is PrinterState.PRINTING
    data.ipp = IppStatus(state="idle")
    data.jobs = [IppJob(id=1, state="processing", name="doc")]
    assert data.state is PrinterState.PRINTING
    assert data.current_job is not None and data.current_job.id == 1
    data.jobs = [IppJob(id=2, state="pending")]
    assert data.current_job is not None and data.current_job.id == 2
    data.jobs = [IppJob(id=3, state="completed")]
    assert data.current_job is None
    data.status = None
    assert data.state is PrinterState.IDLE
    data.ipp = IppStatus(state="stopped")
    assert data.state is PrinterState.ERROR
    data.ipp = IppStatus(state="processing")
    assert data.state is PrinterState.PRINTING
    assert "status" in data.as_dict()


def test_ipp_models() -> None:
    from hp_printer.models import IppJob, IppStatus

    status = IppStatus.from_attributes(
        {
            "printer-state": 3,
            "printer-state-reasons": "none",
            "printer-is-accepting-jobs": True,
            "queued-job-count": 0,
            "printer-up-time": 10,
            "printer-wifi-ssid": "CASA",
            "printer-wifi-state": 8,
            "printer-firmware-string-version": "TWP1",
            "operations-supported": [2, 4, 60],
            "identify-actions-supported": ["flash"],
            "media-ready": "iso_a4_210x297mm",
            "printer-supply": ["type=inkCartridge;level=90;"],
        }
    )
    assert status.state == "idle" and status.state_reasons == ["none"]
    assert status.supports_identify and status.supports_print_job
    assert status.media_ready == ["iso_a4_210x297mm"]
    assert status.firmware_version == "TWP1"
    job = IppJob.from_attributes(
        {
            "job-id": 7,
            "job-name": "test.pdf",
            "job-state": 5,
            "job-state-reasons": "job-printing",
            "job-impressions-completed": 1,
            "date-time-at-creation": "2026-10-30T10:00:00+00:00",
        }
    )
    assert job.state == "processing" and job.is_active
    assert job.state_reasons == ["job-printing"]
    assert job.created_at is not None and job.created_at.year == 2026
    done = IppJob.from_attributes({"job-id": 8, "job-state": 9})
    assert done.state == "completed" and not done.is_active
