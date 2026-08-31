import duckdb, json
con = duckdb.connect()
PARQUET = 'output/processed/rffm_parquet'
names = ('ARAVACA C.F.', 'ARAVACA C.F. - Bhhs Spain', 'ARAVACA C.F. - BHHS SPAIN', 'ARAVACA C.F. - Bhhs Spain ', 'ARAVACA C.F. - CEIBA')

raw = json.load(open('notebooks/aravaca_metro/metro_raw_v3.json', encoding='utf-8'))
seasons = raw['seasons']

# for each season, player_id -> {'start': team_id, 'end': team_id}
per_season = []
for season in seasons:
    d = {}
    for t in raw['stations']:
        if t['season'] != season:
            continue
        for r in t['roster']:
            pid = r['player_id']
            role = r.get('transfer_role')
            entry = d.setdefault(pid, {'start': None, 'end': None})
            if role == 'before':
                entry['start'] = t['team_id']
            elif role == 'after':
                entry['end'] = t['team_id']
            else:
                entry['start'] = t['team_id']
                entry['end'] = t['team_id']
    per_season.append(d)


def find_elsewhere(player_id, season):
    df = con.execute(f'''
    SELECT DISTINCT t.club_name_raw
    FROM read_parquet('{PARQUET}/match_lineups/{season}.parquet') ml
    JOIN read_parquet('{PARQUET}/teams/{season}.parquet') t ON ml.team_id = t.team_id
    WHERE ml.player_id = {player_id} AND t.club_name_raw NOT IN {names}
    LIMIT 1
    ''').df()
    return df.iloc[0]['club_name_raw'] if len(df) else None


links, exits, entries = [], [], []
for i, season in enumerate(seasons):
    cur = per_season[i]
    prev = per_season[i - 1] if i > 0 else None
    nxt = per_season[i + 1] if i < len(seasons) - 1 else None
    for pid, cs in cur.items():
        if nxt is not None:
            if pid in nxt:
                links.append({'player_id': pid, 'from_season': season, 'from_team': cs['end'],
                              'to_season': seasons[i + 1], 'to_team': nxt[pid]['start']})
            else:
                dest = find_elsewhere(pid, seasons[i + 1])
                exits.append({'player_id': pid, 'season': season, 'team_id': cs['end'],
                              'kind': 'left_to_club' if dest else 'vanished', 'dest_club': dest})
        if prev is not None and pid not in prev:
            origin = find_elsewhere(pid, seasons[i - 1])
            entries.append({'player_id': pid, 'season': season, 'team_id': cs['start'],
                            'kind': 'arrived_from_club' if origin else 'new', 'origin_club': origin})
    print(f'{season}: {len(cur)} players', flush=True)

out = {'links': links, 'exits': exits, 'entries': entries}
with open('notebooks/aravaca_metro/metro_links_v3.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False)
print('links:', len(links), 'exits:', len(exits), 'entries:', len(entries))
from collections import Counter
print('exit kinds:', Counter(e['kind'] for e in exits))
print('entry kinds:', Counter(e['kind'] for e in entries))
