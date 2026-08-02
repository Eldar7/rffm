"""Orchestrates discovery -> fetch -> parse -> normalize -> quality-check -> write.

Restartability: raw pages are saved to deterministic per-group paths
(overwritten on re-run, never appended), and processed CSVs are rebuilt
from scratch each run from whatever raw+live data was fetched. A single
group's fetch/parse failure is logged (crawl_log + missing manifest flags)
and does not stop the rest of the run - partial success is expected and
handled downstream by the quality report, not by crashing.
"""
from __future__ import annotations

import dataclasses
import logging
import pathlib
from datetime import datetime, timezone

import pandas as pd

from rffm_scraper.config import Settings
from rffm_scraper.discovery import DiscoveredGroup, run_discovery
from rffm_scraper.fetchers import fetch_calendario, fetch_campo, fetch_clasificaciones, fetch_goleadores
from rffm_scraper.http_client import RffmClient
from rffm_scraper.models import (
    Competition,
    CrawlLogEntry,
    Group,
    ManifestEndpoint,
    ManifestGroup,
    Match,
    Standing,
    Scorer,
    Team,
    TeamGroupMembership,
    Venue,
)
from rffm_scraper.parsers import (
    GroupContext,
    parse_matches,
    parse_scorers,
    parse_standings,
    parse_venue,
    team_group_memberships,
    teams_from_matches_and_standings,
)
from rffm_scraper.quality_checks import run_quality_checks
from rffm_scraper.row_io import atomic_write_text, upsert_coverage_manifest, validate_rows, write_csv

logger = logging.getLogger("rffm_scraper.pipeline")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save_raw(settings: Settings, category_base: str, season_label: str, page_kind: str, group_id: str, content: str) -> str:
    path = settings.raw_dir / category_base.lower() / season_label / page_kind / f"{group_id}.html"
    atomic_write_text(path, content)
    return str(path)


ENDPOINT_DOCS = [
    dict(
        name="seasons", method="GET", path="/api/seasons",
        required_params="", optional_params="delegacion",
        notes="List of all seasons with cod_temporada/nombre/fecha_inicio/fecha_fin.",
    ),
    dict(
        name="game_types", method="GET", path="/api/game-types",
        required_params="", optional_params="delegacion",
        notes="List of game types (Futbol-11/Futbol-7/Futsal/Futbol-5/Futbol-Playa).",
    ),
    dict(
        name="competitions", method="GET", path="/api/competitions",
        required_params="temporada,tipojuego", optional_params="delegacion",
        notes="Competitions for a season+game type, with NombreCategoria used for category filtering.",
    ),
    dict(
        name="groups", method="GET", path="/api/groups",
        required_params="competicion", optional_params="delegacion",
        notes="Groups within a competition, incl. total_jornadas/total_equipos/clasificacion_goleadores flags.",
    ),
    dict(
        name="results (not used)", method="GET", path="/api/results",
        required_params="idGroup,round", optional_params="delegacion",
        notes="Returns a SINGLE round's matches - would require iterating jornada 1..N per group. "
              "The calendario page below is used instead since it returns the whole season in one request.",
    ),
    dict(
        name="calendario_page", method="GET", path="/competicion/calendario",
        required_params="temporada,competicion,grupo,jornada,tipojuego",
        optional_params="",
        notes="Server-rendered page; __NEXT_DATA__.props.pageProps.calendar.rounds contains ALL jornadas "
              "for the group regardless of the jornada query value. Primary source for matches/fixtures.",
    ),
    dict(
        name="clasificaciones_page", method="GET", path="/competicion/clasificaciones",
        required_params="temporada,competicion,grupo,tipojuego", optional_params="",
        notes="__NEXT_DATA__.props.pageProps.standings.clasificacion - standings incl. puntos_sancion.",
    ),
    dict(
        name="goleadores_page", method="GET", path="/competicion/goleadores",
        required_params="temporada,competicion,grupo,tipojuego", optional_params="",
        notes="__NEXT_DATA__.props.pageProps.scorers.goles - top scorers list.",
    ),
    dict(
        name="campo_page", method="GET", path="/campo/<venue_id>",
        required_params="", optional_params="",
        notes="Venue/field profile: address, locality, province, postal code, latitude/longitude. "
              "NOT in robots.txt's Disallow list, so fetched as part of the core crawl for every "
              "unique venue_id (matches.csv's codigo_campo) seen in this run - see venues.csv.",
    ),
    dict(
        name="acta_partido_page", method="GET", path="/acta-partido/<match_id>",
        required_params="", optional_params="temporada,competicion,grupo",
        notes="Match report enrichment: lineups, goals, cards, coaches/delegates, referees. "
              "robots.txt: Disallow /acta-partido/ - fetched only if enrichment.fetch_acta_partido=true, "
              "via enrich_acta.py (separate from the core crawl).",
    ),
    dict(
        name="fichaequipo_page", method="GET", path="/fichaequipo/<team_id>",
        required_params="", optional_params="",
        notes="Team metadata enrichment (club contact info, kit colours). "
              "robots.txt: Disallow /fichaequipo/ - fetched only if enrichment.fetch_fichaequipo=true.",
    ),
    dict(
        name="fichajugador_page", method="GET", path="/fichajugador/<player_id>",
        required_params="", optional_params="temporada",
        notes="Player profile enrichment: birth year, season stats, competition participation. "
              "Bare URL (no temporada) silently defaults to the current season. "
              "robots.txt: Disallow /fichajugador/ - fetched only if enrichment.fetch_fichajugador=true, "
              "via enrich_players.py (separate from the core crawl).",
    ),
]


