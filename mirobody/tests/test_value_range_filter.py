"""A counting question has to be expressible, not left to the model.

"How many days did I sleep more than six hours" is a filter plus a count. The
tool returned the whole series and left both to the model, which a small model
does not do — asked PHIA's "how many days in the past week did I get less than
1 hour of deep sleep", a local 2B answered 30.75, a duration, rather than a
number of days.

`value_min` / `value_max` let the question be asked of the tool, and
`view="stats"` answers it with `count_in_range` beside the whole-window count.
These tests pin the parsing and the schema; the SQL is exercised by the
Postgres suite.
"""

from __future__ import annotations

from mirobody.kernel import query


def test_a_band_parses_into_the_request():
    request = query.parse_request(
        {"indicators": ["steps"], "view": "stats", "value_min": 1000, "value_max": 5000})
    assert (request.value_min, request.value_max) == (1000.0, 5000.0)


def test_one_sided_bounds_are_allowed():
    lower = query.parse_request({"indicators": ["steps"], "value_min": "900"})
    assert lower.value_min == 900.0 and lower.value_max is None
    upper = query.parse_request({"indicators": ["steps"], "value_max": 6})
    assert upper.value_max == 6.0 and upper.value_min is None


def test_absent_bounds_stay_absent():
    request = query.parse_request({"indicators": ["steps"]})
    assert request.value_min is None and request.value_max is None


def test_a_non_numeric_bound_is_ignored_rather_than_fatal():
    request = query.parse_request({"indicators": ["steps"], "value_min": "abc"})
    assert request.value_min is None


def test_the_schema_offers_both_bounds():
    properties = query.TOOL_SCHEMA["properties"]
    assert "value_min" in properties and "value_max" in properties
    assert properties["value_min"]["type"] == "number"


def test_the_band_count_reaches_the_model():
    """A column the renderer does not list never reaches the model. The stats
    table is a fixed column list, so `count_in_range` had to be added to it as
    well as to the row — otherwise the SQL computed a number nobody could read.

    This renders a real envelope rather than checking the tuple: the failure
    this guards against happened *after* the row was correct.
    """
    from mirobody.agent.tools import _render
    from mirobody.kernel import tools

    row = {"indicator": "dailyDeepSleep", "count": 7, "count_in_range": 4, "min": 30.0,
           "max": 120.0, "avg": 70.0, "sum": 490.0, "first": "45", "first_date": "2023-10-25",
           "last": "60", "last_date": "2023-10-31", "change": 15.0, "unit": "min"}
    envelope = tools.Envelope(tools.STATUS_OK, data=[row],
                              meta=tools.Meta(view="stats", row_count=1))
    text = _render.render_compact(envelope)
    assert "count_in_range=4" in text, text[:300]
