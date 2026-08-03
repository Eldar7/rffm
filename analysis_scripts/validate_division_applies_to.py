"""
Validate DIVISIONS.md "Applies to" against actual data.

For each season found under output/processed/rffm/, loads competitions.csv
and computes the observed (division_level, category_base) pairs. Then
compares against the documented "Applies to" mapping from DIVISIONS.md.

Outputs:
  - Per-season table of division_level × category_base combinations
  - Cross-season diff: what appears in one season but not the other
  - Gaps vs documented "Applies to" (combinations seen in data but not documented,
    and documented combinations never seen in any season)
  - Inverted view: per-category pyramid in age order

Usage:
    python analysis_scripts/validate_division_applies_to.py          # validate + print
    python analysis_scripts/validate_division_applies_to.py --dump   # also regenerate CATEGORY_PYRAMIDS.md
"""

import sys
import pandas as pd
from pathlib import Path

# ---------------------------------------------------------------------------
# Documented "Applies to" from DIVISIONS.md
# Maps division_level -> set of category_base values considered expected.
# Use None to mean "any / most categories" (won't flag as undocumented).
# ---------------------------------------------------------------------------
DOCUMENTED_APPLIES_TO: dict[str, set[str] | None] = {
    "SUPERLIGA":                  {"ALEVIN", "INFANTIL", "CADETE"},
    "LIGA NACIONAL":              {"JUVENIL"},
    "DIVISION DE HONOR":          {"ALEVIN", "BENJAMIN", "INFANTIL", "CADETE", "JUVENIL"},
    "PRIMERA DIVISION AUTONOMICA": {"AFICIONADO", "ALEVIN", "BENJAMIN", "INFANTIL", "CADETE", "JUVENIL", "PREBENJAMIN"},
    "PREFERENTE":                 {"AFICIONADO", "ALEVIN", "BENJAMIN", "CADETE", "INFANTIL", "JUVENIL", "PREBENJAMIN", "SENIOR"},
    "SEGUNDA DIVISION B":         {"SENIOR"},
    "TERCERA FEDERACION":         None,  # AFICIONADO/FEMENINO expected; appears as category_base=OTHER — open
    "PRIMERA":                    {"AFICIONADO", "ALEVIN", "BENJAMIN", "CADETE", "INFANTIL", "JUVENIL", "PREBENJAMIN", "SENIOR"},
    "SEGUNDA":                    {"AFICIONADO", "ALEVIN", "CADETE", "INFANTIL", "JUVENIL", "SENIOR"},
    "TERCERA":                    {"SENIOR"},
    "FASE ZONAL":                 None,  # youth categories — open
    "CAMPEONATO UNIVERSITARIO":   {"UNIVERSITARIO"},
    "LIGA UNIVERSITARIA":         {"UNIVERSITARIO"},
    "OTHER":                      None,  # any — open
}

# category_base values that are classifier artifacts, not real age groups.
# Rows with these values are reported separately and excluded from gap analysis.
ARTIFACT_CATEGORIES = {"OTHER"}

BASE_DIR = Path(__file__).parent.parent / "output" / "processed" / "rffm"


def load_season(season_dir: Path) -> pd.DataFrame | None:
    path = season_dir / "competitions.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, usecols=["season", "division_level", "category_base"])
    return df


def observed_pairs(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(["division_level", "category_base"])
        .size()
        .reset_index(name="count")
        .sort_values(["division_level", "category_base"])
    )


