# PowerShell script to set up email password
# Run this script and enter your Gmail App Password when prompted

Write-Host "Setting up Gmail App Password for Energy AI Agent" -ForegroundColor Green
Write-Host ""

# Get the App Password from user
$appPassword = Read-Host "Enter your 16-character Gmail App Password" -AsSecureString
$appPasswordPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($appPassword)
)

# Set environment variable for current session
$env:SENDER_PASSWORD = $appPasswordPlain

Write-Host ""
Write-Host "Email password set for this session!" -ForegroundColor Green
Write-Host "To make it permanent, add to your system environment variables:" -ForegroundColor Yellow
Write-Host "  Variable: SENDER_PASSWORD" -ForegroundColor Yellow
Write-Host "  Value: (your app password)" -ForegroundColor Yellow
Write-Host ""
Write-Host "Or edit config.py directly (less secure)" -ForegroundColor Yellow
Write-Host ""
Write-Host "Testing email configuration..." -ForegroundColor Cyan

# Test the configuration
python -c "from alerts import EmailAlertSystem; alert = EmailAlertSystem(); print('Email configured:', alert.is_configured())"
