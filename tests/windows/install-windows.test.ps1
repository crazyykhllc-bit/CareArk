param([string]$InstallerPath, [string]$FixtureRoot)
$ErrorActionPreference = 'Stop'
$global:CareArkTestTag = 'v0.1.2'
$global:CareArkTestCorruptChecksum = $false
$global:CareArkTestArchiveDownloads = 0
function Invoke-RestMethod {
    param($Uri, $Headers, $TimeoutSec)
    $prefix = 'https://github.com/crazyykhllc-bit/CareArk/releases/download/' + $global:CareArkTestTag + '/'
    return @{ tag_name = $global:CareArkTestTag; draft = $false; prerelease = $false; assets = @(
        @{name = ('CareArk-Windows-' + $global:CareArkTestTag + '.zip'); browser_download_url = ($prefix + 'CareArk-Windows-' + $global:CareArkTestTag + '.zip')},
        @{name = 'SHA256SUMS.txt'; browser_download_url = ($prefix + 'SHA256SUMS.txt')}
    ) }
}
function Invoke-WebRequest {
    param([switch]$UseBasicParsing, $Uri, $Headers, $OutFile, $TimeoutSec)
    if ($Uri.EndsWith('SHA256SUMS.txt')) {
        if ($global:CareArkTestCorruptChecksum) {
            (('0' * 64) + '  CareArk-Windows-' + $global:CareArkTestTag + '.zip') | Set-Content -LiteralPath $OutFile -Encoding ASCII
        } else {
            Copy-Item -LiteralPath (Join-Path $FixtureRoot ($global:CareArkTestTag + '-SHA256SUMS.txt')) -Destination $OutFile
        }
    } else {
        $global:CareArkTestArchiveDownloads++
        Copy-Item -LiteralPath (Join-Path $FixtureRoot ('CareArk-Windows-' + $global:CareArkTestTag + '.zip')) -Destination $OutFile
    }
}
function Assert($Condition, $Message) { if (-not $Condition) { throw $Message } }
$install = Join-Path $FixtureRoot 'programs with spaces'
$desktop = Join-Path $FixtureRoot 'desktop'
New-Item -ItemType Directory -Path $desktop | Out-Null
& $InstallerPath -InstallRoot $install -DesktopDirectory $desktop
$firstVersion = Join-Path $install 'versions\v0.1.2'
Assert (Test-Path -LiteralPath (Join-Path $firstVersion '_internal\alembic\env.py')) 'migration script missing'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $desktop 'CareArk.lnk'))
Assert ($shortcut.TargetPath -eq (Join-Path $firstVersion 'CareArk.exe')) 'shortcut targets wrong executable'
[Runtime.InteropServices.Marshal]::FinalReleaseComObject($shortcut) | Out-Null
Set-Content -LiteralPath (Join-Path $firstVersion 'marker.txt') -Value 'preserved'
& $InstallerPath -InstallRoot $install -DesktopDirectory $desktop
Assert ($global:CareArkTestArchiveDownloads -eq 1) 'same version was downloaded twice'
Assert ((Get-Content -LiteralPath (Join-Path $firstVersion 'marker.txt')) -eq 'preserved') 'same version was overwritten'

$global:CareArkTestTag = 'v0.1.3'
$global:CareArkTestCorruptChecksum = $true
$failed = $false
try { & $InstallerPath -InstallRoot $install -DesktopDirectory $desktop } catch {
    Assert ($_.Exception.Message -match 'SHA256 verification failed') 'unexpected failure'
    $failed = $true
}
Assert $failed 'checksum mismatch was accepted'
Assert (-not (Test-Path -LiteralPath (Join-Path $install 'versions\v0.1.3'))) 'bad download was installed'
$shortcut = $shell.CreateShortcut((Join-Path $desktop 'CareArk.lnk'))
Assert ($shortcut.TargetPath -eq (Join-Path $firstVersion 'CareArk.exe')) 'failed update changed shortcut'
[Runtime.InteropServices.Marshal]::FinalReleaseComObject($shortcut) | Out-Null

$global:CareArkTestCorruptChecksum = $false
& $InstallerPath -InstallRoot $install -DesktopDirectory $desktop
$shortcut = $shell.CreateShortcut((Join-Path $desktop 'CareArk.lnk'))
Assert ($shortcut.TargetPath -eq (Join-Path $install 'versions\v0.1.3\CareArk.exe')) 'upgrade shortcut did not change'
[Runtime.InteropServices.Marshal]::FinalReleaseComObject($shortcut) | Out-Null
[Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null
Assert (Test-Path -LiteralPath (Join-Path $firstVersion 'marker.txt')) 'upgrade removed old program'
Assert (@(Get-ChildItem -LiteralPath $install -Directory | Where-Object Name -like '.install-*').Count -eq 0) 'staging not cleaned'

$failed = $false
try { & $InstallerPath -InstallRoot (Join-Path $env:LOCALAPPDATA 'CareArk') -NoShortcut } catch {
    Assert ($_.Exception.Message -match 'outside the CareArk data directory') 'wrong data directory failure'
    $failed = $true
}
Assert $failed 'installer accepted data directory'
Write-Output 'INSTALLER_TESTS_OK'
