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

def draw_diagonal_pattern(surface, color, rect, angle, spacing=5, line_width=1):
    """Draws a diagonal line pattern within a specific rectangular area."""
    # 1. Create a temporary surface large enough to cover the original rect after rotation.
    #    The length of the diagonal of the rect is a safe size.
    diagonal = int(math.hypot(rect.width, rect.height))
    temp_surface = pygame.Surface((diagonal, diagonal), pygame.SRCALPHA)

    # 2. Draw simple vertical lines onto the temporary surface.
    for x in range(0, diagonal, spacing):
        pygame.draw.line(
            temp_surface,
            color,
            (x, 0),
            (x, diagonal),
            line_width
        )

    # 3. Rotate the temporary surface to the desired angle.
    rotated_surface = pygame.transform.rotozoom(temp_surface, angle, 1)

    # 4. Calculate the position to blit the rotated surface so it's centered on the target rect.
    rotated_rect = rotated_surface.get_rect(center=rect.center)

    # 5. Blit the rotated surface onto the main screen, but clip it to the original rect's area.
    #    This is the key step to ensure the pattern only appears inside the rect.
    original_clip = surface.get_clip()
    surface.set_clip(rect)
    surface.blit(rotated_surface, rotated_rect)
    surface.set_clip(original_clip) # Restore the original clipping area

