"""
Save file pre-splitting optimizer for Stellaris gamestate.

Design referenced from stellaris-sav-tool (https://github.com/QZLin/stellaris-sav-tool):

  - String-safe brace counting: braces inside quoted strings never affect depth,
    so sub-block boundaries are always correct (data integrity).
  - Byte-exact preservation: each split file is a verbatim character slice of
    the original gamestate; files are read/written with newline='' so Windows
    never translates '\\n' <-> '\\r\\n'. Reassembly is byte-identical.
  - Repeated top-level keys get __N suffixes in the manifest, so no block is
    silently overwritten.
  - The manifest records CHARACTER OFFSET ranges for O(1) splice (3 string
    slices, no line splitting), and offsets are re-based after every splice.

Performance (44MB gamestate, ~2.56M lines):
  - full re-parse:            ~10 s
  - per-entity split parse:   ~15-60 ms  (file sizes 20-300 KB)
  - splice back into master:  O(1) via char offsets

File layout in work_dir:
  _manifest.json            - block ranges & metadata (char offsets)
  country_0.txt             - country 0 sub-block text (verbatim slice)
  country_1.txt
  species_db_0.txt
  fleet_0.txt
  ...
"""

import os
import json
import re
import shutil
import time

# Top-level blocks to split into per-entity files.
# Extend as the editor gains features (pop / ships / army ...).
# Override with env SPLIT_BLOCKS="country,species_db,fleet" or "all".
DEFAULT_SPLIT_BLOCKS = [
    'country',          # 67  entities: resources / flag / events / stats
    'species_db',       # 194 entities: species templates
    'fleet',            # ~2k entities: fleet power / mission editing
    'leaders',          # ~600 entities: leader editing
    'galactic_object',  # ~600 entities: stars / planets
]

