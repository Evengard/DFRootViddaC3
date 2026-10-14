#!/usr/bin/env python3
"""Fail-closed inspection of the final DFRoot C3U APK and embedded KernelSU KO.

DFRoot v3.1 creates libdfroot.so and libbootstrap.so; C3U's exact v6 KO is
linked into libbootstrap.so (c3u_ksu_preload.c), not a libexp.so target.

This checks APK bytes, NOT merely the Gradle/CMake output directory.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
import zipfile
from collections import Counter

REQUIRED = (
    'lib/arm64-v8a/libdfroot.so',
    'lib/arm64-v8a/libbootstrap.so',
    'lib/arm64-v8a/libdfrootsu.so',
)


def verify(apk: Path, ko: Path | None = None) -> None:
    if not apk.is_file() or apk.stat().st_size == 0:
        raise ValueError(f'APK missing or empty: {apk}')
    with zipfile.ZipFile(apk) as z:
        entries = z.namelist()
        duplicates = sorted(name for name, count in Counter(entries).items() if count > 1)
        if duplicates:
            raise ValueError('APK contains duplicate ZIP entries: ' + ', '.join(duplicates))
        names = set(entries)
        libs = sorted(n for n in names if n.startswith('lib/') and n.endswith('.so'))
        print('Packaged native libraries:')
        for name in libs:
            print(f'  {name} ({z.getinfo(name).file_size:,} bytes)')
        missing = [name for name in REQUIRED if name not in names]
        if missing:
            raise ValueError('APK is missing required ARM64 binaries: ' + ', '.join(missing)
                             + '. Native CMake builds must run before assembleRelease.')
        for name in REQUIRED:
            if not z.read(name).startswith(b'\x7fELF'):
                raise ValueError(f'Not an ELF native library: {name}')
        if ko is not None:
            data = ko.read_bytes()
            if len(data) < 65536 or not data.startswith(b'\x7fELF'):
                raise ValueError(f'Invalid KernelSU module: {ko}')
            if data not in z.read('lib/arm64-v8a/libbootstrap.so'):
                raise ValueError('Exact C3U KernelSU .ko not found in APK libbootstrap.so; '
                                 'check native bootstrap linkage and stripping')
            print('PASS: exact supplied KernelSU module bytes found in packaged libbootstrap.so')
    print('PASS: required C3U native ELF files are present in APK')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('apk', type=Path)
    p.add_argument('--embedded-ko', type=Path, default=None)
    args = p.parse_args()
    try:
        verify(args.apk, args.embedded_ko)
    except (OSError, ValueError, zipfile.BadZipFile) as err:
        p.exit(1, f'APK verification FAILED: {err}\n')


if __name__ == '__main__':
    main()
