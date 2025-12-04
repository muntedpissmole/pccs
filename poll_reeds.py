#!/usr/bin/env python3
# reeds.py
# Run this ON THE PI itself – super fast, real-time reed switch monitor
# Uses your existing Flask app's internal state directly (no HTTP!)

import sys
import os
import time
from datetime import datetime

# Add your project path so we can import from modules
sys.path.append('/home/pi/pccs')  # ← change if your project is elsewhere

from app import app as flask_app
from modules.reeds import ReedsController

# Grab the already-running reeds controller instance
# (your app.py creates this globally as `reeds_controller`)
from app import reeds_controller

def clear_screen():
    os.system('clear')

def main():
    print("Local Reed Switch Monitor – reading directly from running system")
    print("Press Ctrl+C to stop\n")
    time.sleep(1.5)

    try:
        while True:
            clear_screen()
            print(f" REED SWITCH STATES  |  {datetime.now().strftime('%H:%M:%S')} ")
            print("-" * 55)

            if not reeds_controller or not reeds_controller.reeds:
                print("No reed switches configured!")
            else:
                for reed_id, button in sorted(reeds_controller.reeds.items()):
                    state = "CLOSED" if button.is_pressed else "OPEN  "
                    color = "\033[92m" if button.is_pressed else "\033[91m"  # Green / Red
                    reset = "\033[0m"
                    nice_name = reed_id.replace('_', ' ').title()
                    print(f"  {nice_name:25} {color}{state}{reset}")

            time.sleep(0.3)  # 3+ updates per second – feels instant

    except KeyboardInterrupt:
        print("\n\nStopped. Bye!")
    except Exception as e:
        print(f"\nError: {e}")
        print("Make sure the Flask app is running first!")

if __name__ == "__main__":
    main()
