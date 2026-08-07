#!/usr/bin/env python3
"""
RFFM competition-structure report ("league pyramid"): for every age
category / game type / sex this project tracks, which divisions exist,
how many teams/groups each has, how many teams promote/relegate between
adjacent divisions, and where the ladder crosses out of RFFM's own remit
into a nationally-organised RFEF competition (Tercera RFEF, Liga Nacional
Juvenil, Tercera Federación Femenina, ...).

Unlike the other reports here, the pyramid data itself is NOT derived from
the crawled CSVs — promotion/relegation counts are a competition *rule*,
not an observable match result, so they are hand-transcribed from RFFM's
own official "Bases de Ascensos y Descensos" circulars (cited per pyramid,
with the approval date) — see the docstring of PYRAMIDS_F11 below for the
source documents. What *is* computed from the crawled CSVs is the season
-timing section (compute_timing()): when each phase of each category
actually kicked off and ended, from real match dates, so that part stays
accurate as new seasons are crawled without touching this file.

Usage:
    python analysis_scripts/competition_structure.py
    python analysis_scripts/competition_structure.py --season 2025-2026 --output-dir reports
"""

import argparse
import json
import unicodedata
from pathlib import Path

import pandas as pd

from site_theme import FONT_LINKS, LANG_SWITCH_JS, THEME_INIT_JS, THEME_SWITCH_JS, switch_row_html

BASE = Path(__file__).parent.parent / "output" / "processed" / "rffm"
MANIFEST = BASE / "coverage_manifest.csv"

SRC_F11 = ("BASES DE ASCENSOS Y DESCENSOS COMPETICIÓN FÚTBOL-11, temporada 2025-2026 "
           "(RFFM, aprobadas por la Comisión Delegada el 10/07/2025)")
SRC_FS = ("BASES DE ASCENSOS Y DESCENSOS COMPETICIÓN FÚTBOL SALA "
          "(RFFM, aprobadas por la Comisión Delegada el 23/12/2024)")


def tier(name, org, scope, asc="", desc="", note=None, admin=None):
    """One rung of a pyramid.
    org: 'RFEF' (nationally organised) or 'RFFM' (regional).
    admin: set when RFFM administers an RFEF-owned competition on its
    territory (Tercera RFEF, Liga Nacional Juvenil, Tercera Federación
    Femenina) — RFFM runs the day-to-day league, but promotion above it
    and the competition's ownership belong to RFEF.
    """
    return {"name": name, "org": org, "admin": admin, "scope": scope,
            "asc": asc, "desc": desc, "note": note}


# ─────────────────────────── Fútbol-11 pyramids ───────────────────────────
PYRAMIDS_F11 = [
    {
        "id": "f11_m_aficionado", "group": "f11m", "cat": "AFICIONADO",
        "title_es": "Aficionado / Sénior — masculino, Fútbol-11", "source": SRC_F11,
        "timing_key": ("AFICIONADO", "Futbol-11", False),
        "tiers": [
            tier("SEGUNDA RFEF", "RFEF", "grupo nacional",
                  note="Fuera del ámbito RFFM — el club ya no aparece en datos de esta federación."),
            tier("TERCERA RFEF", "RFEF", "2 grupos × 18", admin="RFFM",
                 asc="1º directo + play-off territorial/nacional (9 más) → Segunda RFEF",
                 desc="mín. 3 (posiciones 16ª-18ª) → Primera División Autonómica"),
            tier("PRIMERA DIVISIÓN AUTONÓMICA", "RFFM", "2 grupos × 18",
                 asc="4 (2 mejores de cada grupo) → Tercera RFEF",
                 desc="mín. 8 (4 últimos de cada grupo) → Preferente"),
            tier("PREFERENTE", "RFFM", "4 grupos × 18",
                 asc="8 (2 de cada grupo) → 1ª Div. Autonómica",
                 desc="mín. 16 (4 de cada grupo) → Primera"),
            tier("PRIMERA", "RFFM", "8 grupos × 18",
                 asc="16 (2 de cada grupo) → Preferente",
                 desc="tantos como haga falta para que Segunda quede en ≤18 equipos/grupo"),
            tier("SEGUNDA", "RFFM", "nº de grupos por determinar",
                 asc="2 por grupo → Primera", desc="— (última división)"),
        ],
    },
    {
        "id": "f11_m_juvenil", "group": "f11m", "cat": "JUVENIL",
        "title_es": "Juvenil — masculino, Fútbol-11", "source": SRC_F11,
        "timing_key": ("JUVENIL", "Futbol-11", False),
        "tiers": [
            tier("DIVISIÓN DE HONOR JUVENIL", "RFEF", "grupos nacionales",
                 note="Organizada exclusivamente por la RFEF; no la administra RFFM."),
            tier("LIGA NACIONAL JUVENIL", "RFEF", "1 grupo × 18", admin="RFFM",
                 asc="2 mejores → División de Honor Juvenil",
                 desc="mín. 2 (17ª-18ª) → 1ª Div. Autonómica",
                 note="Esto es «Nacional Juvenil» — el nivel que antes desaparecía del mapa de clubes por un bug de filtrado, ya corregido."),
            tier("PRIMERA DIVISIÓN AUTONÓMICA", "RFFM", "2 grupos × 18 (nueva en 2025/26)",
                 asc="4 (2 de cada grupo) → Liga Nacional Juvenil",
                 desc="mín. 6 (3 de cada grupo) → Preferente"),
            tier("PREFERENTE", "RFFM", "5 grupos × 18",
                 asc="1º de cada grupo directo a Div. Honor; 2º-9º directos a 1ª Div. Autonómica; "
                     "10º-16º juegan play-off de ascenso a 1ª Div. Autonómica contra los campeones de Primera",
                 desc="— (no bajan a Primera)"),
            tier("PRIMERA", "RFFM", "12 grupos × 18",
                 asc="campeones de grupo → play-off vs. 10º-16º de Preferente; el resto de ascensos, "
                     "vía coeficiente, hasta completar Preferente",
                 desc="— (no bajan; es la penúltima división)"),
            tier("SEGUNDA", "RFFM", "nº de grupos por determinar",
                 asc="2 por grupo → Primera", desc="— (última división)"),
        ],
    },
    {
        "id": "f11_m_cadete", "group": "f11m", "cat": "CADETE",
        "title_es": "Cadete — masculino, Fútbol-11", "source": SRC_F11,
        "timing_key": ("CADETE", "Futbol-11", False),
        "tiers": [
            tier("SUPERLIGA", "RFFM", "1 grupo × 16",
                 asc="— (tope de la pirámide)",
                 desc="4 (posiciones 13ª-16ª) → División de Honor"),
            tier("DIVISIÓN DE HONOR", "RFFM", "2 grupos × 16",
                 asc="2 de cada grupo → Superliga",
                 desc="4 de cada grupo (13ª-16ª) → 1ª Div. Autonómica"),
            tier("PRIMERA DIVISIÓN AUTONÓMICA", "RFFM", "4 grupos × 16 (nueva en 2025/26)",
                 asc="2 de cada grupo (1º-2º) → División de Honor",
                 desc="4 de cada grupo (13ª-16ª) → Preferente"),
            tier("PREFERENTE", "RFFM", "8 grupos × 16",
                 asc="1º-8º directos a 1ª Div. Autonómica; 9º-14º juegan play-off vs. campeones de Primera",
                 desc="— (no bajan a Primera)"),
            tier("PRIMERA", "RFFM", "16 grupos × 16",
                 asc="campeones → play-off vs. 9º-14º de Preferente; resto vía coeficiente",
                 desc="— (no bajan; penúltima división)"),
            tier("SEGUNDA", "RFFM", "nº de grupos por determinar",
                 asc="2 por grupo → Primera", desc="— (última división)"),
        ],
    },
    {
        "id": "f11_m_infantil", "group": "f11m", "cat": "INFANTIL",
        "title_es": "Infantil — masculino, Fútbol-11", "source": SRC_F11,
        "timing_key": ("INFANTIL", "Futbol-11", False),
        "tiers": [
            tier("SUPERLIGA", "RFFM", "1 grupo × 16",
                 asc="— (tope de la pirámide)",
                 desc="4 (posiciones 13ª-16ª) → División de Honor"),
            tier("DIVISIÓN DE HONOR", "RFFM", "2 grupos × 16",
                 asc="2 de cada grupo → Superliga",
                 desc="4 de cada grupo (13ª-16ª) → 1ª Div. Autonómica"),
            tier("PRIMERA DIVISIÓN AUTONÓMICA", "RFFM", "4 grupos × 16 (nueva en 2025/26)",
                 asc="2 de cada grupo (1º-2º) → División de Honor",
                 desc="4 de cada grupo (13ª-16ª) → Preferente"),
            tier("PREFERENTE", "RFFM", "8 grupos × 16",
                 asc="1º-9º directos a 1ª Div. Autonómica; 10º-14º juegan play-off vs. campeones de Primera",
                 desc="— (no bajan a Primera)"),
            tier("PRIMERA", "RFFM", "16 grupos × 16",
                 asc="campeones → play-off vs. 10º-14º de Preferente; resto vía coeficiente",
                 desc="— (no bajan; penúltima división)"),
            tier("SEGUNDA", "RFFM", "nº de grupos por determinar",
                 asc="2 por grupo → Primera", desc="— (última división)"),
        ],
    },
    {
        "id": "f11_m_alevin", "group": "f11m", "cat": "ALEVIN",
        "title_es": "Alevín — masculino, Fútbol-11", "source": SRC_F11,
        "timing_key": ("ALEVIN", "Futbol-11", False),
        "tiers": [
            tier("SUPERLIGA", "RFFM", "1 grupo × 16",
                 asc="— (tope de la pirámide)",
                 desc="4 (posiciones 13ª-16ª) → División de Honor"),
            tier("DIVISIÓN DE HONOR", "RFFM", "2 grupos × 16",
                 asc="4 (2 de cada grupo) → Superliga",
                 desc="4 de cada grupo (13ª-16ª) → 1ª Div. Autonómica"),
            tier("PRIMERA DIVISIÓN AUTONÓMICA", "RFFM", "4 grupos × 14",
                 asc="8 (2 de cada grupo) → División de Honor",
                 desc="4 de cada grupo (11ª-14ª) → Preferente"),
            tier("PREFERENTE", "RFFM", "8 grupos × 14",
                 asc="16 (2 de cada grupo) → 1ª Div. Autonómica",
                 desc="tantos como haga falta para que Primera quede en ≤14 equipos/grupo"),
            tier("PRIMERA", "RFFM", "nº de grupos por determinar",
                 asc="2 por grupo → Preferente", desc="— (última división; Alevín F-11 no tiene Segunda)"),
        ],
    },
]

