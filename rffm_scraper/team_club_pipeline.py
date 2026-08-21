"""Enrichment pipeline: complete team_id -> club_id resolution ->
output/processed/rffm/team_club_map.csv.

Same source page as club_pipeline.py (/fichaequipo/<team_id>, codigo_club),
but a different target-selection strategy that fixes club_pipeline.py's
actual coverage gap: that pipeline fetches only ONE representative team_id
per unique club_name_raw in the current season's teams.csv, reasoning that
codigo_club is identical for every team of a club. That reasoning is
correct, but the representative picked by club_name_raw grouping is not
reliable - club_name_raw drifts in spelling/formatting between teams of the
same club (confirmed live: "A.D. ARGANDA CLUB DE FUTBOL 'B'" vs the
already-resolved "A.D. ARGANDA C.F." are the same club, codigo_club=1363,
but grouped as different clubs by name), so most of the coverage gap is not
"RFFM has no data for this club" but "the representative sample never
picked a team that happened to resolve". This stage targets EVERY
not-yet-resolved team_id instead - no *fuzzy* name-matching involved
anywhere (see the seeding layers below for the one, deliberately narrow,
exact-string exception).

Deliberately a separate stage from club_pipeline.py, not a patch to it -
see PR discussion. club_pipeline.py's clubs.csv (one row per club_id, club
identity/address fields) keeps its existing shape/consumers untouched;
this stage answers a different, narrower question ("given this exact
team_id, what is its club_id") that clubs.csv was never able to answer
completely by construction.

Cross-season by design, unlike clubs.csv: team_id is a stable identity
across seasons (confirmed live - the same team_id recurs across multiple
seasons' teams.csv), so a team_id resolved while processing one season's
target list must never be re-fetched while processing another season's -
that would be wasteful, impolite re-crawling of a robots.txt-disallowed
page for a question already answered. Consequently, unlike clubs.csv/
clubs_crawl_log.csv (season-scoped files), team_club_map.csv and
team_clubs_crawl_log.csv both live once at the processed root (like
club_teams.csv/club_profiles_crawl_log.csv), shared across every season's
run of this stage. Only team_clubs_data_quality_report.csv and the
coverage_manifest.csv row stay season-scoped, since "did season S's own
team_ids get resolved" is a meaningful season-scoped question even though
the underlying fetch history isn't.

Free seeding before any live fetch, three layers, all in
_seed_known_mappings: (1) club_teams.csv (the /fichaclub/ roster already
lists every team_id under its club_id), (2) every season's own clubs.csv
(representative_team_id -> club_id), (3) exact_name_match - a team_id whose
club_name_raw is byte-for-byte identical to another, already-resolved
team_id's club_name_raw (by layer 1, 2, or a prior run's live fetch) is
assigned that same club_id. Layer 3 is still not the fuzzy club_name_raw
matching this stage otherwise avoids everywhere else - it's the same
"codigo_club is confirmed identical across every team of a club" reasoning
clubs.csv already relies on, just requiring an exact string match rather
than eyeballing a near-miss. All three run every invocation (idempotent -
only ever adds team_ids not already present), so the live-fetch gap keeps
shrinking on its own over time - both as club_teams.csv grows from later
club_profiles runs, and as newly-resolved team_ids unlock their own
exact-name siblings - without this stage doing anything extra.

team_club_map.csv is NOT an append-only snapshot log like clubs_extended/
club_teams - a team_id's club_id is a permanent fact once resolved (RFFM
never reassigns a team_id to a different club), so it's one row per
team_id, not a history.

Same resumability/progress/batched-flush/coverage-manifest design as every
other pipeline in this codebase - see acta_pipeline.py's module docstring
for the full "already done" rationale (crawl-log-based, union with
primary-table presence).
"""
from __future__ import annotations

import dataclasses
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd

from rffm_scraper.config import Settings
from rffm_scraper.fetchers import extract_next_data, fetch_fichaequipo
from rffm_scraper.http_client import RffmClient
from rffm_scraper.models import CrawlLogEntry, TeamClubMapping
from rffm_scraper.team_club_parsers import parse_team_club_mapping
from rffm_scraper.row_io import (
    Progress,
    already_done_ids,
    append_or_write_csv,
    atomic_write_text,
    upsert_coverage_manifest,
    validate_rows,
    write_csv,
)
from rffm_scraper.team_club_quality_checks import run_team_club_quality_checks

logger = logging.getLogger("rffm_scraper.team_club_pipeline")

