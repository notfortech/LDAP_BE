"""The deterministic scoring engine.

No language model participates in any value this module produces, and
nothing here reads a clock, a random source, the filesystem or the
network. `score()` is a pure function of (responses, config): the same
pair always yields an identical result, which is what the golden-master
regression suite asserts and what makes a historical result reproducible.

Timestamps belong to the persistence layer, deliberately. A clock inside
the engine would make its output unequal to itself and defeat the test
that protects the product's central claim.

Two stages, both weighted means:

    responses --> signal scores --> construct scores --> bands

A construct whose signals were never assessed is reported as unassessed,
never as zero. Zero is a measurement; silence is not. Conflating them
would tell an institution a learner is weak at something nobody asked
them about.
"""

from dataclasses import dataclass, field

from .bands import resolve_band
from .errors import ResponseError


@dataclass(frozen=True)
class ConstructScore:
    construct_id: str
    display_name: str
    normalised: float
    band: str
    contributing_signals: tuple


@dataclass(frozen=True)
class Result:
    config_version: str
    config_digest: str
    overall_normalised: float
    overall_band: str
    constructs: tuple
    unassessed: tuple
    signal_scores: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        """Stable serialisation. Key order is fixed and no value is
        derived from anything outside the inputs, so two runs on the same
        inputs produce byte-identical JSON."""
        return {
            "config_version": self.config_version,
            "config_digest": self.config_digest,
            "overall": {"normalised": self.overall_normalised, "band": self.overall_band},
            "constructs": [
                {
                    "construct_id": c.construct_id,
                    "display_name": c.display_name,
                    "normalised": c.normalised,
                    "band": c.band,
                    "contributing_signals": list(c.contributing_signals),
                }
                for c in self.constructs
            ],
            "unassessed": list(self.unassessed),
            "signal_scores": dict(sorted(self.signal_scores.items())),
        }


# Four decimal places throughout. Rounding once per stage, at a fixed
# precision, keeps the result independent of platform float formatting.
_PRECISION = 4


def _score_signals(responses: dict, config) -> dict:
    scores = {}
    for signal_id in sorted(config.signals):
        total = 0.0
        weight_sum = 0.0
        for item in config.signals[signal_id]["items"]:
            selected = responses.get(item["item_id"])
            if selected is None:
                continue
            if selected not in config.scale:
                raise ResponseError(
                    f"Item {item['item_id']!r} has option {selected!r}, "
                    f"which is not in scale {sorted(config.scale)}"
                )
            total += config.scale[selected] * item["weight"]
            weight_sum += item["weight"]
        if weight_sum > 0:
            scores[signal_id] = round(total / weight_sum, _PRECISION)
    return scores


def score(responses: dict, config) -> Result:
    """Score a set of responses against a loaded configuration.

    `responses` maps item id to selected option, e.g. {"q1": "A"}.
    Unknown item ids are ignored: withdrawing an item from a set must not
    invalidate a result already in flight.
    """
    signal_scores = _score_signals(responses, config)

    scored = []
    unassessed = []
    for construct in config.constructs:
        total = 0.0
        weight_sum = 0.0
        contributing = []
        for source in construct["derived_from"]:
            value = signal_scores.get(source["signal_id"])
            if value is None:
                continue
            total += value * source["weight"]
            weight_sum += source["weight"]
            contributing.append(source["signal_id"])

        if weight_sum == 0:
            unassessed.append(construct["construct_id"])
            continue

        normalised = round(total / weight_sum, _PRECISION)
        scored.append(ConstructScore(
            construct_id=construct["construct_id"],
            display_name=construct["display_name"],
            normalised=normalised,
            band=resolve_band(normalised, config.bands),
            contributing_signals=tuple(sorted(contributing)),
        ))

    # The overall score is the unweighted mean of the constructs that
    # were actually assessed. Unweighted is a deliberate choice: weighting
    # one capability above another is a claim about relative importance
    # that nothing in the evidence base supports.
    if scored:
        overall = round(sum(c.normalised for c in scored) / len(scored), _PRECISION)
        overall_band = resolve_band(overall, config.bands)
    else:
        overall = 0.0
        overall_band = "Unassessed"

    return Result(
        config_version=config.version,
        config_digest=config.digest,
        overall_normalised=overall,
        overall_band=overall_band,
        constructs=tuple(scored),
        unassessed=tuple(unassessed),
        signal_scores=signal_scores,
    )
