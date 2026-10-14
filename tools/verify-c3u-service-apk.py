#!/usr/bin/env python3
"""Verify final APK contains the Android service, protected ADB entry, and both modes.

Native module byte identity is verified independently by the established build path.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import zipfile

DEX_CLASSES = (
    b'Ldf/root/C3URootForegroundService;',
    b'Ldf/root/C3UAdbRootActivity;',
    b'Ldf/root/C3URootManager;',
    b'Ldf/root/C3URootLog;',
)
DEX_STRINGS = (b'root-only', b'ksun', b'com.rifsxd.ksunext')


def verify(apk: Path) -> None:
    with zipfile.ZipFile(apk) as z:
        dex_files = [name for name in z.namelist()
                     if name.startswith('classes') and name.endswith('.dex')]
        if not dex_files:
            raise ValueError('No classes*.dex inside APK')
        dex = b''.join(z.read(name) for name in dex_files)
        for item in DEX_CLASSES + DEX_STRINGS:
            if item not in dex:
                raise ValueError(f'Android service/intent/manager missing in final DEX: {item!r}')
        if 'AndroidManifest.xml' not in z.namelist():
            raise ValueError('AndroidManifest.xml missing')
    print('PASS: APK DEX has service, protected ADB launcher, manager selector and both modes')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apk', type=Path)
    args = parser.parse_args()
    try:
        verify(args.apk)
    except (ValueError, OSError, zipfile.BadZipFile) as e:
        parser.exit(1, f'FAIL: {e}\n')


if __name__ == '__main__':
    main()
