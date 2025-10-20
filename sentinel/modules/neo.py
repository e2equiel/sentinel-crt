"""Near Earth Object tracker screen module."""

from __future__ import annotations

from sentinel.core import ScreenModule


class NeoTrackerModule(ScreenModule):
    slug = "neo_tracker"

    def on_show(self) -> None:
        """
        Set the application's header title to "S.E.N.T.I.N.E.L. // NEO TRACKER" when this module becomes visible.
        
        If the module has no associated app, no action is taken.
        """
        if self.app:
            self.app.header_title_text = "S.E.N.T.I.N.E.L. // NEO TRACKER"

    def render(self, surface) -> None:  # pragma: no cover - Pygame rendering
        """
        Render the Near Earth Object tracker screen.
        
        If the module is attached to an app, delegate drawing of the NEO tracker to the app; if no app is present, do nothing.
        
        Parameters:
            surface: The drawing surface provided by the framework (typically a pygame.Surface).
        """
        if not self.app:
            return
        self.app.draw_neo_tracker_screen()

    def update(self, dt: float) -> None:
        """
        No-op per-frame update hook for the NEO tracker module.
        
        Parameters:
            dt (float): Time elapsed since the previous frame in seconds; this implementation ignores the value.
        """
        return