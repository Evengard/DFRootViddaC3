#!/usr/bin/env python3
"""Fail-closed v5.4 Java source and final APK smoke checks.

DFRoot v3.1 release has isMinifyEnabled=false. This checks final classes*.dex
so the test fails when Java was patched in one checkout but another was built.
It is a presence/legacy-method check, not a proof of correct runtime behavior.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import zipfile


SOURCE_REQUIRED = {
    'MainActivity.java': (
        'C3U_UNIFIED_ROOT_UI',
        'C3URootForegroundService.ACTION_START_UI',
        'startForegroundService(service)',
        'C3URootLog.read(MainActivity.this)',
    ),
    'C3URootForegroundService.java': (
        'ACTION_START_UI', 'ACTION_START_ADB',
        'ExploitRunner.run(createDeviceProtectedStorageContext(), this)',
        'C3URootLog.append(this,',
    ),
    'C3UAdbRootActivity.java': (
        'C3URootForegroundService.ACTION_START_ADB',
        'startForegroundService(service)',
    ),
    'C3URootLog.java': (
        'static void begin(', 'static void append(', 'static String read(',
    ),
}

DEX_REQUIRED = (
    b'Ldf/root/MainActivity;',
    b'Ldf/root/C3UAdbRootActivity;',
    b'Ldf/root/C3URootForegroundService;',
    b'Ldf/root/C3URootLog;',
    b'df.root.c3u.START_FROM_UI',
    b'df.root.c3u.START_FROM_ADB',
)


def verify_source(java_dir: Path) -> None:
    for name, required in SOURCE_REQUIRED.items():
        path = java_dir / name
        if not path.is_file():
            raise ValueError(f'v5.4 Java file missing: {path}')
        content = path.read_text(encoding='utf-8')
        for fragment in required:
            if fragment not in content:
                raise ValueError(f'v5.4 source {name} lacks {fragment!r}')
        if name == 'MainActivity.java':
            for legacy in ('private void runExploit(', 'mExec.execute(', 'ExploitRunner.run('):
                if legacy in content:
                    raise ValueError(f'Legacy UI root executor remains: {legacy}')
    print('PASS: reviewed v5.4 source files and unified UI/ADB worker are present')


def verify_apk(apk: Path) -> None:
    if not apk.is_file() or not apk.stat().st_size:
        raise ValueError(f'APK missing or empty: {apk}')
    with zipfile.ZipFile(apk) as archive:
        dex_names = [name for name in archive.namelist()
                     if re.fullmatch(r'classes(?:[0-9]+)?\.dex', name)]
        if not dex_names:
            raise ValueError('No classes*.dex entries in APK')
        dex = b''.join(archive.read(name) for name in dex_names)
    missing = [entry.decode('ascii') for entry in DEX_REQUIRED if entry not in dex]
    if missing:
        raise ValueError('Compiled APK lacks v5.4 classes/actions: ' + ', '.join(missing))
    if b'runExploit' in dex:
        raise ValueError('Compiled APK still has runExploit symbol (old UI path)')
    print('PASS: final APK DEX has v5.4 UI/service/log classes and no legacy runExploit')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path)
    parser.add_argument('--apk', type=Path)
    args = parser.parse_args()
    if args.source_dir is None and args.apk is None:
        parser.error('Provide --source-dir, --apk, or both')
    try:
        if args.source_dir is not None:
            verify_source(args.source_dir)
        if args.apk is not None:
            verify_apk(args.apk)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        parser.exit(1, f'v5.4 integration verification FAILED: {exc}\n')


if __name__ == '__main__':
    main()