_MAP_COLUMNS = ["team_id", "club_id", "source", "source_url", "scraped_at"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_known_club_teams(processed_root) -> pd.DataFrame:
    """team_id -> club_id already known from club_teams.csv (the /fichaclub/
    roster, enrich_club_profiles.py) - no live fetch needed for these."""
    path = processed_root / "club_teams.csv"
    if not path.exists():
        return pd.DataFrame(columns=_MAP_COLUMNS)
    df = pd.read_csv(path, dtype=str, keep_default_na=True)
    if df.empty:
        return pd.DataFrame(columns=_MAP_COLUMNS)
    out = df[["team_id", "club_id", "source_url", "scraped_at"]].copy()
    out["source"] = "fichaclub_roster"
    return out[_MAP_COLUMNS]


def _load_known_clubs_representatives(processed_root) -> pd.DataFrame:
    """team_id -> club_id already known from every season's clubs.csv
    (representative_team_id, club_pipeline.py) - no live fetch needed."""
    frames = []
    for path in sorted(processed_root.glob("*/clubs.csv")):
        df = pd.read_csv(path, dtype=str, keep_default_na=True)
        if df.empty:
            continue
        out = df.rename(columns={"representative_team_id": "team_id"})
        out = out[["team_id", "club_id", "source_url", "scraped_at"]].copy()
        out["source"] = "clubs_representative"
        frames.append(out)
    if not frames:
        return pd.DataFrame(columns=_MAP_COLUMNS)
    return pd.concat(frames, ignore_index=True)[_MAP_COLUMNS]


def _load_all_teams_name_map(processed_root) -> pd.DataFrame:
    """Every (team_id, club_name_raw) pair across every season's teams.csv -
    cross-season, since exact_name_match needs to see the whole
    club_name_raw universe, not just one season's."""
    frames = []
    for path in sorted(processed_root.glob("*/teams.csv")):
        df = pd.read_csv(path, usecols=["team_id", "club_name_raw"], dtype=str, keep_default_na=True)
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["team_id", "club_name_raw"])
    return pd.concat(frames, ignore_index=True).dropna(subset=["team_id", "club_name_raw"]).drop_duplicates()


# club_name_raw values that are RFFM's own generic placeholder labels, not
# a real club identity - "Equipo Casa/Fuera (No asignado)" is reused
# verbatim as a bye/no-show stand-in across ~700-800 *different*,
# unrelated team_id slots in different groups, and "Finalista N F-7/F-11"
# is a bracket-TBD placeholder likewise reused across different brackets.
# Matching on either would propagate one team_id's real (or later-reused,
# per the club_pipeline.py module docstring's team_id-reuse finding)
# club_id to every other placeholder sharing the same generic text - a
# real false-positive caught live (all 606-798 "No asignado" team_ids
# collapsed onto the one club_id that team_id 17145319 happened to become
# in a later season - see DATA_FINDINGS.md). Excluded from
# exact_name_match entirely; still correctly left unresolved.
_NON_CLUB_NAME_PATTERN = r"No asignado|^Finalista\s"


def _load_exact_name_match_candidates(processed_root, resolved: pd.DataFrame) -> pd.DataFrame:
    """team_id -> club_id for team_ids not yet resolved, whose club_name_raw
    exactly matches another team_id's club_name_raw that IS already
    resolved (any source, including this same run's own direct-source
    candidates - see caller). No name-matching heuristics beyond exact
    string equality - this is the same reasoning already used to dedupe
    clubs.csv by club_id (codigo_club confirmed identical across every team
    of a club), just applied in the team_id -> club_id direction instead.
    club_name_raw values matching _NON_CLUB_NAME_PATTERN are excluded
    first - see that constant's comment for why exact-string equality
    alone isn't safe for those.

    A club_name_raw group with more than one distinct club_id among its
    resolved members is a genuine collision (should not happen given that
    reasoning) - skipped and logged, never guessed at.
    """
    name_map = _load_all_teams_name_map(processed_root)
    if name_map.empty or resolved.empty:
        return pd.DataFrame(columns=_MAP_COLUMNS)
    name_map = name_map[~name_map["club_name_raw"].str.contains(_NON_CLUB_NAME_PATTERN, case=False, regex=True)]

    named = name_map.merge(
        resolved[["team_id", "club_id", "source_url", "scraped_at"]], on="team_id", how="left",
    )

    rows: list[dict] = []
    for club_name_raw, group in named.groupby("club_name_raw"):
        resolved_rows = group.dropna(subset=["club_id"])
        if resolved_rows.empty:
            continue
        distinct_clubs = resolved_rows["club_id"].unique()
        if len(distinct_clubs) != 1:
            logger.warning(
                "team_clubs: exact_name_match skipping club_name_raw=%r - %d distinct club_ids "
                "among resolved siblings (%s), refusing to guess",
                club_name_raw, len(distinct_clubs), list(distinct_clubs),
            )
            continue
        rep = resolved_rows.iloc[0]
        for team_id in group.loc[group["club_id"].isna(), "team_id"]:
            rows.append(dict(
                team_id=team_id, club_id=rep["club_id"], source="exact_name_match",
                source_url=rep["source_url"], scraped_at=rep["scraped_at"],
            ))
    return pd.DataFrame(rows, columns=_MAP_COLUMNS) if rows else pd.DataFrame(columns=_MAP_COLUMNS)


