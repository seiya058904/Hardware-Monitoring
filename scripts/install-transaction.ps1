param(
    [Parameter(Mandatory=$true)][ValidateSet('Install','Uninstall')][string]$Mode,
    [Parameter(Mandatory=$true)][string]$InstallRoot,
    [string]$SourceRoot
)
$ErrorActionPreference = 'Stop'
$rootPath = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
if ($rootPath -eq [IO.Path]::GetPathRoot($rootPath).TrimEnd('\')) { throw 'Invalid installation root' }
$manifestName = 'managed-files.json'
function Resolve-Managed([string]$relative) {
    if ([IO.Path]::IsPathRooted($relative)) { throw 'Absolute manifest entry' }
    $resolved = [IO.Path]::GetFullPath((Join-Path $rootPath $relative))
    if (-not $resolved.StartsWith($rootPath + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Manifest escapes installation root' }
    $cursor = $resolved
    while ($cursor.Length -ge $rootPath.Length) {
        if ((Test-Path -LiteralPath $cursor) -and ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Reparse point in managed path' }
        $cursor = Split-Path -Parent $cursor
    }
    return $resolved
}
function Digest([string]$path) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    $stream = [IO.File]::OpenRead($path)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace("-", "") }
    finally { $stream.Dispose(); $hasher.Dispose() }
}
function Assert-NoRunningInstance {
    $processes = @(Get-CimInstance Win32_Process -Filter "Name = 'Hardware Monitoring.exe' OR Name = 'PresentMon.exe'")
    foreach ($process in $processes) {
        if (-not $process.ExecutablePath) { throw 'Cannot verify running process path; retry with administrator permissions' }
        $exe = [IO.Path]::GetFullPath($process.ExecutablePath)
        if ($exe.StartsWith($rootPath + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw ('Close this installation before continuing: PID ' + $process.ProcessId)
        }
    }
}
$journal = @()
$backupPath = $null
try {
    Assert-NoRunningInstance
    $manifestPath = Resolve-Managed $manifestName
    $oldEntries = @()
    if (Test-Path -LiteralPath $manifestPath) {
        $oldEntries = @(Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json)
        foreach ($entry in $oldEntries) { $null = Resolve-Managed $entry }
    }
    if ($Mode -eq 'Uninstall') {
        if (-not (Test-Path -LiteralPath $manifestPath)) { throw 'Managed manifest missing; repair this installation before uninstalling' }
        # Keep manifest and uninstaller intact until all managed payload files are removed.
        foreach ($entry in $oldEntries) {
            $target = Resolve-Managed $entry
            if (Test-Path -LiteralPath $target -PathType Leaf) { Remove-Item -LiteralPath $target -Force }
        }
        foreach ($directory in @($oldEntries | ForEach-Object { Split-Path -Parent (Resolve-Managed $_) } | Sort-Object -Unique | Sort-Object Length -Descending)) {
            if ($directory -ne $rootPath -and (Test-Path -LiteralPath $directory) -and -not (Get-ChildItem -LiteralPath $directory -Force | Select-Object -First 1)) {
                Remove-Item -LiteralPath $directory
            }
        }
        Remove-Item -LiteralPath $manifestPath
        exit 0
    }
    $sourcePath = [IO.Path]::GetFullPath($SourceRoot).TrimEnd('\')
    $entries = @(Get-ChildItem -LiteralPath $sourcePath -File -Recurse | ForEach-Object { $_.FullName.Substring($sourcePath.Length + 1) })
    if ('Hardware Monitoring.exe' -notin $entries) { throw 'Incomplete staged package' }
    foreach ($entry in $entries) { $null = Resolve-Managed $entry }
    $null = New-Item -ItemType Directory -Path $rootPath -Force
    $backupPath = Join-Path $rootPath ('.upgrade-' + [guid]::NewGuid().ToString('N'))
    $null = New-Item -ItemType Directory -Path $backupPath
    $newManifest = @($oldEntries + $entries | Sort-Object -Unique)
    $manifestSource = Join-Path $backupPath 'new-manifest.json'
    ConvertTo-Json -InputObject $newManifest | Set-Content -LiteralPath $manifestSource -Encoding UTF8
    foreach ($entry in @($entries) + @($manifestName)) {
        $target = Resolve-Managed $entry
        $source = if ($entry -eq $manifestName) { $manifestSource } else { Join-Path $sourcePath $entry }
        $backup = Join-Path $backupPath ([guid]::NewGuid().ToString('N'))
        $original = Digest $target
        if ($original) { Copy-Item -LiteralPath $target -Destination $backup }
        $journal += [pscustomobject]@{ Target=$target; Backup=$backup; Original=$original; Expected=(Digest $source); Source=$source; Changed=$false }
    }
    foreach ($record in $journal) {
        Assert-NoRunningInstance
        if ((Digest $record.Target) -ne $record.Original) { throw 'Concurrent modification before install' }
        $null = New-Item -ItemType Directory -Path (Split-Path -Parent $record.Target) -Force
        $temporary = $record.Target + '.install-' + [guid]::NewGuid().ToString('N')
        try {
            Copy-Item -LiteralPath $record.Source -Destination $temporary
            if ((Digest $temporary) -ne $record.Expected) { throw 'Staged file verification failed' }
            $record.Changed = $true
            if (Test-Path -LiteralPath $record.Target) { [IO.File]::Replace($temporary, $record.Target, ($record.Backup + ".atomic")) }
            else { [IO.File]::Move($temporary, $record.Target) }
        } finally {
            if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
            if (Test-Path -LiteralPath ($record.Backup + ".atomic")) { Remove-Item -LiteralPath ($record.Backup + ".atomic") }
        }
        if ((Digest $record.Target) -ne $record.Expected) { throw 'Installed file verification failed' }
    }
    foreach ($record in $journal) {
        if (Test-Path -LiteralPath $record.Backup) { Remove-Item -LiteralPath $record.Backup }
    }
    Remove-Item -LiteralPath $manifestSource
    Remove-Item -LiteralPath $backupPath
    exit 0
} catch {
    Write-Output $_.Exception.Message
    $rollbackFailed = $false
    [array]::Reverse($journal)
    foreach ($record in $journal) {
        if (-not $record.Changed) { continue }
        try {
            $current = Digest $record.Target
            if ($current -eq $record.Original) { continue }
            if ($current -ne $record.Expected) { throw 'Concurrent or partial write; preserve for recovery' }
            if ($record.Original) { Copy-Item -LiteralPath $record.Backup -Destination $record.Target -Force }
            else { Remove-Item -LiteralPath $record.Target }
        } catch { $rollbackFailed = $true; Write-Output $_.Exception.Message }
    }
    if ($backupPath) { Write-Output ('Recovery files retained: ' + $backupPath) }
    exit 1
}
