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
