#!/usr/bin/env python3

with open('/home/z/my-project/src/app/page.tsx', 'r') as f:
    content = f.read()

old = 'className={`'
new = 'className={hasChanged ? '

# Multi-line template literal pattern
if old in content:
    # Find the template literal block and replace
    lines = content.split('\n')
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if 'className={`' in line and i+1 < len(lines) and 'flex items-center gap-3' in lines[i+1]:
            # Replace this block
            new_lines.append(line.replace('className={`', "className={hasChanged"))
            i += 1
            while i < len(lines) and '`}>' not in lines[i]:
                if 'hasChanged' in lines[i]:
                    # Extract the two branches
                    pass
                i += 1
            if i < len(lines):
                new_lines.append(line.rstrip() for line in [
                    "                            ? 'flex items-center gap-3 p-3 rounded-lg border transition-colors bg-amber-500/10 border-amber-500/30'",
                    "                            : 'flex items-center gap-3 p-3 rounded-lg border transition-colors bg-white/[0.02] border-gray-700/30 hover:border-gray-600/50'",
                    "                          }>",
                ])
                i += 1
            continue
        new_lines.append(line)
        i += 1
    content = '\n'.join(new_lines)
    with open('/home/z/my-project/src/app/page.tsx', 'w') as f:
        f.write(content)
    print('Fixed!')
else:
    print('Pattern not found')
