"""Regenerates the determinism baseline.

Run this ONLY when issuing a new config version. Running it to make a
failing test pass destroys the guarantee the test exists to provide.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from aptus_engine import load_config, score  # noqa: E402

config = load_config(ROOT / "config" / "v1.0.0")
items = [i["item_id"] for s in sorted(config.signals) for i in config.signals[s]["items"]]

cases = [
    ("all_top", {i: "A" for i in items}),
    ("all_bottom", {i: "D" for i in items}),
    ("mixed_cycle", {item: "ABCD"[n % 4] for n, item in enumerate(items)}),
    ("single_construct", {i["item_id"]: "B" for i in config.signals["SIG_ETHICS_INTEGRITY"]["items"]}),
    ("sparse_one_item_each", {items[n]: "C" for n in range(0, len(items), 2)}),
    ("empty", {}),
]

payload = {
    "config_version": config.version,
    "config_digest": config.digest,
    "cases": [{"name": n, "responses": r, "expected": score(r, config).as_dict()} for n, r in cases],
}
out = ROOT / "tests" / "golden" / "baseline.json"
out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
print(f"baseline written: {len(cases)} cases, digest {config.short_digest}")
