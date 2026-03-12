"""
Test sending prediction email to all recipients
"""
from prediction_engine import PredictionEngine
from config import EMAIL_CONFIG

print("=" * 70)
print("TESTING PREDICTION EMAIL")
print("=" * 70)
print()
print("Email Configuration:")
print(f"  Sender: {EMAIL_CONFIG['sender_email']}")
print("  Recipients:")
for email in EMAIL_CONFIG['recipient_emails']:
    print(f"    - {email.strip()}")
print()

# Load existing predictions
import json
import os

if os.path.exists("data/predictions.json"):
    with open("data/predictions.json", 'r') as f:
        predictions = json.load(f)
    
    print("Sending prediction email...")
    engine = PredictionEngine()
    engine.send_prediction_email(predictions)
    print()
    print("=" * 70)
    print("Email sent! Check inboxes:")
    for email in EMAIL_CONFIG['recipient_emails']:
        print(f"  - {email.strip()}")
else:
    print("No predictions found. Run: python prediction_engine.py")
    print("Then run this script again.")
