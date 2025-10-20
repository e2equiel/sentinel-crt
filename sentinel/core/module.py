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
        """
        Initialize the module with an optional per-module configuration.
        
        Parameters:
            config (Optional[Dict[str, Any]]): Configuration dictionary for the module; if omitted, an empty dict is used.
        
        Initializes these attributes:
            config: The module configuration dictionary.
            manager: Reference to the ModuleManager (set when bound).
            app: Reference to the application instance (set when bound).
            name: Canonical name assigned by the manager (None until bound).
            active: Whether the module is currently active (defaults to False).
        """
        self.config: Dict[str, Any] = config or {}
        self.manager = None  # type: ignore[assignment]
        self.app = None  # type: ignore[assignment]
        self.name: Optional[str] = None
        self.active: bool = False

    # -- lifecycle -----------------------------------------------------------------
    def bind(self, *, name: str, manager: "ModuleManager", app: Any) -> None:
        """
        Bind runtime dependencies to the module and invoke its load hook.
        
        Sets the module's name, manager, and app attributes, then calls on_load().
        
        Parameters:
            name (str): Canonical name of the module within the manager.
        """

        self.name = name
        self.manager = manager
        self.app = app
        self.on_load()

    def unbind(self) -> None:
        """
        Detach the module from its manager and clear its runtime bindings.
        
        Invokes the on_unload() hook, then sets `active` to False and clears `manager`, `app`, and `name`.
        Cleanup is performed even if on_unload() raises.
        """

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
        """
        Perform teardown when the module is removed from its manager.
        
        Subclasses should override to release resources, stop background work, and perform any cleanup required before the module is discarded.
        """

    def on_show(self) -> None:  # pragma: no cover - meant for subclasses
        """Invoked whenever the module becomes the active screen."""

    def on_hide(self) -> None:  # pragma: no cover - meant for subclasses
        """Invoked whenever the module stops being the active screen."""

    def update(self, dt: float) -> None:  # pragma: no cover - meant for subclasses
        """
        Advance this module's internal state by the given time delta.
        
        Parameters:
            dt (float): Time step in seconds to advance the module's logic; may be zero.
        """

    @abstractmethod
    def render(self, surface: Any) -> None:
        """
        Render the module's visual content onto the provided drawing surface.
        
        Parameters:
            surface (Any): Target drawing surface onto which the module should draw its content (e.g., a window, canvas, or buffer).
        """

    def handle_event(self, event: Any) -> None:  # pragma: no cover - meant for subclasses
        """
        Handle an input event dispatched to the active module.
        
        Subclasses should override this hook to respond to incoming events (for example, Pygame events).
        The default implementation does nothing.
        
        Parameters:
            event (Any): The event object to handle (format depends on the event source, e.g. a Pygame event).
        """

    # -- utilities -----------------------------------------------------------------
    def report_state(
        self,
        state: Optional[str],
        *,
        metadata: Optional[Dict[str, Any]] = None,
        weight: Optional[int] = None,
        expires_in: Optional[float] = None,
    ) -> None:
        """
        Publish or clear this module's reported state with optional metadata, weight, and expiry.
        
        If `state` is None, clears the module's previously reported state from the manager. Otherwise, reports `state` to the bound manager along with optional `metadata`, `weight`, and `expires_in` (expiry in seconds).
        
        Parameters:
            state (Optional[str]): The state label to report, or `None` to clear the module's state.
            metadata (Optional[Dict[str, Any]]): Additional arbitrary data attached to the reported state.
            weight (Optional[int]): Numeric weight or priority associated with the state.
            expires_in (Optional[float]): Time in seconds after which the reported state should expire.
        
        Raises:
            RuntimeError: If the module is not bound to a manager or the module's name is undefined.
        """

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
