"""Camera screen module wrapping the legacy drawing routines."""

from __future__ import annotations

from sentinel.core import ScreenModule


class CameraModule(ScreenModule):
    slug = "camera"

    def on_show(self) -> None:
        if self.app:
            self.app.header_title_text = "S.E.N.T.I.N.E.L. // CAMERA"

    def render(self, surface) -> None:  # pragma: no cover - Pygame rendering
        if not self.app:
            return
        self.app.draw_camera_view()

    def update(self, dt: float) -> None:
        # The main application owns the heavy logic for now.
        # This hook exists so camera specific state can be moved here gradually.
        return