# Femenino, Fútbol-11 — RFFM runs these three age brackets as F-11
# (Infantil/Alevín Femenino instead play Fútbol-7, see the note in
# f7_pyramid_note() below); Tercera Federación Femenina is the shared
# open-category doorway to RFEF that every women's Aficionado team feeds
# into regardless of age.
PYRAMIDS_F11_FEM = [
    {
        "id": "f11_f_aficionado", "group": "f11f", "cat": "AFICIONADO",
        "title_es": "Aficionado — femenino, Fútbol-11", "source": SRC_F11,
        "timing_key": ("OTHER", "Futbol-11", True),
        "tiers": [
            tier("SEGUNDA FEDERACIÓN FEMENINA", "RFEF", "grupo nacional",
                 note="Fuera del ámbito RFFM."),
            tier("TERCERA FEDERACIÓN DE FÚTBOL FEMENINO", "RFEF", "1 grupo × 12", admin="RFFM",
                 asc="1º con mejor coeficiente nacional asciende directo; el resto de 1ºs juegan "
                     "play-off nacional → Segunda Federación Femenina",
                 desc="mín. 2 (11ª-12ª) → 1ª Div. Autonómica Femenino"),
            tier("PRIMERA DIVISIÓN AUTONÓMICA FEMENINO", "RFFM", "1 grupo × 16",
                 asc="1º juega play-off de ascenso por proximidad territorial → Tercera Federación",
                 desc="mín. 3 (12ª-14ª) → Preferente Femenino"),
            tier("PREFERENTE FEMENINO", "RFFM", "grupos por determinar",
                 asc="hasta completar 1ª Div. Autonómica (16 equipos)",
                 desc="— (Primera es la última división)"),
            tier("PRIMERA FEMENINO", "RFFM", "por determinar",
                 asc="mejor clasificados → Preferente", desc="— (última división)"),
        ],
    },
    {
        "id": "f11_f_juvenil", "group": "f11f", "cat": "JUVENIL",
        "title_es": "Juvenil — femenino, Fútbol-11", "source": SRC_F11,
        "timing_key": ("JUVENIL", "Futbol-11", True),
        "tiers": [
            tier("PRIMERA DIVISIÓN AUTONÓMICA FEMENINO", "RFFM", "1 grupo × 16",
                 asc="— (tope de la categoría; Juvenil Femenino no conecta con RFEF)",
                 desc="4 (13ª-16ª) → Preferente Femenino"),
            tier("PREFERENTE FEMENINO", "RFFM", "2 grupos × 16",
                 asc="2 de cada grupo → 1ª Div. Autonómica",
                 desc="tantos como haga falta para que Primera quede en ≤16/grupo"),
            tier("PRIMERA FEMENINO", "RFFM", "por determinar",
                 asc="1º de cada grupo → Preferente", desc="— (última división)"),
        ],
    },
    {
        "id": "f11_f_cadete", "group": "f11f", "cat": "CADETE",
        "title_es": "Cadete — femenino, Fútbol-11", "source": SRC_F11,
        "timing_key": ("CADETE", "Futbol-11", True),
        "tiers": [
            tier("PRIMERA DIVISIÓN AUTONÓMICA FEMENINO", "RFFM", "1 grupo × 16",
                 asc="— (tope de la categoría)",
                 desc="4 (13ª-16ª) → Preferente Femenino"),
            tier("PREFERENTE FEMENINO", "RFFM", "2 grupos × 16",
                 asc="2 de cada grupo → 1ª Div. Autonómica",
                 desc="tantos como haga falta para que Primera quede en ≤16/grupo"),
            tier("PRIMERA FEMENINO", "RFFM", "por determinar",
                 asc="1º de cada grupo → Preferente", desc="— (última división)"),
        ],
    },
]

# ─────────────────────────── Fútbol Sala pyramids ──────────────────────────
PYRAMIDS_FS = [
    {
        "id": "fs_m_aficionado", "group": "fsm", "cat": "AFICIONADO",
        "title_es": "Aficionado / Sénior — masculino, Fútbol Sala", "source": SRC_FS,
        "timing_key": ("AFICIONADO", "Fútbol Sala", False),
        "tiers": [
            tier("SEGUNDA DIVISIÓN “B”", "RFEF", "grupo nacional", note="Fuera del ámbito RFFM."),
            tier("TERCERA DIVISIÓN", "RFEF", "2 grupos × 16", admin="RFFM",
                 asc="ganador del play-off entre los 2 campeones de grupo → Segunda División B",
                 desc="15º-16º de cada grupo → 1ª Div. Autonómica"),
            tier("PRIMERA DIVISIÓN AUTONÓMICA", "RFFM", "2 grupos × 14",
                 asc="4 (2 de cada grupo) → Tercera División",
                 desc="13º-14º de cada grupo → Preferente"),
            tier("PREFERENTE", "RFFM", "2 grupos × 14",
                 asc="4 (2 de cada grupo) → 1ª Div. Autonómica",
                 desc="13º-14º de cada grupo → Primera"),
            tier("PRIMERA", "RFFM", "3 grupos × 10",
                 asc="fase por grupos + 2ª fase (grupo “A” con mejor coeficiente): "
                     "1º-4º del grupo “A” → Preferente",
                 desc="— (última división)"),
        ],
    },
    {
        "id": "fs_m_juvenil", "group": "fsm", "cat": "JUVENIL",
        "title_es": "Juvenil — masculino, Fútbol Sala", "source": SRC_FS,
        "timing_key": ("JUVENIL", "Fútbol Sala", False),
        "tiers": [
            tier("DIVISIÓN DE HONOR JUVENIL FS", "RFEF", "grupos nacionales",
                 note="Organizada exclusivamente por la RFEF."),
            tier("PREFERENTE JUVENIL", "RFFM", "1 grupo × 16",
                 asc="1º → División de Honor Juvenil FS; 2º-9º → nueva 1ª Div. Autonómica (creada en 2025/26); "
                     "1ºs de Primera juegan play-off vs. 10º-16º de Preferente por las plazas restantes",
                 desc="— (no baja a Primera)"),
            tier("PRIMERA JUVENIL", "RFFM", "7 grupos × 12",
                 asc="campeones de grupo → play-off vs. 10º-16º de Preferente; perdedores + resto "
                     "por coeficiente completan 2 grupos de Preferente de 14",
                 desc="— (última división)"),
        ],
    },
    {
        "id": "fs_m_cadete", "group": "fsm", "cat": "CADETE",
        "title_es": "Cadete — masculino, Fútbol Sala", "source": SRC_FS,
        "timing_key": ("CADETE", "Fútbol Sala", False),
        "tiers": [
            tier("PREFERENTE CADETE", "RFFM", "1 grupo × 14",
                 asc="1º-8º → nueva 1ª Div. Autonómica (creada en 2025/26); 9º-14º juegan play-off "
                     "vs. campeones de grupo de Primera",
                 desc="— (no baja a Primera)"),
            tier("PRIMERA CADETE", "RFFM", "6 grupos × 14",
                 asc="campeones → play-off vs. 9º-14º de Preferente; resto completa Preferente por coeficiente",
                 desc="— (última división)"),
        ],
    },
    {
        "id": "fs_m_infantil", "group": "fsm", "cat": "INFANTIL",
        "title_es": "Infantil — masculino, Fútbol Sala", "source": SRC_FS,
        "timing_key": ("INFANTIL", "Fútbol Sala", False),
        "tiers": [
            tier("PREFERENTE INFANTIL", "RFFM", "1 grupo × 14",
                 asc="1º-9º → nueva 1ª Div. Autonómica (creada en 2025/26); 10º-14º juegan play-off "
                     "vs. campeones de grupo de Primera",
                 desc="— (no baja a Primera)"),
            tier("PRIMERA INFANTIL", "RFFM", "5 grupos × 14",
                 asc="campeones → play-off vs. 10º-14º de Preferente; resto completa Preferente por coeficiente",
                 desc="— (última división)"),
        ],
    },
]

