import duckdb, json
from collections import Counter
con = duckdb.connect()
PARQUET = 'output/processed/rffm_parquet'
names = ('ARAVACA C.F.', 'ARAVACA C.F. - Bhhs Spain', 'ARAVACA C.F. - BHHS SPAIN', 'ARAVACA C.F. - Bhhs Spain ', 'ARAVACA C.F. - CEIBA')

SEASONS = ['2021-2022', '2022-2023', '2023-2024', '2024-2025', '2025-2026']
PIVOT_BIRTH_YEARS = (2014, 2015)  # superset covering all 3 client-selectable pivots
MIN_APPS = 4

CATEGORY_ORDER = ['PREBENJAMIN', 'BENJAMIN', 'ALEVIN', 'INFANTIL', 'CADETE', 'JUVENIL', 'AFICIONADO']
CAT_ORDINAL = {c: i for i, c in enumerate(CATEGORY_ORDER)}

TIER = {
    'SUPERLIGA': 1, 'LIGA NACIONAL': 1, 'DIVISION DE HONOR': 2, 'PRIMERA DIVISION AUTONOMICA': 3,
    'PREFERENTE': 4, 'SEGUNDA DIVISION B': 5, 'TERCERA FEDERACION': 5, 'PRIMERA': 6, 'SEGUNDA': 7,
    'TERCERA': 8, 'FASE ZONAL': 9, 'OTHER': 9,
}
TIER_BAND = {1: 0, 2: 1, 3: 2, 4: 3, 6: 4, 7: 5}


def get_team_meta_bulk(season):
    """All Aravaca teams that season, any category - team_id -> meta."""
    df = con.execute(f'''
    SELECT DISTINCT t.team_id, t.team, c.division_level, c.game_type, c.category_base
    FROM read_parquet('{PARQUET}/teams/{season}.parquet') t
    JOIN read_parquet('{PARQUET}/team_group_membership/{season}.parquet') m ON t.team_id = m.team_id
    JOIN read_parquet('{PARQUET}/groups/{season}.parquet') g ON m.group_id = g.group_id
    JOIN read_parquet('{PARQUET}/competitions/{season}.parquet') c ON g.competition_id = c.competition_id
    WHERE t.club_name_raw IN {names} AND c.phase_label = 'regular_season'
    ORDER BY t.team
    ''').df()
    best = {}
    for _, r in df.iterrows():
        tier = TIER.get(r['division_level'], 9)
        tid = int(r['team_id'])
        if tid not in best or tier < best[tid]['tier']:
            best[tid] = {'team_id': tid, 'team': r['team'], 'division_level': r['division_level'],
                         'tier': tier, 'game_type': r['game_type'], 'category_base': r['category_base']}
    return best


def letter_of(team_name):
    return team_name.strip().split()[-1]


def best_split(seq):
    n = len(seq)
    if len(set(seq)) < 2:
        return None
    early_team = seq[0]
    c = Counter(seq)
    late_candidates = [t for t in c if t != early_team]
    late_team = max(late_candidates, key=lambda t: c[t])
    best = None
    for k in range(1, n):
        left, right = seq[:k], seq[k:]
        if len(left) < MIN_APPS or len(right) < MIN_APPS:
            continue
        errors = sum(1 for x in left if x != early_team) + sum(1 for x in right if x != late_team)
        rate = errors / n
        if best is None or rate < best[0]:
            best = (rate, k)
    if best is None:
        return None
    rate, k = best
    return {'early': int(early_team), 'late': int(late_team), 'rate': rate, 'split_idx': k,
            'n_early': c[early_team], 'n_late': c[late_team]}


def pd_isna(x):
    try:
        return x != x
    except Exception:
        return x is None


