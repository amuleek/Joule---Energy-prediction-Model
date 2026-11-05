"""
Quick test script to send prediction email immediately
"""
from prediction_engine import PredictionEngine
from config import EMAIL_CONFIG

print("=" * 70)
print("SENDING TEST PREDICTION EMAIL")
print("=" * 70)
print()
print("Recipients:")
for email in EMAIL_CONFIG['recipient_emails']:
    print(f"  - {email.strip()}")
print()

# Generate fresh predictions and send once (generate_predictions already emails)
engine = PredictionEngine()
predictions = engine.run_full_pipeline()

if predictions:
    print()
    print("=" * 70)
    print("Test email sent successfully!")
    print("Check inboxes for prediction email.")
    print("=" * 70)
else:
    print("No predictions generated. Run full pipeline first:")
    print("  python prediction_engine.py")
