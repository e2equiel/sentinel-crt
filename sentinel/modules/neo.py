"""Near Earth Object tracker screen module."""

from __future__ import annotations

from sentinel.core import ScreenModule


class NeoTrackerModule(ScreenModule):
    slug = "neo_tracker"

    def on_show(self) -> None:
        if self.app:
            self.app.header_title_text = "S.E.N.T.I.N.E.L. // NEO TRACKER"

    def render(self, surface) -> None:  # pragma: no cover - Pygame rendering
        if not self.app:
            return
        self.app.draw_neo_tracker_screen()

    def update(self, dt: float) -> None:
        return
