# HP printer local protocols

Everything here was captured from an **HP DeskJet Ink Advantage 2774**
(firmware `TWP1FN2550DR`, 2025-12-12) on 2026-10-30 and cross-checked with
public dumps of other models. Reads never need credentials; LEDM writes are
redirected to HTTPS and ask for HTTP Basic auth with user `admin` and the EWS
password (realm `admin`). CDM writes on the DeskJet accepted plain HTTP
without credentials.

## Ports and discovery

| Port | Protocol | Notes |
| --- | --- | --- |
| 80 | HTTP: LEDM XML, CDM JSON, eSCL, EWS | `curl` gets `499 Request has been forbidden by antivirus`; any other User-Agent works |
| 443 | HTTPS (self-signed, CN = hostname) | required for LEDM `PUT`/`POST`, `/DevMgmt/SecurityDyn.xml`, `/AccessList/Users` |
| 631 | IPP 2.0 (`/ipp/print`), IPPS | AirPrint 2.1, IPP Everywhere, Mopria 2.0 |
| 161/udp | SNMP v1/v2c `public`, read-only | Printer-MIB (RFC 3805) + Host-Resources |
| 9100 | raw PCL3GUI/PCLm | |

mDNS services: `_ipp._tcp`, `_ipps._tcp`, `_uscan._tcp` (eSCL), `_http._tcp`
(EWS), `_printer._tcp`, `_pdl-datastream._tcp`. TXT of `_ipp._tcp`:
`ty=HP DeskJet 2700 series`, `usb_MFG=HP`, `usb_MDL=DeskJet 2700 series`,
`mac=5c:60:ba:50:24:72`, `UUID=…`, `adminurl=http://HP5C60BA502472.local./#hId-pgAirPrint`,
`Scan=T`, `Color=T`, `Duplex=F`, `Fax=F`, `rp=ipp/print`, `TLS=1.2`,
`mopria-certified=2.0`, `URF=…`, `pdl=application/vnd.hp-PCL,image/jpeg,application/PCLm,image/urf,image/pwg-raster`.

Default hostname `HP<last 6 MAC>` (`HP502472`), mDNS host `HP5C60BA502472.local.`.

## LEDM (Low End Data Model)

Entry point `GET /DevMgmt/DiscoveryTree.xml`: lists `ledm:SupportedTree`
(`ResourceURI` + `ResourceType`) and `ledm:SupportedIfc` (`ManifestURI`).
Each manifest declares a root URL, resource nodes and allowed verbs. Resources
the DeskJet 2700 exposes (`Cap` = capabilities, `Dyn` = live values):