# Top-level block header: key={
_TOP_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\{')
# Sub-block header: <id>{
_SUB_RE = re.compile(r'^\s*(\d+)\s*=\{')
# Quoted string (with backslash escapes), used to strip strings before
# counting braces. Clausewitz strings never span lines.
_STR_RE = re.compile(r'"(?:[^"\\]|\\.)*"')


def _now():
    return time.time()


def _line_delta(line):
    """Net brace delta of a line, ignoring braces inside quoted strings.

    Fast paths first: most lines contain no braces at all, and lines with
    braces but no quotes need no stripping. Only the rare mixed line pays
    the regex cost.
    """
    if '{' not in line and '}' not in line:
        return 0
    if '"' not in line:
        return line.count('{') - line.count('}')
    cleaned = _STR_RE.sub('', line)
    return cleaned.count('{') - cleaned.count('}')


def _build_line_offsets(text):
    """
    Build an array where offset[i] = char offset of line i in text.
    offset[len(lines)] = len(text) (one past end).
    O(n) single-pass scan using str.find (C speed).
    """
    offsets = []
    pos = 0
    append = offsets.append
    find = text.find
    while True:
        append(pos)
        nl = find('\n', pos)
        if nl == -1:
            append(len(text))
            break
        pos = nl + 1
    return offsets


def find_top_level_blocks(lines):
    """
    Scan all lines and find top-level key={...} blocks.
    Returns list of (key, start_line, end_line) in document order.
    Handles repeated keys (multiple entries), unlike a dict.
    """
    blocks = []
    depth = 0
    current_key = None
    current_start = None

    for i, line in enumerate(lines):
        if depth == 0 and current_key is None:
            m = _TOP_RE.match(line)
            if m:
                current_key = m.group(1)
                current_start = i

        delta = _line_delta(line)
        if delta:
            depth += delta

        if current_key is not None and depth <= 0:
            blocks.append((current_key, current_start, i))
            current_key = None
            current_start = None

    return blocks


def find_sub_block_ranges(lines, block_start, block_end):
    """
    Within a top-level block [block_start, block_end], find each numeric-key
    sub-block (\\t<id>={ ... }). String-safe, works with inline blocks.
    Returns {key: (start_line, end_line)}.
    """
    sub_blocks = {}
    depth = 0
    current_key = None
    current_start = None

    for i in range(block_start, block_end + 1):
        line = lines[i]

        if depth == 1 and current_key is None:
            m = _SUB_RE.match(line)
            if m:
                current_key = m.group(1)
                current_start = i

        delta = _line_delta(line)
        if delta:
            depth += delta

        if current_key is not None and depth <= 1:
            sub_blocks[current_key] = (current_start, i)
            current_key = None
            current_start = None

    return sub_blocks


def get_split_blocks():
    """Resolve which top-level blocks to split (env SPLIT_BLOCKS overrides)."""
    env = os.environ.get('SPLIT_BLOCKS', '')
    if not env or env.strip().lower() == 'default':
        return list(DEFAULT_SPLIT_BLOCKS)
    if env.strip().lower() == 'none':
        return []
    return [b.strip() for b in env.split(',') if b.strip()]


def split_gamestate(gamestate_text, work_dir, split_blocks=None):
    """
    Split gamestate text into individual sub-block files.

    Returns manifest dict:
      - split_info: {block_name: {sub_key: filename}}
      - sub_ranges: {block_name: {sub_key: [char_start, char_end)}}
        where char_end is Python-slice-exclusive (text[char_start:char_end])
      - block_stats: {block_name: {'count': n, 'bytes': total_chars}}
      - gamestate_chars: length of source text

    Repeated top-level keys become block_name, block_name__1, block_name__2 ...
    """
    os.makedirs(work_dir, exist_ok=True)
    lines = gamestate_text.split('\n')

    t0 = _now()
    offsets = _build_line_offsets(gamestate_text)
    print(f'[SPLIT] Offset table built in {_now()-t0:.2f}s ({len(offsets)-1} lines)')

    t0 = _now()
    top_blocks = find_top_level_blocks(lines)
    print(f'[SPLIT] Found {len(top_blocks)} top-level blocks in {_now()-t0:.2f}s')

    if split_blocks is None:
        split_blocks = get_split_blocks()
    wanted = set(split_blocks)

    manifest = {
        'split_info': {},
        'sub_ranges': {},
        'block_stats': {},
        'gamestate_chars': len(gamestate_text),
    }

    # Deduplicate repeated top-level keys via __N suffixes
    key_seen = {}
    total_files = 0
    t0 = _now()
    for key, start, end in top_blocks:
        if key not in wanted:
            continue
        cnt = key_seen.get(key, 0)
        key_seen[key] = cnt + 1
        block_name = key if cnt == 0 else f'{key}__{cnt}'

        sub_line_ranges = find_sub_block_ranges(lines, start, end)
        if not sub_line_ranges:
            # Non-collection block (no numeric children): keep whole block
            # as a single file keyed 'block'.
            cs = offsets[start]
            ce = offsets[end + 1]
            fname = f'{block_name}_block.txt'
            _write_file(os.path.join(work_dir, fname), gamestate_text[cs:ce])
            manifest['split_info'][block_name] = {'block': fname}
            manifest['sub_ranges'][block_name] = {'block': [cs, ce]}
            manifest['block_stats'][block_name] = {
                'count': 1, 'bytes': ce - cs}
            total_files += 1
            print(f'[SPLIT] {block_name}: non-collection block, kept whole')
            continue

        manifest['split_info'][block_name] = {}
        manifest['sub_ranges'][block_name] = {}
        total_bytes = 0

        for sub_key, (s, e) in sub_line_ranges.items():
            # Character range covering lines s..e including newlines
            cs = offsets[s]
            ce = offsets[e + 1]
            sub_text = gamestate_text[cs:ce]

            fname = f'{block_name}_{sub_key}.txt'
            _write_file(os.path.join(work_dir, fname), sub_text)

            manifest['sub_ranges'][block_name][sub_key] = [cs, ce]
            manifest['split_info'][block_name][sub_key] = fname
            total_bytes += ce - cs
            total_files += 1

        manifest['block_stats'][block_name] = {
            'count': len(sub_line_ranges), 'bytes': total_bytes}
        print(f'[SPLIT] {block_name}: {len(sub_line_ranges)} sub-blocks '
              f'({total_bytes:,} chars, lines {start}-{end})')

    print(f'[SPLIT] Wrote {total_files} split files in {_now()-t0:.2f}s')

    manifest['total_split_files'] = total_files
    manifest_path = os.path.join(work_dir, '_manifest.json')
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False)
    print(f'[SPLIT] Manifest saved, work_dir: {work_dir}')
    return manifest


