"""Loads and validates a versioned engine configuration.

Two guarantees this module exists to provide:

1. A configuration is validated once, at load, and is immutable
   afterwards. Scoring never sees a half-valid config.
2. A configuration has a digest -- a SHA-256 over its canonical JSON
   form. A version string is a label a person can edit; a digest is
   derived from the bytes. Binding a result to the digest is what makes
   "reproduce this result" an answerable question years later.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from .errors import ConfigError

_FILES = ("manifest.json", "constructs.json", "signals.json", "scale.json", "bands.json")


@dataclass(frozen=True)
class EngineConfig:
    version: str
    digest: str
    scale: MappingProxyType
    bands: tuple
    signals: MappingProxyType
    constructs: tuple

    @property
    def short_digest(self) -> str:
        return self.digest[:12]


def _canonical(payload) -> bytes:
    """Byte form used for the digest. sort_keys and fixed separators mean
    reformatting a config file -- reindenting, reordering keys -- does not
    change its digest, but changing any value does."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _validate(raw: dict) -> None:
    scale = raw["scale"]["options"]
    if not scale:
        raise ConfigError("Scale defines no options")
    for option, weight in scale.items():
        if not isinstance(weight, (int, float)) or not 0.0 <= weight <= 1.0:
            raise ConfigError(f"Scale option {option!r} weight {weight!r} is outside 0.0-1.0")

    bands = raw["bands"]["bands"]
    ordered = sorted(bands, key=lambda b: b["min"])
    if ordered[0]["min"] != 0.0 or ordered[-1]["max"] != 1.0:
        raise ConfigError("Band set must span 0.0 to 1.0")
    for lower, upper in zip(ordered, ordered[1:]):
        if lower["max"] != upper["min"]:
            raise ConfigError(f"Gap or overlap between bands {lower['label']!r} and {upper['label']!r}")

    signal_ids = {s["signal_id"] for s in raw["signals"]["signals"]}
    if len(signal_ids) != len(raw["signals"]["signals"]):
        raise ConfigError("Duplicate signal_id in signal definitions")

    seen = set()
    for construct in raw["constructs"]["constructs"]:
        cid = construct["construct_id"]
        if cid in seen:
            raise ConfigError(f"Duplicate construct_id {cid!r}")
        seen.add(cid)
        if not construct["derived_from"]:
            raise ConfigError(f"Construct {cid!r} derives from no signal")
        for source in construct["derived_from"]:
            if source["signal_id"] not in signal_ids:
                raise ConfigError(f"Construct {cid!r} references unknown signal {source['signal_id']!r}")
            if source["weight"] <= 0:
                raise ConfigError(f"Construct {cid!r} gives signal {source['signal_id']!r} a non-positive weight")
        if "evidence" not in construct:
            raise ConfigError(f"Construct {cid!r} has no evidence block")


def load_config(directory) -> EngineConfig:
    """Load, validate and digest the configuration in `directory`."""
    path = Path(directory)
    raw = {}
    for filename in _FILES:
        target = path / filename
        if not target.exists():
            raise ConfigError(f"Configuration file missing: {target}")
        try:
            raw[target.stem] = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{target} is not valid JSON: {exc}") from exc

    _validate(raw)

    return EngineConfig(
        version=raw["manifest"]["config_version"],
        digest=hashlib.sha256(_canonical(raw)).hexdigest(),
        scale=MappingProxyType(dict(raw["scale"]["options"])),
        bands=tuple(raw["bands"]["bands"]),
        signals=MappingProxyType({s["signal_id"]: s for s in raw["signals"]["signals"]}),
        constructs=tuple(raw["constructs"]["constructs"]),
    )