# Categories that RFFM runs Fútbol Sala as a SINGLE division with no
# promotion/relegation at all — the "ladder" is entirely inside one season
# via the two-phase group-reshuffle format (see NOTES_SINGLE_DIVISION_FS).
SINGLE_DIVISION_FS = [
    ("ALEVIN", "Alevín — masculino, Fútbol Sala", "1 grupo por proximidad, tantos como haga falta con 10 equipos"),
    ("BENJAMIN", "Benjamín — masculino, Fútbol Sala", "1 grupo por proximidad, tantos como haga falta con 10 equipos"),
    ("PREBENJAMIN", "Prebenjamín — masculino, Fútbol Sala", "según nº de inscripciones"),
]
SINGLE_DIVISION_FS_FEM = [
    ("JUVENIL", "Juvenil — femenino, Fútbol Sala", "1 grupo × 5"),
    ("CADETE", "Cadete — femenino, Fútbol Sala", "2 grupos de 11 y 10"),
    ("INFANTIL", "Infantil — femenino, Fútbol Sala", "2 grupos × 12"),
    ("ALEVIN", "Alevín — femenino, Fútbol Sala", "2 grupos de 10 y 9"),
    ("BENJAMIN", "Benjamín — femenino, Fútbol Sala", "1 grupo × 12"),
]

PYRAMID_FS_FEM_AFICIONADO = {
    "id": "fs_f_aficionado", "group": "fsf", "cat": "AFICIONADO",
    "title_es": "Aficionado — femenino, Fútbol Sala", "source": SRC_FS,
    "timing_key": ("OTHER", "Fútbol Sala", True),
    "tiers": [
        tier("SEGUNDA FEDERACIÓN FUTSAL FEMENINA", "RFEF", "grupo nacional", note="Fuera del ámbito RFFM."),
        tier("PRIMERA DIVISIÓN AUTONÓMICA FEMENINA", "RFFM", "1 grupo × 14",
             asc="1º juega play-off de ascenso por proximidad territorial",
             desc="mín. 3 (12ª-14ª) → Preferente Femenina"),
        tier("PREFERENTE FEMENINA", "RFFM", "2 grupos × 10",
             asc="1ª fase de liga + 2ª fase entre los 8 mejores coeficientes: 1º-3º → 1ª Div. Autonómica "
                 "(el resto de equipos juega el Torneo de Aficionados-Juvenil aparte)",
             desc="— (última división)"),
    ],
}

# ─────────────────────────── Fútbol-7 pyramids ─────────────────────────────
# Source: BASES DE ASCENSOS Y DESCENSOS COMPETICIÓN FÚTBOL-7 (RFFM, aprobadas
# por la Comisión Delegada el 23/12/2024) — this circular governs 2024/2025's
# own ascensos AND explicitly creates two new top tiers for 2025/2026
# (DIVISIÓN DE HONOR Benjamín, PRIMERA DIVISIÓN AUTONÓMICA Prebenjamín),
# already populated with real teams in this project's 2025-2026 crawl (e.g.
# ARAVACA C.F. - CEIBA 'A' sits in the new División de Honor Benjamín F-7
# after winning its Primera Autonómica group in 2024/2025).
SRC_F7 = ("BASES DE ASCENSOS Y DESCENSOS COMPETICIÓN FÚTBOL-7 (RFFM, aprobadas por la "
          "Comisión Delegada el 23/12/2024) — describe los ascensos de 2024/2025 que crean "
          "las nuevas División de Honor Benjamín y 1ª Div. Autonómica Prebenjamín para 2025/2026")

PYRAMIDS_F7 = [
    {
        "id": "f7_m_alevin", "group": "f7m", "cat": "ALEVIN",
        "title_es": "Alevín — masculino, Fútbol-7", "source": SRC_F7,
        "timing_key": ("ALEVIN", "Futbol-7", False),
        "tiers": [
            tier("DIVISIÓN DE HONOR", "RFFM", "2 grupos × 14",
                 asc="— (tope de la pirámide)",
                 desc="4 de cada grupo (carácter fijo) → 1ª Div. Autonómica"),
            tier("PRIMERA DIVISIÓN AUTONÓMICA", "RFFM", "4 grupos × 14",
                 asc="2 de cada grupo → División de Honor",
                 desc="4 de cada grupo → Preferente"),
            tier("PREFERENTE", "RFFM", "8 grupos × 14",
                 asc="2 de cada grupo → 1ª Div. Autonómica",
                 desc="4 de cada grupo → Primera"),
            tier("PRIMERA", "RFFM", "16 grupos × 13",
                 asc="2 de cada grupo → Preferente",
                 desc="3 de cada grupo (11ª-13ª) + los 3 peores coeficientes de los 10ºs → Segunda"),
            tier("SEGUNDA", "RFFM", "51 grupos / 653 equipos",
                 asc="1º de cada grupo → Primera", desc="— (última división)"),
        ],
    },
    {
        "id": "f7_m_benjamin", "group": "f7m", "cat": "BENJAMIN",
        "title_es": "Benjamín — masculino, Fútbol-7", "source": SRC_F7,
        "timing_key": ("BENJAMIN", "Futbol-7", False),
        "tiers": [
            tier("DIVISIÓN DE HONOR", "RFFM", "4 grupos × 13 (nueva en 2025/26)",
                 asc="— (tope de la pirámide)", desc="— (no hay descensos a 1ª Div. Autonómica)",
                 note="Creada para 2025/2026: suben los seis (6) primeros de cada grupo de 1ª Div. "
                      "Autonómica 2024/2025, más los 4 mejores séptimos por coeficiente."),
            tier("PRIMERA DIVISIÓN AUTONÓMICA", "RFFM", "8 grupos × 13",
                 asc="1º-6º de cada grupo → División de Honor (temporada de creación); "
                     "en años normales: 1º-3º + mejores 4os cuartos por coeficiente → Preferente arriba",
                 desc="— (no baja a Preferente)"),
            tier("PREFERENTE", "RFFM", "16 grupos × 13",
                 asc="1º-3º de cada grupo + los 4 mejores cuartos por coeficiente → 1ª Div. Autonómica",
                 desc="13º de cada grupo (fijo) + los 10 peores 12ºs por coeficiente → Primera"),
            tier("PRIMERA", "RFFM", "78 grupos / 958 equipos",
                 asc="1º de cada grupo → Preferente", desc="— (última división)"),
        ],
    },
    {
        "id": "f7_m_prebenjamin", "group": "f7m", "cat": "PREBENJAMIN",
        "title_es": "Prebenjamín — masculino, Fútbol-7", "source": SRC_F7,
        "timing_key": ("PREBENJAMIN", "Futbol-7", False),
        "tiers": [
            tier("PRIMERA DIVISIÓN AUTONÓMICA", "RFFM", "8 grupos × 12 (nueva en 2025/26)",
                 asc="— (tope de la pirámide)", desc="— (no hay descensos a Preferente)",
                 note="Creada para 2025/2026: suben todos los equipos que jugaron el Subgrupo «A» "
                      "de Preferente en 2024/2025, más los del Subgrupo «B» necesarios para completar plazas."),
            tier("PREFERENTE", "RFFM", "16 grupos × 12",
                 asc="Subgrupo «A» (2ª fase, top-6 de la 1ª fase) juega por el ascenso; en la temporada "
                     "de creación asciende en bloque a la nueva 1ª Div. Autonómica",
                 desc="— (no baja a Primera)"),
            tier("PRIMERA", "RFFM", "53 grupos / 593 equipos",
                 asc="1º de cada Subgrupo «A» + los 43 mejores segundos de Subgrupo «A» por coeficiente → Preferente",
                 desc="— (última división)"),
        ],
    },
]

# Femenino Alevín/Infantil F-7 have real ladders (unlike the equivalent
# Fútbol Sala femenino categories, which are single-division) — Benjamín
# Femenino F-7 already has its new PREFERENTE created for 2025/2026 live in
# this project's crawled data.
PYRAMIDS_F7_FEM = [
    {
        "id": "f7_f_infantil", "group": "f7f", "cat": "INFANTIL",
        "title_es": "Infantil — femenino, Fútbol-7", "source": SRC_F7,
        "timing_key": ("INFANTIL", "Futbol-7", True),
        "tiers": [
            tier("PRIMERA DIVISIÓN AUTONÓMICA", "RFFM", "1 grupo × 14",
                 asc="— (tope de la pirámide)", desc="4 (11ª-14ª) → Preferente"),
            tier("PREFERENTE", "RFFM", "2 grupos × 14 (3 grupos desde 2025/26)",
                 asc="2 de cada grupo → 1ª Div. Autonómica", desc="4 de cada grupo (11ª-14ª) → Primera"),
            tier("PRIMERA", "RFFM", "16 grupos / 193 equipos",
                 asc="1º de cada grupo + los 6 mejores segundos por coeficiente → Preferente",
                 desc="— (última división)"),
        ],
    },
    {
        "id": "f7_f_alevin", "group": "f7f", "cat": "ALEVIN",
        "title_es": "Alevín — femenino, Fútbol-7", "source": SRC_F7,
        "timing_key": ("ALEVIN", "Futbol-7", True),
        "tiers": [
            tier("PRIMERA DIVISIÓN AUTONÓMICA", "RFFM", "1 grupo × 14",
                 asc="— (tope de la pirámide)", desc="4 (11ª-14ª) → Preferente"),
            tier("PREFERENTE", "RFFM", "2 grupos × 14 (3 grupos desde 2025/26)",
                 asc="2 de cada grupo → 1ª Div. Autonómica", desc="4 de cada grupo (11ª-14ª) → Primera"),
            tier("PRIMERA", "RFFM", "10 grupos / 119 equipos",
                 asc="1º y 2º de cada grupo + los 2 mejores terceros por coeficiente → Preferente",
                 desc="— (última división)"),
        ],
    },
    {
        "id": "f7_f_benjamin", "group": "f7f", "cat": "BENJAMIN",
        "title_es": "Benjamín — femenino, Fútbol-7", "source": SRC_F7,
        "timing_key": ("BENJAMIN", "Futbol-7", True),
        "tiers": [
            tier("PREFERENTE", "RFFM", "1 grupo × 12 (nueva en 2025/26)",
                 asc="— (tope de la pirámide)", desc="— (no hay descensos)",
                 note="Creada para 2025/2026: absorbe tantos equipos de Primera 2024/2025 como haga "
                      "falta para completar un grupo de doce (12)."),
            tier("PRIMERA", "RFFM", "4 grupos / 39 equipos",
                 asc="tantos como haga falta para completar Preferente (12 equipos)",
                 desc="— (última división)"),
        ],
    },
]

