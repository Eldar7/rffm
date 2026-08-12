"""
Shared visual language + RU/ES bilingual toggle for every page in the
GitHub Pages site (analysis_scripts/build_site.py and friends).

Ported from a one-off Claude.ai artifact ("RFFM 2025-26: страные счета,
доминаторы и аутсайдеры") that this project's earlier, from-scratch
build_site.py reports didn't match — this module is the shared chrome so
every report gets the same masthead/stat-strip/table/panel language and
the same RU (default) / ES language switch instead of each page
reinventing its own CSS and staying English-only.

Usage in a report module:
    from site_theme import FONT_LINKS, CSS, LANG_SWITCH_JS, lang_switch_html

    HTML = f'''<!DOCTYPE html>
    <html lang="ru">
    <head>
    {FONT_LINKS}
    <style>{CSS}</style>
    </head>
    <body>
    <div class="wrap">
      ...
      {lang_switch_html()}
      ...
    </div>
    <script>
    (function () {{
      var I18N_ES = {{...}};
      {LANG_SWITCH_JS}
    }})();
    </script>
    </body>
    </html>
    '''
"""

FONT_LINKS = """<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;700&family=PT+Sans:wght@400;700&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">"""

# Design tokens + component classes, lifted 1:1 from the original artifact
# (masthead, stat-strip, hero-card, table-scroll, split/panel/rowline,
# curio-grid, scope-note, lead-card, lang-switch) so every report reads as
# one site instead of a pile of one-off dashboards.
CSS = """
  :root {
    --bg: #eef1e7;
    --surface: #ffffff;
    --surface-2: #e3e9d9;
    --ink: #182a1c;
    --ink-muted: #56634f;
    --accent: #1f6f3d;
    --accent-ink: #f5fbf1;
    --gold: #93690f;
    --gold-ink: #2a1e05;
    --gold-soft: #f2e5c4;
    --red: #a03327;
    --red-ink: #fff5f2;
    --red-soft: #f5ddd6;
    --line: #cfd6c0;
    --shadow: 0 1px 2px rgba(24,42,28,0.06), 0 8px 24px rgba(24,42,28,0.05);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0c1712; --surface: #12201a; --surface-2: #192a20; --ink: #e8efe2;
      --ink-muted: #9cae95; --accent: #4bb479; --accent-ink: #06150d;
      --gold: #e0ac4c; --gold-ink: #241a06; --gold-soft: #2e2410;
      --red: #e2685a; --red-ink: #200906; --red-soft: #2f1613; --line: #253626;
      --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 12px 30px rgba(0,0,0,0.35);
    }
  }
  :root[data-theme="dark"] {
    --bg: #0c1712; --surface: #12201a; --surface-2: #192a20; --ink: #e8efe2;
    --ink-muted: #9cae95; --accent: #4bb479; --accent-ink: #06150d;
    --gold: #e0ac4c; --gold-ink: #241a06; --gold-soft: #2e2410;
    --red: #e2685a; --red-ink: #200906; --red-soft: #2f1613; --line: #253626;
    --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 12px 30px rgba(0,0,0,0.35);
  }
  :root[data-theme="light"] {
    --bg: #eef1e7; --surface: #ffffff; --surface-2: #e3e9d9; --ink: #182a1c;
    --ink-muted: #56634f; --accent: #1f6f3d; --accent-ink: #f5fbf1;
    --gold: #93690f; --gold-ink: #2a1e05; --gold-soft: #f2e5c4;
    --red: #a03327; --red-ink: #fff5f2; --red-soft: #f5ddd6; --line: #cfd6c0;
    --shadow: 0 1px 2px rgba(24,42,28,0.06), 0 8px 24px rgba(24,42,28,0.05);
  }

  * { box-sizing: border-box; }
  html { background: var(--bg); }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font-family: 'PT Sans', system-ui, sans-serif;
    font-size: 16px; line-height: 1.55; -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 980px; margin: 0 auto; padding: 0 20px 80px; }
  .wrap.wide { max-width: 1280px; }
  /* Full-bleed: for pages whose content is dense multi-panel visualization
     (Sankey/heatmap/timeline side by side) rather than reading-width prose —
     the centered 980/1280px strip starves those of horizontal room. Keeps a
     little breathing margin instead of touching the viewport edge. */
  .wrap.full { max-width: none; padding-left: clamp(16px, 3vw, 40px); padding-right: clamp(16px, 3vw, 40px); }

  h1, h2, h3, .disp {
    font-family: 'Oswald', system-ui, sans-serif;
    font-weight: 700; text-transform: uppercase; letter-spacing: 0.01em;
    text-wrap: balance; margin: 0;
  }

  a { color: inherit; text-decoration: none; border-bottom: 1px solid var(--line);
    transition: border-color .15s ease, color .15s ease; }
  a:hover { border-bottom-color: currentColor; }
  a:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 2px; }
  a.back { font-family: 'JetBrains Mono', monospace; font-size: 12.5px; color: var(--ink-muted);
    border-bottom: none; }
  a.back:hover { color: var(--accent); }

  /* ---------- Masthead ---------- */
  .masthead {
    border-bottom: 3px solid var(--ink);
    padding: 28px 0 16px;
    display: flex; justify-content: space-between; align-items: flex-end;
    gap: 16px; flex-wrap: wrap;
  }
  .masthead .kicker {
    font-family: 'JetBrains Mono', monospace; font-size: 12px; letter-spacing: 0.14em;
    text-transform: uppercase; color: var(--accent); font-weight: 700; margin-bottom: 6px;
  }
  .masthead h1 { font-size: clamp(24px, 4.4vw, 40px); line-height: 1.05; }
  .masthead .scope {
    text-align: right; font-family: 'JetBrains Mono', monospace; font-size: 12.5px;
    color: var(--ink-muted); line-height: 1.7;
  }
  .masthead .scope b { color: var(--ink); font-weight: 700; }
  .scope-block { display: flex; flex-direction: column; align-items: flex-end; gap: 10px; }

  .switch-row { display: flex; gap: 8px; align-items: center; }
  .lang-switch, .theme-switch { display: inline-flex; border: 1px solid var(--line); border-radius: 999px; overflow: hidden; }
  .lang-opt, .theme-opt {
    font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 700;
    letter-spacing: 0.04em; padding: 4px 12px; background: var(--surface);
    color: var(--ink-muted); border: none; cursor: pointer; line-height: 1.4;
  }
  .lang-opt.is-active, .theme-opt.is-active { background: var(--accent); color: var(--accent-ink); }
  .lang-opt:focus-visible, .theme-opt:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .theme-opt { font-size: 13px; padding: 3px 10px; }

  .stat-strip {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px;
    background: var(--line); border: 1px solid var(--line);
    margin: 18px 0 44px; border-radius: 3px; overflow: hidden;
  }
  @media (max-width: 640px) { .stat-strip { grid-template-columns: repeat(2, 1fr); } }
  .stat-strip .cell { background: var(--surface); padding: 14px 16px; }
  .stat-strip .num {
    font-family: 'Oswald', sans-serif; font-weight: 700; font-size: 26px;
    font-variant-numeric: tabular-nums; line-height: 1;
  }
  .stat-strip .lbl { font-size: 12px; color: var(--ink-muted); margin-top: 6px; }

  section { margin: 56px 0; }
  .section-head {
    display: flex; align-items: baseline; gap: 12px; margin-bottom: 18px;
    border-bottom: 1px solid var(--line); padding-bottom: 10px;
  }
  .section-head h2 { font-size: clamp(20px, 3vw, 28px); }
  .section-head .n {
    font-family: 'JetBrains Mono', monospace; color: var(--accent); font-size: 13px; font-weight: 700;
  }
  .lede { color: var(--ink-muted); max-width: 68ch; margin: 0 0 22px; }

  /* ---------- Hero score card ---------- */
  .hero-card {
    background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
    box-shadow: var(--shadow); padding: 28px clamp(16px, 4vw, 40px);
    display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 18px;
  }
  .hero-card .side { min-width: 0; }
  .hero-card .side.away { text-align: right; }
  .hero-card .club {
    font-family: 'Oswald', sans-serif; font-weight: 700; font-size: clamp(15px, 2.6vw, 21px);
    text-transform: uppercase; line-height: 1.1;
  }
  .hero-card .side.home .club { color: var(--accent); }
  .hero-card .side.away .club { color: var(--red); }
  .hero-card .score {
    font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: clamp(40px, 8vw, 68px);
    line-height: 1; text-align: center; font-variant-numeric: tabular-nums;
    white-space: nowrap; padding: 0 10px;
  }
  .hero-card .score .colon { color: var(--ink-muted); padding: 0 4px; }
  .hero-meta {
    grid-column: 1 / -1; display: flex; justify-content: space-between; flex-wrap: wrap;
    gap: 8px; margin-top: 6px; padding-top: 14px; border-top: 1px dashed var(--line);
    font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--ink-muted);
  }

  /* ---------- Ranked table ---------- */
  .table-scroll { overflow-x: auto; border: 1px solid var(--line); border-radius: 6px;
    background: var(--surface); box-shadow: var(--shadow); }
  table { border-collapse: collapse; width: 100%; min-width: 560px; }
  thead th {
    text-align: left; font-family: 'JetBrains Mono', monospace; font-size: 11px;
    letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-muted);
    padding: 10px 12px; border-bottom: 1px solid var(--line); background: var(--surface-2);
    white-space: nowrap;
  }
  tbody td { padding: 10px 12px; border-bottom: 1px solid var(--line); font-size: 14px; vertical-align: middle; }
  tbody tr:last-child td { border-bottom: none; }
  tbody tr:hover { background: var(--surface-2); }
  td.rank { font-family: 'JetBrains Mono', monospace; color: var(--ink-muted); font-size: 13px; width: 32px; }
  td.score {
    font-family: 'JetBrains Mono', monospace; font-weight: 700; font-variant-numeric: tabular-nums;
    white-space: nowrap; text-align: center;
  }
  td.win { color: var(--accent); }
  td.lose { color: var(--red); }
  td.meta { color: var(--ink-muted); font-size: 12.5px; }
  td.num { font-family: 'JetBrains Mono', monospace; font-variant-numeric: tabular-nums;
    text-align: right; white-space: nowrap; }
  .table-cap {
    font-family: 'Oswald', sans-serif; font-weight: 700; text-transform: uppercase; font-size: 12.5px;
    letter-spacing: 0.04em; padding: 10px 12px; background: var(--surface-2);
    border-bottom: 1px solid var(--line); color: var(--ink-muted);
  }

  /* ---------- Dominator / loser split ---------- */
  .split { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  @media (max-width: 720px) { .split { grid-template-columns: 1fr; } }
  .split .table-scroll table { min-width: 0; }
  .panel { border-radius: 6px; border: 1px solid var(--line); background: var(--surface);
    box-shadow: var(--shadow); overflow: hidden; }
  .panel .panel-head {
    padding: 12px 16px; font-family: 'Oswald', sans-serif; font-weight: 700; text-transform: uppercase;
    font-size: 14px; letter-spacing: 0.04em; display: flex; justify-content: space-between; align-items: center;
  }
  .panel.gold .panel-head { background: var(--gold-soft); color: var(--gold-ink); }
  .panel.red .panel-head { background: var(--red-soft); color: var(--red-ink); }
  .panel-head .tag { font-family: 'JetBrains Mono', monospace; font-size: 10.5px; font-weight: 700; opacity: 0.75; }
  .rowline {
    padding: 11px 16px; display: grid; grid-template-columns: 1.7fr auto; gap: 8px;
    align-items: baseline; border-bottom: 1px solid var(--line);
  }
  .rowline:last-child { border-bottom: none; }
  .rowline .name { font-size: 14px; font-weight: 700; line-height: 1.25; }
  .rowline .sub { font-size: 12px; color: var(--ink-muted); }
  .rowline .stat { font-family: 'JetBrains Mono', monospace; font-size: 13.5px;
    font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
  .panel.gold .rowline .stat { color: var(--accent); font-weight: 700; }
  .panel.red .rowline .stat { color: var(--red); font-weight: 700; }

  /* ---------- Curiosities ---------- */
  .curio-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
  @media (max-width: 720px) { .curio-grid { grid-template-columns: 1fr; } }
  .curio { background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
    box-shadow: var(--shadow); padding: 18px 20px; }
  .curio h3 { font-size: 15px; color: var(--accent); margin-bottom: 8px; }
  .curio p { margin: 0; font-size: 14px; color: var(--ink); }
  .curio p + p { margin-top: 8px; }
  .curio .figure { font-family: 'JetBrains Mono', monospace; font-weight: 700; font-variant-numeric: tabular-nums; }
  .curio .team-a { color: var(--accent); font-weight: 700; }
  .curio .team-b { color: var(--red); font-weight: 700; }

  .scope-note {
    display: flex; gap: 12px; align-items: flex-start; background: var(--surface-2);
    border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 4px;
    padding: 12px 16px; margin: 0 0 22px; font-size: 13.5px; color: var(--ink-muted);
  }
  .scope-note b { color: var(--ink); }
  .scope-note .mark { font-family: 'JetBrains Mono', monospace; font-weight: 700; color: var(--accent); flex: none; }

  .lead-card {
    background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
    box-shadow: var(--shadow); padding: 22px clamp(16px, 4vw, 32px);
    display: grid; grid-template-columns: auto 1fr; gap: 20px; align-items: center; margin-bottom: 16px;
  }
  @media (max-width: 560px) { .lead-card { grid-template-columns: 1fr; } }
  .lead-card .big-num {
    font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: clamp(38px, 7vw, 60px);
    line-height: 1; color: var(--accent); font-variant-numeric: tabular-nums;
  }
  .lead-card .desc .name { font-family: 'Oswald', sans-serif; font-weight: 700; font-size: 17px; text-transform: uppercase; }
  .lead-card .desc .sub { color: var(--ink-muted); font-size: 13.5px; margin-top: 4px; }

  /* ---------- Landing-page cards ---------- */
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px; }
  .card {
    background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
    box-shadow: var(--shadow); padding: 18px 20px; display: flex; flex-direction: column; gap: 8px;
  }
  .card:hover { border-color: var(--accent); }
  .card .title { font-family: 'Oswald', sans-serif; font-weight: 700; text-transform: uppercase; font-size: 16px; }
  .card .desc { font-size: 13.5px; color: var(--ink-muted); }
  .status-ok { color: var(--accent); font-weight: 700; }
  .status-warn { color: var(--gold); font-weight: 700; }

  footer {
    margin-top: 64px; padding-top: 18px; border-top: 1px solid var(--line);
    font-size: 12.5px; color: var(--ink-muted); font-family: 'JetBrains Mono', monospace; line-height: 1.7;
  }
"""

