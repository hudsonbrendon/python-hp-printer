# python-hp-printer

[![PyPI](https://img.shields.io/pypi/v/python-hp-printer.svg)](https://pypi.org/project/python-hp-printer/)
[![Python](https://img.shields.io/pypi/pyversions/python-hp-printer.svg)](https://pypi.org/project/python-hp-printer/)
[![Tests](https://github.com/hudsonbrendon/python-hp-printer/actions/workflows/tests.yml/badge.svg)](https://github.com/hudsonbrendon/python-hp-printer/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Async Python client for HP printers on the local network. It speaks every
protocol an HP inkjet or laser exposes without the cloud:

| Protocol | What it gives you | Models |
| --- | --- | --- |
| **LEDM** (`/DevMgmt/*.xml`, XML) | status + alerts, cartridges, usage counters, settings (sleep, quiet mode, language, clock), print/copy defaults, trays, network, firmware update, ePrint, event/error logs, internal pages, alignment, restart | DeskJet / ENVY / OfficeJet / Smart Tank / LaserJet 2010–2023 |
| **CDM** (`/cdm/*`, JSON) | identity, status, alerts, supplies, counters, power, firmware, media, network, reports, calibration, reboot | HP+ / 2023+ firmware (Smart Tank 5xx, DeskJet 28xx/42xx, LaserJet 3xxx/4xxx) — read paths verified against public captures, LEDM-era printers also expose a few CDM resources |
| **eSCL** (AirScan / Mopria Scan) | scanner status, capabilities, **scanning to JPEG/PDF** from platen or ADF | every HP AiO since ~2012 |
| **IPP** (port 631) | printer state, Wi-Fi state, job list, cancel job, **Identify-Printer** (flash), **Print-Job** (print a JPEG/PDF/PCLm/URF) | everything |

Everything is optional: the client probes `/DevMgmt/DiscoveryTree.xml` and
`/cdm/servicesDiscovery` once and only asks for what the printer advertises,
so an old LaserJet without a scanner and a new CDM-only Smart Tank are both
handled by the same `HPPrinter` class.

Built for the [Home Assistant integration](https://github.com/hudsonbrendon/ha-hp-printer),
but useful on its own. Reverse-engineered on an **HP DeskJet Ink Advantage
2774** (DeskJet 2700 series) and cross-checked against public dumps of
OfficeJet Pro 8035e/9022e, LaserJet M182nw, Smart Tank 580/750 and
Color LaserJet Pro MFP 3302.

## Installation

```bash
pip install python-hp-printer
```

Requires Python 3.14+ (the version Home Assistant runs). Dependencies:
`aiohttp`, `aioipp`, `yarl`.

## Usage

```python
import asyncio
from hp_printer import HPPrinter, ScanSettings


async def main() -> None:
    async with HPPrinter("192.168.1.50") as printer:
        caps = await printer.discover()
        print(caps.has_ledm, caps.has_cdm, caps.has_escl)

        data = await printer.update()  # everything in one PrinterData
        print(data.device.name, data.state)  # "DeskJet 2700 series" PrinterState.IDLE
        for ink in data.consumables.consumables:
            print(ink.color, ink.level, "%", ink.state)
        print(data.usage.total_impressions, "pages")
        print(data.network.wifi.ssid, data.network.wifi.rssi_dbm, "dBm")

        await printer.identify()  # flash the display
        pages = await printer.scan(ScanSettings.for_page("a4", resolution=300))
        open("scan.jpg", "wb").write(pages[0])

        # writes (CDM ones need no password, LEDM ones need the EWS admin password)
        await printer.set_quiet_mode(True)


asyncio.run(main())
```

Pass `session=` to reuse an existing `aiohttp.ClientSession` and
`password=` (user `admin`) to unlock LEDM writes. Writes are automatically
redirected to HTTPS; the printer's self-signed certificate is accepted unless
you pass `verify_ssl=True`.

### Command line

```bash
hp-printer 192.168.1.50 all            # dump everything as JSON
hp-printer 192.168.1.50 supplies
hp-printer 192.168.1.50 scan page.pdf --resolution 300 --source Feeder
hp-printer 192.168.1.50 identify
hp-printer 192.168.1.50 quiet on
hp-printer 192.168.1.50 --password 12345678 power-save 15minutes
hp-printer 192.168.1.50 page networkSummary
```

## What you get

- `DeviceInfo` – model, serial, product number, UUID, firmware version/date,
  manufacture date, memory, control panel type
- `Status` – LEDM status categories + alert table, normalised to
  `PrinterState` (`idle`, `printing`, `scanning`, `copying`, `sleeping`,
  `attention`, `error`, …) with `problems`, `has_error`, `is_busy`
- `ConsumablesInfo` / `Consumable` – level, raw level, state, genuine/refilled/
  setup/trial flags, cartridge number (667, 667XL…), unique id, drops/ink used,
  refills, insertions, CSS colour for dashboards
- `Usage` – total/mono/colour impressions, jams, mispicks, cancel presses,
  ink used, impressions by media type/size/quality, job duration buckets,
  scan/copy/fax counters, mobile/driver counters
- `Settings` + `SettingsCapabilities` – sleep timeout, auto-off, language,
  country, clock, quiet mode, EWS, and the allowed values for each
- `PrintConfig`, `CopyConfig` – defaults with their allowed options
- `MediaHandling` – trays, loaded paper size/type
- `Network` – Wi-Fi SSID/BSSID/RSSI, IP/DNS/gateway, MAC, hostname, Bonjour
  name, protocol switches (IPP, 9100, SNMP, WS-*, LLMNR, WebScan…), Wi-Fi
  Direct, AirPrint/IPPS/BLE states
- `Firmware` – auto check/update flags, update state, target version, progress
- `EPrint`, `ProductLogs`, `DeviceEvent`, `ScannerStatus`,
  `ScannerCapabilities`, `IppStatus`, `IppJob`

Writes: quiet mode, sleep timeout, auto-off, language, country, time/date
format, clock, EWS, location/description, print defaults, copy defaults,
network services, Wi-Fi Direct, firmware auto check/update, firmware check,
internal pages (configuration, network summary, print quality, cleaning
levels…), cartridge alignment, internet check, restart, cancel job, identify,
print.

See [docs/protocol.md](docs/protocol.md) for the full resource map, XML
namespaces and payloads.

## Development

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

Fixtures under `tests/fixtures/` are real dumps (DeskJet 2774, plus CDM dumps
from a Smart Tank 580 and LEDM dumps from a LaserJet M182nw courtesy of
[kou147258/ha-hp-printers](https://github.com/kou147258/ha-hp-printers)).

## License

MIT
