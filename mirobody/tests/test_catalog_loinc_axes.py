"""Every catalogue row that carries a LOINC code must agree with that code.

`metrics.tsv` is the one table behind every "which indicator is this" decision,
and it carries a LOINC code for 92 of its rows. A code that disagrees with the
row's unit, specimen or analyte is worse than no code: the resolver answers with
confidence, the PROPERTY gate then decides between a mass and a molar code, and
nothing downstream can tell that the row was wrong.

The checks below use only the three axes the shipped index already carries for
each code, so they need no external checklist:

  PROPERTY   must match the unit's dimension — mg/dL is MCnc, mmol/L is SCnc,
             U/L and [IU]/L are CCnc. A row whose unit says mass/volume but
             whose code says substance/volume would convert by molar mass and
             silently change the number.
  SYSTEM     a laboratory indicator is measured in serum, plasma or blood;
             a code for urine or a catheter is a different test.
  COMPONENT  must mention the analyte the row is named after.

Device metrics are exempt from SYSTEM and COMPONENT: `^Patient` is the correct
SYSTEM for a step count, and the COMPONENT of a device code often names the
measure ("Duration of physical activity") rather than the product's label.
Three physiological rows (apnea indices, pulse-wave velocity) sit in the Medical
category but are not serum analytes; they are listed by name rather than being
silently skipped, so that adding a fourth is a visible change.
"""

from __future__ import annotations

import re

from mirobody.engine import get_resolver
from mirobody.kernel import metrics

#: unit UCUM -> the PROPERTY a code measured in that unit must carry
EXPECTED_PROPERTY = {
    "mg/dL": "MCnc",
    "g/dL": "MCnc",
    "mg/L": "MCnc",
    "mmol/L": "SCnc",
    "umol/L": "SCnc",
    "U/L": "CCnc",
    "[IU]/L": "CCnc",
}

#: categories whose rows are laboratory measurements
LAB_CATEGORIES = frozenset({"Medical Metrics", "Metabolic Metrics"})

#: rows in a laboratory category that are not serum analytes, by member
NON_SERUM = frozenset({
    "APNEA_HYPOPNEA_INDEX",
    "OBSTRUCTIVE_APNEA_INDEX",
    "PULSE_WAVE_VELOCITY",
})

SERUM_SYSTEMS = ("ser", "plas", "bld", "blood")

def _rows():
    return [m for m in metrics.METRICS.values() if getattr(m, "loinc", "")]

def _axes_of(code: str):
    resolver = get_resolver()
    row = resolver._row_for_code(code)
    if row is None or row < 0:
        return None
    axis = resolver._axis_row(row)
    return axis

def test_every_code_is_reachable():
    """A code in the catalogue that the index cannot find is a dead reference."""
    resolver = get_resolver()
    unreachable = []
    for m in _rows():
        row = resolver._row_for_code(m.loinc)
        if row is None or row < 0:
            unreachable.append((m.member, m.loinc))
    assert not unreachable, f"codes missing from the shipped axis: {unreachable}"

def test_property_matches_unit():
    """The unit and the code's PROPERTY must agree on the dimension."""
    wrong = []
    for m in _rows():
        if m.category not in LAB_CATEGORIES:
            continue
        if m.member in NON_SERUM:
            continue
        expected = EXPECTED_PROPERTY.get(m.unit_ucum)
        if not expected:
            continue
        axis = _axes_of(m.loinc)
        if axis is None:
            continue
        prop = axis[2]
        if prop and prop != expected:
            wrong.append((m.member, m.loinc, m.unit_ucum, prop, expected))
    assert not wrong, f"unit/PROPERTY mismatch: {wrong}"

def test_lab_rows_are_measured_in_blood():
    """A serum analyte must not carry a urine or catheter code."""
    wrong = []
    for m in _rows():
        if m.category not in LAB_CATEGORIES or m.member in NON_SERUM:
            continue
        axis = _axes_of(m.loinc)
        if axis is None:
            continue
        system = (axis[4] or "").lower()
        if system and not any(s in system for s in SERUM_SYSTEMS):
            wrong.append((m.member, m.loinc, axis[4]))
    assert not wrong, f"non-serum SYSTEM on a laboratory row: {wrong}"

def test_component_mentions_the_analyte():
    """A code whose COMPONENT names something else is the wrong code."""
    wrong = []
    for m in _rows():
        if m.category not in LAB_CATEGORIES or m.member in NON_SERUM:
            continue
        axis = _axes_of(m.loinc)
        if axis is None:
            continue
        component = (axis[6] or "").lower()
        analyte = (m.display or m.name or "").lower()
        words = [w for w in re.findall(r"[a-z]{4,}", analyte)]
        if component and words and not any(w in component for w in words):
            # `phosphate` is printed `phosphorus` in NHANES; compare stems too
            stems = {w[:4] for w in words}
            if not any(s in component for s in stems):
                wrong.append((m.member, m.loinc, component[:40], analyte))
    assert not wrong, f"COMPONENT/analyte mismatch: {wrong}"

def test_a_code_has_a_confidence():
    """`kernel.metrics` refuses this at import; pin it so a schema change shows."""
    for m in _rows():
        assert m.confidence, f"{m.member} carries {m.loinc} without a confidence"

if __name__ == "__main__":  # `python test_catalog_loinc_axes.py` without pytest
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
        except Exception as exc:  # noqa: BLE001 - a runner, not a library
            failures += 1
            print(f"  ERROR {name}: {exc!r}")
    raise SystemExit(1 if failures else 0)
