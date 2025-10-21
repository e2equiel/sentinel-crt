"""Runtime manager for background services."""

from __future__ import annotations

from importlib import import_module
from typing import Any, Dict, Mapping

from sentinel.config import ServiceSettings


def _import_string(target: str) -> Any:
    """Import *target* which may be ``module`` or ``module:attribute``."""

    module_path, _, attr = target.partition(":")
    module = import_module(module_path)
    if attr:
        return getattr(module, attr)
    return module


class ServiceManager:
    """Instantiate and coordinate application services."""

    def __init__(
        self,
        app: Any,
        services: Mapping[str, ServiceSettings],
    ) -> None:
        self.app = app
        self._service_defs = dict(services)
        self._instances: Dict[str, Any] = {}

    # ------------------------------------------------------------------ lifecycle
    def start_all(self) -> None:
        """Instantiate and start all enabled services."""

        for name, settings in self._service_defs.items():
            if not settings.enabled:
                continue
            if name in self._instances:
                continue
            cls = _import_string(settings.path)
            instance = cls(
                app=self.app,
                config=dict(settings.settings),
                event_bus=getattr(self.app, "event_bus", None),
            )
            start = getattr(instance, "start", None)
            if callable(start):
                start()
            self._instances[name] = instance

    def stop_all(self) -> None:
        """Stop every running service and clear instances."""

        for name, instance in list(self._instances.items()):
            stop = getattr(instance, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception as exc:  # pragma: no cover - defensive logging
                    print(f"Error stopping service '{name}': {exc}")
            self._instances.pop(name, None)

    # ------------------------------------------------------------------ accessors
    def get(self, name: str) -> Any:
        """Return the running service instance registered under *name*."""

        return self._instances.get(name)

    def items(self):  # pragma: no cover - passthrough helper
        return self._instances.items()


__all__ = ["ServiceManager"]
