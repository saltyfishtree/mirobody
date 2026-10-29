

def test_stats_publishes_a_median_and_a_spread():
    """`stats` answered with min/max/avg/sum, and 393 of PHIA's 4,000 objective
    questions ask for a median (281 for a standard deviation). Asked for the
    median deep-sleep percentage, a local 2B answered with one day's value —
    it had no statistic to read, only rows to count by hand.
    """
    from mirobody.collect import query as collect_query

    source = collect_query._STATS_CTE  # noqa: F841  (documented here, asserted below)
    sql = str(collect_query._STAT_MEDIAN) + str(collect_query._STAT_STDDEV)
    assert "PERCENTILE_CONT(0.5)" in sql
    assert "STDDEV_SAMP" in sql


def test_the_median_respects_the_unit_guard():
    """A median across mg/dL and mmol/L is not a median of anything."""
    from mirobody.collect import query as collect_query

    for macro in (collect_query._STAT_MEDIAN, collect_query._STAT_STDDEV):
        assert "COUNT(DISTINCT unit_ucum) <= 1" in str(macro)


def test_the_new_statistics_reach_the_model():
    """`median` and `stddev` are read by the model only if the stats table
    names them; the column list is fixed, so a row field alone is invisible."""
    from mirobody.agent.tools import _render
    from mirobody.kernel import tools

    row = {"indicator": "restingHeartRates", "count": 30, "min": 55.0, "max": 72.0, "avg": 62.0,
           "median": 61.5, "stddev": 3.62, "sum": 1860.0, "first": "60", "first_date": "2023-10-01",
           "last": "63", "last_date": "2023-10-30", "unit": "bpm"}
    envelope = tools.Envelope(tools.STATUS_OK, data=[row],
                              meta=tools.Meta(view="stats", row_count=1))
    text = _render.render_compact(envelope)
    assert "median=61.5" in text and "stddev=3.62" in text, text[:300]
