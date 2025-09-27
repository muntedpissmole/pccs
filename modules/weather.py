# modules/weather.py
import glob
import time
import requests
import logging

logger = logging.getLogger(__name__)

class WeatherController:
    def __init__(self, on_event=None):
        self.on_event = on_event or (lambda event, data: None)
        base_dir = '/sys/bus/w1/devices/'
        try:
            self.device_folder = glob.glob(base_dir + '28*')[0]
            self.device_file = self.device_folder + '/w1_slave'
            self.available = True
            logger.info("Temperature sensor available")
        except IndexError:
            self.available = False
            logger.warning("Temperature sensor not found")
        except Exception as e:
            self.available = False
            logger.error(f"Error initializing temperature sensor: {e}")
        self.previous_temp_failed = False
        self.previous_fetch_failed = False
        self.previous_was_rainy = False
        if not self.available:
            self.on_event('show_toast', {'warning': 'Temperature sensor not available'})

    def read_temp_raw(self):
        try:
            with open(self.device_file, 'r') as f:
                return f.readlines()
        except Exception as e:
            logger.error(f"Error reading raw temp: {e}")
            return []

    def read_temp(self):
        if not self.available:
            return None
        try:
            lines = self.read_temp_raw()
            while lines[0].strip()[-3:] != 'YES':
                time.sleep(0.2)
                lines = self.read_temp_raw()
            equals_pos = lines[1].find('t=')
            if equals_pos != -1:
                temp_string = lines[1][equals_pos+2:]
                temp_c = float(temp_string) / 1000.0
                return temp_c
            else:
                return None
        except IndexError:
            logger.warning("Invalid temp lines format")
            return None
        except Exception as e:
            logger.error(f"Error reading temp: {e}")
            return None

    def get_weather_data(self, lat, lon):
        weather_data = {
            'temp_C': '--',
            'condition': 'Unknown',
            'min_temp_C': '--',
            'max_temp_C': '--',
            'humidity': '--',
        }
        # Read local temperature sensor
        temp_c = self.read_temp()
        if temp_c is not None:
            weather_data['temp_C'] = '{:.1f}'.format(temp_c)
            if self.previous_temp_failed:
                self.previous_temp_failed = False
                logger.info("Temperature sensor recovered")
        else:
            if not self.previous_temp_failed:
                self.on_event('show_toast', {'message': 'Failed to read temperature sensor', 'type': 'warning'})
                self.previous_temp_failed = True
                logger.warning("Failed to read temperature sensor")

        # Fetch other weather data from wttr.in
        fetch_failed = False
        try:
            weather_url = f"https://wttr.in/{lat:.2f},{lon:.2f}?format=j1"
            weather_res = requests.get(weather_url, headers={'User-Agent': 'curl/7.79.1'}).json()
            current = weather_res['current_condition'][0]
            today = weather_res['weather'][0]
            weather_data['condition'] = current['weatherDesc'][0]['value']
            weather_data['min_temp_C'] = today['mintempC']
            weather_data['max_temp_C'] = today['maxtempC']
            weather_data['humidity'] = current['humidity']
            if self.previous_fetch_failed:
                self.previous_fetch_failed = False
                logger.info("Weather fetch recovered")
            # Check for rain
            condition_lower = weather_data['condition'].lower()
            is_rainy = any(term in condition_lower for term in ['rain', 'shower', 'thunder'])
            if is_rainy != self.previous_was_rainy:
                if is_rainy:
                    self.on_event('show_toast', {'message': 'Rain expected', 'type': 'warning'})
                self.previous_was_rainy = is_rainy
                logger.debug(f"Rain status changed to {is_rainy}")
        except requests.RequestException as e:
            fetch_failed = True
            logger.error(f"Weather fetch error: {e}")
        except KeyError as e:
            fetch_failed = True
            logger.error(f"Invalid weather response format: {e}")
        except Exception as e:
            fetch_failed = True
            logger.error(f"Unexpected error in weather fetch: {e}")
        if fetch_failed and not self.previous_fetch_failed:
            self.on_event('show_toast', {'message': 'Weather fetch failed', 'type': 'warning'})
            self.previous_fetch_failed = True
            logger.warning("Weather fetch failed")

        return weather_data