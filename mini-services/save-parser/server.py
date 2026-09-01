"""
Stellaris Save File Parser - HTTP Service
Provides REST API for parsing, viewing, and modifying Stellaris .sav files.

Optimization: uses save_splitter.py to pre-split gamestate into per-entity
files (country / species_db / fleet / leaders / galactic_object, see
save_splitter.DEFAULT_SPLIT_BLOCKS), so GET/PUT per-entity operations work
on ~20-300KB split files instead of the 44MB gamestate, with O(1) char-offset
splices back into the master text.

Upload pipeline:
  1. unzip meta + gamestate                     (~2s)
  2. pre-split gamestate into per-entity files  (~2s)
  3. respond immediately with meta + split info
  4. full gamestate parse continues in a background thread (for endpoints
     that need global data: /api/countries, /api/species)

Endpoints that only need per-entity data (resources / stats / events / flag)
read split files and never wait for the full parse.

Threading: ThreadingHTTPServer + a global state lock. The background parse
thread never holds the lock while parsing (see _start_background_parse).
"""

import os
import sys
import json
import re
import zipfile
import tempfile
import threading
import traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from clausewitz_parser import parse_clausewitz
from save_splitter import (
    split_gamestate, read_split_file, write_split_file,
    splice_into_gamestate, update_parsed_sub_block,
    cleanup_work_dir, verify_roundtrip,
)


# In-memory save data store (guarded by _state_lock)
save_state = {
    'sav_path': None,
    'meta_text': None,
    'gamestate_text': None,
    'meta_parsed': None,
    'gamestate_parsed': None,
    # Split optimization
    'work_dir': None,
    'manifest': None,
    'country_parsed_cache': {},  # {country_id_str: parsed_dict}
    # Player country id, resolved fast at upload time (small-window parse)
    'player_country_id': 0,
    # Background full-parse bookkeeping
    'parse_thread': None,
    'generation': 0,
}

_state_lock = threading.RLock()


RESOURCE_KEYS = [
    'energy', 'minerals', 'food', 'physics_research', 'society_research',
    'engineering_research', 'influence', 'unity', 'consumer_goods', 'alloys',
    'volatile_motes', 'exotic_gases', 'rare_crystals', 'sr_dark_matter', 'minor_artifacts',
    'sr_zro', 'nanites',
]

RESOURCE_LABELS = {
    'energy': '能量币',
    'minerals': '矿物',
    'food': '食物',
    'physics_research': '物理学研究',
    'society_research': '社会学研究',
    'engineering_research': '工程学研究',
    'influence': '影响力',
    'unity': '凝聚力',
    'consumer_goods': '消费品',
    'alloys': '合金',
    'volatile_motes': '挥发性微粒',
    'exotic_gases': '异星气体',
    'rare_crystals': '稀有水晶',
    'sr_dark_matter': '暗物质',
    'minor_artifacts': '小型遗物',
    'sr_zro': 'ZRO气体',
    'nanites': '纳米机器人',
}

RESOURCE_ICONS = {
    'energy': '⚡', 'minerals': '💎', 'food': '🌾',
    'physics_research': '🔬', 'society_research': '🧬', 'engineering_research': '⚙️',
    'influence': '👑', 'unity': '✨', 'consumer_goods': '📺', 'alloys': '🔩',
    'volatile_motes': '💨', 'exotic_gases': '🧪', 'rare_crystals': '💠',
    'sr_dark_matter': '🌑', 'minor_artifacts': '🏺',
    'sr_zro': '🔮', 'nanites': '🤖',
}

RESOURCE_CATEGORIES = {
    '基础资源': ['energy', 'minerals', 'food'],
    '科研': ['physics_research', 'society_research', 'engineering_research'],
    '战略资源': ['influence', 'unity', 'consumer_goods', 'alloys'],
    '稀有资源': ['volatile_motes', 'exotic_gases', 'rare_crystals'],
    '高级资源': ['sr_dark_matter', 'sr_zro', 'nanites', 'minor_artifacts'],
}

# ============ FLAG DATA ============

FLAG_ICON_CATEGORIES = {
    'human': {'label': '人类', 'prefix': 'flag_human_', 'count': 24, 'dlc': '基础'},
    'spherical': {'label': '球形', 'prefix': 'flag_spherical_', 'count': 21, 'dlc': '基础'},
    'ornate': {'label': '华丽', 'prefix': 'flag_ornate_', 'count': 24, 'dlc': '基础'},
    'blocky': {'label': '方块', 'prefix': 'flag_blocky_', 'count': 24, 'dlc': '基础'},
    'pointy': {'label': '尖形', 'prefix': 'flag_pointy_', 'count': 14, 'dlc': '基础'},
    'pirate': {'label': '海盗', 'prefix': 'flag_pirate_', 'count': 8, 'dlc': '基础'},
    'zoological': {'label': '动物', 'prefix': 'flag_zoological_', 'count': 22, 'dlc': '基础'},
    'corporate': {'label': '企业', 'prefix': 'flag_corporate_', 'count': 7, 'dlc': 'MegaCorp'},
    'domination': {'label': '霸权', 'prefix': 'domination_', 'count': 17, 'dlc': 'Nemesis'},
    'plantoid': {'label': '植物', 'prefix': 'flag_plantoid_', 'count': 12, 'dlc': 'Plantoids'},
    'lithoid': {'label': '岩石', 'prefix': 'flag_lithoid_', 'count': 6, 'dlc': 'Lithoids'},
    'toxoid': {'label': '剧毒', 'prefix': 'flag_toxoid_', 'count': 11, 'dlc': 'Toxoids'},
    'aquatic': {'label': '水生', 'prefix': 'aquatic_', 'count': 10, 'dlc': 'Aquatics'},
    'caravaneer': {'label': '游牧', 'prefix': 'flag_caravaneer_', 'count': 3, 'dlc': '基础'},
    'infernal': {'label': '地狱', 'prefix': 'flag_infernal_', 'count': 5, 'dlc': 'Anniversary'},
    'legion': {'label': '军团', 'prefix': 'flag_legion_', 'count': 5, 'dlc': 'Nemesis'},
}