def main() -> None:
    seasons = sorted(
        d.name for d in BASE_DIR.iterdir()
        if d.is_dir() and (d / "competitions.csv").exists()
    )

    if not seasons:
        print("No season directories with competitions.csv found.")
        return

    season_data: dict[str, pd.DataFrame] = {}
    for season in seasons:
        df = load_season(BASE_DIR / season)
        if df is not None:
            season_data[season] = df
            print(f"\n{'='*60}")
            print(f"Season: {season}  ({len(df)} rows in competitions.csv)")
            print(f"{'='*60}")
            pairs = observed_pairs(df)
            print(pairs.to_string(index=False))

    # -----------------------------------------------------------------------
    # Cross-season diff
    # -----------------------------------------------------------------------
    if len(season_data) >= 2:
        print(f"\n{'='*60}")
        print("Cross-season diff")
        print(f"{'='*60}")
        pair_sets: dict[str, set[tuple[str, str]]] = {}
        for season, df in season_data.items():
            pair_sets[season] = set(
                zip(df["division_level"], df["category_base"])
            )

        all_pairs = set().union(*pair_sets.values())
        rows = []
        for dl, cb in sorted(all_pairs):
            row = {"division_level": dl, "category_base": cb}
            for season in seasons:
                row[season] = "yes" if (dl, cb) in pair_sets.get(season, set()) else " - "
            rows.append(row)
        diff_df = pd.DataFrame(rows)
        print(diff_df.to_string(index=False))

    # -----------------------------------------------------------------------
    # Gap analysis vs DIVISIONS.md
    # -----------------------------------------------------------------------
    print(f"\n{'='*60}")
    print("Gap analysis vs DIVISIONS.md 'Applies to'")
    print(f"{'='*60}")

    all_df = pd.concat(season_data.values(), ignore_index=True)

    # Report artifact rows separately — they are classification noise, not real categories.
    artifact_rows = all_df[all_df["category_base"].isin(ARTIFACT_CATEGORIES)]
    if not artifact_rows.empty:
        print(f"\nRows with artifact category_base ({sorted(ARTIFACT_CATEGORIES)}) — excluded from gap analysis:")
        print(
            artifact_rows.groupby(["division_level", "category_base"])
            .size()
            .reset_index(name="count")
            .to_string(index=False)
        )

    clean_df = all_df[~all_df["category_base"].isin(ARTIFACT_CATEGORIES)]
    all_pairs_by_dl: dict[str, set[str]] = (
        clean_df.groupby("division_level")["category_base"]
        .apply(set)
        .to_dict()
    )

    undocumented_dl: list[str] = []
    unexpected_categories: list[tuple[str, str, str]] = []
    unseen_documented: list[tuple[str, str]] = []

    for dl, observed_cats in all_pairs_by_dl.items():
        if dl not in DOCUMENTED_APPLIES_TO:
            undocumented_dl.append(dl)
            continue
        expected = DOCUMENTED_APPLIES_TO[dl]
        if expected is None:
            continue  # open / "most categories" — no check needed
        for cat in observed_cats - expected:
            unexpected_categories.append((dl, cat, "in data, NOT in docs"))

    for dl, expected in DOCUMENTED_APPLIES_TO.items():
        if expected is None:
            continue
        observed_cats = all_pairs_by_dl.get(dl, set())
        for cat in expected - observed_cats:
            unseen_documented.append((dl, cat))

    if undocumented_dl:
        print("\nDivision levels seen in data but NOT in DIVISIONS.md:")
        for dl in sorted(undocumented_dl):
            cats = sorted(all_pairs_by_dl[dl])
            print(f"  {dl!r:40s}  categories: {cats}")
    else:
        print("\nAll division levels in data are documented. OK")

    if unexpected_categories:
        print("\nCategory/division_level combos in data but outside documented 'Applies to':")
        for dl, cat, note in sorted(unexpected_categories):
            print(f"  {dl!r:40s}  {cat!r:20s}  ({note})")
    else:
        print("No unexpected category/division_level combos. OK")

    if unseen_documented:
        print("\nDocumented 'Applies to' combos NEVER seen in any season's data:")
        for dl, cat in sorted(unseen_documented):
            print(f"  {dl!r:40s}  {cat!r}")
    else:
        print("All documented 'Applies to' combos appear in at least one season. OK")

    # -----------------------------------------------------------------------
    # Inverted view: per-category pyramid (aggregated across all seasons)
    # -----------------------------------------------------------------------
    CATEGORY_ORDER = [
        "PREBENJAMIN", "BENJAMIN", "ALEVIN", "INFANTIL", "CADETE",
        "JUVENIL", "SENIOR", "AFICIONADO", "VETERANOS", "UNIVERSITARIO",
    ]
    TIER_LABEL = {
        "SUPERLIGA": 1, "LIGA NACIONAL": 1,
        "DIVISION DE HONOR": 2,
        "PRIMERA DIVISION AUTONOMICA": 3,
        "PREFERENTE": 4,
        "SEGUNDA DIVISION B": 5, "TERCERA FEDERACION": 5,
        "PRIMERA": 6,
        "SEGUNDA": 7,
        "TERCERA": 8,
    }

    print(f"\n{'='*60}")
    print("Per-category pyramid (all seasons combined, age order)")
    print(f"{'='*60}")

    all_pairs_by_cat: dict[str, set[str]] = (
        all_df[~all_df["category_base"].isin(ARTIFACT_CATEGORIES)]
        .groupby("category_base")["division_level"]
        .apply(set)
        .to_dict()
    )

    observed_order = [c for c in CATEGORY_ORDER if c in all_pairs_by_cat]
    unordered = sorted(c for c in all_pairs_by_cat if c not in CATEGORY_ORDER)

    for cat in observed_order + unordered:
        dls = all_pairs_by_cat[cat]
        ranked = sorted(
            (dl for dl in dls if dl in TIER_LABEL),
            key=lambda x: TIER_LABEL[x],
        )
        untiered = sorted(dl for dl in dls if dl not in TIER_LABEL)
        print(f"\n{cat}:")
        for dl in ranked:
            print(f"  ({TIER_LABEL[dl]}) {dl}")
        for dl in untiered:
            print(f"  (-) {dl}")

    if "--dump" in sys.argv:
        _dump_category_pyramids(
            all_pairs_by_cat, observed_order, unordered, TIER_LABEL, seasons
        )


