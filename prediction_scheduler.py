"""
Prediction Email Scheduler
Sends prediction emails automatically in the morning and evening
"""
import schedule
import time
from datetime import datetime
from prediction_engine import PredictionEngine

class PredictionScheduler:
    """Schedules and sends prediction emails"""
    
    def __init__(self):
        self.engine = PredictionEngine()
    
    def run_and_send_predictions(self):
        """Run prediction pipeline and send emails"""
        print("\n" + "=" * 70)
        print(f"SCHEDULED PREDICTION RUN - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        
        try:
            # Run full pipeline (collects data, generates predictions, sends email)
            predictions = self.engine.run_full_pipeline()
            
            if predictions:
                print("\n[OK] Predictions generated and email sent successfully!")
            else:
                print("\n[!] No predictions generated")
                
        except Exception as e:
            print(f"\n[!] Error in scheduled prediction run: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def start_scheduler(self, morning_time="08:00", evening_time="20:00"):
        """
        Start the scheduler
        Args:
            morning_time: Time to send morning predictions (default 8:00 AM)
            evening_time: Time to send evening predictions (default 8:00 PM)
        """
        print("=" * 70)
        print("PREDICTION EMAIL SCHEDULER")
        print("=" * 70)
        print(f"Morning predictions: {morning_time}")
        print(f"Evening predictions: {evening_time}")
        print()
        print("Scheduled tasks:")
        print(f"  - Every day at {morning_time}: Generate and send predictions")
        print(f"  - Every day at {evening_time}: Generate and send predictions")
        print()
        print("Press Ctrl+C to stop")
        print("=" * 70)
        print()
        
        # Schedule morning predictions
        schedule.every().day.at(morning_time).do(self.run_and_send_predictions)
        
        # Schedule evening predictions
        schedule.every().day.at(evening_time).do(self.run_and_send_predictions)
        
        # Run initial prediction (for testing)
        print("Running initial prediction (test)...")
        self.run_and_send_predictions()
        
        print("\nScheduler started. Waiting for scheduled times...")
        print(f"Next morning run: {morning_time}")
        print(f"Next evening run: {evening_time}")
        print()
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
        except KeyboardInterrupt:
            print("\n\nScheduler stopped by user")

if __name__ == "__main__":
    scheduler = PredictionScheduler()
    
    # Default times: 8:00 AM and 8:00 PM
    # You can customize these times
    scheduler.start_scheduler(
        morning_time="08:00",  # 8:00 AM
        evening_time="20:00"   # 8:00 PM
    )
