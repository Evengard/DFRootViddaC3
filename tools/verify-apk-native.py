#!/usr/bin/env python3
"""Fail-closed inspection of the final DFRoot C3U APK and embedded KernelSU KO."""
from __future__ import annotations
import argparse
from pathlib import Path
import zipfile
from collections import Counter
REQUIRED = ('lib/arm64-v8a/libdfroot.so', 'lib/arm64-v8a/libbootstrap.so', 'lib/arm64-v8a/libdfrootsu.so')

def verify(apk: Path, ko: Path | None = None) -> None:
    if not apk.is_file() or apk.stat().st_size == 0:
        raise ValueError(f'APK missing or empty: {apk}')
    with zipfile.ZipFile(apk) as z:
        names = z.namelist()
        dup = sorted(n for n, count in Counter(names).items() if count > 1)
        if dup:
            raise ValueError('APK contains duplicate ZIP entries: ' + ', '.join(dup))
        missing = [name for name in REQUIRED if name not in names]
        if missing:
            raise ValueError('APK missing native ARM64 libraries: ' + ', '.join(missing))
        for name in REQUIRED:
            if not z.read(name).startswith(b'\x7fELF'):
                raise ValueError(f'Not a native ELF binary: {name}')
        if ko is not None:
            module = ko.read_bytes()
            if not module.startswith(b'\x7fELF') or len(module) < 65536:
                raise ValueError(f'Invalid KernelSU ELF module: {ko}')
            if module not in z.read('lib/arm64-v8a/libbootstrap.so'):
                raise ValueError('Supplied KSU module absent from libbootstrap.so')
    print('PASS: required native ELF files present')

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('apk', type=Path)
    ap.add_argument('--embedded-ko', type=Path)
    args = ap.parse_args()
    try:
        verify(args.apk, args.embedded_ko)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        ap.exit(1, f'APK verification FAILED: {exc}\n')

if __name__ == '__main__':
    main()
