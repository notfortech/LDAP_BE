# Evidence basis for the Aptus deterministic engine

Generated from configuration `1.0.0` (digest `d89f32209419`). Do not edit by hand — edit the configuration and regenerate.

## What this engine claims, and what it does not

Aptus measures **capability and behavioural signal**. It is not a validated psychometric instrument and must not be described as one. The distinction is not cosmetic: a validated instrument requires norming against a reference population and published reliability and validity studies. Those do not exist for this engine, and this document exists so that nobody has to guess that.

What the engine does guarantee is narrower and fully defensible:

- **Determinism.** Scoring is a pure function of responses and configuration. No model inference, no clock, no randomness, no network. Identical inputs always produce identical outputs.
- **Traceability.** Every result records the configuration version and a SHA-256 digest of the configuration that produced it, so any historical result can be reproduced exactly.
- **Transparency.** Every weight, threshold and mapping is in version-controlled configuration, and the derivation of any individual number can be shown on request.

## How a score is computed

Two weighted means, in sequence:

```
responses  ->  signal scores  ->  construct scores  ->  bands
```

Each response selects one of 4 ordered options carrying a fixed weight (A = 1.0, B = 0.75, C = 0.5, D = 0.25). A signal score is the weighted mean of its answered items. A construct score is the weighted mean of its contributing signals. The overall score is the unweighted mean of assessed constructs.

Two deliberate choices carry assumptions worth stating:

- **Equal option spacing asserts rank order only.** The 0.25 intervals say that A ranks above B above C above D. They do not claim the psychological distance between A and B equals that between C and D. No evidence supports that stronger claim.
- **The overall score is unweighted.** Weighting one capability above another would assert relative importance, and nothing in the evidence base supports such a weighting. Institutions wanting a weighted composite should derive it from the per-construct scores against their own programme rationale.

A construct whose signals were never assessed is reported as **unassessed**, never as zero. Zero is a measurement; silence is not.

## Construct grounding

The twelve constructs are grounded in alignment with published Australian frameworks, not in original empirical research. Mapping strength is recorded honestly per construct and is not uniform.

| Construct | Core-competency layer | Core Skills for Work | Mapping | Items |
|---|---|---|---|---|
| Communication & Expression | Speaking / Active Listening / Writing | Communicate for work | strong | 2 |
| Critical Thinking & Problem-Solving | Critical Thinking / Complex Problem Solving | Identify and solve problems | strong | 2 |
| Decision-Making & Judgement | Judgment and Decision Making | Make decisions | strong | 2 |
| Collaboration & Teamwork | Coordination / Social Perceptiveness | Connect and work with others | strong | 2 |
| Accountability & Reliability | Monitoring | Work with roles, rights and protocols | strong | 2 |
| Adaptability & Resilience | Active Learning | Navigate the world of work | moderate | 2 |
| Digital & Technology Capability | Technology Design | Work in a digital world | moderate | 2 |
| Planning & Organisation | Time Management | Plan and organise | moderate | 2 |
| Initiative & Creativity | Active Learning / Learning Strategies | Create and innovate | moderate | 2 |
| Ethical & Professional Practice | Service Orientation | Work with roles, rights and protocols | moderate | 2 |
| Numeracy & Data Literacy | Operations Analysis | Get the work done | moderate | 2 |
| Career Self-Management & Navigation | (no clean mapping) | Manage career and work life | weak | 2 |

Mapping strength across the twelve: 5 strong, 6 moderate, 1 weak.

The core-competency column aligns to the layer the Australian Skills Classification called Core Competencies. Jobs and Skills Australia is replacing that classification with the National Skills Taxonomy, which remains at discussion-paper stage. This column is therefore a migration anchor, not a current national standard.

## Known limitations

Stated per construct, because they differ:

- **Communication & Expression** — Written expression is not directly observed; items infer it from choice behaviour
- **Critical Thinking & Problem-Solving** — Situational items constrain the option set, so option generation is not observed
- **Decision-Making & Judgement** — Real decisions carry consequence; a scenario does not, which weakens behavioural fidelity
- **Collaboration & Teamwork** — Self-report of group behaviour is subject to social desirability bias
- **Accountability & Reliability** — Strongly susceptible to social desirability; the correct answer is often obvious
- **Adaptability & Resilience** — Resilience over time cannot be observed in a single sitting
- **Digital & Technology Capability** — Measures judgement about tools, not operational skill with any tool
- **Planning & Organisation** — No Australian Curriculum general capability maps cleanly; the curriculum column is weak here
- **Initiative & Creativity** — Fixed-option items structurally limit observation of generative behaviour
- **Ethical & Professional Practice** — The defensible answer is usually identifiable, which compresses the score range upward
- **Numeracy & Data Literacy** — Situational items test interpretation, not computation; this is narrower than numeracy
- **Career Self-Management & Navigation** — Neither the Australian Curriculum nor the core-competency layer maps cleanly
- **Career Self-Management & Navigation** — The weakest-grounded construct of the twelve; carried because it is what institutions ask for

## Evidence gaps

These apply to the engine as a whole and are open, not resolved:

1. **Item support is thin.** Every construct rests on 2 items. Internal consistency cannot be meaningfully estimated at this length, and a single atypical response moves a construct score substantially.
2. **No empirical validation.** No norming sample, no test-retest reliability, no inter-item consistency, no criterion or predictive validity study has been conducted.
3. **Band thresholds are conventions.** The quartile cut-points are chosen for interpretability. No external criterion establishes that the Proficient/Strong boundary marks a real difference in capability.
4. **Social desirability is uncontrolled.** Several constructs have an identifiable defensible answer, which compresses scores upward. No lie scale or forced-choice control is in place.
5. **Signals map one-to-one to constructs.** The signal layer currently adds no aggregation; it exists so that signals can later span constructs. Until they do, a construct score is a renamed signal score.

## What would close the gaps

In the order that buys the most defensibility per unit of effort:

1. Raise item support to at least four per construct and report internal consistency.
2. Run a test-retest study on a modest sample to establish score stability.
3. Seek subject-matter expert review of construct-to-item alignment and record dissent, not just agreement.
4. Establish a criterion study — correlate scores against an observable outcome such as course completion or supervisor rating — before any claim of predictive value.
5. Revisit the band thresholds once a score distribution from real cohorts exists.

## Change policy

Status of this configuration: **draft**. Scoring logic changes only by issuing a new configuration version. A published version is never edited in place, because results produced under it must stay reproducible. The determinism regression suite enforces this at build time.
