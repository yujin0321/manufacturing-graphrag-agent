"""Engine configuration: every interpretation choice is an explicit field.

Values that the SOPs do not define (and that the team fixed before
evaluation) live here, not in code. Stage 1 keeps them identical to the
legacy constants so outputs are reproduced byte for byte.
"""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent / "configs"

SLOPE_MODES = {"signal", "alarm"}
MAINT_DIRECTIONS = {"abs", "away"}
MONITOR_GATES = {None, "warning_any"}
MONITOR_ANCHORS = {"incident_start", "warning_trigger"}  # incident_start = legacy v3.1
LINK_POLICIES = {"legacy", "verified"}
SEVERITY_POLICIES = {"sop002_bands", "with_document_tags"}

REQUIRED = {"name", "slope_mode", "maint_direction", "monitor_gate", "monitor_anchor", "id_prefix",
            "sample_seconds", "train_end", "smooth_samples", "incident_gap_min", "outputs",
            "link_policy", "severity_policy"}


class ConfigError(ValueError):
    pass


def load(name_or_path: str | Path) -> dict:
    """Load ``configs/<name>.json`` or an explicit path, then validate."""
    path = Path(name_or_path)
    if not path.suffix:
        path = CONFIG_DIR / f"{name_or_path}.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    validate(cfg)
    cfg["_path"] = path.as_posix()
    return cfg


def validate(cfg: dict) -> None:
    missing = REQUIRED - set(cfg)
    if missing:
        raise ConfigError(f"config missing fields: {sorted(missing)}")
    if cfg["slope_mode"] not in SLOPE_MODES:
        raise ConfigError(f"slope_mode must be one of {sorted(SLOPE_MODES)}")
    if cfg["maint_direction"] not in MAINT_DIRECTIONS:
        raise ConfigError(f"maint_direction must be one of {sorted(MAINT_DIRECTIONS)}")
    if cfg["monitor_gate"] not in MONITOR_GATES:
        raise ConfigError("monitor_gate must be null or 'warning_any'")
    if cfg["monitor_gate"] and cfg["slope_mode"] != "signal":
        raise ConfigError("monitor_gate promotes slope signals, so slope_mode must be 'signal'")
    if cfg["monitor_anchor"] not in MONITOR_ANCHORS:
        raise ConfigError(f"monitor_anchor must be one of {sorted(MONITOR_ANCHORS)}")
    if cfg["link_policy"] not in LINK_POLICIES:
        raise ConfigError(f"link_policy must be one of {sorted(LINK_POLICIES)}")
    if cfg["severity_policy"] not in SEVERITY_POLICIES:
        raise ConfigError(f"severity_policy must be one of {sorted(SEVERITY_POLICIES)}")
    if set(cfg["id_prefix"]) != {"alarm", "incident"}:
        raise ConfigError("id_prefix needs 'alarm' and 'incident'")
    if cfg["sample_seconds"] != 30:
        # k2.scan and k3.runs (reused unchanged) assume the 30 s sampling of the input.
        raise ConfigError("sample_seconds is a property of the frozen input (30)")
    for key in ("smooth_samples", "incident_gap_min"):
        if not isinstance(cfg[key], int) or cfg[key] <= 0:
            raise ConfigError(f"{key} must be a positive integer")
