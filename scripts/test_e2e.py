import time, json, glob, os, zipfile, sys, threading, subprocess

# Start server in background thread
server_proc = subprocess.Popen(
    [sys.executable, 'server.py'],
    cwd='/home/z/my-project/mini-services/save-parser',
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT
)

# Wait for server to be ready
import urllib.request
for _ in range(20):
    try:
        urllib.request.urlopen('http://127.0.0.1:3001/api/status')
        break
    except:
        time.sleep(0.5)
else:
    print('Server failed to start!')
    print(server_proc.stdout.read().decode())
    sys.exit(1)

print('Server is ready')

import requests

BASE = 'http://127.0.0.1:3001'

# 1. Upload
print('=== 1. Upload ===')
t0 = time.time()
with open('/home/z/my-project/download/reference.sav', 'rb') as f:
    resp = requests.post(BASE + '/api/upload', data=f.read(), headers={'Content-Type': 'application/octet-stream'})
t1 = time.time()
d = resp.json()
print(f'Upload took: {(t1-t0)*1000:.0f}ms')
print(f'Split info: {d.get("split_info", {})}')
print(f'Player: {d.get("player_country_id")}')
assert d['success'], f'Upload failed: {d}'

# Check work dir
work_dirs = glob.glob('/tmp/*/stellaris_split_*')
if work_dirs:
    files = os.listdir(work_dirs[0])
    txt_files = [f for f in files if f.endswith('.txt')]
    print(f'Work dir: {work_dirs[0]}')
    print(f'Split files: {len(txt_files)}')

# 2. GET resources
print('\n=== 2. GET resources ===')
t0 = time.time()
resp = requests.get(BASE + '/api/resources?country_id=0')
t1 = time.time()
res = resp.json()['resources']
print(f'Time: {(t1-t0)*1000:.0f}ms')
for k in ['energy','minerals','food','alloys']:
    print(f'  {k}: {res[k]["value"]}')

# 3. PUT resources
print('\n=== 3. PUT resources ===')
t0 = time.time()
resp = requests.put(BASE + '/api/resources', json={'country_id':0,'resources':{'energy':99999,'minerals':50000}})
t1 = time.time()
print(f'Time: {(t1-t0)*1000:.0f}ms')
print(resp.json())

# 4. GET resources again (verify)
print('\n=== 4. GET resources after PUT ===')
t0 = time.time()
resp = requests.get(BASE + '/api/resources?country_id=0')
t1 = time.time()
res = resp.json()['resources']
print(f'Time: {(t1-t0)*1000:.0f}ms')
for k in ['energy','minerals','food','alloys']:
    print(f'  {k}: {res[k]["value"]}')

if res['energy']['value'] == 99999.0 and res['minerals']['value'] == 50000.0:
    print('  VERIFIED: energy=99999, minerals=50000')
else:
    print(f'  FAIL: expected energy=99999 minerals=50000')

# 5. GET events
print('\n=== 5. Events ===')
resp = requests.get(BASE + '/api/events?country_id=0')
d = resp.json()
evts = d.get('events', [])
print(f'Events: {len(evts)}')
for e in evts[:3]:
    print(f'  {e.get("event","?")}: {e.get("days",0)} days')

# 6. GET flag
print('\n=== 6. GET flag ===')
resp = requests.get(BASE + '/api/flag?country_id=0')
flag = resp.json()['flag']
print(f'Icon: {flag.get("icon_category")}/{flag.get("icon_file")}')
print(f'Colors: {flag.get("colors")}')

# 7. PUT flag
print('\n=== 7. PUT flag ===')
resp = requests.put(BASE + '/api/flag', json={
    'country_id': 0, 'flag': {
        'icon_category': 'spherical', 'icon_file': 'flag_spherical_10.dds',
        'bg_category': 'backgrounds', 'bg_file': 'flag_BG_05.dds',
        'colors': ['blue', 'white', 'null', 'null']
    }
})
print(resp.json())

# Verify flag change
resp = requests.get(BASE + '/api/flag?country_id=0')
flag = resp.json()['flag']
print(f'New Icon: {flag.get("icon_category")}/{flag.get("icon_file")}')
if flag['icon_file'] == 'flag_spherical_10.dds':
    print('  VERIFIED: flag changed')
else:
    print(f'  FAIL: {flag["icon_file"]}')

# 8. Export
print('\n=== 8. Export ===')
resp = requests.post(BASE + '/api/export')
with open('/tmp/test_export.sav', 'wb') as f:
    f.write(resp.content)
with zipfile.ZipFile('/tmp/test_export.sav') as z:
    gs = z.read('gamestate').decode('utf-8')
    print(f'Size: {len(gs)/1024/1024:.1f} MB')
    print(f'  energy=99999: {"energy=99999" in gs}')
    print(f'  minerals=50000: {"minerals=50000" in gs}')
    print(f'  flag_spherical_10: {"flag_spherical_10.dds" in gs}')

# Cleanup
requests.delete(BASE + '/api/save')

# Stop server
server_proc.terminate()
server_proc.wait()

print('\n=== ALL TESTS PASSED ===')