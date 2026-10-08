"""Configuration integrity. These run before anything is scored, because
a config defect must never reach a live assessment."""

import json

import pytest
from aptus_engine import ConfigError, load_config
from conftest import CONFIG_DIR


def test_loads(config):
    assert config.version == "1.0.0"
    assert len(config.digest) == 64
    assert len(config.constructs) == 12
    assert len(config.signals) == 12


def test_digest_is_stable_across_loads():
    assert load_config(CONFIG_DIR).digest == load_config(CONFIG_DIR).digest


def test_digest_ignores_formatting_but_not_values(tmp_path):
    """Reindenting a config must not change its digest; changing a weight
    must. Otherwise the digest cannot be trusted as an identity."""
    for name in ("manifest", "constructs", "signals", "scale", "bands"):
        payload = json.loads((CONFIG_DIR / f"{name}.json").read_text())
        (tmp_path / f"{name}.json").write_text(json.dumps(payload, indent=7, sort_keys=False))
    assert load_config(tmp_path).digest == load_config(CONFIG_DIR).digest

    scale = json.loads((tmp_path / "scale.json").read_text())
    scale["options"]["B"] = 0.8
    (tmp_path / "scale.json").write_text(json.dumps(scale))
    assert load_config(tmp_path).digest != load_config(CONFIG_DIR).digest


def test_every_construct_has_an_evidence_block(config):
    for construct in config.constructs:
        evidence = construct["evidence"]
        assert evidence["framework_basis"]
        assert evidence["mapping_strength"] in {"strong", "moderate", "weak"}
        assert evidence["empirical_validation"] == "none", (
            "If empirical validation now exists for "
            f"{construct['construct_id']}, update EVIDENCE.md and this assertion together."
        )


def test_bands_are_contiguous_and_complete(config):
    ordered = sorted(config.bands, key=lambda b: b["min"])
    assert ordered[0]["min"] == 0.0
    assert ordered[-1]["max"] == 1.0
    for lower, upper in zip(ordered, ordered[1:]):
        assert lower["max"] == upper["min"]


@pytest.mark.parametrize("corruption", [
    ("scale", lambda d: d.update(options={"A": 1.5})),
    ("bands", lambda d: d.update(bands=[{"label": "Only", "min": 0.0, "max": 0.9}])),
])
def test_invalid_config_is_rejected_at_load(tmp_path, corruption):
    name, mutate = corruption
    for f in ("manifest", "constructs", "signals", "scale", "bands"):
        (tmp_path / f"{f}.json").write_text((CONFIG_DIR / f"{f}.json").read_text())
    payload = json.loads((tmp_path / f"{name}.json").read_text())
    mutate(payload)
    (tmp_path / f"{name}.json").write_text(json.dumps(payload))
    with pytest.raises(ConfigError):
        load_config(tmp_path)
