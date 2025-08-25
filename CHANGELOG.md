# Changelog

## 1.5.0-beta 2 build 25082025-0800

### Added & Changed
- 

### Fixed
- Screen brightness will be evaulated and re-sent when the screen wakes up as sending the brightness when the screen was asleep had no effect
- When opening the kitchen panel after lighting levels have changed, the page now refreshes to update UI

## 1.5.0-beta 2 build 21082025-1900

### Added & Changed
- Added configurable times for sunset offset and nighttime to settings -> general tab
- Removed scene editor button until work starts on it

### Fixed
- All Off scene now auto sets 1 hour after sunrise, not sunset

### Known Issues
- Manually triggering evening and night scenes from the scene buttons won't ramp the kitchen panel lights

## 1.5.0-beta 2 build 18082025-1900

### Added & Changed
- Evening and night scenes will auto apply on time boundary crossing if the kitchen panel is open (to show that the camper system is in use)

## 1.5.0-beta 2 build 14082025-2000

### Added & Changed
- Refined lighting scenes
- Added event to turn off all lights 1 hour after sunset
- Refined reed switch events to check if evening or night scenes are active and will apply those lighting levels if true (time based logic is still active)
- If the RPI loses comms with the arduino it will periodically try to re-establish comms rather than wait for an app restart
- If the kitchen panel is open and sunset-1hr occurs, set the evening scene. If the evening scene is active and nighttime occurs, set the night scene

## 1.5.0-beta 2 build 04082025-1900

### Added & Changed
- Started planning UI for 5" tent touchscreen
- Added support for kitchen bench reed
- Refined reed switch events
- Refined scene components
- Refined timing between lighting ramps for setting Scenes
- Updated requirements.txt

### Fixed
- Reed switches now always turn off their associated lights when closed
- Kitchen reed events depended on kitchen touchscreen successfully receiving SSH sleep command for some reason

## 1.5.0-beta 2 build 19072025-1430

### Added & Changed
- Removed PCA9685 board and replaced with Arduino mega for mosfet/gate driving capabilities
- Updated code to suit Arduino USB connection
- Implemented reed switch logic
- Back end refinements
- Green LED channel follows red channel level at a multiplier of 0.1 to get a nice red-orange hue
- Added Ardunio sketch to repo
- Updated requirements.txt

### Fixed
- Lighting channels now ramp silky smooth
- Scenes trigger each channel (almost) at the same time and the sliders ramp in sync with their channel levels
- Squished all communications issues between RPI and Arduino
- Removed reed switch writes to config.json as it's redundant

## 1.4.0-beta 1 build 22062025-1445

### Added & Changed
Moved scripts from index.html to script.js
Bug Fixes

## 1.4.0-beta 1 build 19062025-1705

### Added & Changed
Added option to dim brightness at night

### Fixed
- Auto theme does theme check on page load

## 1.4.0-beta 1 build 18062025-2300

### Added & Changed
- Shutdown and setting low/medium/high brightness on remote display
- Turning remote screen off and on based on state of kitchen panel reed switch (where the touchscreen lives, no point in having it on if the panel is shut)
- Improved handling of missing PCA9685 board by disabling lighting faders and scenes, displaying error text on percentage level
- Made temperature and battery voltage display the same error text and water tank level
- Moved version to Help/About settings tab, also shows your current coordinates
- Changed brightness level from slider to low/medium/high buttons to work in with limitations of Waveshare touchscreen brightness commands
- Implement overscroll for lighting pages
- Imrpovement of lighting slider thumbs
- Somehow gave the lighting widgets even more delicious neumorphism

### Fixed
- Scene active styles weren't showing when a scene was active due to relay_states function being accidentally deleted from app.py
- You can no longer select text when swiping left and right

---