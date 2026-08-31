import re

text = '''delayed_event={
	event="test.1"
	days=50
	scope={
	}
}
'''

country_idx = 0
event_index = 0
new_days = 1

lines = text.split('\n')
state = 'seeking_country'
country_depth = 0
country_idx_found = False
econ_found = False
in_delayed_events = False
de_depth = 0
current_event_idx = -1
result_lines = []
modified = False

for i, line in enumerate(lines):
    if modified:
        result_lines.append(line)
        continue
    stripped = line.strip()
    opens = stripped.count('{')
    closes = stripped.count('}')
    if state == 'seeking_country':
        if stripped == 'country={':
            state = 'in_country'
            country_depth = 1
            print(f'L{i}: >> country found')
        result_lines.append(line)
        continue

    if state == 'in_country':
        country_depth += opens - closes
        if country_depth <= 0:
            state = 'seeking_country'
            result_lines.append(line)
            continue
        if not country_idx_found:
            pat = re.compile(r'^\s*' + re.escape('0') + r'=\{\s*$')
            if pat.match(line):
                country_idx_found = True
                print(f'L{i}: >> country 0 found')
            result_lines.append(line)
            continue
        if country_idx_found and not econ_found:
            if re.match(r'^\s*standard_economy_module\s*=\{\s*$', line):
                econ_found = True
                print(f'L{i}: >> econ found')
            result_lines.append(line)
            continue
        if econ_found and not in_delayed_events:
            if re.match(r'^\s*delayed_event\s*=\{\s*$', line):
                in_delayed_events = True
                de_depth = 0
                print(f'L{i}: >> delayed_event found')
            result_lines.append(line)
            continue

    if in_delayed_events and not modified:
        de_depth += opens - closes
        if de_depth <= 0:
            in_delayed_events = False
            print(f'L{i}: >> de closed')
            result_lines.append(line)
            continue
        if de_depth == 1 and re.match(r'^\s*event=', line):
            current_event_idx += 1
            print(f'L{i}: >> EVENT #{current_event_idx}')
        if current_event_idx == event_index and re.match(r'^\s*days=', line):
        indent = line[:len(line) - len(line.lstrip())
        result_lines.append(f'{indent}days={new_days}')
            modified = True
            print(f'L{i}: >> MODIFIED')
            continue
    result_lines.append(line)

print('\nResult:')
for l in result_lines:
    print(l)
