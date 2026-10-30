"""Async client for HP printers over the LAN (LEDM, CDM, eSCL and IPP)."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
import json
import logging
import socket
from typing import Any, Self

import aiohttp
from yarl import URL

from . import cdm
from .const import (
    DEFAULT_HTTPS_PORT,
    DEFAULT_IPP_PORT,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    DEFAULT_USERNAME,
    FIRMWARE_ACTIONS,
    INTERNAL_PRINT_JOBS,
    MAX_CONCURRENT_REQUESTS,
    NS_CAL,
    NS_COPY,
    NS_CPCFGDYN,
    NS_DD,
    NS_DD3,
    NS_FWUDYN,
    NS_IPDYN,
    NS_NADYN,
    NS_NASDYN,
    NS_PRDCFGDYN,
    NS_PRDCFGDYN2,
    NS_PRNCFGDYN,
    NS_PRNCFGDYN2,
    RES_ADAPTERS,
    RES_CALIBRATION_SESSION,
    RES_CALIBRATION_STATE,
    RES_CDM_CONTROL_PANEL,
    RES_CDM_DISCOVERY,
    RES_CDM_PRINT_MODE,
    RES_CONSUMABLES,
    RES_COPY_CONFIG,
    RES_COPY_CONFIG_CAP,
    RES_DISCOVERY_TREE,
    RES_EPRINT,
    RES_ESCL_CAPS,
    RES_ESCL_JOBS,
    RES_ESCL_STATUS,
    RES_EVENT_TABLE,
    RES_FIRMWARE,
    RES_FIRMWARE_ACTION,
    RES_FIRMWARE_CONFIG,
    RES_ICC_JOB,
    RES_ICC_STATUS,
    RES_INTERNAL_PRINT,
    RES_IO_CONFIG,
    RES_MEDIA,
    RES_MEDIA_HANDLING,
    RES_NET_APPS,
    RES_NET_APPS_SECURE,
    RES_POWER_CYCLE,
    RES_PRINT_CONFIG,
    RES_PRINT_CONFIG_CAP,
    RES_PRODUCT_CONFIG,
    RES_PRODUCT_CONFIG_CAP,
    RES_PRODUCT_LOGS,
    RES_PRODUCT_STATUS,
    RES_SECURITY,
    RES_USAGE,
    USER_AGENT,
    PrinterState,
)
from .escl import ScanSettings
from .exceptions import (
    HPPrinterAuthenticationError,
    HPPrinterConnectionError,
    HPPrinterConnectionTimeoutError,
    HPPrinterError,
    HPPrinterNotSupportedError,
    HPPrinterResponseError,
    HPPrinterScanError,
    HPPrinterStatusError,
)
from .ipp import IppClient
from .models import (
    Capabilities,
    ConsumablesInfo,
    CopyConfig,
    DeviceEvent,
    DeviceInfo,
    EPrint,
    Firmware,
    IppJob,
    IppStatus,
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
from .xml_utils import Node, escape, parse_xml, xml_document

_LOGGER = logging.getLogger(__name__)

_REDIRECT_CODES = frozenset({301, 302, 307, 308})
_UNSUPPORTED_CODES = frozenset({400, 404, 405, 410, 501})

_PRODUCT_CONFIG_NS = {
    "prdcfgdyn2": NS_PRDCFGDYN2,
    "prdcfgdyn": NS_PRDCFGDYN,
    "dd": NS_DD,
}
_PRINT_CONFIG_NS = {
    "prncfgdyn2": NS_PRNCFGDYN2,
    "prncfgdyn": NS_PRNCFGDYN,
    "dd": NS_DD,
}
_COPY_CONFIG_NS = {"cpcfgdyn": NS_CPCFGDYN, "copy": NS_COPY, "dd": NS_DD}
_NET_APPS_NS = {"nadyn": NS_NADYN, "dd": NS_DD, "dd3": NS_DD3}
_NET_APPS_SECURE_NS = {"nasdyn": NS_NASDYN, "dd": NS_DD}
_FIRMWARE_NS = {"fwudyn": NS_FWUDYN}
_INTERNAL_PRINT_NS = {"ipdyn": NS_IPDYN, "dd": NS_DD}
_CAL_NS = {"cal": NS_CAL}

# ProductSettings children live in different namespaces: tag -> (prefix, wrapper)
_PRODUCT_SETTING_TAGS: dict[str, tuple[str, str | None]] = {
    "PowerSaveTimeout": ("dd", None),
    "AutoOffTime": ("dd", None),
    "TimeStamp": ("dd", None),
    "TimeFormat": ("dd", None),
    "DateFormat": ("dd", None),
    "QuietPrintMode": ("dd", None),
    "PowerSave": ("dd", None),
    "DeviceLanguage": ("dd", "prdcfgdyn:ProductLanguage"),
    "CountryAndRegionName": ("prdcfgdyn", None),
    "EnableDisable": ("dd", "prdcfgdyn:EWS"),
    "DeviceLocation": ("dd", "prdcfgdyn:DeviceInformation"),
    "Description": ("dd", "prdcfgdyn:DeviceInformation"),
}

_SCAN_POLL_INTERVAL = 1.0
_SCAN_TIMEOUT = 300.0
_SCAN_PAGE_TIMEOUT = 120.0
_SCAN_RETRY_503 = 30


def _on_off(value: bool, on: str = "enabled", off: str = "disabled") -> str:
    return on if value else off


class HPPrinter:
    """Async client talking to one HP printer.

    Reads are unauthenticated on every HP model. Writes to LEDM resources are
    redirected to HTTPS and require the EWS admin password (``password``); CDM
    writes usually work without credentials.
    """

    # Credentials are only sent over TLS unless a printer insists otherwise.
    _send_auth_over_http: bool = False

    def __init__(
        self,
        host: str,
        *,
        port: int = DEFAULT_PORT,
        https_port: int = DEFAULT_HTTPS_PORT,
        ipp_port: int = DEFAULT_IPP_PORT,
        username: str = DEFAULT_USERNAME,
        password: str | None = None,
        session: aiohttp.ClientSession | None = None,
        request_timeout: float = DEFAULT_TIMEOUT,
        verify_ssl: bool = False,
        use_https: bool = False,
    ) -> None:
        """Create the client. Pass ``session`` to share Home Assistant's session."""
        self.host = host
        self.port = port
        self.https_port = https_port
        self.username = username
        self.password = password
        self.request_timeout = request_timeout
        self.verify_ssl = verify_ssl
        self.use_https = use_https
        self._session = session
        self._close_session = session is None
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        self.ipp_port = ipp_port
        self.capabilities: Capabilities | None = None
        self._scanner_caps: ScannerCapabilities | None = None
        self._ipp: IppClient | None = None
        self._ipp_session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------ #
    # Session / transport
    # ------------------------------------------------------------------ #
    @property
    def session(self) -> aiohttp.ClientSession:
        """The aiohttp session (created lazily when none was injected)."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._close_session = True
        return self._session

    @property
    def ipp(self) -> IppClient:
        """IPP client on a dedicated session without keep-alive.

        HP's IPP server hangs on reused connections just like its HTTP
        server, and ``pyipp`` cannot be told to close them, so IPP gets its
        own session with ``force_close``.
        """
        if self._ipp is None:
            self._ipp_session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(force_close=True)
            )
            self._ipp = IppClient(
                self.host,
                port=self.ipp_port,
                session=self._ipp_session,
                request_timeout=self.request_timeout,
            )
        return self._ipp

    async def close(self) -> None:
        """Close the IPP session and the HTTP session if this client created it."""
        if self._ipp_session is not None:
            await self._ipp_session.close()
            self._ipp_session = None
            self._ipp = None
        if self._session is not None and self._close_session:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> Self:
        """Async context manager entry."""
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Async context manager exit."""
        await self.close()

    def url(self, path: str, *, secure: bool = False) -> URL:
        """Build the URL of a resource."""
        if secure or self.use_https:
            return URL.build(
                scheme="https", host=self.host, port=self.https_port, path=path
            )
        return URL.build(scheme="http", host=self.host, port=self.port, path=path)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        data: bytes | str | None = None,
        content_type: str | None = None,
        accept: str = "*/*",
        secure: bool = False,
        read_timeout: float | None = None,
        _redirected: bool = False,
    ) -> tuple[int, bytes, dict[str, str]]:
        """Perform a request and return ``(status, body, headers)``.

        Handles the HTTP->HTTPS redirect HP uses for writes, HTTP basic auth
        for the EWS admin realm and maps transport errors to library errors.
        """
        url = self.url(path, secure=secure)
        # HP's embedded server mishandles idle keep-alive sockets (stale or
        # hung responses), so every request uses a fresh connection.
        headers = {"User-Agent": USER_AGENT, "Accept": accept, "Connection": "close"}
        if content_type:
            headers["Content-Type"] = content_type
        kwargs: dict[str, Any] = {
            "headers": headers,
            "data": data,
            "allow_redirects": False,
        }
        if url.scheme == "https":
            kwargs["ssl"] = None if self.verify_ssl else False
        sent_auth = bool(self.password) and (
            url.scheme == "https" or self._send_auth_over_http
        )
        if sent_auth:
            token = base64.b64encode(
                f"{self.username}:{self.password}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {token}"
        try:
            async with (
                self._semaphore,
                asyncio.timeout(read_timeout or self.request_timeout),
                self.session.request(method, url, **kwargs) as response,
            ):
                body = await response.read()
                status = response.status
                resp_headers = dict(response.headers.items())
        except TimeoutError as err:
            raise HPPrinterConnectionTimeoutError(
                f"Timeout while talking to {self.host}{path}"
            ) from err
        except (aiohttp.ClientError, socket.gaierror, OSError) as err:
            raise HPPrinterConnectionError(
                f"Error communicating with {self.host}{path}: {err}"
            ) from err

        if status in _REDIRECT_CODES and not _redirected:
            location = resp_headers.get("Location", "")
            if location.startswith("https://") or url.scheme == "http":
                return await self._request(
                    method,
                    path,
                    data=data,
                    content_type=content_type,
                    accept=accept,
                    secure=True,
                    read_timeout=read_timeout,
                    _redirected=True,
                )
        if status == 401:
            raise HPPrinterAuthenticationError(
                f"Printer rejected the admin password for {method} {path}"
                if sent_auth
                else f"{method} {path} requires the printer admin password"
            )
        if status in _UNSUPPORTED_CODES:
            raise HPPrinterNotSupportedError(
                f"{method} {path} is not supported by this printer (HTTP {status})"
            )
        if status >= 400:
            raise HPPrinterStatusError(
                f"{method} {path} failed with HTTP {status}", status=status, body=body
            )
        return status, body, resp_headers

    async def get_xml(self, path: str) -> Node:
        """GET an XML resource."""
        _, body, _ = await self._request("GET", path, accept="text/xml, */*")
        return parse_xml(body)

    async def get_json(self, path: str) -> Any:
        """GET a JSON resource (CDM)."""
        _, body, _ = await self._request("GET", path, accept="application/json")
        try:
            return json.loads(body or b"null")
        except json.JSONDecodeError as err:
            raise HPPrinterResponseError(f"Invalid JSON from {path}") from err

    async def put_xml(self, path: str, body: str) -> None:
        """PUT an XML document (LEDM write)."""
        await self._request("PUT", path, data=body.encode(), content_type="text/xml")

    async def post_xml(self, path: str, body: str) -> dict[str, str]:
        """POST an XML document and return the response headers."""
        _, _, headers = await self._request(
            "POST", path, data=body.encode(), content_type="text/xml"
        )
        return headers

    async def put_json(self, path: str, payload: dict[str, Any]) -> None:
        """PUT a JSON document (CDM write)."""
        await self._request(
            "PUT",
            path,
            data=json.dumps(payload).encode(),
            content_type="application/json",
        )

    async def patch_json(self, path: str, payload: dict[str, Any]) -> None:
        """PATCH a JSON document (CDM action)."""
        await self._request(
            "PATCH",
            path,
            data=json.dumps(payload).encode(),
            content_type="application/json",
        )

    async def _optional_xml(self, path: str) -> Node | None:
        try:
            return await self.get_xml(path)
        except HPPrinterNotSupportedError:
            return None

    async def _optional_json(self, path: str) -> Any | None:
        try:
            return await self.get_json(path)
        except HPPrinterNotSupportedError, HPPrinterResponseError:
            return None

    # ------------------------------------------------------------------ #
    # Discovery / capabilities
    # ------------------------------------------------------------------ #
    async def discover(self) -> Capabilities:
        """Probe the printer and remember which protocols/resources it has."""
        tree: Node | None = None
        services: dict[str, Any] | None = None
        try:
            tree = await self.get_xml(RES_DISCOVERY_TREE)
        except HPPrinterNotSupportedError:
            tree = None
        except HPPrinterConnectionError:
            if not self.use_https:
                # CDM-only firmware (nginx) refuses plain HTTP: retry over TLS.
                self.use_https = True
                tree = await self._optional_xml(RES_DISCOVERY_TREE)
            else:
                raise
        services_raw = await self._optional_json(RES_CDM_DISCOVERY)
        if isinstance(services_raw, dict) and "services" in services_raw:
            services = services_raw
        if tree is None and services is None:
            raise HPPrinterNotSupportedError(
                f"{self.host} answers neither LEDM nor CDM; is it an HP printer?"
            )
        self.capabilities = Capabilities.from_discovery(tree, services)
        return self.capabilities

    async def _caps(self) -> Capabilities:
        if self.capabilities is None:
            await self.discover()
        if self.capabilities is None:  # pragma: no cover - discover() always sets it
            raise HPPrinterError("Capability discovery failed")
        return self.capabilities

    async def check_password(self) -> bool | None:
        """Verify the admin password against a protected LEDM resource.

        Returns ``True`` when accepted, ``False`` when rejected and ``None``
        when the printer has no password-protected resource to test against.
        """
        if not self.password:
            return None
        try:
            # plain HTTP is redirected to HTTPS by the printer, then 401 without auth
            await self._request("GET", RES_SECURITY, accept="text/xml")
        except HPPrinterAuthenticationError:
            return False
        except HPPrinterNotSupportedError:
            return None
        return True

    # ------------------------------------------------------------------ #
    # LEDM getters
    # ------------------------------------------------------------------ #
    async def get_device_info(self) -> DeviceInfo:
        """Identification (``ProductConfigDyn`` or CDM identity)."""
        caps = await self._caps()
        if caps.has_ledm:
            return DeviceInfo.from_node(await self.get_xml(RES_PRODUCT_CONFIG))
        identity = await self.get_json(
            caps.cdm_href("system", "identity") or "/cdm/system/v1/identity"
        )
        return cdm.parse_identity(identity)

    async def get_settings(self) -> Settings:
        """Product settings (``ProductConfigDyn/ProductSettings``)."""
        return Settings.from_node(await self.get_xml(RES_PRODUCT_CONFIG))

    async def get_settings_capabilities(self) -> SettingsCapabilities:
        """Allowed values for the settings (``ProductConfigCap``)."""
        return SettingsCapabilities.from_node(
            await self.get_xml(RES_PRODUCT_CONFIG_CAP)
        )

    async def get_status(self) -> Status:
        """Live status (``ProductStatusDyn``)."""
        return Status.from_node(await self.get_xml(RES_PRODUCT_STATUS))

    async def get_consumables(self, *, with_usage: bool = True) -> ConsumablesInfo:
        """Cartridges / toner (``ConsumableConfigDyn`` + usage counters)."""
        info = ConsumablesInfo.from_node(await self.get_xml(RES_CONSUMABLES))
        if with_usage:
            usage = await self._optional_xml(RES_USAGE)
            if usage is not None:
                info.merge_usage(usage)
        return info

    async def get_usage(self) -> Usage:
        """Lifetime counters (``ProductUsageDyn``)."""
        return Usage.from_node(await self.get_xml(RES_USAGE))

    async def get_print_config(self) -> PrintConfig:
        """Default print settings (``PrintConfigDyn`` + ``PrintConfigCap``)."""
        dyn = await self.get_xml(RES_PRINT_CONFIG)
        cap = await self._optional_xml(RES_PRINT_CONFIG_CAP)
        return PrintConfig.from_node(dyn, cap)

    async def get_copy_config(self) -> CopyConfig:
        """Default copy settings (``CopyConfigDyn`` + ``CopyConfigCap``)."""
        dyn = await self.get_xml(RES_COPY_CONFIG)
        cap = await self._optional_xml(RES_COPY_CONFIG_CAP)
        return CopyConfig.from_node(dyn, cap)

    async def get_media(self) -> MediaHandling:
        """Trays and loaded media (``MediaHandlingDyn`` + ``MediaDyn``)."""
        handling = await self.get_xml(RES_MEDIA_HANDLING)
        media = await self._optional_xml(RES_MEDIA)
        return MediaHandling.from_node(handling, media)

    async def get_network(self) -> Network:
        """Adapters, protocols and Wi-Fi Direct configuration."""
        adapters, io_config, net_apps, secure = await asyncio.gather(
            self._optional_xml(RES_ADAPTERS),
            self._optional_xml(RES_IO_CONFIG),
            self._optional_xml(RES_NET_APPS),
            self._optional_xml(RES_NET_APPS_SECURE),
        )
        network = Network.from_nodes(adapters, io_config, net_apps, secure)
        if adapters is not None:
            for adapter in network.adapters:
                if adapter.adapter_type == "USBAdapter":
                    continue
                base = f"{RES_ADAPTERS}/{adapter.name}"
                protocols, stats = await asyncio.gather(
                    self._optional_xml(f"{base}/Protocols"),
                    self._optional_xml(f"{base}/NetworkStats"),
                )
                if protocols is not None:
                    adapter.merge_protocols(protocols)
                if stats is not None:
                    adapter.merge_stats(stats)
        return network

    async def get_firmware(self) -> Firmware:
        """Web firmware update configuration and state."""
        return Firmware.from_node(await self.get_xml(RES_FIRMWARE))

    async def get_eprint(self) -> EPrint:
        """HP web services / ePrint registration."""
        return EPrint.from_node(await self.get_xml(RES_EPRINT))

    async def get_calibration_state(self) -> str | None:
        """Cartridge alignment state (``CalibrationRequired`` / ``Idle``...)."""
        node = await self.get_xml(RES_CALIBRATION_STATE)
        return node.text or node.get("CalibrationState")

    async def get_internet_connection_state(self) -> str | None:
        """Result of the last internet connectivity check."""
        node = await self.get_xml(RES_ICC_STATUS)
        return node.get("State")

    async def get_logs(self) -> ProductLogs:
        """Event and error logs (``ProductLogsDyn``)."""
        return ProductLogs.from_node(await self.get_xml(RES_PRODUCT_LOGS))

    async def get_events(self) -> list[DeviceEvent]:
        """Recent device events (``EventMgmt/EventTable``)."""
        node = await self.get_xml(RES_EVENT_TABLE)
        return [DeviceEvent.from_node(e) for e in node.findall("Event")]

    # ------------------------------------------------------------------ #
    # eSCL scanner
    # ------------------------------------------------------------------ #
    async def get_scanner_status(self) -> ScannerStatus:
        """``/eSCL/ScannerStatus``."""
        return ScannerStatus.from_node(await self.get_xml(RES_ESCL_STATUS))

    async def get_scanner_capabilities(
        self, *, refresh: bool = False
    ) -> ScannerCapabilities:
        """``/eSCL/ScannerCapabilities`` (cached)."""
        if self._scanner_caps is None or refresh:
            self._scanner_caps = ScannerCapabilities.from_node(
                await self.get_xml(RES_ESCL_CAPS)
            )
        return self._scanner_caps

    async def scan(
        self,
        settings: ScanSettings | None = None,
        *,
        progress: Callable[[str], Awaitable[None] | None] | None = None,
    ) -> list[bytes]:
        """Run a scan job and return every page (one item per document).

        For the platen the list holds one JPEG/PDF; for the ADF one item per
        page (JPEG) or a single multi-page PDF depending on the format.
        """
        settings = settings or ScanSettings()
        caps = await self.get_scanner_capabilities()
        source_caps = (
            caps.adf if settings.source.lower() in ("adf", "feeder") else caps.platen
        )
        if source_caps is None:
            raise HPPrinterScanError(f"Scanner has no '{settings.source}' input source")
        if (
            source_caps.resolutions
            and settings.resolution not in source_caps.resolutions
        ):
            raise HPPrinterScanError(
                f"Resolution {settings.resolution} not supported; use one of "
                f"{source_caps.resolutions}"
            )
        body = settings.to_xml(source_caps.max_width, source_caps.max_height)
        try:
            headers = await self.post_xml(RES_ESCL_JOBS, body)
        except HPPrinterStatusError as err:
            if err.status == 409:
                raise HPPrinterScanError("Scanner rejected the scan settings") from err
            if err.status == 503:
                raise HPPrinterScanError("Scanner busy, try again later") from err
            raise
        location = headers.get("Location") or headers.get("location")
        if not location:
            raise HPPrinterScanError("Scanner did not return a job location")
        job_path = URL(location).path if "://" in location else location
        if progress:
            await _maybe_await(progress("started"))
        pages: list[bytes] = []
        try:
            async with asyncio.timeout(_SCAN_TIMEOUT):
                while True:
                    page = await self._fetch_next_document(job_path, len(pages))
                    if page is None:
                        break
                    pages.append(page)
                    if progress:
                        await _maybe_await(progress(f"page {len(pages)}"))
                    if source_caps is caps.platen:
                        break
        except TimeoutError as err:
            raise HPPrinterScanError("Scan timed out") from err
        finally:
            await self.cancel_scan(job_path, silent=True)
        if not pages:
            raise HPPrinterScanError("Scanner returned no pages")
        return pages

    async def _fetch_next_document(self, job_path: str, received: int) -> bytes | None:
        retries_503 = 0
        while True:
            try:
                # the scanner holds the connection open until the page is ready
                status, body, _ = await self._request(
                    "GET",
                    f"{job_path}/NextDocument",
                    accept="*/*",
                    read_timeout=_SCAN_PAGE_TIMEOUT,
                )
            except HPPrinterNotSupportedError:
                # 404 after at least one page = no more documents.
                if received:
                    return None
                scanner = await self.get_scanner_status()
                job = next(
                    (j for j in scanner.jobs if j.uri and j.uri in job_path), None
                )
                if job and job.state in ("Completed", "Canceled", "Aborted"):
                    # received == 0 here, so a finished job means it failed.
                    reasons = ", ".join(job.reasons) or "unknown"
                    raise HPPrinterScanError(
                        f"Scan job {job.state}: {reasons}"
                    ) from None
                await asyncio.sleep(_SCAN_POLL_INTERVAL)
                continue
            except HPPrinterStatusError as err:
                if err.status == 503 and retries_503 < _SCAN_RETRY_503:
                    retries_503 += 1
                    await asyncio.sleep(_SCAN_POLL_INTERVAL)
                    continue
                raise HPPrinterScanError(f"Scan failed with HTTP {err.status}") from err
            if status == 200 and body:
                return body
            if status == 204 or not body:
                return None
            await asyncio.sleep(_SCAN_POLL_INTERVAL)

    async def cancel_scan(self, job_path: str, *, silent: bool = False) -> None:
        """Cancel/delete an eSCL scan job."""
        try:
            await self._request("DELETE", job_path)
        except HPPrinterError:
            if not silent:
                raise

    # ------------------------------------------------------------------ #
    # IPP
    # ------------------------------------------------------------------ #
    async def get_ipp_status(self) -> IppStatus:
        """IPP printer state, Wi-Fi state and capabilities."""
        return await self.ipp.status()

    async def get_jobs(self, which: str = "all") -> list[IppJob]:
        """Print jobs known to the printer."""
        return await self.ipp.jobs(which)

    async def cancel_job(self, job_id: int) -> None:
        """Cancel a print job."""
        await self.ipp.cancel_job(job_id)

    async def identify(self, action: str = "flash") -> None:
        """Flash the printer display (locate)."""
        await self.ipp.identify(action)

    async def print_data(
        self,
        data: bytes,
        *,
        document_format: str = "application/octet-stream",
        job_name: str = "Home Assistant",
        copies: int = 1,
        media: str | None = None,
        print_quality: int | None = None,
        sides: str | None = None,
    ) -> IppJob | None:
        """Print raw document bytes (JPEG, PDF, PCLm, URF...)."""
        return await self.ipp.print_job(
            data,
            document_format=document_format,
            job_name=job_name,
            copies=copies,
            media=media,
            print_quality=print_quality,
            sides=sides,
        )

    async def validate_print(
        self, *, document_format: str = "application/octet-stream", copies: int = 1
    ) -> bool:
        """Check that the printer would accept a job without printing."""
        return await self.ipp.validate_job(
            document_format=document_format, copies=copies
        )

    # ------------------------------------------------------------------ #
    # Aggregate update
    # ------------------------------------------------------------------ #
    async def update(
        self,
        *,
        include_static: bool = True,
        include_network: bool = True,
        include_jobs: bool = True,
        previous: PrinterData | None = None,
    ) -> PrinterData:
        """Fetch everything the printer supports.

        ``include_static``/``include_network`` let callers poll the rarely
        changing resources (usage, configuration, network) less often and
        carry the previous values over.
        """
        caps = await self._caps()
        data = PrinterData(capabilities=caps)
        if previous is not None:
            for name in (
                "device",
                "settings",
                "settings_capabilities",
                "usage",
                "print_config",
                "copy_config",
                "media",
                "network",
                "firmware",
                "eprint",
                "logs",
                "scanner_capabilities",
                "calibration_state",
                "internet_connection_state",
            ):
                setattr(data, name, getattr(previous, name))

        if caps.has_ledm:
            await self._update_ledm(data, caps, include_static, include_network)
        elif caps.has_cdm:
            await self._update_cdm(data, caps, include_static, include_network)

        tasks: dict[str, Awaitable[Any]] = {}
        if caps.has_escl:
            tasks["scanner"] = self.get_scanner_status()
            if data.scanner_capabilities is None:
                tasks["scanner_capabilities"] = self.get_scanner_capabilities()
        if caps.has_ipp:
            tasks["ipp"] = self.get_ipp_status()
            if include_jobs:
                tasks["jobs"] = self.get_jobs("all")
        await self._run_tasks(data, tasks)
        return data

    async def _update_ledm(
        self,
        data: PrinterData,
        caps: Capabilities,
        include_static: bool,
        include_network: bool,
    ) -> None:
        tasks: dict[str, Awaitable[Any]] = {
            "status": self.get_status(),
            "consumables": self.get_consumables(with_usage=False),
        }
        if include_static or data.device is None:
            tasks["device"] = self.get_device_info()
            tasks["settings"] = self.get_settings()
            tasks["usage"] = self.get_usage()
            tasks["print_config"] = self.get_print_config()
            tasks["media"] = self.get_media()
            if caps.has_copy:
                tasks["copy_config"] = self.get_copy_config()
            if caps.has_firmware_update:
                tasks["firmware"] = self.get_firmware()
            if caps.has_eprint:
                tasks["eprint"] = self.get_eprint()
            if caps.has_calibration:
                tasks["calibration_state"] = self.get_calibration_state()
            tasks["logs"] = self.get_logs()
            tasks["internet_connection_state"] = self.get_internet_connection_state()
            if data.settings_capabilities is None:
                tasks["settings_capabilities"] = self.get_settings_capabilities()
        if caps.has_event_mgmt:
            tasks["events"] = self.get_events()
        if include_network or data.network is None:
            tasks["network"] = self.get_network()
        await self._run_tasks(data, tasks)
        if data.settings is not None and caps.has_cdm:
            # CDM is the authoritative (and password-free) source for quiet mode;
            # the LEDM document can lag behind for a few seconds after a write.
            mode = await self._optional_json(RES_CDM_PRINT_MODE)
            if isinstance(mode, dict) and "quietPrintModeEnabled" in mode:
                data.settings.quiet_mode = (
                    str(mode["quietPrintModeEnabled"]).lower() == "true"
                )
        if data.consumables is not None:
            usage_node = await self._optional_xml(RES_USAGE)
            if usage_node is not None:
                if data.usage is None:
                    data.usage = Usage.from_node(usage_node)
                data.consumables.merge_usage(usage_node)

    async def _update_cdm(
        self,
        data: PrinterData,
        caps: Capabilities,
        include_static: bool,
        include_network: bool,
    ) -> None:
        def href(service: str, rel: str, default: str) -> str:
            return caps.cdm_href(service, rel) or default

        status, alerts, print_status, supplies = await asyncio.gather(
            self._optional_json(href("system", "status", "/cdm/system/v1/status")),
            self._optional_json(href("alert", "alerts", "/cdm/alert/v1/alerts")),
            self._optional_json(href("print", "status", "/cdm/print/v2/status")),
            self._optional_json(
                href("supply", "suppliesPublic", "/cdm/supply/v1/suppliesPublic")
            ),
        )
        data.status = cdm.parse_status(status, alerts, print_status)
        if supplies:
            data.consumables = cdm.parse_supplies(supplies)
        if include_static or data.device is None:
            (
                identity,
                counters,
                service_counters,
                power,
                system_config,
                print_config,
                print_mode,
                control_panel,
                fw_config,
                fw_status,
                fw_check,
                media,
            ) = await asyncio.gather(
                self._optional_json(
                    href("system", "identity", "/cdm/system/v1/identity")
                ),
                self._optional_json("/cdm/deviceUsage/v1/lifetimeCounters"),
                self._optional_json("/cdm/deviceUsage/v1/serviceCounters"),
                self._optional_json("/cdm/power/v1/configuration"),
                self._optional_json("/cdm/system/v1/configuration"),
                self._optional_json("/cdm/print/v2/configuration"),
                self._optional_json(RES_CDM_PRINT_MODE),
                self._optional_json(RES_CDM_CONTROL_PANEL),
                self._optional_json("/cdm/firmwareUpdate/v2/configuration"),
                self._optional_json("/cdm/firmwareUpdate/v2/updateStatus"),
                self._optional_json("/cdm/firmwareUpdate/v2/updateCheck"),
                self._optional_json("/cdm/media/v1/configuration"),
            )
            if identity:
                data.device = cdm.parse_identity(identity)
            if counters:
                data.usage = cdm.parse_usage(counters, service_counters)
            data.settings = cdm.parse_settings(
                power, system_config, print_config, print_mode, control_panel
            )
            if fw_config or fw_status or fw_check:
                data.firmware = cdm.parse_firmware(fw_config, fw_status, fw_check)
            if media:
                data.media = cdm.parse_media(media)
        if include_network or data.network is None:
            discovery, print_services, resolver, snmp = await asyncio.gather(
                self._optional_json("/cdm/network/v1/discoveryServices"),
                self._optional_json("/cdm/network/v1/printServices"),
                self._optional_json("/cdm/network/v1/nameResolverServices"),
                self._optional_json("/cdm/network/v1/snmpConfig"),
            )
            data.network = cdm.parse_network(discovery, print_services, resolver, snmp)

    async def _run_tasks(
        self, data: PrinterData, tasks: dict[str, Awaitable[Any]]
    ) -> None:
        names = list(tasks)
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for name, result in zip(names, results, strict=True):
            if isinstance(result, HPPrinterNotSupportedError):
                _LOGGER.debug("%s: %s not supported", self.host, name)
                continue
            if isinstance(result, HPPrinterAuthenticationError):
                data.errors[name] = str(result)
                continue
            if isinstance(result, BaseException):
                if name in ("status", "consumables") and not isinstance(
                    result, HPPrinterError
                ):
                    raise result
                if isinstance(result, HPPrinterError):
                    data.errors[name] = str(result)
                    _LOGGER.debug("%s: %s failed: %s", self.host, name, result)
                    if name == "status":
                        raise result
                    continue
                raise result
            setattr(data, name, result)

    # ------------------------------------------------------------------ #
    # Writes: product settings
    # ------------------------------------------------------------------ #
    async def set_product_settings(self, **values: str) -> None:
        """Write one or more ``ProductSettings`` children (LEDM, needs password)."""
        if not values:
            return
        body_parts = []
        for tag, value in values.items():
            prefix, wrapper = _PRODUCT_SETTING_TAGS.get(tag, ("dd", None))
            element = f"<{prefix}:{tag}>{escape(value)}</{prefix}:{tag}>"
            if wrapper:
                element = f"<{wrapper}>{element}</{wrapper}>"
            body_parts.append(element)
        body = xml_document(
            "prdcfgdyn2:ProductConfigDyn",
            _PRODUCT_CONFIG_NS,
            f"<prdcfgdyn2:ProductSettings>{''.join(body_parts)}</prdcfgdyn2:ProductSettings>",
        )
        await self.put_xml(RES_PRODUCT_CONFIG, body)

    async def set_quiet_mode(self, enabled: bool) -> None:
        """Enable/disable quiet printing. Uses CDM (no password) when available."""
        caps = await self._caps()
        if caps.has_cdm:
            try:
                await self.put_json(
                    RES_CDM_PRINT_MODE,
                    {
                        "version": "1.0.0",
                        "quietPrintModeEnabled": _on_off(enabled, "true", "false"),
                    },
                )
                return
            except HPPrinterNotSupportedError:
                try:
                    await self.patch_json(
                        "/cdm/print/v2/configuration",
                        {"quietModeEnabled": _on_off(enabled, "true", "false")},
                    )
                    return
                except HPPrinterNotSupportedError:
                    pass
        await self.set_product_settings(QuietPrintMode=_on_off(enabled))

    async def set_power_save_timeout(self, value: str) -> None:
        """Set the sleep timeout (e.g. ``5minutes``)."""
        await self.set_product_settings(PowerSaveTimeout=value)

    async def set_auto_off_time(self, value: str) -> None:
        """Set the auto-off delay (e.g. ``2hours``)."""
        await self.set_product_settings(AutoOffTime=value)

    async def set_device_language(self, language: str) -> None:
        """Set the control panel language (CDM first, then LEDM)."""
        caps = await self._caps()
        if caps.has_cdm:
            try:
                await self.put_json(
                    RES_CDM_CONTROL_PANEL,
                    {"version": "1.0.0", "deviceLanguage": language},
                )
                return
            except HPPrinterNotSupportedError:
                pass
        await self.set_product_settings(DeviceLanguage=language)

    async def set_country(self, country: str) -> None:
        """Set the country/region name (e.g. ``brazil``)."""
        await self.set_product_settings(CountryAndRegionName=country)

    async def set_time_format(self, value: str) -> None:
        """Set ``HR12`` / ``HR24``."""
        await self.set_product_settings(TimeFormat=value)

    async def set_date_format(self, value: str) -> None:
        """Set the date format (``MMMDDYYYY`` / ``DDMMMYYYY`` / ``YYYYMMMDD``)."""
        await self.set_product_settings(DateFormat=value)

    async def set_clock(self, timestamp: str) -> None:
        """Set the printer clock (``YYYY-MM-DDTHH:MM:SS``)."""
        await self.set_product_settings(TimeStamp=timestamp)

    async def set_ews_enabled(self, enabled: bool) -> None:
        """Enable/disable the embedded web server."""
        await self.set_product_settings(EnableDisable=_on_off(enabled))

    async def set_device_location(self, location: str) -> None:
        """Set the free-text device location."""
        await self.set_product_settings(DeviceLocation=location)

    async def set_device_description(self, description: str) -> None:
        """Set the free-text device description."""
        await self.set_product_settings(Description=description)

    # ------------------------------------------------------------------ #
    # Writes: print / copy defaults
    # ------------------------------------------------------------------ #
    async def set_print_config(
        self,
        *,
        copies: int | None = None,
        quality: str | None = None,
        resolution: str | None = None,
        borderless: bool | None = None,
        colorlok: bool | None = None,
        job_timeout_seconds: int | None = None,
        courier: str | None = None,
    ) -> None:
        """Write default print settings (``PrintConfigDyn``)."""
        parts = []
        if copies is not None:
            parts.append(
                f"<dd:DefaultPrintCopies>{int(copies)}</dd:DefaultPrintCopies>"
            )
        if quality is not None:
            parts.append(f"<dd:PrintQuality>{escape(quality)}</dd:PrintQuality>")
        if resolution is not None:
            parts.append(
                f"<dd:ResolutionSetting>{escape(resolution)}</dd:ResolutionSetting>"
            )
        if borderless is not None:
            parts.append(
                f"<dd:BorderlessPrinting>{_on_off(borderless, 'true', 'false')}"
                "</dd:BorderlessPrinting>"
            )
        if colorlok is not None:
            parts.append(f"<dd:ColorLok>{_on_off(colorlok)}</dd:ColorLok>")
        if job_timeout_seconds is not None:
            parts.append(
                f"<dd:JobTimeout><dd:LeaseTime>{int(job_timeout_seconds)}</dd:LeaseTime>"
                "<dd:TimeUnits>seconds</dd:TimeUnits></dd:JobTimeout>"
            )
        if courier is not None:
            parts.append(f"<dd:DefaultCourier>{escape(courier)}</dd:DefaultCourier>")
        if not parts:
            return
        await self.put_xml(
            RES_PRINT_CONFIG,
            xml_document("prncfgdyn2:PrintConfigDyn", _PRINT_CONFIG_NS, "".join(parts)),
        )

    async def set_copy_config(
        self,
        *,
        copies: int | None = None,
        quality: str | None = None,
        lighter_darker: int | None = None,
        media_size: str | None = None,
        media_type: str | None = None,
        reduce_enlarge: str | None = None,
        reduce_enlarge_custom: int | None = None,
        output_type: str | None = None,
        margin_off: bool | None = None,
    ) -> None:
        """Write default copy settings (``CopyConfigDyn``)."""
        mapping: list[tuple[str, object | None]] = [
            ("DefaultNumberOfCopies", copies),
            ("DefaultCopyQuality", quality),
            ("DefaultLighterDarker", lighter_darker),
            ("DefaultMediaSizeName", media_size),
            ("DefaultMediaType", media_type),
            ("DefaultReduceEnlarge", reduce_enlarge),
            ("DefaultReduceEnlargeCustom", reduce_enlarge_custom),
            ("DefaultOutputType", output_type),
            ("DefaultMarginOff", None if margin_off is None else _on_off(margin_off)),
        ]
        parts = [
            f"<copy:{tag}>{escape(value)}</copy:{tag}>"
            for tag, value in mapping
            if value is not None
        ]
        if not parts:
            return
        await self.put_xml(
            RES_COPY_CONFIG,
            xml_document("cpcfgdyn:CopyConfigDyn", _COPY_CONFIG_NS, "".join(parts)),
        )

    # ------------------------------------------------------------------ #
    # Writes: network
    # ------------------------------------------------------------------ #
    async def set_network_services(
        self,
        *,
        ipp: bool | None = None,
        port9100: bool | None = None,
        snmp: bool | None = None,
        mdns: bool | None = None,
        mdns_name: str | None = None,
        ws_discovery: bool | None = None,
        ws_print: bool | None = None,
        ws_scan: bool | None = None,
        llmnr: bool | None = None,
        dhcpv6: bool | None = None,
        https_redirect: bool | None = None,
        webscan: bool | None = None,
        direct_print: bool | None = None,
    ) -> None:
        """Write ``NetAppsDyn`` (protocol switches, Bonjour name)."""
        parts = []
        if mdns is not None or mdns_name is not None:
            inner = ""
            if mdns is not None:
                inner += f"<dd:MDNSSupport>{_on_off(mdns)}</dd:MDNSSupport>"
            if mdns_name is not None:
                inner += (
                    f"<dd:ApplicationServiceName>{escape(mdns_name)}"
                    "</dd:ApplicationServiceName>"
                )
            parts.append(f"<nadyn:DNSSDConfig>{inner}</nadyn:DNSSDConfig>")
        if snmp is not None:
            parts.append(
                "<dd:SNMPConfigWithVersion>"
                f"<dd:SNMP>{_on_off(snmp)}</dd:SNMP></dd:SNMPConfigWithVersion>"
            )
        ws = ""
        if ws_discovery is not None:
            ws += f"<nadyn:WSDiscovery>{_on_off(ws_discovery)}</nadyn:WSDiscovery>"
        if ws_print is not None:
            ws += f"<nadyn:WSPrint>{_on_off(ws_print)}</nadyn:WSPrint>"
        if ws_scan is not None:
            ws += f"<nadyn:WSScan>{_on_off(ws_scan)}</nadyn:WSScan>"
        if ws:
            parts.append(f"<nadyn:WebServicesConfig>{ws}</nadyn:WebServicesConfig>")
        for tag, value in (
            ("DHCPv6", dhcpv6),
            ("LLMNR", llmnr),
            ("HTTPSRedirection", https_redirect),
            ("Port9100PrintingSupport", port9100),
            ("IPPSupport", ipp),
            ("WebScan", webscan),
            ("DirectPrint", direct_print),
        ):
            if value is not None:
                parts.append(f"<nadyn:{tag}>{_on_off(value)}</nadyn:{tag}>")
        if not parts:
            return
        await self.put_xml(
            RES_NET_APPS, xml_document("nadyn:NetAppsDyn", _NET_APPS_NS, "".join(parts))
        )

    async def set_secure_network_services(
        self,
        *,
        wifi_direct_show_passphrase: bool | None = None,
        wifi_direct_hide_ssid: bool | None = None,
        wifi_direct_connection_method: str | None = None,
        airprint: bool | None = None,
        ipps: bool | None = None,
        wpad: bool | None = None,
        bluetooth: bool | None = None,
        remote_scans: bool | None = None,
    ) -> None:
        """Write ``NetAppsSecureDyn`` (Wi-Fi Direct, AirPrint, IPPS, BLE...)."""
        parts = []
        wd = ""
        if wifi_direct_show_passphrase is not None:
            show = _on_off(wifi_direct_show_passphrase, "true", "false")
            wd += f"<nasdyn:ShowPassPhrase>{show}</nasdyn:ShowPassPhrase>"
        if wifi_direct_hide_ssid is not None:
            wd += (
                f"<nasdyn:HideSSID>{_on_off(wifi_direct_hide_ssid, 'true', 'false')}"
                "</nasdyn:HideSSID>"
            )
        if wifi_direct_connection_method is not None:
            wd += (
                f"<nasdyn:ConnectionMethod>{escape(wifi_direct_connection_method)}"
                "</nasdyn:ConnectionMethod>"
            )
        if wd:
            parts.append(
                f"<nasdyn:WirelessDirectConfig>{wd}</nasdyn:WirelessDirectConfig>"
            )
        for tag, value in (
            ("AirPrintConfig", airprint),
            ("IPPSConfig", ipps),
            ("WPADConfig", wpad),
            ("BluetoothSmartConfig", bluetooth),
        ):
            if value is not None:
                parts.append(
                    f"<nasdyn:{tag}><nasdyn:State>{_on_off(value)}</nasdyn:State></nasdyn:{tag}>"
                )
        if remote_scans is not None:
            parts.append(
                f"<nasdyn:RemotelyInitiatedScans>{_on_off(remote_scans)}"
                "</nasdyn:RemotelyInitiatedScans>"
            )
        if not parts:
            return
        await self.put_xml(
            RES_NET_APPS_SECURE,
            xml_document(
                "nasdyn:NetAppsSecureDyn", _NET_APPS_SECURE_NS, "".join(parts)
            ),
        )

    # ------------------------------------------------------------------ #
    # Writes: firmware / maintenance / actions
    # ------------------------------------------------------------------ #
    async def set_firmware_auto(
        self, *, check: bool | None = None, update: bool | None = None
    ) -> None:
        """Toggle automatic firmware check / install."""
        parts = []
        if check is not None:
            parts.append(
                f"<fwudyn:AutomaticCheck>{_on_off(check)}</fwudyn:AutomaticCheck>"
            )
        if update is not None:
            parts.append(
                f"<fwudyn:AutomaticUpdate>{_on_off(update)}</fwudyn:AutomaticUpdate>"
            )
        if not parts:
            return
        caps = await self._caps()
        if caps.has_ledm:
            await self.put_xml(
                RES_FIRMWARE_CONFIG,
                xml_document(
                    "fwudyn:FirmwareUpdateConfig", _FIRMWARE_NS, "".join(parts)
                ),
            )
            return
        payload: dict[str, Any] = {"version": "2.0.0"}
        if update is not None or check is not None:
            payload["autoUpdateEnabled"] = _on_off(
                bool(update if update is not None else check), "true", "false"
            )
        await self.patch_json("/cdm/firmwareUpdate/v2/configuration", payload)

    async def firmware_action(self, action: str = "check") -> None:
        """Trigger ``check`` / ``start`` / ``cancel`` / ``reset`` of a web update."""
        if action not in FIRMWARE_ACTIONS:
            raise ValueError(f"action must be one of {FIRMWARE_ACTIONS}")
        caps = await self._caps()
        if caps.has_ledm:
            await self.put_xml(
                RES_FIRMWARE_ACTION,
                xml_document(
                    "fwudyn:FirmwareUpdateAction",
                    _FIRMWARE_NS,
                    f"<fwudyn:UpdateAction>{action}</fwudyn:UpdateAction>",
                ),
            )
            return
        state = {"check": "checking", "start": "downloading", "cancel": "idle"}.get(
            action, "idle"
        )
        await self.patch_json("/cdm/firmwareUpdate/v2/updateCheck", {"state": state})

    async def print_internal_page(self, job_type: str) -> None:
        """Print a built-in report or run a cleaning/alignment page.

        ``job_type`` is one of :data:`hp_printer.const.INTERNAL_PRINT_JOBS`
        (``configurationPage``, ``networkSummary``, ``cleaningPage``,
        ``pqDiagnosticsPage``...). Consumes paper and ink.
        """
        caps = await self._caps()
        if caps.has_ledm:
            body = xml_document(
                "ipdyn:InternalPrintDyn",
                _INTERNAL_PRINT_NS,
                f"<ipdyn:JobType>{escape(job_type)}</ipdyn:JobType>",
            )
            await self.post_xml(RES_INTERNAL_PRINT, body)
            return
        report_id = {
            "configurationPage": "configurationReport",
            "networkSummary": "networkSummaryPage",
            "pqDiagnosticsPage": "printQualityTestReport",
            "eventLogReport": "eventLog",
            "webServicesInfoPage": "webServicesInformationPage",
            "webAccessReport": "webAccessSummaryReport",
        }.get(job_type, job_type)
        await self.patch_json(
            "/cdm/report/v1/print",
            {"version": "1.0.0", "state": "processing", "reportId": report_id},
        )

    async def clean_cartridges(self, level: int = 1) -> None:
        """Run the cartridge cleaning routine (level 1-3, prints a page)."""
        job = {1: "cleaningPage", 2: "cleaningPageLevel2", 3: "cleaningPageLevel3"}.get(
            level, "cleaningPage"
        )
        await self.print_internal_page(job)

    async def align_cartridges(self) -> None:
        """Start the cartridge alignment (prints the alignment page)."""
        caps = await self._caps()
        if caps.has_ledm:
            body = xml_document("cal:CalibrationState", _CAL_NS, "Printing")
            await self.post_xml(RES_CALIBRATION_SESSION, body)
            return
        await self.patch_json(
            "/cdm/calibration/v1/calibration/penAlignSemiauto",
            {"calibrationType": "penAlignSemiauto", "operationType": "calibration"},
        )

    async def check_internet_connection(self) -> None:
        """Ask the printer to test its internet connectivity."""
        await self.post_xml(
            RES_ICC_JOB,
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<ut:InternetConnectionCheck xmlns:ut="http://www.hp.com/schemas/imaging/con/ledm/utilities/2011/12/06">'
            "<ut:Action>start</ut:Action></ut:InternetConnectionCheck>",
        )

    async def restart(self) -> None:
        """Power-cycle the printer (LEDM ``ProductActions`` or CDM ``power/reboot``)."""
        caps = await self._caps()
        if caps.has_ledm and caps.has_product_actions:
            try:
                await self._request(
                    "PUT",
                    RES_POWER_CYCLE,
                    data=b"",
                    content_type="text/xml",
                )
                return
            except HPPrinterNotSupportedError:
                pass
        await self.patch_json("/cdm/power/v1/reboot", {"state": "rebooting"})

    # ------------------------------------------------------------------ #
    # Convenience
    # ------------------------------------------------------------------ #
    async def get_state(self) -> PrinterState:
        """Cheap state check: LEDM status + eSCL scanner state."""
        caps = await self._caps()
        if caps.has_ledm:
            status = await self.get_status()
            if caps.has_escl:
                try:
                    scanner = await self.get_scanner_status()
                    if scanner.is_scanning:
                        return PrinterState.SCANNING
                except HPPrinterError:
                    pass
            return status.state
        status_json = await self._optional_json("/cdm/system/v1/status")
        return cdm.cdm_state(status_json)

    @staticmethod
    def supported_internal_pages() -> tuple[str, ...]:
        """Internal page job types known to the library."""
        return INTERNAL_PRINT_JOBS


async def _maybe_await(result: Awaitable[None] | None) -> None:
    if result is not None:
        await result
