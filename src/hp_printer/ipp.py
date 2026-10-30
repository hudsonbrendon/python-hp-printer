"""Thin IPP layer on top of ``pyipp`` for jobs, identify and printing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pyipp import IPP
from pyipp.enums import IppOperation, IppTag
from pyipp.exceptions import IPPConnectionError, IPPConnectionUpgradeRequired, IPPError
from pyipp.tags import ATTRIBUTE_TAG_MAP

from .const import DEFAULT_IPP_PORT, DEFAULT_TIMEOUT, IPP_BASE_PATH, USER_AGENT
from .exceptions import HPPrinterConnectionError, HPPrinterStatusError
from .models import IppJob, IppStatus

if TYPE_CHECKING:
    from aiohttp import ClientSession

IDENTIFY_PRINTER = 0x3C

# pyipp/aioipp silently drops attributes it does not know how to encode.
ATTRIBUTE_TAG_MAP.setdefault("identify-actions", IppTag.KEYWORD)
ATTRIBUTE_TAG_MAP.setdefault("limit", IppTag.INTEGER)
ATTRIBUTE_TAG_MAP.setdefault("print-color-mode", IppTag.KEYWORD)
ATTRIBUTE_TAG_MAP.setdefault("compression", IppTag.KEYWORD)
CANCEL_MY_JOBS = 0x39
CLOSE_JOB = 0x3B

MONITOR_ATTRIBUTES = [
    "printer-state",
    "printer-state-reasons",
    "printer-state-message",
    "printer-is-accepting-jobs",
    "queued-job-count",
    "printer-up-time",
    "printer-uuid",
    "printer-wifi-ssid",
    "printer-wifi-state",
    "printer-firmware-string-version",
    "printer-firmware-version",
    "printer-make-and-model",
    "media-ready",
    "media-default",
    "document-format-supported",
    "identify-actions-supported",
    "operations-supported",
    "printer-alert-description",
    "printer-supply",
    "printer-icons",
    "printer-strings-uri",
]

JOB_ATTRIBUTES = [
    "job-id",
    "job-name",
    "job-state",
    "job-state-reasons",
    "job-impressions",
    "job-impressions-completed",
    "job-media-sheets-completed",
    "job-originating-user-name",
    "date-time-at-creation",
    "date-time-at-completed",
]


class IppClient:
    """Minimal async IPP client built on ``pyipp``."""

    def __init__(
        self,
        host: str,
        *,
        port: int = DEFAULT_IPP_PORT,
        base_path: str = IPP_BASE_PATH,
        session: ClientSession | None = None,
        tls: bool = False,
        request_timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Create the client; ``session`` is shared with the HTTP client."""
        self.host = host
        self.port = port
        self.base_path = base_path
        self.printer_uri = f"{'ipps' if tls else 'ipp'}://{host}:{port}{base_path}"
        self._ipp = IPP(
            host,
            base_path=base_path,
            port=port,
            session=session,
            tls=tls,
            request_timeout=int(request_timeout),
            user_agent=USER_AGENT,
        )

    async def _execute(
        self, operation: IppOperation | int, message: dict[str, Any]
    ) -> dict[str, Any]:
        op = (
            operation
            if isinstance(operation, IppOperation)
            else IppOperation(operation)
        )
        op_attrs = message.setdefault("operation-attributes-tag", {})
        op_attrs.setdefault("printer-uri", self.printer_uri)
        op_attrs.setdefault("requesting-user-name", "python-hp-printer")
        try:
            return await self._ipp.execute(op, message)
        except IPPConnectionUpgradeRequired as err:
            raise HPPrinterConnectionError(
                f"IPP endpoint {self.printer_uri} requires TLS"
            ) from err
        except IPPConnectionError as err:
            raise HPPrinterConnectionError(
                f"IPP connection to {self.host}:{self.port} failed: {err}"
            ) from err
        except IPPError as err:
            status = err.args[1].get("status-code") if len(err.args) > 1 else None
            raise HPPrinterStatusError(
                f"IPP operation {op.name} failed: {err}", status=int(status or 0)
            ) from err

    async def status(self) -> IppStatus:
        """Return the monitoring subset of ``Get-Printer-Attributes``."""
        response = await self._execute(
            IppOperation.GET_PRINTER_ATTRIBUTES,
            {"operation-attributes-tag": {"requested-attributes": MONITOR_ATTRIBUTES}},
        )
        printers = response.get("printers") or [{}]
        return IppStatus.from_attributes(printers[0])

    async def attributes(self, requested: list[str] | None = None) -> dict[str, Any]:
        """Return raw printer attributes (``all`` by default)."""
        response = await self._execute(
            IppOperation.GET_PRINTER_ATTRIBUTES,
            {
                "operation-attributes-tag": {
                    "requested-attributes": requested or ["all"]
                }
            },
        )
        printers = response.get("printers") or [{}]
        return dict(printers[0])

    async def jobs(self, which: str = "all", limit: int = 20) -> list[IppJob]:
        """Return jobs (``which`` = ``all`` | ``completed`` | ``not-completed``)."""
        response = await self._execute(
            IppOperation.GET_JOBS,
            {
                "operation-attributes-tag": {
                    "which-jobs": which,
                    "limit": limit,
                    "requested-attributes": JOB_ATTRIBUTES,
                }
            },
        )
        jobs = [IppJob.from_attributes(j) for j in response.get("jobs") or []]
        jobs.sort(key=lambda j: j.id, reverse=True)
        return jobs

    async def cancel_job(self, job_id: int) -> None:
        """Cancel a job by id."""
        await self._execute(
            IppOperation.CANCEL_JOB, {"operation-attributes-tag": {"job-id": job_id}}
        )

    async def cancel_all_jobs(self) -> None:
        """Cancel every job of the requesting user (Cancel-My-Jobs)."""
        await self._execute(CANCEL_MY_JOBS, {"operation-attributes-tag": {}})

    async def identify(self, action: str = "flash") -> None:
        """Make the printer flash its display / beep (Identify-Printer)."""
        await self._execute(
            IDENTIFY_PRINTER,
            {"operation-attributes-tag": {"identify-actions": action}},
        )

    def _job_message(
        self,
        *,
        document_format: str,
        job_name: str,
        copies: int,
        media: str | None,
        print_quality: int | None,
        sides: str | None,
    ) -> dict[str, Any]:
        job_attrs: dict[str, Any] = {}
        if copies > 1:
            job_attrs["copies"] = copies
        if media:
            job_attrs["media"] = media
        if print_quality:
            job_attrs["print-quality"] = print_quality
        if sides:
            job_attrs["sides"] = sides
        message: dict[str, Any] = {
            "operation-attributes-tag": {
                "job-name": job_name,
                "document-format": document_format,
            }
        }
        if job_attrs:
            message["job-attributes-tag"] = job_attrs
        return message

    async def validate_job(
        self,
        *,
        document_format: str = "application/octet-stream",
        job_name: str = "python-hp-printer",
        copies: int = 1,
        media: str | None = None,
        print_quality: int | None = None,
        sides: str | None = None,
    ) -> bool:
        """Ask the printer whether it would accept the job (nothing is printed)."""
        message = self._job_message(
            document_format=document_format,
            job_name=job_name,
            copies=copies,
            media=media,
            print_quality=print_quality,
            sides=sides,
        )
        response = await self._execute(IppOperation.VALIDATE_JOB, message)
        return int(response.get("status-code", 1)) < 0x100

    async def print_job(
        self,
        data: bytes,
        *,
        document_format: str = "application/octet-stream",
        job_name: str = "python-hp-printer",
        copies: int = 1,
        media: str | None = None,
        print_quality: int | None = None,
        sides: str | None = None,
    ) -> IppJob | None:
        """Send a document with ``Print-Job`` and return the created job."""
        message = self._job_message(
            document_format=document_format,
            job_name=job_name,
            copies=copies,
            media=media,
            print_quality=print_quality,
            sides=sides,
        )
        message["data"] = data
        response = await self._execute(IppOperation.PRINT_JOB, message)
        jobs = response.get("jobs") or []
        if jobs:
            return IppJob.from_attributes(jobs[0])
        return None

    async def close(self) -> None:
        """Close the underlying pyipp client (only if it owns the session)."""
        await self._ipp.close()
