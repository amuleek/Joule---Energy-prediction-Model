"""Test script to verify email content"""
from email_formatter import PredictionEmailFormatter
import json

# Load predictions
with open('data/predictions.json', 'r') as f:
    predictions = json.load(f)

# Generate HTML
formatter = PredictionEmailFormatter()
html = formatter.format_email_html(predictions, None)

# Check for product cards
import re
product_cards = re.findall(r'<div class="product-card">', html)
print(f"Number of product cards: {len(product_cards)}")

# Check for each product
products = ['RBOB Gasoline', 'Ultra-Low Sulfur Diesel', 'Crude Oil']
for product in products:
    found = product in html
    print(f"{product}: {'[OK] Found' if found else '[MISSING]'}")

# Show a sample of the HTML
print("\n" + "="*60)
print("Sample HTML (showing first product card):")
print("="*60)
start = html.find('<div class="product-card">')
if start != -1:
    end = start + 1000
    print(html[start:end])
else:
    print("No product cards found in HTML!")
