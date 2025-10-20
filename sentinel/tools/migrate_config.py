"""Utility to migrate legacy ``config.py`` settings to the modular layout."""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import Any, Dict

import yaml

from sentinel.config.defaults import DEFAULT_MODULES


LEGACY_CAMERA_KEYS = {
    "camera_name",
    "camera_rtsp_url",
    "frigate_host",
    "frigate_resolution",
    "bbox_delay",
    "zoom_labels",
    "zoom_level",
    "zoom_reset_time",
    "zoom_speed",
    "alert_zones",
}

LEGACY_RADAR_KEYS = {
    "mapbox_user",
    "mapbox_style_id",
    "mapbox_token",
    "map_latitude",
    "map_longitude",
    "map_radius_m",
    "map_distance_rings",
    "map_radial_lines",
    "flight_screen_timeout",
    "min_flight_altitude_ft",
}


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(v) for v in value]
    return value


def _write_yaml(path: Path, payload: Dict[str, Any], *, force: bool) -> None:
    if path.exists() and not force:
        raise SystemExit(f"File '{path}' already exists. Use --force to overwrite.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=True, allow_unicode=True)


def migrate_config(*, output_dir: Path, module_name: str, force: bool) -> None:
    try:
        legacy_config = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:  # pragma: no cover - user error
        raise SystemExit(f"Cannot import module '{module_name}': {exc}")

    raw_config = getattr(legacy_config, "CONFIG", {})
    if not isinstance(raw_config, dict):
        raise SystemExit("Legacy CONFIG must be a dictionary")
    theme = getattr(legacy_config, "THEME_COLORS", {})
    priorities = getattr(legacy_config, "PRIORITIES", getattr(legacy_config, "priorities", {}))

    core_payload: Dict[str, Any] = dict(raw_config)

    modules_payload: Dict[str, Dict[str, Any]] = {}
    defaults = {name: data["module"] for name, data in DEFAULT_MODULES.items()}

    camera_cfg: Dict[str, Any] = {}
    for key in LEGACY_CAMERA_KEYS:
        if key in core_payload:
            camera_cfg[key] = core_payload.pop(key)
    if camera_cfg:
        modules_payload["camera"] = {
            "module": defaults.get("camera", "sentinel.modules.camera:CameraModule"),
            "enabled": True,
            "config": _sanitize(camera_cfg),
        }

    radar_cfg: Dict[str, Any] = {}
    for key in LEGACY_RADAR_KEYS:
        if key in core_payload:
            radar_cfg[key] = core_payload.pop(key)
    if radar_cfg:
        modules_payload["radar"] = {
            "module": defaults.get("radar", "sentinel.modules.radar:RadarModule"),
            "enabled": True,
            "config": _sanitize(radar_cfg),
        }

    output_dir = output_dir.resolve()
    _write_yaml(output_dir / "core.yaml", _sanitize(core_payload), force=force)

    if modules_payload:
        for name, payload in modules_payload.items():
            _write_yaml(output_dir / "modules" / f"{name}.yaml", payload, force=force)

    if isinstance(theme, dict) and theme:
        _write_yaml(output_dir / "theme.yaml", _sanitize(theme), force=force)

    if isinstance(priorities, dict) and priorities:
        _write_yaml(output_dir / "priorities.yaml", _sanitize(priorities), force=force)

    print(f"Configuration migrated to '{output_dir}'.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("settings"),
        help="Destination directory for the modular configuration files.",
    )
    parser.add_argument(
        "--module",
        default="config",
        help="Python module containing the legacy CONFIG object (default: config)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files in the output directory.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    migrate_config(output_dir=args.output, module_name=args.module, force=args.force)


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1:])