FLAG_BACKGROUNDS = [
    '00_solid.dds', '01.dds', '02.dds', '03.dds', '04.dds',
    'circle.dds', 'v.dds', 'sinus.dds', 'new_dawn.dds',
    'flag_BG_01.dds', 'flag_BG_02.dds', 'flag_BG_03.dds', 'flag_BG_04.dds',
    'flag_BG_05.dds', 'flag_BG_06.dds', 'flag_BG_07.dds', 'flag_BG_08.dds',
    'flag_BG_09.dds', 'flag_BG_10.dds', 'flag_BG_11.dds', 'flag_BG_12.dds',
    'flag_BG_13.dds', 'flag_BG_14.dds', 'flag_BG_15.dds', 'flag_BG_16.dds',
    'flag_BG_17.dds', 'flag_BG_18.dds', 'flag_BG_19.dds', 'flag_BG_20.dds',
    'flag_BG_21.dds', 'flag_BG_22.dds', 'flag_BG_23.dds', 'flag_BG_24.dds',
    'pattern_01.dds', 'pattern_02.dds', 'pattern_03.dds', 'pattern_04.dds',
    'pattern_05.dds', 'pattern_06.dds',
]

FLAG_COLORS = [
    'red', 'dark_red', 'burgundy', 'crimson', 'true_red',
    'blue', 'dark_blue', 'cobalt_blue', 'navy_blue', 'mid_blue',
    'green', 'dark_green', 'lime_green', 'olive_green', 'forest_green',
    'yellow', 'gold', 'dark_gold', 'amber',
    'teal', 'dark_teal', 'turquoise', 'cyan',
    'purple', 'dark_purple', 'violet', 'indigo', 'magenta',
    'orange', 'dark_orange', 'rust', 'bronze',
    'pink', 'hot_pink', 'dark_pink', 'fuchsia',
    'brown', 'dark_brown', 'tan', 'beige', 'khaki',
    'grey', 'dark_grey', 'silver', 'steel_grey',
    'black', 'white', 'null',
]


# ============ HELPER FUNCTIONS ============


def extract_save(filepath):
    """Extract .sav (ZIP) and read meta + gamestate texts."""
    with zipfile.ZipFile(filepath, 'r') as z:
        names = z.namelist()
        meta_text = z.read('meta').decode('utf-8') if 'meta' in names else ''
        gamestate_text = z.read('gamestate').decode('utf-8') if 'gamestate' in names else ''
    return meta_text, gamestate_text


def _extract_player_country(player_block):
    """Player country id from a parsed player block value."""
    if not player_block:
        return 0
    if isinstance(player_block, dict):
        items = player_block.get(None, [])
        if items and isinstance(items, list):
            first = items[0]
            if isinstance(first, dict) and 'country' in first:
                try:
                    return int(first['country'])
                except (ValueError, TypeError):
                    return 0
    return 0


def find_player_country_id(gamestate):
    """Find the player's country index from a fully parsed gamestate."""
    return _extract_player_country(gamestate.get('player'))


def find_player_country_id_in_text(gs_text, window=4000):
    """
    Fast player-country lookup WITHOUT a full 44MB parse.
    The `player={...}` block sits near the top of the gamestate and is tiny,
    so parsing a small window is enough.
    """
    m = re.search(r'^player=\{', gs_text, re.MULTILINE)
    if not m:
        return 0
    snippet = gs_text[m.start():m.start() + window]
    try:
        parsed = parse_clausewitz(snippet)
        return _extract_player_country(parsed.get('player'))
    except Exception:
        return 0


def get_top_level_scalar(gs_text, key):
    """
    Fast top-level scalar lookup. Top-level lines are NOT indented, so the
    ^anchor (MULTILINE) only matches them, never nested occurrences.
    Returns the raw string value or None.
    """
    m = re.search(rf'^{re.escape(key)}=(?:"([^"\r\n]*)"|(\S+))', gs_text,
                  re.MULTILINE)
    if not m:
        return None
    return m.group(1) if m.group(1) is not None else m.group(2)


def _start_background_parse(generation, gs_text):
    """
    Parse the full gamestate in a daemon thread; commit the result only if
    the save state is still the same generation AND the master text object
    is unchanged (splices replace the string object, so identity is a cheap
    staleness check). Never holds the state lock while parsing.
    """
    def worker():
        try:
            print('[PARSE-BG] Background full gamestate parse started...')
            parsed = parse_clausewitz(gs_text)
            print('[PARSE-BG] Full parse complete')
        except Exception as e:
            print(f'[PARSE-BG] Full parse failed: {e}')
            traceback.print_exc()
            parsed = {}
        with _state_lock:
            if (save_state['generation'] == generation
                    and save_state['gamestate_text'] is gs_text):
                save_state['gamestate_parsed'] = parsed
            else:
                print('[PARSE-BG] Stale result discarded (state changed)')

    t = threading.Thread(target=worker, daemon=True, name='bg-full-parse')
    save_state['parse_thread'] = t
    t.start()


