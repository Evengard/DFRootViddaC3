#!/usr/bin/env python3
"""Recreate *only* the known-working 78ed5d1f SELinux source edit.

Do not silently substitute the later v3.4.1-tag source, later v6 marker,
or an arbitrary local patch. The original module's exact tracked source
change is known from the user's tested source tree.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess

COMMIT = '78ed5d1f5b5041a197f0b55291876d62a6bd7c67'
ORIGINAL_SHA256 = '0582020d71b6a282e3371a6f97f579dd5e87342c225e82ea232d53b3fcbe451b'
PATCHED_SHA256 = '0700275dcc77217a224ca252f6f5129c3d6947043ce9b95776a11af7760c499d'
RELATIVE_SOURCE = Path('kernel/core/init.c')
BEFORE = '''\t\tif (!getenforce()) {
\t\t\tpr_info("Permissive SELinux, enforcing\\n");
\t\t\tsetenforce(true);
\t\t}
'''
AFTER = '''\t\tif (!getenforce()) {
\t\t\tpr_info("Permissive SELinux, keeping\\n");
\t\t\t//setenforce(true);
\t\t}
'''


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def modify(text: str) -> str:
    if text.count(BEFORE) != 1:
        raise ValueError(f'Expected one exact historical enforcing block; found {text.count(BEFORE)}')
    if AFTER in text:
        raise ValueError('Edited block already exists; refuse to double-patch')
    return text.replace(BEFORE, AFTER, 1)


def apply_to_checkout(repo: Path) -> None:
    repo = repo.resolve()
    head = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    if head != COMMIT:
        raise ValueError(f'Wrong KernelSU commit {head!r}; expected {COMMIT!r}')
    dirty = subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain'], text=True)
    if dirty.strip():
        raise ValueError('Source tree is already dirty; use a freshly checked-out commit')
    src = repo / RELATIVE_SOURCE
    raw = src.read_bytes()
    if digest(raw) != ORIGINAL_SHA256:
        raise ValueError('Original init.c SHA-256 mismatch; source has changed')
    patched = modify(raw.decode('utf-8')).encode('utf-8')
    if digest(patched) != PATCHED_SHA256:
        raise ValueError('Patched init.c SHA-256 mismatch; refuse to build')
    src.write_bytes(patched)
    changed = subprocess.check_output(['git', '-C', str(repo), 'diff', '--name-only'], text=True).strip()
    if changed != RELATIVE_SOURCE.as_posix():
        raise ValueError(f'Unexpected modified files: {changed!r}')
    print(f'PASS: exact reference source commit {COMMIT}')
    print(f'PASS: init.c {ORIGINAL_SHA256} -> {PATCHED_SHA256}')
    print('Source reproduces the only tracked edit in the device-tested source archive.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repository', type=Path)
    args = parser.parse_args()
    apply_to_checkout(args.repository)


if __name__ == '__main__':
    main()