# Excel-style column sort + autofilter for any <table class="dtable"> with
# data-key/data-type on its <th>s and matching data-col/data-v/data-label
# on its <td>s. Self-contained (no deps), reusable across report pages —
# see rffmInitDataTable()'s docstring-equivalent comment in DATATABLE_JS for
# the markup contract. Token names (--line-strong, --ink-faint) fall back to
# this module's base tokens (--line, --ink-muted) for pages that don't
# define the finer-grained set team_cards.py's own <style> block uses.
DATATABLE_CSS = """
  table.dtable thead th[data-key] { position: relative; padding-right: 1.7rem; cursor: pointer; user-select: none; }
  table.dtable thead th[data-key]:hover { color: var(--accent); }
  table.dtable thead th[data-key] .dt-sort-ic {
    display: inline-block; margin-left: 0.3rem; font-size: 0.62rem; color: var(--accent); min-width: 0.6em;
  }
  table.dtable thead th[data-key] .dt-btn {
    position: absolute; right: 0.15rem; top: 50%; transform: translateY(-50%);
    width: 1.15rem; height: 1.15rem; border: none; background: transparent; cursor: pointer;
    color: var(--ink-faint, var(--ink-muted)); font-size: 0.62rem; border-radius: 3px; line-height: 1;
    display: inline-flex; align-items: center; justify-content: center; padding: 0;
  }
  table.dtable thead th[data-key] .dt-btn:hover { background: var(--accent-soft, var(--surface-2)); color: var(--accent); }
  table.dtable thead th[data-key] .dt-btn::after { content: "\\25BE"; }
  table.dtable thead th[data-key].dt-filtered .dt-btn { color: var(--accent); font-weight: 700; }
  .dt-pop {
    position: fixed; z-index: 1000; background: var(--surface);
    border: 1px solid var(--line-strong, var(--line)); border-radius: 8px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.28); padding: 0.55rem; width: 15.5rem;
    font-size: 0.8rem; color: var(--ink); display: none; font-family: inherit;
  }
  .dt-pop.open { display: block; }
  .dt-pop .dt-sortrow { display: flex; gap: 0.3rem; margin-bottom: 0.4rem; }
  .dt-pop .dt-sortrow button {
    flex: 1; font-family: inherit; font-size: 0.72rem; padding: 0.3rem 0.3rem; border-radius: 5px;
    border: 1px solid var(--line-strong, var(--line)); background: var(--surface); color: var(--ink); cursor: pointer;
  }
  .dt-pop .dt-sortrow button:hover { border-color: var(--accent); color: var(--accent); }
  .dt-pop input[type="search"] {
    width: 100%; box-sizing: border-box; padding: 0.3rem 0.5rem; margin-bottom: 0.4rem; border-radius: 5px;
    border: 1px solid var(--line-strong, var(--line)); background: var(--bg); color: var(--ink);
    font-family: inherit; font-size: 0.78rem;
  }
  .dt-pop .dt-list {
    max-height: 12rem; overflow: auto; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line);
    padding: 0.3rem 0; margin-bottom: 0.4rem;
  }
  .dt-pop .dt-item { display: flex; align-items: center; gap: 0.4rem; padding: 0.15rem 0.1rem; cursor: pointer; }
  .dt-pop .dt-item input { margin: 0; flex: none; }
  .dt-pop .dt-item span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dt-pop .dt-actions { display: flex; justify-content: space-between; gap: 0.4rem; }
  .dt-pop .dt-actions button {
    font-family: inherit; font-size: 0.74rem; padding: 0.3rem 0.6rem; border-radius: 5px; cursor: pointer;
    border: 1px solid var(--line-strong, var(--line)); background: var(--surface); color: var(--ink);
  }
  .dt-pop .dt-actions button.dt-apply { background: var(--accent); border-color: var(--accent); color: var(--accent-ink, #fff); }
  .dt-count { font-family: 'JetBrains Mono', monospace; color: var(--accent); font-size: 0.78rem; font-weight: 700; }
"""

