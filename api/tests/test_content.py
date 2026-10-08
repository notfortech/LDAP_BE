"""The item bank and the engine configuration must agree.

They are deliberately separate -- question wording is content, weights
are engine configuration, and they change on different cadences under
different review. That separation only holds if something checks the
seam, otherwise a renamed item id silently stops contributing to a score
and a construct quietly becomes unassessable.
"""

import pytest
from aptus_api.engine_bridge import get_engine_config, get_item_bank


@pytest.fixture(scope="module")
def bank():
    return get_item_bank()


@pytest.fixture(scope="module")
def config():
    return get_engine_config()


def test_every_engine_item_exists_in_the_bank(bank, config):
    referenced = {
        item["item_id"]
        for signal in config.signals.values()
        for item in signal["items"]
    }
    missing = referenced - bank.item_ids()
    assert not missing, (
        f"Engine signals reference items the bank does not contain: {sorted(missing)}. "
        "Those signals can never be scored."
    )


def test_every_bank_item_is_used_by_a_signal(bank, config):
    referenced = {
        item["item_id"]
        for signal in config.signals.values()
        for item in signal["items"]
    }
    orphans = bank.item_ids() - referenced
    assert not orphans, (
        f"Items in the bank that no signal consumes: {sorted(orphans)}. "
        "A candidate would answer these and the answers would score nothing."
    )


def test_item_options_match_the_engine_scale(bank, config):
    valid = set(config.scale)
    for item_id, item in bank.items.items():
        assert set(item["options"]) == valid, (
            f"Item {item_id} offers options {sorted(item['options'])}, "
            f"but the engine scale defines {sorted(valid)}."
        )


def test_every_construct_is_reachable_through_the_full_set(bank, config):
    """If a construct has no items in the full set, it can never be
    scored, and offering it for assignment would mislead an admin."""
    full_constructs = {i["skill_id"] for i in bank.set_items("full")}
    declared = {c["construct_id"] for c in config.constructs}
    unreachable = declared - full_constructs
    assert not unreachable, f"Constructs with no items in the full set: {sorted(unreachable)}"


def test_item_skill_ids_are_known_constructs(bank, config):
    declared = {c["construct_id"] for c in config.constructs}
    unknown = {i["skill_id"] for i in bank.items.values()} - declared
    assert not unknown, f"Items tagged with unknown constructs: {sorted(unknown)}"


def test_sets_reference_only_real_items(bank):
    for set_id, definition in bank.sets.items():
        missing = set(definition["question_ids"]) - bank.item_ids()
        assert not missing, f"Set {set_id!r} references missing items: {sorted(missing)}"


def test_quick_set_is_a_subset_of_full(bank):
    """Practice must draw from the same bank as the formal assessment;
    otherwise practice is not practice for anything."""
    assert set(bank.sets["quick"]["question_ids"]) <= set(bank.sets["full"]["question_ids"])


def test_engine_config_dir_is_explicit_in_an_installed_layout(monkeypatch, tmp_path):
    """Regression guard for a deployment-only failure.

    The repository-relative default resolves in a source checkout and
    does not once the package is installed under site-packages, where
    walking upwards lands somewhere meaningless. A container would have
    booted cleanly and then failed on a candidate's first assessment.
    The error must name the variable that fixes it.
    """
    from aptus_api import engine_bridge

    engine_bridge.get_engine_config.cache_clear()
    monkeypatch.setenv("APTUS_ENGINE_CONFIG_DIR", str(tmp_path / "nowhere"))
    try:
        with pytest.raises(Exception) as exc:
            engine_bridge.get_engine_config()
        message = str(exc.value)
        assert "APTUS_ENGINE_CONFIG_DIR" in message
        assert "manifest.json" in message
    finally:
        engine_bridge.get_engine_config.cache_clear()


def test_engine_config_dir_env_var_is_honoured(monkeypatch):
    from pathlib import Path

    from aptus_api import engine_bridge

    repo_config = Path(__file__).resolve().parents[2] / "engine" / "config" / "v1.0.0"
    engine_bridge.get_engine_config.cache_clear()
    monkeypatch.setenv("APTUS_ENGINE_CONFIG_DIR", str(repo_config))
    try:
        assert engine_bridge.get_engine_config().version == "1.0.0"
        assert "APTUS_ENGINE_CONFIG_DIR" in engine_bridge.describe_config_source()
    finally:
        engine_bridge.get_engine_config.cache_clear()
