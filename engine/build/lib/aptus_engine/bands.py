"""Score-to-band mapping. Single source of truth.

The predecessor engine defined per-construct bands in one module and
re-derived the overall band from hardcoded literals in another, so the
two could silently disagree. Both now resolve through this function
against one configured band set.
"""

from .errors import ConfigError


def resolve_band(normalised: float, bands: list) -> str:
    """Map a 0.0-1.0 score to a band label.

    Bands are lower-inclusive and upper-exclusive so adjacent bands
    cannot both match; the top band includes its upper bound so a
    perfect score has somewhere to land.
    """
    if not 0.0 <= normalised <= 1.0:
        raise ConfigError(f"Score {normalised} outside the 0.0-1.0 range")

    ordered = sorted(bands, key=lambda b: b["min"])
    for band in ordered[:-1]:
        if band["min"] <= normalised < band["max"]:
            return band["label"]

    top = ordered[-1]
    if top["min"] <= normalised <= top["max"]:
        return top["label"]

    raise ConfigError(f"Band set does not cover score {normalised}")
