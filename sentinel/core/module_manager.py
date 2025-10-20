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
        """
        Determine whether this module state is considered expired at the given time.
        
        If the instance has `expires_in` set, that value (seconds) is used as the timeout; otherwise `default_timeout` (seconds) is used. A timeout value less than or equal to zero means the state never expires.
        
        Parameters:
        	now (float): Current monotonic time (seconds).
        	default_timeout (float): Fallback timeout in seconds when `expires_in` is None.
        
        Returns:
        	True if the elapsed time since the state's `timestamp` is greater than the resolved timeout, `False` otherwise.
        """
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
    """
    Import a module or a named attribute from a module using a colon-separated path.
    
    Parameters:
        target (str): Import path in the form "package.module" or "package.module:attribute". If an attribute is provided after a colon, that attribute is returned; otherwise the module object is returned.
    
    Returns:
        The imported module object or the specified attribute from that module.
    """
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
        """
        Initialize the ModuleManager and register the provided screen modules, applying optional priority configuration and idle cycling.
        
        Parameters:
            app (Any): Application context that modules may reference.
            modules (Mapping[str, ScreenModule]): Mapping of module names to ScreenModule instances to register.
            priorities (Optional[Mapping[str, Any]]): Optional priority configuration. If provided, it is loaded to configure priority rules, state timeouts, and idle settings.
            idle_cycle (Optional[Iterable[str]]): Optional ordered iterable of module names to use for idle cycling; names not present in `modules` are ignored and the cycle defaults to all registered modules when empty.
        """
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
        """
        Load and apply a priority configuration mapping into the manager's internal rules and idle/timeout settings.
        
        Parameters:
        	raw_config (Mapping[str, Any]): Configuration mapping that may contain:
        		- "timeout_seconds": numeric state timeout in seconds.
        		- "idle": mapping with optional "cycle" (iterable of module names) and "dwell_seconds" (numeric).
        		- "rules": iterable of rule mappings; each rule may contain:
        			- "when": mapping with required "module" and optional "state" (string or iterable).
        			- "weight": value coercible to int (defaults to 0 on failure).
        			- "screen": target screen name (defaults to the module name).
        		
        	Invalid or malformed entries are ignored. Valid rules are converted to PriorityRule instances and stored in self._rules; numeric fields are normalized and states are normalized to a list of strings.
        """
        self._rules.clear()

        timeout = raw_config.get("timeout_seconds")
        if isinstance(timeout, (int, float)):
            self._state_timeout = float(timeout)

        idle_cfg = raw_config.get("idle", {}) if isinstance(raw_config, Mapping) else {}
        if isinstance(idle_cfg, Mapping):
            cycle = idle_cfg.get("cycle")
            if isinstance(cycle, Iterable) and not isinstance(cycle, (str, bytes)):
                self._idle_cycle = list(cycle)
            elif isinstance(cycle, (str, bytes)):
                self._idle_cycle = [cycle.decode() if isinstance(cycle, bytes) else cycle]
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
        """
        Register a ScreenModule under the given name and bind it to this manager.
        
        Parameters:
            name (str): Unique name to register the module under.
            module (ScreenModule): Module instance to register; it will be bound with this manager and the application.
        
        Raises:
            ValueError: If a module is already registered under `name`.
        """
        if name in self._modules:
            raise ValueError(f"Module '{name}' already registered")
        module.bind(name=name, manager=self, app=self.app)
        module.active = False
        self._modules[name] = module

    def unregister(self, name: str) -> None:
        """
        Unregisters and cleans up a registered module by name.
        
        Removes the module from the registry, calls its unbind method, removes any recorded state for that module, and clears the active screen if the removed module was currently active.
        
        Parameters:
            name (str): The registered module name to remove.
        """
        module = self._modules.pop(name, None)
        if module is None:
            return
        module.unbind()
        self._states.pop(name, None)
        if self.current_screen == name:
            self.current_screen = None

    # -------------------------------------------------------------------- lifecycle
    def shutdown(self) -> None:
        """
        Unregisters and shuts down all registered screen modules.
        
        Removes every module from the manager by calling unregister for each registered name; this unbinds modules, clears their stored state, and deactivates the current screen when applicable.
        """
        for name in list(self._modules.keys()):
            self.unregister(name)

    # ---------------------------------------------------------------------- runtime
    def update(self, dt: float) -> None:
        """
        Advance the manager by a time step: expire stale module states, call each module's update, resolve and activate the highest-priority screen, and advance idle cycling as needed.
        
        Parameters:
        	dt (float): Seconds elapsed since the last update call.
        """
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
        """
        Render the currently active screen module onto the given surface.
        
        If no screen is active or the active screen is not registered, this method does nothing.
        
        Parameters:
            surface (Any): Drawing surface passed to the active screen module's render method.
        """
        if not self.current_screen:
            return
        module = self._modules.get(self.current_screen)
        if module is None:
            return
        module.render(surface)

    def handle_event(self, event: Any) -> None:
        """
        Delegate an input/event to the currently active screen module.
        
        If there is no active screen or the active module is not registered, the event is ignored.
        
        Parameters:
            event (Any): Event object to deliver to the active module's handle_event method.
        """
        if not self.current_screen:
            return
        module = self._modules.get(self.current_screen)
        if module is None:
            return
        module.handle_event(event)

    # --------------------------------------------------------------------- helpers
    def _activate(self, name: str) -> None:
        """
        Activate the named screen module and run its lifecycle transitions.
        
        If the given name is not registered, this is a no-op. Deactivates any previously active screen (sets its `active` flag to False and calls its `on_hide()`), sets `current_screen` to `name`, activates the new module (sets its `active` flag to True and calls its `on_show()`), and updates the application and idle-cycle tracking as applicable: if the `app` has a `current_screen` attribute it is set to `name`, and if `name` is present in `_idle_cycle` the manager's `_idle_index` is updated to that position (lookup failures are ignored).
        Parameters:
            name (str): The registered module name to activate.
        """
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
        """
        Reset the idle timer and activate the named screen module.
        
        Parameters:
            name (str): Name of a registered screen module to make active.
        """
        self._idle_timer = 0.0
        self._activate(name)

    def _advance_idle(self, dt: float) -> None:
        """
        Advance idle-cycle timing and switch to the next idle screen when the configured dwell time elapses.
        
        If there is no idle cycle configured this is a no-op. If the current screen is not part of the idle cycle, the first idle screen is activated and the idle timer is reset. Otherwise the method increments the internal idle timer by `dt`, and when the accumulated time reaches or exceeds the configured idle dwell it activates the next screen in the idle cycle order (wrapping to the first) and resets the idle timer.
        
        Parameters:
            dt (float): Elapsed time in seconds since the last update.
        """
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
        """
        Selects the screen that should be active based on configured priority rules and current module states.
        
        Considers each PriorityRule whose module has a reported state and, if the rule specifies allowed states, only when the module's state is in that set. For each matching rule the effective weight is the module state's `weight_override` when present, otherwise the rule's `weight`. The rule with the highest effective weight determines the returned screen.
        
        Returns:
            The name of the winning screen as a `str`, or `None` if no rule matches the current states.
        """
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
        """
        Record the latest state reported by a module and store it for priority resolution.
        
        Parameters:
            module (str): Name of the module reporting the state.
            state (str): State identifier reported by the module.
            metadata (Optional[Dict[str, Any]]): Arbitrary additional data associated with the state (defaults to empty dict).
            weight (Optional[int]): Optional weight override used when resolving priority; if omitted the configured rule weight will be used.
            expires_in (Optional[float]): Optional lifetime in seconds for this state; a non-positive or None value means no expiration.
        
        Notes:
            This replaces any previously stored state for the given module.
        """
        self._states[module] = ModuleState(
            state=state,
            metadata=metadata or {},
            weight_override=weight,
            expires_in=expires_in,
        )

    def clear_state(self, module: str) -> None:
        """
        Remove the stored state for a module.
        
        Parameters:
            module (str): Name of the module whose recorded state should be cleared.
        """
        self._states.pop(module, None)

    # ---------------------------------------------------------------- utilities
    @staticmethod
    def create_from_config(config: Mapping[str, Any]) -> ScreenModule:
        """
        Instantiate a screen module using a configuration mapping.
        
        Parameters:
            config (Mapping[str, Any]): Mapping that must include either "module" or "path" pointing to an import string (module or module:attribute).
                Optional keys:
                - "config" or "settings": a mapping passed to the module/class/callable as the `config` keyword argument; defaults to an empty dict if absent.
        
        Returns:
            ScreenModule: An instantiated screen module created by importing and calling or constructing the target.
        
        Raises:
            ValueError: If neither "module" nor "path" is present in `config`.
            TypeError: If the imported target cannot be instantiated as a screen module (not a subclass of ScreenModule and not callable).
        """
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
        """
        Provide the mapping of registered screen modules keyed by name.
        
        Returns:
            Mapping[str, ScreenModule]: The registered modules mapping where keys are module names and values are their ScreenModule instances.
        """
        return self._modules