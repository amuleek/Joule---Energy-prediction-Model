@echo off
REM Batch script to set up email password
REM Run this script and enter your Gmail App Password when prompted

echo Setting up Gmail App Password for Energy AI Agent
echo.

set /p APP_PASSWORD="Enter your 16-character Gmail App Password: "

REM Set environment variable
set SENDER_PASSWORD=%APP_PASSWORD%

echo.
echo Email password set for this session!
echo To make it permanent, add SENDER_PASSWORD to your system environment variables
echo.
echo Testing email configuration...

python -c "from alerts import EmailAlertSystem; alert = EmailAlertSystem(); print('Email configured:', alert.is_configured())"

pause
