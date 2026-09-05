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

- **Header/panel toggles: settled in `.view-controls`, "hide header" only
  collapses `.brand`+`.stats-row`.** Went back and forth on where these two
  buttons live. First cut put `#panelToggleBtn` in the header's
  `.view-controls` and `#headerToggleBtn` in the pivot-bar — wrong pairing,
  and the header toggle wrapped onto its own odd row since it was alone
  with `margin-left: auto` in a bar with little else in it. Tried moving
  `#panelToggleBtn` to join it in the pivot-bar instead — also wrong: the
  ask was to restore `#panelToggleBtn` to its original, correct spot in
  `.view-controls` and bring `#headerToggleBtn` to it instead, not the
  reverse. Both buttons are back in `.view-controls` now, next to the zoom
  controls and fullscreen toggle.
  That still leaves the puzzle from the first design pass: `#headerToggleBtn`
  lives inside `<header>`, so if "hide header" hid the *whole* `<header>`
  element, it'd take its own toggle down with it — no way to bring it back.
  Resolved by scoping what "hidden" means: `body.header-hidden` now hides
  only `.brand` and `.stats-row` (the logo/title/stats — purely
  informational), while `.view-controls` (all four buttons) stays visible
  regardless, since it's a *sibling* of `.brand`/`.stats-row` inside
  `<header>`, not hidden itself.
