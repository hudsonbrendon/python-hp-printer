"""Exceptions raised by python-hp-printer."""

from __future__ import annotations


class HPPrinterError(Exception):
    """Base exception for every error raised by this library."""


class HPPrinterConnectionError(HPPrinterError):
    """The printer could not be reached."""


class HPPrinterConnectionTimeoutError(HPPrinterConnectionError):
    """The printer did not answer in time."""


class HPPrinterAuthenticationError(HPPrinterError):
    """The printer rejected the admin credentials (HTTP 401)."""


class HPPrinterNotSupportedError(HPPrinterError):
    """The printer does not expose the requested resource (HTTP 404/405/410)."""


class HPPrinterStatusError(HPPrinterError):
    """The printer answered with an unexpected HTTP status."""

    def __init__(self, message: str, *, status: int, body: bytes = b"") -> None:
        """Initialize the error with the HTTP status and body."""
        super().__init__(message)
        self.status = status
        self.body = body


class HPPrinterResponseError(HPPrinterError):
    """The printer answered with a body that could not be parsed."""


class HPPrinterScanError(HPPrinterError):
    """A scan job failed or was aborted by the scanner."""
