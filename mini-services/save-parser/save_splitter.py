"""
Save file pre-splitting optimizer for Stellaris gamestate.

Strategy:
  - On upload, scan the full gamestate text to identify sub-block line ranges
    for key top-level blocks (country, species_db, etc.)
  - Extract each sub-block into an individual .txt file in a work directory
  - Record CHARACTER OFFSET ranges for O(1) splice (3 string slices, no line split)
  - GET per-country/species data: parse only the small split file (55ms vs 10s)
  - PUT modifications: modify the split file + splice into gamestate_text +
    update gamestate_parsed for just that sub-block (no full re-parse)

File layout in work_dir:
  _manifest.json            - block ranges & metadata (char offsets)
  country_0.txt             - country 0 sub-block text
  country_1.txt
  species_db_0.txt
  species_db_1.txt
  ...
"""

import os
import json
import re
import shutil

# Which top-level blocks to split into individual sub-block files.
SPLIT_BLOCKS = {
    'country': True,
    'species_db': True,
}


def _build_line_offsets(text):
    """
    Build an array where offset[i] = byte offset of line i in text.
    offset[len(lines)] = len(text) (one past end).
    O(n) single-pass scan.
    """
    offsets = []
    pos = 0
    while True:
        offsets.append(pos)
        nl = text.find('\n', pos)
        if nl == -1:
            offsets.append(len(text))
            break
        pos = nl + 1
    return offsets


def find_sub_block_ranges(lines, block_start, block_end):
    """
    Within a top-level block, find each numeric-key sub-block.
    Returns {key: (start_line, end_line)}.
    """
    sub_blocks = {}
    depth = 0
    current_key = None
    current_start = None

    for i in range(block_start, block_end + 1):
        stripped = lines[i].strip()
        opens = stripped.count('{')
        closes = stripped.count('}')

        if depth == 1 and current_key is None:
            m = re.match(r'^\s*(\d+)\s*=\{\s*$', lines[i])
            if m:
                current_key = m.group(1)
                current_start = i

        for _ in range(opens):
            depth += 1
        for _ in range(closes):
            depth -= 1

        if current_key is not None and depth <= 1:
            sub_blocks[current_key] = (current_start, i)
            current_key = None
            current_start = None

    return sub_blocks


def find_top_level_blocks(lines):
    """
    Scan all lines and find top-level key={...} blocks.
    Returns {key: (start_line, end_line)}.
    """
    blocks = {}
    depth = 0
    current_key = None
    current_start = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        opens = stripped.count('{')
        closes = stripped.count('}')

        if depth == 0 and opens > 0:
            m = re.match(r'^(\w+)\s*=\{', stripped)
            if m:
                current_key = m.group(1)
                current_start = i

        for _ in range(opens):
            depth += 1
        for _ in range(closes):
            depth -= 1

        if current_key is not None and depth <= 0:
            blocks[current_key] = (current_start, i)
            current_key = None
            current_start = None

    return blocks


def split_gamestate(gamestate_text, work_dir):
    """
    Split gamestate text into individual sub-block files.

    Returns manifest dict:
      - split_info: {block_name: {sub_key: filename}}
      - sub_ranges: {block_name: {sub_key: [char_start, char_end)}}
        where char_end is Python-slice-exclusive (text[char_start:char_end])
    """
    os.makedirs(work_dir, exist_ok=True)
    lines = gamestate_text.split('\n')

    print(f'[SPLIT] Building line offset table...')
    t0 = _now()
    offsets = _build_line_offsets(gamestate_text)
    t1 = _now()
    print(f'[SPLIT] Offset table built in {t1-t0:.2f}s ({len(offsets)} lines)')

    top_blocks = find_top_level_blocks(lines)
    print(f'[SPLIT] Found {len(top_blocks)} top-level blocks')

    manifest = {
        'split_info': {},
        'sub_ranges': {},
    }

    for key in SPLIT_BLOCKS:
        if key not in top_blocks:
            continue
        start, end = top_blocks[key]
        sub_line_ranges = find_sub_block_ranges(lines, start, end)
        print(f'[SPLIT] {key}: {len(sub_line_ranges)} sub-blocks (lines {start}-{end})')

        manifest['sub_ranges'][key] = {}
        manifest['split_info'][key] = {}

        for sub_key, (s, e) in sub_line_ranges.items():
            # Character range: from start of line s to start of line (e+1)
            # This captures the full content of lines s through e, including newlines
            cs = offsets[s]
            ce = offsets[e + 1]  # exclusive: text[cs:ce] gives lines s..e with newlines
            sub_text = gamestate_text[cs:ce]

            filename = f'{key}_{sub_key}.txt'
            filepath = os.path.join(work_dir, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(sub_text)

            manifest['sub_ranges'][key][sub_key] = [cs, ce]
            manifest['split_info'][key][sub_key] = filename

    # Save manifest
    manifest_path = os.path.join(work_dir, '_manifest.json')
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False)
    print(f'[SPLIT] Manifest saved, work_dir: {work_dir}')
    return manifest


def read_split_file(work_dir, manifest, block_name, sub_key):
    """Read a single sub-block file."""
    info = manifest.get('split_info', {}).get(block_name, {})
    filename = info.get(str(sub_key))
    if not filename:
        return None
    filepath = os.path.join(work_dir, filename)
    if not os.path.exists(filepath):
        return None
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()


def write_split_file(work_dir, manifest, block_name, sub_key, text):
    """Write modified text back to a sub-block file."""
    info = manifest.get('split_info', {}).get(block_name, {})
    filename = info.get(str(sub_key))
    if not filename:
        return False
    filepath = os.path.join(work_dir, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)
    return True


def splice_into_gamestate(gamestate_text, manifest, block_name, sub_key, new_sub_text):
    """
    Replace a sub-block in the full gamestate_text using pre-computed char offsets.
    O(1) lookup + 3 string slices. No line splitting.
    Returns the updated gamestate_text.
    Also adjusts all subsequent char offsets in the manifest by the size diff.
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
    except for the excluded block/key (which was already updated by the caller).
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


def _now():
    import time
    return time.time()