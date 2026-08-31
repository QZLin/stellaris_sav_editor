with open('/home/z/my-project/mini-services/save-parser/server.py','r') as f:
    content = f.read()
lines = content.split('\n')
for i, line in enumerate(lines):
    if 'in_delayed_events = True' in line and i+1 < len(lines) and 'de_depth = 1' in lines[i+1]:
        lines[i+1] = lines[i+1].replace('de_depth = 1', 'de_depth = 0')
        print(f'Fixed at line {i+2}')
        break
with open('/home/z/my-project/mini-services/save-parser/server.py','w') as f:
    f.write('\n'.join(lines))
print('Done')