def _dump_category_pyramids(
    all_pairs_by_cat: dict,
    ordered_cats: list,
    extra_cats: list,
    tier_label: dict,
    seasons: list,
) -> None:
    AGE_META = {
        "PREBENJAMIN": ("6–7", "2019–2020"),
        "BENJAMIN":    ("8–9", "2017–2018"),
        "ALEVIN":      ("10–11", "2015–2016"),
        "INFANTIL":    ("12–13", "2013–2014"),
        "CADETE":      ("14–15", "2011–2012"),
        "JUVENIL":     ("16–18", "2008–2010"),
        "SENIOR":      ("19+ (federated)", "≤ 2007"),
        "AFICIONADO":  ("19+ (amateur)", "≤ 2007"),
        "UNIVERSITARIO": ("—", "—"),
        "VETERANOS":   ("35+", "—"),
    }
    BOTTOM_NOTES = {
        "PREBENJAMIN": "_No SEGUNDA or lower observed. PRIMERA is the floor of the pyramid._",
        "BENJAMIN":    "_No SEGUNDA or lower observed. PRIMERA is the floor of the pyramid._",
        "SENIOR": (
            "_PREFERENTE is the top of the regional (RFFM) ladder. "
            "SEGUNDA DIVISION B is a parallel RFEF federation track, "
            "not a tier above PREFERENTE in the regional pyramid._"
        ),
        "JUVENIL": "_Note: LIGA NACIONAL replaces SUPERLIGA as the top tier for Juvenil._",
    }
    YOUTH = ["PREBENJAMIN", "BENJAMIN", "ALEVIN", "INFANTIL", "CADETE", "JUVENIL"]
    ADULT = ["SENIOR", "AFICIONADO"]
    SPECIAL = ["UNIVERSITARIO", "VETERANOS"]
    SPECIAL_NOTES = {
        "UNIVERSITARIO": "_Separate pyramid, independent of the standard age progression._",
        "VETERANOS": "_Only unclassified (OTHER) competitions observed in crawled seasons — no named division tier yet._",
    }

    seasons_str = " and ".join(f"**{s}**" for s in seasons)

    lines = [
        "# RFFM Category Pyramids",
        "",
        "Division ladder for each age group, aggregated across all crawled seasons.",
        "Tier numbers match `DIVISIONS.md`. `(-)` entries are competition phases or",
        "unclassified competitions, not ranked tiers.",
        "",
        "> **Generated by** `analysis_scripts/validate_division_applies_to.py --dump`",
        "> — re-run when a new season is added to keep this file current.",
        "",
        "---",
        "",
        "## Youth categories (age progression)",
    ]

    def cat_section(cat: str) -> list[str]:
        dls = all_pairs_by_cat.get(cat, set())
        ranked = sorted((dl for dl in dls if dl in tier_label), key=lambda x: tier_label[x])
        untiered = sorted(dl for dl in dls if dl not in tier_label)
        age, birth = AGE_META.get(cat, ("—", "—"))
        age_part = f" — age {age}" if age not in ("—", "") else ""
        birth_part = f" · born {birth}" if birth not in ("—", "") else ""
        header = f"### {cat}{age_part}{birth_part}"
        out = ["", "---", "", header, ""]
        PHASE_LABELS = {
            "FASE ZONAL": "qualifying phase",
            "CAMPEONATO UNIVERSITARIO": "university championship",
            "LIGA UNIVERSITARIA": "university league",
        }
        if ranked:
            top_tier = tier_label[ranked[0]]
            bot_tier = tier_label[ranked[-1]]
            out += ["| Tier | Division level |", "|------|----------------|"]
            for dl in ranked:
                t = tier_label[dl]
                label = f"{t} | {dl}"
                if t == top_tier and t == bot_tier:
                    label += " ← only tier"
                elif t == top_tier:
                    label += " ← top"
                elif t == bot_tier:
                    label += " ← bottom"
                out.append(f"| {label} |")
            for dl in untiered:
                if dl == "OTHER":
                    continue  # classifier artifact — not meaningful to list
                note = PHASE_LABELS.get(dl, "phase")
                out.append(f"| — | {dl} ({note}) |")
        else:
            for dl in untiered:
                if dl == "OTHER":
                    continue
                out.append(f"- `{dl}`")
        if cat in BOTTOM_NOTES:
            out += ["", BOTTOM_NOTES[cat]]
        if cat in SPECIAL_NOTES:
            out += ["", SPECIAL_NOTES[cat]]
        return out

    for cat in YOUTH:
        if cat in all_pairs_by_cat:
            lines += cat_section(cat)

    lines += ["", "---", "", "## Adult categories"]
    for cat in ADULT:
        if cat in all_pairs_by_cat:
            lines += cat_section(cat)

    lines += ["", "---", "", "## Special categories"]
    for cat in SPECIAL:
        if cat in all_pairs_by_cat:
            lines += cat_section(cat)
        else:
            age, birth = AGE_META.get(cat, ("—", "—"))
            lines += ["", "---", "", f"### {cat} — age {age}", "",
                      "No data observed in crawled seasons.", ""]

    for cat in extra_cats:
        if cat not in (YOUTH + ADULT + SPECIAL):
            lines += cat_section(cat)

    lines += [
        "",
        "---",
        "",
        "## Notes",
        "",
        "- Tier gaps (e.g. no tier 5 in youth, no tier 2–3 in SENIOR) reflect actual",
        "  RFFM structure — those division levels simply do not apply to that age group.",
        "- `FASE ZONAL` and `OTHER` are not ranked tiers: FASE ZONAL is a cross-zone",
        "  playoff phase; OTHER means no division token was found in the competition name.",
        f"- Data covers seasons {seasons_str}. A new top or bottom tier",
        "  may appear in future seasons — re-run the generator to update.",
    ]

    out_path = Path(__file__).parent.parent / "CATEGORY_PYRAMIDS.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
