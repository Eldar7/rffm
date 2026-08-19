"""Typed configuration loaded from config.yaml."""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

import yaml


@dataclass
class ApiEndpoints:
    seasons: str
    game_types: str
    competitions: str
    groups: str
    results: str


@dataclass
class Pages:
    calendario: str
    clasificaciones: str
    goleadores: str
    campo: str
    acta_partido: str
    fichaequipo: str
    fichajugador: str
    fichaclub: str


@dataclass
class SiteConfig:
    base_url: str
    api: ApiEndpoints
    pages: Pages


@dataclass
class NetworkConfig:
    user_agent: str
    request_timeout_seconds: float
    rate_limit_seconds: float
    max_retries: int
    retry_backoff_seconds: float


@dataclass
class TargetConfig:
    season_label: str
    category_priority: list[str] = field(default_factory=list)
    # When true, discovery keeps every competition for every category the
    # federation runs (not just ones matching category_priority) and uses
    # the site's own raw NombreCategoria as category_base directly, with no
    # substring consolidation - there's no "priority" concept once nothing
    # is being filtered. See discovery.py.
    crawl_all_categories: bool = False


@dataclass
class ActaPartidoConfig:
    scope_category: str
    skip_byes: bool = True
    skip_unplayed: bool = True
    progress_report_every: int = 25
    csv_flush_every: int = 200
    rate_limit_seconds: float = 1.25
    force_refetch: bool = False
    workers: int = 8


@dataclass
class FichajugadorConfig:
    scope_category: str
    progress_report_every: int = 25
    csv_flush_every: int = 200
    rate_limit_seconds: float = 1.25
    force_refetch: bool = False
    workers: int = 8


@dataclass
class ClubsConfig:
    progress_report_every: int = 25
    csv_flush_every: int = 100
    rate_limit_seconds: float = 1.25
    force_refetch: bool = False
    workers: int = 8


@dataclass
class ClubProfilesConfig:
    progress_report_every: int = 25
    csv_flush_every: int = 100
    rate_limit_seconds: float = 1.25
    force_refetch: bool = False
    workers: int = 8


@dataclass
class TeamClubsConfig:
    progress_report_every: int = 25
    csv_flush_every: int = 200
    rate_limit_seconds: float = 1.25
    force_refetch: bool = False
    workers: int = 8


@dataclass
class EnrichmentConfig:
    fetch_scorers: bool
    fetch_acta_partido: bool
    fetch_fichaequipo: bool
    fetch_fichajugador: bool
    fetch_fichaclub: bool
    acta_partido: ActaPartidoConfig
    fichajugador: FichajugadorConfig
    clubs: ClubsConfig
    club_profiles: ClubProfilesConfig
    team_clubs: TeamClubsConfig


@dataclass
class Settings:
    site: SiteConfig
    network: NetworkConfig
    target: TargetConfig
    enrichment: EnrichmentConfig
    output_dir: pathlib.Path
    config_path: pathlib.Path

    @property
    def raw_dir(self) -> pathlib.Path:
        return self.output_dir / "raw" / "rffm"

    @property
    def processed_root(self) -> pathlib.Path:
        """Cross-season root: home for coverage_manifest.csv, parent of every <season>/ dir."""
        return self.output_dir / "processed" / "rffm"

    @property
    def processed_dir(self) -> pathlib.Path:
        """Season-partitioned output dir, e.g. output/processed/rffm/2025-2026/."""
        return self.processed_root / self.target.season_label

    @property
    def discovery_dir(self) -> pathlib.Path:
        return self.raw_dir / "discovery"


def load_settings(config_path: str | pathlib.Path = "config.yaml") -> Settings:
    config_path = pathlib.Path(config_path)
    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    site = SiteConfig(
        base_url=raw["site"]["base_url"],
        api=ApiEndpoints(**raw["site"]["api"]),
        pages=Pages(**raw["site"]["pages"]),
    )
    network = NetworkConfig(**raw["network"])
    target = TargetConfig(
        season_label=raw["target"]["season_label"],
        category_priority=raw["target"]["category_priority"],
        crawl_all_categories=raw["target"].get("crawl_all_categories", False),
    )
    raw_enrichment = dict(raw["enrichment"])
    acta_raw = raw_enrichment.pop("acta_partido", {})
    fichajugador_raw = raw_enrichment.pop("fichajugador", {})
    clubs_raw = raw_enrichment.pop("clubs", {})
    club_profiles_raw = raw_enrichment.pop("club_profiles", {})
    team_clubs_raw = raw_enrichment.pop("team_clubs", {})
    enrichment = EnrichmentConfig(
        **raw_enrichment,
        acta_partido=ActaPartidoConfig(**acta_raw),
        fichajugador=FichajugadorConfig(**fichajugador_raw),
        clubs=ClubsConfig(**clubs_raw),
        club_profiles=ClubProfilesConfig(**club_profiles_raw),
        team_clubs=TeamClubsConfig(**team_clubs_raw),
    )
    output_dir = pathlib.Path(raw["paths"]["output_dir"])

    return Settings(
        site=site,
        network=network,
        target=target,
        enrichment=enrichment,
        output_dir=output_dir,
        config_path=config_path,
    )
