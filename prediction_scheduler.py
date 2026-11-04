"""
Prediction Email Scheduler
Sends prediction emails automatically (EST timezone)
Schedule: 6:00 AM, 9:00 AM, 10:30 AM, 12:00 PM, 1:30 PM, 6:00 PM EST
"""
import schedule
import time
from datetime import datetime
import pytz
from prediction_engine import PredictionEngine

try:
    from config import INTRADAY_DAY1_CONFIG, SCHEDULER_CONFIG
except ImportError:
    INTRADAY_DAY1_CONFIG = {"check_times": ["10:30", "13:30"]}
    SCHEDULER_CONFIG = {"send_on_startup": False}

class PredictionScheduler:
    """Schedules and sends prediction emails"""
    
    def __init__(self):
        self.engine = PredictionEngine()
        self.est = pytz.timezone('US/Eastern')
        self._run_in_progress = False
    
    def run_and_send_predictions(self):
        """Run prediction pipeline and send emails"""
        if self._run_in_progress:
            print("\n[i] Skipping scheduled run — previous prediction still in progress")
            return
        self._run_in_progress = True
        est_time = datetime.now(self.est)
        print("\n" + "=" * 70)
        print(f"SCHEDULED PREDICTION RUN - {est_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print("=" * 70)
        
        try:
            # Run full pipeline (collects data, generates predictions, sends email)
            predictions = self.engine.run_full_pipeline()
            
            if predictions:
                print("\n[OK] Predictions generated (email sent only if not duplicate)")
            else:
                print("\n[!] No predictions generated")
                
        except Exception as e:
            print(f"\n[!] Error in scheduled prediction run: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            self._run_in_progress = False

    def run_intraday_correction_check(self):
        """Light check: if live tape flipped vs morning email, send CORRECTED."""
        if self._run_in_progress:
            print("\n[i] Skipping intraday check — prediction run in progress")
            return
        self._run_in_progress = True
        est_time = datetime.now(self.est)
        print("\n" + "=" * 70)
        print(f"INTRADAY TAPE CHECK - {est_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print("=" * 70)
        try:
            sent = self.engine.run_intraday_correction()
            if not sent:
                print("\n[i] No intraday correction needed")
        except Exception as e:
            print(f"\n[!] Intraday check error: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            self._run_in_progress = False
    
    def start_scheduler(self, times=None):
        """
        Start the scheduler with 5 daily times (EST)
        Args:
            times: List of times in HH:MM format (default: 6:00 AM, 9:00 AM, 12:00 PM, 6:00 PM EST)
        """
        if times is None:
            times = ["06:00", "09:00", "12:00", "18:00"]  # 6 AM, 9 AM, 12 PM, 6 PM EST
        
        # De-dupe times so the same slot cannot register twice
        times = list(dict.fromkeys(times))
        
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
        print("  - 8:30 PM EST (Sunday only — post-Asia day-1 refresh)")
        for t in INTRADAY_DAY1_CONFIG.get("check_times") or ["10:30", "13:30"]:
            hour = int(t.split(":")[0])
            minute = t.split(":")[1]
            period = "AM" if hour < 12 else "PM"
            display_hour = hour if hour <= 12 else hour - 12
            if display_hour == 0:
                display_hour = 12
            print(f"  - {display_hour}:{minute} {period} EST (intraday tape correction check)")
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
        
        # Schedule all times (once each)
        for time_str in times:
            schedule.every().day.at(time_str).do(self.run_and_send_predictions)

        # Sunday post-Asia refresh: Monday day-1 after Globex/Asia tape (~8:30 PM ET)
        # Skip if 20:30 is already in daily times to avoid double-register on Sundays
        if "20:30" not in times:
            schedule.every().sunday.at("20:30").do(self.run_and_send_predictions)

        # Intraday: correct morning DOWN/UP if live tape gaps >=2% opposite
        for time_str in list(dict.fromkeys(INTRADAY_DAY1_CONFIG.get("check_times") or ["10:30", "13:30"])):
            schedule.every().day.at(time_str).do(self.run_intraday_correction_check)
        
        if SCHEDULER_CONFIG.get("send_on_startup"):
            print("Running initial prediction (startup email enabled)...")
            self.run_and_send_predictions()
        else:
            print(
                "Startup email disabled — predictions run on schedule only "
                "(set SCHEDULER_SEND_ON_STARTUP=true to email on restart)"
            )
        
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
        print(
            "[i] Do not also run `python prediction_engine.py` while this scheduler "
            "is active — use one or the other to avoid duplicate emails."
        )
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
