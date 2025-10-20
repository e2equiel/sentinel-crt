"""Radar screen module."""

from __future__ import annotations

import threading

from sentinel.core import ScreenModule


class RadarModule(ScreenModule):
    slug = "radar"

    def on_show(self) -> None:
        if not self.app:
            return
        self.app.header_title_text = "S.E.N.T.I.N.E.L. // RADAR"
        with self.app.data_lock:
            needs_map = self.app.map_surface is None
        if needs_map:
            threading.Thread(target=self.app.update_map_tiles, daemon=True).start()

    def render(self, surface) -> None:  # pragma: no cover - Pygame rendering
        if not self.app:
            return
        self.app.draw_radar_view()

    def update(self, dt: float) -> None:
        return
