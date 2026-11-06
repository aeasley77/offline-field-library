$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$packages = Join-Path $root 'app\runtime\packages'
$cacheRoot = Join-Path $env:LOCALAPPDATA 'OfflineFieldLibrary'
$runtimeRoot = Join-Path $cacheRoot 'runtime\windows-x64'
$pythonArchive = Join-Path $packages 'python-windows-x64.zip'
$python = Join-Path $runtimeRoot 'python\python.exe'
$kiwixArchive = Join-Path $packages 'kiwix-windows-x64.zip'
$kiwixRoot = Join-Path $cacheRoot 'kiwix\windows-x64'
$kiwix = Join-Path $kiwixRoot 'kiwix-serve.exe'
$appDir = Join-Path $root 'app'
$dashboardUrl = 'http://127.0.0.1:8765'
$kiwixProcess = $null
$dashboardProcess = $null
$alreadyRunning = $false
$existing = [System.Net.Sockets.TcpClient]::new()
try {
    $existing.Connect('127.0.0.1', 8765)
    $alreadyRunning = $true
} catch {
} finally {
    $existing.Dispose()
}
if ($alreadyRunning) {
    Start-Process $dashboardUrl
    return
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    if (-not (Test-Path -LiteralPath $pythonArchive -PathType Leaf)) { throw "Python archive missing: $pythonArchive" }
    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    Expand-Archive -LiteralPath $pythonArchive -DestinationPath $runtimeRoot -Force
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Portable Python did not unpack correctly.' }

if (-not (Test-Path -LiteralPath $kiwix -PathType Leaf) -and (Test-Path -LiteralPath $kiwixArchive -PathType Leaf)) {
    New-Item -ItemType Directory -Path $kiwixRoot -Force | Out-Null
    Expand-Archive -LiteralPath $kiwixArchive -DestinationPath $kiwixRoot -Force
}
if (Test-Path -LiteralPath $kiwixRoot -PathType Container) { $env:PATH = $kiwixRoot + ';' + $env:PATH }
if (-not (Test-Path -LiteralPath (Join-Path $root 'content'))) {
    throw 'The content folder was not found. Run this launcher from the library SSD.'
}

try {
    $zim = Get-ChildItem -LiteralPath (Join-Path $root 'content') -Filter '*.zim' -File -Recurse |
        Where-Object { $_.Name -notlike '._*' -and $_.Name -notlike '.*' } |
        Select-Object -First 1
    if ($zim -and (Test-Path -LiteralPath $kiwix -PathType Leaf)) {
        $zimArg = '"' + $zim.FullName + '"'
        $kiwixArgs = @('--address=127.0.0.1', '--port=8081', $zimArg)
        $kiwixProcess = Start-Process -FilePath $kiwix -ArgumentList $kiwixArgs -WorkingDirectory $kiwixRoot -WindowStyle Hidden -PassThru
    }

    $dashboardProcess = Start-Process -FilePath $python -ArgumentList @('server.py') -WorkingDirectory $appDir -NoNewWindow -PassThru
    $ready = $false
    for ($i = 0; $i -lt 600; $i++) {
        if ($dashboardProcess.HasExited) { throw 'The dashboard server stopped during startup. Check that port 8765 is available.' }
        $client = [System.Net.Sockets.TcpClient]::new()
        try {
            $client.Connect('127.0.0.1', 8765)
            $ready = $true
            break
        } catch {
            Start-Sleep -Milliseconds 500
        } finally {
            $client.Dispose()
        }
    }
    if (-not $ready) { throw 'The dashboard did not start on port 8765. Check that the port is available.' }
    Start-Process $dashboardUrl
    Write-Host 'Offline Field Library is running. Press Ctrl+C in this window to stop it.'
    Wait-Process -Id $dashboardProcess.Id
} finally {
    if ($dashboardProcess -and -not $dashboardProcess.HasExited) {
        Stop-Process -Id $dashboardProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($kiwixProcess -and -not $kiwixProcess.HasExited) {
        Stop-Process -Id $kiwixProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