| Resource | Verbs | Content |
| --- | --- | --- |
| `/DevMgmt/ProductConfigDyn.xml` | GET, PUT | `ProductInformation` (MakeAndModel, MakeAndModelFamily, SKUIdentifier, UUID, SerialNumber, ProductNumber, ServiceID, Version/Revision+Date = firmware, Manufacturer/Date, PasswordStatus, RegionInformation), `ProductSettings` (PowerSaveTimeout, AutoOffTime, ProductLanguage/DeviceLanguage, CountryAndRegionName, TimeStamp, TimeFormat, DateFormat, QuietPrintMode, EWS/EnableDisable+ResourceURI, PowerSave, OobePhase, DeviceInformation/{Description,DeviceLocation,GeoLocation}, ControlPanel), `Memory` |
| `/DevMgmt/ProductConfigCap.xml` | GET | allowed values: PowerSaveTimeout 5/10/15minutes, AutoOffTime 2hours, countries, languages, TimeFormat HR12/HR24, DateFormat, QuietPrintMode, PrintEnginePPM, MaxColorPrintQuality, interpreters |
| `/DevMgmt/ProductStatusDyn.xml` | GET | `Status/StatusCategory` (+ `locid:StringId`), `AlertTable/Alert` (ProductStatusAlertID, Severity Info/Warning/StrictWarning/Error, AlertPriority, AlertDetails/{MarkerColor, ConsumableTypeEnum, MarkerLocation, UserAction, InputBin, MediaType, MediaSize, ErrorCode, DoorCoverLocation, JamLocation…}) |
| `/DevMgmt/ProductStatusCap.xml` | GET | full StatusCategory enum: antiTheftEnabledSupplyDetected, BBCMediaDetected, calibrating, calibrationRequired, cancelJob, carriageJam, cartridgeFailure, cartridgeInWrongOrder, cartridgeLow, cartridgeMissing, cartridgeVeryLow, closeDoorOrCover, copying, copyJobError, dynamicSecurityCheckFailed, genuineHP, improperShutdown, incompatibleConsumable, initializing, inkSystemInitializing, inPowerSave, jamInPrinter, nonHPSupplyDetected, outputBinClosed, printerError, processing, ready, removeMedia, scanProcessing, scannerError, sharedAddressError, shuttingDown, singleCartridgeMode, sizeMismatchInTray, trayClosed, trayEmptyOrOpen, trayOpen, usedConsumable |
| `/DevMgmt/ConsumableConfigDyn.xml` | GET | `ProductConsumableInfo` (NumOfUserReplaceableConsumables, AlignmentMode, SupportedConsumables → cartridge numbers 667/667XL, SingleCartridgeMode, GenuineHPSuppliesOnly, AntiTheftMode), `ConsumableInfo` × N (ConsumableLabelCode K/CMY/C/M/Y, ConsumableStation, ConsumableTypeEnum, ConsumablePercentageLevelRemaining, ConsumableLifeState/{ConsumableState newGenuineHP/ok/low/veryLow/depleted…, MeasuredQuantityState, Brand, IsRefilled, IsSETUP, IsTrial}, ConsumableSelectibilityNumber, ConsumableUniqueID, ConsumableID, ConsumableFamilyName, ConsumableIcon/FillColor RGB, Capacity) |
| `/DevMgmt/ProductUsageDyn.xml` | GET | `PrinterSubunit` (TotalImpressions, JamEvents, MispickEvents, TotalFrontPanelCancelPresses, UsageByMarkingAgent ml, UsageByMedia per size, UsageByMediaType per type + UsageByJobSize + UsageByQuality, UsageByTimeInterval, EWSAccessCount, NetworkImpressions, WirelessNetworkImpressions, QuietModeImpressions, UsageByDataPath, OOBESetupBy), `ConsumableSubunit/Consumable` (ConsumableRawPercentageLevelRemaining, RefilledCount, PenInsertionTriggerSnapshotCounter, drop counters), `ScannerEngineSubunit` (ScanImages, FlatbedImages, AdfImages), `ScanApplicationSubunit` (ScanToHostImages), `CopyApplicationSubunit` (Total/Color/Monochrome/Flatbed/Adf), `PrintApplicationSubunit`, `MobileApplicationSubunit` |
| `/DevMgmt/PrintConfigDyn.xml` / `Cap` | GET, PUT | DefaultPrintCopies (1-99), PrintQuality Best/Draft/Normal, ResolutionSetting fast300/600/1200dpi, BorderlessPrinting, ColorLok, JamRecovery, JobTimeout/LeaseTime (5-300 s), DefaultCourier, DefaultPDLInterpreterOrientation, InkSliders |
| `/DevMgmt/MediaHandlingDyn.xml` / `Cap` | GET | trays (InputBin, TrayState, MediaType, MediaSizeName, Plex, FeederType, TrayLock), DefaultInputTray, MediaOutActionType, OutputBin |
| `/DevMgmt/MediaDyn.xml` / `Cap` | GET | current MediaType/MediaSizeName, printable margins |
| `/DevMgmt/NetAppsDyn.xml` / `Cap` | GET, PUT | DNSSDConfig (MDNSSupport, ApplicationServiceName, DomainName, DNSSDPrintPreferredService), ProxyConfig, SNMPConfigWithVersion (SNMP, AccessOption, community names), WebServicesConfig (WSDiscovery, WSPrint, WSScan), DHCPv6, LLMNR, HTTPSRedirection, Port9100PrintingSupport, IPPSupport, WebScan, DirectPrint, WPADSettings |
| `/DevMgmt/NetAppsSecureDyn.xml` / `Cap` | GET, PUT | WirelessDirectConfig (ShowPassPhrase, HideSSID, DisableSSIDBroadcast, SSIDPrefix, ConnectionMethod), AutoWirelessConfig, AirPrintConfig/State, IPPSConfig/State, WPADConfig/State, RemotelyInitiatedScans, BluetoothSmartConfig/State |
| `/DevMgmt/ProductLogsDyn.xml` | GET | EventLog/Event (SequenceNumber, EventOccurrences, EventCode, TotalImpressions), ErrorLog (text) |
| `/DevMgmt/InternalPrintDyn.xml` | POST | `<ipdyn:InternalPrintDyn><ipdyn:JobType>X</ipdyn:JobType></ipdyn:InternalPrintDyn>`; X from `InternalPrintCap.xml`: cleaningPage, cleaningPageLevel2, cleaningVerificationPage, configurationPage, wifiDirectGuide, diagnosticsPage, extendedConfigurationPage, networkSummary, networkDiagnosticPage, wirelessNetworkPage, paperFeedCleaningPage, pqDiagnosticsPage, ribSmearCleaningPage, eventLogReport, webAccessReport, webServicesInfoPage, ePrintSetupPage, googleCloudPrintPage |
| `/DevMgmt/SecurityDyn.xml` (HTTPS) | GET, PUT | admin password (`<secdyn:Password>` base64), access history, failsafe, StrictSecureConnect |
| `/DevMgmt/ShopForSupplies.xml` | GET | HP SureSupply request (serial, compatible cartridges, levels) |
| `/Copy/CopyConfigDyn.xml` / `Cap` | GET, PUT | DefaultLighterDarker 0-8, DefaultMediaSizeName, DefaultMediaType, DefaultNumberOfCopies 1-9, DefaultReduceEnlarge original/fitToPage/custom (+Custom 25-400 %), DefaultTraySelect, DefaultCopyQuality best/normal, DefaultMarginOff, CopySides, DefaultOutputType monochrome/color, DefaultInputSource |
| `/IoMgmt/Adapters` | GET | Adapter × N (Wifi0 station, Wifi1 Wi-Fi Direct AP, Usb0): HardwareConfig (Name, Power, MacAddress, DeviceConnectivityPortType, WifiNetwork/{SSID hex, BSSID, SignalInfo/{SignalStrength 0-5, dBm}, EncryptionType, AuthenticationMode, WpsSupport}, IsConnected, IsCurrentRequestInterface) |
| `/IoMgmt/Adapters/<name>/Protocols` | GET | IPv4 (address, mask, gateway, DNS, DHCP server, ConfigMethod) and IPv6 addresses |
| `/IoMgmt/Adapters/<name>/NetworkStats` | GET | packet counters |
| `/IoMgmt/Adapters/Wifi0/Profiles/Active` | GET, PUT | current Wi-Fi profile (SSID hex, security, passphrase write-only) |
| `/IoMgmt/IoConfig.xml` | GET, PUT | Hostname, DefaultHostname, domain |
| `/FirmwareUpdate/WebFWUpdate` | GET | Config (AutomaticCheck, AutomaticUpdate) + State (Status idle/checking/available/downloading/installReady/installing/installSuccess/…Failed, TargetFWVersion, ProgressPercentage, Error, Reason, Type) |
| `/FirmwareUpdate/WebFWUpdate/Config` | GET, PUT | `<fwudyn:FirmwareUpdateConfig><fwudyn:AutomaticCheck>enabled</fwudyn:AutomaticCheck><fwudyn:AutomaticUpdate>enabled</fwudyn:AutomaticUpdate></fwudyn:FirmwareUpdateConfig>` |
| `/FirmwareUpdate/WebFWUpdate/StateAction` | PUT | `<fwudyn:FirmwareUpdateAction><fwudyn:UpdateAction>check|start|cancel|reset</fwudyn:UpdateAction></fwudyn:FirmwareUpdateAction>` |
| `/Calibration/State` | GET | `<CalibrationState>CalibrationRequired|…</CalibrationState>` |
| `/Calibration/Session` | POST | `<cal:CalibrationState>Printing</cal:CalibrationState>` starts alignment (prints a page) |
| `/ePrint/ePrintConfigDyn.xml` | GET, PUT | CloudConfiguration (EmailService, MobileAppsService), RegistrationState, SignalingConnectionState, CloudServicesSwitch/Status, RegistrationDetails |
| `/EventMgmt/EventTable` | GET (`?timeout=N` long-poll, `If-None-Match`) | Event (UnqualifiedEventCategory AlertTableChanged/JobEvent/PowerUpEvent/PoweringDownEvent/ScanEvent/ConsumableEvent/DeviceCapabilitiesChanged/OOBEStatusChanged, AgingStamp) |
| `/EventMgmt/SubscriptionList` | GET, POST | push subscriptions (device-initiated UDP/XMPP/USB only on this model) |
| `/Jobs/JobList` | GET (204 when empty), PUT | LEDM job list / cancel |
| `/ProductActions/PowerCycle`, `/DirtyPowerCycle`, `/FactoryDefaults`, `/ResetOnNextBoot` | PUT (secure) | restart / reset |
| `/Utilities/ICCStatus`, `/Utilities/ICCJob` | GET / POST | internet connection check |
| `/OOBE/Status`, `/OOBE/DeviceInfo`, `/OOBE/Config` | GET | setup state |
| `/Scan/ScanCaps`, `/Scan/Status`, `/Scan/Jobs` | GET / POST | legacy LEDM scan (eSCL preferred) |
| `/AccessList/Properties`, `/AccessList/Users` (HTTPS) | GET, PUT/POST | per-user IPP permissions |

