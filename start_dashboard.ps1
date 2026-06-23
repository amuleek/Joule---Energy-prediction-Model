# Stop anything already on port 8080, then start Joule dashboard
$conns = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conns) {
    Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 1
Set-Location $PSScriptRoot
Write-Host "Starting Joule dashboard -> http://localhost:8080"
python dashboard/app.py
