"""The regression gate protecting the product's central claim.

A stored corpus of response sets is replayed and compared byte-for-byte
against a committed baseline. Any drift fails the build.

When a scoring change is intended, the baseline is NOT edited. A new
config version is issued and a new baseline generated beside it, so the
old results stay reproducible. Regenerate with:

    python tools/regen_golden.py
"""

import json
import pathlib

from aptus_engine import score

GOLDEN = pathlib.Path(__file__).resolve().parent / "golden"


def _canonical(result) -> str:
    return json.dumps(result.as_dict(), sort_keys=True, separators=(",", ":"))


def test_scoring_is_reproducible_within_a_run(config, all_items):
    responses = {item: "ABCD"[i % 4] for i, item in enumerate(all_items)}
    assert _canonical(score(responses, config)) == _canonical(score(responses, config))


def test_matches_committed_baseline(config):
    baseline = json.loads((GOLDEN / "baseline.json").read_text())

    assert baseline["config_digest"] == config.digest, (
        "The configuration changed. This is not a test to edit: issue a new "
        "config version and generate a baseline beside this one, so results "
        "produced under the old version stay reproducible."
    )

    for case in baseline["cases"]:
        actual = score(case["responses"], config).as_dict()
        assert actual == case["expected"], f"Scoring drifted for case {case['name']!r}"