def _seed_known_mappings(settings: Settings) -> int:
    """Idempotent: adds any team_id -> club_id mapping already derivable for
    free - no live fetch - to team_club_map.csv, skipping team_ids already
    present. Two layers: club_teams.csv/clubs.csv direct copies, then
    exact_name_match propagation over the result of that first layer (so a
    club newly seeded this run immediately unlocks its exact-name siblings
    too, in the same pass). Returns the number of rows added."""
    processed_root = settings.processed_root
    map_path = processed_root / "team_club_map.csv"
    existing_df = pd.DataFrame(columns=_MAP_COLUMNS)
    if map_path.exists():
        existing_df = pd.read_csv(map_path, dtype=str, keep_default_na=True)
    existing_ids: set[str] = set(existing_df["team_id"].dropna())

    direct_candidates = pd.concat(
        [_load_known_club_teams(processed_root), _load_known_clubs_representatives(processed_root)],
        ignore_index=True,
    )
    direct_candidates = direct_candidates.dropna(subset=["team_id", "club_id"])
    direct_candidates = direct_candidates[~direct_candidates["team_id"].isin(existing_ids)]
    direct_candidates = direct_candidates.drop_duplicates(subset="team_id", keep="first")

    resolved_so_far = pd.concat(
        [existing_df[["team_id", "club_id", "source_url", "scraped_at"]], direct_candidates],
        ignore_index=True,
    ).drop_duplicates(subset="team_id", keep="first")
    name_match_candidates = _load_exact_name_match_candidates(processed_root, resolved_so_far)

    candidates = pd.concat([direct_candidates, name_match_candidates], ignore_index=True)
    candidates = candidates.dropna(subset=["team_id", "club_id"])
    candidates = candidates[~candidates["team_id"].isin(existing_ids)]
    candidates = candidates.drop_duplicates(subset="team_id", keep="first")
    if candidates.empty:
        return 0

    rows = validate_rows(TeamClubMapping, candidates.to_dict("records"), "team_club_mapping")
    if not rows:
        return 0
    append_or_write_csv(pd.DataFrame(rows), map_path)
    return len(rows)


def _load_season_team_ids(settings: Settings) -> list[str]:
    teams_path = settings.processed_dir / "teams.csv"
    df = pd.read_csv(teams_path, dtype=str, keep_default_na=True)
    return sorted(df["team_id"].dropna().unique().tolist())


def _resolved_team_ids(processed_root) -> set[str]:
    path = processed_root / "team_club_map.csv"
    if not path.exists():
        return set()
    return set(pd.read_csv(path, usecols=["team_id"], dtype=str)["team_id"].dropna())


def _raw_path(settings: Settings, team_id: str):
    # No season subdirectory, unlike club_pipeline.py's _raw_path - team_id
    # is season-independent, so one shared cache entry per team_id is
    # correct regardless of which season's run happens to fetch it first.
    return settings.raw_dir / "fichaequipo" / f"{team_id}.html"


def _progress_path(settings: Settings, season_label: str):
    return settings.discovery_dir / f"team_clubs_progress_{season_label}.json"


def _reread_table(processed_root, filename: str) -> pd.DataFrame:
    path = processed_root / filename
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype={"team_id": str, "club_id": str}, keep_default_na=True)


def _flush_batch(processed_root, rows: list[dict], crawl_log_rows: list[dict]) -> None:
    if rows:
        df = pd.DataFrame(validate_rows(TeamClubMapping, rows, "team_club_mapping"))
        append_or_write_csv(df, processed_root / "team_club_map.csv")
        rows.clear()
    if crawl_log_rows:
        log_df = pd.DataFrame(validate_rows(CrawlLogEntry, crawl_log_rows, "team_clubs_crawl_log"))
        append_or_write_csv(log_df, processed_root / "team_clubs_crawl_log.csv")
        crawl_log_rows.clear()


