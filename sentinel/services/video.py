"""Video capture background service."""

from __future__ import annotations

import threading
import time
from typing import Any, Mapping, Optional

import cv2


class VideoCaptureService:
    """Continuously grab frames from the configured RTSP source."""

    def __init__(self, *, app: Any, config: Optional[Mapping[str, Any]], event_bus: Any) -> None:
        self._core: Mapping[str, Any] = getattr(app, "core_settings", {})
        self._options: Mapping[str, Any] = config or {}
        self._event_bus = event_bus
        self._frame_event = self._options.get("frame_event", "services.video.frame")
        self._status_event = self._options.get("status_event", "services.video.status")
        self._thread: Optional[threading.Thread] = None
        self._running = False

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        """Start the capture loop on a background thread."""

        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="VideoCaptureService", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the capture loop and wait for the thread to finish."""

        self._running = False
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5)
        self._thread = None

    # ------------------------------------------------------------------ internals
    def _publish_status(self, value: str) -> None:
        if self._event_bus and self._status_event:
            try:
                self._event_bus.publish(self._status_event, value)
            except Exception as exc:
                print(f"Error publishing video status: {exc}")

    def _publish_frame(self, frame) -> None:
        if self._event_bus and self._frame_event:
            try:
                self._event_bus.publish(self._frame_event, {"frame": frame, "timestamp": time.time()})
            except Exception as exc:
                print(f"Error publishing video frame: {exc}")

    def _run(self) -> None:
        reconnect_delay = float(self._options.get("reconnect_delay", 5))
        camera_url = str(self._options.get("camera_rtsp_url") or self._core.get("camera_rtsp_url", ""))
        resolution = self._core.get("frigate_resolution")
        width = height = None
        if isinstance(resolution, (list, tuple)) and len(resolution) == 2:
            width, height = resolution
        while self._running:
            if not camera_url:
                self._publish_status("OFFLINE")
                time.sleep(reconnect_delay)
                continue
            self._publish_status("INITIALIZING")
            cap = cv2.VideoCapture(camera_url)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if width and height:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            if not cap.isOpened():
                self._publish_status("ERROR")
                cap.release()
                time.sleep(reconnect_delay)
                continue
            self._publish_status("ONLINE")
            while self._running:
                ret, frame = cap.read()
                if not ret:
                    self._publish_status("RECONNECTING...")
                    break
                self._publish_frame(frame)
            cap.release()
            if self._running:
                time.sleep(reconnect_delay)


__all__ = ["VideoCaptureService"]