# rffmInitDataTable(table, opts) turns any <table class="dtable"> into an
# Excel-style grid: click anywhere on a header to cycle its sort state —
# unsorted -> ascending -> descending -> unsorted, a small ▲/▼ appears next
# to the label while it's the active sort column (single-column sort; a
# click on a different header replaces it, doesn't add a second key) —
# separately, click the little ▾ button for a popover with a searchable
# checkbox list of that column's distinct values (an autofilter, not just a
# free-text filter — matches what "как в Excel" actually means). Markup
# contract:
#   <table class="dtable"><thead><tr>
#     <th data-key="goals" data-type="number"><span>Голы</span></th>
#   </tr></thead><tbody>
#     <tr><td data-col="goals" data-v="3">3</td></tr>
#   </tbody></table>
# data-type is "number" (parseFloat + numeric compare, NaN sorts last) or
# "text" (locale compare). data-v is the sort/filter value; falls back to
# the cell's textContent when absent. data-label overrides the text shown
# in the filter checkbox list (defaults to data-v/textContent too) — use it
# when a column's filter should group by something coarser than its literal
# display text (e.g. grouping a "3:2" score cell's checkbox under "Win").
# The header text must live in a child element (e.g. a <span data-i18n=...>)
# rather than directly in the <th>, otherwise this project's language
# switcher (LANG_SWITCH_JS, which does el.innerHTML = ... on [data-i18n]
# elements) will wipe out the appended sort icon/▾ button on every RU/ES
# toggle. Re-calling this on the same <table> (e.g. after re-rendering its
# rows) safely tears down the previous instance first via table._rffmDt.destroy().
DATATABLE_JS = r"""
function rffmInitDataTable(table, opts) {
  if (!table) return null;
  if (table._rffmDt) table._rffmDt.destroy();
  opts = opts || {};
  var labels = Object.assign({
    selectAll: '(все)', search: '...', apply: 'OK', clear: '✕', empty: '(пусто)'
  }, opts.labels || {});
  var thead = table.tHead, tbody = table.tBodies[0];
  if (!thead || !tbody) return null;
  var ths = Array.prototype.slice.call(thead.querySelectorAll('th[data-key]'));
  var state = { sortKey: null, sortDir: 1, filters: {} };
  // Captured once, before any sort/filter runs, so the third click-cycle
  // state ("unsorted") restores this render's original row order instead
  // of just freezing wherever the last active sort left it.
  var originalOrder = Array.prototype.slice.call(tbody.rows);
  var pop = document.createElement('div');
  pop.className = 'dt-pop';
  document.body.appendChild(pop);
  var openKey = null;

  function colCell(tr, key) { return tr.querySelector('[data-col="' + key + '"]'); }
  function cellVal(tr, key) {
    var td = colCell(tr, key);
    if (!td) return '';
    var v = td.getAttribute('data-v');
    return v === null ? td.textContent.trim() : v;
  }
  function cellLabel(tr, key) {
    var td = colCell(tr, key);
    if (!td) return '';
    var l = td.getAttribute('data-label');
    return l !== null ? l : cellVal(tr, key);
  }
  function rows() { return Array.prototype.slice.call(tbody.rows); }
  function closePop() { pop.classList.remove('open'); openKey = null; }

  function distinct(key) {
    var map = new Map();
    rows().forEach(function (tr) {
      var v = cellVal(tr, key), l = cellLabel(tr, key);
      if (!map.has(v)) map.set(v, l);
    });
    return map;
  }

  function apply() {
    var rs = rows();
    rs.forEach(function (tr) {
      var visible = true;
      for (var key in state.filters) {
        var allowed = state.filters[key];
        if (!allowed) continue;
        if (!allowed.has(cellVal(tr, key))) { visible = false; break; }
      }
      tr.style.display = visible ? '' : 'none';
    });
    if (state.sortKey) {
      var th = ths.filter(function (t) { return t.dataset.key === state.sortKey; })[0];
      var type = th ? th.dataset.type : 'text';
      rs.sort(function (a, b) {
        var av = cellVal(a, state.sortKey), bv = cellVal(b, state.sortKey), cmp;
        if (type === 'number') {
          var an = parseFloat(av), bn = parseFloat(bv);
          var aNaN = isNaN(an), bNaN = isNaN(bn);
          cmp = (aNaN && bNaN) ? 0 : aNaN ? 1 : bNaN ? -1 : (an - bn);
        } else {
          cmp = String(av).localeCompare(String(bv), 'ru');
        }
        return cmp * state.sortDir;
      });
      rs.forEach(function (tr) { tbody.appendChild(tr); });
    } else {
      originalOrder.forEach(function (tr) { tbody.appendChild(tr); });
    }
    ths.forEach(function (th) {
      var key = th.dataset.key;
      var ic = th.querySelector('.dt-sort-ic');
      if (ic) ic.textContent = state.sortKey === key ? (state.sortDir === 1 ? '▲' : '▼') : '';
      th.classList.toggle('dt-sorted-asc', state.sortKey === key && state.sortDir === 1);
      th.classList.toggle('dt-sorted-desc', state.sortKey === key && state.sortDir === -1);
      th.classList.toggle('dt-filtered', !!state.filters[key]);
    });
    if (opts.onChange) {
      var visible = rs.filter(function (tr) { return tr.style.display !== 'none'; }).length;
      opts.onChange(visible, rs.length);
    }
  }

  function openPopover(th) {
    var key = th.dataset.key, type = th.dataset.type || 'text';
    openKey = key;
    var values = distinct(key);
    var entries = Array.from(values.entries());
    entries.sort(function (a, b) {
      if (type === 'number') return parseFloat(a[0]) - parseFloat(b[0]);
      return String(a[1]).localeCompare(String(b[1]), 'ru');
    });
    var active = state.filters[key];
    var html = '<input type="search" placeholder="' + labels.search + '">'
      + '<div class="dt-list">'
      + '<label class="dt-item"><input type="checkbox" data-all checked><span><b>' + labels.selectAll + '</b></span></label>'
      + entries.map(function (e) {
          var checked = !active || active.has(e[0]);
          var label = e[1] === '' ? labels.empty : e[1];
          return '<label class="dt-item" data-val="' + String(e[0]).replace(/"/g, '&quot;') + '">'
            + '<input type="checkbox" ' + (checked ? 'checked' : '') + '><span>' + label + '</span></label>';
        }).join('')
      + '</div>'
      + '<div class="dt-actions"><button type="button" data-act="clear">' + labels.clear + '</button>'
      + '<button type="button" class="dt-apply" data-act="apply">' + labels.apply + '</button></div>';
    pop.innerHTML = html;
    var r = th.getBoundingClientRect();
    pop.style.left = Math.max(4, Math.min(r.left, window.innerWidth - 260)) + 'px';
    pop.style.top = (r.bottom + 4) + 'px';
    pop.classList.add('open');

    pop.querySelector('input[type="search"]').addEventListener('input', function (e) {
      var q = e.target.value.toLowerCase();
      pop.querySelectorAll('.dt-list .dt-item[data-val]').forEach(function (el) {
        el.style.display = el.textContent.toLowerCase().indexOf(q) === -1 ? 'none' : '';
      });
    });
    pop.querySelector('[data-all]').addEventListener('change', function (e) {
      pop.querySelectorAll('.dt-list .dt-item[data-val] input').forEach(function (cb) { cb.checked = e.target.checked; });
    });
    pop.querySelector('[data-act="clear"]').addEventListener('click', function () {
      delete state.filters[key]; apply(); closePop();
    });
    pop.querySelector('[data-act="apply"]').addEventListener('click', function () {
      var checked = new Set(); var anyUnchecked = false;
      pop.querySelectorAll('.dt-list .dt-item[data-val]').forEach(function (el) {
        var cb = el.querySelector('input');
        if (cb.checked) checked.add(el.getAttribute('data-val')); else anyUnchecked = true;
      });
      state.filters[key] = anyUnchecked ? checked : null;
      apply(); closePop();
    });
  }

  var cleanups = [];
  ths.forEach(function (th) {
    var ic = document.createElement('span');
    ic.className = 'dt-sort-ic';
    th.appendChild(ic);

    var btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'dt-btn';
    var onFilterClick = function (e) {
      e.stopPropagation();
      if (openKey === th.dataset.key) closePop(); else openPopover(th);
    };
    btn.addEventListener('click', onFilterClick);
    th.appendChild(btn);

    // Whole header is the sort trigger (three states: unsorted -> asc ->
    // desc -> unsorted) — the filter button's own listener stops
    // propagation so this never double-fires on a ▾ click.
    var onHeaderClick = function () {
      var key = th.dataset.key;
      if (state.sortKey !== key) { state.sortKey = key; state.sortDir = 1; }
      else if (state.sortDir === 1) { state.sortDir = -1; }
      else { state.sortKey = null; }
      apply();
    };
    th.addEventListener('click', onHeaderClick);

    cleanups.push(function () {
      th.removeEventListener('click', onHeaderClick);
      btn.removeEventListener('click', onFilterClick);
      btn.remove();
      ic.remove();
    });
  });

  function onDocClick(e) { if (openKey && !pop.contains(e.target)) closePop(); }
  function onScroll() { if (openKey) closePop(); }
  document.addEventListener('click', onDocClick);
  window.addEventListener('scroll', onScroll, true);

  apply();

  var instance = {
    refresh: apply,
    destroy: function () {
      document.removeEventListener('click', onDocClick);
      window.removeEventListener('scroll', onScroll, true);
      cleanups.forEach(function (fn) { fn(); });
      pop.remove();
    }
  };
  table._rffmDt = instance;
  return instance;
}
"""


