"""An empty indicator result must say how to find out what the person has.

Measured on PHIA's objective questions with a local 2B model: 11% of the
failures were the model concluding the record did not contain the metric while
the series existed under a neighbouring name. The tool already set
`next: pick_from_catalog`, which is a token, and the model did not act on it.
The rendering now says in words which call answers "what do I have".
"""

from __future__ import annotations

import pytest

# Minimal installs have no optional chat dependencies; the tool module imports
# them, so skip there rather than fail the engine run.
pytest.importorskip("dotenv")

from mirobody.agent.tools.health_indicators_service import _envelope_for
from mirobody.kernel import query

HINT = "nothing matched these keywords"


def _empty_envelope(view: str = "day"):
    selection = query.Selection(keywords=("deep sleep",))
    window = query.Window(0, 0, "UTC")
    request = query.QueryRequest(selection=selection, view=view)
    return _envelope_for("buckets", request, window, [])


def test_an_empty_result_names_the_catalogue_call():
    envelope = _empty_envelope()
    assert any(HINT in note for note in envelope.assumptions), envelope.assumptions


def test_the_catalogue_pick_step_is_still_advertised():
    envelope = _empty_envelope()
    assert "pick_from_catalog" in envelope.next_steps


def test_a_non_empty_result_does_not_carry_the_hint():
    selection = query.Selection(keywords=("deep sleep",))
    window = query.Window(0, 0, "UTC")
    request = query.QueryRequest(selection=selection, view="day")
    rows = [{"indicator": "dailyDeepSleep", "date": "2026-01-02", "value": 48.0, "unit": "min"}]
    envelope = _envelope_for("buckets", request, window, rows)
    assert not any(HINT in note for note in envelope.assumptions), envelope.assumptions


if __name__ == "__main__":  # runs without pytest
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  PASS {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL {name}: {str(exc)[:200]}")
        except Exception as exc:
            failures += 1
            print(f"  ERROR {name}: {exc!r}")
    raise SystemExit(1 if failures else 0)
