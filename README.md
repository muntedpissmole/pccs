# The Pissmole Camper Control System

## Overview
The Pissmole Camping Control System (PCCS) is a Raspberry Pi-based control system for managing RV/camper trailer lighting and environmental data. It provides a modern interface featuring:
- Control of dimmable lighting and on/off relays
- Swapping between white and red (anti-bug) modes for channels
- Lighting scenes such as bedtime, bathroom and all off
- Time-of-day phase calculation (day, evening and night) and sunset/sunrise times based on GPS derived co-ordinates
- Reed switch monitoring of panel doors that trigger linked lighting to levels based on time-of-day/phase
- Ambient lighting such as accent and awning that turn on whenever any panel is open
- Protection against turning on lights when panels are closed such as a rooftop tent where the LED strip may be pressed against bedding when the tent is closed
- Comprehensive logging that shows what light turned on, why (e.g. phase change) and what activated it (e.g. scene, reed, user interface)
- A toast/message popup system with helpful information when events happen like GPS fix acquired/lost, phase/lighting level changes (e.g. day -> evening)

The PCCS measures and displays environmental data including:
- GPS derived data & time and sunset/sunrise times based on your coordinates
- Water tank level
- Solar generation
- Battery voltage and State of Charge
- Current temperature and daily min/max weather forecasts for your location
- GPS satellite and quality fix and scraping of closest suburb based on your co-ordinates with offline/no internet fallback

All of this is available from a flexible & scalable UI that can be accessed from any device on your network including touchscreens, tablets and phones and has full support for Cloudflare Tunnels for if your Internet connection is behind cgnat (e.g. Starlink, hotspots).

## Hardware
**Backend**

This project has been built with support for:
- Raspberry Pi
- Arduino Mega 2560 and IRLZ234N mosfets to ramp LEDs and the analog inputs for measuring battery voltage, solar generation and water tank level
- Adafruit Ultimate GPS Breakout PA1616S
- 4 channel 5VDC relay module
- DS18B20 1-wire Temperature Sensor
- fuel level sensor that scales from 240ohm (full) to 33ohm (empty)
- 0-25VDC Voltage divider

**Frontend**

 A touchscreen such as a waveshare powered by another RPI or Rock Pi for more capability in handling the intensive graphics processing.

## UI Examples
#### Desktop/Touchscreen UI
<img src="images/pccs-ipad-landscape.png" alt="The PCCS Desktop/Touchscreen UI" width="100%">

 #### Mobile UI
<img src="images/pccs-iphone-top.png" alt="The PCCS Mobile UI" width="49%"> <img src="images/pccs-iphone-bottom.png" alt="The PCCS Mobile UI" width="49%">

## Wiring
#### Raspberry Pi
| Logical/BCM Pin | Physical Pin | Channel Type           | Description                               |
|:---------------:|:------------:|:-----------------------|:------------------------------------------|
| 4               | 7            | 1-Wire Input           | DS18B20 Temperature Sensor                |
| 8               | 12           | UART TX                | GPS Transmit                              |
| 10              | 8            | UART RX                | GPS Receive                               |
| 17              | 10           | Relay Module Channel 1 | Floodlights                               |
| 18              | 12           | Relay Module Channel 2 | Future Water Circuit (Not in Use)         |
| 22              | 13           | Relay Module Channel 3 | Future Lighting Circuit (Not in Use)      |
| 27              | 15           | Relay Module Channel 4 | Future Fridge & Oven Circuit (Not in Use) |
| 12              | 12           | Reed Input             | Kitchen Bench                             |
| 23              | 16           | Reed Input             | Kitchen Panel                             |
| 24              | 18           | Reed Input             | Storage Panel                             |
| 25              | 22           | Reed Input             | Rear Drawer                               |
| 26              | 37           | Reed Input             | Rooftop Tent                              |
| N/A             | N/A          | USB Port               | Arduino Mega                              |

**Notes**
<small>
- Serial port for GPS communications needs to be enabled in raspi-config
- 5V for peripherals (GPS/relay module etc.) not included in above table
</small>

#### Arduino Mega
**Outputs**
 Pin | Channel Type           | Description                            |
:---:|:-----------------------|:---------------------------------------|
| 2  | PWM/Output             | Kitchen Panel RGBW LED Strip - White   |
| 3  | PWM/Output             | Kitchen Panel RGBW LED Strip - Red     |
| 4  | PWM/Output             | Kitchen Panel RGBW LED Strip - Green   |
| 5  | PWM/Output             | Kitchen Bench LED Strip                |
| 6  | PWM/Output             | Storage Panel LED Strip and Downlights |
| 7  | PWM/Output             | Rear drawer LED Strip                  |
| 8  | PWM/Output             | Accent LED Strips                      |
| 9  | PWM/Output             | Awning RGBW LED Strip - White          |
| 10 | PWM/Output             | Awning RGBW LED Strip - Red            |
| 11 | PWM/Output             | Awning RGBW LED Strip - Green          |
| 12 | PWM/Output             | Rooftop tent LED Strip                 |
| 13 | PWM/Output             | Ensuite tent LED Strip                 |

**Inputs**
 Pin | Channel Type           | Description                            |
:---:|:-----------------------|:---------------------------------------|
| A0 | Analog Input           | Battery Voltage Divider Input          |
| A1 | Analog Input           | Water Level Sensor Input               |
| A2 | Analog Input           | Solar Current Transformer Input        |

**Notes**
<small>
- Arduino Mega is used as RPI PWM/I2C servo driver expansion boards don't have enough power to drive the MOSFETs
- Breadboard circuitboard for MOSFETs and outgoing lighting circuit connections is required
- Breadboard circuitboard for voltage injection of analog sensor inputs is also required
- Blue channels of RGB lights not used in this project due to Arduino channel capacity (Green is used to soften the red)
</small>
