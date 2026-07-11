$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$tempRoot = Join-Path $env:TEMP "HardwareMonitoringDeps-v2.3.1"
$presentMonUrl = "https://github.com/GameTechDev/PresentMon/releases/download/v2.3.1/PresentMon-2.3.1-x64.exe"
$lhmUrl = "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/v0.9.4/LibreHardwareMonitor-net472.zip"
$presentMonHash = "364E5D98D4D134BD54DD25C22ED2CA2F4883F8BC3ED6502BEE0C151E3436D30"
$lhmZipHash = "D2E397CC4D33D65C6493DFF83B9335BC341A3AF31CAAFCEEF83F717FDAB37448"
$lhmDllHash = "A0F2728F1734C236A9D02D9E25A88BC4F8CB7BD1FAFF1770726BEB7AF06BF8DC"

New-Item -ItemType Directory -Force $tempRoot | Out-Null
$presentMon = Join-Path $tempRoot "PresentMon-2.3.1-x64.exe"
$lhmZip = Join-Path $tempRoot "LibreHardwareMonitor-net472.zip"
Invoke-WebRequest $presentMonUrl -OutFile $presentMon
Invoke-WebRequest $lhmUrl -OutFile $lhmZip
if ((Get-FileHash $presentMon -Algorithm SHA256).Hash -ne $presentMonHash) { throw "PresentMon SHA-256 mismatch" }
if ((Get-FileHash $lhmZip -Algorithm SHA256).Hash -ne $lhmZipHash) { throw "LibreHardwareMonitor archive SHA-256 mismatch" }

$lhmExtract = Join-Path $tempRoot "LibreHardwareMonitor"
Expand-Archive -LiteralPath $lhmZip -DestinationPath $lhmExtract -Force
$dll = Get-ChildItem $lhmExtract -Recurse -Filter LibreHardwareMonitorLib.dll | Select-Object -First 1
if (-not $dll) { throw "LibreHardwareMonitorLib.dll not found in archive" }
if ((Get-FileHash $dll.FullName -Algorithm SHA256).Hash -ne $lhmDllHash) { throw "LibreHardwareMonitorLib.dll SHA-256 mismatch" }

New-Item -ItemType Directory -Force (Join-Path $root "tools\PresentMon"), (Join-Path $root "_internal\libs") | Out-Null
Copy-Item $presentMon (Join-Path $root "tools\PresentMon\PresentMon.exe") -Force
Copy-Item $dll.FullName (Join-Path $root "_internal\libs\LibreHardwareMonitorLib.dll") -Force
Write-Host "Dependencies verified and copied to canonical build inputs."
