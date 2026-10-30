"""Command line interface: ``python -m hp_printer <host> <command>``."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Any

from .client import HPPrinter
from .escl import ScanSettings
from .exceptions import HPPrinterError
from .models import _Model


def _dump(value: Any) -> None:
    if isinstance(value, _Model):
        print(json.dumps(value.as_dict(), indent=2, ensure_ascii=False))
    elif isinstance(value, list):
        print(
            json.dumps(
                [v.as_dict() if isinstance(v, _Model) else v for v in value],
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hp-printer", description=__doc__)
    parser.add_argument("host", help="printer IP or hostname")
    parser.add_argument("--password", help="EWS admin password (needed for writes)")
    parser.add_argument(
        "--https", action="store_true", help="force HTTPS for every request"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in (
        "capabilities",
        "info",
        "status",
        "state",
        "supplies",
        "usage",
        "settings",
        "settings-caps",
        "print-config",
        "copy-config",
        "media",
        "network",
        "firmware",
        "eprint",
        "logs",
        "events",
        "scanner",
        "scanner-caps",
        "ipp",
        "jobs",
        "all",
        "identify",
        "firmware-check",
        "align",
        "restart",
    ):
        sub.add_parser(name)
    scan = sub.add_parser("scan", help="scan a page to a file")
    scan.add_argument("output", help="output file (.jpg or .pdf)")
    scan.add_argument("--resolution", type=int, default=300)
    scan.add_argument(
        "--color", default="RGB24", choices=["RGB24", "Grayscale8", "BlackAndWhite1"]
    )
    scan.add_argument("--source", default="Platen", choices=["Platen", "Feeder"])
    scan.add_argument("--size", default="max")
    quiet = sub.add_parser("quiet", help="quiet mode on/off")
    quiet.add_argument("value", choices=["on", "off"])
    ps = sub.add_parser("power-save", help="set sleep timeout (e.g. 5minutes)")
    ps.add_argument("value")
    cancel = sub.add_parser("cancel", help="cancel a print job")
    cancel.add_argument("job_id", type=int)
    page = sub.add_parser(
        "page", help="print an internal page (configurationPage, networkSummary...)"
    )
    page.add_argument("job_type")
    prt = sub.add_parser("print", help="print a file over IPP")
    prt.add_argument("file")
    prt.add_argument("--format", default="application/octet-stream")
    prt.add_argument("--copies", type=int, default=1)
    return parser


async def _run(args: argparse.Namespace) -> int:
    async with HPPrinter(
        args.host, password=args.password, use_https=args.https
    ) as printer:
        cmd = args.command
        if cmd == "capabilities":
            _dump(await printer.discover())
        elif cmd == "info":
            _dump(await printer.get_device_info())
        elif cmd == "status":
            _dump(await printer.get_status())
        elif cmd == "state":
            print((await printer.get_state()).value)
        elif cmd == "supplies":
            _dump(await printer.get_consumables())
        elif cmd == "usage":
            _dump(await printer.get_usage())
        elif cmd == "settings":
            _dump(await printer.get_settings())
        elif cmd == "settings-caps":
            _dump(await printer.get_settings_capabilities())
        elif cmd == "print-config":
            _dump(await printer.get_print_config())
        elif cmd == "copy-config":
            _dump(await printer.get_copy_config())
        elif cmd == "media":
            _dump(await printer.get_media())
        elif cmd == "network":
            _dump(await printer.get_network())
        elif cmd == "firmware":
            _dump(await printer.get_firmware())
        elif cmd == "eprint":
            _dump(await printer.get_eprint())
        elif cmd == "logs":
            _dump(await printer.get_logs())
        elif cmd == "events":
            _dump(await printer.get_events())
        elif cmd == "scanner":
            _dump(await printer.get_scanner_status())
        elif cmd == "scanner-caps":
            _dump(await printer.get_scanner_capabilities())
        elif cmd == "ipp":
            _dump(await printer.get_ipp_status())
        elif cmd == "jobs":
            _dump(await printer.get_jobs())
        elif cmd == "all":
            data = await printer.update()
            _dump(data)
            print(f"state: {data.state.value}", file=sys.stderr)
        elif cmd == "identify":
            await printer.identify()
        elif cmd == "firmware-check":
            await printer.firmware_action("check")
        elif cmd == "align":
            await printer.align_cartridges()
        elif cmd == "restart":
            await printer.restart()
        elif cmd == "scan":
            fmt = (
                "application/pdf"
                if args.output.lower().endswith(".pdf")
                else "image/jpeg"
            )
            settings = ScanSettings.for_page(
                args.size,
                resolution=args.resolution,
                color_mode=args.color,
                source=args.source,
                document_format=fmt,
            )
            pages = await printer.scan(
                settings, progress=lambda s: print(s, file=sys.stderr)
            )
            out = Path(args.output)
            if len(pages) == 1:
                out.write_bytes(pages[0])
                print(f"saved {out} ({len(pages[0])} bytes)")
            else:
                for index, page_data in enumerate(pages, 1):
                    target = out.with_stem(f"{out.stem}-{index}")
                    target.write_bytes(page_data)
                    print(f"saved {target}")
        elif cmd == "quiet":
            await printer.set_quiet_mode(args.value == "on")
        elif cmd == "power-save":
            await printer.set_power_save_timeout(args.value)
        elif cmd == "cancel":
            await printer.cancel_job(args.job_id)
        elif cmd == "page":
            await printer.print_internal_page(args.job_type)
        elif cmd == "print":
            job = await printer.print_data(
                Path(args.file).read_bytes(),
                document_format=args.format,
                copies=args.copies,
                job_name=Path(args.file).name,
            )
            _dump(job)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    args = _build_parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except HPPrinterError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
