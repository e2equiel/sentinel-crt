import pygame
import sys
import time
import paho.mqtt.client as mqtt
import threading
import json
import cv2
import numpy as np
from datetime import datetime
import random
from collections import deque
import requests
import io
import math
import traceback

# Import configuration from the separate config file
import config

from sentinel.config import load_configuration
from sentinel.core import ModuleManager
from sentinel.modules.common import draw_diagonal_pattern

from neo_tracker import NEOTracker
from eonet_tracker import EONETTracker

# --- Constants ---
# Colors are defined in the config file now for easier theme management.
# We can keep them here if they are static, but moving them to config.py is also an option.
COLOR_BLACK = (0, 0, 0)



# --- Helper Functions ---
def calculate_zoom_from_radius(radius_m, map_width_px, latitude):
    """Calculates the Mapbox zoom level for a given radius and screen width."""
    if radius_m <= 0 or map_width_px <= 0: return 10
    EARTH_CIRCUMFERENCE_M = 40075017
    meters_per_pixel = (radius_m * 2) / map_width_px
    zoom_level = math.log2((EARTH_CIRCUMFERENCE_M * math.cos(math.radians(latitude))) / (256 * meters_per_pixel))
    return int(round(zoom_level))

def deg2num(lat_deg, lon_deg, zoom):
  """Converts lat/lon to tile numbers."""
  lat_rad = math.radians(lat_deg)
  n = 2.0 ** zoom
  xtile = int((lon_deg + 180.0) / 360.0 * n)
  ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
  return (xtile, ytile)

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculates the distance between two lat/lon points in kilometers."""
    R = 6371 # Earth radius in km
    dLat, dLon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dLat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dLon/2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))

class SentinelApp:
    def __init__(self):
        """
        Initialize the SentinelApp instance and start core UI state, background services, and modules.
        
        This constructor initializes Pygame and the display (fullscreen or windowed per configuration), loads runtime configuration and theme colors into the global config, configures fonts, and sets up all application state (UI regions, detection/alert state, zoom state, visual effect parameters, flight and map placeholders). It creates and starts periodic NASA trackers (NEO and EONET), initializes the ASCII globe visualization, prepares tiled pattern and graph resources, starts the MQTT client and video capture threads, and loads any configured modules via ModuleManager and selects the initial active screen. If the startup screen is the radar, a background thread is launched to preload map tiles.
        
        The constructor may exit the process if required fonts cannot be loaded.
        """
        pygame.init()

        self.settings = load_configuration()
        self.core_settings = dict(self.settings.core)

        if hasattr(config, "CONFIG") and isinstance(config.CONFIG, dict):
            config.CONFIG.update(self.core_settings)
        else:
            config.CONFIG = dict(self.core_settings)

        base_theme = getattr(config, "THEME_COLORS", {})
        if not isinstance(base_theme, dict):
            base_theme = {}
        self.theme_colors = dict(base_theme)
        self.theme_colors.update(self.settings.theme_colors)
        config.THEME_COLORS = self.theme_colors

        fullscreen = self.core_settings.get("fullscreen", True)
        if fullscreen:
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            width = self.core_settings.get("screen_width", 640)
            height = self.core_settings.get("screen_height", 480)
            self.screen = pygame.display.set_mode((width, height))

        pygame.mouse.set_visible(False)
        self.clock = pygame.time.Clock()

        try:
            self.font_large = pygame.font.Font('VT323-Regular.ttf', 24)
            self.font_medium = pygame.font.Font('VT323-Regular.ttf', 20)
            self.font_small = pygame.font.Font('VT323-Regular.ttf', 16)
            self.font_tiny = pygame.font.Font('VT323-Regular.ttf', 12)
        except pygame.error as e:
            print(f"Error loading font VT323-Regular.ttf: {e}")
            print("Please make sure the font file is in the same directory as the script.")
            sys.exit()

        self.running = True
        self.data_lock = threading.RLock()
        self.reset_pending = False
        
        # Application States
        self.current_screen = None
        self.mqtt_status = "CONNECTING..."
        self.video_status = "INITIALIZING"
        self.current_video_frame = None
        self.map_surface = None
        self.map_status = "NO DATA"
        
        self.detection_buffer = deque()
        self.active_detections = {}
        self.last_event_time = "--"
        self.target_label = "--"
        self.target_score = "--"
        self.snapshot_surface = None
        self.mqtt_activity = 0.0 

        # Alert State
        self.alert_level = "none" # none, warning, danger
        self.current_theme_color = self.theme_colors['default']
        self.header_title_text = "S.E.N.T.I.N.E.L. v1.0"

        # Flight Data
        self.active_flights = []
        self.closest_flight = None
        self.closest_flight_photo_surface = None
        self.last_closest_flight_id = None
        self.flight_screen_timer = 0
        self.map_center_tile = (0,0)
        self.map_tile_offset = (0,0)
        self.map_width_tiles = 0
        self.map_height_tiles = 0
        self.map_zoom_level = 0 # Will be calculated dynamically

        # Zoom State
        src_w, src_h = config.CONFIG["frigate_resolution"]
        self.is_zoomed = False
        self.show_zoom_grid = False
        self.zoom_target_rect = pygame.Rect(0, 0, src_w, src_h)
        self.current_zoom_rect = self.zoom_target_rect.copy()
        self.zoom_reset_timer = 0
        
        # Visual Effects
        self.scanner_pos = 0; self.scanner_dir = 2; self.spinner_angle = 0
        self.sys_load_string = "000000"; self.sys_load_update_timer = 0
        self.level_bars_heights = [random.randint(2, 18) for _ in range(5)]; self.level_bars_update_timer = 0
        self.pattern_phase = 0.0
        self.pattern_speed_px_s = 10.0

        # NASA APIs
        self.neo_tracker = NEOTracker(config.CONFIG["nasa_api_key"])
        self.neo_tracker.start_periodic_fetch(interval_hours=6)
        
        self.eonet_tracker = EONETTracker()
        self.eonet_tracker.start_periodic_fetch(interval_hours=1)

        # Screen Cycling
        priorities_idle = self.settings.priorities.get("idle", {}) if isinstance(self.settings.priorities, dict) else {}
        idle_cycle = priorities_idle.get("cycle") if isinstance(priorities_idle, dict) else None
        if idle_cycle:
            self.idle_screen_list = list(idle_cycle)
        else:
            self.idle_screen_list = config.CONFIG.get("idle_screen_list", ["camera", "neo_tracker"])
        
        # NEO & Globe Screen state
        self.sphere_rotation_angle = 0
        self.globe_rotation_angle = 0  # For EONET
        self.planet_angles = [random.uniform(0, 2 * math.pi) for _ in range(4)]
        self.asteroid_path_progress = 0.0
        
        self.calculate_layout()
        
        # Grid and Graph Resources
        self.grid_cell_size = 40
        self.patterns_green = {
            'dots': self.create_tiled_pattern_surface('dots', self.grid_cell_size, self.theme_colors['default'] + (160,)),
            'lines': self.create_tiled_pattern_surface('lines', self.grid_cell_size, self.theme_colors['default'] + (160,))
        }
        self.patterns_orange = {
            'dots': self.create_tiled_pattern_surface('dots', self.grid_cell_size, self.theme_colors['warning'] + (160,)),
            'lines': self.create_tiled_pattern_surface('lines', self.grid_cell_size, self.theme_colors['warning'] + (160,))
        }
        self.patterns_red = {
            'dots': self.create_tiled_pattern_surface('dots', self.grid_cell_size, self.theme_colors['danger'] + (160,)),
            'lines': self.create_tiled_pattern_surface('lines', self.grid_cell_size, self.theme_colors['danger'] + (160,))
        }
        self.zoom_grid_map = []; self.zoom_grid_update_timer = 0
        self.update_zoom_grid_map()
        self.graph_data = deque(maxlen=self.analysis_graph_rect.width)

        self.module_manager = None

        self.mqtt_client = None
        self.start_mqtt_client()
        self.video_thread = None
        self.video_thread_running = False
        self.start_video_capture()

        modules_to_load = {}
        for name, module_settings in self.settings.modules.items():
            if not module_settings.enabled:
                continue
            try:
                module = ModuleManager.create_from_config(
                    {"module": module_settings.path, "config": module_settings.settings}
                )
            except Exception as exc:
                print(f"[ModuleManager] Unable to load module '{name}': {exc}")
                continue
            modules_to_load[name] = module

        if not modules_to_load:
            print("[ModuleManager] No modules configured; loading built-in defaults")
            from sentinel.modules import CameraModule, RadarModule, NeoTrackerModule, EONETGlobeModule

            modules_to_load = {
                "camera": CameraModule(),
                "radar": RadarModule(),
                "neo_tracker": NeoTrackerModule(),
                "eonet_globe": EONETGlobeModule(),
            }

        self.module_manager = ModuleManager(
            self,
            modules_to_load,
            priorities=self.settings.priorities,
            idle_cycle=self.idle_screen_list,
        )

        startup_screen = self.core_settings.get("startup_screen", "camera")
        if isinstance(startup_screen, str) and startup_screen.lower() == "auto":
            startup_screen = None

        if startup_screen and startup_screen in self.module_manager.modules:
            self.module_manager.set_active(startup_screen)
        elif self.module_manager.modules:
            first_screen = next(iter(self.module_manager.modules))
            self.module_manager.set_active(first_screen)

        # Load map on startup if needed
        if self.current_screen == "radar":
            threading.Thread(target=self.update_map_tiles, daemon=True).start()

    def _execute_hard_reset(self):
        """
        Perform a full application reset by stopping background services, clearing runtime state, and restarting necessary threads.
        
        This method stops MQTT and video capture services, clears detection, map, flight, zoom, and graph state, restores default UI/theme values, restarts the MQTT and video threads, and reactivates the configured module or radar map update if applicable. Must be invoked from the main application thread.
        """
        print("INFO: Executing hard reset...")
        
        # 1. Stop background services
        print("INFO: Stopping background services...")
        # Stop MQTT client
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        print("INFO: MQTT client stopped.")
        
        # Stop video thread
        if self.video_thread and self.video_thread.is_alive():
            self.video_thread_running = False
            self.video_thread.join(timeout=5) # Wait for the thread to finish
            if self.video_thread.is_alive():
                print("WARNING: Video thread did not stop in time.")
            else:
                print("INFO: Video capture thread stopped.")

        # 2. Reset application state variables
        print("INFO: Resetting application state...")
        with self.data_lock:
            self.mqtt_status = "CONNECTING..."
            self.video_status = "INITIALIZING"
            startup_screen = config.CONFIG.get("startup_screen", "camera")
            if isinstance(startup_screen, str) and startup_screen.lower() == "auto":
                startup_screen = "camera"
            self.current_screen = startup_screen
            self.map_surface = None
            self.map_status = "NO DATA"
            
            self.detection_buffer.clear()
            self.active_detections = {}
            self.last_event_time = "--"
            self.target_label = "--"
            self.target_score = "--"
            self.snapshot_surface = None
            self.mqtt_activity = 0.0

            self.alert_level = "none"
            self.current_theme_color = self.theme_colors['default']
            self.header_title_text = "S.E.N.T.I.N.E.L. v1.0"

            self.active_flights = []
            self.closest_flight = None
            self.closest_flight_photo_surface = None
            self.last_closest_flight_id = None
            self.flight_screen_timer = 0
            
            src_w, src_h = config.CONFIG["frigate_resolution"]
            self.is_zoomed = False
            self.show_zoom_grid = False
            self.zoom_target_rect = pygame.Rect(0, 0, src_w, src_h)
            self.current_zoom_rect = self.zoom_target_rect.copy()
            
            self.graph_data.clear()

        # 3. Restart services
        print("INFO: Restarting background services...")
        self.start_mqtt_client()
        self.start_video_capture()
        
        if self.module_manager:
            target = self.current_screen
            if not target:
                target = next(iter(self.module_manager.modules), None)
            if target:
                self.module_manager.set_active(target)

        if self.current_screen == "radar":
            threading.Thread(target=self.update_map_tiles, daemon=True).start()

        print("INFO: Hard reset complete.")

    def calculate_layout(self):
        margins = config.CONFIG['margins']
        header_height = 35 if config.CONFIG['show_header'] else 0
        top_offset = margins['top'] + header_height
        
        # Layout for CAMERA view
        camera_panel_height = 105
        internal_gap = 10 # Fixed space between video and panel
        available_width = config.CONFIG["screen_width"] - (margins['left'] + margins['right'])
        
        self.main_area_rect = pygame.Rect(
            margins['left'], 
            top_offset, 
            available_width, 
            config.CONFIG["screen_height"] - top_offset - camera_panel_height - internal_gap - margins['bottom']
        )
        self.status_panel_rect = pygame.Rect(
            margins['left'], 
            self.main_area_rect.bottom + internal_gap, 
            available_width, 
            camera_panel_height
        )
        
        # Layout for RADAR view
        self.map_area_rect = pygame.Rect(
            margins['left'], 
            top_offset, 
            available_width, 
            config.CONFIG["screen_height"] - top_offset - margins['bottom']
        )
        flight_panel_width = 180 
        self.flight_panel_rect = pygame.Rect(self.map_area_rect.right - flight_panel_width, self.map_area_rect.top, flight_panel_width, self.map_area_rect.height)
        self.visible_map_rect = pygame.Rect(self.map_area_rect.topleft, (self.flight_panel_rect.left - self.map_area_rect.left, self.map_area_rect.height))

        # Status Panel Layout
        panel_pad = 8; col_width_1 = 200; col_width_2 = self.status_panel_rect.height - (panel_pad * 2) 
        col_width_3 = self.status_panel_rect.width - col_width_1 - col_width_2 - (panel_pad * 4)
        self.col1_rect = pygame.Rect(self.status_panel_rect.x + panel_pad, self.status_panel_rect.y + panel_pad, col_width_1, self.status_panel_rect.height - (panel_pad * 2))
        self.col2_rect = pygame.Rect(self.col1_rect.right + (panel_pad * 2), self.status_panel_rect.y + panel_pad, col_width_2, col_width_2) 
        self.col3_rect = pygame.Rect(self.col2_rect.right + (panel_pad * 2), self.status_panel_rect.y + panel_pad, col_width_3, self.status_panel_rect.height - (panel_pad * 2))
        self.analysis_graph_rect = pygame.Rect(self.col3_rect.x, self.col3_rect.y + 24, self.col3_rect.width - 15, self.col3_rect.height - 24)

    def create_tiled_pattern_surface(self, pattern_type, size, color):
        base_pattern_size = 10
        base_surface = pygame.Surface((base_pattern_size + 1, base_pattern_size), pygame.SRCALPHA)
        if pattern_type == 'dots': pygame.draw.circle(base_surface, color, (base_pattern_size // 2, base_pattern_size // 2), 1)
        elif pattern_type == 'lines': pygame.draw.line(base_surface, color, (0, base_pattern_size), (base_pattern_size, 0), 1)
        tiled_surface = pygame.Surface((size, size), pygame.SRCALPHA)
        for x in range(0, size, base_pattern_size):
            for y in range(0, size, base_pattern_size): tiled_surface.blit(base_surface, (x, y))
        return tiled_surface

    def update_zoom_grid_map(self):
        cols, rows = self.main_area_rect.width // self.grid_cell_size + 1, self.main_area_rect.height // self.grid_cell_size + 1
        center_x, center_y = self.main_area_rect.width / 2, self.main_area_rect.height / 2
        max_dist = np.hypot(center_x, center_y) or 1 
        new_map = []
        for r in range(rows):
            row_list = []
            for c in range(cols):
                dist_norm = np.hypot((c + 0.5) * self.grid_cell_size - center_x, (r + 0.5) * self.grid_cell_size - center_y) / max_dist
                threshold, p_type = random.random() * 0.4, 0 
                if dist_norm > 0.2 + threshold: p_type = 1
                if dist_norm > 0.6 + threshold: p_type = 2
                row_list.append(p_type)
            new_map.append(row_list)
        with self.data_lock: self.zoom_grid_map = new_map

    def start_mqtt_client(self):
        try:
            client_id = f"sentinel_crt_ui_{time.time()}"
            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
            self.mqtt_client.username_pw_set(config.CONFIG["mqtt_user"], config.CONFIG["mqtt_password"])
            self.mqtt_client.on_connect, self.mqtt_client.on_message, self.mqtt_client.on_disconnect = self.on_connect, self.on_message, self.on_disconnect
            self.mqtt_client.connect_async(config.CONFIG["mqtt_host"], config.CONFIG["mqtt_port"], 60)
            self.mqtt_client.loop_start()
        except Exception as e:
            print(f"Error starting MQTT client: {e}")
            self.mqtt_status = "ERROR"
            self.mqtt_client = None

    def start_video_capture(self):
        """Starts the video capture thread."""
        if self.video_thread and self.video_thread.is_alive():
            print("WARNING: Video capture thread is already running.")
            return
        
        self.video_thread_running = True
        self.video_thread = threading.Thread(target=self.video_capture_thread, daemon=True)
        self.video_thread.start()

    def video_capture_thread(self):
        reconnect_delay = 5
        while self.video_thread_running:
            print("Connecting to video stream...")
            cap = cv2.VideoCapture(config.CONFIG["camera_rtsp_url"])
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            if not cap.isOpened():
                with self.data_lock: self.video_status = "ERROR"
                print(f"Could not open stream. Retrying in {reconnect_delay} seconds...")
                time.sleep(reconnect_delay)
                continue

            with self.data_lock: self.video_status = "ONLINE"
            print("Video connection established.")
            target_w, target_h = self.main_area_rect.size

            while self.video_thread_running:
                ret, frame = cap.read()
                if not ret:
                    with self.data_lock: self.video_status = "RECONNECTING..."; self.current_video_frame = None
                    print("Lost video stream. Attempting to reconnect...")
                    break
                with self.data_lock: z_rect = self.current_zoom_rect
                zoomed_frame = frame[int(z_rect.y):int(z_rect.y+z_rect.h), int(z_rect.x):int(z_rect.x+z_rect.w)]
                if zoomed_frame.shape[0] > 0 and zoomed_frame.shape[1] > 0:
                    final_frame = cv2.resize(zoomed_frame, (target_w, target_h))
                else: continue
                rotated_frame = np.rot90(np.fliplr(cv2.cvtColor(final_frame, cv2.COLOR_BGR2RGB)))
                with self.data_lock: self.current_video_frame = pygame.surfarray.make_surface(rotated_frame)
            cap.release()
            if self.video_thread_running: time.sleep(reconnect_delay)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.value == 0:
            print("Connected to MQTT broker!")
            self.mqtt_status = "CONNECTED"
            client.subscribe(config.CONFIG["frigate_topic"])
            client.subscribe(config.CONFIG["flight_topic"])

            restart_topic = config.CONFIG.get("mqtt_restart_topic")
            if restart_topic:
                client.subscribe(restart_topic)
        else:
            print(f"Failed to connect to MQTT, code: {reason_code}")
            self.mqtt_status = f"FAILED ({reason_code.value})"

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        print(f"Disconnected from MQTT broker. Reason: {reason_code}")
        if self.running and reason_code is not None and reason_code.value != 0: 
            self.mqtt_status = "DISCONNECTED"

    def on_message(self, client, userdata, msg):
        try:
            # Check for reset command first
            if msg.topic == config.CONFIG.get("mqtt_restart_topic"):
                payload_str = msg.payload.decode('utf-8')
                if payload_str == config.CONFIG.get("mqtt_restart_payload"):
                    print("INFO: Restart command received. Flagging for reset.")
                    self.reset_pending = True # Set the flag for the main loop
                    return

            payload = json.loads(msg.payload)
            if msg.topic == config.CONFIG["frigate_topic"]: 
                self.detection_buffer.append((time.time(), payload))
                with self.data_lock: self.mqtt_activity += 15.0 
            elif msg.topic == config.CONFIG["flight_topic"]: 
                self.handle_flight_data(payload)
                with self.data_lock: self.mqtt_activity += 5.0

        except json.JSONDecodeError: 
            print(f"Error decoding MQTT JSON from topic {msg.topic}.")
        except Exception as e:
            print(f"An error occurred in on_message: {e}")
    
    def handle_flight_data(self, flights):
        flight_list = flights if isinstance(flights, list) else ([flights] if flights else [])
        min_alt = config.CONFIG.get("min_flight_altitude_ft", 0)
        filtered_flights = [f for f in flight_list if f.get('altitude') is not None and f.get('altitude') >= min_alt]

        with self.data_lock:
            self.active_flights = filtered_flights
            if filtered_flights:
                home_lat, home_lon = config.CONFIG['map_latitude'], config.CONFIG['map_longitude']
                for f in filtered_flights:
                    f['distance_km'] = haversine_distance(home_lat, home_lon, f['latitude'], f['longitude'])
                self.closest_flight = min(filtered_flights, key=lambda f: f['distance_km'])
                
                closest_id = self.closest_flight.get('id')
                if closest_id != self.last_closest_flight_id:
                    self.last_closest_flight_id = closest_id
                    photo_url = self.closest_flight.get('photo')
                    if photo_url:
                        threading.Thread(target=self.fetch_flight_photo, args=(photo_url,), daemon=True).start()
                    else:
                        self.closest_flight_photo_surface = None
            else:
                self.closest_flight = None
                self.last_closest_flight_id = None
                self.closest_flight_photo_surface = None
            
            if filtered_flights:
                self.flight_screen_timer = time.time() + config.CONFIG["flight_screen_timeout"]
                if self.map_surface is None:
                    threading.Thread(target=self.update_map_tiles, daemon=True).start()
    
    def update_map_tiles(self):
        with self.data_lock: self.map_status = "LOADING..."
        lat, lon = config.CONFIG['map_latitude'], config.CONFIG['map_longitude']
        self.map_zoom_level = calculate_zoom_from_radius(config.CONFIG['map_radius_m'], self.visible_map_rect.width, lat)
        zoom = self.map_zoom_level
        
        xtile, ytile = deg2num(lat, lon, zoom)
        
        width_tiles = math.ceil(self.map_area_rect.width / 256) + 2
        height_tiles = math.ceil(self.map_area_rect.height / 256) + 2
        map_surf = pygame.Surface((width_tiles * 256, height_tiles * 256))
        
        for dx in range(width_tiles):
            for dy in range(height_tiles):
                tile_x, tile_y = xtile - (width_tiles // 2) + dx, ytile - (height_tiles // 2) + dy
                url = f"https://api.mapbox.com/styles/v1/{config.CONFIG['mapbox_user']}/{config.CONFIG['mapbox_style_id']}/tiles/256/{zoom}/{tile_x}/{tile_y}?access_token={config.CONFIG['mapbox_token']}"
                try:
                    res = requests.get(url, timeout=3)
                    res.raise_for_status()
                    map_surf.blit(pygame.image.load(io.BytesIO(res.content)), (dx * 256, dy * 256))
                except requests.RequestException: continue
        
        with self.data_lock:
            self.map_surface, self.map_status, self.map_center_tile = map_surf, "ONLINE", (xtile, ytile)
            self.map_width_tiles, self.map_height_tiles = width_tiles, height_tiles
            frac_x = (lon + 180.0) / 360.0 * (2**zoom) - xtile
            frac_y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * (2**zoom) - ytile
            self.map_tile_offset = ( (self.visible_map_rect.width / 2) - (frac_x * 256) - ((width_tiles // 2) * 256), (self.map_area_rect.height / 2) - (frac_y * 256) - ((height_tiles // 2) * 256) )

    def fetch_snapshot_image(self, event_id):
        url = f"http://{config.CONFIG['frigate_host']}:5000/api/events/{event_id}/snapshot.jpg?crop=1"
        try:
            response = requests.get(url, timeout=3)
            response.raise_for_status()
            scaled_snapshot = pygame.transform.scale(pygame.image.load(io.BytesIO(response.content)), self.col2_rect.size)
            with self.data_lock: self.snapshot_surface = scaled_snapshot
        except requests.exceptions.RequestException as e: 
            print(f"Error downloading snapshot: {e}")
    
    def fetch_flight_photo(self, url):
        """
        Fetch an aircraft image from the given URL and store it on the instance.
        
        Parameters:
            url (str): HTTP(S) URL pointing to an aircraft photo.
        
        Description:
            Attempts to download and decode the image; on success stores the loaded
            pygame Surface in self.closest_flight_photo_surface, on failure stores None.
        """
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            photo_data = io.BytesIO(response.content)
            photo_img = pygame.image.load(photo_data)
            
            with self.data_lock: self.closest_flight_photo_surface = photo_img
        except Exception as e:
            print(f"Error downloading aircraft photo: {e}")
            with self.data_lock: self.closest_flight_photo_surface = None

    def run(self):
        """
        Run the application's main loop until stopped.
        
        Continuously processes input events, updates application state, and renders frames at the configured frame rate. Guarantees that shutdown() is called when the loop exits.
        """
        exit_code = 0
        try:
            while self.running:
                dt = self.clock.tick(self.core_settings.get("fps", 30)) / 1000.0
                self.handle_events()
                self.update(dt)
                self.draw()
        except KeyboardInterrupt:
            print("INFO: Keyboard interrupt received. Exiting main loop.")
            exit_code = 130
        except Exception:
            print("ERROR: Unhandled exception in main loop:")
            traceback.print_exc()
            exit_code = 1
        finally:
            self.shutdown()
        return exit_code

    def shutdown(self):
        """Shut down background services and release application resources."""
        print("Closing application...")
        self.running = False
        self.video_thread_running = False
        if self.video_thread and self.video_thread.is_alive():
            self.video_thread.join(timeout=5)
        if self.module_manager:
            self.module_manager.shutdown()
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        pygame.quit()

    def handle_events(self):
        """
        Polls the Pygame event queue, handles application quit/escape, and forwards remaining events to the module manager.
        
        If a QUIT event or an ESC keydown is received, sets `self.running` to False to request shutdown. If a ModuleManager is present, each event is passed to its `handle_event` method.
        """
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                self.running = False
                continue
            if self.module_manager:
                self.module_manager.handle_event(event)

    def update(self, dt: float):
        """
        Advance the application's state by one frame.
        
        Performs pending hard-reset processing, updates detections and alert level, synchronizes module manager state, advances zoom logic when on the camera screen, progresses globe/planet/asteroid animations (including the ASCII globe), updates visual HUD effects, and decays/records MQTT activity for the analysis graph.
        
        Parameters:
            dt (float): Time elapsed since the last update call, in seconds.
        """
        if self.reset_pending:
            self._execute_hard_reset()
            self.reset_pending = False
            return

        self.update_detections()
        self.update_alert_level()
        if self.module_manager:
            if "camera" in self.module_manager.modules:
                if self.alert_level != "none":
                    self.module_manager.report_state("camera", self.alert_level, metadata={"source": "alerts"})
                else:
                    self.module_manager.clear_state("camera")

            if "radar" in self.module_manager.modules:
                if self.active_flights:
                    self.module_manager.report_state(
                        "radar",
                        "air-traffic",
                        metadata={"count": len(self.active_flights)},
                    )
                else:
                    self.module_manager.clear_state("radar")

            self.module_manager.update(dt)

        if self.current_screen == "camera":
            self.update_zoom_priority()
            self.update_zoom()

        self.sphere_rotation_angle += 0.005
        if self.sphere_rotation_angle > math.pi * 2:
            self.sphere_rotation_angle = 0
            
        self.globe_rotation_angle += 0.008  # Slower rotation for the globe
        if self.globe_rotation_angle > math.pi * 2:
            self.globe_rotation_angle = 0

        # Anima los planetas a diferentes velocidades
        self.planet_angles[0] += 0.010 # Mercurio
        self.planet_angles[1] += 0.007 # Venus
        self.planet_angles[2] += 0.005 # Tierra
        self.planet_angles[3] += 0.003 # Marte

        # Anima el asteroide a lo largo de su ruta
        self.asteroid_path_progress += 0.008
        if self.asteroid_path_progress > 1.0:
            self.asteroid_path_progress = 0.0 # Reinicia la animación
        
        self.update_visual_effects()
        with self.data_lock:
            self.mqtt_activity *= 0.90
            graph_h = self.analysis_graph_rect.height
            new_y = (graph_h - 15) - self.mqtt_activity + (random.random() - 0.5) * 8
            self.graph_data.append(np.clip(new_y, 5, graph_h - 5))

    def update_alert_level(self):
        """
        Update the application's alert level based on active detections and configured alert zones.
        
        Considers only active detections whose label is listed in the configured `zoom_labels`. If any such detection has entered a zone listed in `alert_zones['danger']`, the alert level is set to "danger"; otherwise if any have entered a zone listed in `alert_zones['warning']`, the alert level is set to "warning"; if neither applies the alert level is "none". Side effects: sets `self.alert_level`, `self.current_theme_color`, and `self.header_title_text` to values appropriate for the resolved level.
        """
        current_level = "none"
        with self.data_lock:
            for detection in self.active_detections.values():
                if detection.get('label') not in config.CONFIG['zoom_labels']: continue
                
                entered_zones = detection.get('entered_zones', [])
                if any(zone in config.CONFIG['alert_zones']['danger'] for zone in entered_zones):
                    current_level = "danger"
                    break # Danger has the highest priority
                if any(zone in config.CONFIG['alert_zones']['warning'] for zone in entered_zones):
                    current_level = "warning"
            
            self.alert_level = current_level
            if self.alert_level == "danger":
                self.current_theme_color = self.theme_colors['danger']
                self.header_title_text = "DANGER"
            elif self.alert_level == "warning":
                self.current_theme_color = self.theme_colors['warning']
                self.header_title_text = "WARNING"
            else:
                self.current_theme_color = self.theme_colors['default']
                self.header_title_text = "S.E.N.T.I.N.E.L. v1.0"

    def update_visual_effects(self):
        """
        Advance and refresh HUD and animation state used by the UI.
        
        Updates animation timers and state for the header spinner, patterned background phase, synthetic system-load string, randomized level-bar heights, and — when a snapshot is present — the scanner sweep position.
        """
        now = time.time()
        self.spinner_angle += 4
        dt = self.clock.get_time() / 1000.0
        self.pattern_phase += self.pattern_speed_px_s * dt
        if now > self.sys_load_update_timer:
            self.sys_load_string, self.sys_load_update_timer = f"{random.randint(0, 0xFFFFFF):06X}", now + 0.2
        if now > self.level_bars_update_timer:
            self.level_bars_heights, self.level_bars_update_timer = [random.randint(2, 18) for _ in range(5)], now + 0.3
        if self.snapshot_surface:
            self.scanner_pos += self.scanner_dir
            if self.scanner_pos <= 0 or self.scanner_pos >= self.col2_rect.width: self.scanner_dir *= -1

    def update_detections(self):
        now = time.time()
        while self.detection_buffer and (now - self.detection_buffer[0][0] > config.CONFIG["bbox_delay"]):
            _, payload = self.detection_buffer.popleft()
            event_type, detection = payload.get('type'), payload.get('after', {})
            if detection.get('camera') != config.CONFIG['camera_name']: continue
            detection_id = detection.get('id')
            with self.data_lock:
                if event_type == 'end':
                    if detection_id in self.active_detections: del self.active_detections[detection_id]
                else:
                    is_new = detection_id not in self.active_detections
                    self.active_detections[detection_id] = detection
                    self.last_event_time = datetime.now().strftime("%H:%M:%S")
                    self.target_label = detection.get('label', '--').upper()
                    self.target_score = f"{(detection.get('score', 0) * 100):.1f}%"
                    if is_new: threading.Thread(target=self.fetch_snapshot_image, args=(detection_id,), daemon=True).start()

    def update_zoom_priority(self):
        """Decides which object to zoom in on based on alert level."""
        with self.data_lock:
            zoomable_detections = [d for d in self.active_detections.values() if d.get('label') in config.CONFIG['zoom_labels']]
            if not zoomable_detections:
                self.is_zoomed = False
                return

            danger_d = [d for d in zoomable_detections if any(z in config.CONFIG['alert_zones']['danger'] for z in d.get('entered_zones', []))]
            warning_d = [d for d in zoomable_detections if any(z in config.CONFIG['alert_zones']['warning'] for z in d.get('entered_zones', []))]

            target_detection = None
            if danger_d: target_detection = max(danger_d, key=lambda d: d.get('score', 0))
            elif warning_d: target_detection = max(warning_d, key=lambda d: d.get('score', 0))
            else: target_detection = max(zoomable_detections, key=lambda d: d.get('score', 0))
            
            if target_detection:
                self.is_zoomed = True
                self.zoom_reset_timer = time.time() + config.CONFIG["zoom_reset_time"]
                self.update_zoom_target(target_detection)

    def update_zoom_target(self, detection):
        src_w, src_h = config.CONFIG["frigate_resolution"]
        box = detection['box']
        box_w, box_h, center_x, center_y = box[2]-box[0], box[3]-box[1], box[0]+(box[2]-box[0])/2, box[1]+(box[3]-box[1])/2
        target_ar = self.main_area_rect.width / self.main_area_rect.height
        zoom_h = box_h * config.CONFIG["zoom_level"]
        zoom_w = zoom_h * target_ar
        if zoom_w < box_w * config.CONFIG["zoom_level"]: zoom_w, zoom_h = box_w * config.CONFIG["zoom_level"], zoom_w / target_ar
        zoom_w, zoom_h = min(zoom_w, src_w), min(zoom_h, src_h)
        zoom_x = max(0, min(center_x - zoom_w / 2, src_w - zoom_w))
        zoom_y = max(0, min(center_y - zoom_h / 2, src_h - zoom_h))
        self.zoom_target_rect.update(zoom_x, zoom_y, zoom_w, zoom_h)
    
    def update_zoom(self):
        with self.data_lock:
            if not self.is_zoomed and self.current_zoom_rect.w < config.CONFIG['frigate_resolution'][0] * 0.99:
                 src_w, src_h = config.CONFIG["frigate_resolution"]
                 self.zoom_target_rect.update(0, 0, src_w, src_h)

            if self.is_zoomed and time.time() > self.zoom_reset_timer:
                self.is_zoomed = False

            speed = config.CONFIG["zoom_speed"]
            self.current_zoom_rect.x += (self.zoom_target_rect.x - self.current_zoom_rect.x) * speed
            self.current_zoom_rect.y += (self.zoom_target_rect.y - self.current_zoom_rect.y) * speed
            self.current_zoom_rect.w += (self.zoom_target_rect.w - self.current_zoom_rect.w) * speed
            self.current_zoom_rect.h += (self.zoom_target_rect.h - self.current_zoom_rect.h) * speed
            src_w, _ = config.CONFIG["frigate_resolution"]
            self.show_zoom_grid = self.current_zoom_rect.w < src_w * 0.99
            if self.show_zoom_grid and time.time() > self.zoom_grid_update_timer:
                self.update_zoom_grid_map()
                self.zoom_grid_update_timer = time.time() + 0.5

    def draw(self):
        """
        Render the active UI screen and header to the main display surface.
        
        Chooses a module-managed screen when a module manager and current module screen exist; otherwise renders one of the built-in screens ('camera', 'radar', 'neo_tracker', 'eonet_globe') with a fallback to the camera view. If the header is enabled in configuration, draws the header on top of the screen, then updates the display buffer.
        """
        self.screen.fill(COLOR_BLACK)

        if self.module_manager:
            self.module_manager.render(self.screen)
        else:
            self._draw_placeholder()

        # Dibuja el header encima de todo, si está habilitado
        if config.CONFIG.get('show_header', True):
            self.draw_header()

        pygame.display.flip()

    def _draw_placeholder(self):
        message = "MODULE MANAGER OFFLINE"
        surface = self.font_large.render(message, True, self.current_theme_color)
        self.screen.blit(surface, surface.get_rect(center=self.screen.get_rect().center))

    def draw_header(self):
        margins = config.CONFIG['margins']
        header_rect = pygame.Rect(margins['left'], margins['top'] - 5, self.screen.get_width() - (margins['left'] + margins['right']), 30)
        color = self.current_theme_color
        
        pygame.draw.line(self.screen, color, (header_rect.left, header_rect.bottom), (header_rect.right, header_rect.bottom), 2)
        title_surface = self.font_large.render(self.header_title_text, True, color)
        title_rect = title_surface.get_rect(topleft=(header_rect.left, header_rect.top + 2))
        self.screen.blit(title_surface, title_rect)
        
        bar_x = header_rect.right - 5 * 8
        for i, height in enumerate(self.level_bars_heights):
            pygame.draw.rect(self.screen, color, (bar_x + i * 8, header_rect.centery - height/2 + 1, 4, height))
        sys_load_surface = self.font_medium.render(f"SYS-LOAD: {self.sys_load_string}", True, color)
        sys_load_rect = sys_load_surface.get_rect(right=bar_x - 15, centery=header_rect.centery)
        self.screen.blit(sys_load_surface, sys_load_rect)
        spinner_char_surf = self.font_medium.render("+", True, color)
        original_spinner_rect = spinner_char_surf.get_rect(right=sys_load_rect.left - 10, centery=header_rect.centery)
        rotated_spinner = pygame.transform.rotate(spinner_char_surf, self.spinner_angle)
        rotated_spinner_rect = rotated_spinner.get_rect(center=original_spinner_rect.center)
        self.screen.blit(rotated_spinner, rotated_spinner_rect)

        pattern_left_margin = 10
        pattern_right_margin = 24
        pattern_start_x = title_rect.right + pattern_left_margin
        pattern_end_x = sys_load_rect.left - pattern_right_margin
        pattern_width = max(0, pattern_end_x - pattern_start_x)

        pattern_rect = pygame.Rect(
            pattern_start_x,
            header_rect.top + 6,
            pattern_width,
            header_rect.height - 12
        )
        draw_diagonal_pattern(
            self.screen,
            color,
            pattern_rect,
            -45,
            spacing=8,
            line_width=4,
            phase=self.pattern_phase,
        )

if __name__ == '__main__':
    app = SentinelApp()
    sys.exit(app.run())
