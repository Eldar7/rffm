# Metro de la Cantera — Aravaca C.F.

Build pipeline + source for the "Metro de la Cantera" interactive artifact:
an alluvial/Sankey-style map of how Aravaca C.F. youth players move between
lettered teams and divisions across 5 seasons (2021-22 → 2025-26), pivoted on
birth year rather than category (see below for why).

**Published artifact:** https://claude.ai/code/artifact/0343bcea-2855-43f4-bcef-433c009d4a63
(`aravaca_metro_v3.html` in this directory is the last-published source —
update it and republish to this same URL to keep the link, via the `Artifact`
tool: `action: "read"` first to pull the live version, edit, then
`action: "publish"` with `url` set to the URL above.)

## Pipeline (run from the repo root)

```
python3 notebooks/aravaca_metro/build_metro_v3.py    # -> metro_raw_v3.json, intra_transfers_v3.json
python3 notebooks/aravaca_metro/build_links_v3.py     # -> metro_links_v3.json
python3 notebooks/aravaca_metro/finalize_metro_v3.py  # -> metro_final_v3.json
```

Then embed `metro_final_v3.json` into `aravaca_metro_v3.html` by replacing
the `const DATA = {...}` (or `const RAW = {...}`) blob between the `<script>`
tag and the rest of the JS, e.g.:

```python
import re, json
html = open('notebooks/aravaca_metro/aravaca_metro_v3.html', encoding='utf-8').read()
data = json.dumps(json.load(open('notebooks/aravaca_metro/metro_final_v3.json', encoding='utf-8')), ensure_ascii=False)
html2 = re.sub(r'const RAW = \{.*?\};\n', f'const RAW = {data};\n', html, count=1, flags=re.S)
open('notebooks/aravaca_metro/aravaca_metro_v3.html', 'w', encoding='utf-8').write(html2)
```

`team_slug_map_v3.json` is a separate one-time build (slower — replays the
real site's own `team_cards_v2.build_club_team_cards()` +
`site_theme.club_slug_map()` from `analysis_scripts/`, so the artifact's
team_card.html deep links match exactly what the published site generates).
Only needs re-running if new `(season, team_id)` pairs show up:

```python
import sys; sys.path.insert(0, 'analysis_scripts')
import team_cards_v2 as tc, json
from site_theme import club_slug_map
raw = json.load(open('notebooks/aravaca_metro/metro_raw_v3.json', encoding='utf-8'))
pairs = sorted({(s['season'], s['team_id']) for s in raw['stations']})
out, cache = {}, {}
for season, tid in pairs:
    if season not in cache:
        club_teams = tc.build_club_team_cards(season)
        cache[season] = (club_teams, club_slug_map(sorted(club_teams.keys())))
    club_teams, slugs = cache[season]
    found = next(((name, slugs[name]) for name, teams in club_teams.items() if tc.norm_id(tid) in teams), None)
    out[f'{season}|{tid}'] = found
json.dump(out, open('notebooks/aravaca_metro/team_slug_map_v3.json', 'w', encoding='utf-8'), ensure_ascii=False)
```

## Why birth-year, not category

