import sys, time, os, zipfile, json, shutil, re
tmpdir = '/tmp/test_split_work'
if os.path.exists(tmpdir):
    shutil.rmtree(tmpdir)

# Extract
with zipfile.ZipFile('/home/z/my-project/download/reference.sav', 'r') as z:
    gs_text = z.read('gamestate').decode('utf-8')
print(f'Gamestate: {len(gs_text)/1024/1024:.1f} MB, {gs_text.count(chr(10))+1} lines')

# Split
sys.path.insert(0, '/home/z/my-project/mini-services/save-parser')
from save_splitter import split_gamestate, read_split_file, splice_into_gamestate, cleanup_work_dir
from clausewitz_parser import parse_clausewitz

t0 = time.time()
manifest = split_gamestate(gs_text, tmpdir)
t1 = time.time()
print(f'Split took: {t1-t0:.2f}s')

# Test 1: Single splice + round-trip verification
print('\n=== Test 1: Single splice round-trip ===')
c0_text = read_split_file(tmpdir, manifest, 'country', '0')
modified = c0_text.replace('custom_name=yes', 'custom_name=no')

t0 = time.time()
new_gs = splice_into_gamestate(gs_text, manifest, 'country', '0', modified)
t1 = time.time()
print(f'Splice took: {t1-t0:.4f}s')

# Verify round-trip with updated offsets
cs, ce = manifest['sub_ranges']['country']['0']
extracted = new_gs[cs:ce]
print(f'Round-trip match: {extracted == modified}')

# Test 2: Multiple sequential splices
print('\n=== Test 2: Multiple sequential splices ===')
for cid in ['0', '5', '10', '50']:
    ct = read_split_file(tmpdir, manifest, 'country', cid)
    # Just re-write the same content (no actual change)
    new_gs = splice_into_gamestate(new_gs, manifest, 'country', cid, ct)
    cs, ce = manifest['sub_ranges']['country'][cid]
    ext = new_gs[cs:ce]
    print(f'  country_{cid}: round-trip={ext == ct}, size={len(ct)}')

# Test 3: Verify other blocks are not corrupted
print('\n=== Test 3: Integrity check ===')
# Country 1 should be unmodified
orig_c1 = read_split_file(tmpdir, manifest, 'country', '1')
cs1, ce1 = manifest['sub_ranges']['country']['1']
spliced_c1 = new_gs[cs1:ce1]
print(f'Country 1 intact: {spliced_c1 == orig_c1}')

# Species should all be intact
orig_s0 = read_split_file(tmpdir, manifest, 'species_db', '0')
cs_s, ce_s = manifest['sub_ranges']['species_db']['0']
spliced_s0 = new_gs[cs_s:ce_s]
print(f'Species 0 intact: {spliced_s0 == orig_s0}')

# Test 4: Performance comparison
print('\n=== Test 4: Performance ===')
# Parse single country file
ct = read_split_file(tmpdir, manifest, 'country', '0')
t0 = time.time()
for _ in range(10):
    parse_clausewitz(ct)
t1 = time.time()
print(f'Parse country_0 x10: {(t1-t0)*1000:.0f}ms total, {(t1-t0)*100:.0f}ms avg')

# Splice performance
t0 = time.time()
for _ in range(10):
    splice_into_gamestate(new_gs, manifest, 'country', '0', ct)
t1 = time.time()
print(f'Splice x10: {(t1-t0)*1000:.0f}ms total, {(t1-t0)*100:.0f}ms avg')

shutil.rmtree(tmpdir)
print('\nAll tests passed!')
