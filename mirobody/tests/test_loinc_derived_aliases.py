"""The names generated from LOINC must keep answering their own code.

`standardize_build/loinc_aliases.py` derives alias rows from a LOINC release —
the official designations of the codes the catalogue ships, for the ones the
index did not answer yet. This test pins the result without needing the release
present: the manifest the generator writes names each alias and the code it must
answer, and every one of those codes has to be a code the catalogue carries.

Two properties matter:

  the alias answers its own code
      a row that answers a different code is worse than no row: the resolver
      would report an identity the product does not use.

  the code is in the catalogue
      an alias pointing at a code no indicator carries would resolve into
      nothing a tool can query.
"""

from __future__ import annotations

import csv
from pathlib import Path

from mirobody.engine import get_resolver

MANIFEST = Path(__file__).resolve().parents[2] / "standardize_build" / "loinc_alias_manifest.tsv"
CATALOGUE = Path(__file__).resolve().parents[1] / "res" / "catalog" / "metrics.tsv"
SEPARATOR = "\t"


def _manifest() -> list[tuple[str, str]]:
    rows = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        term, code = line.split(SEPARATOR)
        rows.append((term, code))
    return rows


def _catalogue_codes() -> set[str]:
    with CATALOGUE.open(encoding="utf-8") as fh:
        return {(row.get("loinc") or "").strip()
                for row in csv.DictReader(fh, delimiter="\t") if (row.get("loinc") or "").strip()}


def test_the_manifest_is_not_empty():
    """An empty manifest would make the rest of this file vacuous.

    The floor is what the generator found on the catalogue as shipped; it grows
    when more codes are added, never shrinks.
    """
    assert len(_manifest()) >= 3, _manifest()


def test_each_alias_answers_its_own_code():
    resolver = get_resolver()
    wrong = []
    for term, code in _manifest():
        got = resolver.resolve(term)
        if not got.resolved or got.loinc != code:
            wrong.append((term, code, got.loinc or "-"))
    assert not wrong, f"alias does not answer its code: {wrong}"


def test_each_alias_points_at_a_catalogue_code():
    codes = _catalogue_codes()
    orphans = [(term, code) for term, code in _manifest() if code not in codes]
    assert not orphans, f"alias points at a code no indicator carries: {orphans}"


def test_aliases_are_two_column_rows():
    """The overrides file is `term TAB target`; a third column is rejected by
    test_engine_coverage.py, so catch it here too with a clearer message."""
    overrides = CATALOGUE.parents[1] / "loinc" / "resolver_overrides.tsv"
    bad = []
    for number, line in enumerate(overrides.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        if line.count("\t") != 1:
            bad.append((number, line[:60]))
    assert not bad, f"rows that are not term<TAB>target: {bad[:5]}"


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