- **Header hideable, side panel wider + resizable.** `#headerToggleBtn` (in
  the pivot-bar, so it's still reachable once the header itself is hidden)
  toggles `body.header-hidden`, same `display:none` pattern as the legend/
  panel toggles. The side panel's default width went from 300px to 405px
  (+35%) and gained a native `resize: horizontal` handle (`min-width:
  160px`, `max-width: 70vw`).
  Getting the wider default to actually render took a second fix:
  `.panel`'s `flex: 0 1 300px` used a fixed-length flex-basis, which the
  native resize handle's inline `width` can't override (a flex item's main
  size comes from flex-basis when it's a definite length, not from
  `width`) — changed to `flex: 0 1 auto` + a real `width: 405px`, so
  flex-basis resolves *from* that width instead of overriding it, and
  `resize` (which sets `width` inline) has something to actually act on.
  That alone still rendered at 276px, not 405 — `#canvasWrap`'s own
  `flex: 1 1 auto` gives it an "auto" flex-basis that resolves to its own
  *content's* natural preferred width (the SVG, easily 1700px+), and
  flexbox's shrink distribution is weighted by each item's flex-basis —
  so canvas-wrap's huge preferred size was dragging `.panel` down
  proportionally too, even with hundreds of spare pixels available
  page-wide. Fixed by giving canvas-wrap an explicit `flex: 1 1 0` — basis
  0 instead of content-derived, the standard idiom for "grow to fill
  remaining space regardless of what's inside," which stops it from
  skewing the shrink weighting.
- **Backing bands tried, then reverted; the real left-edge-gap bug found
  underneath.** After narrowing the gutter for mobile, the row labels sat
  flush against — effectively inside — the diagram's own tinted content.
  First fix was a `--surface-card` backing band behind both label overlays
  (`#canalLabelsBg`/`#seasonHeadersBg`) so they'd read as a clearly
  separate strip. Explicitly asked to revert: wanted the pre-band look
  back (translucent labels only, nothing solid blocking the diagram) —
  those elements are gone again. (The `--season-stripe` per-season column
  tint from the header redesign is a *different* thing and stayed;
  "revert the labels" wasn't "revert the stripe.")
  Removing the band exposed the actual bug the band had been *hiding*
  rather than fixing: `.canal-label`'s `left: 8px` (from the pre-sticky
  `position: absolute` design, where `left` resolves at the containing
  block's *padding* edge) was carried over unchanged into the sticky
  overlay, where `left` instead resolves at canvas-wrap's *content* edge
  (after padding) — the same edge `#zoomWrap` (the diagram) starts from.
  So the label was never sitting in the gutter at all; it started exactly
  where the diagram does and read as "inside the table" independent of the
  band. Fixed with `CANAL_LABEL_LEFT_BASE = CANAL_LABEL_EDGE_GAP -
  ROW_GUTTER_BASE` (both constants, currently `3` and `42`) — a *negative*
  base left that pulls the label back before the content edge, into the
  gutter, landing it a constant `CANAL_LABEL_EDGE_GAP` from the true left
  edge at any zoom (`applyZoom()` scales it by `zoomLevel` like everything
  else here, so the gap stays proportionally minimal rather than growing
  with zoom). `ROW_GUTTER_BASE` also dropped from 60 to 42 (just enough
  for the label's own wrapped width, no longer padded out for a band that
  doesn't exist anymore).
  The header line-overlap-at-zoom bug found alongside this (title/category/
  years colliding at high zoom, since only their font size scaled with
  zoom, not the fixed gaps between them) is unrelated to the band and
  stayed fixed: `BASE_TOP` per header class, multiplied by `zoomLevel` in
  `applyZoom()` next to the existing `BASE_FONT_SIZE`.
- **Mobile fixes: label font didn't zoom, sticky labels sat in the wrong
  place, gutters too wide.** All three turned out to share one root cause,
  found by testing (headless Chromium can't be trusted to report the real
  device viewport unless the artifact's own `<meta viewport>` tag is
  present — the raw repo file has none, since the publish wrapper adds it;
  had to test against a manually re-wrapped copy to see what a phone
  actually sees): several header-area flex rows (`.view-controls`,
  `.legend .grp`, `.pivot-bar`) had no `flex-wrap`, so on a narrow screen
  their un-wrappable content forced the *entire page* — `window.innerWidth`
  itself, not just those rows — wider than the real device width (measured
  646px on a 390px-wide phone before the fix). Every sticky/rescale
  computation was then correct *relative to that inflated width*, which is
  exactly why the row labels looked shifted right of where they belonged
  on a real phone: the whole page was laid out for a phantom ~650px screen
  and rendered zoomed out to fit. Fixed by adding `flex-wrap: wrap` to all
  three; `.panel` also changed from `flex: 0 0 300px` (a hard floor that
  alone needed 300px + canvas-wrap's own minimum gutter width to coexist)
  to `flex: 0 1 300px; min-width: 160px` so it can shrink instead of
  forcing overflow.
  Once that was fixed, the other two were direct: canvas-wrap's padding
  dropped from `18px 40px 40px 100px` to `12px 16px 16px 44px` (the row
  label gutter alone was 100px for ~11px-wide vertical text) — verified
  the tier names still fit without new wrapping at the smaller size, on a
  simulated 390px-wide viewport with the canvas around 230px. And the
  header/row-label font sizes, which `applyZoom()` was deliberately *not*
  scaling (a design call at the time, to match the pre-existing
  canal-label precedent) — reverted that: `BASE_FONT_SIZE` now holds each
  overlay class's 100%-zoom size, and `applyZoom()` multiplies it by
  `zoomLevel` alongside the existing position rescale.
  **Not fixed, found along the way:** the legend (5 groups) previously
  overflowed the page width silently on narrow screens instead of
  wrapping; now that `.grp` wraps, it instead grows very tall (each
  swatch group stacks to multiple lines), pushing the canvas far down a
  phone-height viewport. The existing fullscreen legend-collapse toggle
  doesn't apply outside fullscreen — worth extending to narrow viewports
  too, but that's a separate change from what was asked here.
- **Column headers redesigned + made sticky.** Season titles are now centered
  over the *whole* season (all its lanes combined, via `text-anchor: middle`
  at `x0 + totalW/2`) rather than left-aligned at the season's edge — so
  "2022-2023" sits centered over both its Prebenjamín and Benjamín
  sub-columns. Each lane gets its own centered category name + a
  birth-year/age line (`ageAtSeason()`: season's first year minus birth
  year, e.g. 2022-2023 → 2015 is "7 y.o.") — combined onto one line
  ("2015, 6 y.o.; 2014, 7 y.o.") when the season's two birth years still
  share a lane, split into two lines/lanes once they've diverged into
  different categories. Season columns alternate a subtle background tint
  (`--season-stripe`, one new CSS var per theme) painted *behind* the
  existing division-tier bands so the two subtle overlays compose instead
  of clashing.

  These header labels, and the division-tier row labels (`#canalLabels`,
  already existed), moved from SVG text / a scroll-along HTML overlay to
  two dedicated sticky HTML overlays (`#seasonHeaders` sticky-top,
  `#canalLabels` now sticky-left) so both stay on screen through any
  scroll — the classic spreadsheet frozen-row/frozen-column pattern. Both
  are zero-size (`width/height: 0`) normal-flow siblings of `#zoomWrap` so
  `position: sticky` has a real scrollport to stick against (it doesn't
  work reliably on elements inside a `transform`-scaled ancestor, which is
  exactly what `#zoomWrap` is — this is *why* they're siblings of it, not
  children); their labels are absolutely positioned within via
  `data-base-left`/`data-base-top`, rescaled by `applyZoom()` exactly like
  the pre-existing canal-label trick, just on the horizontal axis this
  time. **The bug that first shipped:** both overlays got a `top: 0` *and*
  `left: 0` sticky inset — that pins an element to a corner immediately,
  ignoring scroll on **both** axes, which silently no-ops the entire
  feature (nothing ever visibly moved, in either direction, at any scroll
  position — caught by comparing element position before/after a
  synthetic scroll in Playwright, since it looked fine by eye at rest).
  Fixed to exactly one inset per overlay (`left: 0` only for the row
  labels, `top: 0` only for the headers) so the other axis tracks scroll
  normally. Both are `opacity: 0.82` — translucent since, once scrolled,
  they float over live diagram content rather than blank margin.
- **Side panel is hideable.** `#panelToggleBtn` in the header toggles
  `body.panel-hidden`, which just `display: none`s `.panel` — `canvas-wrap`
  is `flex: 1 1 auto` so it reclaims the ~300px on its own, no layout math
  needed. Independent of fullscreen (unlike the legend, it doesn't
  auto-hide on entering fullscreen) and, like the other toggles, untouched
  by `render()` so it survives a pivot switch.
- **Team-card deep link fixed.** The "Abrir carta de participación del
  equipo" link in the side panel pointed at the root `team_card.html`
  (`analysis_scripts/team_cards.py`, v1 — only a Matches/Roster tab pair),
  not `v2/team_card.html` (`analysis_scripts/team_cards_v2.py` — adds the
  third "Mapa de participación" tab, backed by
  `analysis_scripts/team_participation_map_v2.py`'s per-club JSON).
  `build_site.py` publishes both under the same site (v1 at the root, v2
  under `/v2/`) with identical `season`/`club`/`team` query params, so the
  fix was just the path, not the params.
- Data is fully converged and clean: 32 stations, 251 links, 68 exits (50
  vanished / 18 left to another club), 1 genuine intra-season transfer.
- **Fullscreen + zoom (built).** `#fsBtn` in the header calls
  `document.documentElement.requestFullscreen()`, falling back to a CSS-only
  `body.fauxfs { position: fixed; inset: 0; z-index: max }` maximize if the
  real Fullscreen API throws (e.g. a host that blocks it) — confirmed
  working as real OS-level fullscreen on the published claude.ai artifact,
  so the fauxfs path is a fallback only, never the common case there.
  First cut kept the legend visible in fullscreen per an explicit initial
  ask, but the legend (5 groups, wraps to multiple rows) ate too much of
  the newly-gained vertical space — revised to collapse it by default on
  entering fullscreen behind a `#legendToggleBtn` ("Mostrar/Ocultar
  leyenda") that only appears while `body.is-fullscreen` is set; header and
  pivot-bar stay put either way. `legend-collapsed` is reset (re-collapsed)
  on every fresh fullscreen entry but left alone across re-renders (pivot
  switches) within the same fullscreen session. Zoom is `−`/`%`/`+` buttons
  (10% steps, 25%–300%,
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
  On a tablet, one-finger pan across the canvas worked from day one (it's
  just `canvas-wrap`'s native `overflow: auto` scroll) but two-finger pinch
  did nothing — there was no pinch handling at all, and fullscreen mode
  disables the browser's own page-level pinch-zoom, so a tablet user had no
  way to zoom in fullscreen. Fixed with `touchstart`/`touchmove`/`touchend`
  listeners on `#canvasWrap` that track two-touch distance and feed the
  ratio into zoom; `touchmove` only calls `preventDefault()` when
  `ev.touches.length === 2`, so one-finger touchmove events fall through
  untouched and native pan keeps working (verified with synthetic
  `TouchEvent`s in Playwright: 2-touch move is cancelled and drives zoom,
  1-touch move is not cancelled and leaves zoom alone).
- **Zoom anchoring.** First cut of pinch always scaled from `transform-origin:
  0 0` (top-left), so pinching over any other part of the diagram visibly
  yanked it toward the corner instead of zooming into the pinched spot —
  same root cause would've hit a future scroll-wheel zoom too, since neither
  is a property of the input device, it's `setZoom()` never taking a point.
  Replaced with `setZoomAt(z, clientX, clientY)`: reads `#canvasWrap`'s
  current `scrollLeft`/`scrollTop`, and after changing `zoomLevel` solves for
  the new scroll offset that keeps the content under `(clientX, clientY)`
  pinned to that same viewport position (`newScroll = (oldScroll + local) *
  (newZoom/oldZoom) - local`). Pinch anchors on the two-touch midpoint,
  recomputed every `touchmove` so a pinch that drifts sideways tracks
  correctly; the `−`/`+`/`%` buttons (no input point to anchor on) anchor on
  the center of whatever's currently visible in `#canvasWrap`, instead of
  jumping to the corner. Verified by computing the expected post-zoom scroll
  offset from the same formula and diffing against the actual one after a
  synthetic pinch (sub-pixel match).
