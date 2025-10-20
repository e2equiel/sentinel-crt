"""Camera screen module wrapping the legacy drawing routines."""

from __future__ import annotations

from sentinel.core import ScreenModule


class CameraModule(ScreenModule):
    slug = "camera"

    def on_show(self) -> None:
        """
        Set the application's header title to the camera screen label when this module becomes visible.
        
        If the module has an associated `app`, assigns "S.E.N.T.I.N.E.L. // CAMERA" to `app.header_title_text`.
        """
        if self.app:
            self.app.header_title_text = "S.E.N.T.I.N.E.L. // CAMERA"

    def render(self, surface) -> None:  # pragma: no cover - Pygame rendering
        """
        Render the camera view onto the provided drawing surface.
        
        If the module is not attached to an application instance, this method does nothing.
        
        Parameters:
            surface: Pygame drawing surface to render the camera view onto.
        """
        if not self.app:
            return
        self.app.draw_camera_view()

    def update(self, dt: float) -> None:
        # The main application owns the heavy logic for now.
        # This hook exists so camera specific state can be moved here gradually.
        """
        Hook invoked each frame to update camera-module state.
        
        Parameters:
            dt (float): Time elapsed since the previous update, in seconds.
        """
        return