"""Derive resolver aliases from a LOINC release, for the codes the product ships.

The catalogue names its indicators in the product's own words ("Blood Glucose",
"Alanine aminotransferase"). LOINC names the same concepts in the standard's
words, and every LOINC term carries the synonyms an implementer needs: its
long common name, its short name, its consumer name and RELATEDNAMES2. Reading
those from the release is the ontology-driven way to widen the vocabulary — the
alternative, harvesting printed strings from a report or a benchmark, only
covers the producer those strings came from.

Three rules keep this safe:

  fill a gap, never redirect a hit
      a candidate is emitted only when the alias index currently answers
      nothing for it, or already answers the intended code. A broad synonym
      ("Glucose") must not take over a term that today resolves to something
      more specific.

  one term, one code
      a synonym that names two different codes inside the catalogue is
      dropped: LOINC's RELATEDNAMES2 lists the words of the concept, not a
      disambiguated label.

  the target must be reachable
      the right-hand side is the code's LONG_COMMON_NAME, and the row is
      written only if that name resolves back to the code. An override that
      points at a dead key is worse than no override.

Usage:
    python -m standardize_build.loinc_aliases \
        --loinc /path/to/Loinc_2.83 \
        --catalog mirobody/res/catalog/metrics.tsv \
        --out /tmp/loinc_alias_rows.tsv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

#: Words that describe how a value is reported rather than what was measured.
#: RELATEDNAMES2 lists them for almost every term, and as alias keys they would
#: answer "Plasma" with whichever analyte happened to be indexed first.
GENERIC = frozenset({
    "chemistry", "level", "point in time", "random", "quantitative", "quantitating",
    "quantity", "qnt", "quan", "quant", "ordinal", "nominal", "qualitative", "qly",
    "pl", "plsm", "plasma", "ser", "serum", "bld", "blood", "ur", "urine", "csf",
    "mass concentration", "substance concentration", "catalytic concentration",
    "mcnc", "scnc", "ccnc", "ncnc", "acnc", "clinical", "clin", "screen", "test",
    "panel", "ord", "time", "pt", "titer", "arbitrary concentration", "-", "1", "2",
    "predicted", "measured", "calculated", "estimated",
})

#: A designation this short is an abbreviation that collides across analytes
#: (``Fe`` iron against ``FE``, ``K`` potassium against a dozen others). LOINC
#: itself uses them, but only next to a specimen and a class, which a bare
#: alias key does not carry.
MIN_LEN = 3


def catalogue_codes(path: Path) -> dict[str, str]:
    """LOINC_NUM -> the product's display name, for rows that carry a code."""
    out: dict[str, str] = {}
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            code = (row.get("loinc") or "").strip()
            if code:
                out[code] = (row.get("display") or row.get("member") or "").strip()
    return out


#: The designations that are names of the concept. RELATEDNAMES2 is excluded on
#: purpose: measured on this catalogue it yields "Creat" for creatinine, "Gluc"
#: for glucose, "Prot" for protein and "Tissue" for perfusion index — lexical
#: fragments and filing words, not names a report would ever print. Fifteen
#: such rows were generated before the exclusion and every one was unsafe.
ALIAS_FIELDS = ("LONG_COMMON_NAME", "SHORTNAME", "COMPONENT", "CONSUMER_NAME")


def designations(row: dict[str, str]) -> list[tuple[str, str]]:
    """(field, text) for every *name* LOINC gives a term."""
    out: list[tuple[str, str]] = []
    for field in ALIAS_FIELDS:
        text = (row.get(field) or "").strip()
        if text:
            out.append((field, text))
    return out


#: Right-hand sides to try, in order. A LONG_COMMON_NAME is the most precise
#: but the bundle does not index every one of them ("Lactate dehydrogenase
#: [Enzymatic activity/volume] in Serum or Plasma" answers nothing, while
#: "Lactate dehydrogenase" answers 14804-9), so the component and the short
#: name are tried first and the long name last.
TARGET_FIELDS = ("COMPONENT", "SHORTNAME", "LONG_COMMON_NAME")


def _shares_stem(term: str, long_name: str) -> bool:
    """Does `term` share a four-character stem with `long_name`?

    "Hematology" against "Bilirubin.total [...]" -> no, so it is a shelf.
    "Creat" against "Creatinine [...]"           -> yes, an abbreviation.
    "Tumor marker" against "Lactate dehydrogenase [...]" -> no.
    """
    words = re.findall(r"[a-z]{4,}", long_name.lower())
    if not words:
        return False
    stem = term.lower()[:4]
    return any(word[:4] == stem or stem in word for word in words)


