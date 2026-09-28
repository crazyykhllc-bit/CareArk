#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'Programs\CareArk'),
    [string]$DesktopDirectory = [Environment]::GetFolderPath('Desktop'),
    [string]$Version,
    [switch]$NoShortcut
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) {
    throw 'CareArk requires 64-bit Windows 10 or later.'
}
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$dataRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'CareArk'))
if ($InstallRoot.TrimEnd('\') -eq $dataRoot.TrimEnd('\') -or $InstallRoot.StartsWith($dataRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Choose a program directory outside the CareArk data directory.'
}
New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
$lock = $null
$staging = $null
try {
    $lock = [IO.File]::Open((Join-Path $InstallRoot '.install.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $repository = 'crazyykhllc-bit/CareArk'
    $headers = @{ 'User-Agent' = 'CareArk-Windows-Installer'; 'Accept' = 'application/vnd.github+json' }
    $endpoint = 'https://api.github.com/repos/' + $repository + '/releases/latest'
    if ($Version) {
        if ($Version -notmatch '^v[0-9]+\.[0-9]+\.[0-9]+$') { throw 'Version must look like v0.1.2.' }
        $endpoint = 'https://api.github.com/repos/' + $repository + '/releases/tags/' + $Version
    }
    Write-Host 'Checking the latest CareArk Windows release...'
    $release = Invoke-RestMethod -Uri $endpoint -Headers $headers -TimeoutSec 30
    $tag = [string]$release.tag_name
    if ($tag -notmatch '^v[0-9]+\.[0-9]+\.[0-9]+$' -or $release.draft -or $release.prerelease) { throw 'No supported stable release was found.' }
    $archiveName = 'CareArk-Windows-' + $tag + '.zip'
    $archives = @($release.assets | Where-Object { $_.name -eq $archiveName })
    $checksums = @($release.assets | Where-Object { $_.name -eq 'SHA256SUMS.txt' })
    if ($archives.Count -ne 1 -or $checksums.Count -ne 1) { throw 'The Windows archive or checksum asset is missing.' }
    $urlPrefix = 'https://github.com/' + $repository + '/releases/download/' + $tag + '/'
    foreach ($asset in @($archives[0], $checksums[0])) {
        if (-not ([string]$asset.browser_download_url).StartsWith($urlPrefix, [StringComparison]::Ordinal)) { throw 'Unexpected release download address.' }
    }
    $staging = Join-Path $InstallRoot ('.install-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $staging | Out-Null
    $checksumPath = Join-Path $staging 'SHA256SUMS.txt'
    Invoke-WebRequest -UseBasicParsing -Uri $checksums[0].browser_download_url -Headers $headers -OutFile $checksumPath -TimeoutSec 60
    $pattern = '^([0-9a-fA-F]{64})\s+\*?' + [regex]::Escape($archiveName) + '$'
    $matching = @(Get-Content -LiteralPath $checksumPath | Where-Object { $_ -match $pattern })
    if ($matching.Count -ne 1) { throw 'The checksum file does not identify this Windows archive.' }
    $expectedHash = [regex]::Match($matching[0], $pattern).Groups[1].Value.ToLowerInvariant()
    $versionDirectory = Join-Path (Join-Path $InstallRoot 'versions') $tag
    $manifestPath = Join-Path $versionDirectory 'install-manifest.json'
    $requiredFiles = @('CareArk.exe', '_internal\alembic\env.py', '_internal\app\web\index.html')
    if (Test-Path -LiteralPath $versionDirectory) {
        if (-not (Test-Path -LiteralPath $manifestPath)) { throw 'This version directory already exists without a verified installation. Choose another InstallRoot.' }
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        if ($manifest.sha256 -ne $expectedHash -or $manifest.version -ne $tag) { throw 'The existing installation does not match the published release.' }
        foreach ($file in $requiredFiles) {
            if (-not (Test-Path -LiteralPath (Join-Path $versionDirectory $file) -PathType Leaf)) { throw 'The existing installation is incomplete. Choose another InstallRoot to reinstall.' }
        }
        Write-Host ('CareArk ' + $tag + ' is already installed.')
    } else {
        $archivePath = Join-Path $staging $archiveName
        Write-Host ('Downloading ' + $archiveName + '...')
        Invoke-WebRequest -UseBasicParsing -Uri $archives[0].browser_download_url -Headers $headers -OutFile $archivePath -TimeoutSec 300
        $hash = [Security.Cryptography.SHA256]::Create()
        $source = [IO.File]::OpenRead($archivePath)
        try { $actualHash = [BitConverter]::ToString($hash.ComputeHash($source)).Replace('-', '').ToLowerInvariant() }
        finally { $source.Dispose(); $hash.Dispose() }
        if ($actualHash -ne $expectedHash) { throw 'SHA256 verification failed. Nothing has been installed.' }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive = [IO.Compression.ZipFile]::OpenRead($archivePath)
        try {
            foreach ($entry in $archive.Entries) {
                $destination = [IO.Path]::GetFullPath((Join-Path $staging $entry.FullName))
                if (-not $destination.StartsWith((Join-Path $staging 'CareArk') + '\', [StringComparison]::OrdinalIgnoreCase) -and $destination -ne (Join-Path $staging 'CareArk')) {
                    throw 'The archive contains an unexpected file path.'
                }
            }
        } finally { $archive.Dispose() }
        [IO.Compression.ZipFile]::ExtractToDirectory($archivePath, $staging)
        $program = Join-Path $staging 'CareArk'
        foreach ($file in $requiredFiles) {
            if (-not (Test-Path -LiteralPath (Join-Path $program $file) -PathType Leaf)) { throw 'The release archive is incomplete. Nothing has been installed.' }
        }
        @{ version = $tag; sha256 = $expectedHash; source = $archives[0].browser_download_url } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $program 'install-manifest.json') -Encoding UTF8
        New-Item -ItemType Directory -Path (Split-Path $versionDirectory -Parent) -Force | Out-Null
        Move-Item -LiteralPath $program -Destination $versionDirectory
    }
    $executable = Join-Path $versionDirectory 'CareArk.exe'
    if (-not $NoShortcut) {
        if (-not (Test-Path -LiteralPath $DesktopDirectory -PathType Container)) { throw 'The desktop directory was not found. Rerun with -NoShortcut or set -DesktopDirectory.' }
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut((Join-Path $DesktopDirectory 'CareArk.lnk'))
        $shortcut.TargetPath = $executable
        $shortcut.WorkingDirectory = $versionDirectory
        $shortcut.Description = 'CareArk - personal and family health archive'
        $shortcut.Save()
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shortcut) | Out-Null
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null
        Write-Host 'Desktop shortcut created. Double-click CareArk to open the workbench.'
    }
    Write-Host ('Installed: ' + $executable)
    Write-Host ('Data stays in: ' + $dataRoot)
} finally {
    if ($staging -and (Test-Path -LiteralPath $staging)) {
        $resolvedStaging = [IO.Path]::GetFullPath($staging)
        if ($resolvedStaging.StartsWith($InstallRoot.TrimEnd('\') + '\.install-', [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolvedStaging -Recurse -Force
        }
    }
    if ($lock) { $lock.Dispose() }
}
