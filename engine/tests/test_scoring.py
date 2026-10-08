"""Scoring behaviour, including the band boundaries where a defect does
real harm to a real learner."""

import pytest
from aptus_engine import ResponseError, resolve_band, score


def test_all_top_option_scores_strong(config, all_items):
    result = score({i: "A" for i in all_items}, config)
    assert result.overall_normalised == 1.0
    assert result.overall_band == "Strong"
    assert len(result.constructs) == 12
    assert result.unassessed == ()


def test_all_bottom_option_scores_emerging(config, all_items):
    result = score({i: "D" for i in all_items}, config)
    assert result.overall_normalised == 0.25
    assert result.overall_band == "Developing"
    assert all(c.band == "Developing" for c in result.constructs)


def test_empty_responses_score_nothing_rather_than_zero(config):
    """The distinction the predecessor engine got wrong: nobody answered,
    so nothing is known -- not 'everything is weak'."""
    result = score({}, config)
    assert result.constructs == ()
    assert len(result.unassessed) == 12
    assert result.overall_band == "Unassessed"


def test_partial_assessment_omits_untouched_constructs(config):
    items = [i["item_id"] for i in config.signals["SIG_ETHICS_INTEGRITY"]["items"]]
    result = score({i: "A" for i in items}, config)
    assert [c.construct_id for c in result.constructs] == ["SK_ETHICS"]
    assert len(result.unassessed) == 11
    assert "SK_ETHICS" not in result.unassessed


def test_one_of_two_items_still_scores_the_construct(config):
    """A signal with one of two items answered is scored on what exists,
    not penalised for the missing one."""
    items = [i["item_id"] for i in config.signals["SIG_PLANNING_PRIORITISATION"]["items"]]
    result = score({items[0]: "A"}, config)
    planning = next(c for c in result.constructs if c.construct_id == "SK_PLANNING")
    assert planning.normalised == 1.0


def test_unknown_item_ids_are_ignored(config, all_items):
    baseline = score({i: "B" for i in all_items}, config)
    with_junk = score({**{i: "B" for i in all_items}, "withdrawn_item": "A"}, config)
    assert baseline.as_dict() == with_junk.as_dict()


def test_option_outside_the_scale_is_rejected(config, all_items):
    with pytest.raises(ResponseError, match="not in scale"):
        score({**{i: "A" for i in all_items}, all_items[0]: "Z"}, config)


@pytest.mark.parametrize("value,expected", [
    (0.0, "Emerging"), (0.2499, "Emerging"),
    (0.25, "Developing"), (0.4999, "Developing"),
    (0.5, "Proficient"), (0.7499, "Proficient"),
    (0.75, "Strong"), (1.0, "Strong"),
])
def test_band_boundaries(config, value, expected):
    """Every threshold tested on both sides. Lower-inclusive throughout,
    with the top band closed so a perfect score lands somewhere."""
    assert resolve_band(value, config.bands) == expected


def test_result_binds_to_the_config_that_produced_it(config, all_items):
    result = score({i: "C" for i in all_items}, config)
    assert result.config_version == config.version
    assert result.config_digest == config.digest
