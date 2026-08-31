"""
Stellaris Save File Parser - HTTP Service
Provides REST API for parsing, viewing, and modifying Stellaris .sav files.
"""

import os
import sys
import json
import zipfile
import tempfile
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import traceback

from clausewitz_parser import parse_clausewitz


# In-memory save data store
save_state = {
    'sav_path': None,
    'meta_text': None,
    'gamestate_text': None,
    'meta_parsed': None,
    'gamestate_parsed': None,
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


def extract_save(filepath: str):
    """Extract .sav (ZIP) and read meta + gamestate texts."""
    with zipfile.ZipFile(filepath, 'r') as z:
        names = z.namelist()
        meta_text = z.read('meta').decode('utf-8') if 'meta' in names else ''
        gamestate_text = z.read('gamestate').decode('utf-8') if 'gamestate' in names else ''
    return meta_text, gamestate_text


def find_player_country_id(gamestate: dict) -> int:
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


def get_country_resources(gamestate: dict, country_idx: int) -> dict:
    """Extract resources for a specific country from modules.standard_economy_module."""
    countries = gamestate.get('country', {})
    c_key = str(country_idx)
    if c_key not in countries:
        return {}
    country = countries[c_key]
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


def get_countries_list(gamestate: dict) -> list:
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
        gov_type = country.get('type', '')
        is_player = False
        result.append({
            'id': str(idx),
            'name': str(name_data),
            'type': str(gov_type),
            'custom_name': bool(country.get('custom_name', False)),
            'capital': country.get('capital', ''),
            'military_power': float(country.get('military_power', 0)),
            'economy_power': float(country.get('economy_power', 0)),
            'tech_power': float(country.get('tech_power', 0)),
            'fleet_size': country.get('fleet_size', 0),
        })
    return result


def get_species_list(gamestate: dict, limit: int = 50) -> list:
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


def get_budget_info(gamestate: dict, country_idx: int) -> dict:
    """Get budget/income info for a country."""
    countries = gamestate.get('country', {})
    c_key = str(country_idx)
    if c_key not in countries:
        return {}
    country = countries[c_key]
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


def get_tech_count(gamestate: dict, country_idx: int) -> int:
    """Get number of researched technologies."""
    countries = gamestate.get('country', {})
    c_key = str(country_idx)
    if c_key not in countries:
        return 0
    country = countries[c_key]
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


def _find_block_by_path(text_lines: list, path_steps: list) -> tuple:
    """
    Navigate through nested blocks to find the target block.
    Returns (start_line_idx, end_line_idx, indent_level) or (-1,-1,-1) if not found.
    """
    depth = 0
    step_idx = 0
    current_step = path_steps[0]
    block_start = -1

    for i, line in enumerate(text_lines):
        stripped = line.strip()

        # Track depth via braces
        for ch in stripped:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1

        if step_idx < len(path_steps):
 # Check if this line matches the current step
            pattern = re.compile(rf'^\s*{re.escape(str(current_step))}\s*[=\{{]')
            if pattern.match(line):
                if step_idx == 0:
                    block_start = i
                step_idx += 1
                if step_idx < len(path_steps):
                    current_step = path_steps[step_idx]
                else:
                    # Found the target block
                    # Return the block content range (after the opening brace)
                    return (block_start, i, depth)

    return (-1, -1, -1)


def modify_resource_in_text(text: str, country_idx: int, resource_key: str, new_value: float) -> str:
    """Modify a single resource value directly in the raw gamestate text."""
    lines = text.split('\n')

    # State machine to navigate: country={ 0={ ... modules={ standard_economy_module={ resources={ resource_key=VALUE } } } } }
    state = 'seeking_country'
    country_depth = 0
    country_idx_found = False
    module_depth = 0
    econ_found = False
    resource_block_depth = 0
    in_resource_block = False
    result_lines = []
    modified = False

    for line in lines:
        if modified:
            result_lines.append(line)
            continue

        stripped = line.strip()

        # Count braces on this line
        opens = stripped.count('{')
        closes = stripped.count('}')

        if state == 'seeking_country':
            if stripped == 'country={':
                state = 'in_country'
                country_depth = 1
            result_lines.append(line)
            continue

        if state == 'in_country':
            country_depth += opens - closes

            if country_depth <= 0:
                state = 'seeking_country'
                result_lines.append(line)
                continue

            if not country_idx_found:
                # Look for the specific country index
                idx_pat = re.compile(r'^\s*' + re.escape(str(country_idx)) + r'=\{\s*$')
                if idx_pat.match(line):
                    country_idx_found = True
                    result_lines.append(line)
                    continue

            if country_idx_found and not econ_found:
                # Look for standard_economy_module
                if re.match(r'^\s*standard_economy_module\s*={\s*$', line):
                    econ_found = True
                    result_lines.append(line)
                    continue

            if econ_found and not in_resource_block:
                if re.match(r'^\s*resources\s*={\s*$', line):
                    in_resource_block = True
                    resource_block_depth = 1
                    result_lines.append(line)
                    continue

            if in_resource_block:
                resource_block_depth += opens - closes

                if resource_block_depth <= 0:
                    in_resource_block = False
                    result_lines.append(line)
                    continue

                # Check for the resource key
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


def modify_date_in_text(text: str, new_date: str) -> str:
    """Modify the game date in text."""
    pattern = re.compile(r'^(date=")\d{4}\.\d{2}\.\d{2}(")', re.MULTILINE)
    return pattern.sub(f'\\g<1>{new_date}\\g<2>', text, count=1)


def modify_name_in_text(text: str, old_name: str, new_name: str) -> str:
    """Modify the empire name in gamestate text."""
    # In gamestate, the name is in the first country's name block
    # Format: name={\n\tkey="OLDNAME"\n}
    pattern = re.compile(r'^(name=\{\n\s*key=")' + re.escape(old_name) + r'(")', re.MULTILINE)
    result = pattern.sub(f'\\g<1>{new_name}\\g<2>', text, count=1)
    return result


def modify_name_in_meta(text: str, new_name: str) -> str:
    """Modify the empire name in meta text."""
    pattern = re.compile(r'^(name=")' + r'[^"]*' + r'(")', re.MULTILINE)
    return pattern.sub(f'\\g<1>{new_name}\\g<2>', text, count=1)


class SaveHandler(BaseHTTPRequestHandler):
    """HTTP request handler for save file operations."""

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, filepath: str, filename: str):
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

    def _read_body(self) -> bytes:
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
                if not save_state['gamestate_parsed']:
                    self._send_json({'error': 'No save file loaded'}, 400)
                    return
                country_id = params.get('country_id', ['0'])[0]
                resources = get_country_resources(save_state['gamestate_parsed'], int(country_id))
                budget = get_budget_info(save_state['gamestate_parsed'], int(country_id))
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
                    'tech_count': get_tech_count(gs, player_idx),
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

                gamestate_parsed = {}
                try:
                    gamestate_parsed = parse_clausewitz(gamestate_text) if gamestate_text else {}
                except Exception as e:
                    print(f'Warning: Full gamestate parse failed: {e}')

                save_state['sav_path'] = tmp.name
                save_state['meta_text'] = meta_text
                save_state['gamestate_text'] = gamestate_text
                save_state['meta_parsed'] = meta_parsed
                save_state['gamestate_parsed'] = gamestate_parsed

                player_idx = find_player_country_id(gamestate_parsed)
                meta_name = meta_parsed.get('name', '')
                meta_date = meta_parsed.get('date', '')

                dlcs = meta_parsed.get('required_dlcs', {})
                if isinstance(dlcs, dict):
                    dlcs = dlcs.get(None, [])
                if not isinstance(dlcs, list):
                    dlcs = [dlcs]

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
                })

            elif path == '/api/export':
                if not save_state['sav_path']:
                    self._send_json({'error': 'No save file loaded'}, 400)
                    return

                # Create modified .sav file
                export_tmp = tempfile.NamedTemporaryFile(suffix='.sav', delete=False)
                export_tmp.close()

                with zipfile.ZipFile(export_tmp.name, 'w', zipfile.ZIP_DEFLATED) as zout:
                    zout.writestr('meta', save_state['meta_text'].encode('utf-8'))
                    zout.writestr('gamestate', save_state['gamestate_text'].encode('utf-8'))

                self._send_file(export_tmp.name, 'modified_save.sav')

                # Clean up after sending
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
                if not save_state['gamestate_text']:
                    self._send_json({'error': 'No save file loaded'}, 400)
                    return

                country_id = data.get('country_id', 0)
                resources = data.get('resources', {})

                gs_text = save_state['gamestate_text']
                for key, value in resources.items():
                    try:
                        gs_text = modify_resource_in_text(gs_text, int(country_id), key, float(value))
                    except (ValueError, TypeError):
                        pass

                save_state['gamestate_text'] = gs_text

                # Re-parse to update cache
                try:
                    save_state['gamestate_parsed'] = parse_clausewitz(gs_text)
                except:
                    pass

                self._send_json({'success': True, 'message': f'Updated {len(resources)} resources'})

            elif path == '/api/date':
                if not save_state['gamestate_text']:
                    self._send_json({'error': 'No save file loaded'}, 400)
                    return

                new_date = data.get('date', '')
                if not re.match(r'^\d{4}\.\d{2}\.\d{2}$', new_date):
                    self._send_json({'error': 'Invalid date format, use YYYY.MM.DD'}, 400)
                    return

                save_state['gamestate_text'] = modify_date_in_text(save_state['gamestate_text'], new_date)
                save_state['meta_text'] = modify_date_in_text(save_state['meta_text'], new_date)

                try:
                    save_state['gamestate_parsed'] = parse_clausewitz(save_state['gamestate_text'])
                    save_state['meta_parsed'] = parse_clausewitz(save_state['meta_text'])
                except:
                    pass

                self._send_json({'success': True, 'date': new_date})

            elif path == '/api/name':
                if not save_state['gamestate_text']:
                    self._send_json({'error': 'No save file loaded'}, 400)
                    return

                new_name = data.get('name', '')
                old_name = save_state['meta_parsed'].get('name', '') if save_state['meta_parsed'] else ''

                if old_name:
                    save_state['gamestate_text'] = modify_name_in_text(save_state['gamestate_text'], old_name, new_name)
                save_state['meta_text'] = modify_name_in_meta(save_state['meta_text'], new_name)

                try:
                    save_state['gamestate_parsed'] = parse_clausewitz(save_state['gamestate_text'])
                    save_state['meta_parsed'] = parse_clausewitz(save_state['meta_text'])
                except:
                    pass

                self._send_json({'success': True, 'name': new_name})

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
                if save_state['sav_path'] and os.path.exists(save_state['sav_path']):
                    os.unlink(save_state['sav_path'])
                save_state['sav_path'] = None
                save_state['meta_text'] = None
                save_state['gamestate_text'] = None
                save_state['meta_parsed'] = None
                save_state['gamestate_parsed'] = None
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
