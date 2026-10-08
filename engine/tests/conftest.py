import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from aptus_engine import load_config  # noqa: E402

CONFIG_DIR = pathlib.Path(__file__).resolve().parent.parent / "config" / "v1.0.0"


@pytest.fixture(scope="session")
def config():
    return load_config(CONFIG_DIR)


@pytest.fixture(scope="session")
def all_items(config):
    """Every item id the configuration references, in stable order."""
    items = []
    for signal_id in sorted(config.signals):
        items.extend(i["item_id"] for i in config.signals[signal_id]["items"])
    return items
