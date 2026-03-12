"""
Test Email Configuration
Run this script to test if email alerts are properly configured
"""
from alerts import EmailAlertSystem
from data_collector import EnergyDataCollector
from analyzer import PriceAnalyzer

print("=" * 60)
print("Testing Email Alert Configuration")
print("=" * 60)

alert_system = EmailAlertSystem()

print(f"\nSender Email: {alert_system.sender_email}")
print(f"Recipient Emails: {', '.join(alert_system.recipient_emails)}")
print(f"SMTP Server: {alert_system.smtp_server}:{alert_system.smtp_port}")
print(f"\nEmail Configured: {alert_system.is_configured()}")

if not alert_system.is_configured():
    print("\n" + "=" * 60)
    print("[X] EMAIL NOT CONFIGURED")
    print("=" * 60)
    print("\nTo enable email alerts, you need to:")
    print("1. Get a Gmail App Password:")
    print("   https://myaccount.google.com/apppasswords")
    print("\n2. Set the password using one of these methods:")
    print("\n   Method 1 - Environment Variable (Recommended):")
    print("   PowerShell: $env:SENDER_PASSWORD='your-app-password'")
    print("   CMD: set SENDER_PASSWORD=your-app-password")
    print("\n   Method 2 - Edit config.py directly:")
    print("   Change line 12: 'sender_password': 'your-app-password'")
    print("\n3. Run this test again to verify")
else:
    print("\n" + "=" * 60)
    print("[OK] EMAIL CONFIGURED")
    print("=" * 60)
    print("\nTesting email send...")
    
    # Create a test analysis
    collector = EnergyDataCollector()
    analyzer = PriceAnalyzer()
    
    # Get a price
    price_data = collector.get_crude_oil_price()
    if price_data:
        # Create a test analysis
        analysis = analyzer.analyze_price(price_data)
        
        # Force an alert for testing
        analysis['should_alert'] = True
        current_price = price_data['price']
        previous_price = 90.0
        change_amount = current_price - previous_price
        change_percent = (change_amount / previous_price) * 100
        
        analysis['change_metrics'] = {
            'direction': 'INCREASE',
            'change_percent': change_percent,
            'change_amount': change_amount,
            'previous_price': previous_price,
            'current_price': current_price,
            'is_significant': True
        }
        
        print(f"\nSending test alert for {analysis['product']}...")
        if alert_system.send_alert(analysis):
            print("[OK] Test email sent successfully!")
            print(f"Check your inbox: {alert_system.recipient_emails[0]}")
        else:
            print("[X] Failed to send test email")
            print("Check your App Password and internet connection")
    else:
        print("[X] Could not fetch price data for test")

print("\n" + "=" * 60)
