"""Lightweight pub/sub event bus for runtime components."""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Callable, DefaultDict, List

EventHandler = Callable[[Any], None]


class EventBus:
    """Thread-safe event dispatcher used to decouple services and modules."""

    def __init__(self) -> None:
        self._handlers: DefaultDict[str, List[EventHandler]] = defaultdict(list)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ subscription
    def subscribe(self, event: str, handler: EventHandler) -> EventHandler:
        """Register *handler* to be invoked whenever *event* is published."""

        if not callable(handler):
            raise TypeError("event handler must be callable")
        with self._lock:
            self._handlers[event].append(handler)
        return handler

    def unsubscribe(self, event: str, handler: EventHandler) -> None:
        """Remove *handler* from the subscription list for *event*."""

        with self._lock:
            listeners = self._handlers.get(event)
            if not listeners:
                return
            try:
                listeners.remove(handler)
            except ValueError:
                return
            if not listeners:
                self._handlers.pop(event, None)

    # ------------------------------------------------------------------ publishing
    def publish(self, event: str, payload: Any = None) -> None:
        """Invoke all handlers registered for *event* with *payload*."""

        with self._lock:
            listeners = list(self._handlers.get(event, ()))
        for handler in listeners:
            try:
                handler(payload)
            except Exception as exc:  # pragma: no cover - defensive logging
                print(f"Error in event handler for '{event}': {exc}")


__all__ = ["EventBus"]