### XML namespaces used for writes

```
dd          http://www.hp.com/schemas/imaging/con/dictionaries/1.0/
dd3         http://www.hp.com/schemas/imaging/con/dictionaries/2009/04/06
prdcfgdyn   http://www.hp.com/schemas/imaging/con/ledm/productconfigdyn/2007/11/05
prdcfgdyn2  http://www.hp.com/schemas/imaging/con/ledm/productconfigdyn/2009/03/16
prncfgdyn   http://www.hp.com/schemas/imaging/con/ledm/printconfigdyn/2007/11/02
prncfgdyn2  http://www.hp.com/schemas/imaging/con/ledm/printconfigdyn/2009/05/06
cpcfgdyn    http://www.hp.com/schemas/imaging/con/ledm/cpcfgdyn/2008/05/05
copy        http://www.hp.com/schemas/imaging/con/copy/2008/07/07
nadyn       http://www.hp.com/schemas/imaging/con/ledm/netappdyn/2009/06/24
nasdyn      http://www.hp.com/schemas/imaging/con/ledm/netappsecdyn/2012/11/15
fwudyn      http://www.hp.com/schemas/imaging/con/ledm/firmwareupdatedyn/2010/12/12
ipdyn       http://www.hp.com/schemas/imaging/con/ledm/internalprintdyn/2008/03/21
cal         http://www.hp.com/schemas/imaging/con/cnx/markingagentcalibration/2009/04/08
ccdyn       http://www.hp.com/schemas/imaging/con/ledm/consumableconfigdyn/2007/11/19
io / wifi   http://www.hp.com/schemas/imaging/con/ledm/iomgmt/2008/11/30 / …/wifi/2009/06/26
```

