# The Pissmole Camping Control System (PCCS)

## Overview
The Pissmole Camping Control System (PCCS) is a Raspberry Pi-based control system designed to manage camper trailer electronics. It controls dimmable lighting and relays, lighting scenes that can be executed on time of sunset/sunrise offset or fixed times, general purpose relays, GPS for sunset/sunrise/date/time and coordinates calculations, reed switch monitoring for panel doors and drawers and triggering of lighting channels or scenes. It also displys environmental data such as temperature, battery voltage, current time, sunset/sunrise times and water tank level with a user-friendly interface featuring a neomorphism theme with dark and light options.

## Installation
This project has been developed for Raspberry Pi Bookworm. It runs on Flask in a venv.
Confirm Flask and venv modules are installed:
```
sudo apt install python3 python3-venv python3-pip -y
```

Create your folder then create virtual environment:
```
mkdir ~/pccs
cd ~/pccs
python3 -m venv venv
```

Activate virtual environment and install Flask:
```
source venv/bin/activate
pip install flask
```

Copy files to root folder.
Install requirements:
```
pip install -r requirements.txt
```

Run app.py:
```
python3 app.py
```
Or install as a service to start with the RPI.

## Hardware requirements:
### Backend:
- Raspberry Pi
- Arduino Mega 2560 and IRLZ234N mosfets to run your LEDs and the analog inputs for measuring battery voltage and water tank level respectively
- Adafruit Ultimate GPS Breakout PA1616S
- 4 channel 5VDC relay module
- DS18B20 Temperature Sensor
- fuel level sensor that scales from 240ohm (full) to 33ohm (empty)
- 0-25VDC Voltage Detection Module Voltage Sensor

### Front End:
- Waveshare 10.1" 1280 x 800 Touchscreen
- RPI or Rock for powering the touchscren web ui.

### Connections
See config.json for lighting, relay and reed switch connections.
- Battery level sensor: Arduino Mega channel A0.
- Water sensor: Arduino Mega channel A1.
- Solar CT - Arduino Mega channel A2.
- Battery/load CT Vout - Arduino Mega channel A3.
- Battery/load CT Vref - Arduino Mega channel A4.
- Temperature Sensor: Pin 7 on the RPI.
