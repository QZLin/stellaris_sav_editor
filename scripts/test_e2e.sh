#!/bin/bash
# End-to-end test: upload -> check split -> get resources -> modify -> verify
set -e

echo '=== 1. Upload ==='
T0=$(date +%s%N)
UPLOAD_RESP=$(curl -s -X POST http://localhost:3001/api/upload \
  --data-binary @/home/z/my-project/download/reference.sav)
T1=$(date +%s%N)
MS=$(( (T1 - T0) / 1000000 ))
echo "Upload took: ${MS}ms"
echo "$UPLOAD_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  Split info: {d.get(\"split_info\", {})}')"
echo "$UPLOAD_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  Player: {d.get(\"player_country_id\")}')"

# Check split files exist
echo ''
echo '=== 2. Check split files ==='
WORK_DIR=$(ls -d /tmp/*/stellaris_split_* 2>/dev/null | head -1)
if [ -n "$WORK_DIR" ]; then
  COUNT=$(ls "$WORK_DIR"/*.txt 2>/dev/null | wc -l)
  echo "Work dir: $WORK_DIR"
  echo "Split files: $COUNT"
  ls -la "$WORK_DIR"/country_0.txt 2>/dev/null | awk '{print "  country_0.txt: "$5" bytes"}'
  ls -la "$WORK_DIR"/species_db_1.txt 2>/dev/null | awk '{print "  species_db_1.txt: "$5" bytes"}'
else
  echo "No work dir found!"
fi

echo ''
echo '=== 3. GET resources (should use split, fast) ==='
T0=$(date +%s%N)
RES_RESP=$(curl -s 'http://localhost:3001/api/resources?country_id=0')
T1=$(date +%s%N)
MS=$(( (T1 - T0) / 1000000 ))
echo "GET resources took: ${MS}ms"
echo "$RES_RESP" | python3 -c "
import sys,json
d=json.load(sys.stdin)
res=d.get('resources',{})
for k in ['energy','minerals','food','alloys']:
    if k in res:
        print(f'  {k}: {res[k][\"value\"]}')"

echo ''
echo '=== 4. PUT resources (should use split, no full re-parse) ==='
T0=$(date +%s%N)
PUT_RESP=$(curl -s -X PUT http://localhost:3001/api/resources \
  -H 'Content-Type: application/json' \
  -d '{"country_id": 0, "resources": {"energy": 99999, "minerals": 50000}}')
T1=$(date +%s%N)
MS=$(( (T1 - T0) / 1000000 ))
echo "PUT resources took: ${MS}ms"
echo "$PUT_RESP"

echo ''
echo '=== 5. GET resources again (verify changes, should be instant) ==='
T0=$(date +%s%N)
RES_RESP2=$(curl -s 'http://localhost:3001/api/resources?country_id=0')
T1=$(date +%s%N)
MS=$(( (T1 - T0) / 1000000 ))
echo "GET resources took: ${MS}ms"
echo "$RES_RESP2" | python3 -c "
import sys,json
d=json.load(sys.stdin)
res=d.get('resources',{})
for k in ['energy','minerals','food','alloys']:
    if k in res:
        print(f'  {k}: {res[k][\"value\"]}')"

echo ''
echo '=== 6. GET events ==='
EVT_RESP=$(curl -s 'http://localhost:3001/api/events?country_id=0')
echo "$EVT_RESP" | python3 -c "
import sys,json
d=json.load(sys.stdin)
evts=d.get('events',[])
print(f'  Events count: {len(evts)}')
for e in evts[:5]:
    print(f'    {e.get(\"event\",\"?\")}: {e.get(\"days\",0)} days')"

echo ''
echo '=== 7. GET flag ==='
FLAG_RESP=$(curl -s 'http://localhost:3001/api/flag?country_id=0')
echo "$FLAG_RESP" | python3 -c "
import sys,json
d=json.load(sys.stdin)
f=d.get('flag',{})
print(f'  Icon: {f.get(\"icon_category\")}/{f.get(\"icon_file\")}')
print(f'  BG: {f.get(\"bg_category\")}/{f.get(\"bg_file\")}')
print(f'  Colors: {f.get(\"colors\")}')"

echo ''
echo '=== 8. PUT flag ==='
PUT_FLAG=$(curl -s -X PUT http://localhost:3001/api/flag \
  -H 'Content-Type: application/json' \
  -d '{"country_id": 0, "flag": {"icon_category": "spherical", "icon_file": "flag_spherical_10.dds", "bg_category": "backgrounds", "bg_file": "flag_BG_05.dds", "colors": ["blue", "white", "null", "null"]}}')
echo "$PUT_FLAG"

# Verify flag change
FLAG_RESP2=$(curl -s 'http://localhost:3001/api/flag?country_id=0')
echo "$FLAG_RESP2" | python3 -c "
import sys,json
d=json.load(sys.stdin)
f=d.get('flag',{})
print(f'  New Icon: {f.get(\"icon_category\")}/{f.get(\"icon_file\")}')
print(f'  New Colors: {f.get(\"colors\")}')"

echo ''
echo '=== 9. Export and verify ==='
T0=$(date +%s%N)
curl -s -X POST http://localhost:3001/api/export -o /tmp/test_export.sav
T1=$(date +%s%N)
MS=$(( (T1 - T0) / 1000000 ))
echo "Export took: ${MS}ms"
python3 -c "
import zipfile
with zipfile.ZipFile('/tmp/test_export.sav') as z:
    gs = z.read('gamestate').decode('utf-8')
    print(f'  Exported gamestate: {len(gs)/1024/1024:.1f} MB')
    # Verify energy was changed
    if 'energy=99999' in gs:
        print('  energy=99999 found in exported file: YES')
    else:
        print('  energy=99999 found in exported file: NO')
    if 'minerals=50000' in gs:
        print('  minerals=50000 found in exported file: YES')
    else:
        print('  minerals=50000 found in exported file: NO')
    # Verify flag change
    if 'flag_spherical_10.dds' in gs:
        print('  New flag icon found: YES')
    else:
        print('  New flag icon found: NO')"

echo ''
echo '=== 10. Cleanup ==='
curl -s -X DELETE http://localhost:3001/api/save
echo 'Done!'