def class_words(loinc_dir: Path) -> frozenset[str]:
    """Every LOINC CLASS value, lowercased.

    RELATEDNAMES2 lists the words a term is filed under as well as synonyms:
    glucose carries "Endocrine" and "Endocrinology", bilirubin carries
    "Hematology", bicarbonate carries "Pulmonary". As alias keys those answer a
    category question with one arbitrary analyte, so a term that names a CLASS
    is never an alias.
    """
    out: set[str] = set()
    with (loinc_dir / "LoincTable" / "Loinc.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            for word in (row.get("CLASS") or "").split("."):
                word = word.strip().lower()
                if word:
                    out.add(word)
    return frozenset(out)


def candidates(loinc_dir: Path, codes: dict[str, str],
               class_names: frozenset[str]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """term -> [codes that claim it], plus code -> candidate target names."""
    claims: dict[str, list[str]] = defaultdict(list)
    targets: dict[str, list[str]] = {}
    with (loinc_dir / "LoincTable" / "Loinc.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            code = row["LOINC_NUM"]
            if code not in codes or row.get("STATUS") != "ACTIVE":
                continue
            targets[code] = [(row.get(f) or "").strip() for f in TARGET_FIELDS]
            for field, text in designations(row):
                if len(text) < MIN_LEN or text.lower() in GENERIC:
                    continue
                if text.lower() in class_names:
                    continue
                # RELATEDNAMES2 also carries the shelves a term is filed on
                # ("Endocrine" under glucose, "Hematology" under bilirubin,
                # "Pulmonary" under bicarbonate). Those are not other names of
                # the analyte, and as keys they would answer a category
                # question with one arbitrary member. A real synonym shares a
                # stem with the term it names; a shelf does not. The stem test
                # is deliberately loose (first four characters) so that
                # abbreviations LOINC itself lists survive.
                if field == "RELATEDNAMES2" and not _shares_stem(
                        text, row.get("LONG_COMMON_NAME") or ""):
                    continue
                claims[text].append(code)
    return claims, targets


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--loinc", required=True, type=Path, help="unpacked LOINC release directory")
    ap.add_argument("--catalog", required=True, type=Path, help="metrics.tsv")
    ap.add_argument("--out", required=True, type=Path, help="where to write the alias rows")
    ap.add_argument("--manifest", type=Path,
                    help="also write <term> TAB <code>, so a test can check the rows "
                         "without a LOINC release present")
    args = ap.parse_args(argv)

    codes = catalogue_codes(args.catalog)
    class_names = class_words(args.loinc)
    claims, target_names = candidates(args.loinc, codes, class_names)

    from mirobody.engine import get_resolver
    resolver = get_resolver()

    # one reachable target per code, most precise that the index actually answers
    target_of: dict[str, str] = {}
    for code, names in target_names.items():
        for name in names:
            if not name:
                continue
            back = resolver.resolve(name)
            if back.resolved and back.loinc == code:
                target_of[code] = name
                break

    rows: list[tuple[str, str, str]] = []      # term, target, source
    dropped_ambiguous = dropped_dead_target = dropped_would_redirect = 0
    for term, owners in sorted(claims.items()):
        # every rendition of the same concept (187 codes share nothing, but a
        # synonym can legitimately point at one code through several fields)
        if len(owners) > 1:
            dropped_ambiguous += 1
            continue
        code = owners[0]
        target = target_of.get(code, "")
        if not target:
            dropped_dead_target += 1
            continue
        current = resolver.resolve(term)
        if current.resolved and current.loinc != code:
            # the index already answers this term with another code; taking it
            # over would trade a deliberate decision for a synonym list
            dropped_would_redirect += 1
            continue
        if current.resolved and current.loinc == code:
            continue                                # already right, no row needed
        rows.append((term, target, code))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write("# Derived by standardize_build.loinc_aliases from a LOINC release.\n")
        fh.write("# <printed term> TAB <a name the index answers for that code>. Source:\n")
        fh.write("# SHORTNAME and CONSUMER_NAME of the codes res/catalog/metrics.tsv carries.\n")
        # exactly two columns: the file's own test rejects a third
        for term, target, _code in rows:
            fh.write(f"{term}\t{target}\n")

    if args.manifest:
        with args.manifest.open("w", encoding="utf-8") as fh:
            fh.write("# <printed term>\t<the LOINC code it must resolve to>\n")
            for term, _target, code in rows:
                fh.write(f"{term}\t{code}\n")

    print(f"catalogue codes with a LOINC row: {len(codes)}")
    print(f"candidate terms:                  {len(claims)}")
    print(f"rows written:                     {len(rows)}")
    print(f"dropped, names two codes:         {dropped_ambiguous}")
    print(f"dropped, target unreachable:      {dropped_dead_target}")
    print(f"dropped, would redirect a hit:    {dropped_would_redirect}")
    print(f"class names excluded as aliases:  {len(class_names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
