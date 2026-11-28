$ErrorActionPreference = "Stop"

$hostUriPrefix = "postgresql://postgres.jwevvmvmtckcfgwuthcp:"
$hostUriSuffix = "@aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres"

Write-Host ""
Write-Host "=== KET NOI FASTAPI VOI SUPABASE POSTGRESQL ===" -ForegroundColor Cyan
Write-Host "Host da cau hinh san: aws-1-ap-northeast-1.pooler.supabase.com:5432" -ForegroundColor Gray
Write-Host "(Neu ban quen mat khau DB: vao Supabase -> Settings -> Database -> Reset database password)" -ForegroundColor Yellow
Write-Host ""

$secPwd = Read-Host "Nhap mat khau Database Supabase roi nhan Enter" -AsSecureString
$bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secPwd)
try {
    $plainPwd = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
} finally {
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

if ([string]::IsNullOrWhiteSpace($plainPwd)) {
    Write-Host "LOI: Mat khau khong duoc de trong." -ForegroundColor Red
    exit 1
}

# Allow user to paste either raw password OR full postgresql:// URI
if ($plainPwd.Trim().StartsWith("postgresql://") -or $plainPwd.Trim().StartsWith("postgres://")) {
    $uri = $plainPwd.Trim()
    if ($uri -match "\[YOUR-.*PASSWORD\]") {
        Write-Host "LOI: Ban chua thay [YOUR-DATABASE-PASSWORD] bang mat khau that." -ForegroundColor Red
        exit 1
    }
} else {
    $encodedPwd = [System.Uri]::EscapeDataString($plainPwd.Trim())
    $uri = "$hostUriPrefix$encodedPwd$hostUriSuffix"
}

$envFile = Join-Path $PSScriptRoot "backend\.env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $PSScriptRoot "backend\.env.example") $envFile
}

$lines = Get-Content $envFile
$updated = $false
$newLines = foreach ($line in $lines) {
    if ($line -match "^\s*DATABASE_URL\s*=") {
        $updated = $true
        "DATABASE_URL=$uri"
    } else {
        $line
    }
}
if (-not $updated) {
    $newLines += "DATABASE_URL=$uri"
}
Set-Content -Path $envFile -Value $newLines -Encoding UTF8

Write-Host ""
Write-Host "Dang kiem tra ket noi truc tiep tu FastAPI den Supabase PostgreSQL..." -ForegroundColor Cyan
Push-Location (Join-Path $PSScriptRoot "backend")
try {
    python -c "from app.db.connection import get_connection, is_postgres_connection; c = get_connection(); assert is_postgres_connection(c); print('KET NOI THANH CONG! ->', {'employees': c.execute('SELECT COUNT(*) FROM employees').fetchone()[0], 'attendance': c.execute('SELECT COUNT(*) FROM attendance').fetchone()[0], 'anomalies': c.execute('SELECT COUNT(*) FROM anomalies').fetchone()[0]}); c.close()"
    Write-Host ""
    Write-Host "HOAN TAT! Hay khoi dong lai backend (uvicorn) neu dang chay, sau do kiem tra http://127.0.0.1:8000/api/health" -ForegroundColor Green
} finally {
    Pop-Location
}
