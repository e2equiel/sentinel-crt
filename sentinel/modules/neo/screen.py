"""NEO tracker screen module rendering implementation."""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pygame

import config
from sentinel.core import ScreenModule
from sentinel.modules.common import draw_dashed_line

COLOR_WHITE = (220, 220, 220)
COLOR_YELLOW = (255, 255, 0)


class NeoTrackerModule(ScreenModule):
    slug = "neo_tracker"

    def on_show(self) -> None:
        if self.app:
            self.app.header_title_text = "S.E.N.T.I.N.E.L. // DEEP SPACE"

    def render(self, surface: pygame.Surface) -> None:  # pragma: no cover - Pygame rendering
        app = self.app
        if app is None:
            return

        neo_data = app.neo_tracker.get_closest_neo_data()
        sphere_center_x = surface.get_width() // 2
        sphere_center_y = surface.get_height() // 2 + 20
        sphere_radius = 120
        self._draw_vector_sphere(surface, sphere_center_x, sphere_center_y, sphere_radius, app.current_theme_color, app.sphere_rotation_angle)
        self._draw_asteroid_trajectory(surface, sphere_center_x, sphere_center_y, sphere_radius, neo_data, app.current_theme_color, app)
        self._draw_neo_hud(surface, neo_data, app)
        self._draw_solar_system_map(surface, neo_data, app)

    def update(self, dt: float) -> None:
        return

    # ------------------------------------------------------------------ helpers
    def _draw_vector_sphere(self, surface: pygame.Surface, x: int, y: int, radius: int, color, rotation_angle: float) -> None:
        num_long_lines = 12
        for i in range(num_long_lines):
            angle = (i / num_long_lines) * math.pi + rotation_angle
            ellipse_width = abs(int(radius * 2 * math.cos(angle)))
            if ellipse_width <= 2:
                continue
            rect = pygame.Rect(x - ellipse_width // 2, y - radius, ellipse_width, radius * 2)
            pygame.draw.ellipse(surface, color, rect, 1)

        num_lat_lines = 7
        for i in range(1, num_lat_lines):
            lat_y = y - radius + (i * (radius * 2) / num_lat_lines)
            dist_from_center = abs(y - lat_y)
            width_factor = math.sqrt(max(radius**2 - dist_from_center**2, 0)) / radius
            ellipse_width = int(radius * 2 * width_factor)
            rect = pygame.Rect(x - ellipse_width // 2, lat_y - 2, ellipse_width, 4)
            pygame.draw.ellipse(surface, color, rect, 1)

    def _draw_asteroid_trajectory(self, surface: pygame.Surface, cx: int, cy: int, radius: int, neo_data: Optional[dict], color, app) -> None:
        if not neo_data:
            return

        start_x = cx - radius * 2.5
        end_x = cx + radius * 2.5
        miss_dist_km = neo_data.get("miss_distance_km", 1_000_000)
        pass_height = min(1.0, miss_dist_km / 5_000_000) * radius * 1.5
        start_y = cy - radius
        end_y = cy + pass_height

        num_segments = 50
        for i in range(num_segments):
            x1 = start_x + (end_x - start_x) * (i / num_segments)
            y1 = start_y + (end_y - start_y) * (i / num_segments)
            x2 = start_x + (end_x - start_x) * ((i + 1) / num_segments)
            y2 = start_y + (end_y - start_y) * ((i + 1) / num_segments)

            z = (x1 - cx) / (radius * 1.5)
            is_behind = z**2 + ((y1 - cy) / radius) ** 2 < 1.1
            if is_behind:
                draw_dashed_line(surface, color + (100,), (x1, y1), (x2, y2), 1, 4)
            else:
                alpha = int(np.clip(100 + z * 155, 100, 255))
                width = int(np.clip(1 + z * 2, 1, 3))
                pygame.draw.line(surface, color + (alpha,), (x1, y1), (x2, y2), width)

    def _draw_neo_hud(self, surface: pygame.Surface, neo_data: Optional[dict], app) -> None:
        margins = config.CONFIG["margins"]
        x_offset = margins["left"] + 10
        y_offset = margins["top"] + 45

        title_surf = app.font_large.render("// DEEP SPACE THREAT ANALYSIS //", True, app.current_theme_color)
        surface.blit(title_surf, (x_offset, y_offset))
        y_offset += 30

        if not neo_data:
            status_surf = app.font_medium.render("...ACQUIRING TARGET DATA...", True, app.current_theme_color)
            surface.blit(status_surf, (x_offset, y_offset))
            return

        line_height = 18
        is_hazardous = neo_data["is_hazardous"]
        assessment_text = "!!! POTENTIAL HAZARD !!!" if is_hazardous else "[ NOMINAL ]"
        assessment_color = app.theme_colors["danger"] if is_hazardous else COLOR_WHITE

        info_lines = [
            ("ID:", neo_data["name"], COLOR_WHITE),
            ("DIAMETER:", f"~{neo_data['diameter_m']} METERS", COLOR_WHITE),
            ("VELOCITY:", f"{neo_data['velocity_kmh']:,} KM/H", COLOR_WHITE),
            ("APPROACH:", neo_data["approach_date"].split(" ")[0], COLOR_WHITE),
            ("MISS DISTANCE:", f"{neo_data['miss_distance_km']:,} KM", COLOR_WHITE),
            ("ASSESSMENT:", assessment_text, assessment_color),
        ]

        for label, value, value_color in info_lines:
            label_surf = app.font_small.render(label, True, app.current_theme_color)
            value_surf = app.font_medium.render(value, True, value_color)
            surface.blit(label_surf, (x_offset, y_offset))
            y_offset += line_height
            surface.blit(value_surf, (x_offset, y_offset))
            y_offset += line_height * 1.5

    def _draw_solar_system_map(self, surface: pygame.Surface, neo_data: Optional[dict], app) -> None:
        map_rect = pygame.Rect(400, 280, 220, 180)
        center_x = map_rect.centerx
        center_y = map_rect.centery
        max_radius = map_rect.width // 2 - 10

        pygame.draw.rect(surface, app.current_theme_color, map_rect, 1)
        map_title_surf = app.font_small.render("SYSTEM NAV-MAP", True, app.current_theme_color)
        surface.blit(map_title_surf, (map_rect.x + 5, map_rect.y + 2))

        pygame.draw.circle(surface, COLOR_YELLOW, (center_x, center_y), 5)

        orbit_radii = [max_radius * 0.3, max_radius * 0.5, max_radius * 0.75, max_radius * 0.95]
        planet_colors = [(165, 42, 42), (210, 180, 140), (0, 120, 255), (255, 69, 0)]
        for i, radius in enumerate(orbit_radii):
            pygame.draw.circle(surface, app.current_theme_color + (40,), (center_x, center_y), int(radius), 1)
            planet_x = center_x + radius * math.cos(app.planet_angles[i])
            planet_y = center_y + radius * math.sin(app.planet_angles[i])
            pygame.draw.circle(surface, planet_colors[i], (int(planet_x), int(planet_y)), 2)

        if not neo_data:
            return

        miss_dist_km = neo_data.get("miss_distance_km", 5_000_000)
        closeness_factor = np.clip(1.0 - (miss_dist_km / 10_000_000), 0.1, 0.9)
        earth_orbit_radius = orbit_radii[2]

        p0 = (map_rect.left, map_rect.top + 20)
        p1 = (center_x + earth_orbit_radius * closeness_factor, center_y + 10)
        p2 = (map_rect.right - 10, map_rect.bottom)

        path_points = []
        for t_step in np.linspace(0, 1, 30):
            x = (1 - t_step) ** 2 * p0[0] + 2 * (1 - t_step) * t_step * p1[0] + t_step**2 * p2[0]
            y = (1 - t_step) ** 2 * p0[1] + 2 * (1 - t_step) * t_step * p1[1] + t_step**2 * p2[1]
            path_points.append((x, y))
        pygame.draw.lines(surface, app.current_theme_color + (80,), False, path_points, 1)

        t = app.asteroid_path_progress
        ast_x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t**2 * p2[0]
        ast_y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t**2 * p2[1]
        ast_color = app.theme_colors["danger"] if neo_data["is_hazardous"] else COLOR_YELLOW
        pygame.draw.circle(surface, ast_color, (int(ast_x), int(ast_y)), 2)


__all__ = ["NeoTrackerModule"]
