"""EONET globe screen module rendering implementation."""

from __future__ import annotations

import math
from typing import Iterable, Optional

import pygame

import config
from sentinel.core import ScreenModule
from sentinel.modules.common import draw_dashed_line

from .ascii_globe import ASCIIGlobe
from .tracker import EONETTracker

COLOR_WHITE = (220, 220, 220)
COLOR_YELLOW = (255, 255, 0)


class EONETGlobeModule(ScreenModule):
    slug = "eonet_globe"

    def __init__(self, config=None):
        super().__init__(config=config)
        self._ascii_globe: Optional[ASCIIGlobe] = None
        self._tracker: Optional[EONETTracker] = None
        self._globe_rotation_angle = 0.0

    def on_load(self) -> None:
        if not self.app:
            return
        screen = self.app.screen
        center = (screen.get_width() * 0.6, screen.get_height() / 2 + 20)
        radius = 160
        self._ascii_globe = ASCIIGlobe(
            screen.get_width(),
            screen.get_height(),
            radius,
            center,
        )
        self._tracker = EONETTracker()
        self._tracker.start_periodic_fetch(interval_hours=1)

    def on_show(self) -> None:
        if self.app:
            self.app.header_title_text = "S.E.N.T.I.N.E.L. // EONET"

    def on_unload(self) -> None:
        self._ascii_globe = None
        self._tracker = None

    def render(self, surface: pygame.Surface) -> None:  # pragma: no cover - Pygame rendering
        app = self.app
        if app is None or self._ascii_globe is None or self._tracker is None:
            return

        color = app.current_theme_color
        events = self._tracker.get_events()
        self._ascii_globe.draw(surface, app.font_tiny, color)

        if events:
            for index, event in enumerate(events, 1):
                coords = event.get("coordinates")
                if not coords or len(coords) != 2:
                    continue
                lon, lat = coords
                lon_rad = math.radians(lon) + self._globe_rotation_angle
                lat_rad = math.radians(lat)
                x3d = math.cos(lat_rad) * math.cos(lon_rad)
                y3d = math.sin(lat_rad)
                z3d = -math.cos(lat_rad) * math.sin(lon_rad)
                if z3d <= -0.1:
                    continue
                globe_center_x, globe_center_y = self._ascii_globe.center_x, self._ascii_globe.center_y
                globe_radius = self._ascii_globe.radius
                screen_x = int(globe_center_x + globe_radius * x3d)
                screen_y = int(globe_center_y - globe_radius * y3d)
                dx = screen_x - globe_center_x
                dy = screen_y - globe_center_y
                dist = math.hypot(dx, dy)
                if dist == 0:
                    continue
                projection_dist = 40
                end_line_x = screen_x + (dx / dist) * projection_dist
                end_line_y = screen_y + (dy / dist) * projection_dist
                tag_topleft = self._get_hud_tag_topleft(app, (end_line_x, end_line_y), str(index))
                self._draw_hud_tag(surface, app, tag_topleft, str(index), color)
                draw_dashed_line(surface, color, (screen_x, screen_y), (end_line_x, end_line_y))
                alpha = int(100 + 155 * max(z3d, 0))
                pygame.draw.circle(surface, COLOR_YELLOW + (alpha,), (screen_x, screen_y), 4)

        self._draw_eonet_hud(surface, events or [])

    def update(self, dt: float) -> None:
        if self._ascii_globe is None:
            return
        self._globe_rotation_angle = (self._globe_rotation_angle + 0.008) % (2 * math.pi)
        self._ascii_globe.update(angle_x=0.0, angle_y=self._globe_rotation_angle)

    # ------------------------------------------------------------------ helpers
    def _get_hud_tag_topleft(self, app, center_pos, text: str):
        text_surf = app.font_tiny.render(text, True, COLOR_WHITE)
        padding = 4
        tag_width = text_surf.get_width() + padding * 2
        tag_height = text_surf.get_height() + padding * 2
        return (center_pos[0] - tag_width / 2, center_pos[1] - tag_height / 2)

    def _draw_hud_tag(self, surface: pygame.Surface, app, topleft_pos, text: str, color) -> None:
        text_surf = app.font_tiny.render(text, True, COLOR_WHITE)
        padding = 4
        bg_rect = pygame.Rect(
            topleft_pos[0],
            topleft_pos[1],
            text_surf.get_width() + padding * 2,
            text_surf.get_height() + padding * 2,
        )
        bg_surf = pygame.Surface(bg_rect.size, pygame.SRCALPHA)
        bg_surf.fill((0, 0, 0, 180))
        surface.blit(bg_surf, bg_rect.topleft)
        surface.blit(text_surf, (bg_rect.x + padding, bg_rect.y + padding))
        pygame.draw.rect(surface, color, bg_rect, 1)

    def _draw_eonet_hud(self, surface: pygame.Surface, events: Iterable[dict]) -> None:
        margins = config.CONFIG["margins"]
        x_offset = margins["left"] + 20
        y_offset = margins["top"] + 60
        title_surf = self.app.font_large.render("// GLOBAL EVENT MONITOR //", True, self.app.current_theme_color)
        surface.blit(title_surf, (x_offset, y_offset))
        y_offset += 30

        if not events:
            status_surf = self.app.font_medium.render("...SCANNING FOR GLOBAL EVENTS...", True, self.app.current_theme_color)
            surface.blit(status_surf, (x_offset, y_offset))
            return

        max_events_to_show = 8
        line_height = 20

        for index, event in enumerate(events[:max_events_to_show], 1):
            number_box_size = 22
            box_rect = pygame.Rect(x_offset, y_offset, number_box_size, number_box_size)
            pygame.draw.rect(surface, self.app.current_theme_color, box_rect, 1)
            num_surf = self.app.font_small.render(str(index), True, COLOR_WHITE)
            surface.blit(num_surf, num_surf.get_rect(center=box_rect.center).topleft)

            text_x_offset = x_offset + number_box_size + 8
            category_color = (
                self.app.theme_colors["warning"]
                if event.get("category") in {"Wildfires", "Severe Storms"}
                else COLOR_WHITE
            )
            cat_surf = self.app.font_small.render(f"[{event.get('category', '').upper()}]", True, category_color)
            surface.blit(cat_surf, (text_x_offset, y_offset))

            title_text = event.get("title", "")
            if len(title_text) > 35:
                title_text = title_text[:32] + "..."
            title_surf = self.app.font_medium.render(title_text, True, COLOR_WHITE)
            surface.blit(title_surf, (text_x_offset, y_offset + line_height))

            y_offset += line_height * 2.5
            if y_offset > surface.get_height() - 50:
                break


__all__ = ["EONETGlobeModule"]