def run_pipeline(settings: Settings) -> dict:
    started_at = _now_iso()
    client = RffmClient(settings)
    discovery = run_discovery(client, settings)

    competitions: dict[str, dict] = {}
    groups_rows: list[dict] = []
    manifest_group_rows: list[dict] = []
    all_matches: list[dict] = []
    all_standings: list[dict] = []
    all_scorers: list[dict] = []
    teams_acc: dict[str, dict] = {}
    membership_acc: dict[tuple[str, str], dict] = {}

    for g in discovery.groups:
        _process_group(
            client, settings, g, competitions, groups_rows, manifest_group_rows,
            all_matches, all_standings, all_scorers, teams_acc, membership_acc,
        )

    matches_df = pd.DataFrame(validate_rows(Match, all_matches, "match"))
    venues_df = _fetch_venues(client, settings, matches_df)
    standings_df = pd.DataFrame(validate_rows(Standing, all_standings, "standing"))
    scorers_df = pd.DataFrame(validate_rows(Scorer, all_scorers, "scorer"))
    teams_df = pd.DataFrame(validate_rows(Team, list(teams_acc.values()), "team"))
    membership_df = pd.DataFrame(
        validate_rows(TeamGroupMembership, list(membership_acc.values()), "team_group_membership")
    )
    competitions_df = pd.DataFrame(validate_rows(Competition, list(competitions.values()), "competition"))
    groups_df = pd.DataFrame(validate_rows(Group, groups_rows, "group"))
    manifest_groups_df = pd.DataFrame(validate_rows(ManifestGroup, manifest_group_rows, "manifest_group"))

    fixtures_df = matches_df[~matches_df["is_finished"]].copy() if not matches_df.empty else matches_df

    quality_issues = run_quality_checks(matches_df, standings_df, teams_df, manifest_groups_df)
    quality_df = pd.DataFrame(quality_issues)

    seasons_df = pd.DataFrame(discovery.seasons_raw)
    game_types_df = pd.DataFrame(discovery.game_types_raw)
    endpoints_df = pd.DataFrame(validate_rows(ManifestEndpoint, ENDPOINT_DOCS, "manifest_endpoint"))
    crawl_log_df = pd.DataFrame(
        validate_rows(CrawlLogEntry, [dataclasses.asdict(e) for e in client.crawl_log], "crawl_log")
    )

    processed = settings.processed_dir
    processed.mkdir(parents=True, exist_ok=True)
    write_csv(seasons_df, processed / "seasons.csv")
    write_csv(game_types_df, processed / "game_types.csv")
    write_csv(competitions_df, processed / "competitions.csv")
    write_csv(groups_df, processed / "groups.csv")
    write_csv(teams_df, processed / "teams.csv")
    write_csv(membership_df, processed / "team_group_membership.csv")
    write_csv(matches_df, processed / "matches.csv")
    write_csv(fixtures_df, processed / "fixtures.csv")
    write_csv(venues_df, processed / "venues.csv")
    write_csv(standings_df, processed / "standings.csv")
    write_csv(scorers_df, processed / "scorers.csv")
    write_csv(manifest_groups_df, processed / "manifest_groups.csv")
    write_csv(endpoints_df, processed / "manifest_endpoints.csv")
    write_csv(crawl_log_df, processed / "crawl_log.csv")
    write_csv(quality_df, processed / "data_quality_report.csv")
    _write_page_manifest(settings, manifest_group_rows, processed / "manifest_pages.csv")

    # Core stage always completes in one run (it's fast, ~20 min/season) -
    # unlike the batched acta_partido/fichajugador stages, this is the one
    # and only coverage_manifest write for this stage per run. Not
    # category-scoped (category_base="ALL") since discovery covers every
    # matching category in a single pass, not one CLI invocation per
    # category the way the enrichment stages are.
    failed_groups = sum(1 for row in manifest_group_rows if not row["has_calendario"])
    season_id = discovery.groups[0].season_id if discovery.groups else ""
    upsert_coverage_manifest(
        settings.processed_root, season=settings.target.season_label, season_id=season_id,
        category_base="ALL", stage="core",
        status="complete" if failed_groups == 0 else "complete_with_failures",
        targets_total=len(discovery.groups), targets_completed=len(manifest_group_rows),
        targets_failed=failed_groups, started_at=started_at, completed_at=_now_iso(),
    )

    summary = dict(
        groups_discovered=len(discovery.groups),
        competitions=len(competitions),
        matches=len(matches_df),
        venues=len(venues_df),
        standings=len(standings_df),
        scorers=len(scorers_df),
        teams=len(teams_df),
        quality_issues=len(quality_df),
        crawl_requests=len(crawl_log_df),
    )
    logger.info("Pipeline summary: %s", summary)
    return summary


