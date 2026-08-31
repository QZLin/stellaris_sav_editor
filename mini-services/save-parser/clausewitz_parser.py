"""
Paradox Clausewitz Engine Format Parser for Stellaris Save Files.

The format is a nested key-value structure with braces:
  key=value
  key={ ... }
  key="string"
  key=123.456
  key=yes/no
  Lists are implicit: repeated keys under a brace block.
  Values without keys are list items (integers, strings, etc.).
"""

import re
from typing import Any, Optional


def parse_clausewitz(text: str) -> dict:
    """Parse a Clausewitz format string into a nested dict/list structure."""
    import sys
    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old_limit, 50000))
    try:
        tokens = tokenize(text)
        result, _ = _parse_block(tokens, 0)
        return result
    finally:
        sys.setrecursionlimit(old_limit)


def tokenize(text: str) -> list:
    """Tokenize Clausewitz text into a list of tokens."""
    tokens = []
    i = 0
    n = len(text)

    while i < n:
        c = text[i]

        # Skip whitespace
        if c in ' \t\r\n':
            i += 1
            continue

        # Braces
        if c == '{':
            tokens.append('{')
            i += 1
            continue
        if c == '}':
            tokens.append('}')
            i += 1
            continue

        # Equals sign
        if c == '=':
            tokens.append('=')
            i += 1
            continue

        # Quoted string
        if c == '"':
            j = i + 1
            while j < n:
                if text[j] == '\\' and j + 1 < n:
                    j += 2
                    continue
                if text[j] == '"':
                    break
                j += 1
            tokens.append(('str', text[i+1:j]))
            i = j + 1
            continue

        # Comment (# to end of line)
        if c == '#':
            while i < n and text[i] != '\n':
                i += 1
            continue

        # Number or identifier
        # A token ends at whitespace, {, }, =, or #
        j = i
        while j < n and text[j] not in ' \t\r\n{}=#':
            j += 1
        word = text[i:j]
        if not word:
            i += 1
            continue

        # Try to parse as number
        try:
            if '.' in word:
                tokens.append(('num', float(word)))
            else:
                tokens.append(('num', int(word)))
        except ValueError:
            # Boolean
            if word.lower() == 'yes':
                tokens.append(('bool', True))
            elif word.lower() == 'no':
                tokens.append(('bool', False))
            else:
                tokens.append(('id', word))

        i = j

    return tokens


def _parse_block(tokens: list, pos: int) -> tuple:
    """
    Parse tokens into a structured representation.
    Returns (result_dict, next_position).
    Handles the implicit list semantics of Clausewitz format:
    - If a key appears multiple times, values are collected into a list.
    - Values without a key are collected into a list under None key.
    """
    result = {}
    list_values = []  # for bare values (no key)

    while pos < len(tokens):
        token = tokens[pos]

        if token == '}':
            pos += 1
            break

        # Skip stray '=' tokens
        if token == '=':
            pos += 1
            continue

        # Bare brace block as list item
        if token == '{':
            val, pos = _parse_value(tokens, pos)
            list_values.append(val)
            continue

        # Check if a non-id token (number/string/bool) is followed by '=' or '{'
        # In Clausewitz format, numbers can be keys: 0={ ... }, 1={ ... }
        if isinstance(token, tuple) and token[0] != 'id':
            next_pos = pos + 1
            if next_pos < len(tokens) and (tokens[next_pos] == '=' or tokens[next_pos] == '{'):
                # This is actually a key
                key = str(token[1]) if token[0] == 'num' else token[1]
                pos = next_pos
                if tokens[pos] == '=':
                    pos += 1
                val, pos = _parse_value(tokens, pos)
                if key in result:
                    if isinstance(result[key], list):
                        result[key].append(val)
                    else:
                        result[key] = [result[key], val]
                else:
                    result[key] = val
                continue
            else:
                # It's a bare list item
                val, pos = _parse_value(tokens, pos)
                list_values.append(val)
                continue

        # It must be an identifier (key)
        if not isinstance(token, tuple) or token[0] != 'id':
            # Unknown token, skip
            pos += 1
            continue

        key = token[1]
        pos += 1

        # Check if next is '='
        if pos < len(tokens) and tokens[pos] == '=':
            pos += 1  # skip '='
            val, pos = _parse_value(tokens, pos)
        elif pos < len(tokens) and tokens[pos] == '{':
            # key={...} without =
            val, pos = _parse_value(tokens, pos)
        else:
            # Bare key (like in required_dlcs)
            val = key

        # Handle repeated keys -> convert to list
        if key in result:
            if isinstance(result[key], list):
                result[key].append(val)
            else:
                result[key] = [result[key], val]
        else:
            result[key] = val

    # Attach bare list values if any
    if list_values:
        if None in result:
            if isinstance(result[None], list):
                result[None].extend(list_values)
            else:
                result[None] = [result[None]] + list_values
        else:
            result[None] = list_values

    return result, pos