A LEDM `PUT` carries a partial document: the root element with its
namespaces and only the elements being changed, e.g.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<prdcfgdyn2:ProductConfigDyn xmlns:prdcfgdyn2="…/productconfigdyn/2009/03/16"
  xmlns:prdcfgdyn="…/productconfigdyn/2007/11/05" xmlns:dd="…/dictionaries/1.0/">
  <prdcfgdyn2:ProductSettings>
    <dd:PowerSaveTimeout>10minutes</dd:PowerSaveTimeout>
  </prdcfgdyn2:ProductSettings>
</prdcfgdyn2:ProductConfigDyn>
```

Plain HTTP answers `301 Location: https://…`; HTTPS without credentials
answers `401 WWW-Authenticate: Basic realm="admin"`.

## CDM (Cloud Device Model)

`GET /cdm/servicesDiscovery` → `{"version","services":[{"serviceGun","links":[{"rel","href","hints":[{"method"}]}]}]}`.
The DeskJet 2700 (LEDM era) only exposes:

| href | Verbs | Body |
| --- | --- | --- |
| `/cdm/print/v1/printModeConfiguration` | GET, PUT | `{"version":"1.0.0","quietPrintModeEnabled":"true"}` — works over HTTP without password |
| `/cdm/print/v1/mediaConfiguration` (+`/constraints`) | GET, PUT | default media per size group |
| `/cdm/controlPanel/v1/configuration` (+`/constraints`) | GET, PUT | `{"version":"1.0.0","deviceLanguage":"pt"}` |
| `/cdm/telemetry/v1/eventing/eventCapabilities`, `/events` | GET | telemetry event categories |
| `/cdm/remoteAuthentication/v1/{capabilities,config,pushbuttons,tokens}` | GET / POST | PIN / push-button token auth (HTTPS) |
| `/cdm/awc/v1/*` | — | Auto Wireless Connect, inactive once set up |