def club_slug_map(club_names: list[str]) -> dict[str, str]:
    """Deterministic club_name_raw -> URL-safe slug, stable across scripts
    that need to agree on the same file name for the same club without
    sharing any other state (club_division_map.py picks the slug a team-card
    link points at; team_cards.py picks the slug it writes the file under).
    Input order doesn't matter — collisions are broken by sorting the
    colliding names themselves, not by iteration order."""
    import re
    import unicodedata

    def base_slug(name: str) -> str:
        s = unicodedata.normalize("NFKD", name)
        s = "".join(c for c in s if not unicodedata.combining(c))
        s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
        return s or "club"

    by_base: dict[str, list[str]] = {}
    for name in club_names:
        by_base.setdefault(base_slug(name), []).append(name)

    out: dict[str, str] = {}
    for base, names in by_base.items():
        if len(names) == 1:
            out[names[0]] = base
        else:
            for i, name in enumerate(sorted(set(names)), start=1):
                out[name] = base if i == 1 else f"{base}-{i}"
    return out


def lang_switch_html(active: str = "ru") -> str:
    """The RU/ES toggle buttons; drop into the masthead's .scope-block."""
    ru_active = "is-active" if active == "ru" else ""
    es_active = "is-active" if active == "es" else ""
    return (
        '<div class="lang-switch" role="group" aria-label="Language / Idioma">'
        f'<button type="button" class="lang-opt {ru_active}" data-lang-btn="ru">RU</button>'
        f'<button type="button" class="lang-opt {es_active}" data-lang-btn="es">ES</button>'
        "</div>"
    )


