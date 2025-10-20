"""Radar screen module rendering implementation."""

from __future__ import annotations

import math
from typing import Any

import pygame

import config
from sentinel.core import ScreenModule
from sentinel.modules.common import draw_dashed_line

COLOR_WHITE = (220, 220, 220)
COLOR_YELLOW = (255, 255, 0)
COLOR_RING = (0, 255, 65, 70)


class RadarModule(ScreenModule):
    slug = "radar"

    def on_show(self) -> None:
        if self.app:
            self.app.header_title_text = "S.E.N.T.I.N.E.L. // RADAR"

    def render(self, surface: pygame.Surface) -> None:  # pragma: no cover - Pygame rendering
        app = self.app
        if app is None:
            return

        self._draw_map(surface, app)
        self._draw_flight_info_panel(surface, app)

    def update(self, dt: float) -> None:
        return

    # ------------------------------------------------------------------ helpers
    def _draw_map(self, surface: pygame.Surface, app) -> None:
        with app.data_lock:
            if app.map_surface:
                surface.set_clip(app.map_area_rect)
                surface.blit(
                    app.map_surface,
                    (app.map_area_rect.x + app.map_tile_offset[0], app.map_area_rect.y + app.map_tile_offset[1]),
                )
                self._draw_map_overlays(surface, app)
                surface.set_clip(None)
            else:
                placeholder = app.font_medium.render(app.map_status, True, app.current_theme_color)
                surface.blit(placeholder, placeholder.get_rect(center=app.map_area_rect.center))
        pygame.draw.rect(surface, app.current_theme_color, app.map_area_rect, 2)

    def _draw_map_overlays(self, surface: pygame.Surface, app) -> None:
        home_lat = self._cfg("map_latitude", 0.0)
        home_lon = self._cfg("map_longitude", 0.0)
        home_pos = self._screen_pos_from_coords(app, home_lat, home_lon)

        map_radius_m = float(self._cfg("map_radius_m", 15000)) or 1.0
        pixels_per_meter = (app.visible_map_rect.width / 2) / map_radius_m
        num_rings = int(self._cfg("map_distance_rings", 3) or 0)
        num_rings = max(1, num_rings)
        radius_step_m = map_radius_m / num_rings
        max_radius_px = int(map_radius_m * pixels_per_meter)

        panel_surface = pygame.Surface(app.map_area_rect.size, pygame.SRCALPHA)
        panel_surface.fill((0, 0, 0, 120))
        pygame.draw.rect(panel_surface, app.theme_colors["default"], panel_surface.get_rect(), 1)
        surface.blit(panel_surface, app.map_area_rect.topleft)

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
                label_surf = app.font_small.render(label, True, COLOR_RING)
                label_pos = (
                    home_pos[0] + (max_radius_px + 15) * math.cos(label_angle_rad),
                    home_pos[1] + (max_radius_px + 15) * math.sin(label_angle_rad),
                )
                label_rect = label_surf.get_rect(center=label_pos)
                label_rect.clamp_ip(app.visible_map_rect)
                surface.blit(label_surf, label_rect)

            for label, angle in intermediate_points_sorted:
                label_angle_rad = math.radians(angle - 90)
                label_surf = app.font_tiny.render(label, True, COLOR_RING)
                label_pos = (
                    home_pos[0] + (max_radius_px + 15) * math.cos(label_angle_rad),
                    home_pos[1] + (max_radius_px + 15) * math.sin(label_angle_rad),
                )
                label_rect = label_surf.get_rect(center=label_pos)
                label_rect.clamp_ip(app.visible_map_rect)
                surface.blit(label_surf, label_rect)

        for i in range(1, num_rings + 1):
            dist_m = i * radius_step_m
            radius_px = int(dist_m * pixels_per_meter)
            pygame.draw.circle(surface, COLOR_RING, (int(home_pos[0]), int(home_pos[1])), radius_px, 1)
            dist_km = dist_m / 1000
            label_text = f"{dist_km:.0f}km"
            label_surf = app.font_small.render(label_text, True, COLOR_RING)
            surface.blit(label_surf, (home_pos[0] + radius_px - label_surf.get_width() - 5, home_pos[1] - 15))

        if app.map_area_rect.collidepoint(home_pos):
            size = 8
            home_rect = pygame.Rect(home_pos[0] - size, home_pos[1] - size, size * 2, size * 2)
            pygame.draw.rect(surface, app.theme_colors["default"], home_rect, 1)
            pygame.draw.line(surface, app.theme_colors["default"], (home_rect.left, home_rect.centery), (home_rect.right, home_rect.centery), 1)
            pygame.draw.line(surface, app.theme_colors["default"], (home_rect.centerx, home_rect.top), (home_rect.centerx, home_rect.bottom), 1)

        closest_flight_pos = None
        for flight in app.active_flights:
            screen_pos = self._screen_pos_from_coords(app, flight.get("latitude"), flight.get("longitude"))
            if not app.map_area_rect.collidepoint(screen_pos):
                continue
            is_closest = flight == app.closest_flight
            plane_size, color = (12, COLOR_YELLOW) if is_closest else (8, app.theme_colors["default"])
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

        if closest_flight_pos and app.map_area_rect.collidepoint(home_pos):
            draw_dashed_line(surface, COLOR_YELLOW, home_pos, closest_flight_pos, dash_length=8)
            dist_text = f"{app.closest_flight.get('distance_km', 0):.1f} km"
            dist_surf = app.font_small.render(dist_text, True, COLOR_YELLOW)
            mid_point = ((home_pos[0] + closest_flight_pos[0]) / 2, (home_pos[1] + closest_flight_pos[1]) / 2)
            dist_rect = dist_surf.get_rect(center=mid_point)
            surface.blit(dist_surf, dist_rect)

    def _draw_flight_info_panel(self, surface: pygame.Surface, app) -> None:
        panel_surface = pygame.Surface(app.flight_panel_rect.size, pygame.SRCALPHA)
        panel_surface.fill((0, 0, 0, 180))
        pygame.draw.rect(panel_surface, app.theme_colors["default"], panel_surface.get_rect(), 1)

        title_surf = app.font_medium.render("CLOSEST AIRCRAFT", True, COLOR_YELLOW)
        panel_surface.blit(title_surf, (10, 10))
        pygame.draw.line(panel_surface, app.theme_colors["default"], (10, 35), (app.flight_panel_rect.width - 10, 35), 1)

        y_offset = 45
        with app.data_lock:
            flight = app.closest_flight
            photo = app.closest_flight_photo_surface

        if not flight:
            panel_surface.blit(
                app.font_small.render("> NO TARGETS...", True, app.theme_colors["default"]),
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
                panel_surface.blit(app.font_small.render(label, True, app.theme_colors["default"]), (10, y_offset))
                panel_surface.blit(app.font_medium.render(value, True, COLOR_WHITE), (10, y_offset + 14))
                y_offset += 36

            pygame.draw.line(panel_surface, app.theme_colors["default"], (10, y_offset), (app.flight_panel_rect.width - 10, y_offset), 1)
            y_offset += 8
            panel_surface.blit(app.font_small.render("ROUTE:", True, app.theme_colors["default"]), (10, y_offset))
            route_text = f"{flight.get('airport_origin_code', 'N/A')} > {flight.get('airport_destination_code', 'N/A')}"
            panel_surface.blit(app.font_medium.render(route_text, True, COLOR_WHITE), (10, y_offset + 14))

            if photo:
                panel_w = app.flight_panel_rect.width - 20
                photo_h = int(panel_w / (photo.get_width() / photo.get_height()))
                photo_rect = pygame.Rect(10, app.flight_panel_rect.height - photo_h - 10, panel_w, photo_h)
                scaled_photo = pygame.transform.scale(photo, photo_rect.size)
                panel_surface.blit(scaled_photo, photo_rect)
                pygame.draw.rect(panel_surface, app.theme_colors["default"], photo_rect, 1)
            else:
                photo_rect = pygame.Rect(10, app.flight_panel_rect.height - 90, app.flight_panel_rect.width - 20, 80)
                no_img = app.font_small.render("NO IMAGE DATA", True, app.theme_colors["default"])
                panel_surface.blit(no_img, no_img.get_rect(center=photo_rect.center))
                pygame.draw.rect(panel_surface, app.theme_colors["default"], photo_rect, 1)

        surface.blit(panel_surface, app.flight_panel_rect.topleft)

    def _screen_pos_from_coords(self, app, lat: float, lon: float):
        zoom = app.map_zoom_level
        center_tile_x, center_tile_y = app.map_center_tile
        offset_x, offset_y = app.map_tile_offset

        flight_tile_x, flight_tile_y = deg2num(lat, lon, zoom)
        flight_frac_x = (lon + 180.0) / 360.0 * (2 ** zoom) - flight_tile_x
        flight_frac_y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * (2 ** zoom) - flight_tile_y

        flight_pixel_x_in_tile = flight_frac_x * 256
        flight_pixel_y_in_tile = flight_frac_y * 256
        tile_diff_x = (flight_tile_x - (center_tile_x - app.map_width_tiles // 2)) * 256
        tile_diff_y = (flight_tile_y - (center_tile_y - app.map_height_tiles // 2)) * 256

        map_surf_x = tile_diff_x + flight_pixel_x_in_tile
        map_surf_y = tile_diff_y + flight_pixel_y_in_tile
        screen_x = app.map_area_rect.x + offset_x + map_surf_x
        screen_y = app.map_area_rect.y + offset_y + map_surf_y
        return screen_x, screen_y

    def _cfg(self, key: str, default: Any) -> Any:
        if isinstance(self.config, dict) and key in self.config:
            return self.config[key]
        return config.CONFIG.get(key, default)

def deg2num(lat_deg: float, lon_deg: float, zoom: int):
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return xtile, ytile


__all__ = ["RadarModule"]
