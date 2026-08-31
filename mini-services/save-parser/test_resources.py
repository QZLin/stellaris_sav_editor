#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
from clausewitz_parser import parse_clausewitz
import zipfile

with zipfile.ZipFile('/home/z/my-project/download/reference.sav', 'r') as z:
    gs_text = z.read('gamestate').decode('utf-8')

gs = parse_clausewitz(gs_text)

# Check country 0 structure
countries = gs.get('country', {})
c0 = countries.get('0', countries.get(0, {}))
print('Country 0 keys:', list(c0.keys())[:20])

resources = c0.get('resources', {})
print('Resources:', resources)

# Also check player block
player = gs.get('player', {})
print('Player:', player)
