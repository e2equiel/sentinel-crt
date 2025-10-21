# Sentinel CRT

![Camera View](./docs/camera.png)

![Radar View](./docs/radar.png)

Sentinel CRT is a Python-based monitoring interface designed with a retro, CRT-like aesthetic. It's built to run on a Raspberry Pi connected to a CRT television, providing a heads-up display for real-time events from a [Frigate NVR](https://frigate.video/) instance and nearby air traffic.

## Features

-   **Frigate Integration**: Displays a live RTSP feed from a camera and overlays bounding boxes for detected objects from Frigate's MQTT events.
-   **Dynamic Zoom**: Automatically zooms in on objects of interest (e.g., people, cars) based on their location in defined zones.
-   **Alert Levels**: The interface color theme changes dynamically (Green, Orange, Red) based on the threat level of the zone an object enters.
-   **Aircraft Radar**: Switches to a radar map display when an aircraft is detected overhead, showing its position, callsign, altitude, and route.
-   **CRT Aesthetic**: Uses a retro pixel font (VT323) and visual effects like scanlines and grid overlays to mimic the look of an old terminal.
-   **Highly Configurable**: All settings, from MQTT credentials to alert zones and Mapbox tokens, are managed in a single `config.py` file.

## Hardware Requirements

-   **Raspberry Pi**: A raspberry Pi 3B+ or newer is recommended.
-   **CRT Television/Monitor**: Any CRT with a composite or RF input will work.
-   **HDMI to Composite/RF Adapter**: To connect the Raspberry Pi to the CRT.
-   A running instance of Frigate NVR on your network.
-   (Optional) An ADS-B flight tracking setup that publishes data to your MQTT broker.

## Software Requirements

-   Python 3
-   Pygame
-   OpenCV for Python
-   Paho-MQTT
-   Requests
-   Numpy

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/e2equiel/sentinel-crt.git
cd sentinel-crt
```

### 2. Install Dependencies

It's recommended to use a Python virtual environment.

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Create Configuration File

Copy the example configuration file and edit it with your own settings.
```bash
cp config.py.example config.py
nano config.py
```
You will need to fill in:
-   Your MQTT broker details (`mqtt_host`, `mqtt_user`, `mqtt_password`).
-   Your camera's RTSP URL and Frigate settings (`camera_name`, `camera_rtsp_url`, etc.).
-   Your Frigate alert zones.
-   Your Mapbox account details (`mapbox_user`, `mapbox_token`, etc.) if you want to use the flight radar.
-   Your home latitude and longitude.

### 4. Fonts

The UI uses the `VT323` font and ships with `sentinel/assets/fonts/VT323-Regular.ttf`. If you wish to replace the font, drop the updated file in that directory so the application can load it automatically.

## Running on a Raspberry Pi

### 1. Prepare Raspberry OS

-   Install the latest Raspberry Pi OS Lite (64-bit).
-   Enable Composite Video Output: Edit the `/boot/config.txt` file by running `sudo nano /boot/config.txt`. Add the following lines:

    ```
    # Enable composite video
    enable_tvout=1
    # Set the video mode for CRT & generated a profile for RTC2 (e.g., 640x480 NTSC)
    sdtv_mode=0
    sdtv_aspect=1
    ```
    (Note: `sdtv_mode` can be 0 for NTSC or 2 for PAL. `sdtv_aspect` can be 1 for 4:3).
-   Reboot the Pi.

### 2. Install System Dependencies

You may need to install some system libraries for OpenCV and Pygame to work correctly.
```bash
sudo apt update && sudo apt upgrade
sudo apt install -y git python3 python3-pip python3-venv libatlas-base-dev libavformat-dev \
  libavcodec-dev libswscale-dev libqtgui4 libqt4-test libopenjp2-7 libtiff5 libjpeg-dev \
  libhdf5-dev libopenblas-dev liblapack-dev libxcb1-dev libsdl2-image-2.0-0 libsdl2-mixer-2.0-0 \
  libsdl2-ttf-2.0-0 libportmidi0 libfreetype6-dev libglib2.0-0
