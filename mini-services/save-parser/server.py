"""
Stellaris Save File Parser - HTTP Service
Provides REST API for parsing, viewing, and modifying Stellaris .sav files.
Optimization: uses save_splitter.py to pre-split gamestate into per-country/
per-species files, so GET/PUT per-entity operations work on ~300KB instead
of 44MB. No full re-parse after modifications.
"""

import os
import sys
import json
import zipfile
import tempfile
import re
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from clausewitz_parser import parse_clausewitz
from save_splitter import (
    split_gamestate, read_split_file, write_split_file,
    splice_into_gamestate, update_parsed_sub_block,
    cleanup_work_dir,
)


# In-memory save data store
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
}


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
    'volatile_motes': '易爆微粒',
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


def find_player_country_id(gamestate):
    """Find the player's country index."""
    player = gamestate.get('player')
    if not player:
        return 0
    if isinstance(player, dict):
        items = player.get(None, [])
        if items and isinstance(items, list) and len(items) > 0:
            first = items[0]
            if isinstance(first, dict) and 'country' in first:
                return int(first['country'])
    return 0


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

    # Try split file
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
# These operate on SPLIT FILE text (small, ~300KB) instead of full 44MB.


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

        stripped = line.strip()
        opens = stripped.count('{')
        closes = stripped.count('}')

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
    """Modify the game date in text."""
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
        stripped = line.strip()
        opens = stripped.count('{')
        closes = stripped.count('}')

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
        stripped = line.strip()
        opens = stripped.count('{')
        closes = stripped.count('}')

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


def modify_flag_in_text(text, flag_data):
    """Modify flag data in a country's split file text.
    
    flag_data = {
        icon_category, icon_file, bg_category, bg_file, colors: [c1, c2, c3, c4]
    }
    """
    lines = text.split('\n')
    state = 'seeking_flag'
    flag_depth = 0
    result_lines = []
    in_colors = False
    colors_depth = 0
    colors_emitted = False
    icon_done = False
    bg_done = False

    for line in lines:
        stripped = line.strip()
        opens = stripped.count('{')
        closes = stripped.count('}')

        if state == 'seeking_flag':
            if re.match(r'^\s*flag=\{\s*$', line):
                state = 'in_flag'
                flag_depth = 1
            result_lines.append(line)
            continue

        if state == 'in_flag':
            flag_depth += opens - closes

            # Track colors block
            if in_colors:
                colors_depth += opens - closes
                if colors_depth <= 0:
                    in_colors = False
                # Skip original color lines (we'll emit our own)
                continue

            # Check for colors={
            if re.match(r'^\s*colors=\{\s*$', line):
                colors = flag_data.get('colors', [])
                indent = line[:len(line) - len(line.lstrip())]
                # Emit the colors block with new values
                result_lines.append(f'{indent}colors={{')
                for c in colors:
                    result_lines.append(f'{indent}\t"{c}"')
                result_lines.append(f'{indent}}}')
                colors_emitted = True
                in_colors = True
                colors_depth = opens - closes
                if colors_depth <= 0:
                    in_colors = False
                continue

            # Modify icon
            if not icon_done and re.match(r'^\s*icon=\{\s*$', line):
                indent = line[:len(line) - len(line.lstrip())]
                result_lines.append(f'{indent}icon={{')
                result_lines.append(f'{indent}\tcategory="{flag_data.get("icon_category", "")}"')
                result_lines.append(f'{indent}\tfile="{flag_data.get("icon_file", "")}"')
                # Skip original icon content until depth returns to flag+1
                icon_done = True
                # We need to skip lines until the closing } of icon
                # The depth tracking will handle this - we're at flag_depth + opens already
                # But we already added the opens to flag_depth... let me handle differently
                # Actually let me use a sub-state approach
                result_lines.append(line)  # keep the original line too for now
                continue

            # Modify background
            if not bg_done and re.match(r'^\s*background=\{\s*$', line):
                indent = line[:len(line) - len(line.lstrip())]
                result_lines.append(f'{indent}background={{')
                result_lines.append(f'{indent}\tcategory="{flag_data.get("bg_category", "")}"')
                result_lines.append(f'{indent}\tfile="{flag_data.get("bg_file", "")}"')
                bg_done = True
                # Same issue with skipping original content
                result_lines.append(line)
                continue

            if flag_depth <= 0:
                state = 'done'

            result_lines.append(line)
            continue

        result_lines.append(line)

    return '\n'.join(result_lines)


