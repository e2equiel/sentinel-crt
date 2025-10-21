from __future__ import annotations

import random
import time
from collections import deque
from typing import Optional

import pygame

import config
from sentinel.core import ScreenModule
from sentinel.modules.common import draw_dashed_line

from .controller import CameraController


def _create_tiled_pattern_surface(pattern_type: str, size: int, color) -> pygame.Surface:
    base_pattern_size = 10
    base_surface = pygame.Surface((base_pattern_size + 1, base_pattern_size), pygame.SRCALPHA)
    if pattern_type == 'dots':
        pygame.draw.circle(base_surface, color, (base_pattern_size // 2, base_pattern_size // 2), 1)
    elif pattern_type == 'lines':
        pygame.draw.line(base_surface, color, (0, base_pattern_size), (base_pattern_size, 0), 1)
    tiled_surface = pygame.Surface((size, size), pygame.SRCALPHA)
    for x in range(0, size, base_pattern_size):
        for y in range(0, size, base_pattern_size):
            tiled_surface.blit(base_surface, (x, y))
    return tiled_surface


class CameraModule(ScreenModule):
    slug = "camera"

    def __init__(self, config: Optional[dict] = None) -> None:
        super().__init__(config=config)
        self.controller: Optional[CameraController] = None
        self._subscriptions: list[tuple[str, object]] = []
        self._graph_data: deque[float] = deque()
        self._mqtt_activity = 0.0
        self._mqtt_status = "CONNECTING..."
        self._video_status = "INITIALIZING"
        self._last_alert_level = "none"
        self._scanner_pos = 0
        self._scanner_dir = 2
        self.grid_cell_size = 40
        self.patterns_green: dict[str, pygame.Surface] = {}
        self.patterns_orange: dict[str, pygame.Surface] = {}
        self.patterns_red: dict[str, pygame.Surface] = {}

    # ------------------------------------------------------------------ lifecycle
    def on_load(self) -> None:
        if not self.app:
            return
        self.controller = CameraController(self.app.core_settings)
        self._setup_layout()
        self._graph_data = deque(maxlen=self.analysis_graph_rect.width)
        bus = getattr(self.app, "event_bus", None)
        if bus:
            self._subscriptions = [
                ("services.mqtt.detection", bus.subscribe("services.mqtt.detection", self._handle_detection)),
                ("services.mqtt.status", bus.subscribe("services.mqtt.status", self._handle_mqtt_status)),
                ("services.video.frame", bus.subscribe("services.video.frame", self._handle_video_frame)),
                ("services.video.status", bus.subscribe("services.video.status", self._handle_video_status)),
            ]

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
            self.app.header_title_text = "S.E.N.T.I.N.E.L. // CAMERA"

    # ------------------------------------------------------------------ event handlers
    def _handle_detection(self, payload) -> None:
        if not self.controller or not isinstance(payload, dict):
            return
        self.controller.queue_detection(payload)
        self._mqtt_activity += 15.0

    def _handle_mqtt_status(self, status: str) -> None:
        if isinstance(status, str):
            self._mqtt_status = status

    def _handle_video_status(self, status: str) -> None:
        if isinstance(status, str):
            self._video_status = status

    def _handle_video_frame(self, payload) -> None:
        if not self.controller or not isinstance(payload, dict):
            return
        frame = payload.get("frame")
        if frame is None:
            return
        self.controller.process_frame(frame)

    # ------------------------------------------------------------------ runtime
    def update(self, dt: float) -> None:
        if not self.controller:
            return
        on_camera_screen = bool(self.active)
        self.controller.update(on_camera_screen=on_camera_screen)

        level = self.controller.alert_level
        if self.app and level != self._last_alert_level:
            self._last_alert_level = level
            self.app.event_bus.publish("ui.alert", {"level": level})
            if level and level != "none":
                self.report_state(level, metadata={"source": "alerts"})
            else:
                self.report_state(None)

        self._mqtt_activity *= 0.90
        if self.analysis_graph_rect.width > 0:
            graph_h = self.analysis_graph_rect.height
            new_y = (graph_h - 15) - self._mqtt_activity + (random.random() - 0.5) * 8
            clamped = max(5, min(new_y, graph_h - 5))
            self._graph_data.append(clamped)

        if self.controller.snapshot_surface:
            self._scanner_pos += self._scanner_dir
            if self._scanner_pos <= 0 or self._scanner_pos >= self.col2_rect.width:
                self._scanner_dir *= -1
        else:
            self._scanner_pos = 0

    def render(self, surface: pygame.Surface) -> None:  # pragma: no cover - Pygame rendering
        app = self.app
        controller = self.controller
        if not app or not controller:
            return

        self._draw_video_feed(surface, controller)
        if controller.show_zoom_grid:
            self._draw_zoom_grid(surface, controller)
        self._draw_bounding_boxes(surface, controller)
        self._draw_status_panel(surface, controller)

    # ------------------------------------------------------------------ layout
    def _setup_layout(self) -> None:
        if not self.app:
            return
        cfg = config.CONFIG
        margins = cfg['margins']
        header_height = 35 if cfg.get('show_header', True) else 0
        top_offset = margins['top'] + header_height
        available_width = cfg["screen_width"] - (margins['left'] + margins['right'])

        self.main_area_rect = pygame.Rect(
            margins['left'],
            top_offset,
            available_width,
            cfg["screen_height"] - top_offset - 105 - 10 - margins['bottom'],
        )
        self.status_panel_rect = pygame.Rect(
            margins['left'],
            self.main_area_rect.bottom + 10,
            available_width,
            105,
        )

        panel_pad = 8
        col_width_1 = 200
        col_width_2 = self.status_panel_rect.height - (panel_pad * 2)
        col_width_3 = self.status_panel_rect.width - col_width_1 - col_width_2 - (panel_pad * 4)
        self.col1_rect = pygame.Rect(self.status_panel_rect.x + panel_pad, self.status_panel_rect.y + panel_pad, col_width_1, self.status_panel_rect.height - (panel_pad * 2))
        self.col2_rect = pygame.Rect(self.col1_rect.right + (panel_pad * 2), self.status_panel_rect.y + panel_pad, col_width_2, col_width_2)
        self.col3_rect = pygame.Rect(self.col2_rect.right + (panel_pad * 2), self.status_panel_rect.y + panel_pad, col_width_3, self.status_panel_rect.height - (panel_pad * 2))
        self.analysis_graph_rect = pygame.Rect(self.col3_rect.x, self.col3_rect.y + 24, self.col3_rect.width - 15, self.col3_rect.height - 24)

        theme = self.app.theme_colors
        self.patterns_green = {
            'dots': _create_tiled_pattern_surface('dots', self.grid_cell_size, theme['default'] + (160,)),
            'lines': _create_tiled_pattern_surface('lines', self.grid_cell_size, theme['default'] + (160,)),
        }
        self.patterns_orange = {
            'dots': _create_tiled_pattern_surface('dots', self.grid_cell_size, theme['warning'] + (160,)),
            'lines': _create_tiled_pattern_surface('lines', self.grid_cell_size, theme['warning'] + (160,)),
        }
        self.patterns_red = {
            'dots': _create_tiled_pattern_surface('dots', self.grid_cell_size, theme['danger'] + (160,)),
            'lines': _create_tiled_pattern_surface('lines', self.grid_cell_size, theme['danger'] + (160,)),
        }

        if self.controller:
            self.controller.configure_view(self.main_area_rect, self.col2_rect.size, self.grid_cell_size)

    # ------------------------------------------------------------------ primitives
    def _draw_video_feed(self, surface: pygame.Surface, controller: CameraController) -> None:
        frame_surface = controller.current_surface
        if frame_surface:
            surface.blit(frame_surface, self.main_area_rect.topleft)
        else:
            placeholder = self.app.font_medium.render("VIDEO FEED OFFLINE", True, self.app.current_theme_color)
            surface.blit(placeholder, placeholder.get_rect(center=self.main_area_rect.center))
        pygame.draw.rect(surface, self.app.current_theme_color, self.main_area_rect, 2)

    def _draw_zoom_grid(self, surface: pygame.Surface, controller: CameraController) -> None:
        grid_surface = pygame.Surface(self.main_area_rect.size, pygame.SRCALPHA)

        if self.controller and self.controller.alert_level == "warning":
            patterns = self.patterns_orange
        elif self.controller and self.controller.alert_level == "danger":
            patterns = self.patterns_red
        else:
            patterns = self.patterns_green

        grid_color = self.app.current_theme_color + (160,)

        for r, row in enumerate(controller.zoom_grid_map):
            for c, pattern_type in enumerate(row):
                pos = (c * self.grid_cell_size, r * self.grid_cell_size)
                if pattern_type == 1:
                    grid_surface.blit(patterns["dots"], pos)
                elif pattern_type == 2:
                    grid_surface.blit(patterns["lines"], pos)

        for x in range(0, self.main_area_rect.width, self.grid_cell_size):
            pygame.draw.line(grid_surface, grid_color, (x, 0), (x, self.main_area_rect.height), 1)
        for y in range(0, self.main_area_rect.height, self.grid_cell_size):
            pygame.draw.line(grid_surface, grid_color, (0, y), (self.main_area_rect.width, y), 1)

        surface.blit(grid_surface, self.main_area_rect.topleft)

    def _draw_bounding_boxes(self, surface: pygame.Surface, controller: CameraController) -> None:
        zoom_rect = controller.current_zoom_rect
        if zoom_rect.w == 0 or zoom_rect.h == 0:
            return
        detections = list(controller.active_detections.values())
        for detection in detections:
            box = detection.get("box")
            if not box:
                continue
            box_x_rel = box[0] - zoom_rect.x
            box_y_rel = box[1] - zoom_rect.y
            scale_x = self.main_area_rect.width / zoom_rect.w
            scale_y = self.main_area_rect.height / zoom_rect.h
            x1 = box_x_rel * scale_x
            y1 = box_y_rel * scale_y
            w = (box[2] - box[0]) * scale_x
            h = (box[3] - box[1]) * scale_y
            box_rect = pygame.Rect(self.main_area_rect.x + x1, self.main_area_rect.y + y1, w, h)
            clipped_box = box_rect.clip(self.main_area_rect)
            if clipped_box.width <= 0 or clipped_box.height <= 0:
                continue
            pygame.draw.rect(surface, self.app.current_theme_color, clipped_box, 1)
            label = detection.get("label", "")
            score = detection.get("score", 0)
            label_surface = self.app.font_small.render(f"{label.upper()} [{score:.0%}]", True, self.app.current_theme_color)
            label_pos_y = box_rect.y - 18
            if label_pos_y < self.main_area_rect.y:
                label_pos_y = clipped_box.y + 2
            surface.blit(label_surface, (clipped_box.x + 2, label_pos_y))

    def _draw_status_panel(self, surface: pygame.Surface, controller: CameraController) -> None:
        color = self.app.current_theme_color
        pygame.draw.rect(surface, color, self.status_panel_rect, 2)

        y_offset = self.col1_rect.y + 2
        row_height = 14
        camera_name = self.config.get("camera_name") or config.CONFIG.get("camera_name", "")
        texts = [
            ("MQTT LINK:", self._mqtt_status),
            ("VIDEO FEED:", self._video_status),
            ("CAMERA:", camera_name.upper()),
            ("LAST EVENT:", controller.last_event_time),
            ("TARGET:", controller.target_label),
            ("CONFIDENCE:", controller.target_score),
        ]

        for index, (label, value) in enumerate(texts):
            y_pos = y_offset + index * row_height
            label_surface = self.app.font_small.render(label, True, color)
            label_rect = label_surface.get_rect()
            value_surface = self.app.font_small.render(str(value), True, (220, 220, 220))
            value_rect = value_surface.get_rect()
            label_rect.topleft = (self.col1_rect.x, y_pos)
            value_rect.topright = (self.col1_rect.right, y_pos)

            line_y = label_rect.centery
            start_x = label_rect.right + 4
            end_x = value_rect.left - 4
            if start_x < end_x:
                draw_dashed_line(surface, color, (start_x, line_y), (end_x, line_y), 1, 2)

            surface.blit(label_surface, label_rect)
            surface.blit(value_surface, value_rect)

        snapshot = controller.snapshot_surface
        if snapshot:
            surface.blit(snapshot, self.col2_rect)
            self._draw_snapshot_scanner(surface)
        else:
            no_signal = self.app.font_small.render("NO SIGNAL", True, color)
            surface.blit(no_signal, no_signal.get_rect(center=self.col2_rect.center))

        pygame.draw.rect(surface, color, self.col2_rect, 1)

        scan_text = "> SCANNING FOR TARGETS"
        if int(time.time() * 2) % 2 == 0:
            scan_text += "_"
        surface.blit(self.app.font_small.render(scan_text, True, color), (self.col3_rect.x, self.col3_rect.y))
        self._draw_analysis_graph(surface)

    def _draw_snapshot_scanner(self, surface: pygame.Surface) -> None:
        scanner_surface = pygame.Surface(self.col2_rect.size, pygame.SRCALPHA)
        trail_color = self.app.current_theme_color + (25,)
        trail_width = 20
        if self._scanner_dir > 0:
            trail_rect = pygame.Rect(self._scanner_pos - trail_width, 0, trail_width, self.col2_rect.height)
        else:
            trail_rect = pygame.Rect(self._scanner_pos, 0, trail_width, self.col2_rect.height)
        scanner_surface.fill(trail_color, trail_rect)
        pygame.draw.line(scanner_surface, self.app.current_theme_color, (self._scanner_pos, 0), (self._scanner_pos, self.col2_rect.height), 2)
        surface.blit(scanner_surface, self.col2_rect.topleft)

    def _draw_analysis_graph(self, surface: pygame.Surface) -> None:
        graph_rect = self.analysis_graph_rect
        color = self.app.current_theme_color

        grid_surface = pygame.Surface(graph_rect.size, pygame.SRCALPHA)
        cell_size = 10
        for x in range(0, graph_rect.width, cell_size):
            pygame.draw.line(grid_surface, color + (100,), (x, 0), (x, graph_rect.height), 1)
        for y in range(0, graph_rect.height, cell_size):
            pygame.draw.line(grid_surface, color + (100,), (0, y), (graph_rect.width, y), 1)
        surface.blit(grid_surface, graph_rect.topleft)
        pygame.draw.rect(surface, color, graph_rect, 1)

        points = []
        for index, value in enumerate(self._graph_data):
            points.append((graph_rect.x + index, graph_rect.y + value))
        if len(points) > 1:
            pygame.draw.lines(surface, color, False, points, 1)


__all__ = ["CameraModule"]