def _wait_for_parse(timeout=150):
    """
    Ensure the full gamestate parse is available.
    Joins the background thread; if the result was discarded (state changed
    mid-parse) or never started, restarts the parse and waits once more.
    Never holds the state lock while joining - the worker needs it to commit.
    """
    t = save_state.get('parse_thread')
    if t and t.is_alive():
        t.join(timeout)

    if save_state.get('gamestate_parsed') or not save_state.get('gamestate_text'):
        return save_state.get('gamestate_parsed')

    # Result was discarded or never started: restart under the lock.
    with _state_lock:
        t = save_state.get('parse_thread')
        if ((not t or not t.is_alive())
                and not save_state.get('gamestate_parsed')
                and save_state.get('gamestate_text')):
            _start_background_parse(save_state['generation'],
                                    save_state['gamestate_text'])
    t = save_state.get('parse_thread')
    if t and t.is_alive():
        t.join(timeout)
    return save_state.get('gamestate_parsed')


def _get_country_parsed(country_idx):
    """
    Get parsed country data, using split file cache when available.
    Falls back to full gamestate_parsed if split not available.
    """
    cid_str = str(country_idx)
    manifest = save_state['manifest']
    work_dir = save_state['work_dir']

    # Check cache first
    if cid_str in save_state['country_parsed_cache']:
        return save_state['country_parsed_cache'][cid_str]

    # Try split file (fast: ~20-300KB instead of 44MB)
    if manifest and work_dir:
        text = read_split_file(work_dir, manifest, 'country', cid_str)
        if text:
            parsed = parse_clausewitz(text)
            # The split file is "0={...}" so the data is under key "0"
            country_data = parsed.get(cid_str, parsed)
            save_state['country_parsed_cache'][cid_str] = country_data
            return country_data

    # Fallback to full parsed
    gs = save_state['gamestate_parsed']
    if gs:
        countries = gs.get('country', {})
        return countries.get(cid_str, {})
    return {}


def _invalidate_country_cache(country_idx):
    """Remove a country from the parsed cache."""
    cid_str = str(country_idx)
    save_state['country_parsed_cache'].pop(cid_str, None)


def get_country_resources(country_idx):
    """Extract resources for a specific country (uses split optimization)."""
    country = _get_country_parsed(country_idx)
    if not isinstance(country, dict):
        return {}
    modules = country.get('modules', {})
    if not isinstance(modules, dict):
        return {}
    econ = modules.get('standard_economy_module', {})
    if not isinstance(econ, dict):
        return {}
    resources = econ.get('resources', {})
    return resources if isinstance(resources, dict) else {}


def get_countries_list(gamestate):
    """Get list of all countries with basic info."""
    countries = gamestate.get('country', {})
    if not countries or not isinstance(countries, dict):
        return []
    result = []
    for idx, country in countries.items():
        if not isinstance(country, dict):
            continue
        name_data = country.get('name', '')
        if isinstance(name_data, dict):
            name_data = name_data.get('key', '')
        result.append({
            'id': str(idx),
            'name': str(name_data),
            'type': str(country.get('type', '')),
            'custom_name': bool(country.get('custom_name', False)),
            'capital': country.get('capital', ''),
            'military_power': float(country.get('military_power', 0)),
            'economy_power': float(country.get('economy_power', 0)),
            'tech_power': float(country.get('tech_power', 0)),
            'fleet_size': country.get('fleet_size', 0),
        })
    return result


def get_species_list(gamestate, limit=50):
    """Get list of species with traits."""
    species_db = gamestate.get('species_db', {})
    if not species_db or not isinstance(species_db, dict):
        return []
    result = []
    for idx, species in species_db.items():
        if not isinstance(species, dict):
            continue
        name_data = species.get('name', '')
        if isinstance(name_data, dict):
            name_data = name_data.get('key', '')
        traits = species.get('traits', [])
        if isinstance(traits, dict):
            traits = traits.get('trait', [])
        if not isinstance(traits, list):
            traits = [traits] if traits else []
        result.append({
            'id': str(idx),
            'name': str(name_data) if name_data else '(未命名)',
            'class': species.get('class', ''),
            'portrait': species.get('portrait', ''),
            'traits': [str(t) for t in traits if t],
            'home_planet': species.get('home_planet', ''),
        })
        if len(result) >= limit:
            break
    return result


def get_budget_info(country_idx):
    """Get budget/income info for a country."""
    country = _get_country_parsed(country_idx)
    if not isinstance(country, dict):
        return {}
    budget = country.get('budget', {})
    if not isinstance(budget, dict):
        return {}
    current = budget.get('current_month', {})
    if not isinstance(current, dict):
        return {}
    income = current.get('income', {})
    if not isinstance(income, dict):
        return {}
    result = {}
    for source_name, source_data in income.items():
        if not isinstance(source_data, dict):
            continue
        for res_key, val in source_data.items():
            if res_key not in result:
                result[res_key] = 0.0
            try:
                result[res_key] += float(val)
            except (ValueError, TypeError):
                pass
    return result


def get_tech_count(country_idx):
    """Get number of researched technologies."""
    country = _get_country_parsed(country_idx)
    if not isinstance(country, dict):
        return 0
    tech_status = country.get('tech_status', {})
    if not isinstance(tech_status, dict):
        return 0
    techs = tech_status.get('technology', [])
    if isinstance(techs, list):
        return len(techs)
    return 0


