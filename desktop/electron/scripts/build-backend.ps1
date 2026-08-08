[CmdletBinding()]
param(
    [string]$BuildPython = '',
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$electronRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $electronRoot '..\..')).Path
$runtimeRoot = Join-Path $electronRoot 'runtime\backend'
$cacheRoot = Join-Path $electronRoot '.cache\python'

# Python 3.12.10 is the final 3.12 release with official Windows binary
# installers. Later 3.12 security releases are source-only.
$pythonVersion = '3.12.10'
$archiveName = "python-$pythonVersion-embed-amd64.zip"
$archivePath = Join-Path $cacheRoot $archiveName
$archiveUrl = "https://www.python.org/ftp/python/$pythonVersion/$archiveName"
$expectedSha256 = '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'

$gtkCacheRoot = Join-Path $electronRoot '.cache\gtk'
$gtkInstallerName = 'gtk3-runtime-3.24.31-2022-01-04-ts-win64.exe'
$gtkInstallerPath = Join-Path $gtkCacheRoot $gtkInstallerName
$gtkInstallerUrl = "https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases/download/2022-01-04/$gtkInstallerName"
$gtkInstallerSha256 = 'd05e1488ca0e6ffaabb579bbeb82113c099152ca4260ebc63084b0dd174d4558'
$gtkInstallRoot = Join-Path $gtkCacheRoot 'runtime'

if (-not $BuildPython) {
    $repoVenvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $repoVenvPython) {
        $BuildPython = $repoVenvPython
    }
    else {
        $BuildPython = (Get-Command python.exe -ErrorAction Stop).Source
    }
}
if (-not (Test-Path -LiteralPath $BuildPython)) {
    throw "Build Python was not found: $BuildPython"
}

$frontendDist = Join-Path $repoRoot 'frontend\dist'
if (-not (Test-Path -LiteralPath (Join-Path $frontendDist 'index.html'))) {
    throw 'frontend/dist is missing. Build the production frontend before assembling the runtime.'
}
$requirementsLock = Join-Path $electronRoot 'requirements-windows-lock.txt'
if (-not (Test-Path -LiteralPath $requirementsLock)) {
    throw 'desktop/electron/requirements-windows-lock.txt is missing. Windows packaging requires its platform-specific hash-locked dependencies.'
}

New-Item -ItemType Directory -Path $cacheRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $archivePath)) {
    $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
    if (-not (Test-Path -LiteralPath $curl)) {
        throw 'Windows curl.exe is unavailable.'
    }
    & $curl --fail --location --retry 3 --output $archivePath $archiveUrl
    if ($LASTEXITCODE -ne 0) {
        throw 'Python embeddable package download failed.'
    }
}

$actualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
if ($actualSha256 -ne $expectedSha256) {
    throw "Python archive checksum mismatch. Expected $expectedSha256, got $actualSha256"
}