ALL_PYRAMIDS = (PYRAMIDS_F11 + PYRAMIDS_F11_FEM + PYRAMIDS_F7 + PYRAMIDS_F7_FEM
                 + PYRAMIDS_FS + [PYRAMID_FS_FEM_AFICIONADO])

PHASE_BUCKET = {
    "regular_season": "liga",
    "phase segunda fase": "fase2",
    "playoff": "playoff",
    "playoff FASE FINAL": "playoff",
    "phase fase final": "playoff",
    "phase 7 fase": "playoff",
    "playoff 7 FASE": "playoff",
}
BUCKET_LABEL_ES = {"liga": "Liga regular", "fase2": "2ª fase", "playoff": "Play-off / Torneo de Campeones"}
MONTHS_ES = ["sep", "oct", "nov", "dic", "ene", "feb", "mar", "abr", "may", "jun"]


def month_index(ts) -> int:
    return (ts.month - 9) % 12


def list_seasons() -> list[str]:
    m = pd.read_csv(MANIFEST, dtype=str)
    core = m[(m["stage"] == "core") & (m["category_base"] == "ALL") &
             (m["status"].isin(["complete", "complete_with_failures"]))]
    return sorted(core["season"].unique().tolist())


def compute_timing(season: str) -> dict:
    """(category_base, game_type, is_femenino) -> list of {bucket, start_m,
    end_m, n} spans, computed straight from this season's real match dates —
    not hand-authored, so it stays correct as new seasons get crawled."""
    d = BASE / season
    matches = pd.read_csv(d / "matches.csv", dtype=str)
    comps = pd.read_csv(d / "competitions.csv", dtype=str)
    matches["match_date"] = pd.to_datetime(matches["match_date"], errors="coerce")
    comp_meta = comps.set_index("competition_id")[["category_base", "division_level", "is_femenino"]]
    matches = matches.join(comp_meta, on="competition_id")
    matches = matches.dropna(subset=["match_date"])
    matches["bucket"] = matches["phase_label"].map(PHASE_BUCKET).fillna("playoff")
    matches["is_fem"] = matches["is_femenino"].eq("True")

    out: dict[tuple, list] = {}
    for (cat, gt, is_fem, bucket), grp in matches.groupby(["category_base", "game_type", "is_fem", "bucket"]):
        start, end = grp["match_date"].min(), grp["match_date"].max()
        out.setdefault((cat, gt, is_fem), []).append({
            "bucket": bucket, "start_m": month_index(start), "end_m": month_index(end),
            "start": start.strftime("%d.%m"), "end": end.strftime("%d.%m"), "n": int(len(grp)),
        })
    for spans in out.values():
        spans.sort(key=lambda s: s["start_m"])
    return out


def timeline_html(spans: list) -> str:
    if not spans:
        return '<div class="tl-empty">—</div>'
    cells = []
    for i, mo in enumerate(MONTHS_ES):
        hit = next((s for s in spans if s["start_m"] <= i <= s["end_m"]), None)
        cls = f"tl-cell tl-{hit['bucket']}" if hit else "tl-cell tl-off"
        title = f' title="{BUCKET_LABEL_ES[hit["bucket"]]}: {hit["start"]}–{hit["end"]} ({hit["n"]} partidos)"' if hit else ""
        cells.append(f'<span class="{cls}"{title}></span>')
    legend = " ".join(sorted({s["bucket"] for s in spans}))
    return f'<div class="tl-row" data-buckets="{legend}">' + "".join(cells) + "</div>"


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


# A few tier names use different wording than the division_level token the
# scraper's classify_division_level() assigns to the real competition rows
# (see DATA_DICTIONARY.md / DIVISIONS.md) — mapped by hand here, everything
# else matches by stripping accents/curly quotes.
TIER_DIVISION_LEVEL_OVERRIDES = {
    "TERCERA RFEF": "TERCERA FEDERACION",
    "LIGA NACIONAL JUVENIL": "LIGA NACIONAL",
    "TERCERA FEDERACIÓN DE FÚTBOL FEMENINO": "TERCERA FEDERACION",
    "TERCERA DIVISIÓN": "TERCERA",
    "SEGUNDA DIVISIÓN “B”": "SEGUNDA DIVISION B",
}


def _division_level_for_tier(name: str) -> str:
    return TIER_DIVISION_LEVEL_OVERRIDES.get(name, _strip_accents(name).upper())


def build_examples_index(season: str) -> dict:
    """(category_base, game_type, is_femenino, division_level) -> up to 3 real
    competition names from this season's competitions.csv — lets each tier
    card show which actual RFFM tournaments live at that rung, instead of
    just the abstract division_level name."""
    comps = pd.read_csv(BASE / season / "competitions.csv", dtype=str)
    comps = comps[comps["phase_label"] == "regular_season"]
    comps["is_fem_bool"] = comps["is_femenino"] == "True"
    idx: dict[tuple, list[str]] = {}
    for (cat, gt, fem, dl), grp in comps.groupby(["category_base", "game_type", "is_fem_bool", "division_level"]):
        idx[(cat, gt, fem, dl)] = sorted(grp["competition"].dropna().unique().tolist())[:3]
    return idx


def tier_examples(idx: dict, cat_candidates: list[str], game_type: str, is_fem: bool, tier_name: str) -> list[str]:
    dl = _division_level_for_tier(tier_name)
    for c in cat_candidates:
        names = idx.get((c, game_type, is_fem, dl))
        if names:
            return names
    return []


def tier_row_html(t: dict, is_last: bool, examples: list[str], season: str) -> str:
    org_cls = "org-rfef" if t["org"] == "RFEF" else "org-rffm"
    admin_badge = f'<span class="admin-badge">RFFM la administra</span>' if t.get("admin") else ""
    note_html = f'<div class="tier-note">{t["note"]}</div>' if t.get("note") else ""
    asc_html = f'<div class="tier-line"><span class="tier-arrow up">↑</span>{t["asc"]}</div>' if t.get("asc") else ""
    desc_html = f'<div class="tier-line"><span class="tier-arrow down">↓</span>{t["desc"]}</div>' if t.get("desc") else ""
    ex_html = ""
    if examples:
        chips = "".join(f'<span class="ex-chip">{e}</span>' for e in examples)
        ex_html = f'<div class="tier-examples"><span class="ex-label">{season}:</span>{chips}</div>'
    connector = "" if is_last else '<div class="tier-connector"></div>'
    return f'''<div class="tier {org_cls}">
      <div class="tier-head"><span class="tier-name">{t["name"]}</span>
        <span class="tier-org">{t["org"]}</span>{admin_badge}</div>
      <div class="tier-scope">{t["scope"]}</div>
      {asc_html}{desc_html}{note_html}{ex_html}
    </div>{connector}'''


def pyramid_card_html(p: dict, timing: dict, examples_idx: dict, season: str) -> str:
    cat, game_type, is_fem = p["timing_key"]
    cat_candidates = list(dict.fromkeys([p["cat"], cat, "OTHER"]))
    tiers_html = "".join(
        tier_row_html(t, i == len(p["tiers"]) - 1,
                       tier_examples(examples_idx, cat_candidates, game_type, is_fem, t["name"]), season)
        for i, t in enumerate(p["tiers"])
    )
    spans = timing.get(p["timing_key"], [])
    tl = timeline_html(spans)
    return f'''<div class="pyramid-card" data-group="{p["group"]}">
      <h3>{p["title_es"]}</h3>
      <div class="pyramid-ladder">{tiers_html}</div>
      <div class="pyramid-timing"><div class="tl-months">{"".join(f'<span>{m}</span>' for m in MONTHS_ES)}</div>{tl}</div>
      <div class="pyramid-src">{p["source"]}</div>
    </div>'''


