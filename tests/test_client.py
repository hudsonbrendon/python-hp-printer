"""HPPrinter transport and high level flows against a fake printer (aiohttp server)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

from hp_printer import HPPrinter, PrinterState, ScanSettings
from hp_printer.const import INTERNAL_PRINT_JOBS
from hp_printer.exceptions import (
    HPPrinterAuthenticationError,
    HPPrinterConnectionError,
    HPPrinterNotSupportedError,
    HPPrinterResponseError,
    HPPrinterScanError,
    HPPrinterStatusError,
)

from .conftest import load_fixture

LEDM_FILES = {
    "/DevMgmt/DiscoveryTree.xml": "DiscoveryTree.xml",
    "/DevMgmt/ProductConfigDyn.xml": "ProductConfigDyn.xml",
    "/DevMgmt/ProductConfigCap.xml": "ProductConfigCap.xml",
    "/DevMgmt/ProductStatusDyn.xml": "ProductStatusDyn.xml",
    "/DevMgmt/ConsumableConfigDyn.xml": "ConsumableConfigDyn.xml",
    "/DevMgmt/ProductUsageDyn.xml": "ProductUsageDyn.xml",
    "/DevMgmt/PrintConfigDyn.xml": "PrintConfigDyn.xml",
    "/DevMgmt/PrintConfigCap.xml": "PrintConfigCap.xml",
    "/DevMgmt/MediaHandlingDyn.xml": "MediaHandlingDyn.xml",
    "/DevMgmt/MediaDyn.xml": "MediaDyn.xml",
    "/DevMgmt/NetAppsDyn.xml": "NetAppsDyn.xml",
    "/DevMgmt/NetAppsSecureDyn.xml": "NetAppsSecureDyn.xml",
    "/DevMgmt/ProductLogsDyn.xml": "ProductLogsDyn.xml",
    "/Copy/CopyConfigDyn.xml": "CopyConfigDyn.xml",
    "/Copy/CopyConfigCap.xml": "CopyConfigCap.xml",
    "/IoMgmt/Adapters": "Adapters.xml",
    "/IoMgmt/IoConfig.xml": "IoConfig.xml",
    "/IoMgmt/Adapters/Wifi0/Protocols": "Wifi0Protocols.xml",
    "/IoMgmt/Adapters/Wifi0/NetworkStats": "Wifi0NetworkStats.xml",
    "/FirmwareUpdate/WebFWUpdate": "WebFWUpdate.xml",
    "/Calibration/State": "CalibrationState.xml",
    "/ePrint/ePrintConfigDyn.xml": "ePrintConfigDyn.xml",
    "/EventMgmt/EventTable": "EventTable.xml",
    "/Utilities/ICCStatus": "ICCStatus.xml",
    "/eSCL/ScannerCapabilities": "ScannerCapabilities.xml",
    "/eSCL/ScannerStatus": "ScannerStatus.xml",
}

SCAN_JOB = "/eSCL/ScanJobs/job-1"


class FakePrinter:
    """Minimal fake of the DeskJet HTTP surface."""

    def __init__(self) -> None:
        """Initialise request log and behaviour knobs."""
        self.requests: list[tuple[str, str, bytes]] = []
        self.quiet = "false"
        self.password: str | None = None
        self.redirect_writes = True
        self.scan_pages: list[bytes] = [b"\xff\xd8page1"]
        self.scan_status_503 = 0
        self.scan_fail = False
        self.https_port = 0
        self.app = web.Application()
        self.app.router.add_route("*", "/{tail:.*}", self.handle)

    async def handle(self, request: web.Request) -> web.StreamResponse:
        """Dispatch every request."""
        body = await request.read()
        self.requests.append((request.method, request.path, body))
        path = request.path
        if request.method == "GET":
            if path in LEDM_FILES:
                return web.Response(
                    body=load_fixture(LEDM_FILES[path]), content_type="text/xml"
                )
            if path == "/cdm/servicesDiscovery":
                return web.Response(
                    body=load_fixture("servicesDiscovery.json"),
                    content_type="application/json",
                )
            if path == "/cdm/print/v1/printModeConfiguration":
                return web.json_response(
                    {"version": "1.0.0", "quietPrintModeEnabled": self.quiet}
                )
            if path == "/broken.json":
                return web.Response(body=b"{nope", content_type="application/json")
            if path == "/broken.xml":
                return web.Response(body=b"<nope", content_type="text/xml")
            if path == "/DevMgmt/SecurityDyn.xml":
                auth = request.headers.get("Authorization")
                if self.password and auth != _basic("admin", self.password):
                    return web.Response(status=401)
                return web.Response(body=b"<x/>", content_type="text/xml")
            if path == "/teapot":
                return web.Response(status=418, body=b"short and stout")
            if path == f"{SCAN_JOB}/NextDocument":
                if self.scan_status_503:
                    self.scan_status_503 -= 1
                    return web.Response(status=503)
                if self.scan_pages:
                    return web.Response(
                        body=self.scan_pages.pop(0), content_type="image/jpeg"
                    )
                return web.Response(status=404)
            return web.Response(status=404)
        if request.method == "POST" and path == "/eSCL/ScanJobs":
            if self.scan_fail:
                return web.Response(status=409)
            return web.Response(
                status=201, headers={"Location": f"http://127.0.0.1:80{SCAN_JOB}"}
            )
        if request.method == "POST" and path in (
            "/DevMgmt/InternalPrintDyn.xml",
            "/Calibration/Session",
            "/Utilities/ICCJob",
        ):
            return web.Response(status=201)
        if request.method == "DELETE" and path == SCAN_JOB:
            return web.Response(status=200)
        if request.method == "PUT" and path == "/cdm/print/v1/printModeConfiguration":
            self.quiet = (await request.json())["quietPrintModeEnabled"]
            return web.Response(status=200)
        if request.method in ("PUT", "PATCH") and path.startswith("/cdm/"):
            return web.Response(status=200)
        if request.method == "PUT":
            # LEDM writes: redirect to https once, then require basic auth.
            if (
                self.redirect_writes
                and request.scheme == "http"
                and not request.headers.get("X-Secure")
            ):
                return web.Response(
                    status=301,
                    headers={"Location": f"https://127.0.0.1:{self.https_port}{path}"},
                )
            auth = request.headers.get("Authorization")
            if self.password and auth != _basic("admin", self.password):
                return web.Response(
                    status=401, headers={"WWW-Authenticate": 'Basic realm="admin"'}
                )
            return web.Response(status=200)
        return web.Response(status=405)


def _basic(user: str, password: str) -> str:
    import base64

    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


@pytest.fixture
async def fake() -> AsyncIterator[tuple[FakePrinter, Callable[..., HPPrinter]]]:
    printer = FakePrinter()
    server = TestServer(printer.app)
    await server.start_server()
    port = server.port
    assert port is not None
    printer.redirect_writes = False  # plain http server: no https hop in tests

    def make(**kwargs: Any) -> HPPrinter:
        return HPPrinter(
            "127.0.0.1", port=port, https_port=port, ipp_port=port, **kwargs
        )

    try:
        yield printer, make
    finally:
        await server.close()


async def test_discover_and_update(
    fake: tuple[FakePrinter, Callable[..., HPPrinter]],
) -> None:
    printer, make = fake
    async with make() as client:
        caps = await client.discover()
        assert caps.has_ledm and caps.has_cdm and caps.has_escl
        data = await client.update(include_jobs=False)
        # IPP is not served by the fake: it is reported, not raised
        assert "ipp" in data.errors
        assert data.device is not None and data.device.serial_number == "BR28BCB23H"
        assert data.status is not None and data.state is PrinterState.SLEEPING
        assert data.consumables is not None
        assert data.consumables.consumables[1].raw_level == 65  # usage merged
        assert data.usage is not None and data.usage.total_impressions == 66
        assert data.settings is not None and data.settings.quiet_mode is False
        assert data.settings_capabilities is not None
        assert data.print_config is not None and data.copy_config is not None
        assert data.media is not None and data.media.default_tray == "Tray1"
        assert data.network is not None and data.network.wifi is not None
        assert data.network.wifi.ipv4_address == "192.168.31.12"
        assert data.firmware is not None and data.eprint is not None
        assert data.calibration_state == "CalibrationRequired"
        assert data.internet_connection_state == "idle"
        assert data.logs is not None and data.events
        assert data.scanner is not None and data.scanner_capabilities is not None
        # second poll without statics carries them over
        again = await client.update(
            include_static=False,
            include_network=False,
            include_jobs=False,
            previous=data,
        )
        assert again.device is data.device and again.network is data.network
        assert again.usage is data.usage
        assert (
            again.consumables is not None
            and again.consumables.consumables[1].raw_level == 65
        )
        assert await client.get_state() is PrinterState.SLEEPING
    assert client._session is None  # own session closed


async def test_transport_errors(
    fake: tuple[FakePrinter, Callable[..., HPPrinter]],
) -> None:
    _, make = fake
    async with make() as client:
        with pytest.raises(HPPrinterNotSupportedError):
            await client.get_xml("/missing")
        with pytest.raises(HPPrinterResponseError):
            await client.get_json("/broken.json")
        with pytest.raises(HPPrinterResponseError):
            await client.get_xml("/broken.xml")
        with pytest.raises(HPPrinterStatusError) as err:
            await client.get_xml("/teapot")
        assert err.value.status == 418 and err.value.body == b"short and stout"
    async with HPPrinter("127.0.0.1", port=1, request_timeout=2) as dead:
        with pytest.raises(HPPrinterConnectionError):
            await dead.get_xml("/DevMgmt/DiscoveryTree.xml")
        with pytest.raises(HPPrinterConnectionError):
            await dead.discover()


async def test_writes(fake: tuple[FakePrinter, Callable[..., HPPrinter]]) -> None:
    printer, make = fake
    async with make() as client:
        await client.set_quiet_mode(True)  # CDM path, no password needed
        assert printer.quiet == "true"
        await client.set_quiet_mode(False)
        assert printer.quiet == "false"
        await client.set_device_language("en")  # CDM control panel
        assert printer.requests[-1][1] == "/cdm/controlPanel/v1/configuration"
        # LEDM writes without password: fake requires none here
        await client.set_power_save_timeout("10minutes")
        method, path, body = printer.requests[-1]
        assert (method, path) == ("PUT", "/DevMgmt/ProductConfigDyn.xml")
        assert b"<dd:PowerSaveTimeout>10minutes</dd:PowerSaveTimeout>" in body
        assert (
            b'xmlns:prdcfgdyn2="http://www.hp.com/schemas/imaging/con/ledm/productconfigdyn/2009/03/16"'
            in body
        )
        await client.set_country("brazil")
        assert (
            b"<prdcfgdyn:CountryAndRegionName>brazil</prdcfgdyn:CountryAndRegionName>"
            in printer.requests[-1][2]
        )
        await client.set_ews_enabled(False)
        assert (
            b"<prdcfgdyn:EWS><dd:EnableDisable>disabled</dd:EnableDisable></prdcfgdyn:EWS>"
            in printer.requests[-1][2]
        )
        await client.set_device_location("Office <1>")
        assert (
            b"<dd:DeviceLocation>Office &lt;1&gt;</dd:DeviceLocation>"
            in printer.requests[-1][2]
        )
        await client.set_product_settings()  # no-op
        await client.set_auto_off_time("2hours")
        await client.set_time_format("HR24")
        await client.set_date_format("DDMMMYYYY")
        await client.set_clock("2026-10-30T10:00:00")
        await client.set_device_description("desc")
        await client.set_print_config(
            copies=2,
            quality="Best",
            resolution="fast1200dpi",
            borderless=True,
            colorlok=False,
            job_timeout_seconds=60,
            courier="dark",
        )
        body = printer.requests[-1][2]
        assert b"<dd:DefaultPrintCopies>2</dd:DefaultPrintCopies>" in body
        assert b"<dd:BorderlessPrinting>true</dd:BorderlessPrinting>" in body
        assert b"<dd:JobTimeout><dd:LeaseTime>60</dd:LeaseTime>" in body
        await client.set_print_config()  # no-op
        await client.set_copy_config(
            copies=3,
            quality="best",
            lighter_darker=5,
            media_size="iso_a4_210x297mm",
            media_type="plain",
            reduce_enlarge="fitToPage",
            reduce_enlarge_custom=50,
            output_type="color",
            margin_off=False,
        )
        body = printer.requests[-1][2]
        assert b"<copy:DefaultNumberOfCopies>3</copy:DefaultNumberOfCopies>" in body
        assert b"<copy:DefaultMarginOff>disabled</copy:DefaultMarginOff>" in body
        await client.set_copy_config()
        await client.set_network_services(
            ipp=True,
            port9100=False,
            snmp=False,
            mdns=True,
            mdns_name="My HP",
            ws_discovery=True,
            ws_print=False,
            ws_scan=True,
            llmnr=False,
            dhcpv6=True,
            https_redirect=False,
            webscan=True,
            direct_print=False,
        )
        body = printer.requests[-1][2]
        assert b"<nadyn:IPPSupport>enabled</nadyn:IPPSupport>" in body
        assert b"<dd:ApplicationServiceName>My HP</dd:ApplicationServiceName>" in body
        assert b"<dd:SNMP>disabled</dd:SNMP>" in body
        assert b"<nadyn:WSScan>enabled</nadyn:WSScan>" in body
        await client.set_network_services()
        await client.set_secure_network_services(
            wifi_direct_show_passphrase=False,
            wifi_direct_hide_ssid=True,
            wifi_direct_connection_method="auto",
            airprint=True,
            ipps=False,
            wpad=False,
            bluetooth=False,
            remote_scans=True,
        )
        body = printer.requests[-1][2]
        assert b"<nasdyn:HideSSID>true</nasdyn:HideSSID>" in body
        assert (
            b"<nasdyn:IPPSConfig><nasdyn:State>disabled</nasdyn:State></nasdyn:IPPSConfig>"
            in body
        )
        await client.set_secure_network_services()
        await client.set_firmware_auto(check=True, update=False)
        body = printer.requests[-1][2]
        assert printer.requests[-1][1] == "/FirmwareUpdate/WebFWUpdate/Config"
        assert b"<fwudyn:AutomaticUpdate>disabled</fwudyn:AutomaticUpdate>" in body
        await client.set_firmware_auto()
        await client.firmware_action("check")
        assert printer.requests[-1][1] == "/FirmwareUpdate/WebFWUpdate/StateAction"
        assert (
            b"<fwudyn:UpdateAction>check</fwudyn:UpdateAction>"
            in printer.requests[-1][2]
        )
        with pytest.raises(ValueError, match="action"):
            await client.firmware_action("explode")
        await client.print_internal_page("networkSummary")
        assert printer.requests[-1][1] == "/DevMgmt/InternalPrintDyn.xml"
        assert (
            b"<ipdyn:JobType>networkSummary</ipdyn:JobType>" in printer.requests[-1][2]
        )
        await client.clean_cartridges(2)
        assert b"cleaningPageLevel2" in printer.requests[-1][2]
        await client.align_cartridges()
        assert printer.requests[-1][1] == "/Calibration/Session"
        assert b">Printing</cal:CalibrationState>" in printer.requests[-1][2]
        await client.check_internet_connection()
        assert printer.requests[-1][1] == "/Utilities/ICCJob"
        await client.restart()
        assert printer.requests[-1][1] == "/ProductActions/PowerCycle"
        assert HPPrinter.supported_internal_pages() == INTERNAL_PRINT_JOBS


async def test_write_requires_password(
    fake: tuple[FakePrinter, Callable[..., HPPrinter]],
) -> None:
    printer, make = fake
    printer.password = "secret"
    async with make() as client:
        with pytest.raises(HPPrinterAuthenticationError, match="requires"):
            await client.set_power_save_timeout("10minutes")
    # the fake only speaks plain HTTP, so let the client send credentials over it
    async with make(password="wrong") as client:
        client._send_auth_over_http = True
        with pytest.raises(HPPrinterAuthenticationError, match="rejected"):
            await client.set_power_save_timeout("10minutes")
    async with make(password="secret") as client:
        client._send_auth_over_http = True
        await client.set_power_save_timeout("10minutes")
        assert printer.requests[-1][1] == "/DevMgmt/ProductConfigDyn.xml"
    async with make() as client:
        assert await client.check_password() is None  # no password configured
    async with make(password="wrong") as client:
        client._send_auth_over_http = True
        assert await client.check_password() is False
    async with make(password="secret") as client:
        client._send_auth_over_http = True
        assert await client.check_password() is True
    # without the flag nothing is sent over http even when a password is known
    async with make(password="secret") as client:
        with pytest.raises(HPPrinterAuthenticationError, match="requires"):
            await client.set_power_save_timeout("10minutes")


async def test_scan_flow(fake: tuple[FakePrinter, Callable[..., HPPrinter]]) -> None:
    printer, make = fake
    async with make() as client:
        events: list[str] = []
        pages = await client.scan(ScanSettings(resolution=75), progress=events.append)
        assert pages == [b"\xff\xd8page1"]
        assert events == ["started", "page 1"]
        posted = next(
            b for m, p, b in printer.requests if m == "POST" and p == "/eSCL/ScanJobs"
        )
        assert b"<scan:XResolution>75</scan:XResolution>" in posted
        assert ("DELETE", SCAN_JOB, b"") in printer.requests
        # 503 retries then success
        printer.scan_pages = [b"p"]
        printer.scan_status_503 = 2
        assert await client.scan(ScanSettings(resolution=75)) == [b"p"]
        # unsupported resolution / source
        with pytest.raises(HPPrinterScanError, match="Resolution"):
            await client.scan(ScanSettings(resolution=123))
        with pytest.raises(HPPrinterScanError, match="input source"):
            await client.scan(ScanSettings(source="Feeder", resolution=75))
        printer.scan_fail = True
        with pytest.raises(HPPrinterScanError, match="rejected"):
            await client.scan(ScanSettings(resolution=75))
        printer.scan_fail = False
        # job finished without pages -> error from scanner status (fixture has no job)
        printer.scan_pages = []
        import hp_printer.client as client_module

        client_module._SCAN_TIMEOUT = 2.5
        with pytest.raises(HPPrinterScanError):
            await client.scan(ScanSettings(resolution=75))
        client_module._SCAN_TIMEOUT = 180.0
        await client.cancel_scan("/eSCL/ScanJobs/nope", silent=True)
        with pytest.raises(HPPrinterNotSupportedError):
            await client.cancel_scan("/eSCL/ScanJobs/nope")


async def test_cdm_only_printer() -> None:
    """A printer that only answers /cdm/* must still produce PrinterData."""
    app = web.Application()
    fixtures = {
        "/cdm/servicesDiscovery": "servicesDiscovery.json",
        "/cdm/system/v1/identity": "cdm/cdm_system_v1_identity.json",
        "/cdm/system/v1/status": "cdm/cdm_system_v1_status.json",
        "/cdm/alert/v1/alerts": "cdm/cdm_alert_v1_alerts.json",
        "/cdm/print/v2/status": "cdm/cdm_print_v2_status.json",
        "/cdm/supply/v1/suppliesPublic": "cdm/cdm_supply_v1_suppliesPublic.json",
        "/cdm/deviceUsage/v1/lifetimeCounters": "cdm/cdm_deviceUsage_v1_lifetimeCounters.json",
        "/cdm/deviceUsage/v1/serviceCounters": "cdm/cdm_deviceUsage_v1_serviceCounters.json",
        "/cdm/power/v1/configuration": "cdm/cdm_power_v1_configuration.json",
        "/cdm/system/v1/configuration": "cdm/cdm_system_v1_configuration.json",
        "/cdm/print/v2/configuration": "cdm/cdm_print_v2_configuration.json",
        "/cdm/firmwareUpdate/v2/configuration": "cdm/cdm_firmwareUpdate_v2_configuration.json",
        "/cdm/firmwareUpdate/v2/updateStatus": "cdm/cdm_firmwareUpdate_v2_updateStatus.json",
        "/cdm/firmwareUpdate/v2/updateCheck": "cdm/cdm_firmwareUpdate_v2_updateCheck.json",
        "/cdm/media/v1/configuration": "cdm/cdm_media_v1_configuration.json",
        "/cdm/network/v1/discoveryServices": "cdm/cdm_network_v1_discoveryServices.json",
        "/cdm/network/v1/printServices": "cdm/cdm_network_v1_printServices.json",
        "/cdm/network/v1/nameResolverServices": "cdm/cdm_network_v1_nameResolverServices.json",
        "/cdm/network/v1/snmpConfig": "cdm/cdm_network_v1_snmpConfig.json",
    }
    writes: list[tuple[str, str]] = []

    async def handle(request: web.Request) -> web.Response:
        if request.method == "GET" and request.path in fixtures:
            return web.Response(
                body=load_fixture(fixtures[request.path]),
                content_type="application/json",
            )
        if request.method in ("PUT", "PATCH") and request.path.startswith("/cdm/"):
            writes.append((request.method, request.path))
            return web.Response(status=204)
        return web.Response(status=404)

    app.router.add_route("*", "/{tail:.*}", handle)
    server = TestServer(app)
    await server.start_server()
    try:
        async with HPPrinter("127.0.0.1", port=server.port or 80, ipp_port=1) as client:
            caps = await client.discover()
            assert caps.has_cdm and not caps.has_ledm and not caps.has_escl
            data = await client.update(include_jobs=False)
            assert data.device is not None and "Smart Tank" in (
                data.device.make_and_model or ""
            )
            assert data.consumables is not None and data.consumables.consumables
            assert data.usage is not None and data.usage.total_impressions == 10531
            assert (
                data.settings is not None
                and data.settings.power_save_timeout == "5minutes"
            )
            assert data.firmware is not None and data.media is not None
            assert data.network is not None and data.network.ipp_enabled
            assert data.state in (PrinterState.SLEEPING, PrinterState.IDLE)
            assert (await client.get_device_info()).serial_number == "SN-ANON-0000"
            assert await client.get_state() in (
                PrinterState.SLEEPING,
                PrinterState.IDLE,
            )
            await client.set_firmware_auto(update=True)
            await client.firmware_action("check")
            await client.print_internal_page("configurationPage")
            await client.align_cartridges()
            await client.restart()
            assert ("PATCH", "/cdm/firmwareUpdate/v2/configuration") in writes
            assert ("PATCH", "/cdm/report/v1/print") in writes
            assert (
                "PATCH",
                "/cdm/calibration/v1/calibration/penAlignSemiauto",
            ) in writes
            assert ("PATCH", "/cdm/power/v1/reboot") in writes
    finally:
        await server.close()


async def test_neither_protocol() -> None:
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", lambda _r: web.Response(status=404))
    server = TestServer(app)
    await server.start_server()
    try:
        async with HPPrinter("127.0.0.1", port=server.port or 80) as client:
            with pytest.raises(HPPrinterNotSupportedError, match="neither"):
                await client.discover()
    finally:
        await server.close()
