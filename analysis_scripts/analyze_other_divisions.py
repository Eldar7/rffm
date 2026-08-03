import pandas as pd
import re

season = "2025-2026"
comp = pd.read_csv(f"output/processed/rffm/{season}/competitions.csv")
matches = pd.read_csv(f"output/processed/rffm/{season}/matches.csv")

other_divs = comp[comp['division_level'] == 'OTHER']
print(f"OTHER divisions: {len(other_divs)}\n")
print("=" * 80)

for _, row in other_divs.iterrows():
    comp_id = row['competition_id']
    comp_matches = matches[matches['competition_id'] == comp_id]
    name = row['competition']
    print(f"  {name:50} | {len(comp_matches):4} | {row['game_type']}")

print("\n" + "=" * 80)
print("\nDetailed analysis of competition names:\n")

# Group by patterns
names = other_divs['competition'].unique()
for name in sorted(names):
    # Try to extract structure
    if 'COPA' in name:
        print(f"  🏆 CUP: {name}")
    elif 'SEGUNDA' in name or '2ª' in name or 'FASE' in name:
        print(f"  🥈 SECONDARY: {name}")
    elif 'CAMPEONES' in name or 'CAMPEON' in name:
        print(f"  🎖️  PLAYOFF: {name}")
    elif 'PREFERENTE' in name:
        print(f"  📊 PREFERENTE: {name}")
    elif 'PRIMERA' in name or '1ª' in name:
        if 'F-7' in name or 'FS' in name:
            print(f"  ⭐ PRIMARY (futsal/7): {name}")
        else:
            print(f"  ⭐ PRIMARY: {name}")
    else:
        print(f"  ❓ UNKNOWN: {name}")

print("\n" + "=" * 80)
print("\nKey insight:")
print("  • PREBENJAMÍN has LOCAL competition names that don't fit traditional")
print("    AUTONÓMICA / REGIONAL / PROVINCIAL tiers")
print("  • They're fundamentally MUNICIPAL/LOCAL but currently tagged as OTHER")
print("  • Need a rule to detect and label these as LOCAL or MUNICIPAL tier")
