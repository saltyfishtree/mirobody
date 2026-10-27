"""The rows added from the LOINC Universal Lab Orders must stay queryable.

Each row in this PR was written only if three things held, and this test keeps
them true without needing the LOINC release present:

  the catalogue row exists         member, code and unit all as generated
  the display answers its code     a row whose label resolves to a different
                                   code claims one concept and answers another
  the unit matches the PROPERTY    mg/dL is a mass concentration; mmol/L a
                                   substance one. A unit outside its code's
                                   PROPERTY converts by the wrong chemistry.

The manifest carries the three facts per row, so a hand edit to metrics.tsv is
caught here rather than in a query.
"""

from __future__ import annotations

from pathlib import Path

from mirobody.engine import get_resolver
from mirobody.kernel import metrics

MANIFEST = (Path(__file__).resolve().parents[2] / "standardize_build"
            / "universal_order_manifest.tsv")

#: unit UCUM -> the LOINC PROPERTY values that may carry it. A set, because
#: [IU]/L is a catalytic concentration for an enzyme and an arbitrary one for
#: IgE or hCG; the code decides, the unit only narrows.
EXPECTED_PROPERTY = {
    "mg/dL": {"MCnc"}, "g/dL": {"MCnc"}, "mg/L": {"MCnc"}, "ug/mL": {"MCnc"},
    "ng/mL": {"MCnc"}, "pg/mL": {"MCnc"}, "g/L": {"MCnc"}, "ug/dL": {"MCnc"},
    "ng/dL": {"MCnc"}, "ug/L": {"MCnc"},
    "mmol/L": {"SCnc"}, "umol/L": {"SCnc"}, "nmol/L": {"SCnc"}, "pmol/L": {"SCnc"},
    "U/L": {"CCnc"}, "[IU]/L": {"CCnc", "ACnc"}, "mU/L": {"CCnc"}, "U/mL": {"CCnc"},
    "MFr": {"MFr"}, "VFr": {"VFr"},
}


def _by_member():
    """`metrics.METRICS` is keyed by the catalogue's lowerCamel `name`, so the
    member column needs its own index."""
    return {m.member: m for m in metrics.METRICS.values()}


def _manifest() -> list[tuple[str, str, str]]:
    rows = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        member, code, unit = line.split("\t")
        rows.append((member, code, unit))
    return rows


def test_the_catalogue_carries_every_manifest_row():
    index = _by_member()
    missing = [m for m, _c, _u in _manifest() if m not in index]
    assert not missing, f"manifest rows absent from the catalogue: {missing[:5]}"


def test_each_row_keeps_its_code_and_unit():
    index = _by_member()
    wrong = []
    for member, code, unit in _manifest():
        row = index.get(member)
        if row is None:
            continue
        if row.loinc != code or (row.unit_ucum or "") != unit:
            wrong.append((member, code, row.loinc, unit, row.unit_ucum))
    assert not wrong, f"row drifted from its manifest entry: {wrong[:5]}"


def test_each_display_answers_its_own_code():
    resolver = get_resolver()
    index = _by_member()
    wrong = []
    for member, code, _unit in _manifest():
        row = index.get(member)
        if row is None:
            continue
        hit = resolver.resolve(row.display)
        if not hit.resolved or hit.loinc != code:
            wrong.append((member, code, hit.loinc or "-"))
    assert not wrong, f"display answers a different code: {wrong[:5]}"


def test_each_unit_matches_its_code_property():
    resolver = get_resolver()
    wrong = []
    for member, code, unit in _manifest():
        expected = EXPECTED_PROPERTY.get(unit)
        if not expected:
            continue
        axis = resolver._axis_row(resolver._row_for_code(code))
        prop = axis[2] if axis else ""
        if prop and prop not in expected:
            wrong.append((member, code, unit, prop, sorted(expected)))
    assert not wrong, f"unit/PROPERTY mismatch: {wrong[:5]}"


def test_no_member_name_is_used_twice():
    names = [m for m, _c, _u in _manifest()]
    duplicates = {n for n in names if names.count(n) > 1}
    assert not duplicates, f"duplicate members: {sorted(duplicates)[:5]}"


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
