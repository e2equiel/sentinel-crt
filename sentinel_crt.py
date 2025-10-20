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

# Import configuration from the separate config file
import config

from sentinel.config import load_configuration
from sentinel.core import ModuleManager

from neo_tracker import NEOTracker
from eonet_tracker import EONETTracker
from ascii_globe import ASCIIGlobe # <-- AÑADIDO

# --- Constants ---
# Colors are defined in the config file now for easier theme management.
# We can keep them here if they are static, but moving them to config.py is also an option.
COLOR_BLACK = (0, 0, 0)
COLOR_WHITE = (220, 220, 220) 
COLOR_YELLOW = (255, 255, 0)
COLOR_RING = (0, 255, 65, 70)



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

def draw_dashed_line(surf, color, start_pos, end_pos, width=1, dash_length=5):
    """Draws a dashed line on a Pygame surface."""
    x1, y1 = start_pos; x2, y2 = end_pos
    dl = dash_length
    if (x1 == x2 and y1 == y2): return
    dx, dy = x2 - x1, y2 - y1
    dist = math.hypot(dx, dy)
    dashes = int(dist / dl)
    for i in range(dashes // 2):
        start = (x1 + dx * (i * 2) / dashes, y1 + dy * (i * 2) / dashes)
        end = (x1 + dx * (i * 2 + 1) / dashes, y1 + dy * (i * 2 + 1) / dashes)
        pygame.draw.line(surf, color, start, end, width)

def draw_diagonal_pattern(surface, color, rect, angle, spacing=5, line_width=1, phase=0):
    diagonal = int(math.hypot(rect.width, rect.height))
    temp_surface = pygame.Surface((diagonal, diagonal), pygame.SRCALPHA)

    phase_int = int(phase)
    for x in range(-diagonal, diagonal, spacing):
        x_pos = x + (phase_int % spacing)
        pygame.draw.line(temp_surface, color, (x_pos, 0), (x_pos, diagonal), line_width)

    rotated_surface = pygame.transform.rotozoom(temp_surface, angle, 1)
    rotated_rect = rotated_surface.get_rect(center=rect.center)

    original_clip = surface.get_clip()
    surface.set_clip(rect)
    surface.blit(rotated_surface, rotated_rect)
    surface.set_clip(original_clip)

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
        self.globe_rotation_angle = 0 # For EONET
        self.planet_angles = [random.uniform(0, 2 * math.pi) for _ in range(4)] # Ángulos iniciales para 4 planetas
        self.asteroid_path_progress = 0.0

        # <-- AÑADIDO: INICIALIZACIÓN DEL GLOBO ASCII -->
        self.globe_center_x = self.screen.get_width() * 0.6
        self.globe_center_y = self.screen.get_height() / 2 + 20
        self.globe_radius = 160
        self.ascii_globe = ASCIIGlobe(
            self.screen.get_width(),
            self.screen.get_height(),
            self.globe_radius,
            (self.globe_center_x, self.globe_center_y),
            'earth_W140_H35.txt'
        )
        # <-- FIN DEL CÓDIGO AÑADIDO -->
        
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

        if modules_to_load:
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
        else:
            print("[ModuleManager] No modules configured; defaulting to camera view")
            self.current_screen = "camera"

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
            client.subscribe(config.CONFIG["mqtt_restart_topic"])
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
        try:
            while self.running:
                dt = self.clock.tick(self.core_settings.get("fps", 30)) / 1000.0
                self.handle_events()
                self.update(dt)
                self.draw()
        finally:
            self.shutdown()

    def shutdown(self):
        """
        Shuts down the application and terminates all background services.
        
        Stops and shuts down the module manager if present, stops the MQTT network loop and disconnects the client, quits Pygame, and exits the process.
        
        Raises:
            SystemExit: terminates the running process.
        """
        print("Closing application...")
        if self.module_manager:
            self.module_manager.shutdown()
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()
        pygame.quit()
        sys.exit()

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
            
        self.globe_rotation_angle += 0.008 # Slower rotation for the globe
        if self.globe_rotation_angle > math.pi * 2:
            self.globe_rotation_angle = 0

        # <-- AÑADIDO: ACTUALIZACIÓN DEL GLOBO ASCII -->
        self.ascii_globe.update(angle_x=0.0, angle_y=self.globe_rotation_angle)

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

        if self.module_manager and self.module_manager.current_screen:
            self.module_manager.render(self.screen)
        else:
            if self.current_screen == "camera":
                self.draw_camera_view()
            elif self.current_screen == "radar":
                self.draw_radar_view()
            elif self.current_screen == "neo_tracker":
                self.draw_neo_tracker_screen()
            elif self.current_screen == "eonet_globe":
                self.draw_eonet_globe_screen()
            else:
                self.draw_camera_view()

        # Dibuja el header encima de todo, si está habilitado
        if config.CONFIG.get('show_header', True):
            self.draw_header()

        pygame.display.flip()

    def draw_camera_view(self):
        self.draw_video_feed()
        if self.show_zoom_grid: self.draw_zoom_grid()
        self.draw_bounding_boxes()
        self.draw_status_panel()

    def draw_radar_view(self):
        self.draw_map()
        self.draw_flight_info_panel()

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
        draw_diagonal_pattern(self.screen, color, pattern_rect, -45, 8, 4, phase=self.pattern_phase)

    def draw_video_feed(self):
        with self.data_lock:
            if self.current_video_frame: self.screen.blit(self.current_video_frame, self.main_area_rect.topleft)
            else:
                placeholder_text = self.font_medium.render("VIDEO FEED OFFLINE", True, self.current_theme_color)
                self.screen.blit(placeholder_text, placeholder_text.get_rect(center=self.main_area_rect.center))
        pygame.draw.rect(self.screen, self.current_theme_color, self.main_area_rect, 2)

    def draw_zoom_grid(self):
        grid_surface = pygame.Surface(self.main_area_rect.size, pygame.SRCALPHA)
        
        if self.alert_level == "warning": patterns = self.patterns_orange
        elif self.alert_level == "danger": patterns = self.patterns_red
        else: patterns = self.patterns_green

        grid_color = self.current_theme_color + (160,)

        with self.data_lock:
            for r, row in enumerate(self.zoom_grid_map):
                for c, p_type in enumerate(row):
                    pos = (c * self.grid_cell_size, r * self.grid_cell_size)
                    if p_type == 1: grid_surface.blit(patterns['dots'], pos)
                    elif p_type == 2: grid_surface.blit(patterns['lines'], pos)
        
        for x in range(0, self.main_area_rect.width, self.grid_cell_size): pygame.draw.line(grid_surface, grid_color, (x, 0), (x, self.main_area_rect.height), 1)
        for y in range(0, self.main_area_rect.height, self.grid_cell_size): pygame.draw.line(grid_surface, grid_color, (0, y), (self.main_area_rect.width, y), 1)
        self.screen.blit(grid_surface, self.main_area_rect.topleft)

    def draw_bounding_boxes(self):
        with self.data_lock:
            if not self.active_detections: return
            z_rect = self.current_zoom_rect
            if z_rect.w == 0 or z_rect.h == 0: return
            for detection in self.active_detections.values():
                box = detection.get('box')
                if not box: continue
                box_x_rel, box_y_rel = box[0] - z_rect.x, box[1] - z_rect.y
                scale_x, scale_y = self.main_area_rect.width / z_rect.w, self.main_area_rect.height / z_rect.h
                x1, y1, w, h = box_x_rel * scale_x, box_y_rel * scale_y, (box[2] - box[0]) * scale_x, (box[3] - box[1]) * scale_y
                box_rect = pygame.Rect(self.main_area_rect.x + x1, self.main_area_rect.y + y1, w, h)
                clipped_box = box_rect.clip(self.main_area_rect)
                if clipped_box.width > 0 and clipped_box.height > 0:
                    pygame.draw.rect(self.screen, self.current_theme_color, clipped_box, 1)
                    label, score = detection.get('label', ''), detection.get('score', 0)
                    label_surface = self.font_small.render(f"{label.upper()} [{score:.0%}]", True, self.current_theme_color)
                    label_pos_y = box_rect.y - 18
                    if label_pos_y < self.main_area_rect.y: label_pos_y = clipped_box.y + 2
                    self.screen.blit(label_surface, (clipped_box.x + 2, label_pos_y))
    
    def draw_map(self):
        with self.data_lock:
            if self.map_surface:
                self.screen.set_clip(self.map_area_rect)
                self.screen.blit(self.map_surface, (self.map_area_rect.x + self.map_tile_offset[0], self.map_area_rect.y + self.map_tile_offset[1]))
                self.draw_map_overlays() 
                self.screen.set_clip(None)
            else:
                placeholder_text = self.font_medium.render(self.map_status, True, self.current_theme_color)
                self.screen.blit(placeholder_text, placeholder_text.get_rect(center=self.map_area_rect.center))
        pygame.draw.rect(self.screen, self.current_theme_color, self.map_area_rect, 2)

    def get_screen_pos_from_coords(self, lat, lon):
        """Converts lat/lon coordinates to a screen position."""
        zoom = self.map_zoom_level
        center_tile_x, center_tile_y = self.map_center_tile
        offset_x, offset_y = self.map_tile_offset
        
        flight_tile_x, flight_tile_y = deg2num(lat, lon, zoom)
        flight_frac_x = (lon + 180.0) / 360.0 * (2**zoom) - flight_tile_x
        flight_frac_y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * (2**zoom) - flight_tile_y
        
        flight_pixel_x_in_tile, flight_pixel_y_in_tile = flight_frac_x * 256, flight_frac_y * 256
        tile_diff_x = (flight_tile_x - (center_tile_x - self.map_width_tiles // 2)) * 256
        tile_diff_y = (flight_tile_y - (center_tile_y - self.map_height_tiles // 2)) * 256
        
        map_surf_x, map_surf_y = tile_diff_x + flight_pixel_x_in_tile, tile_diff_y + flight_pixel_y_in_tile
        screen_x, screen_y = self.map_area_rect.x + offset_x + map_surf_x, self.map_area_rect.y + offset_y + map_surf_y
        return screen_x, screen_y

    def draw_map_overlays(self):
        """
        Render radar/map overlays on the map area including range rings, optional radial lines and labels, the configured home/base marker, aircraft markers (highlighting the closest), and a dashed line with distance label to the closest flight.
        
        This method:
        - Draws concentric distance rings centered on the configured map latitude/longitude using the configured map radius and map_distance_rings.
        - Optionally draws radial sector lines and cardinal/intermediate direction labels when `map_radial_lines` is enabled in configuration.
        - Renders a boxed home/base marker at the configured coordinates if it lies inside the visible map area.
        - Renders each active flight as a rotated triangular marker, visually highlighting the closest flight and drawing a selection rectangle around it.
        - If a closest flight is present and visible, draws a dashed connector from home to the flight and renders the midpoint distance label.
        
        Notes:
        - Overlays are drawn onto `self.screen` and constrained by `self.map_area_rect` / `self.visible_map_rect`.
        - Several appearance and behavior aspects are driven by configuration keys such as `map_latitude`, `map_longitude`, `map_radius_m`, and `map_distance_rings`.
        """
        home_pos = self.get_screen_pos_from_coords(config.CONFIG['map_latitude'], config.CONFIG['map_longitude'])
        
        pixels_per_meter = (self.visible_map_rect.width / 2) / config.CONFIG['map_radius_m']
        num_rings = config.CONFIG.get("map_distance_rings", 3)
        radius_step_m = config.CONFIG['map_radius_m'] / num_rings
        max_radius_px = int(config.CONFIG['map_radius_m'] * pixels_per_meter)

        panel_surface = pygame.Surface(self.map_area_rect.size, pygame.SRCALPHA)
        panel_surface.fill((0, 0, 0, 120)) 
        pygame.draw.rect(panel_surface, self.theme_colors['default'], panel_surface.get_rect(), 1)
        self.screen.blit(panel_surface, self.map_area_rect.topleft)
        
        if config.CONFIG.get("map_radial_lines", False):
            # --- CORRECCIÓN PARA EL ORDEN DEL RADAR ---
            cardinal_points = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}
            intermediate_points = {"NNE": 22.5, "ENE": 67.5, "ESE": 112.5, "SSE": 157.5, "SSW": 202.5, "WSW": 247.5, "WNW": 292.5, "NNW": 337.5}
            
            # Unimos y ordenamos los puntos por su ángulo para asegurar el orden de dibujo
            all_points_sorted = sorted((cardinal_points | intermediate_points).items(), key=lambda item: item[1])
            cardinal_points_sorted = sorted(cardinal_points.items(), key=lambda item: item[1])
            intermediate_points_sorted = sorted(intermediate_points.items(), key=lambda item: item[1])

            line_start_radius = 20
            start_radius_inter = max_radius_px - (radius_step_m * pixels_per_meter)
            
            # Dibujar las líneas de los sectores (hasta el penúltimo anillo)
            for _, angle in cardinal_points_sorted:
                line_angle_rad = math.radians(angle - 90 - 22.5)
                start_x, start_y = home_pos[0] + line_start_radius * math.cos(line_angle_rad), home_pos[1] + line_start_radius * math.sin(line_angle_rad)
                end_x, end_y = home_pos[0] + start_radius_inter * math.cos(line_angle_rad), home_pos[1] + start_radius_inter * math.sin(line_angle_rad)
                pygame.draw.line(self.screen, COLOR_RING, (start_x, start_y), (end_x, end_y), 1)

            # Dibujar las líneas exteriores (desde el penúltimo al último anillo)
            for _, angle in all_points_sorted:
                line_angle_rad = math.radians(angle - 90 - 11.25)
                start_x, start_y = home_pos[0] + start_radius_inter * math.cos(line_angle_rad), home_pos[1] + start_radius_inter * math.sin(line_angle_rad)
                end_x, end_y = home_pos[0] + max_radius_px * math.cos(line_angle_rad), home_pos[1] + max_radius_px * math.sin(line_angle_rad)
                pygame.draw.line(self.screen, COLOR_RING, (start_x, start_y), (end_x, end_y), 1)

            # Dibujar las etiquetas de texto
            for label, angle in cardinal_points_sorted:
                label_angle_rad = math.radians(angle - 90)
                label_surf = self.font_small.render(label, True, COLOR_RING)
                label_pos = (home_pos[0] + (max_radius_px + 15) * math.cos(label_angle_rad), home_pos[1] + (max_radius_px + 15) * math.sin(label_angle_rad))
                label_rect = label_surf.get_rect(center=label_pos)
                label_rect.clamp_ip(self.visible_map_rect) 
                self.screen.blit(label_surf, label_rect)
            
            for label, angle in intermediate_points_sorted:
                label_angle_rad = math.radians(angle - 90)
                label_surf = self.font_tiny.render(label, True, COLOR_RING)
                label_pos = (home_pos[0] + (max_radius_px + 15) * math.cos(label_angle_rad), home_pos[1] + (max_radius_px + 15) * math.sin(label_angle_rad))
                label_rect = label_surf.get_rect(center=label_pos)
                label_rect.clamp_ip(self.visible_map_rect)
                self.screen.blit(label_surf, label_rect)


        for i in range(1, num_rings + 1):
            dist_m = i * radius_step_m
            radius_px = int(dist_m * pixels_per_meter)
            pygame.draw.circle(self.screen, COLOR_RING, (int(home_pos[0]), int(home_pos[1])), radius_px, 1)
            dist_km = dist_m / 1000
            label_text = f"{dist_km:.0f}km"
            label_surf = self.font_small.render(label_text, True, COLOR_RING)
            self.screen.blit(label_surf, (home_pos[0] + radius_px - label_surf.get_width() - 5, home_pos[1] - 15))

        if self.map_area_rect.collidepoint(home_pos):
            size = 8
            home_rect = pygame.Rect(home_pos[0] - size, home_pos[1] - size, size * 2, size * 2)
            pygame.draw.rect(self.screen, self.theme_colors['default'], home_rect, 1)
            pygame.draw.line(self.screen, self.theme_colors['default'], (home_rect.left, home_rect.centery), (home_rect.right, home_rect.centery), 1)
            pygame.draw.line(self.screen, self.theme_colors['default'], (home_rect.centerx, home_rect.top), (home_rect.centerx, home_rect.bottom), 1)

        closest_flight_pos = None
        for flight in self.active_flights:
            screen_pos = self.get_screen_pos_from_coords(flight.get('latitude'), flight.get('longitude'))
            if self.map_area_rect.collidepoint(screen_pos):
                is_closest = (flight == self.closest_flight)
                plane_size, color = (12, COLOR_YELLOW) if is_closest else (8, self.theme_colors['default'])
                angle = math.radians(flight.get('track', 0) - 90)
                cos_a, sin_a = math.cos(angle), math.sin(angle)
                points = [(-plane_size, -plane_size//2), (plane_size, 0), (-plane_size, plane_size//2)]
                rotated_points = [(p[0] * cos_a - p[1] * sin_a + screen_pos[0], p[0] * sin_a + p[1] * cos_a + screen_pos[1]) for p in points]
                pygame.draw.polygon(self.screen, color, rotated_points)
                if is_closest:
                    closest_flight_pos = screen_pos
                    pygame.draw.rect(self.screen, COLOR_YELLOW, (screen_pos[0] - 15, screen_pos[1] - 15, 30, 30), 1)

        if closest_flight_pos and self.map_area_rect.collidepoint(home_pos):
            draw_dashed_line(self.screen, COLOR_YELLOW, home_pos, closest_flight_pos, dash_length=8)
            dist_text = f"{self.closest_flight.get('distance_km', 0):.1f} km"
            dist_surf = self.font_small.render(dist_text, True, COLOR_YELLOW)
            mid_point = ((home_pos[0] + closest_flight_pos[0]) / 2, (home_pos[1] + closest_flight_pos[1]) / 2)
            dist_rect = dist_surf.get_rect(center=mid_point)
            self.screen.blit(dist_surf, dist_rect)

    def draw_flight_info_panel(self):
        """
        Render the "Closest Aircraft" information panel and blit it to the configured flight panel area.
        
        Renders a semi-transparent panel showing either a "NO TARGETS" message or details for the currently tracked closest flight (callsign, model, altitude, speed, heading, and route). If a flight photo is available it is scaled and displayed at the bottom of the panel; otherwise a "NO IMAGE DATA" placeholder box is shown. The panel border, text, and divider lines use the app's theme colors and the finished surface is blitted to self.flight_panel_rect on the main screen.
        """
        panel_surface = pygame.Surface(self.flight_panel_rect.size, pygame.SRCALPHA)
        panel_surface.fill((0, 0, 0, 180)) 
        pygame.draw.rect(panel_surface, self.theme_colors['default'], panel_surface.get_rect(), 1)
        
        title_surf = self.font_medium.render("CLOSEST AIRCRAFT", True, COLOR_YELLOW)
        panel_surface.blit(title_surf, (10, 10))
        pygame.draw.line(panel_surface, self.theme_colors['default'], (10, 35), (self.flight_panel_rect.width - 10, 35), 1)

        y_offset = 45
        with self.data_lock: flight, photo = self.closest_flight, self.closest_flight_photo_surface
        
        if not flight:
            panel_surface.blit(self.font_small.render("> NO TARGETS...", True, self.theme_colors['default']), (10, y_offset))
        else:
            details = {
                "CALLSIGN:": flight.get('callsign', 'N/A').upper(), "MODEL:": flight.get('model', 'N/A'),
                "ALTITUDE:": f"{flight.get('altitude', 0)} FT", "SPEED:": f"{flight.get('speed', 0)} KTS",
                "HEADING:": f"{flight.get('track', 0)}°"
            }
            for label, value in details.items():
                panel_surface.blit(self.font_small.render(label, True, self.theme_colors['default']), (10, y_offset))
                panel_surface.blit(self.font_medium.render(value, True, COLOR_WHITE), (10, y_offset + 14))
                y_offset += 36
            
            pygame.draw.line(panel_surface, self.theme_colors['default'], (10, y_offset), (self.flight_panel_rect.width - 10, y_offset), 1)
            y_offset += 8
            panel_surface.blit(self.font_small.render("ROUTE:", True, self.theme_colors['default']), (10, y_offset))
            route_text = f"{flight.get('airport_origin_code', 'N/A')} > {flight.get('airport_destination_code', 'N/A')}"
            panel_surface.blit(self.font_medium.render(route_text, True, COLOR_WHITE), (10, y_offset + 14))
            
            if photo:
                panel_w = self.flight_panel_rect.width - 20 
                photo_h = int(panel_w / (photo.get_width() / photo.get_height()))
                photo_rect = pygame.Rect(10, self.flight_panel_rect.height - photo_h - 10, panel_w, photo_h)
                scaled_photo = pygame.transform.scale(photo, photo_rect.size)
                panel_surface.blit(scaled_photo, photo_rect)
                pygame.draw.rect(panel_surface, self.theme_colors['default'], photo_rect, 1)
            else:
                photo_rect = pygame.Rect(10, self.flight_panel_rect.height - 80 - 10, self.flight_panel_rect.width - 20, 80)
                no_img_surf = self.font_small.render("NO IMAGE DATA", True, self.theme_colors['default'])
                panel_surface.blit(no_img_surf, no_img_surf.get_rect(center=photo_rect.center))
                pygame.draw.rect(panel_surface, self.theme_colors['default'], photo_rect, 1)

        self.screen.blit(panel_surface, self.flight_panel_rect.topleft)

    def draw_status_panel(self):
        color = self.current_theme_color
        pygame.draw.rect(self.screen, color, self.status_panel_rect, 2)
        y_offset, row_h = self.col1_rect.y + 2, 14
        texts = [
            ("MQTT LINK:", self.mqtt_status), ("VIDEO FEED:", self.video_status), ("CAMERA:", config.CONFIG['camera_name'].upper()),
            ("LAST EVENT:", self.last_event_time), ("TARGET:", self.target_label), ("CONFIDENCE:", self.target_score)
        ]
        for i, (label, value) in enumerate(texts):
            y_pos = y_offset + (i * row_h)

            label_surface = self.font_small.render(label, True, color)
            label_rect = label_surface.get_rect()
            
            value_surface = self.font_small.render(str(value), True, COLOR_WHITE)
            value_rect = value_surface.get_rect()

            label_rect.topleft = (self.col1_rect.x, y_pos)
            value_rect.topright = (self.col1_rect.right, y_pos)

            line_y = label_rect.centery
            start_x = label_rect.right + 4
            end_x = value_rect.left - 4

            if start_x < end_x:
                start_pos = (start_x, line_y)
                end_pos = (end_x, line_y)
                draw_dashed_line(self.screen, color, start_pos, end_pos, 1, 2)
            
            self.screen.blit(label_surface, label_rect)
            self.screen.blit(value_surface, value_rect)
            
        with self.data_lock:
            if self.snapshot_surface:
                self.screen.blit(self.snapshot_surface, self.col2_rect)
                self.draw_snapshot_scanner()
            else:
                no_signal_surf = self.font_small.render("NO SIGNAL", True, color)
                self.screen.blit(no_signal_surf, no_signal_surf.get_rect(center=self.col2_rect.center))
        pygame.draw.rect(self.screen, color, self.col2_rect, 1)

        scan_text = "> SCANNING FOR TARGETS"
        if int(time.time() * 2) % 2 == 0: scan_text += "_" 
        self.screen.blit(self.font_small.render(scan_text, True, color), (self.col3_rect.x, self.col3_rect.y))
        self.draw_analysis_graph()

    def draw_snapshot_scanner(self):
        scanner_surface = pygame.Surface(self.col2_rect.size, pygame.SRCALPHA)
        trail_color = self.current_theme_color + (25,) # Dynamic trail color
        
        trail_width = 20
        if self.scanner_dir > 0: trail_rect = pygame.Rect(self.scanner_pos - trail_width, 0, trail_width, self.col2_rect.height)
        else: trail_rect = pygame.Rect(self.scanner_pos, 0, trail_width, self.col2_rect.height)
        
        scanner_surface.fill(trail_color, trail_rect)
        pygame.draw.line(scanner_surface, self.current_theme_color, (self.scanner_pos, 0), (self.scanner_pos, self.col2_rect.height), 2)
        self.screen.blit(scanner_surface, self.col2_rect.topleft)

    def draw_analysis_graph(self):
        graph_rect = self.analysis_graph_rect
        color = self.current_theme_color
        
        grid_surface = pygame.Surface(graph_rect.size, pygame.SRCALPHA)
        cell_size = 10
        for x in range(0, graph_rect.width, cell_size): pygame.draw.line(grid_surface, color + (100,), (x, 0), (x, graph_rect.height), 1)
        for y in range(0, graph_rect.height, cell_size): pygame.draw.line(grid_surface, color + (100,), (0, y), (graph_rect.width, y), 1)
        self.screen.blit(grid_surface, graph_rect.topleft)
        pygame.draw.rect(self.screen, color, graph_rect, 1)
        
        points = []
        with self.data_lock:
            for i, y in enumerate(self.graph_data): points.append((graph_rect.x + i, graph_rect.y + y))
        if len(points) > 1: pygame.draw.lines(self.screen, color, False, points, 1)

    def draw_neo_tracker_screen(self):
        """
        Draws the NEO tracker screen with a central sphere, top-left HUD,
        and a bottom-right solar system mini-map.
        """
        # Obtiene los datos una vez para usarlos en todas las funciones
        neo_data = self.neo_tracker.get_closest_neo_data()
        
        # 1. Dibuja el elemento central: la esfera pseudo-3D y su trayectoria
        sphere_center_x = self.screen.get_width() // 2
        sphere_center_y = self.screen.get_height() // 2 + 20 # Un poco más arriba para no chocar con el mini-mapa
        sphere_radius = 120
        self.draw_vector_sphere(sphere_center_x, sphere_center_y, sphere_radius, self.current_theme_color, self.sphere_rotation_angle)
        self.draw_asteroid_trajectory(sphere_center_x, sphere_center_y, sphere_radius, neo_data, self.current_theme_color)
        
        # 2. Dibuja la información de texto en la esquina superior izquierda
        self.draw_neo_hud(neo_data)
        
        # 3. Dibuja el nuevo mini-mapa en la esquina inferior derecha
        self.draw_solar_system_map(neo_data)
    
    def draw_vector_sphere(self, x, y, radius, color, rotation_angle):
        """Draws a rotating pseudo-3D wireframe sphere."""
        # Dibuja las líneas de longitud (elipses verticales)
        num_long_lines = 12
        for i in range(num_long_lines):
            angle = (i / num_long_lines) * math.pi + rotation_angle
            
            # El coseno hace que las elipses se achaten en los bordes, simulando una esfera
            ellipse_width = abs(int(radius * 2 * math.cos(angle)))
            
            if ellipse_width > 2: # Solo dibuja las que son visibles
                rect = pygame.Rect(x - ellipse_width // 2, y - radius, ellipse_width, radius * 2)
                pygame.draw.ellipse(self.screen, color, rect, 1)

        # Dibuja las líneas de latitud (elipses horizontales)
        num_lat_lines = 7
        for i in range(1, num_lat_lines):
            lat_y = y - radius + (i * (radius * 2) / num_lat_lines)
            
            # El cálculo de la anchura simula la curvatura de la esfera
            dist_from_center = abs(y - lat_y)
            width_factor = math.sqrt(radius**2 - dist_from_center**2) / radius
            ellipse_width = int(radius * 2 * width_factor)
            
            rect = pygame.Rect(x - ellipse_width // 2, lat_y - 2, ellipse_width, 4)
            pygame.draw.ellipse(self.screen, color, rect, 1)

    # ==============================================================================
    # == NUEVAS FUNCIONES Y MODIFICACIONES PARA EONET
    # ==============================================================================

    def draw_eonet_globe_screen(self):
        """Dibuja el globo de EONET con etiquetas proyectadas radialmente."""
        color = self.current_theme_color
        
        globe_center_x = self.globe_center_x
        globe_center_y = self.globe_center_y
        globe_radius = self.globe_radius
        events = self.eonet_tracker.get_events()

        self.ascii_globe.draw(self.screen, self.font_tiny, color)
        
        if events:
            for i, event in enumerate(events, 1):
                if not event['coordinates'] or len(event['coordinates']) != 2:
                    continue

                lon, lat = event['coordinates']

                # <-- CORRECCIÓN: Revertimos la rotación a '+' para que coincida con el nuevo eje Z
                lon_rad = math.radians(lon) + self.globe_rotation_angle
                
                lat_rad = math.radians(lat)
                
                x3d = math.cos(lat_rad) * math.cos(lon_rad)
                y3d = math.sin(lat_rad)
                # <-- CORRECCIÓN: Negamos Z aquí también para sincronizarlo con el globo
                z3d = -math.cos(lat_rad) * math.sin(lon_rad)
                
                if z3d > -0.1:
                    screen_x = int(globe_center_x + globe_radius * x3d)
                    screen_y = int(globe_center_y - globe_radius * y3d)
                    
                    dx = screen_x - globe_center_x
                    dy = screen_y - globe_center_y
                    dist = math.hypot(dx, dy)
                    if dist == 0: continue

                    projection_dist = 40
                    end_line_x = screen_x + (dx / dist) * projection_dist
                    end_line_y = screen_y + (dy / dist) * projection_dist

                    tag_topleft = self.get_hud_tag_topleft((end_line_x, end_line_y), str(i))
                    self.draw_hud_tag(self.screen, tag_topleft, str(i), color)

                    draw_dashed_line(self.screen, color, (screen_x, screen_y), (end_line_x, end_line_y))
                    
                    alpha = int(100 + 155 * (z3d if z3d > 0 else 0))
                    pygame.draw.circle(self.screen, COLOR_YELLOW + (alpha,), (screen_x, screen_y), 4)

        self.draw_eonet_hud(events)

    def get_hud_tag_topleft(self, center_pos, text):
        """Calcula la posición topleft de una etiqueta para que quede centrada en center_pos."""
        text_surf = self.font_tiny.render(text, True, COLOR_WHITE)
        padding = 4
        tag_width = text_surf.get_width() + padding * 2
        tag_height = text_surf.get_height() + padding * 2
        return (center_pos[0] - tag_width / 2, center_pos[1] - tag_height / 2)

    def draw_hud_tag(self, surface, topleft_pos, text, color):
        """Dibuja una etiqueta numerada en una posición absoluta y devuelve su Rect."""
        text_surf = self.font_tiny.render(text, True, COLOR_WHITE)
        padding = 4
        bg_rect = pygame.Rect(
            topleft_pos[0], 
            topleft_pos[1],
            text_surf.get_width() + padding * 2,
            text_surf.get_height() + padding * 2
        )
        bg_surf = pygame.Surface(bg_rect.size, pygame.SRCALPHA)
        bg_surf.fill((0, 0, 0, 180))
        surface.blit(bg_surf, bg_rect.topleft)
        pygame.draw.rect(surface, color, bg_rect, 1)
        surface.blit(text_surf, text_surf.get_rect(center=bg_rect.center).topleft)
        return bg_rect

    def draw_eonet_hud(self, events):
        """
        Render the textual HUD for the EONET globe screen in the left margin.
        
        Displays a header and either a scanning status or a numbered list of up to 8 recent global events. For each event the HUD shows a numbered box, an uppercase category tag, and the event title (truncated with an ellipsis if longer than 35 characters). If an event's category is "Wildfires" or "Severe Storms", the category tag is rendered using the theme's warning color; all other text uses the standard colors from the current theme.
        
        Parameters:
            events (list[dict]): A list of event objects. Each event should contain at least:
                - 'category' (str): the event category name.
                - 'title' (str): the event title to display.
        
        """
        margins = config.CONFIG['margins']
        x_offset = margins['left'] + 10
        y_offset = margins['top'] + 45

        title_surf = self.font_large.render("// GLOBAL EVENT MONITOR //", True, self.current_theme_color)
        self.screen.blit(title_surf, (x_offset, y_offset))
        y_offset += 30

        if not events:
            status_surf = self.font_medium.render("...SCANNING FOR GLOBAL EVENTS...", True, self.current_theme_color)
            self.screen.blit(status_surf, (x_offset, y_offset))
            return
        
        max_events_to_show = 8
        line_height = 20
        
        for i, event in enumerate(events[:max_events_to_show], 1):
            number_box_size = 22
            box_rect = pygame.Rect(x_offset, y_offset, number_box_size, number_box_size)
            pygame.draw.rect(self.screen, self.current_theme_color, box_rect, 1)
            
            num_surf = self.font_small.render(str(i), True, COLOR_WHITE)
            self.screen.blit(num_surf, num_surf.get_rect(center=box_rect.center).topleft)
            
            text_x_offset = x_offset + number_box_size + 8

            category_color = self.theme_colors['warning'] if event['category'] in ['Wildfires', 'Severe Storms'] else COLOR_WHITE
            
            cat_surf = self.font_small.render(f"[{event['category'].upper()}]", True, category_color)
            self.screen.blit(cat_surf, (text_x_offset, y_offset))
            
            title_text = event['title']
            if len(title_text) > 35:
                title_text = title_text[:32] + "..."
            title_surf = self.font_medium.render(title_text, True, COLOR_WHITE)
            self.screen.blit(title_surf, (text_x_offset, y_offset + line_height))

            y_offset += line_height * 2.5
            if y_offset > self.screen.get_height() - 50:
                break

    # ==============================================================================
    # == FIN DE LAS MODIFICACIONES
    # ==============================================================================

    def draw_asteroid_trajectory(self, cx, cy, radius, neo_data, color):
        """Draws a pseudo-3D trajectory line for the NEO."""
        if not neo_data:
            return

        # Simula una trayectoria simple de izquierda a derecha
        start_x, end_x = cx - radius * 2.5, cx + radius * 2.5
        
        # La altura de la trayectoria depende de la distancia de aproximación
        # Normalizamos la distancia para que siempre se vea bien
        miss_dist_km = neo_data.get('miss_distance_km', 1000000)
        # Un valor más bajo significa que pasa más cerca. Lo escalamos para la pantalla.
        pass_height = min(1.0, miss_dist_km / 5000000) * radius * 1.5
        start_y, end_y = cy - radius, cy + pass_height

        num_segments = 50
        for i in range(num_segments):
            # Interpola la posición del segmento
            t = i / (num_segments - 1)
            x1 = start_x + (end_x - start_x) * (i / num_segments)
            y1 = start_y + (end_y - start_y) * (i / num_segments)
            x2 = start_x + (end_x - start_x) * ((i + 1) / num_segments)
            y2 = start_y + (end_y - start_y) * ((i + 1) / num_segments)

            # --- El truco del Pseudo-3D ---
            # Simula una coordenada Z: negativo detrás de la esfera, positivo delante
            z = (x1 - cx) / (radius * 1.5) 
            
            is_behind = z**2 + ((y1 - cy)/radius)**2 < 1.1 # ¿Está el punto "detrás" del planeta?

            if is_behind:
                # Si está detrás, dibuja una línea punteada y más oscura
                draw_dashed_line(self.screen, color + (100,), (x1, y1), (x2, y2), 1, 4)
            else:
                # Si está delante, el grosor y brillo dependen de Z
                alpha = int(np.clip(100 + z * 155, 100, 255))
                width = int(np.clip(1 + z * 2, 1, 3))
                pygame.draw.line(self.screen, color + (alpha,), (x1, y1), (x2, y2), width)
    
    def draw_neo_hud(self, neo_data):
        """
        Render the NEO tracker HUD in the top-left column with concise threat and approach details.
        
        Parameters:
            neo_data (dict | None): Object containing NEO information or None if unavailable. When present, expected keys:
                - 'name' (str): Identifier of the NEO.
                - 'diameter_m' (number): Estimated diameter in meters.
                - 'velocity_kmh' (number): Relative velocity in kilometers per hour.
                - 'approach_date' (str): Approach datetime string (date portion is displayed).
                - 'miss_distance_km' (number): Closest approach distance in kilometers.
                - 'is_hazardous' (bool): Hazard flag used to highlight assessment.
        """
        margins = config.CONFIG['margins']
        x_offset = margins['left'] + 10
        y_offset = margins['top'] + 45 # Debajo del header

        title_surf = self.font_large.render("// DEEP SPACE THREAT ANALYSIS //", True, self.current_theme_color)
        self.screen.blit(title_surf, (x_offset, y_offset))
        y_offset += 30

        if not neo_data:
            status_surf = self.font_medium.render("...ACQUIRING TARGET DATA...", True, self.current_theme_color)
            self.screen.blit(status_surf, (x_offset, y_offset))
            return
            
        line_height = 18 # Un poco más compacto para que entre todo

        # --- Lógica de una sola columna ---
        is_hazardous = neo_data['is_hazardous']
        assessment_text = "!!! POTENTIAL HAZARD !!!" if is_hazardous else "[ NOMINAL ]"
        assessment_color = self.theme_colors['danger'] if is_hazardous else COLOR_WHITE

        # Combinamos toda la info en una sola lista de tuplas (etiqueta, valor, color_valor)
        info_lines = [
            ("ID:", neo_data['name'], COLOR_WHITE),
            ("DIAMETER:", f"~{neo_data['diameter_m']} METERS", COLOR_WHITE),
            ("VELOCITY:", f"{neo_data['velocity_kmh']:,} KM/H", COLOR_WHITE),
            ("APPROACH:", neo_data['approach_date'].split(" ")[0], COLOR_WHITE),
            ("MISS DISTANCE:", f"{neo_data['miss_distance_km']:,} KM", COLOR_WHITE),
            ("ASSESSMENT:", assessment_text, assessment_color)
        ]

        for label, value, value_color in info_lines:
            label_surf = self.font_small.render(label, True, self.current_theme_color)
            value_surf = self.font_medium.render(value, True, value_color)
            
            self.screen.blit(label_surf, (x_offset, y_offset))
            y_offset += line_height
            self.screen.blit(value_surf, (x_offset, y_offset))
            y_offset += line_height * 1.5 # Espacio extra entre pares de datos
    
    def draw_solar_system_map(self, neo_data):
        """
        Render a compact schematic solar system mini-map in the bottom-right corner of the screen.
        
        Renders a framed mini-map showing the Sun, scaled orbital rings, planet markers, and a stylized asteroid trajectory. When NEO data is provided, the asteroid path and current asteroid marker are drawn; the NEO's miss distance adjusts the trajectory's proximity to the planetary orbits and the marker color reflects hazard status.
        
        Parameters:
            neo_data (dict | None): Near-Earth object information used to plot the asteroid path. Expected keys:
                - 'miss_distance_km' (numeric): Distance in kilometers used to scale the trajectory's closeness to the orbits.
                - 'is_hazardous' (bool): If true, the asteroid marker is rendered using the danger theme color; otherwise a neutral color is used.
        """
        # Define el área para nuestro "mini-mapa"
        map_rect = pygame.Rect(400, 280, 220, 180) # Posición y tamaño en la esquina inferior derecha
        center_x, center_y = map_rect.centerx, map_rect.centery
        max_radius = map_rect.width // 2 - 10 # El radio máximo es ahora mucho más pequeño

        # Dibuja un recuadro para el mini-mapa
        pygame.draw.rect(self.screen, self.current_theme_color, map_rect, 1)
        map_title_surf = self.font_small.render("SYSTEM NAV-MAP", True, self.current_theme_color)
        self.screen.blit(map_title_surf, (map_rect.x + 5, map_rect.y + 2))
        
        # Dibuja el Sol
        pygame.draw.circle(self.screen, COLOR_YELLOW, (center_x, center_y), 5)

        # Dibuja órbitas y planetas (escalados al nuevo tamaño)
        orbit_radii = [max_radius * 0.3, max_radius * 0.5, max_radius * 0.75, max_radius * 0.95]
        planet_colors = [(165, 42, 42), (210, 180, 140), (0, 120, 255), (255, 69, 0)]
        for i, radius in enumerate(orbit_radii):
            pygame.draw.circle(self.screen, self.current_theme_color + (40,), (center_x, center_y), int(radius), 1)
            planet_x = center_x + radius * math.cos(self.planet_angles[i])
            planet_y = center_y + radius * math.sin(self.planet_angles[i])
            pygame.draw.circle(self.screen, planet_colors[i], (int(planet_x), int(planet_y)), 2)

        # Dibuja la trayectoria del asteroide (recalculada para el mini-mapa)
        if not neo_data:
            return

        miss_dist_km = neo_data.get('miss_distance_km', 5000000)
        closeness_factor = np.clip(1.0 - (miss_dist_km / 10000000), 0.1, 0.9)
        earth_orbit_radius = orbit_radii[2]

        # Puntos de la curva relativos al nuevo mapa
        p0 = (map_rect.left, map_rect.top + 20)
        p1 = (center_x + earth_orbit_radius * closeness_factor, center_y + 10)
        p2 = (map_rect.right - 10, map_rect.bottom)
        
        path_points = []
        for t_step in np.linspace(0, 1, 30): # Menos segmentos para un mapa más pequeño
            x = (1 - t_step)**2 * p0[0] + 2 * (1 - t_step) * t_step * p1[0] + t_step**2 * p2[0]
            y = (1 - t_step)**2 * p0[1] + 2 * (1 - t_step) * t_step * p1[1] + t_step**2 * p2[1]
            path_points.append((x, y))
        pygame.draw.lines(self.screen, self.current_theme_color + (80,), False, path_points, 1)

        t = self.asteroid_path_progress
        ast_x = (1 - t)**2 * p0[0] + 2 * (1 - t) * t * p1[0] + t**2 * p2[0]
        ast_y = (1 - t)**2 * p0[1] + 2 * (1 - t) * t * p1[1] + t**2 * p2[1]
        
        ast_color = self.theme_colors['danger'] if neo_data['is_hazardous'] else COLOR_YELLOW
        pygame.draw.circle(self.screen, ast_color, (int(ast_x), int(ast_y)), 2) # Un simple círculo para el asteroide

if __name__ == '__main__':
    app = SentinelApp()
    app.run()