```

After installing the packages, create and activate a virtual environment (if you did not already do so during the repository set up) and install the Python dependencies:

```bash
python3 -m venv ~/sentinel-crt/venv
source ~/sentinel-crt/venv/bin/activate
pip install --upgrade pip
pip install -r ~/sentinel-crt/requirements.txt
```

### 3. Follow Installation Steps

Follow steps 1-4 from the main **Installation** section above to clone the repository, install Python packages, configure the app, and confirm that the bundled font is present in `sentinel/assets/fonts/`.

### 4. Run the Application

From within the `sentinel-crt` directory:

```bash
python3 sentinel_crt.py
```

### 5. (Optional) Run on Boot

To make the script run automatically when the Raspberry Pi starts, you can create a simple `systemd` service.

1.  Create a service file:
    ```bash
    sudo nano /etc/systemd/system/sentinel-crt.service
    ```
2.  Paste the following content, making sure to replace `/home/pi/sentinel-crt` with the actual path to the project directory.
    ```ini
    [Unit]
    Description=Sentinel CRT Service
    After=network.target

    [Service]
    ExecStart=/home/pi/sentinel-crt/venv/bin/python /home/pi/sentinel-crt/sentinel_crt.py
    WorkingDirectory=/home/pi/sentinel-crt
    StandardOutput=inherit
    StandardError=inherit
    Restart=always
    User=pi

    [Install]
    WantedBy=multi-user.target
    ```
3.  Enable and start the service:
    ```bash
    sudo systemctl daemon-reload
    sudo systemctl enable sentinel-crt.service
    sudo systemctl start sentinel-crt.service
    ```
You can check its status with `sudo systemctl status sentinel-crt.service`.

## Documentation

Detailed information about built-in modules and services lives under [`docs/modules`](docs/modules) and [`docs/services`](docs/services). Each page explains what the component does, how it is configured, and the events it emits or consumes.

## Home Assistant Flight Radar Integration

Sentinel CRT expects flight data over MQTT on the topic configured in `config.py` (`flight_topic`, default `flights/overhead`). Each message can be a single JSON object or a JSON array of aircraft objects. The application calculates proximity based on your configured `map_latitude` and `map_longitude` and displays the closest aircraft. The following fields are used:

| Field | Required | Description |
|-------|----------|-------------|
| `id` | ✅ | Unique identifier for the aircraft (ICAO hex, call sign + timestamp, etc.). |
| `latitude` / `longitude` | ✅ | Current aircraft position in decimal degrees. |
| `altitude` | ✅ | Altitude in feet. Used for filtering below `min_flight_altitude_ft`. |
| `speed` | ✅ | Ground speed in knots. |
| `track` | ✅ | Heading in degrees (0–359). |
| `callsign` | ✅ | Aircraft call sign. Displayed in the info panel. |
| `model` | ✅ | Aircraft model or type description. |
| `airport_origin_code` | Optional | IATA/ICAO code for the origin airport. |
| `airport_destination_code` | Optional | IATA/ICAO code for the destination airport. |
| `photo` | Optional | HTTPS URL to a square-ish aircraft image. |

### Example Home Assistant Automations

#### Publish a Full Aircraft List from FlightRadar24

The following automation polls the [FlightRadar24 integration](https://www.home-assistant.io/integrations/flightradar24/) every five seconds, builds an array of aircraft dictionaries, and publishes the entire list to `flights/overhead`.

```yaml
alias: Send Aircraft Fleet to CRT Monitor
description: Sends the complete aircraft list to the monitor via MQTT
mode: single
trigger:
  - platform: time_pattern
    seconds: "/5"
condition: []
action:
  - service: mqtt.publish
    data:
      topic: flights/overhead
      retain: false
      payload: >-
        {% set aircraft_list = state_attr('sensor.flightradar24_current_in_area', 'flights') %}
        {% if aircraft_list and aircraft_list | count > 0 %}
          [
          {% for aircraft in aircraft_list %}
            {
              "id": "{{ aircraft.get('id') }}",
              "callsign": "{{ aircraft.get('callsign', 'N/A') }}",
              "altitude": {{ aircraft.get('altitude', 0) }},
              "speed": {{ aircraft.get('ground_speed', 0) }},
              "track": {{ aircraft.get('heading', 0) }},
              "latitude": {{ aircraft.get('latitude', 0) }},
              "longitude": {{ aircraft.get('longitude', 0) }},
              "photo": "{{ aircraft.get('aircraft_photo_small', '') }}",
              "model": "{{ aircraft.get('aircraft_model', '') }}",
              "airport_origin_code": "{{ aircraft.get('airport_origin_code_iata', '') }}",
              "airport_destination_code": "{{ aircraft.get('airport_destination_code_iata', '') }}",
              "airport_origin_name": "{{ aircraft.get('airport_origin_name', '') }}",
              "airport_destination_name": "{{ aircraft.get('airport_destination_name', '') }}"
            }
            {% if not loop.last %},{% endif %}
          {% endfor %}
          ]
        {% else %}
          []
        {% endif %}
```

#### Publish the Nearest Aircraft from ADS-B Exchange

Below is an example automation that publishes the nearest aircraft reported by the [ADS-B Exchange integration](https://www.home-assistant.io/integrations/adsb/) to the MQTT topic `flights/overhead`. Update the sensor/entity names to match your installation.

```yaml
alias: Publish nearest aircraft to Sentinel CRT
mode: single
trigger:
  - platform: state
    entity_id: sensor.adsb_exchange_nearest
  - platform: time_pattern
    minutes: "/1"
variables:
  aircraft: "{{ state_attr('sensor.adsb_exchange_nearest', 'aircraft') or {} }}"
condition:
  - condition: template
    value_template: "{{ aircraft.get('latitude') is not none and aircraft.get('longitude') is not none }}"
action:
  - service: mqtt.publish
    data:
      topic: flights/overhead
      payload: >-
        {{
          [{
            "id": aircraft.get('hex', ''),
            "callsign": aircraft.get('flight', 'UNKNOWN'),
            "model": aircraft.get('type', 'N/A'),
            "latitude": aircraft.get('latitude'),
            "longitude": aircraft.get('longitude'),
            "altitude": aircraft.get('altitude_baro', 0) | int,
            "speed": aircraft.get('ground_speed', 0) | int,
            "track": aircraft.get('track', 0) | int,
            "airport_origin_code": aircraft.get('origin', 'N/A'),
            "airport_destination_code": aircraft.get('destination', 'N/A'),
            "photo": state_attr('sensor.adsb_exchange_nearest', 'image')
          }]
          | tojson
        }}
      qos: 0
      retain: false
```

If you track multiple aircraft, build a list in the `variables` section and publish the entire array. Sentinel CRT will automatically select and highlight the closest aircraft and switch to the radar view when any aircraft remain above `min_flight_altitude_ft`.