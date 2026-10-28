"""A window with no readings has to say so, and say which cause it is.

`(no rows)` alone leaves a reader to conclude the record lacks the metric.
There are two causes — the person has no such series, or the series has no
reading in this window — and the response must separate them. Measured on
PHIA's objective set, 11% of the failures were a model concluding the metric
did not exist while the series was there under a neighbouring name.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

# The engine tests also run on a minimal install that has no optional chat
# dependencies; the tool module imports them, so skip rather than fail there.
pytest.importorskip("dotenv")

from mirobody.agent.tools.health_indicators_service import _envelope_for
from mirobody.kernel import query

ZERO = "0 readings"


def _empty_window_envelope():
    selection = query.Selection(indicators=("dailyDeepSleep",))
    window = query.resolve_window("UTC", start="2026-01-01", end="2026-01-07", hours=24,
                                  now=datetime(2026, 10, 14, tzinfo=UTC))
    request = query.QueryRequest(selection=selection, view="day",
                                 start="2026-01-01", end="2026-01-07")
    return _envelope_for("buckets", request, window, [])


def test_an_empty_window_says_zero_rather_than_nothing():
    envelope = _empty_window_envelope()
    note = next((a for a in envelope.assumptions if a.startswith(ZERO)), "")
    assert note, envelope.assumptions
    assert "2026-01-01" in note and "2026-01-07" in note


def test_the_zero_note_names_the_catalogue_as_the_way_out():
    envelope = _empty_window_envelope()
    note = next((a for a in envelope.assumptions if a.startswith(ZERO)), "")
    assert "catalogue" in note


def test_a_result_with_rows_does_not_claim_zero():
    selection = query.Selection(indicators=("dailyDeepSleep",))
    window = query.resolve_window("UTC", start="2026-01-01", end="2026-01-07", hours=24,
                                  now=datetime(2026, 10, 14, tzinfo=UTC))
    request = query.QueryRequest(selection=selection, view="day",
                                 start="2026-01-01", end="2026-01-07")
    rows = [{"indicator": "dailyDeepSleep", "date": "2026-01-02", "value": 47.0, "unit": "min"}]
    envelope = _envelope_for("buckets", request, window, rows)
    assert not any(a.startswith(ZERO) for a in envelope.assumptions), envelope.assumptions
