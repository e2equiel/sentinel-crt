"""Configuration loader that merges defaults, files and user overrides."""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, MutableMapping, Optional

import yaml

from .defaults import clone_defaults


def _deep_update(base: MutableMapping[str, Any], updates: Mapping[str, Any]) -> MutableMapping[str, Any]:
    """
    Recursively merge mapping values from `updates` into `base`.
    
    Nested mappings are merged into corresponding nested mutable mappings in `base`; other values overwrite `base` entries. The `base` mapping is modified in place and also returned.
    
    Parameters:
        base (MutableMapping[str, Any]): The mapping to update; mutated in place.
        updates (Mapping[str, Any]): The mapping providing updates to apply.
    
    Returns:
        MutableMapping[str, Any]: The same `base` mapping after applying the updates.
    """
    for key, value in updates.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), MutableMapping):
            _deep_update(base[key], value)  # type: ignore[index]
        else:
            base[key] = value
    return base


def _load_yaml(path: Path) -> Dict[str, Any]:
    """
    Load a YAML file and return its top-level mapping as a dictionary.
    
    Parameters:
        path (Path): Path to the YAML file to load.
    
    Returns:
        dict: The parsed mapping from the YAML file. Returns an empty dict if the file does not exist or the document is empty.
    
    Raises:
        ValueError: If the YAML document exists but is not a mapping.
    """
    if not path.exists():
        return {}
    with path.open("r", encoding="utf8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, Mapping):
        raise ValueError(f"Configuration file '{path}' must contain a mapping")
    return dict(data)


@dataclass
class ModuleSettings:
    path: str
    enabled: bool = True
    settings: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConfigurationBundle:
    core: Dict[str, Any]
    modules: Dict[str, ModuleSettings]
    services: Dict[str, "ServiceSettings"]
    priorities: Dict[str, Any]
    theme_colors: Dict[str, Any]


@dataclass
class ServiceSettings:
    path: str
    enabled: bool = True
    settings: Dict[str, Any] = field(default_factory=dict)


def load_configuration(settings_dir: Optional[Path] = None) -> ConfigurationBundle:
    """
    Load and merge layered configuration from defaults, YAML files in a settings directory, and optional user-provided overrides.
    
    Parameters:
        settings_dir (Optional[Path]): Directory to load YAML configuration from. If not provided, resolved from the SENTINEL_SETTINGS_DIR environment variable or defaults to the package's "settings" directory.
    
    Returns:
        ConfigurationBundle: Aggregated configuration containing:
            - core: merged core settings
            - modules: mapping of module name to ModuleSettings
            - services: per-service configuration mappings
            - priorities: merged priorities settings
            - theme_colors: merged theme color settings
    """

    root_dir = Path(__file__).resolve().parents[2]
    settings_dir = Path(
        settings_dir
        or os.environ.get("SENTINEL_SETTINGS_DIR")
        or (root_dir / "settings")
    )

    (
        core_config,
        modules_config,
        services_config,
        priorities_config,
        theme_colors,
    ) = clone_defaults()

    # -- load YAML files ----------------------------------------------------------
    core_yaml = settings_dir / "core.yaml"
    if core_yaml.exists():
        _deep_update(core_config, _load_yaml(core_yaml))

    priorities_yaml = settings_dir / "priorities.yaml"
    if priorities_yaml.exists():
        _deep_update(priorities_config, _load_yaml(priorities_yaml))

    modules_dir = settings_dir / "modules"
    if modules_dir.exists():
        for module_file in modules_dir.glob("*.yaml"):
            payload = _load_yaml(module_file)
            name = module_file.stem
            existing = modules_config.get(name, {})
            module_path = payload.get("module") or payload.get("path") or existing.get("module")
            if not module_path:
                raise ValueError(f"Module file '{module_file}' is missing the 'module' key")
            modules_config[name] = {
                "module": module_path,
                "enabled": payload.get("enabled", existing.get("enabled", True)),
                "config": payload.get("config") or payload.get("settings") or existing.get("config", {}),
            }

    services_dir = settings_dir / "services"
    if services_dir.exists():
        for service_file in services_dir.glob("*.yaml"):
            payload = _load_yaml(service_file)
            name = service_file.stem
            existing = services_config.get(name, {})
            service_path = payload.get("service") or payload.get("path") or existing.get("service")
            if not service_path:
                raise ValueError(f"Service file '{service_file}' is missing the 'service' key")
            services_config[name] = {
                "service": service_path,
                "enabled": payload.get("enabled", existing.get("enabled", True)),
                "config": payload.get("config") or payload.get("settings") or existing.get("config", {}),
            }

    theme_yaml = settings_dir / "theme.yaml"
    if theme_yaml.exists():
        _deep_update(theme_colors, _load_yaml(theme_yaml))

    # -- merge user config module -------------------------------------------------
    try:
        user_config = importlib.import_module("config")
    except ModuleNotFoundError:
        user_config = None

    if user_config:
        config_dict = getattr(user_config, "CONFIG", {})
        if isinstance(config_dict, Mapping):
            config_copy = dict(config_dict)
        else:
            config_copy = {}

        modules_section = config_copy.pop("modules", None)
        priorities_section = config_copy.pop("priorities", None)
        services_section = config_copy.pop("services", None)

        _deep_update(core_config, config_copy)

        if isinstance(priorities_section, Mapping):
            _deep_update(priorities_config, priorities_section)

        if isinstance(modules_section, Mapping):
            for name, payload in modules_section.items():
                if not isinstance(payload, Mapping):
                    continue
                module_path = payload.get("module") or payload.get("path")
                if not module_path:
                    existing = modules_config.get(name)
                    module_path = existing.get("module") if isinstance(existing, Mapping) else None
                if not module_path:
                    continue
                modules_config[name] = {
                    "module": module_path,
                    "enabled": payload.get("enabled", True),
                    "config": payload.get("config") or payload.get("settings") or {},
                }

        if isinstance(services_section, Mapping):
            for name, payload in services_section.items():
                if not isinstance(payload, Mapping):
                    continue
                service_path = payload.get("service") or payload.get("path")
                if not service_path:
                    existing = services_config.get(name)
                    service_path = existing.get("service") if isinstance(existing, Mapping) else None
                if not service_path:
                    continue
                services_config[name] = {
                    "service": service_path,
                    "enabled": payload.get("enabled", True),
                    "config": payload.get("config") or payload.get("settings") or {},
                }

        theme_section = getattr(user_config, "THEME_COLORS", None)
        if isinstance(theme_section, Mapping):
            _deep_update(theme_colors, theme_section)

    # -- convert module dicts into dataclasses ------------------------------------
    module_settings: Dict[str, ModuleSettings] = {}
    for name, payload in modules_config.items():
        if not isinstance(payload, Mapping):
            continue
        path = payload.get("module") or payload.get("path")
        if not isinstance(path, str):
            continue
        enabled = bool(payload.get("enabled", True))
        cfg = payload.get("config") or payload.get("settings") or {}
        module_settings[name] = ModuleSettings(path=path, enabled=enabled, settings=dict(cfg))

    service_settings: Dict[str, ServiceSettings] = {}
    for name, payload in services_config.items():
        if not isinstance(payload, Mapping):
            continue
        path = payload.get("service") or payload.get("path")
        if not isinstance(path, str):
            continue
        enabled = bool(payload.get("enabled", True))
        cfg = payload.get("config") or payload.get("settings") or {}
        service_settings[name] = ServiceSettings(path=path, enabled=enabled, settings=dict(cfg))

    return ConfigurationBundle(
        core=core_config,
        modules=module_settings,
        services=service_settings,
        priorities=priorities_config,
        theme_colors=theme_colors,
    )


__all__ = [
    "ConfigurationBundle",
    "ModuleSettings",
    "ServiceSettings",
    "load_configuration",
]
