# PowerShell script to set up email password (writes to .env)
# Run: .\setup_email.ps1

$envFile = Join-Path $PSScriptRoot ".env"
$exampleFile = Join-Path $PSScriptRoot ".env.example"

Write-Host "Setting up Gmail App Password for Energy AI Agent" -ForegroundColor Green
Write-Host ""

if (-not (Test-Path $envFile)) {
    if (Test-Path $exampleFile) {
        Copy-Item $exampleFile $envFile
        Write-Host "Created .env from .env.example" -ForegroundColor Yellow
    } else {
        Write-Host "Missing .env and .env.example - create .env first." -ForegroundColor Red
        exit 1
    }
}

$appPassword = Read-Host "Enter your 16-character Gmail App Password" -AsSecureString
$appPasswordPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($appPassword)
).Replace(" ", "")

# Store with spaces (Gmail format) - config.py strips them on load
$appPasswordFormatted = ($appPasswordPlain -replace '(.{4})', '$1 ').Trim()

$content = Get-Content $envFile -Raw
if ($content -match '(?m)^SENDER_PASSWORD=.*') {
    $content = $content -replace '(?m)^SENDER_PASSWORD=.*', "SENDER_PASSWORD=$appPasswordFormatted"
} else {
    $content = "SENDER_PASSWORD=$appPasswordFormatted`r`n" + $content
}
if ($content -notmatch '(?m)^SENDER_EMAIL=') {
    $content = "SENDER_EMAIL=amuleeksidhu96@gmail.com`r`n" + $content
}

Set-Content -Path $envFile -Value $content.TrimEnd()

Write-Host ""
Write-Host "Saved to .env (SENDER_PASSWORD updated)" -ForegroundColor Green
Write-Host "Testing email send..." -ForegroundColor Cyan

$testScript = Join-Path $PSScriptRoot 'test_prediction_email.py'
python $testScript