def single_division_card_html(cat: str, title: str, scope: str, timing: dict, group: str,
                               is_fem: bool, game_type: str = "Fútbol Sala", source: str = SRC_FS) -> str:
    key = (cat, game_type, is_fem)
    spans = timing.get(key, [])
    tl = timeline_html(spans)
    return f'''<div class="pyramid-card single" data-group="{group}">
      <h3>{title}</h3>
      <div class="single-note">División única — sin ascensos ni descensos. {scope}.
      La clasificación se resuelve en dos fases dentro de la misma temporada: una liga inicial
      de proximidad geográfica y una segunda fase que reagrupa a los equipos por nivel
      (coeficiente de la primera fase) para jugar el título y el resto de puestos.</div>
      <div class="pyramid-timing"><div class="tl-months">{"".join(f'<span>{m}</span>' for m in MONTHS_ES)}</div>{tl}</div>
      <div class="pyramid-src">{source}</div>
    </div>'''


GROUP_LABELS = [
    ("f11m", "Fútbol-11 · Masculino"), ("f11f", "Fútbol-11 · Femenino"),
    ("f7m", "Fútbol-7 · Masculino"), ("f7f", "Fútbol-7 · Femenino"),
    ("fsm", "Fútbol Sala · Masculino"), ("fsf", "Fútbol Sala · Femenino"),
]

I18N_ES = {
    "eyebrow": "RFFM (Madrid) &middot; estructura de competiciones",
    "h1": "Pirámide de ligas de la RFFM: categorías, divisiones, ascensos",
    "lede": "Para cada edad / tipo de juego / sexo &mdash; la escalera completa de divisiones de arriba a abajo: "
            "cuántos equipos/grupos hay en cada división, cuántos ascienden y descienden entre divisiones vecinas, "
            "y dónde la escalera sale del ámbito de la RFFM hacia competiciones organizadas por toda España (RFEF: "
            "Tercera RFEF, Liga Nacional Juvenil, Tercera Federación Femenina). Las reglas de ascenso/descenso están "
            "tomadas de las circulares oficiales «Bases de Ascensos y Descensos» de la RFFM (temporada 2025-2026, "
            "ver la referencia bajo cada tarjeta); el calendario de fases al pie de cada tarjeta está calculado a "
            "partir de las fechas reales de los partidos en los datos recopilados, no transcrito a mano.",
    "leg1": '<span class="leg-swatch leg-rffm"></span><b>RFFM</b> &mdash; competición regional',
    "leg2": '<span class="leg-swatch leg-rfef"></span><b>RFEF</b> &mdash; competición nacional (la RFFM puede administrarla en su territorio)',
    "leg3": '<span class="leg-swatch leg-liga"></span>liga regular',
    "leg4": '<span class="leg-swatch leg-fase2"></span>2ª fase (grupos por nivel)',
    "leg5": '<span class="leg-swatch leg-playoff"></span>play-off / Torneo de Campeones',
    "h_single": "Otras categorías de Fútbol Sala sin pirámide",
    "h_single_n": "división única, sin ascensos ni descensos",
    "single_p": "Prebenjamín/Benjamín/Alevín (masculino) y toda la línea Juvenil&ndash;Benjamín (femenino) de Fútbol "
                "Sala juegan en la RFFM en una única división por edad &mdash; no hay ascensos ni descensos en absoluto, "
                "y la estructura dentro de la temporada se resuelve con un formato de dos fases (1ª fase &mdash; liga "
                "por proximidad geográfica, 2ª fase &mdash; reagrupación por nivel para disputar el título y el resto "
                "de puestos).",
    "h_how": "Cómo está organizado",
    "h_strict": "Cuán estrictas son las reglas de ascenso/descenso",
    "h_strict_n": "mecánica entre temporadas, no principios generales",
    "how_p1": '<b>Dos fronteras distintas.</b> Un club puede cruzar dos fronteras diferentes: (1) entre divisiones '
              '<i>dentro</i> de la RFFM (la escalera habitual de ascenso/descenso descrita en cada tarjeta) y (2) la '
              'frontera entre la RFFM y la RFEF &mdash; cuando el campeón de la división superior de la RFFM en una '
              'categoría asciende a una competición que ya no organiza la RFFM, sino la federación española en su '
              'conjunto (Tercera RFEF, Liga Nacional Juvenil, Tercera Federación Femenina). La RFFM administra '
              'físicamente estas tres competiciones en su territorio (inscripciones, calendario, árbitros) &mdash; '
              'por eso siguen apareciendo en los datos recopilados por este proyecto &mdash; pero el derecho de '
              'ascenso/descenso desde ellas ya pertenece a la RFEF, no a la RFFM. Por eso en la tabla de niveles de '
              '<code>DIVISIONS.md</code> la nota de LIGA NACIONAL advierte «no confundir con el nivel regional» '
              '&mdash; es en realidad la base de la pirámide nacional, no la cima de la regional.',
    "how_p2": '<b>La «nueva Primera División Autonómica» de 2025/2026.</b> Para Juvenil, Cadete e Infantil, la '
              'circular oficial introduce explícitamente una nueva división entre Preferente y el siguiente nivel a '
              'partir de esta temporada &mdash; por eso parte de los ascensos de 2025/2026 no siguen la cadena '
              'vertical habitual, sino un play-off entre los campeones de grupo de Primera y la parte baja de la '
              'tabla de Preferente. Es una mecánica transitoria de la temporada de creación, no una regla '
              'permanente.',
    "how_p3": '<b>Por qué el calendario de abajo a veces tiene dos fases.</b> Muchas divisiones (sobre todo Fútbol '
              'Sala en categorías inferiores y Primera de Fútbol-11 Aficionado) disputan en la práctica dos torneos '
              'distintos dentro de la misma temporada: 1ª fase &mdash; liga normal (a menudo por proximidad '
              'geográfica, sin tener en cuenta el nivel), 2ª fase &mdash; los clubes se reagrupan según el '
              'coeficiente final de la 1ª fase en nuevos grupos, donde se deciden tanto el título como las plazas de '
              'ascenso; los puntos de la primera fase <i>no se arrastran</i>. No son dos competiciones distintas '
              '&mdash; es una sola escalera dividida en dos mitades de temporada.',
    "how_p4": '<b>Play-off / Torneo de Campeones &mdash; aparte de la escalera.</b> Tras la liga regular, muchas '
              'divisiones disputan un play-off corto entre los primeros de cada grupo (a veces llamado directamente '
              '«Torneo de Campeones» / «Copa de Campeones»), pero según el reglamento no mueve al equipo hacia '
              'arriba o abajo en la pirámide &mdash; es un trofeo aparte, por encima de los ascensos/descensos ya '
              'decididos. Este es justamente el patrón detrás de la «Copa de Campeones de Autonómica Juvenil» que '
              'parecía haber desaparecido: ver <code>DIVISIONS.md</code>, sección «The post-season phase pattern».',
    "how_p5": '<b>Fuentes.</b> Los ascensos/descensos de cada pirámide proceden de los documentos oficiales de la '
              'RFFM: «Bases de Ascensos y Descensos Competición Fútbol-11, temporada 2025-2026» (aprob. 10/07/2025), '
              '«Bases de Ascensos y Descensos Competición Fútbol-7» (aprob. 23/12/2024) y «Bases de Ascensos y '
              'Descensos Competición Fútbol Sala» (aprob. 23/12/2024), rffm.es. El calendario de fases está calculado '
              'a partir de <code>matches.csv</code> de la temporada recopilada por este proyecto; ver '
              '<code>DIVISIONS.md</code> para la tabla completa de niveles de <code>division_level</code> y '
              '<code>club_division_map.html</code> para saber exactamente quién juega dónde.',
    "strict_p1": '<b>El derecho de ascenso solo se pierde por un motivo &mdash; «filialidad/dependencia».</b> Un '
                 'club no puede tener dos de sus equipos en la misma división (en las categorías más jóvenes las '
                 'reglas son más laxas &mdash; en Primera Benjamín/Prebenjamín se permite más de un equipo del mismo '
                 'club en un grupo; ver «Disposiciones comunes» de cada documento). Si el equipo que ganó el ascenso '
                 'no puede subir por este motivo, el derecho pasa automáticamente al siguiente mejor clasificado '
                 '<i>de la misma división</i> que no tenga ese impedimento &mdash; la plaza no se pierde, se '
                 'desplaza hacia abajo en la tabla.',
    "strict_p2": '<b>El orden de desempate es rígido, no discrecional.</b> Cuando varios equipos compiten por la '
                 'misma plaza (por ejemplo, una vacante en la división superior que se abre después del 30 de '
                 'junio), la decisión sigue siempre la misma cadena formalizada: 1) puesto en la clasificación final '
                 'de su grupo; 2) coeficiente de puntos (puntos / partidos disputados &mdash; importante si los '
                 'grupos jugaron distinto número de jornadas); 3) diferencia general de goles en todos los partidos '
                 'de su grupo; 4) goles a favor (o coeficiente de goles a favor, si los grupos tienen distinto '
                 'tamaño); y solo si nada de esto decide &mdash; un partido de desempate en campo neutral, en la '
                 'fecha que designe la federación. Ningún documento deja aquí margen de discreción.',
    "strict_p3": '<b>Si dos equipos del mismo club se ganan el ascenso y solo hay una plaza</b> &mdash; sube el que '
                 'tenga mejor resultado deportivo según la misma cadena (coeficiente de puntos → diferencia de '
                 'goles → goles a favor), y al inicio de la siguiente temporada se reasignan las letras «A»/«B» de '
                 'los equipos de ese club: el que subió pasa a ser «A».',
    "strict_p4": '<b>«Arrastre» &mdash; el efecto de tirar hacia abajo por toda la cadena.</b> El número de '
                 'descensos anunciado en cada división es un <i>mínimo</i>, no una cifra definitiva. Si desciende '
                 'más equipos de los garantizados desde arriba (incluso desde la RFEF &mdash; por ejemplo, por una '
                 'mala temporada de los clubes madrileños en Segunda RFEF o Segunda Federación Femenina), el exceso '
                 '«arrastra» hacia abajo el mismo número de más en la división inferior, y así sucesivamente por '
                 'toda la pirámide &mdash; hasta Preferente/Primera. Los equipos descendidos precisamente por '
                 'arrastre, y no por su propia clasificación, tienen derecho preferente a ocupar las vacantes que '
                 'se abran en su antigua división la temporada siguiente.',
    "strict_p5": '<b>La temporada transitoria 2025/2026 &mdash; nuevas divisiones creadas «desde cero» dentro de una '
                 'pirámide ya existente.</b> Para Juvenil/Cadete/Infantil (Fútbol-11 y Sala) y Benjamín/Prebenjamín '
                 '(Fútbol-7), la RFFM inserta esta misma temporada un nuevo escalón superior (p. ej. «1ª División '
                 'Autonómica» o «División de Honor») entre divisiones ya existentes. Por eso parte de los ascensos '
                 'de 2025/2026 son excepcionales: por ejemplo, a la nueva División de Honor Benjamín ascendieron en '
                 'bloque los equipos del 1º al 6º puesto de cada grupo de Primera Autonómica 2024/2025 más los 4 '
                 'mejores séptimos por coeficiente &mdash; en vez del habitual «solo el campeón» o «play-off entre '
                 'el 1º y el 2º». Estas reglas transitorias están marcadas en las tarjetas con una nota en cursiva; '
                 'a partir de la siguiente temporada normalmente se sustituyen por una fórmula fija de «los N '
                 'mejores puestos ascienden directamente».',
    "strict_p6": '<b>Formato «sede» frente a «local-visitante».</b> En las divisiones superiores (Honor/Autonómica/'
                 'Preferente) los partidos casi siempre se juegan en el formato clásico de local y visitante; en '
                 'Primera y por debajo, muchas categorías inferiores juegan en formato «sede» &mdash; varios clubes '
                 'reciben por turnos toda una jornada completa en un mismo campo. Esto no afecta a los ascensos/'
                 'descensos, pero explica por qué en <code>club_division_map.html</code> un mismo club suele tener '
                 'varias sedes «locales» distintas en vez de una sola.',
    "footer": 'Construido a partir de <code>output/processed/rffm/{competitions,matches}.csv</code> (calendario de '
              'fases) y de las circulares oficiales de la RFFM (estructura de ascensos/descensos, cotejada a mano '
              '&mdash; no se extrae automáticamente del sitio web). Ver <code>analysis_scripts/competition_structure.py</code>.',
}

HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RFFM — структура соревнований</title>
%FONT_LINKS%
%THEME_INIT%
<style>
:root{
  --bg:#eef0ea; --surface:#ffffff; --ink:#1b2a1f; --ink-soft:#516155; --ink-faint:#8b9a8e;
  --accent:#2f6b3c; --accent-soft:#dce8dd; --gold:#8a6a12; --gold-soft:#f3e7c4;
  --line:#d7ddd2; --line-strong:#b9c4bb; --shadow: 0 1px 2px rgba(27,42,31,0.06);
  --teal:#1a6b7a; --teal-soft:#d8eef1; --rfef:#a03327; --rfef-soft:#f5ddd6;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#10160f; --surface:#171f16; --ink:#eef1ea; --ink-soft:#a9b6a8; --ink-faint:#6c796d;
    --accent:#74c47f; --accent-soft:#20301f; --gold:#d9b64a; --gold-soft:#332a10;
    --line:#2a352a; --line-strong:#3a473a; --shadow: 0 1px 3px rgba(0,0,0,0.4);
    --teal:#5fc3d6; --teal-soft:#12313a; --rfef:#e2685a; --rfef-soft:#33201d;
  }
}
:root[data-theme="dark"]{
  --bg:#10160f; --surface:#171f16; --ink:#eef1ea; --ink-soft:#a9b6a8; --ink-faint:#6c796d;
  --accent:#74c47f; --accent-soft:#20301f; --gold:#d9b64a; --gold-soft:#332a10;
  --line:#2a352a; --line-strong:#3a473a; --shadow: 0 1px 3px rgba(0,0,0,0.4);
  --teal:#5fc3d6; --teal-soft:#12313a; --rfef:#e2685a; --rfef-soft:#33201d;
}
:root[data-theme="light"]{
  --bg:#eef0ea; --surface:#ffffff; --ink:#1b2a1f; --ink-soft:#516155; --ink-faint:#8b9a8e;
  --accent:#2f6b3c; --accent-soft:#dce8dd; --gold:#8a6a12; --gold-soft:#f3e7c4;
  --line:#d7ddd2; --line-strong:#b9c4bb; --shadow: 0 1px 2px rgba(27,42,31,0.06);
  --teal:#1a6b7a; --teal-soft:#d8eef1; --rfef:#a03327; --rfef-soft:#f5ddd6;
}
*{box-sizing:border-box;}
html,body{margin:0;}
body{ background:var(--bg); color:var(--ink); font-family:'PT Sans', ui-sans-serif, "Helvetica Neue", Arial, sans-serif;
  line-height:1.5; -webkit-font-smoothing:antialiased; }
a{ color:var(--accent); text-decoration:none; } a:hover{ text-decoration:underline; }
.page{ max-width:1280px; margin:0 auto; padding:2.25rem 1.25rem 4rem; display:flex; flex-direction:column; gap:1.75rem; }
h1{ font-family:'Oswald', ui-sans-serif, "Arial Narrow", "Helvetica Neue", Arial, sans-serif; font-weight:700;
  text-transform:uppercase; letter-spacing:0.01em; text-wrap:balance; margin:0; color:var(--ink); font-size:clamp(1.4rem,2.8vw,1.9rem); line-height:1.2; }
header.masthead{display:flex; flex-direction:column; gap:0.4rem; border-bottom:3px solid var(--ink); padding-bottom:1rem; position:relative;}
.eyebrow{ font-family:'JetBrains Mono',monospace; font-size:0.72rem; font-weight:700; letter-spacing:0.14em; text-transform:uppercase; color:var(--accent); }
.masthead p{margin:0; color:var(--ink-soft); font-size:0.95rem; max-width:76ch;}
a.back{font-family:'JetBrains Mono',monospace; font-size:0.8rem; color:var(--accent); text-decoration:none;}
a.back:hover{text-decoration:underline;}
.masthead .switch-row{position:absolute; top:0; right:0; display:flex; gap:0.5rem;}
.lang-switch, .theme-switch{ display:inline-flex; border:1px solid var(--line-strong); border-radius:999px; overflow:hidden; }
.lang-opt, .theme-opt{ font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:700; letter-spacing:0.04em;
  padding:4px 12px; background:var(--surface); color:var(--ink-soft); border:none; cursor:pointer; }
