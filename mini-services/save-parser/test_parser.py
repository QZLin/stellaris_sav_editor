#!/usr/bin/env python3
"""Quick test of the parser with the reference save file."""
import sys
import time
sys.path.insert(0, '.')
from clausewitz_parser import parse_clausewitz
import zipfile

print('Loading reference save...')
with zipfile.ZipFile('/home/z/my-project/download/reference.sav', 'r') as z:
    meta_text = z.read('meta').decode('utf-8')

print('Parsing meta...')
meta = parse_clausewitz(meta_text)
print(f'Version: {meta.get("version", "")}')
print(f'Name: {meta.get("name", "")}')
print(f'Date: {meta.get("date", "")}')
print(f'Ironman: {meta.get("ironman", "")}')

print()
print('Parsing gamestate (this may take a while for 44MB)...')
t0 = time.time()
with zipfile.ZipFile('/home/z/my-project/download/reference.sav', 'r') as z:
    gs_text = z.read('gamestate').decode('utf-8')
print(f'Read {len(gs_text)} chars in {time.time()-t0:.1f}s')

t0 = time.time()
gs = parse_clausewitz(gs_text)
print(f'Parsed in {time.time()-t0:.1f}s')

print(f'Date: {gs.get("date", "")}')
print(f'Tick: {gs.get("tick", "")}')

# Countries
player = gs.get('player', [])
print(f'Player block: {player}')

countries = gs.get('country', {})
if isinstance(countries, dict):
    print(f'Number of countries: {len(countries)}')
    for idx in list(countries.keys())[:3]:
        c = countries[idx]
        if isinstance(c, dict):
            name = c.get('name', '')
            if isinstance(name, dict):
                name = name.get('key', '')
            resources = c.get('resources', {})
            print(f'  Country {idx}: name={name}, resources_keys={list(resources.keys())[:5]}...')

# Species
species_db = gs.get('species_db', {})
if isinstance(species_db, dict):
    print(f'Number of species: {len(species_db)}')
    for idx in list(species_db.keys())[:3]:
        s = species_db[idx]
        if isinstance(s, dict):
            name = s.get('name', '')
            if isinstance(name, dict):
                name = name.get('key', '')
            print(f'  Species {idx}: name={name}, class={s.get("class", "")}')

print()
print('TEST PASSED!')
