"""Generates EVIDENCE.md from the engine configuration.

The evidence basis is not a document somebody maintains alongside the
code; it is generated from the same config the engine scores with. If a
weight, a mapping or a limitation changes, this document changes with it.
That is the point: a hand-maintained evidence statement drifts from the
system it describes, and a drifted evidence statement is worse than none.
"""
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from aptus_engine import load_config  # noqa: E402

cfg = load_config(ROOT / "config" / "v1.0.0")
L = []
w = L.append

w("# Evidence basis for the Aptus deterministic engine")
w("")
w(f"Generated from configuration `{cfg.version}` (digest `{cfg.short_digest}`). "
  "Do not edit by hand — edit the configuration and regenerate.")
w("")
w("## What this engine claims, and what it does not")
w("")
w("Aptus measures **capability and behavioural signal**. It is not a validated "
  "psychometric instrument and must not be described as one. The distinction is "
  "not cosmetic: a validated instrument requires norming against a reference "
  "population and published reliability and validity studies. Those do not exist "
  "for this engine, and this document exists so that nobody has to guess that.")
w("")
w("What the engine does guarantee is narrower and fully defensible:")
w("")
w("- **Determinism.** Scoring is a pure function of responses and configuration. "
  "No model inference, no clock, no randomness, no network. Identical inputs "
  "always produce identical outputs.")
w("- **Traceability.** Every result records the configuration version and a "
  "SHA-256 digest of the configuration that produced it, so any historical "
  "result can be reproduced exactly.")
w("- **Transparency.** Every weight, threshold and mapping is in version-controlled "
  "configuration, and the derivation of any individual number can be shown on request.")
w("")
w("## How a score is computed")
w("")
w("Two weighted means, in sequence:")
w("")
w("```")
w("responses  ->  signal scores  ->  construct scores  ->  bands")
w("```")
w("")
w(f"Each response selects one of {len(cfg.scale)} ordered options carrying a fixed weight "
  f"({', '.join(f'{k} = {v}' for k, v in sorted(cfg.scale.items()))}). A signal score is the "
  "weighted mean of its answered items. A construct score is the weighted mean of its "
  "contributing signals. The overall score is the unweighted mean of assessed constructs.")
w("")
w("Two deliberate choices carry assumptions worth stating:")
w("")
w("- **Equal option spacing asserts rank order only.** The 0.25 intervals say that A "
  "ranks above B above C above D. They do not claim the psychological distance "
  "between A and B equals that between C and D. No evidence supports that stronger claim.")
w("- **The overall score is unweighted.** Weighting one capability above another "
  "would assert relative importance, and nothing in the evidence base supports "
  "such a weighting. Institutions wanting a weighted composite should derive it "
  "from the per-construct scores against their own programme rationale.")
w("")
w("A construct whose signals were never assessed is reported as **unassessed**, never "
  "as zero. Zero is a measurement; silence is not.")
w("")
w("## Construct grounding")
w("")
w("The twelve constructs are grounded in alignment with published Australian "
  "frameworks, not in original empirical research. Mapping strength is recorded "
  "honestly per construct and is not uniform.")
w("")
w("| Construct | Core-competency layer | Core Skills for Work | Mapping | Items |")
w("|---|---|---|---|---|")
for c in cfg.constructs:
    e = c["evidence"]; f = e["framework_basis"]
    w(f"| {c['display_name']} | {f['asc_core_competency']} | {f['csfw_area']} | "
      f"{e['mapping_strength']} | {e['item_support']} |")
w("")
strength = Counter(c["evidence"]["mapping_strength"] for c in cfg.constructs)
w(f"Mapping strength across the twelve: {strength['strong']} strong, "
  f"{strength['moderate']} moderate, {strength['weak']} weak.")
w("")
w("The core-competency column aligns to the layer the Australian Skills Classification "
  "called Core Competencies. Jobs and Skills Australia is replacing that classification "
  "with the National Skills Taxonomy, which remains at discussion-paper stage. This "
  "column is therefore a migration anchor, not a current national standard.")
w("")
w("## Known limitations")
w("")
w("Stated per construct, because they differ:")
w("")
for c in cfg.constructs:
    for lim in c["evidence"]["known_limitations"]:
        w(f"- **{c['display_name']}** — {lim}")
w("")
w("## Evidence gaps")
w("")
w("These apply to the engine as a whole and are open, not resolved:")
w("")
w(f"1. **Item support is thin.** Every construct rests on {cfg.constructs[0]['evidence']['item_support']} "
  "items. Internal consistency cannot be meaningfully estimated at this length, and a "
  "single atypical response moves a construct score substantially.")
w("2. **No empirical validation.** No norming sample, no test-retest reliability, no "
  "inter-item consistency, no criterion or predictive validity study has been conducted.")
w("3. **Band thresholds are conventions.** The quartile cut-points are chosen for "
  "interpretability. No external criterion establishes that the Proficient/Strong "
  "boundary marks a real difference in capability.")
w("4. **Social desirability is uncontrolled.** Several constructs have an identifiable "
  "defensible answer, which compresses scores upward. No lie scale or forced-choice "
  "control is in place.")
w("5. **Signals map one-to-one to constructs.** The signal layer currently adds no "
  "aggregation; it exists so that signals can later span constructs. Until they do, "
  "a construct score is a renamed signal score.")
w("")
w("## What would close the gaps")
w("")
w("In the order that buys the most defensibility per unit of effort:")
w("")
w("1. Raise item support to at least four per construct and report internal consistency.")
w("2. Run a test-retest study on a modest sample to establish score stability.")
w("3. Seek subject-matter expert review of construct-to-item alignment and record "
  "dissent, not just agreement.")
w("4. Establish a criterion study — correlate scores against an observable outcome such "
  "as course completion or supervisor rating — before any claim of predictive value.")
w("5. Revisit the band thresholds once a score distribution from real cohorts exists.")
w("")
w("## Change policy")
w("")
w(f"Status of this configuration: **{__import__('json').loads((ROOT / 'config' / 'v1.0.0' / 'manifest.json').read_text())['status']}**. "
  "Scoring logic changes only by issuing a new configuration version. A published "
  "version is never edited in place, because results produced under it must stay "
  "reproducible. The determinism regression suite enforces this at build time.")
w("")

(ROOT / "EVIDENCE.md").write_text("\n".join(L))
print(f"EVIDENCE.md written ({len(L)} lines) from config {cfg.short_digest}")
