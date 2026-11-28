# Run from PowerShell: .\run-demo.ps1. Ctrl+C stops the frontend and owned backend.
$ErrorActionPreference = 'Stop'
$repoDir = $PSScriptRoot
$pythonBin = Join-Path $repoDir 'backend/.venv/Scripts/python.exe'
$nodeBin = Join-Path (Split-Path $repoDir -Parent) '.tools/node-runtime/package/bin/node.exe'
if (-not (Test-Path -LiteralPath $nodeBin)) {
    $nodeBin = (Get-Command node -ErrorAction Stop).Source
}
if (-not (Test-Path -LiteralPath $pythonBin)) { throw 'Create backend/.venv and install requirements first; see docs/FACE_ATTENDANCE.md.' }
$viteBin = Join-Path $repoDir 'frontend/node_modules/vite/bin/vite.js'
if (-not (Test-Path -LiteralPath $viteBin)) { throw 'Run npm install in frontend first.' }
$probe = New-Object System.Net.Sockets.TcpClient
try {
    $connection = $probe.ConnectAsync('127.0.0.1', 8000)
    if ($connection.Wait(300) -and $probe.Connected) { throw 'Port 8000 is already in use. Stop the existing server first.' }
} catch [System.AggregateException] {
    # Connection refused: the port is available.
} finally { $probe.Dispose() }
$logsDir = Join-Path $repoDir '.runtime'
New-Item -ItemType Directory -Force $logsDir | Out-Null
$backendProcess = Start-Process -FilePath $pythonBin -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000' -WorkingDirectory (Join-Path $repoDir 'backend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logsDir 'backend.out.log') -RedirectStandardError (Join-Path $logsDir 'backend.err.log')
$previousDir = Get-Location
try {
    Set-Location (Join-Path $repoDir 'frontend')
    Write-Host 'Demo: http://localhost:5173/face-attendance'
    Write-Host 'HR demo: hr@company.vn / Demo@123 (unless changed). Backend logs: .runtime/'
    & $nodeBin $viteBin --host 127.0.0.1 --port 5173 --strictPort
} finally {
    Set-Location $previousDir
    if (-not $backendProcess.HasExited) { $backendProcess.Kill() }
}