def stats_for(df_lineups, df_goals, pid, team_id, date_lo=None, date_hi=None):
    sub = df_lineups[(df_lineups['player_id'] == pid) & (df_lineups['team_id'] == team_id)]
    if date_lo is not None:
        sub = sub[sub['match_date'] >= date_lo]
    if date_hi is not None:
        sub = sub[sub['match_date'] < date_hi]
    apps = len(sub)
    cap = bool(sub['is_captain'].any())
    gk = bool(sub['is_goalkeeper'].any())
    gsub = df_goals[(df_goals['player_id'] == pid) & (df_goals['team_id'] == team_id)]
    if date_lo is not None:
        gsub = gsub[gsub['match_date'] >= date_lo]
    if date_hi is not None:
        gsub = gsub[gsub['match_date'] < date_hi]
    goals = len(gsub)
    return apps, goals, cap, gk


# ---------- load per-season lineup+goal rows, filtered to the pivot birth years ----------
season_df, goals_df, team_meta = [], [], []
for season in SEASONS:
    df = con.execute(f'''
    SELECT ml.player_id, ml.team_id, m.match_date, ml.is_captain, ml.is_goalkeeper,
           p.player_name, p.birth_year
    FROM read_parquet('{PARQUET}/match_lineups/{season}.parquet') ml
    JOIN read_parquet('{PARQUET}/teams/{season}.parquet') t ON ml.team_id = t.team_id
    JOIN read_parquet('{PARQUET}/matches/{season}.parquet') m ON ml.match_id = m.match_id
    LEFT JOIN read_parquet('{PARQUET}/players.parquet') p ON ml.player_id = p.player_id
    WHERE t.club_name_raw IN {names} AND p.birth_year IN {PIVOT_BIRTH_YEARS}
    ORDER BY ml.player_id, m.match_date
    ''').df()
    df['player_id'] = df['player_id'].astype(int)
    df['team_id'] = df['team_id'].astype(int)
    df['match_date'] = df['match_date'].astype(str)
    df['is_captain'] = df['is_captain'].astype(str) == 'True'
    df['is_goalkeeper'] = df['is_goalkeeper'].astype(str) == 'True'
    season_df.append(df)

    gdf = con.execute(f'''
    SELECT mg.player_id, mg.team_id, m.match_date
    FROM read_parquet('{PARQUET}/match_goals/{season}.parquet') mg
    JOIN read_parquet('{PARQUET}/teams/{season}.parquet') t ON mg.team_id = t.team_id
    JOIN read_parquet('{PARQUET}/matches/{season}.parquet') m ON mg.match_id = m.match_id
    LEFT JOIN read_parquet('{PARQUET}/players.parquet') p ON mg.player_id = p.player_id
    WHERE t.club_name_raw IN {names} AND p.birth_year IN {PIVOT_BIRTH_YEARS}
    ''').df()
    gdf['player_id'] = gdf['player_id'].astype(int)
    gdf['team_id'] = gdf['team_id'].astype(int)
    gdf['match_date'] = gdf['match_date'].astype(str)
    goals_df.append(gdf)

    team_meta.append(get_team_meta_bulk(season))
    print(season, 'lineup rows:', len(df), 'distinct players:', df['player_id'].nunique(), 'Aravaca teams:', len(team_meta[-1]), flush=True)

# ---------- classify each player-season (majority team, or genuine intra-season transfer) ----------
classification = []
meta_by_season = []
intra_transfers_out = []
for si, season in enumerate(SEASONS):
    df = season_df[si]
    result, meta = {}, {}
    for pid, g in df.groupby('player_id'):
        meta[pid] = {
            'name': g['player_name'].iloc[0],
            'birth_year': None if pd_isna(g['birth_year'].iloc[0]) else int(g['birth_year'].iloc[0]),
        }
        teams_seq = list(g['team_id'])
        counts = Counter(teams_seq)
        qualifying = {t: n for t, n in counts.items() if n >= MIN_APPS}
        if not qualifying:
            majority = counts.most_common(1)[0][0]
            result[pid] = {'start_team': int(majority), 'end_team': int(majority), 'transfer': None}
            continue
        if len(qualifying) == 1:
            t = list(qualifying.keys())[0]
            result[pid] = {'start_team': int(t), 'end_team': int(t), 'transfer': None}
            continue
        split = best_split(teams_seq)
        if split and split['rate'] <= 0.15 and split['n_early'] >= MIN_APPS and split['n_late'] >= MIN_APPS \
           and split['early'] in qualifying and split['late'] in qualifying:
            split_date = list(g['match_date'])[split['split_idx']]
            result[pid] = {'start_team': split['early'], 'end_team': split['late'],
                            'transfer': {'from': split['early'], 'to': split['late'], 'date': split_date}}
            intra_transfers_out.append({'player_id': int(pid), 'season': season,
                                         'from': str(split['early']), 'to': str(split['late']), 'date': split_date})
        else:
            majority = max(qualifying, key=lambda t: qualifying[t])
            result[pid] = {'start_team': int(majority), 'end_team': int(majority), 'transfer': None}
    classification.append(result)
    meta_by_season.append(meta)

