"""Runtime module orchestration and priority evaluation."""

from __future__ import annotations

import importlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional

from .module import ScreenModule


@dataclass
class ModuleState:
    """Represents the latest state reported by a module."""

    state: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    weight_override: Optional[int] = None
    expires_in: Optional[float] = None
    timestamp: float = field(default_factory=time.monotonic)

    def is_expired(self, now: float, default_timeout: float) -> bool:
        timeout = self.expires_in if self.expires_in is not None else default_timeout
        if timeout <= 0:
            return False
        return (now - self.timestamp) > timeout


@dataclass
class PriorityRule:
    """Configuration for the priority resolver."""

    module: str
    states: Iterable[str]
    weight: int
    screen: str


def _import_string(target: str) -> Any:
    module_path, _, attribute = target.partition(":")
    module = importlib.import_module(module_path)
    if attribute:
        return getattr(module, attribute)
    return module


class ModuleManager:
    """Coordinates screen modules and applies priority rules."""

    def __init__(
        self,
        app: Any,
        modules: Mapping[str, ScreenModule],
        *,
        priorities: Optional[Mapping[str, Any]] = None,
        idle_cycle: Optional[Iterable[str]] = None,
    ) -> None:
        self.app = app
        self._modules: Dict[str, ScreenModule] = {}
        self._states: MutableMapping[str, ModuleState] = {}
        self._rules: List[PriorityRule] = []
        self._idle_cycle: List[str] = list(idle_cycle or [])
        self._idle_index = 0
        self._idle_timer = 0.0
        self._idle_dwell = 20.0
        self._state_timeout = 15.0
        self.current_screen: Optional[str] = None

        if priorities:
            self._load_priority_config(priorities)

        for name, module in modules.items():
            self.register(name, module)

        if not self._idle_cycle:
            self._idle_cycle = list(self._modules.keys())

        if self._idle_cycle:
            self._idle_cycle = [name for name in self._idle_cycle if name in self._modules]
            if not self._idle_cycle and self._modules:
                self._idle_cycle = list(self._modules.keys())

    # ------------------------------------------------------------------ priorities
    def _load_priority_config(self, raw_config: Mapping[str, Any]) -> None:
        self._rules.clear()

        timeout = raw_config.get("timeout_seconds")
        if isinstance(timeout, (int, float)):
            self._state_timeout = float(timeout)

        idle_cfg = raw_config.get("idle", {}) if isinstance(raw_config, Mapping) else {}
        if isinstance(idle_cfg, Mapping):
            cycle = idle_cfg.get("cycle")
            if isinstance(cycle, Iterable):
                self._idle_cycle = list(cycle)
            dwell = idle_cfg.get("dwell_seconds")
            if isinstance(dwell, (int, float)):
                self._idle_dwell = max(0.0, float(dwell))

        rules = raw_config.get("rules", [])
        if not isinstance(rules, Iterable):
            return

        for raw_rule in rules:
            if not isinstance(raw_rule, Mapping):
                continue
            when = raw_rule.get("when", {})
            module_name = when.get("module") if isinstance(when, Mapping) else None
            if not module_name:
                continue
            states = when.get("state", []) if isinstance(when, Mapping) else []
            if isinstance(states, str):
                states = [states]
            weight = raw_rule.get("weight", 0)
            screen = raw_rule.get("screen", module_name)
            try:
                weight_int = int(weight)
            except (TypeError, ValueError):
                weight_int = 0
            self._rules.append(PriorityRule(module=module_name, states=list(states), weight=weight_int, screen=screen))

    # ---------------------------------------------------------------- registration
    def register(self, name: str, module: ScreenModule) -> None:
        if name in self._modules:
            raise ValueError(f"Module '{name}' already registered")
        module.bind(name=name, manager=self, app=self.app)
        module.active = False
        self._modules[name] = module

    def unregister(self, name: str) -> None:
        module = self._modules.pop(name, None)
        if module is None:
            return
        module.unbind()
        self._states.pop(name, None)
        if self.current_screen == name:
            self.current_screen = None

    # -------------------------------------------------------------------- lifecycle
    def shutdown(self) -> None:
        for name in list(self._modules.keys()):
            self.unregister(name)

    # ---------------------------------------------------------------------- runtime
    def update(self, dt: float) -> None:
        now = time.monotonic()
        expired = [name for name, state in self._states.items() if state.is_expired(now, self._state_timeout)]
        for name in expired:
            self._states.pop(name, None)

        for module in self._modules.values():
            module.update(dt)

        target_screen = self._resolve_priority()
        if target_screen:
            if target_screen != self.current_screen:
                self._activate(target_screen)
            self._idle_timer = 0.0
        else:
            self._advance_idle(dt)

    def render(self, surface: Any) -> None:
        if not self.current_screen:
            return
        module = self._modules.get(self.current_screen)
        if module is None:
            return
        module.render(surface)

    def handle_event(self, event: Any) -> None:
        if not self.current_screen:
            return
        module = self._modules.get(self.current_screen)
        if module is None:
            return
        module.handle_event(event)

    # --------------------------------------------------------------------- helpers
    def _activate(self, name: str) -> None:
        if name not in self._modules:
            return
        if self.current_screen and self.current_screen in self._modules:
            previous = self._modules[self.current_screen]
            previous.active = False
            previous.on_hide()
        self.current_screen = name
        module = self._modules[name]
        module.active = True
        module.on_show()
        if hasattr(self.app, "current_screen"):
            self.app.current_screen = name
        if name in self._idle_cycle:
            try:
                self._idle_index = self._idle_cycle.index(name)
            except ValueError:
                pass

    def set_active(self, name: str) -> None:
        self._idle_timer = 0.0
        self._activate(name)

    def _advance_idle(self, dt: float) -> None:
        if not self._idle_cycle:
            return
        if self.current_screen not in self._idle_cycle:
            self._idle_index = 0
            self._activate(self._idle_cycle[0])
            self._idle_timer = 0.0
            return

        self._idle_timer += dt
        if self._idle_timer < self._idle_dwell:
            return
        self._idle_timer = 0.0
        self._idle_index = (self._idle_index + 1) % len(self._idle_cycle)
        self._activate(self._idle_cycle[self._idle_index])

    def _resolve_priority(self) -> Optional[str]:
        best_screen = None
        best_weight = float("-inf")

        for rule in self._rules:
            module_state = self._states.get(rule.module)
            if module_state is None:
                continue
            if rule.states and module_state.state not in rule.states:
                continue
            weight = module_state.weight_override if module_state.weight_override is not None else rule.weight
            if weight > best_weight:
                best_weight = weight
                best_screen = rule.screen

        return best_screen

    # --------------------------------------------------------------------- states
    def report_state(
        self,
        module: str,
        state: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
        weight: Optional[int] = None,
        expires_in: Optional[float] = None,
    ) -> None:
        self._states[module] = ModuleState(
            state=state,
            metadata=metadata or {},
            weight_override=weight,
            expires_in=expires_in,
        )

    def clear_state(self, module: str) -> None:
        self._states.pop(module, None)

    # ---------------------------------------------------------------- utilities
    @staticmethod
    def create_from_config(config: Mapping[str, Any]) -> ScreenModule:
        target = config.get("module") or config.get("path")
        if not target:
            raise ValueError("Module configuration must include 'module' or 'path'")
        cls = _import_string(target)
        if isinstance(cls, type) and issubclass(cls, ScreenModule):
            return cls(config=config.get("config") or config.get("settings") or {})
        if callable(cls):
            return cls(config=config.get("config") or config.get("settings") or {})
        raise TypeError(f"Cannot instantiate module from target '{target}'")

    # ---------------------------------------------------------------- properties
    @property
    def modules(self) -> Mapping[str, ScreenModule]:
        return self._modules
