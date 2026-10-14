#!/usr/bin/env python3
"""Add a focusable Settings control to DFRoot's MainActivity on Android TV.

Only Java MainActivity checkouts are currently supported, and the edit is
idempotent. This fails rather than guessing when layout/source differs.
"""
from pathlib import Path
import argparse
import re
import sys

TAG = "C3UTvSettings.install(this);"


def patch(repo: Path, helper: Path) -> Path:
    source = repo / "app/src/main/java"
    if not source.is_dir():
        raise ValueError(f"Missing Java source directory: {source}")
    candidates = [p for p in source.rglob('MainActivity.java')
                  if re.search(r'\bclass\s+MainActivity\b', p.read_text())]
    if len(candidates) != 1:
        raise ValueError(f"Expected exactly one Java MainActivity; found {len(candidates)}. "
                         "TV UI patch cannot safely choose an Activity.")
    target = candidates[0]
    text = target.read_text()
    package_match = re.search(r'^\s*package\s+([\w.]+)\s*;', text, re.M)
    if package_match is None:
        raise ValueError("Java MainActivity package declaration not found")
    package = package_match.group(1)
    # Signature accepts annotations and multiline arguments but not Kotlin.
    m = re.search(r'\bvoid\s+onCreate\s*\(\s*(?:@\w+\s+)*'
                  r'(?:android\.os\.)?Bundle\s+\w+\s*\)\s*\{', text)
    if m is None:
        raise ValueError("MainActivity.onCreate(Bundle) method not found")
    left = m.end() - 1
    depth = 0
    right = -1
    # Java brace scanner skips strings/chars/comments to avoid premature match.
    state = 'code'
    idx = left
    while idx < len(text):
        c = text[idx]
        next_c = text[idx+1] if idx + 1 < len(text) else ''
        if state == 'code':
            if c == '"': state = 'string'
            elif c == "'": state = 'char'
            elif c == '/' and next_c == '/': state = 'line'; idx += 1
            elif c == '/' and next_c == '*': state = 'block'; idx += 1
            elif c == '{': depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0: right = idx; break
        elif state == 'string':
            if c == '\\': idx += 1
            elif c == '"': state = 'code'
        elif state == 'char':
            if c == '\\': idx += 1
            elif c == "'": state = 'code'
        elif state == 'line':
            if c == '\n': state = 'code'
        elif state == 'block':
            if c == '*' and next_c == '/': state = 'code'; idx += 1
        idx += 1
    if right == -1:
        raise ValueError("Could not reliably identify the end of onCreate")
    method = text[left:right]
    if TAG not in text:
        if not re.search(r'\bsetContentView\s*\(', method):
            raise ValueError("MainActivity does not call setContentView in onCreate; "
                             "cannot safely add TV control")
        text = text[:right] + '    // C3U_TV_SETTINGS: DPAD-focusable fallback.\n        ' + TAG + '\n    ' + text[right:]
    elif text.count(TAG) != 1:
        raise ValueError("Ambiguous existing C3U settings patch")
    if package == 'df.root':
        patched_helper = helper.read_text()
    else:
        patched_helper = re.sub(r'^package df\.root;', f'package {package};',
                                helper.read_text(), count=1, flags=re.M)
    output_helper = target.with_name('C3UTvSettings.java')
    # Check the target's source package doesn't conflict with a pre-existing
    # helper from another fork before writing.
    if output_helper.exists() and 'C3UTvSettings' not in output_helper.read_text():
        raise ValueError(f"Refusing to overwrite unrelated source: {output_helper}")
    target.write_text(text)
    output_helper.write_text(patched_helper)
    return target


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument('dfroot', type=Path)
    ns = args.parse_args()
    try:
        activity = patch(ns.dfroot.resolve(), Path(__file__).with_name('C3UTvSettings.java'))
    except (OSError, ValueError) as e:
        args.exit(1, f'TV Settings patch refused: {e}\n')
    print(f'TV Settings control inserted/verified in: {activity}')


if __name__ == '__main__':
    main()