def modify_flag_in_text_v2(text, flag_data):
    """Simpler flag modification: use regex to replace specific fields.
    
    This replaces the first occurrence of each flag field within the flag={...} block.
    Works on the country's split file text (small).
    """
    # Find the flag block boundaries
    lines = text.split('\n')
    flag_start = -1
    flag_end = -1
    depth = 0
    for i, line in enumerate(lines):
        if re.match(r'^\s*flag=\{\s*$', line):
            flag_start = i
            depth = 1
            continue
        if flag_start >= 0:
            depth += line.count('{') - line.count('}')
            if depth <= 0:
                flag_end = i
                break

    if flag_start < 0 or flag_end < 0:
        return text

    # Rebuild the flag block
    indent = '\t'
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

    # Replace lines[flag_start:flag_end+1] with new_flag_lines
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

    # Splice into full gamestate
    save_state['gamestate_text'] = splice_into_gamestate(
        save_state['gamestate_text'], manifest, 'country', cid_str, new_text
    )

    # Update parsed cache
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
    })


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
                loaded = save_state['sav_path'] is not None
                self._send_json({
                    'loaded': loaded,
                    'filename': os.path.basename(save_state['sav_path']) if loaded else None,
                })

            elif path == '/api/meta':
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
                if not save_state['gamestate_parsed']:
                    self._send_json({'error': 'No save file loaded'}, 400)
                    return
                countries = get_countries_list(save_state['gamestate_parsed'])
                player_idx = find_player_country_id(save_state['gamestate_parsed'])
                self._send_json({
                    'countries': countries,
                    'player_country_id': str(player_idx),
                })

            elif path == '/api/resources':
                country_id = params.get('country_id', ['0'])[0]
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
                if not save_state['gamestate_parsed']:
                    self._send_json({'error': 'No save file loaded'}, 400)
                    return
                species_db = save_state['gamestate_parsed'].get('species_db', {})
                total = len(species_db) if isinstance(species_db, dict) else 0
                species = get_species_list(save_state['gamestate_parsed'], limit=50)
                self._send_json({'species': species, 'total': total})

            elif path == '/api/events':
                if not save_state['gamestate_text']:
                    self._send_json({'error': 'No save file loaded'}, 400)
                    return
                country_id = int(params.get('country_id', [0])[0])
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
                country_id = int(params.get('country_id', [0])[0])
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
                if not save_state['gamestate_parsed']:
                    self._send_json({'error': 'No save file loaded'}, 400)
                    return
                date = save_state['gamestate_parsed'].get('date', '')
                self._send_json({'date': date})

            elif path == '/api/stats':
                if not save_state['gamestate_parsed']:
                    self._send_json({'error': 'No save file loaded'}, 400)
                    return
                gs = save_state['gamestate_parsed']
                player_idx = find_player_country_id(gs)
                countries = gs.get('country', {})
                c_key = str(player_idx)
                country = countries.get(c_key, {}) if isinstance(countries, dict) else {}
                self._send_json({
                    'date': gs.get('date', ''),
                    'tick': gs.get('tick', 0),
                    'num_species': len(gs.get('species_db', {})) if isinstance(gs.get('species_db'), dict) else 0,
                    'num_countries': len(countries) if isinstance(countries, dict) else 0,
                    'player_country_id': str(player_idx),
                    'tech_count': get_tech_count(player_idx),
                    'fleet_size': country.get('fleet_size', 0) if isinstance(country, dict) else 0,
                    'military_power': float(country.get('military_power', 0)) if isinstance(country, dict) else 0,
                    'empire_size': country.get('empire_size', 0) if isinstance(country, dict) else 0,
                    'owned_planets_count': len(country.get('owned_planets', {}).get(None, [])) if isinstance(country, dict) else 0,
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

                # Full parse of gamestate (needed for global data like countries list)
                gamestate_parsed = {}
                try:
                    print('[UPLOAD] Starting full gamestate parse...')
                    gamestate_parsed = parse_clausewitz(gamestate_text) if gamestate_text else {}
                    print('[UPLOAD] Full parse complete')
                except Exception as e:
                    print(f'[UPLOAD] Warning: Full gamestate parse failed: {e}')

                save_state['sav_path'] = tmp.name
                save_state['meta_text'] = meta_text
                save_state['gamestate_text'] = gamestate_text
                save_state['meta_parsed'] = meta_parsed
                save_state['gamestate_parsed'] = gamestate_parsed
                save_state['country_parsed_cache'] = {}

                # Pre-split the gamestate for fast per-entity access
                work_dir = os.path.join(os.path.dirname(tmp.name), f'stellaris_split_{os.path.basename(tmp.name)}')
                try:
                    print('[UPLOAD] Starting gamestate split...')
                    manifest = split_gamestate(gamestate_text, work_dir)
                    save_state['work_dir'] = work_dir
                    save_state['manifest'] = manifest
                    print('[UPLOAD] Split complete')
                except Exception as e:
                    print(f'[UPLOAD] Warning: Split failed: {e}')
                    traceback.print_exc()
                    # Continue without split - will fall back to full text
                    save_state['work_dir'] = None
                    save_state['manifest'] = None

                player_idx = find_player_country_id(gamestate_parsed)
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
                })

            elif path == '/api/export':
                if not save_state['sav_path']:
                    self._send_json({'error': 'No save file loaded'}, 400)
                    return

                export_tmp = tempfile.NamedTemporaryFile(suffix='.sav', delete=False)
                export_tmp.close()

                with zipfile.ZipFile(export_tmp.name, 'w', zipfile.ZIP_DEFLATED) as zout:
                    zout.writestr('meta', save_state['meta_text'].encode('utf-8'))
                    zout.writestr('gamestate', save_state['gamestate_text'].encode('utf-8'))

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
                # Date is top-level, no split needed; quick re-parse of meta only
                try:
                    save_state['meta_parsed'] = parse_clausewitz(save_state['meta_text'])
                except:
                    pass
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
                except:
                    pass
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
                    save_state['gamestate_text'] = modify_flag_in_text_v2(save_state['gamestate_text'], country_id, flag_data)
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
                _cleanup_all()
                self._send_json({'success': True})
            else:
                self._send_json({'error': 'Not found'}, 404)
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def log_message(self, format, *args):
        print(f'[SAVE-SERVICE] {args[0]}')


def run_server(port=3001):
    server = HTTPServer(('0.0.0.0', port), SaveHandler)
    print(f'Stellaris Save Parser Service running on port {port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nShutting down...')
        server.server_close()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3001))
    run_server(port)
