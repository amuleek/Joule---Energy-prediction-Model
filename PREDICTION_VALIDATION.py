"""
Prediction Validation - Checks for unrealistic predictions
"""
import json
import math

def validate_predictions(predictions_file="data/predictions.json"):
    """Validate predictions for realism"""
    with open(predictions_file, 'r') as f:
        predictions = json.load(f)
    
    warnings = []
    
    # Reasonable bounds for energy prices
    MAX_DAILY_CHANGE = 5.0  # 5% max daily change
    MAX_WEEKLY_CHANGE = 10.0  # 10% max weekly change
    MAX_MONTHLY_CHANGE = 20.0  # 20% max monthly change
    
    for product, pred in predictions.items():
        if not pred:
            continue
        
        current_price = pred.get('current_price', 0)
        if current_price <= 0:
            warnings.append(f"{product}: Invalid current price ({current_price})")
            continue
        
        # Check each time horizon
        horizons = [
            ('next_day', 'Daily', MAX_DAILY_CHANGE),
            ('next_week', 'Weekly', MAX_WEEKLY_CHANGE),
            ('biweekly', 'Biweekly', MAX_WEEKLY_CHANGE * 1.5),
            ('monthly', 'Monthly', MAX_MONTHLY_CHANGE)
        ]
        
        for horizon_key, horizon_name, max_change in horizons:
            horizon_data = pred.get(horizon_key, {})
            if not horizon_data:
                continue
            
            change_pct = abs(horizon_data.get('change_percent', 0))
            
            if math.isnan(change_pct):
                warnings.append(f"{product} {horizon_name}: NaN change percentage")
            elif change_pct > max_change:
                warnings.append(
                    f"{product} {horizon_name}: UNREALISTIC prediction - "
                    f"{change_pct:.2f}% change (max reasonable: {max_change}%)"
                )
    
    return warnings

if __name__ == "__main__":
    warnings = validate_predictions()
    if warnings:
        print("[WARNING] PREDICTION VALIDATION WARNINGS:")
        print("=" * 60)
        for warning in warnings:
            print(f"  • {warning}")
        print("=" * 60)
        print("\n[WARNING] These predictions may be unreliable due to:")
        print("  • Limited historical data")
        print("  • Model overfitting")
        print("  • Data quality issues")
    else:
        print("[OK] All predictions within reasonable bounds")
