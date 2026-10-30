"""Constants, resource paths and enumerations for python-hp-printer."""

from __future__ import annotations

from enum import StrEnum
from importlib import metadata

try:
    VERSION = metadata.version("python-hp-printer")
except metadata.PackageNotFoundError:  # pragma: no cover - editable/source runs
    VERSION = "0.0.0"

USER_AGENT = f"Mozilla/5.0 (compatible; python-hp-printer/{VERSION})"

DEFAULT_PORT = 80
DEFAULT_HTTPS_PORT = 443
DEFAULT_IPP_PORT = 631
DEFAULT_USERNAME = "admin"
DEFAULT_TIMEOUT = 10.0
MAX_CONCURRENT_REQUESTS = 4

# --- LEDM (Low End Data Model) resources -----------------------------------
RES_DISCOVERY_TREE = "/DevMgmt/DiscoveryTree.xml"
RES_PRODUCT_CONFIG = "/DevMgmt/ProductConfigDyn.xml"
RES_PRODUCT_CONFIG_CAP = "/DevMgmt/ProductConfigCap.xml"
RES_PRODUCT_STATUS = "/DevMgmt/ProductStatusDyn.xml"
RES_CONSUMABLES = "/DevMgmt/ConsumableConfigDyn.xml"
RES_USAGE = "/DevMgmt/ProductUsageDyn.xml"
RES_PRINT_CONFIG = "/DevMgmt/PrintConfigDyn.xml"
RES_PRINT_CONFIG_CAP = "/DevMgmt/PrintConfigCap.xml"
RES_MEDIA_HANDLING = "/DevMgmt/MediaHandlingDyn.xml"
RES_MEDIA = "/DevMgmt/MediaDyn.xml"
RES_NET_APPS = "/DevMgmt/NetAppsDyn.xml"
RES_NET_APPS_SECURE = "/DevMgmt/NetAppsSecureDyn.xml"
RES_PRODUCT_LOGS = "/DevMgmt/ProductLogsDyn.xml"
RES_SECURITY = "/DevMgmt/SecurityDyn.xml"
RES_INTERNAL_PRINT = "/DevMgmt/InternalPrintDyn.xml"
RES_INTERNAL_PRINT_CAP = "/DevMgmt/InternalPrintCap.xml"
RES_COPY_CONFIG = "/Copy/CopyConfigDyn.xml"
RES_COPY_CONFIG_CAP = "/Copy/CopyConfigCap.xml"
RES_ADAPTERS = "/IoMgmt/Adapters"
RES_IO_CONFIG = "/IoMgmt/IoConfig.xml"
RES_FIRMWARE = "/FirmwareUpdate/WebFWUpdate"
RES_FIRMWARE_CONFIG = "/FirmwareUpdate/WebFWUpdate/Config"
RES_FIRMWARE_STATE = "/FirmwareUpdate/WebFWUpdate/State"
RES_FIRMWARE_ACTION = "/FirmwareUpdate/WebFWUpdate/StateAction"
RES_CALIBRATION_STATE = "/Calibration/State"
RES_CALIBRATION_SESSION = "/Calibration/Session"
RES_EPRINT = "/ePrint/ePrintConfigDyn.xml"
RES_EVENT_TABLE = "/EventMgmt/EventTable"
RES_POWER_CYCLE = "/ProductActions/PowerCycle"
RES_ICC_STATUS = "/Utilities/ICCStatus"
RES_ICC_JOB = "/Utilities/ICCJob"
RES_OOBE_STATUS = "/OOBE/Status"
RES_JOB_LIST = "/Jobs/JobList"

# --- eSCL (AirScan) ---------------------------------------------------------
RES_ESCL_CAPS = "/eSCL/ScannerCapabilities"
RES_ESCL_STATUS = "/eSCL/ScannerStatus"
RES_ESCL_JOBS = "/eSCL/ScanJobs"
RES_ESCL_CONFIG = "/eSCL/eSCLConfig"

# --- CDM (Cloud Device Model, JSON) -----------------------------------------
RES_CDM_DISCOVERY = "/cdm/servicesDiscovery"
RES_CDM_PRINT_MODE = "/cdm/print/v1/printModeConfiguration"
RES_CDM_CONTROL_PANEL = "/cdm/controlPanel/v1/configuration"
RES_CDM_MEDIA_CONFIG = "/cdm/print/v1/mediaConfiguration"
RES_CDM_IDENTITY = "/cdm/system/v1/identity"
RES_CDM_SUPPLIES = "/cdm/supply/v1/suppliesPublic"
RES_CDM_PRODUCT_STATUS = "/cdm/system/v1/productStatus"

# --- IPP --------------------------------------------------------------------
IPP_BASE_PATH = "/ipp/print"

