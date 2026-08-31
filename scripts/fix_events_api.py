import re

with open('/home/z/my-project/mini-services/save-parser/server.py','r') as f:
    content = f.read()

func_code = '''
def get_delayed_events_from_text(text, country_idx):
    """Extract delayed events directly from raw text (fast, no full parse needed)."""
    lines = text.split('\\n')
    state = 'seeking_country'
    country_depth = 0
    country_idx_found = False
    econ_found = False
    in_de = False
    de_depth = 0
    events = []
    current_evt = {}
    for line in lines:
        stripped = line.strip()
        opens = stripped.count('{')
        closes = stripped.count('}')
        if state == 'seeking_country':
            if stripped == 'country={':
                state = 'in_country'
                country_depth = 1
            continue
        if state == 'in_country':
            country_depth += opens - closes
            if country_depth <= 0:
                state = 'seeking_country'
                continue
            if not country_idx_found:
                if re.match(r'^' + r'\\s*' + re.escape(str(country_idx)) + r'=\\{\\s*$', line):
                    country_idx_found = True
                    continue
            if country_idx_found and not econ_found:
                if re.match(r'^\\s*standard_economy_module\\s*=\\{\\s*$', line):
                    econ_found = True
                    continue
            if econ_found and not in_de:
                if re.match(r'^\\s*delayed_event\\s*=\\{\\s*$', line):
                    in_de = True
                    de_depth = 0
                    continue
            if in_de:
                de_depth += opens - closes
                if de_depth <= 0:
                    in_de = False
                    continue
                m = re.match(r'^\\s*event="([^"]+)"', line)
                if m:
                    current_evt = {'event': m.group(1), 'days': 0}
                    continue
                m = re.match(r'^\\s*days=(\\d+)', line)
                if m and current_evt:
                    current_evt['days'] = int(m.group(1))
                    events.append(current_evt)
                    current_evt = {}
                    continue
    return events

'''

# Insert function before class SaveHandler
insert_point = content.find('class SaveHandler:')
if insert_point < 0:
    print('ERROR'); exit(1)
content = content[:insert_point] + func_code + content[insert_point:]

# Fix events GET handler
old = 'get_delayed_events(save_state["gamestate_parsed"], country_id)'
new = 'get_delayed_events_from_text(save_state["gamestate_text"], country_id)'
count = content.count(old)
if count > 0:
    content = content.replace(old, new, 1)
    print(f'Fixed {count} occurrence(s)')
else:
    print('WARNING: old handler not found')

with open('/home/z/my-project/mini-services/save-parser/server.py','w') as f:
    f.write(content)
print('Done')