def _fetch_one_team_club(
    team_id: str,
    settings: Settings,
    team_clubs_settings: Settings,
    local: threading.local,
    run_id: str,
    force_refetch: bool,
) -> tuple[str, dict, dict | None, float]:
    """Fetch and parse one /fichaequipo/ page for its codigo_club. Runs in a
    worker thread. Returns (team_id, log_entry_dict, mapping_row_or_None,
    fetch_seconds)."""
    if not hasattr(local, "client"):
        local.client = RffmClient(team_clubs_settings, run_id=run_id)
    client = local.client

    raw_path = _raw_path(settings, team_id)
    source_url = f"{settings.site.base_url}{settings.site.pages.fichaequipo}/{team_id}"

    team_json = None
    cache_hit = False
    fetch_seconds = 0.0

    if raw_path.exists() and not force_refetch:
        cached_html = raw_path.read_text(encoding="utf-8")
        page_props = extract_next_data(cached_html)
        team_json = (page_props or {}).get("team")
        if team_json is not None:
            cache_hit = True
        else:
            logger.warning("Cached fichaequipo file unparseable, will refetch: %s", raw_path)

    if team_json is None:
        fetch_started = time.monotonic()
        result = fetch_fichaequipo(client, team_clubs_settings, team_id)
        if result.ok and result.raw_html:
            atomic_write_text(raw_path, result.raw_html)
            team_json = (result.page_props or {}).get("team")
            fetch_seconds = time.monotonic() - fetch_started
        log_entry = dataclasses.asdict(client.crawl_log[-1])
    elif cache_hit:
        log_entry = dict(
            run_id=run_id, timestamp=_now_iso(), stage="team_clubs",
            entity_type="team_ficha", entity_id=team_id, source_url=source_url,
            http_status=None, success=True, retry_count=0,
            parser_type="html_next_data_cached", raw_saved_path=str(raw_path),
            message="served_from_raw_cache",
        )

    mapping_row = None
    if team_json is not None:
        mapping_row = parse_team_club_mapping(team_json, team_id, source_url)

    return team_id, log_entry, mapping_row, fetch_seconds