# --- XML namespaces used when writing ---------------------------------------
NS_DD = "http://www.hp.com/schemas/imaging/con/dictionaries/1.0/"
NS_DD3 = "http://www.hp.com/schemas/imaging/con/dictionaries/2009/04/06"
NS_PRDCFGDYN = "http://www.hp.com/schemas/imaging/con/ledm/productconfigdyn/2007/11/05"
NS_PRDCFGDYN2 = "http://www.hp.com/schemas/imaging/con/ledm/productconfigdyn/2009/03/16"
NS_PRNCFGDYN = "http://www.hp.com/schemas/imaging/con/ledm/printconfigdyn/2007/11/02"
NS_PRNCFGDYN2 = "http://www.hp.com/schemas/imaging/con/ledm/printconfigdyn/2009/05/06"
NS_CPCFGDYN = "http://www.hp.com/schemas/imaging/con/ledm/cpcfgdyn/2008/05/05"
NS_COPY = "http://www.hp.com/schemas/imaging/con/copy/2008/07/07"
NS_FWUDYN = "http://www.hp.com/schemas/imaging/con/ledm/firmwareupdatedyn/2010/12/12"
NS_NADYN = "http://www.hp.com/schemas/imaging/con/ledm/netappdyn/2009/06/24"
NS_NASDYN = "http://www.hp.com/schemas/imaging/con/ledm/netappsecdyn/2012/11/15"
NS_IPDYN = "http://www.hp.com/schemas/imaging/con/ledm/internalprintdyn/2008/03/21"
NS_CAL = "http://www.hp.com/schemas/imaging/con/cnx/markingagentcalibration/2009/04/08"
NS_ESCL = "http://schemas.hp.com/imaging/escl/2011/05/03"
NS_PWG = "http://www.pwg.org/schemas/2010/12/sm"
NS_CCDYN = "http://www.hp.com/schemas/imaging/con/ledm/consumableconfigdyn/2007/11/19"


class PrinterState(StrEnum):
    """Normalised printer state derived from LEDM status categories."""

    IDLE = "idle"
    PRINTING = "printing"
    SCANNING = "scanning"
    COPYING = "copying"
    CANCELING = "canceling"
    INITIALIZING = "initializing"
    CALIBRATING = "calibrating"
    SHUTTING_DOWN = "shutting_down"
    SLEEPING = "sleeping"
    ATTENTION = "attention"
    ERROR = "error"
    UNKNOWN = "unknown"


# LEDM ProductStatusDyn categories that mean the device is busy doing something.
BUSY_CATEGORIES: dict[str, PrinterState] = {
    "processing": PrinterState.PRINTING,
    "printing": PrinterState.PRINTING,
    "scanProcessing": PrinterState.SCANNING,
    "scanning": PrinterState.SCANNING,
    "copying": PrinterState.COPYING,
    "cancelJob": PrinterState.CANCELING,
    "initializing": PrinterState.INITIALIZING,
    "inkSystemInitializing": PrinterState.INITIALIZING,
    "calibrating": PrinterState.CALIBRATING,
    "shuttingDown": PrinterState.SHUTTING_DOWN,
}

SLEEP_CATEGORIES = frozenset({"inPowerSave", "sleep", "powerSave"})

# Categories that are purely informational (never raise attention).
INFO_CATEGORIES = frozenset(
    {
        "ready",
        "genuineHP",
        "inPowerSave",
        "processing",
        "scanProcessing",
        "copying",
        "initializing",
        "inkSystemInitializing",
        "calibrating",
        "shuttingDown",
        "cancelJob",
        "usedConsumable",
    }
)

# Categories that always mean a hard error, even without an alert table.
ERROR_CATEGORIES = frozenset(
    {
        "carriageJam",
        "cartridgeFailure",
        "cartridgeInWrongOrder",
        "cartridgeMissing",
        "closeDoorOrCover",
        "copyJobError",
        "dynamicSecurityCheckFailed",
        "incompatibleConsumable",
        "jamInPrinter",
        "inkSystemFailure",
        "outputBinClosed",
        "printerError",
        "removeMedia",
        "scannerError",
        "sharedAddressError",
        "trayClosed",
        "trayEmptyOrOpen",
        "trayOpen",
        "antiTheftEnabledSupplyDetected",
        "nonHPSupplyDetected",
    }
)

# Consumable label codes -> (human colour name, CSS colour).
CONSUMABLE_COLORS: dict[str, tuple[str, str]] = {
    "K": ("black", "#000000"),
    "MK": ("matte_black", "#1a1a1a"),
    "PK": ("photo_black", "#2b2b2b"),
    "C": ("cyan", "#00AEEF"),
    "M": ("magenta", "#EC008C"),
    "Y": ("yellow", "#FFF200"),
    "CMY": ("tri_color", "#00AEEF"),
    "LC": ("light_cyan", "#7FD6F5"),
    "LM": ("light_magenta", "#F57FC3"),
    "GY": ("gray", "#808080"),
    "LGY": ("light_gray", "#B0B0B0"),
}

MARKER_COLOR_TO_LABEL: dict[str, str] = {
    "Black": "K",
    "MatteBlack": "MK",
    "PhotoBlack": "PK",
    "Cyan": "C",
    "Magenta": "M",
    "Yellow": "Y",
    "CyanMagentaYellow": "CMY",
    "LightCyan": "LC",
    "LightMagenta": "LM",
    "Gray": "GY",
    "LightGray": "LGY",
}

POWER_SAVE_TIMEOUTS_DEFAULT = ("5minutes", "10minutes", "15minutes")

INTERNAL_PRINT_JOBS = (
    "cleaningPage",
    "cleaningPageLevel2",
    "cleaningVerificationPage",
    "configurationPage",
    "diagnosticsPage",
    "extendedConfigurationPage",
    "networkSummary",
    "networkDiagnosticPage",
    "wirelessNetworkPage",
    "paperFeedCleaningPage",
    "pqDiagnosticsPage",
    "ribSmearCleaningPage",
    "eventLogReport",
    "webAccessReport",
    "webServicesInfoPage",
    "ePrintSetupPage",
    "wifiDirectGuide",
)

FIRMWARE_ACTIONS = ("check", "start", "cancel", "reset")

IPP_JOB_STATES: dict[int, str] = {
    3: "pending",
    4: "pending_held",
    5: "processing",
    6: "processing_stopped",
    7: "canceled",
    8: "aborted",
    9: "completed",
}

IPP_PRINTER_STATES: dict[int, str] = {3: "idle", 4: "processing", 5: "stopped"}