.lang-opt.is-active, .theme-opt.is-active{background:var(--accent); color:#fff;}
.theme-opt{font-size:13px; padding:3px 10px;}

.legend-panel{ background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:1rem 1.2rem;
  box-shadow:var(--shadow); display:flex; flex-wrap:wrap; gap:1.1rem; align-items:center; font-size:0.82rem; color:var(--ink-soft); }
.legend-panel b{color:var(--ink);}
.leg-swatch{display:inline-block; width:0.85rem; height:0.85rem; border-radius:3px; margin-right:0.3rem; vertical-align:-1px;}
.leg-rfef{background:var(--rfef-soft); box-shadow:inset 0 0 0 1.5px var(--rfef);}
.leg-rffm{background:var(--accent-soft); box-shadow:inset 0 0 0 1.5px var(--accent);}
.leg-liga{background:var(--accent);} .leg-fase2{background:var(--teal);} .leg-playoff{background:var(--gold);}

.filter-panel{ display:flex; flex-wrap:wrap; gap:0.4rem; }
.filter-panel button{ font-family:'JetBrains Mono',monospace; font-size:0.78rem; font-weight:700; color:var(--ink-soft);
  background:var(--surface); border:1.5px solid var(--line-strong); border-radius:999px; padding:0.4rem 0.9rem; cursor:pointer; }
.filter-panel button.active{ background:var(--accent); border-color:var(--accent); color:#fff; }
.filter-panel button:hover:not(.active){ border-color:var(--accent); color:var(--ink); }

.pyramid-grid{ display:grid; grid-template-columns:repeat(auto-fill, minmax(320px, 1fr)); gap:1.1rem; }
.pyramid-card{ background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:1.1rem 1.2rem 0.9rem;
  box-shadow:var(--shadow); display:flex; flex-direction:column; gap:0.7rem; }
.pyramid-card h3{ font-family:'Oswald',sans-serif; font-weight:700; text-transform:uppercase; font-size:0.92rem; margin:0; color:var(--ink); }
.pyramid-ladder{ display:flex; flex-direction:column; }
.tier{ border-radius:6px; padding:0.55rem 0.7rem; font-size:0.78rem; }
.tier.org-rffm{ background:var(--accent-soft); box-shadow:inset 0 0 0 1px var(--accent); }
.tier.org-rfef{ background:var(--rfef-soft); box-shadow:inset 0 0 0 1px var(--rfef); }
.tier-head{ display:flex; align-items:center; gap:0.4rem; flex-wrap:wrap; }
.tier-name{ font-weight:700; color:var(--ink); }
.tier-org{ font-family:'JetBrains Mono',monospace; font-size:0.64rem; font-weight:700; letter-spacing:0.04em;
  padding:0.05rem 0.4rem; border-radius:3px; background:var(--surface); color:var(--ink-soft); }
.admin-badge{ font-size:0.64rem; color:var(--ink-faint); font-style:italic; }
.tier-scope{ color:var(--ink-soft); font-size:0.72rem; margin-top:0.15rem; }
.tier-line{ margin-top:0.3rem; display:flex; gap:0.35rem; align-items:baseline; color:var(--ink); font-size:0.74rem; }
.tier-arrow{ flex:none; font-weight:700; }
.tier-arrow.up{ color:var(--accent); } .tier-arrow.down{ color:var(--rfef); }
.tier-note{ margin-top:0.3rem; font-size:0.7rem; color:var(--ink-faint); font-style:italic; }
.tier-examples{ margin-top:0.35rem; padding-top:0.3rem; border-top:1px dashed var(--line-strong);
  display:flex; flex-wrap:wrap; gap:0.3rem; align-items:center; }
.ex-label{ font-family:'JetBrains Mono',monospace; font-size:0.6rem; font-weight:700; color:var(--ink-faint); margin-right:0.1rem; }
.ex-chip{ font-family:'JetBrains Mono',monospace; font-size:0.62rem; color:var(--ink); background:var(--surface);
  border:1px solid var(--line-strong); border-radius:3px; padding:0.08rem 0.35rem; }
.tier-connector{ height:0.9rem; width:2px; background:var(--line-strong); margin:0.1rem auto; }
.single-note{ font-size:0.78rem; color:var(--ink-soft); }
.pyramid-timing{ border-top:1px dashed var(--line); padding-top:0.5rem; }
.tl-months{ display:grid; grid-template-columns:repeat(10,1fr); font-family:'JetBrains Mono',monospace;
  font-size:0.6rem; color:var(--ink-faint); text-align:center; margin-bottom:0.2rem; }
.tl-row{ display:grid; grid-template-columns:repeat(10,1fr); gap:2px; }
.tl-cell{ height:0.85rem; border-radius:2px; background:var(--line); }
.tl-cell.tl-off{ background:var(--line); opacity:0.35; }
.tl-cell.tl-liga{ background:var(--accent); }
.tl-cell.tl-fase2{ background:var(--teal); }
.tl-cell.tl-playoff{ background:var(--gold); }
.tl-empty{ font-size:0.72rem; color:var(--ink-faint); }
.pyramid-src{ font-size:0.62rem; color:var(--ink-faint); border-top:1px dashed var(--line); padding-top:0.4rem; }

.info-panel{ background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:1.1rem 1.3rem;
  box-shadow:var(--shadow); font-size:0.85rem; color:var(--ink-soft); }
.info-panel h2{ font-family:'Oswald',sans-serif; font-weight:700; text-transform:uppercase; font-size:1.05rem;
  color:var(--ink); margin:0 0 0.6rem; }
.info-panel p{ margin:0 0 0.7rem; }
.info-panel p:last-child{margin-bottom:0;}
.info-panel code{ font-family:ui-monospace,monospace; font-size:0.86em; background:var(--accent-soft); padding:0.05em 0.35em; border-radius:3px; color:var(--ink); }
.section-h{ display:flex; align-items:baseline; gap:0.6rem; }
.section-h h2{ font-family:'Oswald',sans-serif; font-weight:700; text-transform:uppercase; font-size:1.15rem; color:var(--ink); margin:0; }
.section-h .n{ font-family:'JetBrains Mono',monospace; color:var(--accent); font-size:0.78rem; font-weight:700; }
footer.note{font-size:0.78rem; color:var(--ink-soft); max-width:90ch;}
</style>
</head>
<body>
<div class="page">
  <header class="masthead">
    %SWITCH_ROW%
    <a class="back" href="index.html">&larr; RFFM data</a>
    <span class="eyebrow" data-i18n="eyebrow">RFFM (Мадрид) &middot; структура соревнований</span>
    <h1 data-i18n="h1">Пирамида лиг RFFM: категории, дивизионы, переходы</h1>
    <p data-i18n="lede">Для каждого возраста / типа игры / пола &mdash; полная лестница дивизионов сверху вниз: сколько команд/групп
      в каждом дивизионе, сколько переходит вверх и вниз между соседями, и где лестница выходит за пределы RFFM
      в общенациональные соревнования RFEF (Tercera RFEF, Liga Nacional Juvenil, Tercera Federación Femenina).
      Правила переходов взяты из официальных circular RFFM «Bases de Ascensos y Descensos» (сезон 2025-2026,
      см. подпись под каждой карточкой); календарь фаз внизу каждой карточки посчитан из реальных дат матчей
      в собранных данных, а не переписан вручную.</p>
  </header>

  <div class="legend-panel">
    <span data-i18n="leg1"><span class="leg-swatch leg-rffm"></span><b>RFFM</b> &mdash; региональное соревнование</span>
    <span data-i18n="leg2"><span class="leg-swatch leg-rfef"></span><b>RFEF</b> &mdash; общенациональное (может администрироваться RFFM на своей территории)</span>
    <span data-i18n="leg3"><span class="leg-swatch leg-liga"></span>регулярный чемпионат</span>
    <span data-i18n="leg4"><span class="leg-swatch leg-fase2"></span>2-й этап (группы по уровню)</span>
    <span data-i18n="leg5"><span class="leg-swatch leg-playoff"></span>плей-офф / Torneo de Campeones</span>
  </div>

  <div class="filter-panel" id="filterPanel"></div>

  <div class="pyramid-grid" id="pyramidGrid"></div>

  <section>
    <div class="section-h"><h2 data-i18n="h_single">Прочие категории Fútbol Sala без пирамиды</h2>
      <span class="n" data-i18n="h_single_n">единственный дивизион, ascenso/descenso не предусмотрены</span></div>
    <p style="color:var(--ink-soft); font-size:0.85rem; max-width:80ch;" data-i18n="single_p">
      Prebenjamín/Benjamín/Alevín (мужской) и вся линейка Juvenil&ndash;Benjamín (женский) Fútbol Sala играют
      в РФФМ одним дивизионом на возраст &mdash; повышений/понижений нет вовсе, а внутригодовая структура
      реализуется через двухфазный формат (1-я фаза &mdash; лига по территориальной близости, 2-я фаза &mdash;
      перегруппировка по уровню для розыгрыша титула и остальных мест).
    </p>
    <div class="pyramid-grid" id="singleGrid"></div>
  </section>

  <section>
    <div class="section-h"><h2 data-i18n="h_how">Как это устроено</h2></div>
    <div class="info-panel">
      <p data-i18n="how_p1"><b>Два раздельных пограничных перехода.</b> Клуб может пересечь две разные границы: (1) между дивизионами
        <i>внутри</i> RFFM (обычная ladder ascenso/descenso, описанная в каждой карточке) и (2) границу между
        RFFM и RFEF &mdash; когда чемпион верхнего RFFM-дивизиона какой-то категории поднимается в соревнование,
        которое организует уже не RFFM, а испанская федерация целиком (Tercera RFEF, Liga Nacional Juvenil,
        Tercera Federación Femenina). RFFM физически администрирует эти три соревнования на своей территории
        (заявки, календарь, судьи) &mdash; поэтому они всё ещё попадают в собранные этим проектом данные &mdash;
        но право повышения/понижения из них принадлежит уже RFEF, а не RFFM. Именно поэтому в тарифной таблице
        <code>DIVISIONS.md</code> для LIGA NACIONAL стоит замечание «не путать с региональным уровнем» &mdash;
        это фактически низ национальной пирамиды, а не верх региональной.</p>
      <p data-i18n="how_p2"><b>«Новая Primera División Autonómica» 2025/2026.</b> Для Juvenil, Cadete и Infantil официальный circular
        явно вводит новый дивизион между Preferente и следующим уровнем начиная с этого сезона &mdash; поэтому
        часть переходов в 2025/2026 идёт не по обычной вертикальной цепочке, а через play-off между чемпионами
        групп Primera и нижней частью таблицы Preferente. Это разовая переходная механика сезона запуска, а не
        постоянное правило.</p>
      <p data-i18n="how_p3"><b>Почему в календаре снизу бывает две фазы.</b> Многие дивизионы (особенно Fútbol Sala младших
        категорий и Primera Fútbol-11 Aficionado) физически играют два разных турнира подряд в рамках одного
        сезона: 1-я фаза &mdash; обычная лига (часто по территориальной близости, без учёта силы), 2-я фаза
        &mdash; клубы перегруппированы по итоговому коэффициенту 1-й фазы в новые группы, где и разыгрываются
        и титул, и путёвки на повышение; очки первой фазы <i>не переносятся</i>. Это не два отдельных
        соревнования &mdash; это одна лестница, поделённая на два тайма сезона.</p>
      <p data-i18n="how_p4"><b>Плей-офф / Torneo de Campeones — отдельно от ladder.</b> После регулярного чемпионата многие дивизионы
        разыгрывают короткий плей-офф между призёрами групп (иногда прямо называется «Torneo de Campeones» /
        «Copa de Campeones»), но по регламенту он не двигает команду вверх или вниз по пирамиде &mdash; это отдельный
        трофей поверх уже определившихся ascenso/descenso. Именно этот паттерн стоит за пропавшей из вида
        «Copa de Campeones de Autonómica Juvenil»: см. <code>DIVISIONS.md</code>, раздел «The post-season phase pattern».</p>
      <p data-i18n="how_p5"><b>Источники.</b> Промо/вылет по каждой пирамиде &mdash; из официальных документов RFFM: «Bases de Ascensos
        y Descensos Competición Fútbol-11, temporada 2025-2026» (утв. 10.07.2025), «Bases de Ascensos y Descensos
        Competición Fútbol-7» (утв. 23.12.2024) и «Bases de Ascensos y Descensos Competición Fútbol Sala»
        (утв. 23.12.2024), rffm.es. Календарь фаз &mdash; посчитан из
        <code>matches.csv</code> собранного этим проектом сезона; см. <code>DIVISIONS.md</code> для полной
        тарифной таблицы <code>division_level</code> и <code>club_division_map.html</code> для того, кто конкретно
        где играет.</p>
    </div>
  </section>

  <section>
    <div class="section-h"><h2 data-i18n="h_strict">Насколько строги правила перехода</h2>
      <span class="n" data-i18n="h_strict_n">механика между сезонами, а не общие принципы</span></div>
    <div class="info-panel">
      <p data-i18n="strict_p1"><b>Право на повышение теряется только по одной причине &mdash; «filialidad/dependencia».</b> Клуб не может
        держать два своих состава в одном дивизионе (для младших возрастов правила мягче &mdash; в Primera
        Benjamín/Prebenjamín допускается больше одной команды клуба в группе, см. «Disposiciones comunes» каждого
        документа). Если победившая команда не может подняться из-за этого, право автоматически переходит к
        следующей по итоговой таблице команде <i>того же дивизиона</i>, у которой такого препятствия нет &mdash;
        вакансия не «сгорает», а сдвигается вниз по таблице.</p>
      <p data-i18n="strict_p2"><b>Порядок разрешения равенства &mdash; жёсткий, не на усмотрение комитета.</b> Когда несколько команд
        претендуют на одну и ту же путёвку (например, вакансию в дивизионе выше, открывшуюся после 30 июня), решение
        всегда идёт по одной и той же формализованной цепочке: 1) место в итоговой таблице своей группы; 2)
        коэффициент очков (очки / сыгранные матчи &mdash; важно, если группы играли разное число туров);
        3) общая разница мячей по всем матчам своей группы; 4) число забитых мячей (или коэффициент забитых
        голов, если группы разного размера); и только если ничего из этого не развело команды &mdash; очная
        переигровка на нейтральном поле в дату, которую назначит федерация. Ни один документ не оставляет здесь
        пространства для дискреции.</p>
      <p data-i18n="strict_p3"><b>Если у клуба сразу два состава заслужили повышение, а слот один</b> &mdash; поднимается тот, что показал
        лучший спортивный результат по той же цепочке (коэффициент очков → разница мячей → голы забитые), и с
        начала следующего сезона буквы «A»/«B» у команд этого клуба переприсваиваются: та, что поднялась,
        становится «A».</p>
      <p data-i18n="strict_p4"><b>«Arrastre» &mdash; эффект вытягивания вниз по всей цепочке.</b> Объявленное число вылетающих команд в
        каждом дивизионе &mdash; это <i>минимум</i>, а не окончательная цифра. Если сверху (вплоть до RFEF &mdash;
        например, из-за плохого сезона мадридских клубов в Segunda RFEF или Segunda Federación Femenina) вылетело
        больше команд, чем гарантированно предусмотрено, избыток «утягивает» на один дивизион ниже ровно на столько
        же команд больше заявленного, и так далее вниз по всей пирамиде &mdash; вплоть до Preferente/Primera. Команды,
        вылетевшие именно из-за arrastre, а не по итогам своей таблицы, получают приоритетное право занять вакансии
        в своём прежнем дивизионе в следующем сезоне, если такие откроются.</p>
      <p data-i18n="strict_p5"><b>Транзитный сезон 2025/2026 &mdash; новые дивизионы создаются «с нуля» внутри уже существующей пирамиды.</b>
        Для Juvenil/Cadete/Infantil (Fútbol-11 и Sala) и Benjamín/Prebenjamín (Fútbol-7) РФФМ прямо в этом сезоне
        вставляет новую верхнюю ступень (напр. «1ª División Autonómica» или «División de Honor») между уже
        существующими дивизионами. Из-за этого часть переходов 2025/2026 &mdash; разовые: например, в новую
        División de Honor Benjamín целиком поднялись команды с 1-го по 6-е места каждой группы Primera Autonómica
        2024/2025 плюс 4 лучших седьмых места по коэффициенту &mdash; вместо обычных «только чемпион» или
        «плей-офф 1-2 места». Такие переходные правила отмечены в карточках отдельной пометкой курсивом; со
        следующего сезона они, как правило, заменяются на постоянную формулу «N лучших мест напрямую».</p>
      <p data-i18n="strict_p6"><b>Формат «sede» против «local-visitante».</b> В верхних дивизионах (Honor/Autonómica/Preferente) матчи
        почти всегда играются классическим «дома-в гостях»; в Primera и ниже многие младшие категории играют в
        формате «sede» &mdash; несколько клубов по очереди принимают весь тур целиком на одном поле. На ascenso/
        descenso это не влияет, но объясняет, почему в <code>club_division_map.html</code> у одного клуба часто
        оказывается несколько разных «домашних» площадок вместо одной.</p>
    </div>
  </section>

  <footer class="note" data-i18n="footer">Построено из <code>output/processed/rffm/{competitions,matches}.csv</code> (календарь фаз) и
    официальных circular RFFM (структура ascenso/descenso, вручную сверена — не парсится автоматически из сайта).
    См. <code>analysis_scripts/competition_structure.py</code>.</footer>
