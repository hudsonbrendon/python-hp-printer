# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-30

### Added

- `HPPrinter` async client with capability discovery (LEDM discovery tree +
  CDM services discovery) and automatic HTTP→HTTPS redirect handling for
  authenticated writes.
- LEDM parsers: device info, settings (+ capabilities), status/alerts,
  consumables (+ usage merge), usage counters, print/copy configuration,
  media handling, network (adapters, protocols, Wi-Fi Direct), firmware,
  ePrint, product logs, event table.
- CDM parsers for CDM-only printers: identity, status/alerts, supplies,
  lifetime counters, power/print/control-panel settings, firmware, media,
  network services.
- eSCL scanning: scanner status, capabilities, scan to JPEG/PDF from platen or
  ADF with job polling, 503 retries and cleanup.
- IPP: printer state/Wi-Fi state, job list, cancel job, Identify-Printer,
  Validate-Job and Print-Job (via `aioipp`).
- Writes: quiet mode (CDM or LEDM), sleep timeout, auto-off, language, country,
  clock/time/date format, EWS, location/description, print and copy defaults,
  network services, Wi-Fi Direct / secure services, firmware auto
  check/update and actions, internal pages, cartridge cleaning and alignment,
  internet connection check, restart.
- `hp-printer` command line interface.
