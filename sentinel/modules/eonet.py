"""EONET globe screen module."""

from __future__ import annotations

from sentinel.core import ScreenModule


class EONETGlobeModule(ScreenModule):
    slug = "eonet_globe"

    def on_show(self) -> None:
        if self.app:
            self.app.header_title_text = "S.E.N.T.I.N.E.L. // EONET"

    def render(self, surface) -> None:  # pragma: no cover - Pygame rendering
        if not self.app:
            return
        self.app.draw_eonet_globe_screen()

    def update(self, dt: float) -> None:
        return
