"""Radar-specific state and helper routines."""

from __future__ import annotations

import io
import math
import threading
import time
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import pygame
import requests

from sentinel.utils.geo import calculate_zoom_from_radius, deg2num, haversine_distance


class RadarController:
    """Manage map tiles, flight tracking, and associated assets."""

    def __init__(self, core_config: Mapping[str, object]) -> None:
        self._core_config = core_config
        self._lock = threading.RLock()
        self._map_surface: Optional[pygame.Surface] = None
        self._map_status = "NO DATA"
        self._map_center_tile = (0, 0)
        self._map_tile_offset = (0.0, 0.0)
        self._map_width_tiles = 0
        self._map_height_tiles = 0
        self._map_zoom_level = 0
        self._active_flights: List[Dict] = []
        self._closest_flight: Optional[Dict] = None
        self._closest_flight_photo_surface: Optional[pygame.Surface] = None
        self._last_closest_flight_id: Optional[str] = None
        self._flight_screen_timer = 0.0
        self._map_area_rect = pygame.Rect(0, 0, 1, 1)
        self._visible_map_rect = pygame.Rect(0, 0, 1, 1)
        self._flight_panel_rect = pygame.Rect(0, 0, 1, 1)

    # ------------------------------------------------------------------ configuration
    def configure_layout(
        self,
        map_rect: pygame.Rect,
        visible_rect: pygame.Rect,
        flight_panel_rect: pygame.Rect,
    ) -> None:
        with self._lock:
            self._map_area_rect = map_rect.copy()
            self._visible_map_rect = visible_rect.copy()
            self._flight_panel_rect = flight_panel_rect.copy()

    # ------------------------------------------------------------------ properties
    @property
    def map_surface(self) -> Optional[pygame.Surface]:
        with self._lock:
            return self._map_surface

    @property
    def map_status(self) -> str:
        with self._lock:
            return self._map_status

    @property
    def map_tile_offset(self) -> Tuple[float, float]:
        with self._lock:
            return self._map_tile_offset

    @property
    def map_center_tile(self) -> Tuple[int, int]:
        with self._lock:
            return self._map_center_tile

    @property
    def map_width_tiles(self) -> int:
        with self._lock:
            return self._map_width_tiles

    @property
    def map_height_tiles(self) -> int:
        with self._lock:
            return self._map_height_tiles

    @property
    def map_zoom_level(self) -> int:
        with self._lock:
            return self._map_zoom_level

    @property
    def active_flights(self) -> List[Dict]:
        with self._lock:
            return list(self._active_flights)

    @property
    def closest_flight(self) -> Optional[Dict]:
        with self._lock:
            return dict(self._closest_flight) if self._closest_flight else None

    @property
    def closest_flight_photo_surface(self) -> Optional[pygame.Surface]:
        with self._lock:
            return self._closest_flight_photo_surface

    @property
    def flight_panel_rect(self) -> pygame.Rect:
        with self._lock:
            return self._flight_panel_rect.copy()

    @property
    def map_area_rect(self) -> pygame.Rect:
        with self._lock:
            return self._map_area_rect.copy()

    @property
    def visible_map_rect(self) -> pygame.Rect:
        with self._lock:
            return self._visible_map_rect.copy()

    # ------------------------------------------------------------------ lifecycle
    def reset(self) -> None:
        with self._lock:
            self._map_surface = None
            self._map_status = "NO DATA"
            self._map_center_tile = (0, 0)
            self._map_tile_offset = (0.0, 0.0)
            self._map_width_tiles = 0
            self._map_height_tiles = 0
            self._map_zoom_level = 0
            self._active_flights = []
            self._closest_flight = None
            self._closest_flight_photo_surface = None
            self._last_closest_flight_id = None
        self._flight_screen_timer = 0.0

    # ------------------------------------------------------------------ flight data
    def handle_flights(self, flights: Sequence[Dict] | Dict | None) -> None:
        if isinstance(flights, dict):
            flight_list = [flights]
        elif isinstance(flights, Sequence):
            flight_list = list(flights)
        else:
            flight_list = []

        min_alt = float(self._core_config.get("min_flight_altitude_ft", 0))
        filtered = [
            f
            for f in flight_list
            if f.get("altitude") is not None and f.get("altitude") >= min_alt
        ]

        with self._lock:
            self._active_flights = filtered
            if not filtered:
                self._closest_flight = None
                self._last_closest_flight_id = None
                self._closest_flight_photo_surface = None
                return

            home_lat = float(self._core_config.get("map_latitude", 0.0))
            home_lon = float(self._core_config.get("map_longitude", 0.0))
            for flight in filtered:
                flight["distance_km"] = haversine_distance(
                    home_lat,
                    home_lon,
                    flight.get("latitude", 0.0),
                    flight.get("longitude", 0.0),
                )
            closest = min(filtered, key=lambda f: f.get("distance_km", math.inf))
            self._closest_flight = dict(closest)
            closest_id = closest.get("id")
            if closest_id != self._last_closest_flight_id:
                self._last_closest_flight_id = closest_id
                photo_url = closest.get("photo")
                if photo_url:
                    threading.Thread(
                        target=self.fetch_flight_photo,
                        args=(photo_url,),
                        daemon=True,
                    ).start()
                else:
                    self._closest_flight_photo_surface = None

        self._flight_screen_timer = time.time() + float(self._core_config.get("flight_screen_timeout", 10))
        if self.map_surface is None:
            threading.Thread(target=self.update_map_tiles, daemon=True).start()

    # ------------------------------------------------------------------ map handling
    def update_map_tiles(self) -> None:
        with self._lock:
            self._map_status = "LOADING..."
            map_rect = self._map_area_rect.copy()
            visible_rect = self._visible_map_rect.copy()
        lat = float(self._core_config.get("map_latitude", 0.0))
        lon = float(self._core_config.get("map_longitude", 0.0))
        zoom = calculate_zoom_from_radius(
            float(self._core_config.get("map_radius_m", 15000)),
            visible_rect.width,
            lat,
        )
        xtile, ytile = deg2num(lat, lon, zoom)
        width_tiles = math.ceil(map_rect.width / 256) + 2
        height_tiles = math.ceil(map_rect.height / 256) + 2
        map_surface = pygame.Surface((width_tiles * 256, height_tiles * 256))

        for dx in range(width_tiles):
            for dy in range(height_tiles):
                tile_x = xtile - (width_tiles // 2) + dx
                tile_y = ytile - (height_tiles // 2) + dy
                url = (
                    f"https://api.mapbox.com/styles/v1/{self._core_config.get('mapbox_user', '')}"
                    f"/{self._core_config.get('mapbox_style_id', '')}/tiles/256/{zoom}/{tile_x}/{tile_y}"
                    f"?access_token={self._core_config.get('mapbox_token', '')}"
                )
                try:
                    response = requests.get(url, timeout=3)
                    response.raise_for_status()
                    tile_image = pygame.image.load(io.BytesIO(response.content))
                    map_surface.blit(tile_image, (dx * 256, dy * 256))
                except (requests.RequestException, pygame.error):
                    continue

        frac_x = (lon + 180.0) / 360.0 * (2**zoom) - xtile
        frac_y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * (2**zoom) - ytile
        offset_x = (visible_rect.width / 2) - (frac_x * 256) - ((width_tiles // 2) * 256)
        offset_y = (visible_rect.height / 2) - (frac_y * 256) - ((height_tiles // 2) * 256)

        with self._lock:
            self._map_surface = map_surface
            self._map_status = "ONLINE"
            self._map_center_tile = (xtile, ytile)
            self._map_tile_offset = (offset_x, offset_y)
            self._map_width_tiles = width_tiles
            self._map_height_tiles = height_tiles
            self._map_zoom_level = zoom

    # ------------------------------------------------------------------ assets
    def fetch_flight_photo(self, url: str) -> None:
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            image = pygame.image.load(io.BytesIO(response.content))
        except (requests.RequestException, pygame.error) as exc:
            print(f"Error downloading aircraft photo: {exc}")
            with self._lock:
                self._closest_flight_photo_surface = None
            return
        with self._lock:
            self._closest_flight_photo_surface = image


__all__ = ["RadarController"]