def _write_file(filepath, text):
    """Write text byte-exactly (newline='' disables platform translation)."""
    with open(filepath, 'w', encoding='utf-8', newline='') as f:
        f.write(text)


def read_split_file(work_dir, manifest, block_name, sub_key):
    """Read a single sub-block file (byte-exact, no newline translation)."""
    info = manifest.get('split_info', {}).get(block_name, {})
    filename = info.get(str(sub_key))
    if not filename:
        return None
    filepath = os.path.join(work_dir, filename)
    if not os.path.exists(filepath):
        return None
    with open(filepath, 'r', encoding='utf-8', newline='') as f:
        return f.read()


def write_split_file(work_dir, manifest, block_name, sub_key, text):
    """Write modified text back to a sub-block file (byte-exact)."""
    info = manifest.get('split_info', {}).get(block_name, {})
    filename = info.get(str(sub_key))
    if not filename:
        return False
    _write_file(os.path.join(work_dir, filename), text)
    return True


def splice_into_gamestate(gamestate_text, manifest, block_name, sub_key, new_sub_text):
    """
    Replace a sub-block in the full gamestate_text using pre-computed char
    offsets. O(1) lookup + 3 string slices. No line splitting.
    Adjusts all subsequent char offsets in the manifest by the size diff.
    Returns the updated gamestate_text.
    """
    ranges = manifest.get('sub_ranges', {}).get(block_name, {})
    key_str = str(sub_key)
    if key_str not in ranges:
        print(f'[SPLIT] WARNING: sub_key {key_str} not found in ranges for {block_name}')
        return gamestate_text

    cs, ce = ranges[key_str]
    old_size = ce - cs
    new_size = len(new_sub_text)
    diff = new_size - old_size

    result = gamestate_text[:cs] + new_sub_text + gamestate_text[ce:]

    # Update the modified block's range to the new size
    ranges[key_str] = [cs, cs + new_size]

    # Adjust all OTHER sub-block offsets that come after the replaced region
    if diff != 0:
        _adjust_offsets(manifest, block_name, key_str, ce, diff)

    return result


def _adjust_offsets(manifest, exclude_block, exclude_key, after_char, diff):
    """
    Adjust all char offsets in the manifest that start at or after after_char,
    except for the excluded block/key (already updated by the caller).
    """
    for bname, sub_ranges in manifest.get('sub_ranges', {}).items():
        for skey in list(sub_ranges.keys()):
            if bname == exclude_block and skey == exclude_key:
                continue
            scs, sce = sub_ranges[skey]
            if scs >= after_char:
                sub_ranges[skey] = [scs + diff, sce + diff]


def update_parsed_sub_block(gamestate_parsed, block_name, sub_key, parsed_data):
    """Update in-memory parsed dict for one sub-block (avoids full re-parse)."""
    if not gamestate_parsed:
        return
    block = gamestate_parsed.get(block_name)
    if not isinstance(block, dict):
        return
    block[str(sub_key)] = parsed_data


def verify_roundtrip(gamestate_text, manifest, work_dir):
    """
    Verify split roundtrip is byte-identical: replacing every sub-range with
    its split-file content must rebuild the exact original text.
    Returns True if identical.
    """
    spans = []
    for bname, ranges in manifest.get('sub_ranges', {}).items():
        for skey, (cs, ce) in ranges.items():
            spans.append((cs, ce,
                          os.path.join(work_dir, manifest['split_info'][bname][skey])))
    spans.sort(key=lambda x: x[0], reverse=True)

    rebuilt = gamestate_text
    for cs, ce, fp in spans:
        with open(fp, 'r', encoding='utf-8', newline='') as f:
            rebuilt = rebuilt[:cs] + f.read() + rebuilt[ce:]

    ok = rebuilt == gamestate_text
    if not ok:
        print('[SPLIT] VERIFY FAILED: roundtrip is not byte-identical!')
    return ok


def cleanup_work_dir(work_dir):
    """Remove the work directory and all split files."""
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir)
        print(f'[SPLIT] Cleaned up: {work_dir}')


def load_manifest(work_dir):
    """Load manifest from work directory."""
    path = os.path.join(work_dir, '_manifest.json')
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)
