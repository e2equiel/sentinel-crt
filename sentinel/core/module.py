"""Base classes for Sentinel screen modules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class ScreenModule(ABC):
    """Base class for modular screens.

    Modules can access the running application through ``self.app`` once the
    module is registered by the :class:`~sentinel.core.module_manager.ModuleManager`.
    They can emit state changes via :meth:`report_state` which are then consumed by
    the priority resolver.
    """

    #: Human friendly identifier. It is optional but helps describing modules in
    #: configuration files. The manager will always set ``self.name`` when the
    #: module is registered.
    slug: Optional[str] = None

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config: Dict[str, Any] = config or {}
        self.manager = None  # type: ignore[assignment]
        self.app = None  # type: ignore[assignment]
        self.name: Optional[str] = None
        self.active: bool = False

    # -- lifecycle -----------------------------------------------------------------
    def bind(self, *, name: str, manager: "ModuleManager", app: Any) -> None:
        """Attach runtime dependencies to the module.

        Parameters
        ----------
        name:
            The canonical name for the module inside the manager.
        manager:
            The :class:`ModuleManager` instance coordinating modules.
        app:
            The high level application instance, typically ``SentinelApp``.
        """

        self.name = name
        self.manager = manager
        self.app = app
        self.on_load()

    def unbind(self) -> None:
        """Called when the module is being removed from the manager."""

        try:
            self.on_unload()
        finally:
            self.active = False
            self.manager = None
            self.app = None
            self.name = None

    # -- hooks ---------------------------------------------------------------------
    def on_load(self) -> None:  # pragma: no cover - meant for subclasses
        """Hook executed immediately after registration."""

    def on_unload(self) -> None:  # pragma: no cover - meant for subclasses
        """Hook executed when the module is removed from the manager."""

    def on_show(self) -> None:  # pragma: no cover - meant for subclasses
        """Invoked whenever the module becomes the active screen."""

    def on_hide(self) -> None:  # pragma: no cover - meant for subclasses
        """Invoked whenever the module stops being the active screen."""

    def update(self, dt: float) -> None:  # pragma: no cover - meant for subclasses
        """Advance the module logic by ``dt`` seconds."""

    @abstractmethod
    def render(self, surface: Any) -> None:
        """Draw the screen content onto ``surface``."""

    def handle_event(self, event: Any) -> None:  # pragma: no cover - meant for subclasses
        """Process a Pygame event when the module is active."""

    # -- utilities -----------------------------------------------------------------
    def report_state(
        self,
        state: Optional[str],
        *,
        metadata: Optional[Dict[str, Any]] = None,
        weight: Optional[int] = None,
        expires_in: Optional[float] = None,
    ) -> None:
        """Convenience wrapper to publish module state to the manager."""

        if self.manager is None:
            raise RuntimeError("Module not bound to a manager")
        if self.name is None:
            raise RuntimeError("Module name is undefined")
        if state is None:
            self.manager.clear_state(self.name)
        else:
            self.manager.report_state(
                self.name,
                state,
                metadata=metadata or {},
                weight=weight,
                expires_in=expires_in,
            )


# Avoid circular imports at runtime.
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - for type checking only
    from .module_manager import ModuleManager