def _fetch_venues(client: RffmClient, settings: Settings, matches_df: pd.DataFrame) -> pd.DataFrame:
    """One /campo/<id> fetch per unique venue_id seen in this run's
    matches.csv. Not robots.txt-gated, so this runs unconditionally as part
    of the core crawl rather than a separate opt-in enrichment stage - see
    fetch_campo's docstring."""
    if matches_df.empty or "venue_id" not in matches_df.columns:
        return pd.DataFrame(columns=list(Venue.model_fields))

    venue_ids = sorted(matches_df["venue_id"].dropna().unique().tolist())
    rows: list[dict] = []
    for venue_id in venue_ids:
        result = fetch_campo(client, settings, venue_id)
        if not result.ok or not result.page_props:
            continue
        field_json = result.page_props.get("field")
        if not field_json:
            continue
        rows.append(parse_venue(field_json, venue_id, result.url))

    logger.info("Fetched %d/%d venues", len(rows), len(venue_ids))
    return pd.DataFrame(validate_rows(Venue, rows, "venue"))


def _write_page_manifest(settings: Settings, manifest_group_rows: list[dict], path: pathlib.Path) -> None:
    rows = []
    for row in manifest_group_rows:
        for kind, flag in (
            ("calendario", "has_calendario"),
            ("clasificaciones", "has_clasificaciones"),
            ("goleadores", "has_goleadores"),
        ):
            if not row[flag]:
                continue
            rows.append(
                dict(
                    page_kind=kind,
                    group_id=row["group_id"],
                    competition_id=row["competition_id"],
                    season_id=row["season_id"],
                    game_type_id=row["game_type_id"],
                    url=(
                        f"{settings.site.base_url}{getattr(settings.site.pages, kind)}"
                        f"?temporada={row['season_id']}&competicion={row['competition_id']}"
                        f"&grupo={row['group_id']}&tipojuego={row['game_type_id']}"
                    ),
                    raw_saved_path=str(
                        settings.raw_dir / row["category_base"].lower() / settings.target.season_label / kind
                        / f"{row['group_id']}.html"
                    ),
                )
            )
    pd.DataFrame(rows).to_csv(path, index=False)
    logger.info("Wrote %s (%d rows)", path, len(rows))


