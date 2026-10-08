# aptus-engine

The deterministic capability scoring engine. Pure Python, no runtime
dependencies, no network, no model inference.

## Why this is a separate package

Scoring is the product's defensible claim and its core IP. Isolating it
from the web application means it can be versioned, tested and audited
on its own terms, and that nothing in the API layer can reach in and
adjust a number.

## Guarantees

- **Deterministic.** `score()` is a pure function of `(responses, config)`.
  No clock, no randomness, no I/O. Identical inputs always produce
  identical outputs, enforced by a golden-master suite on every build.
- **Versioned.** Configuration carries a version and a SHA-256 digest of
  its canonical form. Every result records both, so a historical result
  can be reproduced exactly.
- **No AI.** No language model participates in any value this package
  produces. This is a hard boundary, not a default.
- **Honest about silence.** A construct nobody was assessed on is
  reported unassessed, never scored zero.

## Use

```python
from aptus_engine import load_config, score

config = load_config("config/v1.0.0")
result = score({"q1": "A", "q2": "C"}, config)

print(result.overall_band, result.config_digest[:12])
print(result.as_dict())
```

The engine does not timestamp or persist anything — that belongs to the
caller. A clock inside the engine would make its output unequal to
itself and defeat the determinism test.

## Layout

```
config/v1.0.0/     versioned engine configuration (the IP)
  manifest.json      version, status, change policy
  constructs.json    12 capability constructs + evidence register
  signals.json       signal definitions and item weights
  scale.json         response scale weights
  bands.json         band thresholds
src/aptus_engine/  the engine
tests/             unit, boundary and determinism suites
tools/             config build, baseline regen, evidence doc generator
EVIDENCE.md        generated research/evidence basis — do not hand-edit
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```

`tests/test_determinism.py` is a release gate. If it fails, scoring
changed. **Do not regenerate the baseline to make it pass** — issue a new
config version and generate a baseline beside the existing one, so
results produced under the old version stay reproducible.

## Changing scoring

1. Create `config/vX.Y.Z/` from the previous version.
2. Make the change there. Never edit a published version in place.
3. `python tools/regen_golden.py` against the new version.
4. `python tools/build_evidence_doc.py` to regenerate `EVIDENCE.md`.
5. Record what changed and why in the new manifest's `notes`.