Earlier attempts pivoted on a fixed category-per-season (PREBENJAMÍN 21-22 →
ALEVÍN 25-26) with a recursive lookup ("is this player still at the club
under some other category?") to catch kids who age at a different pace than
the season's nominal category. That recursion is what caused most of the
headaches this was rebuilt to fix:

- **Station id collisions** — `team_id` is a persistent slot reused
  year-over-year, not season-unique, so two different real teams could get
  merged. Fixed (in the old design) with composite `season_idx:team_id`
  ids — still true here.
- **"Bridge station" confusion** — a discovered other-category team showed
  either a misleadingly tiny roster (just the one traced kid) or, when shown
  in full, a mostly-unrelated real squad with zero connections to the
  cohort — looked like a bug either way.
- **The "snowball"** — tracing *every* real teammate on a discovered bridge
  team (not just the specific traced kid) for further discovery converges,
  but only after ~9 rounds, to ~130 stations spanning the *entire* club
  (PREBENJAMÍN through JUVENIL, including the adult AFICIONADO team) — not
  the intended PREBENJAMÍN→ALEVÍN story.

Pivoting on **birth year** sidesteps all of it: a direct SQL query ("every
Aravaca appearance, any team, any category, for players born in year X,
across these 5 seasons") needs no recursion, so there's nothing to snowball,
and every player shown belongs to the cohort by definition — no more
traced-vs-context distinction.

The artifact's pivot selector offers 3 starting points, matching what the
data actually supports:
- `category` — PREBENJAMÍN 2021-22 as a whole (pulls in both its birth years,
  2014 and 2015, as two parallel tracks/sub-columns).
- `by2014` / `by2015` — a single birth year, one track.

Within a season, if the two birth years have diverged into different real
categories (e.g. 2022-23: 2014 already in Benjamín, 2015 still in
Prebenjamín), they render as two side-by-side sub-columns (each labeled with
its birth year) rather than stacked in one shared column. A player playing
outside *either* year's own expected category that season gets a side lane
(clamped to 1 category away), marked with a border pattern (not color, to
avoid clashing with the already-heavily-used palette) — empirically 0 such
cases exist in this specific cohort, so the mechanism is built and tested but
has nothing to show right now.

## Files

| File | What |
|---|---|
| `build_metro_v3.py` | Queries `output/processed/rffm_parquet/*` directly for every Aravaca appearance of players born in 2014 or 2015 (no category filter), classifies each player-season to one team (MIN_APPS≥4 majority, or a genuine intra-season transfer via date-split), and writes per-station rosters. |
| `build_links_v3.py` | From the raw rosters, computes cross-season continuity (`links`), exits (`left_to_club` / `vanished`), and entries (`arrived_from_club` / `new`). No recursive "other category" lookup needed anymore — see above. |
| `finalize_metro_v3.py` | Merges raw + links + intra-transfers + `team_slug_map_v3.json` into the final `metro_final_v3.json` embedded in the artifact; assigns station ids, category ordinals, and a barycenter-ish row order to minimize line crossings. |
| `metro_raw_v3.json` / `metro_links_v3.json` / `intra_transfers_v3.json` / `metro_final_v3.json` | Pipeline outputs, checked in so the artifact can be rebuilt/inspected without re-querying Parquet. |
| `team_slug_map_v3.json` | `"season|team_id" -> [club_name_raw, club_slug]`, for the artifact's `team_card.html` deep links. |
| `aravaca_metro_v3.html` | The artifact source — CSS design tokens/fonts match the rest of this session's Claude Artifacts, JS builds the SVG canvas client-side from the embedded `RAW` data, recomputing per the selected pivot. |

## Known state / open items

- Data is fully converged and clean: 32 stations, 251 links, 68 exits (50
  vanished / 18 left to another club), 1 genuine intra-season transfer.
- **Fullscreen + zoom (built).** `#fsBtn` in the header calls
  `document.documentElement.requestFullscreen()`, falling back to a CSS-only
  `body.fauxfs { position: fixed; inset: 0; z-index: max }` maximize if the
  real Fullscreen API throws (e.g. a host that blocks it) — nothing else is
  hidden in either mode, per an explicit ask to keep header/pivot-bar/legend/
  side-panel all visible. Zoom is `−`/`%`/`+` buttons (10% steps, 25%–300%,
  click `%` to reset to 100%) that set `transform: scale()` on `#zoomWrap`
  (wraps only the `<svg>`). This was **not** a coordinate-math problem in the
  end: `resolveHit()`'s `mousemove`/`click` handlers key off `ev.target` +
  `closest()`, not `getBoundingClientRect()`, and the browser's hit-testing
  already accounts for CSS transforms, so hover/click needed no changes and
  keep working at any zoom (verified with Playwright at 100%/150%). The one
  real gotcha was `#canalLabels` (the vertical band-name overlay) — it's a
  plain HTML div, a *sibling* of `#zoomWrap`, not inside it, because
  `canvas-wrap`'s `padding-left: 100px` gutter it lives in does **not**
  scale; nesting it inside the scaled wrapper was tried first and clips it
  off-screen above ~104% zoom (its `left` offset scales but the gutter
  doesn't). Instead `render()` stores each label's unscaled y in
  `dataset.baseTop`, and `applyZoom()` recomputes `style.top = baseTop *
  zoomLevel` on every zoom change (and once at the end of every `render()`,
  so a pivot switch mid-zoom keeps both the zoom level and label alignment).