class SentinelApp:
    def __init__(self):
        pygame.init()
        # Use config dictionary for settings
        self.screen = pygame.display.set_mode((config.CONFIG["screen_width"], config.CONFIG["screen_height"]))
        pygame.display.set_caption("S.E.N.T.I.N.E.L. v1.0")
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
        
        # Application States
        self.current_screen = config.CONFIG["startup_screen"] if config.CONFIG["startup_screen"] != "auto" else "camera"
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
        self.current_theme_color = config.THEME_COLORS['default']
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
        
        self.calculate_layout()
        
        # Grid and Graph Resources
        self.grid_cell_size = 40
        self.patterns_green = {
            'dots': self.create_tiled_pattern_surface('dots', self.grid_cell_size, config.THEME_COLORS['default'] + (160,)),
            'lines': self.create_tiled_pattern_surface('lines', self.grid_cell_size, config.THEME_COLORS['default'] + (160,))
        }
        self.patterns_orange = {
            'dots': self.create_tiled_pattern_surface('dots', self.grid_cell_size, config.THEME_COLORS['warning'] + (160,)),
            'lines': self.create_tiled_pattern_surface('lines', self.grid_cell_size, config.THEME_COLORS['warning'] + (160,))
        }
        self.patterns_red = {
            'dots': self.create_tiled_pattern_surface('dots', self.grid_cell_size, config.THEME_COLORS['danger'] + (160,)),
            'lines': self.create_tiled_pattern_surface('lines', self.grid_cell_size, config.THEME_COLORS['danger'] + (160,))
        }
        self.zoom_grid_map = []; self.zoom_grid_update_timer = 0
        self.update_zoom_grid_map()
        self.graph_data = deque(maxlen=self.analysis_graph_rect.width)

        self.start_mqtt_client()
        self.start_video_capture()

        # Load map on startup if needed
        if self.current_screen == "radar":
            threading.Thread(target=self.update_map_tiles, daemon=True).start()

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
        threading.Thread(target=self.video_capture_thread, daemon=True).start()

    def video_capture_thread(self):
        reconnect_delay = 5
        while self.running:
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
            while self.running:
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
            if self.running: time.sleep(reconnect_delay)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.value == 0:
            print("Connected to MQTT broker!")
            self.mqtt_status = "CONNECTED"
            client.subscribe(config.CONFIG["frigate_topic"])
            client.subscribe(config.CONFIG["flight_topic"])
        else:
            print(f"Failed to connect to MQTT, code: {reason_code}")
            self.mqtt_status = f"FAILED ({reason_code.value})"

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        print(f"Disconnected from MQTT broker. Reason: {reason_code}")
        if self.running and reason_code is not None and reason_code.value != 0: 
            self.mqtt_status = "DISCONNECTED"

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
            if msg.topic == config.CONFIG["frigate_topic"]: 
                self.detection_buffer.append((time.time(), payload))
                with self.data_lock: self.mqtt_activity += 15.0 
            elif msg.topic == config.CONFIG["flight_topic"]: 
                self.handle_flight_data(payload)
                with self.data_lock: self.mqtt_activity += 5.0
        except json.JSONDecodeError: 
            print(f"Error decoding MQTT JSON from topic {msg.topic}.")
    
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
        """Downloads the aircraft photo."""
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
        while self.running:
            self.handle_events(), self.update(), self.draw()
            self.clock.tick(config.CONFIG["fps"])
        print("Closing application..."), self.mqtt_client.loop_stop(), self.mqtt_client.disconnect(), pygame.quit(), sys.exit()

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE): self.running = False
    
    def update(self):
        self.update_detections()
        self.update_alert_level()
        
        if self.current_screen == "camera":
            self.update_zoom_priority()
            self.update_zoom()
        
        # Screen switching logic with alert priority
        if config.CONFIG["startup_screen"] == "auto":
            if self.alert_level != "none":
                self.current_screen = "camera"
            elif self.active_flights:
                self.current_screen = "radar"
            elif self.current_screen == "radar" and time.time() > self.flight_screen_timer:
                self.current_screen = "camera"
        
        self.update_visual_effects()
        with self.data_lock:
            self.mqtt_activity *= 0.90
            graph_h = self.analysis_graph_rect.height
            new_y = (graph_h - 15) - self.mqtt_activity + (random.random() - 0.5) * 8
            self.graph_data.append(np.clip(new_y, 5, graph_h - 5))

    def update_alert_level(self):
        """Determines the current alert level based on detection zones."""
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
                self.current_theme_color = config.THEME_COLORS['danger']
                self.header_title_text = "DANGER"
            elif self.alert_level == "warning":
                self.current_theme_color = config.THEME_COLORS['warning']
                self.header_title_text = "WARNING"
            else:
                self.current_theme_color = config.THEME_COLORS['default']
                self.header_title_text = "S.E.N.T.I.N.E.L. v1.0"

    def update_visual_effects(self):
        now = time.time()
        self.spinner_angle += 4
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
        self.screen.fill(COLOR_BLACK)
        if config.CONFIG['show_header']:
            self.draw_header()
        
        if self.current_screen == "camera": self.draw_camera_view()
        elif self.current_screen == "radar": self.draw_radar_view()
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
        title_rect = title_surface.get_rect()
        self.screen.blit(title_surface, (header_rect.left, header_rect.top + 2))
        
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

        pattern_rect = pygame.Rect(title_rect.right + 14, header_rect.top + 6, sys_load_rect.left - (title_rect.right + 38), header_rect.height - 12)
        draw_diagonal_pattern(self.screen, color, pattern_rect, -45, 8, 4)

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
        """Draws all elements over the map: home base, planes, lines, etc."""
        home_pos = self.get_screen_pos_from_coords(config.CONFIG['map_latitude'], config.CONFIG['map_longitude'])
        
        pixels_per_meter = (self.visible_map_rect.width / 2) / config.CONFIG['map_radius_m']
        num_rings = config.CONFIG.get("map_distance_rings", 3)
        radius_step_m = config.CONFIG['map_radius_m'] / num_rings
        max_radius_px = int(config.CONFIG['map_radius_m'] * pixels_per_meter)

        panel_surface = pygame.Surface(self.map_area_rect.size, pygame.SRCALPHA)
        panel_surface.fill((0, 0, 0, 120)) 
        pygame.draw.rect(panel_surface, config.THEME_COLORS['default'], panel_surface.get_rect(), 1)
        self.screen.blit(panel_surface, self.map_area_rect.topleft)
        
        if config.CONFIG.get("map_radial_lines", False):
            cardinal_points = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}
            intermediate_points = {"NNE": 22.5, "ENE": 67.5, "ESE": 112.5, "SSE": 157.5, "SSW": 202.5, "WSW": 247.5, "WNW": 292.5, "NNW": 337.5}
            line_start_radius = 20
            start_radius_inter = max_radius_px - (radius_step_m * pixels_per_meter)
            
            # Draw SECTOR lines (at main cardinal points)
            for angle in cardinal_points.values():
                line_angle_rad = math.radians(angle - 90 - 22.5) # Offset to be sector boundaries
                start_x, start_y = home_pos[0] + line_start_radius * math.cos(line_angle_rad), home_pos[1] + line_start_radius * math.sin(line_angle_rad)
                end_x, end_y = home_pos[0] + start_radius_inter * math.cos(line_angle_rad), home_pos[1] + start_radius_inter * math.sin(line_angle_rad)
                pygame.draw.line(self.screen, COLOR_RING, (start_x, start_y), (end_x, end_y), 1)

            # Draw LABELS in the CENTER of the sectors (at cardinal points)
            for label, angle in cardinal_points.items():
                label_angle_rad = math.radians(angle - 90)
                label_surf = self.font_small.render(label, True, COLOR_RING)
                label_pos = (home_pos[0] + (max_radius_px + 15) * math.cos(label_angle_rad), home_pos[1] + (max_radius_px + 15) * math.sin(label_angle_rad))
                label_rect = label_surf.get_rect(center=label_pos)
                label_rect.clamp_ip(self.visible_map_rect) 
                self.screen.blit(label_surf, label_rect)
            
            # Draw intermediate lines and labels
            for label, angle in (intermediate_points | cardinal_points).items():
                line_angle_rad = math.radians(angle - 90 - 11.25)
                start_x, start_y = home_pos[0] + start_radius_inter * math.cos(line_angle_rad), home_pos[1] + start_radius_inter * math.sin(line_angle_rad)
                end_x, end_y = home_pos[0] + max_radius_px * math.cos(line_angle_rad), home_pos[1] + max_radius_px * math.sin(line_angle_rad)
                pygame.draw.line(self.screen, COLOR_RING, (start_x, start_y), (end_x, end_y), 1)
                
            for label, angle in intermediate_points.items():
                line_angle_rad = math.radians(angle - 90)
                label_surf = self.font_tiny.render(label, True, COLOR_RING)
                label_pos = (home_pos[0] + (max_radius_px + 15) * math.cos(line_angle_rad), home_pos[1] + (max_radius_px + 15) * math.sin(line_angle_rad))
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
            pygame.draw.rect(self.screen, config.THEME_COLORS['default'], home_rect, 1)
            pygame.draw.line(self.screen, config.THEME_COLORS['default'], (home_rect.left, home_rect.centery), (home_rect.right, home_rect.centery), 1)
            pygame.draw.line(self.screen, config.THEME_COLORS['default'], (home_rect.centerx, home_rect.top), (home_rect.centerx, home_rect.bottom), 1)

        closest_flight_pos = None
        for flight in self.active_flights:
            screen_pos = self.get_screen_pos_from_coords(flight.get('latitude'), flight.get('longitude'))
            if self.map_area_rect.collidepoint(screen_pos):
                is_closest = (flight == self.closest_flight)
                plane_size, color = (12, COLOR_YELLOW) if is_closest else (8, config.THEME_COLORS['default'])
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
        panel_surface = pygame.Surface(self.flight_panel_rect.size, pygame.SRCALPHA)
        panel_surface.fill((0, 0, 0, 180)) 
        pygame.draw.rect(panel_surface, config.THEME_COLORS['default'], panel_surface.get_rect(), 1)
        
        title_surf = self.font_medium.render("CLOSEST AIRCRAFT", True, COLOR_YELLOW)
        panel_surface.blit(title_surf, (10, 10))
        pygame.draw.line(panel_surface, config.THEME_COLORS['default'], (10, 35), (self.flight_panel_rect.width - 10, 35), 1)

        y_offset = 45
        with self.data_lock: flight, photo = self.closest_flight, self.closest_flight_photo_surface
        
        if not flight:
            panel_surface.blit(self.font_small.render("> NO TARGETS...", True, config.THEME_COLORS['default']), (10, y_offset))
        else:
            details = {
                "CALLSIGN:": flight.get('callsign', 'N/A').upper(), "MODEL:": flight.get('model', 'N/A'),
                "ALTITUDE:": f"{flight.get('altitude', 0)} FT", "SPEED:": f"{flight.get('speed', 0)} KTS",
                "HEADING:": f"{flight.get('track', 0)}°"
            }
            for label, value in details.items():
                panel_surface.blit(self.font_small.render(label, True, config.THEME_COLORS['default']), (10, y_offset))
                panel_surface.blit(self.font_medium.render(value, True, COLOR_WHITE), (10, y_offset + 14))
                y_offset += 36
            
            pygame.draw.line(panel_surface, config.THEME_COLORS['default'], (10, y_offset), (self.flight_panel_rect.width - 10, y_offset), 1)
            y_offset += 8
            panel_surface.blit(self.font_small.render("ROUTE:", True, config.THEME_COLORS['default']), (10, y_offset))
            route_text = f"{flight.get('airport_origin_code', 'N/A')} > {flight.get('airport_destination_code', 'N/A')}"
            panel_surface.blit(self.font_medium.render(route_text, True, COLOR_WHITE), (10, y_offset + 14))
            
            if photo:
                panel_w = self.flight_panel_rect.width - 20 
                photo_h = int(panel_w / (photo.get_width() / photo.get_height()))
                photo_rect = pygame.Rect(10, self.flight_panel_rect.height - photo_h - 10, panel_w, photo_h)
                scaled_photo = pygame.transform.scale(photo, photo_rect.size)
                panel_surface.blit(scaled_photo, photo_rect)
                pygame.draw.rect(panel_surface, config.THEME_COLORS['default'], photo_rect, 1)
            else:
                photo_rect = pygame.Rect(10, self.flight_panel_rect.height - 80 - 10, self.flight_panel_rect.width - 20, 80)
                no_img_surf = self.font_small.render("NO IMAGE DATA", True, config.THEME_COLORS['default'])
                panel_surface.blit(no_img_surf, no_img_surf.get_rect(center=photo_rect.center))
                pygame.draw.rect(panel_surface, config.THEME_COLORS['default'], photo_rect, 1)

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

if __name__ == '__main__':
    app = SentinelApp()
    app.run()
