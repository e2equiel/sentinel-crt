"""Radar screen module rendering implementation."""

from __future__ import annotations

import math
import threading
from typing import Any, Optional

import pygame

import config
from sentinel.core import ScreenModule
from sentinel.modules.common import draw_dashed_line
from sentinel.utils.geo import deg2num

from .controller import RadarController

COLOR_WHITE = (220, 220, 220)
COLOR_YELLOW = (255, 255, 0)
COLOR_RING = (0, 255, 65, 70)


class RadarModule(ScreenModule):
    slug = "radar"

    def __init__(self, config: Optional[dict] = None) -> None:
        super().__init__(config=config)
        self.controller: Optional[RadarController] = None
        self._subscriptions: list[tuple[str, object]] = []
        self.map_area_rect = pygame.Rect(0, 0, 1, 1)
        self.visible_map_rect = pygame.Rect(0, 0, 1, 1)
        self.flight_panel_rect = pygame.Rect(0, 0, 1, 1)
        self._last_state_flights = 0

    # ------------------------------------------------------------------ lifecycle
    def on_load(self) -> None:
        if not self.app:
            return
        self.controller = RadarController(self.app.core_settings)
        self._setup_layout()
        bus = getattr(self.app, "event_bus", None)
        if bus:
            self._subscriptions = [
                ("services.mqtt.flights", bus.subscribe("services.mqtt.flights", self._handle_flights)),
            ]
        threading.Thread(target=self.controller.update_map_tiles, daemon=True).start()

    def on_unload(self) -> None:
        bus = getattr(self.app, "event_bus", None)
        if bus:
            for event, handler in self._subscriptions:
                bus.unsubscribe(event, handler)
        self._subscriptions = []
        if self.controller:
            self.controller.reset()
        self.controller = None

    def on_show(self) -> None:
        if self.app:
            self.app.header_title_text = "S.E.N.T.I.N.E.L. // RADAR"
        if self.controller:
            threading.Thread(target=self.controller.update_map_tiles, daemon=True).start()

    # ------------------------------------------------------------------ event handlers
    def _handle_flights(self, payload) -> None:
        if not self.controller:
            return
        self.controller.handle_flights(payload)

    # ------------------------------------------------------------------ runtime
    def update(self, dt: float) -> None:
        if not self.controller or not self.app:
            return
        flights = self.controller.active_flights
        if flights:
            count = len(flights)
            if count != self._last_state_flights:
                self.report_state("air-traffic", metadata={"count": count})
                self._last_state_flights = count
        else:
            if self._last_state_flights:
                self.report_state(None)
                self._last_state_flights = 0

    def render(self, surface: pygame.Surface) -> None:  # pragma: no cover - Pygame rendering
        controller = self.controller
        if not controller or not self.app:
            return

        self._draw_map(surface, controller)
        self._draw_flight_info_panel(surface, controller)

    # ------------------------------------------------------------------ layout
    def _setup_layout(self) -> None:
        if not self.app:
            return
        cfg = config.CONFIG
        margins = cfg['margins']
        header_height = 35 if cfg.get('show_header', True) else 0
        top_offset = margins['top'] + header_height
        available_width = cfg["screen_width"] - (margins['left'] + margins['right'])

        self.map_area_rect = pygame.Rect(
            margins['left'],
            top_offset,
            available_width,
            cfg["screen_height"] - top_offset - margins['bottom'],
        )
        flight_panel_width = 180
        self.flight_panel_rect = pygame.Rect(self.map_area_rect.right - flight_panel_width, self.map_area_rect.top, flight_panel_width, self.map_area_rect.height)
        self.visible_map_rect = pygame.Rect(self.map_area_rect.topleft, (self.flight_panel_rect.left - self.map_area_rect.left, self.map_area_rect.height))

        if self.controller:
            self.controller.configure_layout(self.map_area_rect, self.visible_map_rect, self.flight_panel_rect)

    # ------------------------------------------------------------------ helpers
    def _draw_map(self, surface: pygame.Surface, controller: RadarController) -> None:
        map_surface = controller.map_surface
        map_status = controller.map_status
        offset = controller.map_tile_offset
        if map_surface:
            surface.set_clip(self.map_area_rect)
            surface.blit(
                map_surface,
                (self.map_area_rect.x + offset[0], self.map_area_rect.y + offset[1]),
            )
            self._draw_map_overlays(surface, controller)
            surface.set_clip(None)
        else:
            placeholder = self.app.font_medium.render(map_status, True, self.app.current_theme_color)
            surface.blit(placeholder, placeholder.get_rect(center=self.map_area_rect.center))
        pygame.draw.rect(surface, self.app.current_theme_color, self.map_area_rect, 2)

    def _draw_map_overlays(self, surface: pygame.Surface, controller: RadarController) -> None:
        home_lat = self._cfg("map_latitude", 0.0)
        home_lon = self._cfg("map_longitude", 0.0)
        home_pos = self._screen_pos_from_coords(controller, home_lat, home_lon)

        map_radius_m = float(self._cfg("map_radius_m", 15000)) or 1.0
        pixels_per_meter = (self.visible_map_rect.width / 2) / map_radius_m
        num_rings = int(self._cfg("map_distance_rings", 3) or 0)
        num_rings = max(1, num_rings)
        radius_step_m = map_radius_m / num_rings
        max_radius_px = int(map_radius_m * pixels_per_meter)

        panel_surface = pygame.Surface(self.map_area_rect.size, pygame.SRCALPHA)
        panel_surface.fill((0, 0, 0, 120))
        pygame.draw.rect(panel_surface, self.app.theme_colors["default"], panel_surface.get_rect(), 1)
        surface.blit(panel_surface, self.map_area_rect.topleft)

        if bool(self._cfg("map_radial_lines", False)):
            cardinal_points = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}
            intermediate_points = {
                "NNE": 22.5,
                "ENE": 67.5,
                "ESE": 112.5,
                "SSE": 157.5,
                "SSW": 202.5,
                "WSW": 247.5,
                "WNW": 292.5,
                "NNW": 337.5,
            }

            all_points_sorted = sorted((cardinal_points | intermediate_points).items(), key=lambda item: item[1])
            cardinal_points_sorted = sorted(cardinal_points.items(), key=lambda item: item[1])
            intermediate_points_sorted = sorted(intermediate_points.items(), key=lambda item: item[1])

            line_start_radius = 20
            start_radius_inter = max_radius_px - (radius_step_m * pixels_per_meter)

            for _, angle in cardinal_points_sorted:
                line_angle_rad = math.radians(angle - 90 - 22.5)
                start_x = home_pos[0] + line_start_radius * math.cos(line_angle_rad)
                start_y = home_pos[1] + line_start_radius * math.sin(line_angle_rad)
                end_x = home_pos[0] + start_radius_inter * math.cos(line_angle_rad)
                end_y = home_pos[1] + start_radius_inter * math.sin(line_angle_rad)
                pygame.draw.line(surface, COLOR_RING, (start_x, start_y), (end_x, end_y), 1)

            for _, angle in all_points_sorted:
                line_angle_rad = math.radians(angle - 90 - 11.25)
                start_x = home_pos[0] + start_radius_inter * math.cos(line_angle_rad)
                start_y = home_pos[1] + start_radius_inter * math.sin(line_angle_rad)
                end_x = home_pos[0] + max_radius_px * math.cos(line_angle_rad)
                end_y = home_pos[1] + max_radius_px * math.sin(line_angle_rad)
                pygame.draw.line(surface, COLOR_RING, (start_x, start_y), (end_x, end_y), 1)

            for label, angle in cardinal_points_sorted:
                label_angle_rad = math.radians(angle - 90)
                label_surf = self.app.font_small.render(label, True, COLOR_RING)
                label_pos = (
                    home_pos[0] + (max_radius_px + 15) * math.cos(label_angle_rad),
                    home_pos[1] + (max_radius_px + 15) * math.sin(label_angle_rad),
                )
                label_rect = label_surf.get_rect(center=label_pos)
                label_rect.clamp_ip(self.visible_map_rect)
                surface.blit(label_surf, label_rect)

            for label, angle in intermediate_points_sorted:
                label_angle_rad = math.radians(angle - 90)
                label_surf = self.app.font_tiny.render(label, True, COLOR_RING)
                label_pos = (
                    home_pos[0] + (max_radius_px + 15) * math.cos(label_angle_rad),
                    home_pos[1] + (max_radius_px + 15) * math.sin(label_angle_rad),
                )
                label_rect = label_surf.get_rect(center=label_pos)
                label_rect.clamp_ip(self.visible_map_rect)
                surface.blit(label_surf, label_rect)

        for i in range(1, num_rings + 1):
            dist_m = i * radius_step_m
            radius_px = int(dist_m * pixels_per_meter)
            pygame.draw.circle(surface, COLOR_RING, (int(home_pos[0]), int(home_pos[1])), radius_px, 1)
            dist_km = dist_m / 1000
            label_text = f"{dist_km:.0f}km"
            label_surf = self.app.font_small.render(label_text, True, COLOR_RING)
            surface.blit(label_surf, (home_pos[0] + radius_px - label_surf.get_width() - 5, home_pos[1] - 15))

        if self.map_area_rect.collidepoint(home_pos):
            size = 8
            home_rect = pygame.Rect(home_pos[0] - size, home_pos[1] - size, size * 2, size * 2)
            pygame.draw.rect(surface, self.app.theme_colors["default"], home_rect, 1)
            pygame.draw.line(surface, self.app.theme_colors["default"], (home_rect.left, home_rect.centery), (home_rect.right, home_rect.centery), 1)
            pygame.draw.line(surface, self.app.theme_colors["default"], (home_rect.centerx, home_rect.top), (home_rect.centerx, home_rect.bottom), 1)

        closest_flight_pos = None
        flights = controller.active_flights
        closest_flight = controller.closest_flight

        for flight in flights:
            screen_pos = self._screen_pos_from_coords(controller, flight.get("latitude"), flight.get("longitude"))
            if not self.map_area_rect.collidepoint(screen_pos):
                continue
            is_closest = closest_flight and flight.get("id") == closest_flight.get("id")
            plane_size, color = (12, COLOR_YELLOW) if is_closest else (8, self.app.theme_colors["default"])
            angle = math.radians(flight.get("track", 0) - 90)
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            points = [(-plane_size, -plane_size // 2), (plane_size, 0), (-plane_size, plane_size // 2)]
            rotated_points = [
                (px * cos_a - py * sin_a + screen_pos[0], px * sin_a + py * cos_a + screen_pos[1])
                for px, py in points
            ]
            pygame.draw.polygon(surface, color, rotated_points)
            if is_closest:
                closest_flight_pos = screen_pos
                pygame.draw.rect(surface, COLOR_YELLOW, (screen_pos[0] - 15, screen_pos[1] - 15, 30, 30), 1)

        if closest_flight_pos and self.map_area_rect.collidepoint(home_pos) and closest_flight:
            draw_dashed_line(surface, COLOR_YELLOW, home_pos, closest_flight_pos, dash_length=8)
            dist_text = f"{closest_flight.get('distance_km', 0):.1f} km"
            dist_surf = self.app.font_small.render(dist_text, True, COLOR_YELLOW)
            mid_point = ((home_pos[0] + closest_flight_pos[0]) / 2, (home_pos[1] + closest_flight_pos[1]) / 2)
            dist_rect = dist_surf.get_rect(center=mid_point)
            surface.blit(dist_surf, dist_rect)

    def _draw_flight_info_panel(self, surface: pygame.Surface, controller: RadarController) -> None:
        panel_surface = pygame.Surface(self.flight_panel_rect.size, pygame.SRCALPHA)
        panel_surface.fill((0, 0, 0, 180))
        pygame.draw.rect(panel_surface, self.app.theme_colors["default"], panel_surface.get_rect(), 1)

        title_surf = self.app.font_medium.render("CLOSEST AIRCRAFT", True, COLOR_YELLOW)
        panel_surface.blit(title_surf, (10, 10))
        pygame.draw.line(panel_surface, self.app.theme_colors["default"], (10, 35), (self.flight_panel_rect.width - 10, 35), 1)

        y_offset = 45
        flight = controller.closest_flight
        photo = controller.closest_flight_photo_surface

        if not flight:
            panel_surface.blit(
                self.app.font_small.render("> NO TARGETS...", True, self.app.theme_colors["default"]),
                (10, y_offset),
            )
        else:
            details = {
                "CALLSIGN:": flight.get("callsign", "N/A").upper(),
                "MODEL:": flight.get("model", "N/A"),
                "ALTITUDE:": f"{flight.get('altitude', 0)} FT",
                "SPEED:": f"{flight.get('speed', 0)} KTS",
                "HEADING:": f"{flight.get('track', 0)}°",
            }
            for label, value in details.items():
                panel_surface.blit(self.app.font_small.render(label, True, self.app.theme_colors["default"]), (10, y_offset))
                panel_surface.blit(self.app.font_medium.render(value, True, COLOR_WHITE), (10, y_offset + 14))
                y_offset += 36

            pygame.draw.line(panel_surface, self.app.theme_colors["default"], (10, y_offset), (self.flight_panel_rect.width - 10, y_offset), 1)
            y_offset += 8
            panel_surface.blit(self.app.font_small.render("ROUTE:", True, self.app.theme_colors["default"]), (10, y_offset))
            route_text = f"{flight.get('airport_origin_code', 'N/A')} > {flight.get('airport_destination_code', 'N/A')}"
            panel_surface.blit(self.app.font_medium.render(route_text, True, COLOR_WHITE), (10, y_offset + 14))

            if photo:
                panel_w = self.flight_panel_rect.width - 20
                photo_h = int(panel_w / (photo.get_width() / photo.get_height()))
                photo_rect = pygame.Rect(10, self.flight_panel_rect.height - photo_h - 10, panel_w, photo_h)
                scaled_photo = pygame.transform.scale(photo, photo_rect.size)
                panel_surface.blit(scaled_photo, photo_rect)
                pygame.draw.rect(panel_surface, self.app.theme_colors["default"], photo_rect, 1)
            else:
                photo_rect = pygame.Rect(10, self.flight_panel_rect.height - 90, self.flight_panel_rect.width - 20, 80)
                no_img = self.app.font_small.render("NO IMAGE DATA", True, self.app.theme_colors["default"])
                panel_surface.blit(no_img, no_img.get_rect(center=photo_rect.center))
                pygame.draw.rect(panel_surface, self.app.theme_colors["default"], photo_rect, 1)

        surface.blit(panel_surface, self.flight_panel_rect.topleft)

    def _screen_pos_from_coords(self, controller: RadarController, lat: float, lon: float):
        zoom = controller.map_zoom_level
        center_tile_x, center_tile_y = controller.map_center_tile
        offset_x, offset_y = controller.map_tile_offset

        flight_tile_x, flight_tile_y = deg2num(lat, lon, zoom)
        flight_frac_x = (lon + 180.0) / 360.0 * (2 ** zoom) - flight_tile_x
        flight_frac_y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * (2 ** zoom) - flight_tile_y

        flight_pixel_x_in_tile = flight_frac_x * 256
        flight_pixel_y_in_tile = flight_frac_y * 256
        tile_diff_x = (flight_tile_x - (center_tile_x - controller.map_width_tiles // 2)) * 256
        tile_diff_y = (flight_tile_y - (center_tile_y - controller.map_height_tiles // 2)) * 256

        map_surf_x = tile_diff_x + flight_pixel_x_in_tile
        map_surf_y = tile_diff_y + flight_pixel_y_in_tile
        screen_x = self.map_area_rect.x + offset_x + map_surf_x
        screen_y = self.map_area_rect.y + offset_y + map_surf_y
        return screen_x, screen_y

    def _cfg(self, key: str, default: Any) -> Any:
        if isinstance(self.config, dict) and key in self.config:
            return self.config[key]
        return config.CONFIG.get(key, default)


__all__ = ["RadarModule"]