def _process_group(
    client: RffmClient,
    settings: Settings,
    g: DiscoveredGroup,
    competitions: dict[str, dict],
    groups_rows: list[dict],
    manifest_group_rows: list[dict],
    all_matches: list[dict],
    all_standings: list[dict],
    all_scorers: list[dict],
    teams_acc: dict[str, dict],
    membership_acc: dict[tuple[str, str], dict],
) -> None:
    scraped_at = _now_iso()
    ctx = GroupContext(
        season=g.season_label,
        season_id=g.season_id,
        category=g.category_base,
        competition=g.competition_label_raw,
        competition_id=g.competition_id,
        group=g.group_label_raw,
        group_id=g.group_id,
        game_type=g.game_type_label,
        game_type_id=g.game_type_id,
        phase_label=g.phase_label,
    )

    if g.competition_id not in competitions:
        competitions[g.competition_id] = dict(
            season=g.season_label,
            season_id=g.season_id,
            category_base=g.category_base,
            category_label_raw=g.category_label_raw,
            is_femenino=g.is_femenino,
            division_level=g.division_level,
            competition=g.competition_label_raw,
            competition_id=g.competition_id,
            phase_label=g.phase_label,
            game_type=g.game_type_label,
            game_type_id=g.game_type_id,
            source_url=(
                f"{settings.site.base_url}{settings.site.api.competitions}"
                f"?temporada={g.season_id}&tipojuego={g.game_type_id}"
            ),
            scraped_at=scraped_at,
        )

    groups_rows.append(
        dict(
            season=g.season_label,
            season_id=g.season_id,
            category=g.category_base,
            competition=g.competition_label_raw,
            competition_id=g.competition_id,
            group=g.group_label_raw,
            group_id=g.group_id,
            group_label_raw=g.group_label_raw,
            subgroup_label=None,
            source_url=f"{settings.site.base_url}{settings.site.api.groups}?competicion={g.competition_id}",
            scraped_at=scraped_at,
        )
    )

    cal = fetch_calendario(
        client, settings, season_id=g.season_id, competicion=g.competition_id,
        grupo=g.group_id, game_type_id=g.game_type_id, entity_id=g.group_id,
    )
    clas = fetch_clasificaciones(
        client, settings, season_id=g.season_id, competicion=g.competition_id,
        grupo=g.group_id, game_type_id=g.game_type_id, entity_id=g.group_id,
    )
    gol = None
    if settings.enrichment.fetch_scorers and g.clasificacion_goleadores:
        gol = fetch_goleadores(
            client, settings, season_id=g.season_id, competicion=g.competition_id,
            grupo=g.group_id, game_type_id=g.game_type_id, entity_id=g.group_id,
        )

    group_matches: list[dict] = []
    group_standings: list[dict] = []
    group_scorers: list[dict] = []

    if cal.ok and cal.raw_html:
        _save_raw(settings, g.category_base, g.season_label, "calendario", g.group_id, cal.raw_html)
        calendar_json = (cal.page_props or {}).get("calendar")
        if calendar_json:
            group_matches = parse_matches(calendar_json, ctx, cal.url)
            all_matches.extend(group_matches)

    if clas.ok and clas.raw_html:
        _save_raw(settings, g.category_base, g.season_label, "clasificaciones", g.group_id, clas.raw_html)
        standings_json = (clas.page_props or {}).get("standings")
        if standings_json:
            group_standings = parse_standings(standings_json, ctx, clas.url)
            all_standings.extend(group_standings)

    if gol is not None and gol.ok and gol.raw_html:
        _save_raw(settings, g.category_base, g.season_label, "goleadores", g.group_id, gol.raw_html)
        scorers_json = (gol.page_props or {}).get("scorers")
        if scorers_json:
            group_scorers = parse_scorers(scorers_json, ctx, gol.url)
            all_scorers.extend(group_scorers)

    teams_acc.update(teams_from_matches_and_standings(group_matches, group_standings))
    for key, row in team_group_memberships(group_matches, group_standings, ctx, cal.url).items():
        membership_acc[(g.group_id, key)] = row

    manifest_group_rows.append(
        dict(
            season_id=g.season_id,
            game_type_id=g.game_type_id,
            competition_id=g.competition_id,
            group_id=g.group_id,
            category_base=g.category_base,
            category_label_raw=g.category_label_raw,
            is_femenino=g.is_femenino,
            division_level=g.division_level,
            competition_label_raw=g.competition_label_raw,
            group_label_raw=g.group_label_raw,
            has_calendario=bool(group_matches) or (cal.ok and cal.page_props is not None),
            has_clasificaciones=bool(group_standings) or (clas.ok and clas.page_props is not None),
            has_goleadores=bool(group_scorers) or (gol is not None and gol.ok and gol.page_props is not None),
        )
    )
