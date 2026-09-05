# Metro de la Cantera — Club Atlético de Madrid

Second club built on the same "Metro de la Cantera" engine as
`notebooks/aravaca_metro/` — read that directory's README first for the full
design rationale (birth-year pivot instead of category, the sub-column
mechanism, sticky/zoomable UI, deep-link mechanics). This file only covers
what's actually different for this club.

**Published artifact:** https://claude.ai/code/artifact/bcdf3213-de26-4da4-b4c8-5b9432a3b59f
(`atletico_metro_v3.html` in this directory is the last-published source —
update it and republish to this same URL via the `Artifact` tool: `action:
"read"` first to pull the live version, edit, then `action: "publish"` with
`url` set to the URL above.)

## How this cohort was picked

Started from a deep link the user pasted:
`https://eldar7.github.io/rffm/team_card.html?season=2025-2026&club=club-atletico-de-madrid-s-a-d&team=39`
— team_id 39 is "CLUB ATLETICO DE MADRID S.A.D. A", Benjamín, División de
Honor, 2025-26, and its entire roster that season is birth year 2016 (one
year, not a 2014/2015-style pair like Aravaca). Added the adjacent 2015
cohort (already one category ahead, in Alevín) to get the same "two
neighboring birth years, category/by-year pivot" shape as Aravaca, per
explicit ask — `PIVOT_BIRTH_YEARS = (2015, 2016)`.

## Why this pipeline is scoped by team_id, not club_name_raw

Aravaca's `names` tuple (a handful of club_name_raw spelling variants) works
because Aravaca is a small club — one team per category, one name to spell a
few ways. Atlético de Madrid is not: `team_club_map` lists **88 distinct
team_ids** under club_id 40024, because a big academy fields several
parallel teams per category (A/B/C/.../letter, each its own team_id) across
every age group, plus adult and reserve sides. Filtering by club_name_raw
text would both under- and over-match here (spelling drifts exactly like
Aravaca's did, *and* the same raw name covers categories nowhere near this
cohort).

So both `build_metro_v3.py` and `build_links_v3.py` resolve `TEAM_IDS` once
from `team_club_map` (`WHERE club_id = 40024`) and filter every lineup/goals
query by `t.team_id IN {TEAM_IDS}` instead of a name tuple. This is *not* the
recursive "is this player somewhere else in the club" search the original
Aravaca design abandoned (see aravaca_metro's README for why that
snowballed) — `team_club_map` is already the closed set of this club's teams,
looked up once, not expanded by following each traced player. The per-player
birth-year filter still does the real work of keeping the story to one
cohort; team_id scoping just replaces name-matching as the "which teams
count as this club" mechanism.

One thing name-matching would have silently pulled in: `CLUB ATLETICO DE
MADRID - FEM.` (women's/girls' section) shares club_id 40024 in
`team_club_map`, and a handful of 2015/2016-born players' matches genuinely
show up under FEM team_ids in the raw lineup data. Excluded via
`t.club_name_raw NOT LIKE '%FEM%'` — a different program, not this cohort's
pathway, and not something Aravaca's README had to consider since Aravaca
has no separate women's section in this data.

## Scale vs. Aravaca

39 stations across 5 seasons (Aravaca: 32), but the shape is different, not
just bigger: a single season can have up to 16 stations here (2024-25) vs.
Aravaca's max of ~7-8, since this cohort's players spread across many
parallel same-category teams (letters up to K/L seen), not just adjacent
categories. Exit-rate composition also differs a lot: 112 of 126 exits are
`left_to_club` (found at a specific other club) vs. only 14 `vanished` —
Aravaca's split was closer to even (18 left_to_club / 50 vanished out of 68).
Both are real, expected differences from being a first-tier academy with
heavy scouting turnover, not a pipeline bug.

## Team-card deep links

`team_slug_map_v3.json` was rebuilt for this club the same way
aravaca_metro's README documents (replays `team_cards_v2.build_club_team_cards()`
+ `site_theme.club_slug_map()` per season) — confirmed it reproduces the
exact URL the user's original deep link used
(`v2/team_card.html?season=2025-2026&club=club-atletico-de-madrid-s-a-d&team=39`).
This step is slow (~30-40s per season, scans the whole season's club list,
not just this club) — ran it in the background rather than blocking on it.

## Files

Same shape as `aravaca_metro/`: `build_metro_v3.py` → `build_links_v3.py` →
`finalize_metro_v3.py` → embed `metro_final_v3.json` into
`atletico_metro_v3.html`'s `const RAW = {...}` (see aravaca_metro's README for
the exact embed snippet — same mechanism, just this directory's paths).
