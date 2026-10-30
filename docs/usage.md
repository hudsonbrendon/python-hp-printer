# Usage

## Connecting

```python
import aiohttp
from hp_printer import HPPrinter

async with aiohttp.ClientSession() as session:
    printer = HPPrinter("192.168.1.50", session=session, password="12345678")
    caps = await printer.discover()
```

`discover()` reads `/DevMgmt/DiscoveryTree.xml` and `/cdm/servicesDiscovery`
and fills `printer.capabilities`. Every later call only touches the resources
the printer advertised; unsupported ones raise `HPPrinterNotSupportedError`
or are simply left `None` in `PrinterData`.

## Polling

```python
data = await printer.update()  # everything
fast = await printer.update(
    include_static=False,  # status, supplies, scanner, jobs
    include_network=False,
    previous=data,
)  # carries device/usage/network over
```

`PrinterData.state` combines LEDM status categories, the eSCL scanner state and
IPP job state into one `PrinterState`.

## Scanning

```python
from hp_printer import ScanSettings

pages = await printer.scan(
    ScanSettings.for_page(
        "a4", resolution=300, color_mode="RGB24", document_format="application/pdf"
    )
)
```

For an ADF use `source="Feeder"` (and `duplex=True` when supported); every
page is returned as a separate item.

## Writing settings

| Method | Protocol | Needs password |
| --- | --- | --- |
| `set_quiet_mode` | CDM (falls back to LEDM) | no on LEDM-era HP+; yes on pure LEDM |
| `set_device_language` | CDM / LEDM | no / yes |
| `set_power_save_timeout`, `set_auto_off_time`, `set_country`, `set_time_format`, `set_date_format`, `set_clock`, `set_ews_enabled`, `set_device_location`, `set_device_description` | LEDM | yes |
| `set_print_config`, `set_copy_config` | LEDM | yes |
| `set_network_services`, `set_secure_network_services` | LEDM | yes |
| `set_firmware_auto`, `firmware_action` | LEDM / CDM | yes / no |
| `print_internal_page`, `clean_cartridges`, `align_cartridges` | LEDM POST / CDM PATCH | no (observed) |
| `identify`, `cancel_job`, `print_data` | IPP | no |
| `restart` | LEDM ProductActions / CDM reboot | yes / no |

The password is the EWS admin password (default: the PIN printed on the
label inside the cartridge door on most models). A wrong password raises
`HPPrinterAuthenticationError`.