def theme_switch_html() -> str:
    """Light/dark toggle buttons; drop next to lang_switch_html() output."""
    return (
        '<div class="theme-switch" role="group" aria-label="Theme / Tema">'
        '<button type="button" class="theme-opt" data-theme-btn="light" title="Light / Claro">&#9728;</button>'
        '<button type="button" class="theme-opt" data-theme-btn="dark" title="Dark / Oscuro">&#9790;</button>'
        "</div>"
    )


def switch_row_html(active_lang: str = "ru") -> str:
    """lang_switch_html() + theme_switch_html() side by side in one row."""
    return f'<div class="switch-row">{lang_switch_html(active_lang)}{theme_switch_html()}</div>'


# Drop-in JS that wires up [data-i18n] spans against an `I18N_ES` dict
# (RU text is read from the DOM itself, matching the artifact's approach —
# no separate RU dict needed since the markup already *is* Russian).
LANG_SWITCH_JS = r"""
  var root = document.documentElement;
  function apply(lang) {
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      if (el.dataset.ru === undefined) el.dataset.ru = el.innerHTML;
      if (lang === 'ru') {
        el.innerHTML = el.dataset.ru;
      } else if (Object.prototype.hasOwnProperty.call(I18N_ES, el.dataset.i18n)) {
        el.innerHTML = I18N_ES[el.dataset.i18n];
      }
    });
    document.documentElement.lang = lang;
    document.querySelectorAll('.lang-opt').forEach(function (btn) {
      var active = btn.getAttribute('data-lang-btn') === lang;
      btn.classList.toggle('is-active', active);
    });
    try { localStorage.setItem('rffm_lang', lang); } catch (e) {}
  }
  document.querySelectorAll('.lang-opt').forEach(function (btn) {
    btn.addEventListener('click', function () { apply(btn.getAttribute('data-lang-btn')); });
  });
  var saved = null;
  try { saved = localStorage.getItem('rffm_lang'); } catch (e) {}
  if (saved === 'es') apply('es');
"""

# Placed early in <head> (right after FONT_LINKS) so the saved theme applies
# before first paint — avoids a flash of the wrong theme on load.
THEME_INIT_JS = r"""<script>
(function () {
  try {
    var t = localStorage.getItem('rffm_theme');
    if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t;
  } catch (e) {}
})();
</script>"""

# Button wiring; drop anywhere after theme_switch_html()'s markup exists in the DOM.
THEME_SWITCH_JS = r"""
  function rffmApplyTheme(theme) {
    if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    document.querySelectorAll('.theme-opt').forEach(function (btn) {
      btn.classList.toggle('is-active', btn.getAttribute('data-theme-btn') === theme);
    });
    try { localStorage.setItem('rffm_theme', theme); } catch (e) {}
  }
  document.querySelectorAll('.theme-opt').forEach(function (btn) {
    btn.addEventListener('click', function () { rffmApplyTheme(btn.getAttribute('data-theme-btn')); });
  });
  (function () {
    var saved = null;
    try { saved = localStorage.getItem('rffm_theme'); } catch (e) {}
    var current = saved || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    document.querySelectorAll('.theme-opt').forEach(function (btn) {
      btn.classList.toggle('is-active', btn.getAttribute('data-theme-btn') === current);
    });
  })();
"""