n_transfers = sum(1 for r in classification for v in r.values() if v['transfer'])
print(f'intra-season transfers detected: {n_transfers}')

# ---------- build stations (one per real Aravaca team_id that season with >=1 qualifying pivot-birth-year player) ----------
stations_out = []
for si, season in enumerate(SEASONS):
    cls = classification[si]
    meta = meta_by_season[si]
    df_lineups, df_goals = season_df[si], goals_df[si]
    tmeta = team_meta[si]

    roster_by_team = {}
    for pid, c in cls.items():
        if pid not in meta:
            continue
        m = meta[pid]
        if c['transfer']:
            tr = c['transfer']
            if tr['from'] in tmeta:
                apps, goals, cap, gk = stats_for(df_lineups, df_goals, pid, tr['from'], date_hi=tr['date'])
                roster_by_team.setdefault(tr['from'], []).append({
                    'player_id': int(pid), 'name': m['name'], 'birth_year': m['birth_year'],
                    'is_gk': gk, 'is_cap': cap, 'apps': apps, 'goals': goals, 'transfer_role': 'before',
                })
            if tr['to'] in tmeta:
                apps, goals, cap, gk = stats_for(df_lineups, df_goals, pid, tr['to'], date_lo=tr['date'])
                roster_by_team.setdefault(tr['to'], []).append({
                    'player_id': int(pid), 'name': m['name'], 'birth_year': m['birth_year'],
                    'is_gk': gk, 'is_cap': cap, 'apps': apps, 'goals': goals, 'transfer_role': 'after',
                })
        else:
            t = c['start_team']
            if t in tmeta:
                apps, goals, cap, gk = stats_for(df_lineups, df_goals, pid, t)
                roster_by_team.setdefault(t, []).append({
                    'player_id': int(pid), 'name': m['name'], 'birth_year': m['birth_year'],
                    'is_gk': gk, 'is_cap': cap, 'apps': apps, 'goals': goals, 'transfer_role': None,
                })

    for team_id, roster in roster_by_team.items():
        tm = tmeta[team_id]
        stations_out.append({
            'season': season, 'team_id': team_id, 'team': tm['team'], 'letter': letter_of(tm['team']),
            'division_level': tm['division_level'], 'category_base': tm['category_base'],
            'game_type': tm['game_type'], 'tier': tm['tier'],
            'roster': sorted(roster, key=lambda r: -r['goals']),
        })

raw = {'seasons': SEASONS, 'pivot_birth_years': list(PIVOT_BIRTH_YEARS), 'stations': stations_out}
OUT = 'notebooks/aravaca_metro/metro_raw_v3.json'
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(raw, f, ensure_ascii=False)
with open('notebooks/aravaca_metro/intra_transfers_v3.json', 'w', encoding='utf-8') as f:
    json.dump(intra_transfers_out, f, ensure_ascii=False)

for season in SEASONS:
    ss = [s for s in stations_out if s['season'] == season]
    cats = Counter(s['category_base'] for s in ss)
    print(season, 'stations:', len(ss), 'by category:', dict(cats), 'roster rows:', sum(len(s['roster']) for s in ss))
print('total stations:', len(stations_out), 'total roster rows:', sum(len(s['roster']) for s in stations_out))
