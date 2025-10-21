"""Camera-specific state management and helpers."""

from __future__ import annotations

import io
import random
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, Dict, Mapping, Optional, Tuple

import cv2
import numpy as np
import pygame
import requests


@dataclass
class Viewport:
    """Describe the viewport and snapshot dimensions used by the camera module."""

    viewport_rect: pygame.Rect
    snapshot_size: Tuple[int, int]
    grid_cell_size: int


class CameraController:
    """Encapsulates detection, zoom, and alert logic for the camera module."""

    def __init__(self, core_config: Mapping[str, object]) -> None:
        self._core_config = core_config
        self._lock = threading.RLock()
        self._detection_buffer: Deque[Tuple[float, Dict]] = deque()
        self._active_detections: Dict[str, Dict] = {}
        self._last_event_time = "--"
        self._target_label = "--"
        self._target_score = "--"
        self._snapshot_surface: Optional[pygame.Surface] = None
        resolution = core_config.get("frigate_resolution", (1920, 1080))
        if not (isinstance(resolution, (list, tuple)) and len(resolution) == 2):
            resolution = (1920, 1080)
        self._zoom_target_rect = pygame.Rect(0, 0, resolution[0], resolution[1])
        self._current_zoom_rect = self._zoom_target_rect.copy()
        self._zoom_reset_timer = 0.0
        self._is_zoomed = False
        self._show_zoom_grid = False
        self._zoom_grid_map: list[list[int]] = []
        self._zoom_grid_update_timer = 0.0
        self._alert_level = "none"
        self._current_surface: Optional[pygame.Surface] = None
        self._viewport = Viewport(pygame.Rect(0, 0, 1, 1), (0, 0), 40)

    # ------------------------------------------------------------------ configuration
    def configure_view(self, viewport_rect: pygame.Rect, snapshot_size: Tuple[int, int], grid_cell_size: int) -> None:
        with self._lock:
            self._viewport = Viewport(viewport_rect.copy(), snapshot_size, grid_cell_size)
            self._refresh_zoom_grid(force=True)

    # ------------------------------------------------------------------ properties
    @property
    def alert_level(self) -> str:
        return self._alert_level

    @property
    def last_event_time(self) -> str:
        return self._last_event_time

    @property
    def target_label(self) -> str:
        return self._target_label

    @property
    def target_score(self) -> str:
        return self._target_score

    @property
    def snapshot_surface(self) -> Optional[pygame.Surface]:
        with self._lock:
            return self._snapshot_surface

    @property
    def zoom_grid_map(self):
        with self._lock:
            return list(self._zoom_grid_map)

    @property
    def current_zoom_rect(self) -> pygame.Rect:
        with self._lock:
            return self._current_zoom_rect.copy()

    @property
    def active_detections(self) -> Dict[str, Dict]:
        with self._lock:
            return dict(self._active_detections)

    @property
    def show_zoom_grid(self) -> bool:
        with self._lock:
            return self._show_zoom_grid

    @property
    def current_surface(self) -> Optional[pygame.Surface]:
        with self._lock:
            return self._current_surface

    # ------------------------------------------------------------------ lifecycle
    def reset(self) -> None:
        with self._lock:
            self._detection_buffer.clear()
            self._active_detections.clear()
            self._last_event_time = "--"
            self._target_label = "--"
            self._target_score = "--"
            self._snapshot_surface = None
            resolution = self._core_config.get("frigate_resolution", (1920, 1080))
            if not (isinstance(resolution, (list, tuple)) and len(resolution) == 2):
                resolution = (1920, 1080)
            self._zoom_target_rect = pygame.Rect(0, 0, resolution[0], resolution[1])
            self._current_zoom_rect = self._zoom_target_rect.copy()
            self._zoom_reset_timer = 0.0
            self._is_zoomed = False
            self._show_zoom_grid = False
            self._zoom_grid_map = []
            self._zoom_grid_update_timer = 0.0
            self._current_surface = None
        self._alert_level = "none"

    def queue_detection(self, payload: Dict) -> None:
        self._detection_buffer.append((time.time(), payload))

    # ------------------------------------------------------------------ frame handling
    def process_frame(self, frame) -> None:
        viewport = self._viewport
        if viewport.viewport_rect.width <= 0 or viewport.viewport_rect.height <= 0:
            return
        with self._lock:
            zoom_rect = self._current_zoom_rect.copy()
        h, w = frame.shape[:2]
        x1 = int(max(0, min(zoom_rect.x, w - 1)))
        y1 = int(max(0, min(zoom_rect.y, h - 1)))
        x2 = int(max(0, min(zoom_rect.x + zoom_rect.w, w)))
        y2 = int(max(0, min(zoom_rect.y + zoom_rect.h, h)))
        if x2 <= x1 or y2 <= y1:
            return
        zoomed = frame[y1:y2, x1:x2]
        if zoomed.size == 0:
            return
        resized = cv2.resize(zoomed, viewport.viewport_rect.size)
        rotated = np.rot90(np.fliplr(cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)))
        surface = pygame.surfarray.make_surface(rotated)
        with self._lock:
            self._current_surface = surface

    # ------------------------------------------------------------------ update cycle
    def update(self, *, on_camera_screen: bool) -> None:
        self._process_detection_buffer()
        self._update_alert_level()
        if on_camera_screen:
            self._update_zoom_priority()
        self._update_zoom()

    def _process_detection_buffer(self) -> None:
        bbox_delay = float(self._core_config.get("bbox_delay", 0.4))
        now = time.time()
        while self._detection_buffer and (now - self._detection_buffer[0][0] > bbox_delay):
            _, payload = self._detection_buffer.popleft()
            event_type = payload.get("type")
            detection = payload.get("after", {}) or {}
            if detection.get("camera") != self._core_config.get("camera_name"):
                continue
            detection_id = detection.get("id")
            if not detection_id:
                continue
            is_new = False
            with self._lock:
                if event_type == "end":
                    self._active_detections.pop(detection_id, None)
                else:
                    is_new = detection_id not in self._active_detections
                    self._active_detections[detection_id] = detection
                    self._last_event_time = datetime.now().strftime("%H:%M:%S")
                    self._target_label = detection.get("label", "--").upper()
                    self._target_score = f"{(detection.get('score', 0) * 100):.1f}%"
            if is_new:
                threading.Thread(
                    target=self._fetch_snapshot_image,
                    args=(detection_id,),
                    daemon=True,
                ).start()

    def _update_alert_level(self) -> None:
        current_level = "none"
        zoom_labels = set(self._core_config.get("zoom_labels", []))
        alert_zones = self._core_config.get("alert_zones", {})
        danger_zones = set(alert_zones.get("danger", []))
        warning_zones = set(alert_zones.get("warning", []))
        with self._lock:
            detections = list(self._active_detections.values())
        for detection in detections:
            if detection.get("label") not in zoom_labels:
                continue
            entered_zones = detection.get("entered_zones", [])
            if any(zone in danger_zones for zone in entered_zones):
                current_level = "danger"
                break
            if any(zone in warning_zones for zone in entered_zones):
                current_level = "warning"
        self._alert_level = current_level

    def _update_zoom_priority(self) -> None:
        zoom_labels = set(self._core_config.get("zoom_labels", []))
        with self._lock:
            zoomable = [
                d
                for d in self._active_detections.values()
                if d.get("label") in zoom_labels
            ]
        if not zoomable:
            self._is_zoomed = False
            return

        def in_zone(detection, zones):
            entered = detection.get("entered_zones", [])
            return any(zone in zones for zone in entered)

        alert_zones = self._core_config.get("alert_zones", {})
        danger_zones = set(alert_zones.get("danger", []))
        warning_zones = set(alert_zones.get("warning", []))
        danger = [d for d in zoomable if in_zone(d, danger_zones)]
        warning = [d for d in zoomable if in_zone(d, warning_zones)]

        if danger:
            target = max(danger, key=lambda d: d.get("score", 0))
        elif warning:
            target = max(warning, key=lambda d: d.get("score", 0))
        else:
            target = max(zoomable, key=lambda d: d.get("score", 0))

        if target:
            self._is_zoomed = True
            self._zoom_reset_timer = time.time() + float(self._core_config.get("zoom_reset_time", 5))
            self._update_zoom_target(target)

    def _update_zoom_target(self, detection: Dict) -> None:
        resolution = self._core_config.get("frigate_resolution", (1920, 1080))
        if not (isinstance(resolution, (list, tuple)) and len(resolution) == 2):
            resolution = (1920, 1080)
        src_w, src_h = resolution
        box = detection.get("box")
        if not box:
            return
        box_w = box[2] - box[0]
        box_h = box[3] - box[1]
        center_x = box[0] + box_w / 2
        center_y = box[1] + box_h / 2
        viewport = self._viewport.viewport_rect
        target_ar = viewport.width / viewport.height if viewport.height else 1
        zoom_h = box_h * float(self._core_config.get("zoom_level", 2.5))
        zoom_w = zoom_h * target_ar
        min_zoom_w = box_w * float(self._core_config.get("zoom_level", 2.5))
        if zoom_w < min_zoom_w:
            zoom_w = min_zoom_w
            zoom_h = zoom_w / target_ar
        zoom_w = min(zoom_w, src_w)
        zoom_h = min(zoom_h, src_h)
        zoom_x = max(0, min(center_x - zoom_w / 2, src_w - zoom_w))
        zoom_y = max(0, min(center_y - zoom_h / 2, src_h - zoom_h))
        with self._lock:
            self._zoom_target_rect.update(zoom_x, zoom_y, zoom_w, zoom_h)

    def _update_zoom(self) -> None:
        resolution = self._core_config.get("frigate_resolution", (1920, 1080))
        if not (isinstance(resolution, (list, tuple)) and len(resolution) == 2):
            resolution = (1920, 1080)
        src_w, src_h = resolution
        speed = float(self._core_config.get("zoom_speed", 0.08))
        with self._lock:
            if not self._is_zoomed and self._current_zoom_rect.w < src_w * 0.99:
                self._zoom_target_rect.update(0, 0, src_w, src_h)
            if self._is_zoomed and time.time() > self._zoom_reset_timer:
                self._is_zoomed = False
            self._current_zoom_rect.x += (self._zoom_target_rect.x - self._current_zoom_rect.x) * speed
            self._current_zoom_rect.y += (self._zoom_target_rect.y - self._current_zoom_rect.y) * speed
            self._current_zoom_rect.w += (self._zoom_target_rect.w - self._current_zoom_rect.w) * speed
            self._current_zoom_rect.h += (self._zoom_target_rect.h - self._current_zoom_rect.h) * speed
            self._show_zoom_grid = self._current_zoom_rect.w < src_w * 0.99
        if self._show_zoom_grid and time.time() > self._zoom_grid_update_timer:
            self._refresh_zoom_grid()

    def _refresh_zoom_grid(self, *, force: bool = False) -> None:
        viewport = self._viewport
        if not force and time.time() <= self._zoom_grid_update_timer:
            return
        if viewport.viewport_rect.width <= 0 or viewport.viewport_rect.height <= 0:
            return
        grid_size = max(1, viewport.grid_cell_size)
        cols = viewport.viewport_rect.width // grid_size + 1
        rows = viewport.viewport_rect.height // grid_size + 1
        center_x = viewport.viewport_rect.width / 2
        center_y = viewport.viewport_rect.height / 2
        max_dist = (center_x ** 2 + center_y ** 2) ** 0.5 or 1
        new_map = []
        for r in range(rows):
            row = []
            for c in range(cols):
                cell_x = (c + 0.5) * grid_size
                cell_y = (r + 0.5) * grid_size
                dist_norm = ((cell_x - center_x) ** 2 + (cell_y - center_y) ** 2) ** 0.5 / max_dist
                threshold = random.random() * 0.4
                pattern_type = 0
                if dist_norm > 0.2 + threshold:
                    pattern_type = 1
                if dist_norm > 0.6 + threshold:
                    pattern_type = 2
                row.append(pattern_type)
            new_map.append(row)
        with self._lock:
            self._zoom_grid_map = new_map
        self._zoom_grid_update_timer = time.time() + 0.5

    # ------------------------------------------------------------------ assets
    def _fetch_snapshot_image(self, event_id: str) -> None:
        host = self._core_config.get("frigate_host", "")
        if not host:
            return
        url = f"http://{host}:5000/api/events/{event_id}/snapshot.jpg?crop=1"
        try:
            response = requests.get(url, timeout=3)
            response.raise_for_status()
            image = pygame.image.load(io.BytesIO(response.content))
        except (requests.RequestException, pygame.error) as exc:
            print(f"Error downloading snapshot: {exc}")
            return
        snapshot_size = self._viewport.snapshot_size
        if snapshot_size[0] > 0 and snapshot_size[1] > 0:
            image = pygame.transform.scale(image, snapshot_size)
        with self._lock:
            self._snapshot_surface = image


__all__ = ["CameraController"]
