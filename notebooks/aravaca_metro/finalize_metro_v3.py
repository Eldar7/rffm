import json

raw = json.load(open('notebooks/aravaca_metro/metro_raw_v3.json', encoding='utf-8'))
links_raw = json.load(open('notebooks/aravaca_metro/metro_links_v3.json', encoding='utf-8'))
intra = json.load(open('notebooks/aravaca_metro/intra_transfers_v3.json', encoding='utf-8'))
team_slug_map = json.load(open('notebooks/aravaca_metro/team_slug_map_v3.json', encoding='utf-8'))

CATEGORY_ORDER = ['PREBENJAMIN', 'BENJAMIN', 'ALEVIN', 'INFANTIL', 'CADETE', 'JUVENIL', 'AFICIONADO']
CAT_ORDINAL = {c: i for i, c in enumerate(CATEGORY_ORDER)}
TIER_BAND = {1: 0, 2: 1, 3: 2, 4: 3, 6: 4, 7: 5}

season_names = raw['seasons']
season_idx_of = {name: i for i, name in enumerate(season_names)}

exit_by_key = {(e['season'], e['player_id']): e for e in links_raw['exits']}
entry_by_key = {(e['season'], e['player_id']): e for e in links_raw['entries']}
intra_by_key = {(t['season'], t['player_id']): t for t in intra}


def letter_of(team_name):
    return team_name.strip().split()[-1]


# ordering within a season (barycenter-ish, minimizes line crossings): by
# previous season's (category_ordinal, division tier, row index) per player
prev_order = None
stations_out = []
for si, season in enumerate(season_names):
    teams = [s for s in raw['stations'] if s['season'] == season]
    teams.sort(key=lambda t: (CAT_ORDINAL.get(t['category_base'], 9), TIER_BAND.get(t['tier'], 9), t['team']))
    team_rank = {t['team_id']: i for i, t in enumerate(teams)}

    this_order = {}
    for t in teams:
        roster = t['roster']
        if prev_order is None:
            ordered = sorted(roster, key=lambda r: -r['goals'])
        else:
            def sort_key(r):
                po = prev_order.get(r['player_id'])
                if po is not None:
                    return (0, po[0], po[1])
                return (1, 0, -r['goals'])
            ordered = sorted(roster, key=sort_key)
        for j, r in enumerate(ordered):
            this_order[r['player_id']] = (team_rank[t['team_id']], j)

        roster_out = []
        for r in ordered:
            pid = r['player_id']
            entry = entry_by_key.get((season, pid))
            intra_t = intra_by_key.get((season, pid))
            roster_out.append({
                'player_id': pid, 'name': r['name'], 'birth_year': r['birth_year'],
                'is_gk': r['is_gk'], 'is_cap': r['is_cap'], 'apps': r['apps'], 'goals': r['goals'],
                'transfer_role': r.get('transfer_role'),
                'entry_kind': entry['kind'] if (entry and r.get('transfer_role') != 'after') else None,
                'origin_club': entry.get('origin_club') if (entry and r.get('transfer_role') != 'after') else None,
                'intra_transfer': intra_t,
            })
        slug_entry = team_slug_map.get(f"{season}|{t['team_id']}")
        stations_out.append({
            'id': f"{si}:{t['team_id']}", 'season_idx': si, 'season': season,
            'team_id': t['team_id'], 'letter': letter_of(t['team']),
            'division_level': t['division_level'], 'category_base': t['category_base'],
            'category_ordinal': CAT_ORDINAL.get(t['category_base'], 9),
            'game_type': t['game_type'], 'tier_band': TIER_BAND.get(t['tier'], 9),
            'club_slug': slug_entry[1] if slug_entry else None,
            'roster': roster_out,
        })
    prev_order = this_order

links_out = [{
    'player_id': l['player_id'],
    'from': f"{season_idx_of[l['from_season']]}:{l['from_team']}",
    'to': f"{season_idx_of[l['to_season']]}:{l['to_team']}",
    'from_season': l['from_season'], 'to_season': l['to_season'],
} for l in links_raw['links']]

exits_out = [{'player_id': e['player_id'], 'season': e['season'],
              'team': f"{season_idx_of[e['season']]}:{e['team_id']}",
              'kind': e['kind'], 'dest_club': e['dest_club']} for e in links_raw['exits']]

intra_out = [{'player_id': t['player_id'], 'season': t['season'],
              'from': f"{season_idx_of[t['season']]}:{t['from']}",
              'to': f"{season_idx_of[t['season']]}:{t['to']}", 'date': t['date']}
             for t in intra]

final = {
    'season_names': season_names,
    'pivot_birth_years': raw['pivot_birth_years'],
    'category_order': CATEGORY_ORDER,
    'stations': stations_out, 'links': links_out, 'exits': exits_out, 'intra_transfers': intra_out,
}
with open('notebooks/aravaca_metro/metro_final_v3.json', 'w', encoding='utf-8') as f:
    json.dump(final, f, ensure_ascii=False)
print('stations:', len(stations_out), 'links:', len(links_out), 'exits:', len(exits_out), 'intra:', len(intra_out))
