"""Propose catalogue rows for the LOINC Universal Lab Orders a product lacks.

`res/catalog/metrics.tsv` lists the indicators a tool can query. The standard
carries a set of laboratory orders an implementation is expected to support
(`AccessoryFiles/LoincUniversalLabOrdersValueSet`); the overlap is the honest
measure of clinical-lab alignment, and this script produces the rows that close
it.

Facts come from LOINC, shape comes from the catalogue. A row is written only
when it can actually be queried:

  the code must already answer to a name
      otherwise the catalogue would carry an indicator no query can reach. On
      LOINC 2.83 with the bundle as shipped, 315 of the 370 uncovered CHEM
      orders qualify; the other 55 need the bundle rebuilt first.

  unit must match the code's PROPERTY
      mg/dL is a mass concentration, mmol/L a substance concentration, U/L a
      catalytic one. A row whose unit falls outside its code's PROPERTY would
      convert by the wrong chemistry.

  state and policy come from TIME_ASPCT
      Pt -> instant/last, 24H -> provider_daily/provider_value.

  member names follow the specimen
      A generic name belongs to the canonical specimen. When the standard
      measures one component in several specimens, every rendition carries its
      specimen suffix, the serum one included: leaving one of a family bare is
      how a query ends up answered by the wrong specimen.

  qualitative orders are out of scope
      PROPERTY PrThr (presence/absence) cannot be a numeric series; modelling
      it needs a data_type the catalogue does not have. They are counted, not
      written.

Usage:
    python -m standardize_build.loinc_catalog_rows \
        --loinc /path/to/Loinc_2.83 \
        --catalog mirobody/res/catalog/metrics.tsv \
        --class CHEM --out /tmp/chem_rows.tsv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

#: LOINC PROPERTY -> the unit dimensions that may carry it.
PROPERTY_UNITS = {
    "MCnc": {"mg/dL", "g/dL", "mg/L", "ug/mL", "ng/mL", "pg/mL", "g/L", "ug/dL", "ng/dL", "ug/L"},
    "SCnc": {"mmol/L", "umol/L", "nmol/L", "pmol/L", "mol/L"},
    "CCnc": {"U/L", "[IU]/L", "mU/L", "U/mL"},
    "ACnc": {"[IU]/L", "[IU]/mL", "U/L"},
    "NCnc": {"/uL", "10*3/uL", "10*6/uL", "/L"},
    "MFr": {"%"},
    "VFr": {"%", "mL/dL"},
    "Time": {"s", "min", "h"},
}

#: TIME_ASPCT -> (state_class, aggregation_policy)
TIMING = {
    "Pt": ("instant", "last"),
    "24H": ("provider_daily", "provider_value"),
    "12H": ("provider_daily", "provider_value"),
    "8H": ("provider_daily", "provider_value"),
    "4H": ("provider_daily", "provider_value"),
    "1H": ("provider_daily", "provider_value"),
}

#: The specimens a generic indicator name belongs to.
CANONICAL_SYSTEMS = frozenset({"SER", "PLAS", "BLD", "SER/PLAS", "BLD/TISS"})

#: SYSTEM -> suffix used when the specimen is not canonical.
SYSTEM_TAG = {
    "UR": "URINE", "CSF": "CSF", "STL": "STOOL", "SPRM": "SEMEN", "SALV": "SALIVA",
    "BODY FLD": "BODY_FLUID", "AMNIOTIC FL": "AMNIOTIC_FLUID", "GASTRIC": "GASTRIC",
    "SYNOVIAL FL": "SYNOVIAL_FLUID", "PLEURAL FL": "PLEURAL_FLUID",
    "PERITONEAL FL": "PERITONEAL_FLUID", "SWEAT": "SWEAT", "TEARS": "TEARS",
    "MILK": "MILK", "HAIR": "HAIR", "NAIL": "NAIL", "STONE": "STONE",
}


def snake(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", (text or "").strip()).strip("_")
    return re.sub(r"_+", "_", text).upper()


def camel(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text or "")
    if not words:
        return "indicator"
    head = words[0][0].lower() + words[0][1:]
    return head + "".join(w[:1].upper() + w[1:] for w in words[1:])


def assign_names(rows: list[dict]) -> None:
    """Give each row the member and display its specimen deserves."""
    families: dict[str, list[dict]] = {}
    for row in rows:
        families.setdefault(row["_component"], []).append(row)

    for component, family in families.items():
        for row in family:
            system = row["_system"]
            tag = "" if system in CANONICAL_SYSTEMS else SYSTEM_TAG.get(system, snake(system))
            if len(family) > 1:
                # a family needs every member distinguishable, serum included
                tag = tag or "SERUM"
            row["member"] = f"{row['_base']}_{tag}" if tag else row["_base"]
            # member carries the specimen; display stays the name LOINC answers
            if not row["display"]:
                row["display"] = component
            row["name"] = camel(component) + (
                "".join(w.capitalize() for w in tag.split("_")) if tag else "")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--loinc", required=True, type=Path)
    ap.add_argument("--catalog", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--class", dest="klass", action="append", default=[],
                    help="LOINC CLASS to include (repeatable); default CHEM")
    args = ap.parse_args(argv)

    classes = set(args.klass or ["CHEM"])

    with args.catalog.open(encoding="utf-8") as fh:
        existing = list(csv.DictReader(fh, delimiter="\t"))
    have_member = {r["member"] for r in existing}
    have_loinc = {(r.get("loinc") or "").strip() for r in existing} - {""}

    order_set = {
        (r.get("LOINC_NUM") or list(r.values())[0]).strip()
        for r in csv.DictReader(
            (args.loinc / "AccessoryFiles" / "LoincUniversalLabOrdersValueSet"
             / "LoincUniversalLabOrdersValueSet.csv").open(encoding="utf-8"))
    }

    from mirobody.engine import get_resolver
    from mirobody.units import normalize_unit

    resolver = get_resolver()
    rows: list[dict] = []
    reasons: Counter[str] = Counter()

    for rec in csv.DictReader((args.loinc / "LoincTable" / "Loinc.csv").open(encoding="utf-8")):
        code = rec["LOINC_NUM"]
        if code not in order_set or code in have_loinc:
            continue
        if rec.get("CLASS") not in classes or rec.get("STATUS") != "ACTIVE":
            continue
        prop = (rec.get("PROPERTY") or "").strip()
        timing = (rec.get("TIME_ASPCT") or "").strip()
        if prop == "PrThr":
            reasons["定性检验（PrThr），超出目录模型"] += 1
            continue
        if timing not in TIMING:
            reasons["时相不在 instant/24H 之列"] += 1
            continue
        if prop not in PROPERTY_UNITS:
            reasons[f"PROPERTY {prop or '空白'} 无单位维度定义"] += 1
            continue
        unit = normalize_unit(rec.get("EXAMPLE_UCUM_UNITS") or "") or ""
        if unit and unit not in PROPERTY_UNITS[prop]:
            reasons[f"单位 {unit} 与 PROPERTY {prop} 不符"] += 1
            continue
        component = (rec.get("COMPONENT") or "").strip()
        if (rec.get("SYSTEM") or "").strip() in {"XXX", "-"}:
            reasons["标本未指明（SYSTEM XXX）"] += 1
            continue
        base = snake(component)
        if base in have_member:
            reasons["成员名已被占用"] += 1
            continue
        # NOTE: `base` is not reserved here. A component measured in several
        # specimens is one family whose members differ only by the suffix, so
        # reserving the bare name would keep every sibling out.
        # Some name of the code must answer today, or the row is unreachable.
        # That name also becomes the display: a synthesised label ("Creatinine
        # (body_fld)") is not a key the index knows, so the resolver would fall
        # back to the serum code and the row would claim one concept while
        # answering another. 94 of the first 240 proposals failed exactly this
        # way.
        answered = None
        for name in (rec.get("LONG_COMMON_NAME"), component, rec.get("SHORTNAME")):
            if not name:
                continue
            hit = resolver.resolve(name)
            if hit.resolved and hit.loinc == code:
                answered = name
                break
        if answered is None:
            reasons["解析器认不出这个码（需重建 bundle）"] += 1
            continue
        state, policy = TIMING[timing]
        rows.append({
            "_component": component, "_system": (rec.get("SYSTEM") or "").strip(), "_base": base,
            "member": "", "name": "", "display": answered,
            "category": "Medical Metrics", "standard_unit": unit, "unit_ucum": unit,
            "data_type": "series", "state_class": state, "aggregation_policy": policy,
            "loinc": code, "confidence": "confident", "window": "00:00", "panel": "",
            "aggregation_methods": policy, "derived": "",
            "description": (rec.get("LONG_COMMON_NAME") or component)[:80],
            "since": "1.4.0",
        })

    assign_names(rows)
    # the suffix decides uniqueness, so the collision check belongs here
    seen: set[str] = set()
    unique_rows = []
    for row in rows:
        if row["member"] in seen or row["member"] in have_member:
            reasons["命名后仍与其他成员重名"] += 1
            continue
        seen.add(row["member"])
        unique_rows.append(row)
    rows = unique_rows

    for row in rows:
        for key in ("_component", "_system", "_base"):
            row.pop(key, None)

    header = list(existing[0].keys())
    with args.out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, delimiter="\t", lineterminator="\n")
        for row in rows:
            writer.writerow(row)

    print(f"class {sorted(classes)}: {len(rows)} rows proposed")
    for reason, count in reasons.most_common():
        print(f"   skipped {count:4d}  {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
