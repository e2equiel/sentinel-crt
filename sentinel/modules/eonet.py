"""EONET globe screen module."""

from __future__ import annotations

from sentinel.core import ScreenModule


class EONETGlobeModule(ScreenModule):
    slug = "eonet_globe"

    def on_show(self) -> None:
        """
        Update the application's header title to "S.E.N.T.I.N.E.L. // EONET" when this module becomes visible.
        
        Sets the app's `header_title_text` attribute if an application instance is attached to this module; does nothing otherwise.
        """
        if self.app:
            self.app.header_title_text = "S.E.N.T.I.N.E.L. // EONET"

    def render(self, surface) -> None:  # pragma: no cover - Pygame rendering
        """
        Render the EONET globe screen using the application's draw_eonet_globe_screen method.
        
        Does nothing if the module has no associated application.
        """
        if not self.app:
            return
        self.app.draw_eonet_globe_screen()

    def update(self, dt: float) -> None:
        """
        No-op update method retained for interface compatibility.
        
        Parameters:
            dt (float): Time elapsed since the last update in seconds.
        """
        return