def _parse_value(tokens: list, pos: int) -> tuple:
    """Parse a value (could be a number, string, bool, or brace block)."""
    if pos >= len(tokens):
        return None, pos

    token = tokens[pos]

    if token == '{':
        pos += 1  # skip '{'
        val, pos = _parse_block(tokens, pos)
        return val, pos

    if isinstance(token, tuple):
        return token[1], pos + 1

    return token, pos + 1


def serialize_clausewitz(data: Any, indent: int = 0, indent_str: str = '\t') -> str:
    """Serialize a parsed structure back to Clausewitz format text."""
    lines = []
    prefix = indent_str * indent

    if isinstance(data, dict):
        # Separate bare values (None key) from key-value pairs
        bare_values = data.pop(None, []) if None in data else []

        for key, value in data.items():
            if isinstance(value, list):
                for item in value:
                    lines.append(_format_kv(key, item, prefix, indent, indent_str))
            else:
                lines.append(_format_kv(key, value, prefix, indent, indent_str))

        # Restore bare values
        if bare_values:
            for bv in bare_values:
                lines.append(_format_bare_value(bv, prefix, indent, indent_str))

        if indent > 0:
            # Inner block
            if lines:
                return '{\n' + '\n'.join(lines) + '\n' + indent_str * (indent - 1) + '}'
            else:
                return '{\n' + indent_str * (indent - 1) + '}'
        else:
            return '\n'.join(lines)

    elif isinstance(data, list):
        for item in data:
            lines.append(_format_bare_value(item, prefix, indent, indent_str))
        return '\n'.join(lines)

    else:
        return _format_literal(data)


def _format_kv(key: str, value: Any, prefix: str, indent: int, indent_str: str) -> str:
    """Format a key=value pair."""
    if isinstance(value, dict):
        inner = serialize_clausewitz(value, indent + 1, indent_str)
        return f'{prefix}{key}={inner}'
    elif isinstance(value, list):
        # If list items are dicts, format as repeated key={{...}}
        parts = []
        for item in value:
            if isinstance(item, dict):
                inner = serialize_clausewitz(item, indent + 1, indent_str)
                parts.append(f'{prefix}{key}={inner}')
            else:
                parts.append(f'{prefix}{key}={_format_literal(item)}')
        return '\n'.join(parts)
    else:
        return f'{prefix}{key}={_format_literal(value)}'


def _format_bare_value(value: Any, prefix: str, indent: int, indent_str: str) -> str:
    """Format a bare value (no key)."""
    if isinstance(value, dict):
        inner = serialize_clausewitz(value, indent + 1, indent_str)
        return f'{prefix}{inner}'
    else:
        return f'{prefix}{_format_literal(value)}'


def _format_literal(value: Any) -> str:
    """Format a literal value."""
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, float):
        # Remove trailing zeros but keep at least one decimal
        formatted = f'{value:.5f}'.rstrip('0')
        if formatted.endswith('.'):
            formatted += '0'
        return formatted
    return str(value)