# ============ TEXT MODIFICATION FUNCTIONS ============
# These operate on SPLIT FILE text (small, ~20-300KB) instead of full 44MB.


def modify_resource_in_text(text, country_idx, resource_key, new_value):
    """Modify a single resource value in a country's split file text."""
    lines = text.split('\n')
    state = 'seeking_econ'
    econ_depth = 0
    resource_block_depth = 0
    in_resource_block = False
    result_lines = []
    modified = False

    for line in lines:
        if modified:
            result_lines.append(line)
            continue

        opens = line.count('{')
        closes = line.count('}')

        if state == 'seeking_econ':
            if re.match(r'^\s*standard_economy_module\s*=\{\s*$', line):
                state = 'in_econ'
                econ_depth = 1
            result_lines.append(line)
            continue

        if state == 'in_econ':
            econ_depth += opens - closes
            if econ_depth <= 0:
                state = 'done'
                result_lines.append(line)
                continue
            if not in_resource_block:
                if re.match(r'^\s*resources\s*=\{\s*$', line):
                    in_resource_block = True
                    resource_block_depth = 1
                result_lines.append(line)
                continue
            # in resource block
            resource_block_depth += opens - closes
            if resource_block_depth <= 0:
                in_resource_block = False
                result_lines.append(line)
                continue
            match = re.match(rf'^(\s*){re.escape(resource_key)}=(.+)$', line)
            if match:
                indent = match.group(1)
                formatted = f'{new_value:.5f}'.rstrip('0')
                if formatted.endswith('.'):
                    formatted += '0'
                result_lines.append(f'{indent}{resource_key}={formatted}')
                modified = True
                continue
            result_lines.append(line)
            continue

        result_lines.append(line)

    return '\n'.join(result_lines)


def modify_date_in_text(text, new_date):
    """Modify the game date in text (top-level date= line)."""
    pattern = re.compile(r'^(date=")\d{4}\.\d{2}\.\d{2}(")', re.MULTILINE)
    return pattern.sub(f'\\g<1>{new_date}\\g<2>', text, count=1)


def modify_name_in_text(text, old_name, new_name):
    """Modify the empire name in gamestate text."""
    pattern = re.compile(r'^(name=\{\n\s*key=")' + re.escape(old_name) + r'(")', re.MULTILINE)
    return pattern.sub(f'\\g<1>{new_name}\\g<2>', text, count=1)


def modify_name_in_meta(text, new_name):
    """Modify the empire name in meta text."""
    pattern = re.compile(r'^(name=")' + r'[^"]*' + r'(")', re.MULTILINE)
    return pattern.sub(f'\\g<1>{new_name}\\g<2>', text, count=1)


def get_delayed_events_from_text(text):
    """Extract delayed events from a country's split file text."""
    lines = text.split('\n')
    state = 'seeking_event_module'
    emod_depth = 0
    in_de = False
    de_depth = 0
    events = []
    current_evt = {}

    for line in lines:
        opens = line.count('{')
        closes = line.count('}')

        if state == 'seeking_event_module':
            if re.match(r'^\s*standard_event_module\s*=\{\s*$', line):
                state = 'in_event_module'
                emod_depth = 1
            continue

        if state == 'in_event_module':
            emod_depth += opens - closes
            if emod_depth <= 0:
                break
            if not in_de:
                if re.match(r'^\s*delayed_event\s*=\{\s*$', line):
                    in_de = True
                    de_depth = 0
                continue
            de_depth += opens - closes
            if de_depth <= 0:
                in_de = False
                continue
            m = re.match(r'^\s*event="([^"]+)"', line)
            if m:
                current_evt = {'event': m.group(1), 'days': 0}
                continue
            m = re.match(r'^\s*days=(\d+)', line)
            if m and current_evt:
                current_evt['days'] = int(m.group(1))
                events.append(current_evt)
                current_evt = {}

    return events


def modify_event_days_in_text(text, event_index, new_days):
    """Modify the days value of a specific delayed event in split file text."""
    lines = text.split('\n')
    state = 'seeking_event_module'
    emod_depth = 0
    in_delayed_events = False
    de_depth = 0
    current_event_idx = -1
    result_lines = []
    modified = False

    for line in lines:
        if modified:
            result_lines.append(line)
            continue
        opens = line.count('{')
        closes = line.count('}')

        if state == 'seeking_event_module':
            if re.match(r'^\s*standard_event_module\s*=\{\s*$', line):
                state = 'in_event_module'
                emod_depth = 1
            result_lines.append(line)
            continue

        if state == 'in_event_module':
            emod_depth += opens - closes
            if emod_depth <= 0:
                result_lines.append(line)
                continue
            if not in_delayed_events:
                if re.match(r'^\s*delayed_event\s*=\{\s*$', line):
                    in_delayed_events = True
                    de_depth = 0
                result_lines.append(line)
                continue
            de_depth += opens - closes
            if de_depth <= 0:
                in_delayed_events = False
                result_lines.append(line)
                continue
            if de_depth == 1 and re.match(r'^\s*event=', line):
                current_event_idx += 1
            if current_event_idx == event_index and re.match(r'^\s*days=', line):
                indent = line[:len(line) - len(line.lstrip())]
                result_lines.append(f'{indent}days={new_days}')
                modified = True
                continue
            result_lines.append(line)
            continue

        result_lines.append(line)

    return '\n'.join(result_lines)


