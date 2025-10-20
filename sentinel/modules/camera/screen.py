"""Camera screen module rendering implementation."""

from __future__ import annotations

import time

import pygame

import config
from sentinel.core import ScreenModule
from sentinel.modules.common import draw_dashed_line


class CameraModule(ScreenModule):
    slug = "camera"

    def on_show(self) -> None:
        if self.app:
            self.app.header_title_text = "S.E.N.T.I.N.E.L. // CAMERA"

    def render(self, surface: pygame.Surface) -> None:  # pragma: no cover - Pygame rendering
        app = self.app
        if app is None:
            return

        self._draw_video_feed(surface, app)
        if app.show_zoom_grid:
            self._draw_zoom_grid(surface, app)
        self._draw_bounding_boxes(surface, app)
        self._draw_status_panel(surface, app)

    def update(self, dt: float) -> None:
        # Camera specific animations are still handled by the legacy app for now.
        return

    # ------------------------------------------------------------------ primitives
    def _draw_video_feed(self, surface: pygame.Surface, app) -> None:
        with app.data_lock:
            if app.current_video_frame:
                surface.blit(app.current_video_frame, app.main_area_rect.topleft)
            else:
                placeholder = app.font_medium.render(
                    "VIDEO FEED OFFLINE",
                    True,
                    app.current_theme_color,
                )
                surface.blit(placeholder, placeholder.get_rect(center=app.main_area_rect.center))
        pygame.draw.rect(surface, app.current_theme_color, app.main_area_rect, 2)

    def _draw_zoom_grid(self, surface: pygame.Surface, app) -> None:
        grid_surface = pygame.Surface(app.main_area_rect.size, pygame.SRCALPHA)

        if app.alert_level == "warning":
            patterns = app.patterns_orange
        elif app.alert_level == "danger":
            patterns = app.patterns_red
        else:
            patterns = app.patterns_green

        grid_color = app.current_theme_color + (160,)

        with app.data_lock:
            for r, row in enumerate(app.zoom_grid_map):
                for c, pattern_type in enumerate(row):
                    pos = (c * app.grid_cell_size, r * app.grid_cell_size)
                    if pattern_type == 1:
                        grid_surface.blit(patterns["dots"], pos)
                    elif pattern_type == 2:
                        grid_surface.blit(patterns["lines"], pos)

        for x in range(0, app.main_area_rect.width, app.grid_cell_size):
            pygame.draw.line(grid_surface, grid_color, (x, 0), (x, app.main_area_rect.height), 1)
        for y in range(0, app.main_area_rect.height, app.grid_cell_size):
            pygame.draw.line(grid_surface, grid_color, (0, y), (app.main_area_rect.width, y), 1)

        surface.blit(grid_surface, app.main_area_rect.topleft)

    def _draw_bounding_boxes(self, surface: pygame.Surface, app) -> None:
        with app.data_lock:
            if not app.active_detections:
                return
            zoom_rect = app.current_zoom_rect
            if zoom_rect.w == 0 or zoom_rect.h == 0:
                return
            for detection in app.active_detections.values():
                box = detection.get("box")
                if not box:
                    continue
                box_x_rel = box[0] - zoom_rect.x
                box_y_rel = box[1] - zoom_rect.y
                scale_x = app.main_area_rect.width / zoom_rect.w
                scale_y = app.main_area_rect.height / zoom_rect.h
                x1 = box_x_rel * scale_x
                y1 = box_y_rel * scale_y
                w = (box[2] - box[0]) * scale_x
                h = (box[3] - box[1]) * scale_y
                box_rect = pygame.Rect(app.main_area_rect.x + x1, app.main_area_rect.y + y1, w, h)
                clipped_box = box_rect.clip(app.main_area_rect)
                if clipped_box.width <= 0 or clipped_box.height <= 0:
                    continue
                pygame.draw.rect(surface, app.current_theme_color, clipped_box, 1)
                label = detection.get("label", "")
                score = detection.get("score", 0)
                label_surface = app.font_small.render(f"{label.upper()} [{score:.0%}]", True, app.current_theme_color)
                label_pos_y = box_rect.y - 18
                if label_pos_y < app.main_area_rect.y:
                    label_pos_y = clipped_box.y + 2
                surface.blit(label_surface, (clipped_box.x + 2, label_pos_y))

    def _draw_status_panel(self, surface: pygame.Surface, app) -> None:
        color = app.current_theme_color
        pygame.draw.rect(surface, color, app.status_panel_rect, 2)

        y_offset = app.col1_rect.y + 2
        row_height = 14
        camera_name = self.config.get("camera_name") or config.CONFIG.get("camera_name", "")
        texts = [
            ("MQTT LINK:", app.mqtt_status),
            ("VIDEO FEED:", app.video_status),
            ("CAMERA:", camera_name.upper()),
            ("LAST EVENT:", app.last_event_time),
            ("TARGET:", app.target_label),
            ("CONFIDENCE:", app.target_score),
        ]

        for index, (label, value) in enumerate(texts):
            y_pos = y_offset + index * row_height
            label_surface = app.font_small.render(label, True, color)
            label_rect = label_surface.get_rect()
            value_surface = app.font_small.render(str(value), True, (220, 220, 220))
            value_rect = value_surface.get_rect()
            label_rect.topleft = (app.col1_rect.x, y_pos)
            value_rect.topright = (app.col1_rect.right, y_pos)

            line_y = label_rect.centery
            start_x = label_rect.right + 4
            end_x = value_rect.left - 4
            if start_x < end_x:
                draw_dashed_line(surface, color, (start_x, line_y), (end_x, line_y), 1, 2)

            surface.blit(label_surface, label_rect)
            surface.blit(value_surface, value_rect)

        with app.data_lock:
            if app.snapshot_surface:
                surface.blit(app.snapshot_surface, app.col2_rect)
                self._draw_snapshot_scanner(surface, app)
            else:
                no_signal = app.font_small.render("NO SIGNAL", True, color)
                surface.blit(no_signal, no_signal.get_rect(center=app.col2_rect.center))

        pygame.draw.rect(surface, color, app.col2_rect, 1)

        scan_text = "> SCANNING FOR TARGETS"
        if int(time.time() * 2) % 2 == 0:
            scan_text += "_"
        surface.blit(app.font_small.render(scan_text, True, color), (app.col3_rect.x, app.col3_rect.y))
        self._draw_analysis_graph(surface, app)

    def _draw_snapshot_scanner(self, surface: pygame.Surface, app) -> None:
        scanner_surface = pygame.Surface(app.col2_rect.size, pygame.SRCALPHA)
        trail_color = app.current_theme_color + (25,)
        trail_width = 20
        if app.scanner_dir > 0:
            trail_rect = pygame.Rect(app.scanner_pos - trail_width, 0, trail_width, app.col2_rect.height)
        else:
            trail_rect = pygame.Rect(app.scanner_pos, 0, trail_width, app.col2_rect.height)
        scanner_surface.fill(trail_color, trail_rect)
        pygame.draw.line(scanner_surface, app.current_theme_color, (app.scanner_pos, 0), (app.scanner_pos, app.col2_rect.height), 2)
        surface.blit(scanner_surface, app.col2_rect.topleft)

    def _draw_analysis_graph(self, surface: pygame.Surface, app) -> None:
        graph_rect = app.analysis_graph_rect
        color = app.current_theme_color

        grid_surface = pygame.Surface(graph_rect.size, pygame.SRCALPHA)
        cell_size = 10
        for x in range(0, graph_rect.width, cell_size):
            pygame.draw.line(grid_surface, color + (100,), (x, 0), (x, graph_rect.height), 1)
        for y in range(0, graph_rect.height, cell_size):
            pygame.draw.line(grid_surface, color + (100,), (0, y), (graph_rect.width, y), 1)
        surface.blit(grid_surface, graph_rect.topleft)
        pygame.draw.rect(surface, color, graph_rect, 1)

        points = []
        with app.data_lock:
            for index, value in enumerate(app.graph_data):
                points.append((graph_rect.x + index, graph_rect.y + value))
        if len(points) > 1:
            pygame.draw.lines(surface, color, False, points, 1)


__all__ = ["CameraModule"]