if ($Clean -and (Test-Path -LiteralPath $runtimeRoot)) {
    $resolvedRuntime = (Resolve-Path -LiteralPath $runtimeRoot).Path
    $allowedRoot = (Resolve-Path -LiteralPath $electronRoot).Path + '\runtime\'
    if (-not $resolvedRuntime.StartsWith($allowedRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean unexpected runtime path: $resolvedRuntime"
    }
    Remove-Item -LiteralPath $resolvedRuntime -Recurse -Force
}

New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
Expand-Archive -LiteralPath $archivePath -DestinationPath $runtimeRoot -Force

$pthPath = Join-Path $runtimeRoot 'python312._pth'
$pthContent = @(
    'python312.zip'
    '.'
    'Lib\site-packages'
    'import site'
) -join [Environment]::NewLine
[IO.File]::WriteAllText(
    $pthPath,
    $pthContent + [Environment]::NewLine,
    [Text.UTF8Encoding]::new($false)
)

$sitePackages = Join-Path $runtimeRoot 'Lib\site-packages'
New-Item -ItemType Directory -Path $sitePackages -Force | Out-Null

# An interrupted setuptools wheel build can leave these ignored directories in
# the source tree. Reusing them causes WinError 183 when the same dist-info
# directory is created again, so remove only these exact, non-reparse paths.
$packagingArtifacts = @(
    (Join-Path $repoRoot 'build'),
    (Join-Path $repoRoot 'agent\vibe_trading_ai.egg-info')
)
function Remove-PackagingArtifact {
    param([Parameter(Mandatory)][string]$ArtifactPath)

    if (-not (Test-Path -LiteralPath $ArtifactPath)) {
        return
    }
    $item = Get-Item -LiteralPath $ArtifactPath -Force
    if ($item.Attributes.HasFlag([IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing to remove packaging artifact through a reparse point: $ArtifactPath"
    }
    $expectedPath = [IO.Path]::GetFullPath($ArtifactPath)
    if (-not $item.FullName.Equals($expectedPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove unexpected packaging artifact: $($item.FullName)"
    }
    Remove-Item -LiteralPath $item.FullName -Recurse -Force
}
foreach ($artifact in $packagingArtifacts) {
    Remove-PackagingArtifact -ArtifactPath $artifact
}

# Install the Windows/Python 3.12 dependency lock with hash verification. The
# lock is generated from agent/requirements.txt on Windows and deliberately
# excludes optional channel extras such as [channels], [weixin], [telegram],
# and [discord].
& $BuildPython -m pip install `
    --disable-pip-version-check `
    --require-hashes `
    --target $sitePackages `
    --requirement $requirementsLock
if ($LASTEXITCODE -ne 0) {
    throw 'Installing hash-locked base dependencies into the embedded runtime failed.'
}

# Install only this checked-out project after its dependency closure has been
# verified above. --no-deps prevents project metadata from re-resolving newer
# packages outside the committed lock.
$installExitCode = 1
try {
    & $BuildPython -m pip install `
        --disable-pip-version-check `
        --no-deps `
        --upgrade `
        --target $sitePackages `
        $repoRoot
    $installExitCode = $LASTEXITCODE
}
finally {
    foreach ($artifact in $packagingArtifacts) {
        Remove-PackagingArtifact -ArtifactPath $artifact
    }
}
if ($installExitCode -ne 0) {
    throw 'Installing Vibe-Trading into the embedded runtime failed.'
}

# Dependency wheels often include test suites that are never imported at
# runtime. Remove only directories named exactly test/tests.
$sitePackagesResolved = (Resolve-Path -LiteralPath $sitePackages).Path
$testDirectories = @(
    Get-ChildItem -LiteralPath $sitePackages -Recurse -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @('test', 'tests') } |
        Sort-Object { $_.FullName.Length }
)
$pruneRoots = [System.Collections.Generic.List[System.IO.DirectoryInfo]]::new()
foreach ($directory in $testDirectories) {
    $coveredByParent = $false
    foreach ($parent in $pruneRoots) {
        if ($directory.FullName.StartsWith($parent.FullName + '\', [StringComparison]::OrdinalIgnoreCase)) {
            $coveredByParent = $true
            break
        }
    }
    if (-not $coveredByParent) {
        $pruneRoots.Add($directory)
    }
}
$reclaimedBytes = 0L
$removedFiles = 0
foreach ($directory in $pruneRoots) {
    $resolved = (Resolve-Path -LiteralPath $directory.FullName).Path
    if (-not $resolved.StartsWith($sitePackagesResolved + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to prune unexpected test directory: $resolved"
    }
    $files = @(Get-ChildItem -LiteralPath $resolved -Recurse -File -Force -ErrorAction SilentlyContinue)
    $reclaimedBytes += ($files | Measure-Object -Property Length -Sum).Sum
    $removedFiles += $files.Count
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
Write-Host ("Pruned {0} packaged test files ({1:N1} MB)" -f $removedFiles, ($reclaimedBytes / 1MB))

# WeasyPrint needs Pango/Cairo/GLib on Windows. Copy only the verified
# rendering dependency closure, not the GTK UI or developer payloads.
New-Item -ItemType Directory -Path $gtkCacheRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $gtkInstallerPath)) {
    Invoke-WebRequest -UseBasicParsing -Uri $gtkInstallerUrl -OutFile $gtkInstallerPath
}
$actualGtkSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $gtkInstallerPath).Hash.ToLowerInvariant()
if ($actualGtkSha256 -ne $gtkInstallerSha256) {
    throw "GTK runtime checksum mismatch. Expected $gtkInstallerSha256, got $actualGtkSha256"
}
$gtkGObject = Join-Path $gtkInstallRoot 'bin\libgobject-2.0-0.dll'
if (-not (Test-Path -LiteralPath $gtkGObject)) {
    New-Item -ItemType Directory -Path $gtkInstallRoot -Force | Out-Null
    $gtkInstall = Start-Process `
        -FilePath $gtkInstallerPath `
        -ArgumentList @('/S', "/D=$gtkInstallRoot") `
        -Wait `
        -PassThru
    if ($gtkInstall.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $gtkGObject)) {
        throw "GTK runtime extraction failed (exit code $($gtkInstall.ExitCode))."
    }
}

$runtimeGtk = Join-Path $runtimeRoot 'gtk'
New-Item -ItemType Directory -Path (Join-Path $runtimeGtk 'bin') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $runtimeGtk 'etc') -Force | Out-Null
$gtkRuntimeDlls = @(
    'libbrotlicommon.dll', 'libbrotlidec.dll', 'libbz2-1.dll', 'libdatrie-1.dll',
    'libexpat-1.dll', 'libffi-7.dll', 'libfontconfig-1.dll', 'libfreetype-6.dll',
    'libfribidi-0.dll', 'libgcc_s_seh-1.dll', 'libgio-2.0-0.dll', 'libglib-2.0-0.dll',
    'libgmodule-2.0-0.dll', 'libgobject-2.0-0.dll', 'libgraphite2.dll',
    'libharfbuzz-0.dll', 'libiconv-2.dll', 'libintl-8.dll', 'libpango-1.0-0.dll',
    'libpangoft2-1.0-0.dll', 'libpcre-1.dll', 'libpng16-16.dll', 'libstdc++-6.dll',
    'libthai-0.dll', 'libwinpthread-1.dll', 'zlib1.dll'
)
foreach ($gtkDll in $gtkRuntimeDlls) {
    Copy-Item `
        -LiteralPath (Join-Path $gtkInstallRoot "bin\$gtkDll") `
        -Destination (Join-Path $runtimeGtk 'bin') `
        -Force
}
Copy-Item `
    -LiteralPath (Join-Path $gtkInstallRoot 'etc\fonts') `
    -Destination (Join-Path $runtimeGtk 'etc') `
    -Recurse `
    -Force

$runtimeFrontend = Join-Path $runtimeRoot 'Lib\frontend\dist'
New-Item -ItemType Directory -Path (Split-Path -Parent $runtimeFrontend) -Force | Out-Null
Copy-Item `
    -LiteralPath $frontendDist `
    -Destination (Split-Path -Parent $runtimeFrontend) `
    -Recurse `
    -Force

Copy-Item `
    -LiteralPath (Join-Path $repoRoot 'LICENSE') `
    -Destination (Join-Path $runtimeRoot 'Vibe-Trading-LICENSE.txt') `
    -Force
Copy-Item `
    -LiteralPath (Join-Path $repoRoot 'NOTICE') `
    -Destination (Join-Path $runtimeRoot 'Vibe-Trading-NOTICE.txt') `
    -Force

$runtimePython = Join-Path $runtimeRoot 'python.exe'
& $BuildPython -m pip --python $runtimePython check
if ($LASTEXITCODE -ne 0) {
    throw 'The embedded runtime does not satisfy the checked-out project dependency metadata.'
}

& {
    $gtkBin = Join-Path $runtimeRoot 'gtk\bin'
    $previousPath = $env:PATH
    $previousDllDirectories = $env:WEASYPRINT_DLL_DIRECTORIES
    try {
        $env:PATH = $gtkBin + [IO.Path]::PathSeparator + $env:PATH
        $env:WEASYPRINT_DLL_DIRECTORIES = $gtkBin
        $smokeScript = @'
import importlib.util
import api_server
import cli
from weasyprint import HTML

assert len(HTML(string="<p>PDF smoke</p>").write_pdf()) > 1000
for optional_module in (
    "dingtalk_stream",
    "discord",
    "telegram",
    "neonize",
    "qrcode",
):
    assert importlib.util.find_spec(optional_module) is None, optional_module
print("embedded backend, PDF, and minimal-adapter checks OK")
'@
        $smokeScript | & $runtimePython -
    }
    finally {
        $env:PATH = $previousPath
        $env:WEASYPRINT_DLL_DIRECTORIES = $previousDllDirectories
    }
}
if ($LASTEXITCODE -ne 0) {
    throw 'Embedded backend import smoke test failed.'
}

$inventoryScript = @'
import importlib.metadata
import json

packages = sorted(
    (
        {"name": dist.metadata["Name"], "version": dist.version}
        for dist in importlib.metadata.distributions()
        if dist.metadata["Name"]
    ),
    key=lambda item: item["name"].lower(),
)
print(json.dumps({"format": "python-importlib-metadata", "packages": packages}, indent=2))
'@
$inventoryJson = $inventoryScript | & $runtimePython -
$inventoryJson |
    Set-Content -LiteralPath (Join-Path $runtimeRoot 'python-dependency-inventory.json') -Encoding utf8

$size = (
    Get-ChildItem -LiteralPath $runtimeRoot -Recurse -File |
        Measure-Object -Property Length -Sum
).Sum
Write-Host ("Backend runtime ready: {0} ({1:N1} MB)" -f $runtimeRoot, ($size / 1MB))