def get_flag_from_parsed(country):
    """Extract flag data from parsed country data."""
    if not isinstance(country, dict):
        return {}
    flag = country.get('flag', {})
    if not isinstance(flag, dict):
        return {}
    icon = flag.get('icon', {})
    bg = flag.get('background', {})
    colors = flag.get('colors', {})
    if isinstance(colors, dict):
        colors = colors.get(None, [])
    return {
        'icon_category': icon.get('category', '') if isinstance(icon, dict) else '',
        'icon_file': icon.get('file', '') if isinstance(icon, dict) else '',
        'bg_category': bg.get('category', '') if isinstance(bg, dict) else '',
        'bg_file': bg.get('file', '') if isinstance(bg, dict) else '',
        'colors': [str(c) for c in colors] if isinstance(colors, list) else [],
    }


def modify_flag_in_text_v2(text, flag_data):
    """Rebuild the flag={...} block inside a country's split file text.

    Uses the ORIGINAL leading indentation of the flag block so the splice
    stays as byte-close to the source formatting as possible.
    """
    # Find the flag block boundaries
    lines = text.split('\n')
    flag_start = -1
    flag_end = -1
    depth = 0
    for i, line in enumerate(lines):
        if flag_start < 0:
            if re.match(r'^\s*flag=\{\s*$', line):
                flag_start = i
                depth = 1
            continue
        depth += line.count('{') - line.count('}')
        if depth <= 0:
            flag_end = i
            break

    if flag_start < 0 or flag_end < 0:
        return text

    # Preserve the original indentation of the flag= line
    first = lines[flag_start]
    indent = first[:len(first) - len(first.lstrip())]

    icon_cat = flag_data.get('icon_category', '')
    icon_file = flag_data.get('icon_file', '')
    bg_cat = flag_data.get('bg_category', '')
    bg_file = flag_data.get('bg_file', '')
    colors = flag_data.get('colors', [])

    new_flag_lines = [f'{indent}flag={{']
    new_flag_lines.append(f'{indent}\ticon={{')
    new_flag_lines.append(f'{indent}\t\tcategory="{icon_cat}"')
    new_flag_lines.append(f'{indent}\t\tfile="{icon_file}"')
    new_flag_lines.append(f'{indent}\t}}')
    new_flag_lines.append(f'{indent}\tbackground={{')
    new_flag_lines.append(f'{indent}\t\tcategory="{bg_cat}"')
    new_flag_lines.append(f'{indent}\t\tfile="{bg_file}"')
    new_flag_lines.append(f'{indent}\t}}')
    new_flag_lines.append(f'{indent}\tcolors={{')
    for c in colors:
        new_flag_lines.append(f'{indent}\t\t"{c}"')
    new_flag_lines.append(f'{indent}\t}}')
    new_flag_lines.append(f'{indent}}}')

    result_lines = lines[:flag_start] + new_flag_lines + lines[flag_end + 1:]
    return '\n'.join(result_lines)


# ============ COUNTRY-LEVEL MODIFY + SPLICE ============


def _modify_and_splice(country_idx, modify_fn, *args):
    """
    Read a country's split file, apply modify_fn(text, *args) -> new_text,
    write back, splice into gamestate_text, update parsed cache.
    Returns True on success.
    """
    cid_str = str(country_idx)
    work_dir = save_state['work_dir']
    manifest = save_state['manifest']

    if not work_dir or not manifest:
        print(f'[SPLIT] No work_dir/manifest, cannot modify country {cid_str}')
        return False

    # Read split file
    text = read_split_file(work_dir, manifest, 'country', cid_str)
    if text is None:
        print(f'[SPLIT] Country {cid_str} split file not found')
        return False

    # Modify
    new_text = modify_fn(text, *args)

    # Write back to split file
    write_split_file(work_dir, manifest, 'country', cid_str, new_text)

    # Splice into full gamestate (O(1) via char offsets)
    save_state['gamestate_text'] = splice_into_gamestate(
        save_state['gamestate_text'], manifest, 'country', cid_str, new_text
    )

    # Update parsed caches
    _invalidate_country_cache(country_idx)
    parsed = parse_clausewitz(new_text)
    country_data = parsed.get(cid_str, parsed)
    save_state['country_parsed_cache'][cid_str] = country_data
    update_parsed_sub_block(save_state['gamestate_parsed'], 'country', cid_str, country_data)

    return True


def _cleanup_all():
    """Clean up all in-memory and on-disk state."""
    if save_state.get('work_dir'):
        cleanup_work_dir(save_state['work_dir'])
    if save_state.get('sav_path') and os.path.exists(save_state['sav_path']):
        try:
            os.unlink(save_state['sav_path'])
        except OSError:
            pass
    save_state.update({
        'sav_path': None,
        'meta_text': None,
        'gamestate_text': None,
        'meta_parsed': None,
        'gamestate_parsed': None,
        'work_dir': None,
        'manifest': None,
        'country_parsed_cache': {},
        'player_country_id': 0,
        'parse_thread': None,
    })
    save_state['generation'] += 1


