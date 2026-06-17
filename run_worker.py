import time
import sys
from app.agent_core import run_agent_cycle, generate_daily_briefing

# Configuration Windows pulled from environment variables, with defaults
MORNING_HOUR   = int(os.environ.get("MORNING_HOUR", 7))
AFTERNOON_HOUR = int(os.environ.get("AFTERNOON_HOUR", 16))


CHECK_INTERVAL_SECONDS = 600  # Wake up every 10 minutes to check the current time

def main():
    print("==========================================================")
    print("🚀 Starting Production Time-Based Family Agent Worker...")
    print(f"⏰ Active Sweeps: Morning ({MORNING_HOUR}:00) & Afternoon ({AFTERNOON_HOUR}:00)")
    print("==========================================================")
    
    # Tracking variables to ensure we only run ONCE during target hours
    last_morning_run_date = ""
    last_afternoon_run_date = ""
    
    try:
        while True:
            current_struct = time.localtime()
            current_date   = time.strftime('%Y-%m-%d', current_struct)
            current_hour   = current_struct.tm_hour
            current_min    = current_struct.tm_min
            
            print(f"[🕒 Heartbeat {time.strftime('%H:%M', current_struct)}] Checking schedule rules...")
            
            # --- 1. MORNING CYCLE (7:00 AM Window) ---
            if current_hour == MORNING_HOUR and current_date != last_morning_run_date:
                print(f"\n🌅 [{time.strftime('%Y-%m-%d %H:%M:%S')}] Launching Morning Briefing & Sweep...")
                # First generate the calendar brief for your phone
                generate_daily_briefing()
                # Then scan incoming school emails
                run_agent_cycle()
                
                last_morning_run_date = current_date
                print("📋 Morning cycle logged successfully. Returning to standby.")
            
            # --- 2. AFTERNOON CYCLE (4:00 PM Window) ---
            elif current_hour == AFTERNOON_HOUR and current_date != last_afternoon_run_date:
                print(f"\n🌇 [{time.strftime('%Y-%m-%d %H:%M:%S')}] Launching Afternoon Inbox Sweep...")
                # The afternoon loop runs a fresh email target sweep to parse new homework or notes
                run_agent_cycle()
                
                last_afternoon_run_date = current_date
                print("📋 Afternoon cycle logged successfully. Returning to standby.")
                
            # Sleep quietly in the background for 10 minutes before checking the clock again
            time.sleep(CHECK_INTERVAL_SECONDS)
            
    except KeyboardInterrupt:
        print("\n🛑 Worker safely interrupted by user. Shutting down gracefully.")
        sys.exit(0)

if __name__ == "__main__":
    main()