def run_team_club_enrichment(
    settings: Settings,
    force_refetch: bool | None = None,
    workers: int | None = None,
) -> dict:
    if not settings.enrichment.fetch_fichaequipo:
        raise RuntimeError(
            "enrichment.fetch_fichaequipo is false in config - refusing to crawl "
            "/fichaequipo/ (robots.txt-disallowed) without an explicit opt-in."
        )

    cfg = settings.enrichment.team_clubs
    force_refetch = cfg.force_refetch if force_refetch is None else force_refetch
    workers = cfg.workers if workers is None else workers
    season_label = settings.target.season_label

    team_clubs_settings = dataclasses.replace(
        settings,
        network=dataclasses.replace(settings.network, rate_limit_seconds=cfg.rate_limit_seconds),
    )
    client = RffmClient(team_clubs_settings)

    processed = settings.processed_dir
    processed_root = settings.processed_root
    processed.mkdir(parents=True, exist_ok=True)
    processed_root.mkdir(parents=True, exist_ok=True)

    matches_df = pd.read_csv(processed / "matches.csv", dtype=str, keep_default_na=True)
    season_id = matches_df.loc[matches_df["season"] == season_label, "season_id"].iloc[0]

    seeded = _seed_known_mappings(settings)
    if seeded:
        logger.info(
            "team_clubs: seeded %d team_id -> club_id mapping(s) for free from "
            "club_teams.csv/clubs.csv (no live fetch)", seeded,
        )

    target_team_ids = _load_season_team_ids(settings)

    # Resumability source of truth, cross-season (unlike club_pipeline.py):
    # union of every season's team_clubs fetch successes (single shared log,
    # not per-season) and every team_id already resolved (seeded or fetched)
    # in team_club_map.csv - see module docstring for why both files are
    # shared across seasons rather than living under processed_dir.
    done_ids: set[str] = already_done_ids(processed_root / "team_clubs_crawl_log.csv", entity_type="team_ficha")
    done_ids |= _resolved_team_ids(processed_root)
    already_done = done_ids & set(target_team_ids)
    remaining = [tid for tid in target_team_ids if tid not in done_ids]

    logger.info(
        "team_clubs enrichment: %d targets total (season=%s), %d already resolved/attempted "
        "(cross-season), %d remaining (workers=%d)",
        len(target_team_ids), season_label, len(already_done), len(remaining), workers,
    )

    progress = Progress(_progress_path(settings, season_label), season_label, len(target_team_ids))
    progress.completed = len(already_done)
    progress.write()

    started_at = _now_iso()
    pending_rows: list[dict] = []
    pending_crawl_log_rows: list[dict] = []
    items_since_flush = 0

    local = threading.local()
    if workers == 1:
        local.client = client

    def _process_result(team_id: str, log_entry: dict, mapping_row: dict | None, fetch_seconds: float) -> None:
        nonlocal items_since_flush
        pending_crawl_log_rows.append(log_entry)
        progress.completed += 1
        progress.last_item_processed = team_id
        if mapping_row is None:
            progress.failed += 1
        else:
            if fetch_seconds > 0:
                progress.record_fetch(fetch_seconds)
            else:
                progress.skipped_cached += 1
            done_ids.add(team_id)
            pending_rows.append(mapping_row)
        items_since_flush += 1
        if progress.completed % cfg.progress_report_every == 0:
            progress.write()
            logger.info(
                "team_clubs progress: %d/%d (cached=%d fresh=%d failed=%d)",
                progress.completed, progress.total_targets, progress.skipped_cached,
                progress.freshly_fetched_ok, progress.failed,
            )
        if items_since_flush >= cfg.csv_flush_every:
            _flush_batch(processed_root, pending_rows, pending_crawl_log_rows)
            progress.write()
            upsert_coverage_manifest(
                processed_root, season=season_label, season_id=season_id,
                category_base="ALL", stage="team_clubs", status="partial",
                targets_total=len(target_team_ids), targets_completed=progress.completed,
                targets_failed=progress.failed, started_at=started_at,
            )
            items_since_flush = 0

    if workers == 1:
        for team_id in remaining:
            result = _fetch_one_team_club(
                team_id, settings, team_clubs_settings, local, client.run_id, force_refetch,
            )
            _process_result(*result)
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rffm-team-club") as executor:
            futures = {
                executor.submit(
                    _fetch_one_team_club, tid, settings, team_clubs_settings,
                    local, client.run_id, force_refetch,
                ): tid
                for tid in remaining
            }
            for future in as_completed(futures):
                _process_result(*future.result())

    _flush_batch(processed_root, pending_rows, pending_crawl_log_rows)
    progress.write()

    resolved_after = _resolved_team_ids(processed_root)
    missing = set(target_team_ids) - resolved_after
    # A team_id that was attempted (HTTP success recorded in the crawl log)
    # but genuinely has no codigo_club is a valid negative outcome, not a
    # crawl failure - same "complete_with_failures" semantics club_pipeline.py
    # already uses for RFFM's own real fichaequipo gaps.
    final_status = "complete" if not missing else "complete_with_failures"
    upsert_coverage_manifest(
        processed_root, season=season_label, season_id=season_id,
        category_base="ALL", stage="team_clubs", status=final_status,
        targets_total=len(target_team_ids), targets_completed=progress.completed,
        targets_failed=len(missing), started_at=started_at, completed_at=_now_iso(),
    )

    map_df = _reread_table(processed_root, "team_club_map.csv")
    # Safety net mirroring clubs.csv's own end-of-run dedup (club_pipeline.py)
    # - should be unreachable given the resolved-set check above, but cheap
    # to guard against a duplicate team_id slipping through a killed-and-
    # resumed run.
    if not map_df.empty and map_df["team_id"].duplicated().any():
        map_df = map_df.drop_duplicates(subset="team_id", keep="first").reset_index(drop=True)
        write_csv(map_df, processed_root / "team_club_map.csv")

    quality_issues = run_team_club_quality_checks(season_label, target_team_ids, resolved_after)
    write_csv(pd.DataFrame(quality_issues), processed / "team_clubs_data_quality_report.csv")

    summary = dict(
        season=season_label,
        targets=len(target_team_ids),
        already_done_before_this_run=len(already_done),
        processed_this_run=len(remaining),
        seeded_for_free=seeded,
        completed=progress.completed,
        freshly_fetched_ok=progress.freshly_fetched_ok,
        skipped_cached=progress.skipped_cached,
        failed=progress.failed,
        missing_after_this_run=len(missing),
        status=final_status,
        team_club_map_rows=len(map_df),
        quality_issues=len(quality_issues),
    )
    logger.info("team_clubs enrichment summary: %s", summary)
    return summary