class SaveHandler(BaseHTTPRequestHandler):
    """HTTP request handler for save file operations."""

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, filepath, filename):
        import mimetypes
        ctype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        size = os.path.getsize(filepath)
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(size))
        self.end_headers()
        with open(filepath, 'rb') as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        return self.rfile.read(length) if length > 0 else b''

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        try:
            if path == '/api/status':
                with _state_lock:
                    loaded = save_state['sav_path'] is not None
                    payload = {
                        'loaded': loaded,
                        'filename': os.path.basename(save_state['sav_path']) if loaded else None,
                        'parsing': bool(save_state.get('parse_thread')
                                        and save_state['parse_thread'].is_alive()),
                    }
                self._send_json(payload)

            elif path == '/api/meta':
                with _state_lock:
                    if not save_state['meta_parsed']:
                        self._send_json({'error': 'No save file loaded'}, 400)
                        return
                    meta = save_state['meta_parsed']
                dlcs = meta.get('required_dlcs', {})
                if isinstance(dlcs, dict):
                    dlcs = dlcs.get(None, [])
                if not isinstance(dlcs, list):
                    dlcs = [dlcs]
                self._send_json({
                    'version': meta.get('version', ''),
                    'name': meta.get('name', ''),
                    'date': meta.get('date', ''),
                    'ironman': meta.get('ironman', False),
                    'dlcs': dlcs,
                    'meta_fleets': meta.get('meta_fleets', 0),
                    'meta_planets': meta.get('meta_planets', 0),
                })

            elif path == '/api/countries':
                # Needs global data: ensure the full parse is available.
                with _state_lock:
                    has_save = bool(save_state['gamestate_text'])
                if not has_save:
                    self._send_json({'error': 'No save file loaded'}, 400)
                    return
                gs = _wait_for_parse()
                if not gs:
                    self._send_json({'error': '全量解析尚未完成，请稍后重试'}, 503)
                    return
                with _state_lock:
                    gs = save_state['gamestate_parsed']
                    countries = get_countries_list(gs) if gs else []
                    player_idx = save_state['player_country_id']
                self._send_json({
                    'countries': countries,
                    'player_country_id': str(player_idx),
                })

            elif path == '/api/resources':
                country_id = params.get('country_id', ['0'])[0]
                with _state_lock:
                    resources = get_country_resources(int(country_id))
                    budget = get_budget_info(int(country_id))
                labeled = {}
                for key in RESOURCE_KEYS:
                    val = resources.get(key, 0)
                    labeled[key] = {
                        'value': float(val) if val else 0.0,
                        'label': RESOURCE_LABELS.get(key, key),
                        'icon': RESOURCE_ICONS.get(key, ''),
                        'income': round(budget.get(key, 0.0), 2),
                    }
                self._send_json({
                    'resources': labeled,
                    'country_id': country_id,
                    'categories': RESOURCE_CATEGORIES,
                })

            elif path == '/api/species':
                with _state_lock:
                    has_save = bool(save_state['gamestate_text'])
                if not has_save:
                    self._send_json({'error': 'No save file loaded'}, 400)
                    return
                gs = _wait_for_parse()
                if not gs:
                    self._send_json({'error': '全量解析尚未完成，请稍后重试'}, 503)
                    return
                with _state_lock:
                    gs = save_state['gamestate_parsed']
                    species_db = gs.get('species_db', {}) if isinstance(gs, dict) else {}
                    total = len(species_db) if isinstance(species_db, dict) else 0
                    species = get_species_list(gs, limit=50) if gs else []
                self._send_json({'species': species, 'total': total})

            elif path == '/api/events':
                with _state_lock:
                    if not save_state['gamestate_text']:
                        self._send_json({'error': 'No save file loaded'}, 400)
                        return
                    country_id = int(params.get('country_id', ['0'])[0])
                    # Use split file for fast extraction
                    cid_str = str(country_id)
                    work_dir = save_state['work_dir']
                    manifest = save_state['manifest']
                    if work_dir and manifest:
                        text = read_split_file(work_dir, manifest, 'country', cid_str)
                    else:
                        text = save_state['gamestate_text']
                events = get_delayed_events_from_text(text) if text else []
                self._send_json({'events': events, 'country_id': str(country_id)})

            elif path == '/api/flag':
                country_id = int(params.get('country_id', ['0'])[0])
                with _state_lock:
                    country = _get_country_parsed(country_id)
                flag = get_flag_from_parsed(country)
                self._send_json({
                    'flag': flag,
                    'country_id': str(country_id),
                    'available_categories': FLAG_ICON_CATEGORIES,
                    'available_backgrounds': FLAG_BACKGROUNDS,
                    'available_colors': FLAG_COLORS,
                })

            elif path == '/api/date':
                with _state_lock:
                    if not save_state['gamestate_text']:
                        self._send_json({'error': 'No save file loaded'}, 400)
                        return
                    date = get_top_level_scalar(save_state['gamestate_text'], 'date')
                self._send_json({'date': date or ''})

            elif path == '/api/stats':
                # Split-first: works BEFORE the background full parse finishes.
                with _state_lock:
                    gs_text = save_state['gamestate_text']
                    if not gs_text:
                        self._send_json({'error': 'No save file loaded'}, 400)
                        return
                    manifest = save_state['manifest']
                    player_idx = save_state['player_country_id']
                    country = _get_country_parsed(player_idx)
                    tech_count = get_tech_count(player_idx)

                date = get_top_level_scalar(gs_text, 'date') or ''
                tick_raw = get_top_level_scalar(gs_text, 'tick')
                try:
                    tick = int(tick_raw) if tick_raw is not None else 0
                except (ValueError, TypeError):
                    tick = 0

                if manifest:
                    num_countries = len(manifest.get('sub_ranges', {}).get('country', {}))
                    num_species = len(manifest.get('sub_ranges', {}).get('species_db', {}))
                else:
                    # No split available: fall back to the full parse (which is
                    # synchronous in the no-split upload path).
                    gs = save_state['gamestate_parsed']
                    countries_d = gs.get('country', {}) if isinstance(gs, dict) else {}
                    species_d = gs.get('species_db', {}) if isinstance(gs, dict) else {}
                    num_countries = len(countries_d) if isinstance(countries_d, dict) else 0
                    num_species = len(species_d) if isinstance(species_d, dict) else 0

                owned_planets = country.get('owned_planets', {}) if isinstance(country, dict) else {}
                self._send_json({
                    'date': date,
                    'tick': tick,
                    'num_species': num_species,
                    'num_countries': num_countries,
                    'player_country_id': str(player_idx),
                    'tech_count': tech_count,
                    'fleet_size': country.get('fleet_size', 0) if isinstance(country, dict) else 0,
                    'military_power': float(country.get('military_power', 0)) if isinstance(country, dict) else 0,
                    'empire_size': country.get('empire_size', 0) if isinstance(country, dict) else 0,
                    'owned_planets_count': len(owned_planets.get(None, [])) if isinstance(owned_planets, dict) else 0,
                })

            else:
                self._send_json({'error': 'Not found'}, 404)

        except Exception as e:
            traceback.print_exc()
            self._send_json({'error': str(e)}, 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            if path == '/api/upload':
                body = self._read_body()
                if not body:
                    self._send_json({'error': 'No file data'}, 400)
                    return

                with _state_lock:
                    # Clean up any previous state
                    _cleanup_all()

                    # Save to temp file
                    tmp = tempfile.NamedTemporaryFile(suffix='.sav', delete=False)
                    tmp.write(body)
                    tmp.close()

                    try:
                        meta_text, gamestate_text = extract_save(tmp.name)
                    except Exception as e:
                        os.unlink(tmp.name)
                        self._send_json({'error': f'Failed to parse .sav file: {str(e)}'}, 400)
                        return

                    meta_parsed = parse_clausewitz(meta_text) if meta_text else {}

                    save_state['sav_path'] = tmp.name
                    save_state['meta_text'] = meta_text
                    save_state['gamestate_text'] = gamestate_text
                    save_state['meta_parsed'] = meta_parsed
                    save_state['country_parsed_cache'] = {}

                    # Fast player country lookup (small-window parse)
                    player_idx = find_player_country_id_in_text(gamestate_text)
                    save_state['player_country_id'] = player_idx

                    # Pre-split the gamestate for fast per-entity access.
                    # Falls back gracefully if splitting fails.
                    work_dir = os.path.join(
                        os.path.dirname(tmp.name),
                        f'stellaris_split_{os.path.basename(tmp.name)}')
                    try:
                        print('[UPLOAD] Starting gamestate split...')
                        manifest = split_gamestate(gamestate_text, work_dir)
                        save_state['work_dir'] = work_dir
                        save_state['manifest'] = manifest
                        print('[UPLOAD] Split complete')
                        if os.environ.get('SAVE_VERIFY') == '1':
                            ok = verify_roundtrip(gamestate_text, manifest, work_dir)
                            print(f'[UPLOAD] Roundtrip verify: {"PASS" if ok else "FAIL"}')
                    except Exception as e:
                        print(f'[UPLOAD] Warning: Split failed: {e}')
                        traceback.print_exc()
                        save_state['work_dir'] = None
                        save_state['manifest'] = None

                    if save_state['manifest']:
                        # Split succeeded: full parse can run in the
                        # background - the response goes out NOW.
                        _start_background_parse(save_state['generation'],
                                                gamestate_text)
                        gamestate_parsed = None
                    else:
                        # No split: parse synchronously (old behaviour)
                        print('[UPLOAD] Starting full gamestate parse...')
                        gamestate_parsed = parse_clausewitz(gamestate_text) if gamestate_text else {}
                        print('[UPLOAD] Full parse complete')
                        save_state['gamestate_parsed'] = gamestate_parsed

                    meta_name = meta_parsed.get('name', '')
                    meta_date = meta_parsed.get('date', '')

                    dlcs = meta_parsed.get('required_dlcs', {})
                    if isinstance(dlcs, dict):
                        dlcs = dlcs.get(None, [])
                    if not isinstance(dlcs, list):
                        dlcs = [dlcs]

                    # Report split info
                    split_info = {}
                    if save_state['manifest']:
                        for bname, info in save_state['manifest'].get('split_info', {}).items():
                            split_info[bname] = len(info)

                self._send_json({
                    'success': True,
                    'filename': os.path.basename(tmp.name),
                    'meta': {
                        'version': meta_parsed.get('version', ''),
                        'name': meta_name,
                        'date': meta_date,
                        'ironman': meta_parsed.get('ironman', False),
                        'dlcs': dlcs,
                        'meta_fleets': meta_parsed.get('meta_fleets', 0),
                        'meta_planets': meta_parsed.get('meta_planets', 0),
                    },
                    'player_country_id': str(player_idx),
                    'gamestate_size': len(gamestate_text),
                    'split_info': split_info,
                    'background_parse': bool(save_state.get('parse_thread')),
                })

            elif path == '/api/export':
                with _state_lock:
                    if not save_state['sav_path']:
                        self._send_json({'error': 'No save file loaded'}, 400)
                        return
                    meta_text = save_state['meta_text']
                    gamestate_text = save_state['gamestate_text']

                export_tmp = tempfile.NamedTemporaryFile(suffix='.sav', delete=False)
                export_tmp.close()

                with zipfile.ZipFile(export_tmp.name, 'w', zipfile.ZIP_DEFLATED) as zout:
                    zout.writestr('meta', meta_text.encode('utf-8'))
                    zout.writestr('gamestate', gamestate_text.encode('utf-8'))

                self._send_file(export_tmp.name, 'modified_save.sav')
                os.unlink(export_tmp.name)

            else:
                self._send_json({'error': 'Not found'}, 404)

        except Exception as e:
            traceback.print_exc()
            self._send_json({'error': str(e)}, 500)

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            body = self._read_body()
            data = json.loads(body) if body else {}

            with _state_lock:
                if path == '/api/resources':
                    country_id = data.get('country_id', 0)
                    resources = data.get('resources', {})

                    # Use split-based modification
                    if save_state['work_dir'] and save_state['manifest']:
                        for key, value in resources.items():
                            try:
                                _modify_and_splice(
                                    country_id, modify_resource_in_text,
                                    int(country_id), key, float(value)
                                )
                            except (ValueError, TypeError) as e:
                                print(f'[PUT] Resource {key} modification error: {e}')
                        self._send_json({'success': True, 'message': f'Updated {len(resources)} resources'})
                    else:
                        # Fallback: modify full text (slow)
                        gs_text = save_state['gamestate_text']
                        for key, value in resources.items():
                            try:
                                gs_text = modify_resource_in_text(gs_text, int(country_id), key, float(value))
                            except (ValueError, TypeError):
                                pass
                        save_state['gamestate_text'] = gs_text
                        self._send_json({'success': True, 'message': f'Updated {len(resources)} resources'})

                elif path == '/api/date':
                    new_date = data.get('date', '')
                    if not re.match(r'^\d{4}\.\d{2}\.\d{2}$', new_date):
                        self._send_json({'error': 'Invalid date format, use YYYY.MM.DD'}, 400)
                        return

                    save_state['gamestate_text'] = modify_date_in_text(save_state['gamestate_text'], new_date)
                    save_state['meta_text'] = modify_date_in_text(save_state['meta_text'], new_date)
                    # Keep derived structures in sync (cheap)
                    try:
                        save_state['meta_parsed'] = parse_clausewitz(save_state['meta_text'])
                    except Exception:
                        pass
                    if isinstance(save_state.get('gamestate_parsed'), dict):
                        save_state['gamestate_parsed']['date'] = new_date
                    self._send_json({'success': True, 'date': new_date})

                elif path == '/api/name':
                    new_name = data.get('name', '')
                    old_name = save_state['meta_parsed'].get('name', '') if save_state['meta_parsed'] else ''

                    # Modify in full gamestate_text (name is at top level, not in split blocks)
                    if old_name:
                        save_state['gamestate_text'] = modify_name_in_text(save_state['gamestate_text'], old_name, new_name)
                    save_state['meta_text'] = modify_name_in_meta(save_state['meta_text'], new_name)
                    try:
                        save_state['meta_parsed'] = parse_clausewitz(save_state['meta_text'])
                    except Exception:
                        pass
                    if isinstance(save_state.get('gamestate_parsed'), dict):
                        save_state['gamestate_parsed'].pop('name', None)
                    self._send_json({'success': True, 'name': new_name})

                elif path == '/api/events':
                    country_id = int(data.get('country_id', 0))
                    event_changes = data.get('events', [])

                    if save_state['work_dir'] and save_state['manifest']:
                        for change in event_changes:
                            evt_idx = change.get('index', -1)
                            new_days = change.get('days', 0)
                            if evt_idx >= 0:
                                _modify_and_splice(
                                    country_id, modify_event_days_in_text,
                                    evt_idx, int(new_days)
                                )
                        self._send_json({'success': True, 'message': f'Updated {len(event_changes)} events'})
                    else:
                        gs_text = save_state['gamestate_text']
                        for change in event_changes:
                            evt_idx = change.get('index', -1)
                            new_days = change.get('days', 0)
                            if evt_idx >= 0:
                                gs_text = modify_event_days_in_text(gs_text, country_id, evt_idx, int(new_days))
                        save_state['gamestate_text'] = gs_text
                        self._send_json({'success': True, 'message': f'Updated {len(event_changes)} events'})

                elif path == '/api/flag':
                    country_id = int(data.get('country_id', 0))
                    flag_data = data.get('flag', {})

                    if save_state['work_dir'] and save_state['manifest']:
                        _modify_and_splice(country_id, modify_flag_in_text_v2, flag_data)
                        self._send_json({'success': True, 'message': 'Flag updated'})
                    else:
                        save_state['gamestate_text'] = modify_flag_in_text_v2(save_state['gamestate_text'], flag_data)
                        self._send_json({'success': True, 'message': 'Flag updated'})

                else:
                    self._send_json({'error': 'Not found'}, 404)

        except Exception as e:
            traceback.print_exc()
            self._send_json({'error': str(e)}, 500)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            if path == '/api/save':
                with _state_lock:
                    _cleanup_all()
                self._send_json({'success': True})
            else:
                self._send_json({'error': 'Not found'}, 404)
        except Exception as e:
            traceback.print_exc()
            self._send_json({'error': str(e)}, 500)

    def log_message(self, format, *args):
        print(f'[SAVE-SERVICE] {args[0]}')


def run_server(port=3001):
    server = ThreadingHTTPServer(('0.0.0.0', port), SaveHandler)
    server.daemon_threads = True
    print(f'Stellaris Save Parser Service running on port {port} '
          f'(split blocks: {os.environ.get("SPLIT_BLOCKS", "default")})')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nShutting down...')
        server.server_close()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3001))
    run_server(port)
