"""Loads the deterministic engine and the item bank, once, at startup.

The engine is a separate package with no knowledge of HTTP, databases or
organisations. This module is the only place the two meet, which keeps
the boundary honest: nothing in the API can reach into scoring, and the
engine never learns what a tenant is.
"""

import json
import os
from functools import lru_cache
from pathlib import Path

from aptus_engine import ConfigError, load_config, score  # noqa: F401  (re-exported)

_DATA = Path(__file__).resolve().parent / "data"

# Where the engine configuration lives.
#
# In this repository the engine sits beside the API, and that relative
# path resolves. In an installed deployment it does not: the package
# ends up under site-packages and the walk upwards lands somewhere
# meaningless. So a deployment sets APTUS_ENGINE_CONFIG_DIR explicitly,
# and startup verifies it rather than discovering the problem on the
# first assessment.
_ENV_VAR = "APTUS_ENGINE_CONFIG_DIR"
_REPO_RELATIVE = Path(__file__).resolve().parents[3] / "engine" / "config" / "v1.0.0"


def default_config_dir() -> Path:
    configured = os.environ.get(_ENV_VAR, "").strip()
    return Path(configured) if configured else _REPO_RELATIVE


def describe_config_source() -> str:
    configured = os.environ.get(_ENV_VAR, "").strip()
    return f"{_ENV_VAR}={configured}" if configured else f"repository layout ({_REPO_RELATIVE})"


class ItemBank:
    """Assessment item content: the questions a candidate sees.

    Deliberately separate from engine configuration. The engine needs
    only item ids and selected options; question wording is content that
    changes on a different cadence and under a different review process.
    """

    def __init__(self, payload: dict):
        self.sets = payload["sets"]
        self.items = {item["question_id"]: item for item in payload["items"]}

    def item_ids(self) -> set:
        return set(self.items)

    def set_items(self, set_id: str) -> list:
        definition = self.sets.get(set_id)
        if definition is None:
            raise KeyError(set_id)
        return [self.items[qid] for qid in definition["question_ids"]]

    def items_for_constructs(self, set_id: str, construct_ids) -> list:
        """Filter a set to the constructs a candidate is assigned.

        An empty or absent assignment set means every construct, so the
        caller passes None for that case rather than an empty collection
        -- conflating "assigned nothing" with "assigned everything" would
        silently serve a candidate the wrong assessment.
        """
        items = self.set_items(set_id)
        if construct_ids is None:
            return items
        wanted = set(construct_ids)
        return [i for i in items if i["skill_id"] in wanted]


@lru_cache(maxsize=1)
def get_item_bank() -> ItemBank:
    return ItemBank(json.loads((_DATA / "item_bank.json").read_text(encoding="utf-8")))


@lru_cache(maxsize=4)
def get_engine_config(directory: str | None = None):
    target = Path(directory) if directory else default_config_dir()
    if not target.exists():
        raise ConfigError(
            f"Engine configuration not found at {target}. "
            f"Resolved from {describe_config_source()}. "
            f"Set {_ENV_VAR} to the directory holding manifest.json."
        )
    return load_config(target)
