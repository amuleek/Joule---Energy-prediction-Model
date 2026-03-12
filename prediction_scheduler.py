"""
Prediction Email Scheduler
Sends prediction emails automatically 5 times daily (EST timezone)
Schedule: 6:00 AM, 9:00 AM, 12:00 PM, 6:00 PM EST
"""
import schedule
import time
from datetime import datetime
import pytz
from prediction_engine import PredictionEngine

class PredictionScheduler:
    """Schedules and sends prediction emails"""
    
    def __init__(self):
        self.engine = PredictionEngine()
        self.est = pytz.timezone('US/Eastern')
    
    def run_and_send_predictions(self):
        """Run prediction pipeline and send emails"""
        est_time = datetime.now(self.est)
        print("\n" + "=" * 70)
        print(f"SCHEDULED PREDICTION RUN - {est_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
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
    
    def start_scheduler(self, times=None):
        """
        Start the scheduler with 5 daily times (EST)
        Args:
            times: List of times in HH:MM format (default: 6:00 AM, 9:00 AM, 12:00 PM, 6:00 PM EST)
        """
        if times is None:
            times = ["06:00", "09:00", "12:00", "18:00"]  # 6 AM, 9 AM, 12 PM, 6 PM EST
        
        print("=" * 70)
        print("PREDICTION EMAIL SCHEDULER (EST Timezone)")
        print("=" * 70)
        print("Scheduled times (EST):")
        for t in times:
            hour = int(t.split(':')[0])
            minute = t.split(':')[1]
            period = "AM" if hour < 12 else "PM"
            display_hour = hour if hour <= 12 else hour - 12
            if display_hour == 0:
                display_hour = 12
            print(f"  - {display_hour}:{minute} {period} EST")
        print()
        print("Predictions include:")
        print("  - Daily (Tomorrow)")
        print("  - One Week")
        print("  - Two Weeks")
        print("  - Monthly")
        print()
        print("Press Ctrl+C to stop")
        print("=" * 70)
        print()
        
        # Schedule all times
        for time_str in times:
            schedule.every().day.at(time_str).do(self.run_and_send_predictions)
        
        # Run initial prediction (for testing)
        print("Running initial prediction (test)...")
        self.run_and_send_predictions()
        
        print("\nScheduler started. Waiting for scheduled times...")
        print("Next scheduled runs:")
        for t in times:
            hour = int(t.split(':')[0])
            minute = t.split(':')[1]
            period = "AM" if hour < 12 else "PM"
            display_hour = hour if hour <= 12 else hour - 12
            if display_hour == 0:
                display_hour = 12
            print(f"  - {display_hour}:{minute} {period} EST")
        print()
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
        except KeyboardInterrupt:
            print("\n\nScheduler stopped by user")

if __name__ == "__main__":
    scheduler = PredictionScheduler()
    
    # Schedule: 6:00 AM, 9:00 AM, 12:00 PM, 6:00 PM EST (daily)
    scheduler.start_scheduler(
        times=["06:00", "09:00", "12:00", "18:00"]
    )
