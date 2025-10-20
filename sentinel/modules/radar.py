"""Radar screen module."""

from __future__ import annotations

import threading

from sentinel.core import ScreenModule


class RadarModule(ScreenModule):
    slug = "radar"

    def on_show(self) -> None:
        """
        Prepare and display the radar screen for the current app.
        
        Sets the app header title to "S.E.N.T.I.N.E.L. // RADAR", checks whether the app's map surface is present, and if missing starts a daemon background thread to update map tiles. If the module is not attached to an app, does nothing.
        """
        if not self.app:
            return
        self.app.header_title_text = "S.E.N.T.I.N.E.L. // RADAR"
        with self.app.data_lock:
            needs_map = self.app.map_surface is None
        if needs_map:
            threading.Thread(target=self.app.update_map_tiles, daemon=True).start()

    def render(self, surface) -> None:  # pragma: no cover - Pygame rendering
        """
        Render the radar view for this module.
        
        If the module has no associated app, the method returns without action.
        
        Parameters:
            surface: The Pygame surface to render onto.
        """
        if not self.app:
            return
        self.app.draw_radar_view()

    def update(self, dt: float) -> None:
        """
        Placeholder update hook invoked once per frame.
        
        This method intentionally performs no operations; it accepts the elapsed time since the previous update so subclasses or future implementations can use it.
        
        Parameters:
            dt (float): Time elapsed since the previous frame in seconds.
        """
        return