CDM-only printers (Smart Tank 5xx, DeskJet 28xx/42xx/49xx, LaserJet 3xxx/4xxx,
OfficeJet Pro 81xx/91xx) additionally expose `system/v1/{identity,status,
statistics,configuration}`, `supply/v1/suppliesPublic`, `alert/v1/alerts`,
`deviceUsage/v1/{lifetimeCounters,serviceCounters}`, `power/v1/{configuration,reboot}`,
`print/v2/{status,configuration}`, `media/v1/configuration`, `scan/v1/status`,
`firmwareUpdate/v2/{configuration,updateStatus,updateCheck}`, `network/v1/*`,
`ioConfig/v2/*`, `report/v1/{reports,print}` (PATCH `{"state":"processing","reportId":"…"}`),
`calibration/v1/calibration/penAlignSemiauto` (PATCH). The client maps those
onto the same models when LEDM is absent. Some of these firmwares refuse plain
HTTP (301/HSTS) — the client retries discovery over HTTPS automatically.

## eSCL (AirScan)

```
GET  /eSCL/ScannerCapabilities   → platen/ADF limits (1/300 in), resolutions, colour modes, formats, intents
GET  /eSCL/ScannerStatus         → pwg:State Idle|Processing|Testing|Stopped|Down, scan:AdfState, scan:Jobs/JobInfo
POST /eSCL/ScanJobs              → 201 + Location (409 bad settings, 503 busy)
GET  <job>/NextDocument          → image (200), 503 retry, 404 no more pages
GET  <job>/ScanImageInfo
DELETE <job>
```

Request body (namespaces `scan` = `http://schemas.hp.com/imaging/escl/2011/05/03`,
`pwg` = `http://www.pwg.org/schemas/2010/12/sm`):

```xml
<scan:ScanSettings xmlns:scan="…" xmlns:pwg="…">
  <pwg:Version>2.63</pwg:Version>
  <pwg:ScanRegions><pwg:ScanRegion>
    <pwg:ContentRegionUnits>escl:ThreeHundredthsOfInches</pwg:ContentRegionUnits>
    <pwg:XOffset>0</pwg:XOffset><pwg:YOffset>0</pwg:YOffset>
    <pwg:Width>2480</pwg:Width><pwg:Height>3508</pwg:Height>
  </pwg:ScanRegion></pwg:ScanRegions>
  <pwg:InputSource>Platen</pwg:InputSource>
  <scan:ColorMode>RGB24</scan:ColorMode>
  <scan:XResolution>300</scan:XResolution><scan:YResolution>300</scan:YResolution>
  <pwg:DocumentFormat>image/jpeg</pwg:DocumentFormat>
  <scan:DocumentFormatExt>image/jpeg</scan:DocumentFormatExt>
  <scan:Intent>Document</scan:Intent>
</scan:ScanSettings>
```

A 75 dpi A4 preview on the DeskJet takes ~6 s end to end.

## IPP

`Get-Printer-Attributes` returns 156 attributes. Beyond the usual CUPS
`marker-*` set the useful ones are `printer-state` (3 idle / 4 processing /
5 stopped), `printer-state-reasons`, `printer-alert-description`,
`printer-supply` (`type=inkCartridge;maxcapacity=100;level=90;…`),
`printer-input-tray`, `printer-wifi-ssid`, `printer-wifi-state` (8 = on),
`printer-firmware-string-version`, `printer-uuid`, `printer-icons`,
`printer-strings-uri`, `media-ready`, `identify-actions-supported`
(`flash`, `pin`), `operations-supported` = Print-Job, Print-URI, Validate-Job,
Create-Job, Send-Document, Send-URI, Cancel-Job, Get-Job-Attributes, Get-Jobs,
Get-Printer-Attributes, Set-Printer-Attributes, Cancel-My-Jobs, Close-Job,
Identify-Printer. `Identify-Printer` with `identify-actions=flash` blinks the
panel. `document-format-supported`: PCL, JPEG, PCLm, URF, PWG raster (no PDF).

## SNMP (read-only, community `public`)

Host-Resources `hrDeviceStatus 1.3.6.1.2.1.25.3.2.1.5.1`,
`hrPrinterStatus .25.3.5.1.1.1` (3 idle / 4 printing / 5 warmup),
`hrPrinterDetectedErrorState .25.3.5.1.2.1`; Printer-MIB covers,
`prtInputTable`, `prtMarkerSupplies`, `prtGeneralSerialNumber
1.3.6.1.2.1.43.5.1.1.17.1`. Not used by the library (LEDM/IPP give more).