</div>
<script>
const PYRAMID_GROUPS = %PYRAMID_GROUPS_JSON%;
const PYRAMID_HTML = %PYRAMID_HTML_JSON%;
const SINGLE_HTML = %SINGLE_HTML_JSON%;

document.getElementById('pyramidGrid').innerHTML = PYRAMID_HTML;
document.getElementById('singleGrid').innerHTML = SINGLE_HTML;

const panel = document.getElementById('filterPanel');
let active = null;
PYRAMID_GROUPS.forEach(([key, label]) => {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.textContent = label;
  btn.addEventListener('click', () => {
    active = active === key ? null : key;
    [...panel.children].forEach(b => b.classList.toggle('active', b === btn && active));
    document.querySelectorAll('#pyramidGrid .pyramid-card').forEach(card => {
      card.classList.toggle('hidden', active && card.dataset.group !== active);
    });
  });
  panel.appendChild(btn);
});

(function () {
  var I18N_ES = %I18N_ES_JSON%;
  %LANG_SWITCH_JS%
})();
</script>
<style>.hidden{display:none !important;}</style>
%THEME_SWITCH_JS_TAG%
</body>
</html>
"""


def build_html(season: str) -> str:
    timing = compute_timing(season)
    examples_idx = build_examples_index(season)
    pyramid_html = "".join(pyramid_card_html(p, timing, examples_idx, season) for p in ALL_PYRAMIDS)
    single_html = "".join(
        single_division_card_html(cat, title, scope, timing, "fsm", is_fem=False)
        for cat, title, scope in SINGLE_DIVISION_FS
    ) + "".join(
        single_division_card_html(cat, title, scope, timing, "fsf", is_fem=True)
        for cat, title, scope in SINGLE_DIVISION_FS_FEM
    )
    theme_switch_tag = f"<script>{THEME_SWITCH_JS}</script>"
    return (HTML
            .replace("%FONT_LINKS%", FONT_LINKS)
            .replace("%THEME_INIT%", THEME_INIT_JS)
            .replace("%SWITCH_ROW%", switch_row_html())
            .replace("%PYRAMID_GROUPS_JSON%", json.dumps(GROUP_LABELS, ensure_ascii=False))
            .replace("%PYRAMID_HTML_JSON%", json.dumps(pyramid_html, ensure_ascii=False))
            .replace("%SINGLE_HTML_JSON%", json.dumps(single_html, ensure_ascii=False))
            .replace("%I18N_ES_JSON%", json.dumps(I18N_ES, ensure_ascii=False))
            .replace("%LANG_SWITCH_JS%", LANG_SWITCH_JS)
            .replace("%THEME_SWITCH_JS_TAG%", theme_switch_tag))


def main():
    parser = argparse.ArgumentParser(description="RFFM competition-structure ('league pyramid') report")
    parser.add_argument("--season", default=None, help="season to compute the phase-timing calendar from (default: latest complete core crawl)")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()

    season = args.season or list_seasons()[-1]
    build_all(Path(__file__).parent.parent / args.output_dir, season)


def build_all(out_dir: Path, season: str | None = None) -> None:
    season = season or list_seasons()[-1]
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Building competition_structure.html (phase timing from season {season})")
    (out_dir / "competition_structure.html").write_text(build_html(season), encoding="utf-8")
    print(f"Report written to {out_dir / 'competition_structure.html'}")


if __name__ == "__main__":
    main()
