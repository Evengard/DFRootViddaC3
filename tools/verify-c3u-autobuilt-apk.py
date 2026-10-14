#!/usr/bin/env python3
"""Prove the CI output APK embeds exactly the .ko rebuilt in the SAME run."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

KNOWN_GOOD_SHA = '7b5374327b316ccb4e0c4271b938b664f193b7aeb3dd25bd9428976a6c08a38b'
REF = '78ed5d1f5b5041a197f0b55291876d62a6bd7c67'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify(apk: Path, ko: Path, manifest: Path) -> str:
    if not all(p.is_file() for p in (apk, ko, manifest)):
        raise ValueError('APK, just-built .ko, and build-manifest.json are all required')
    info = json.loads(manifest.read_text())
    module = info.get('kernelsu', {})
    if module.get('selection') != 'ci-compiled-unverified':
        raise ValueError('APK was NOT built in freshly compiled module mode')
    if module.get('source_revision') != REF:
        raise ValueError('Wrong KernelSU compilation source revision')
    content = ko.read_bytes()
    sha = digest(content)
    if module.get('sha256') != sha or module.get('bytes') != len(content):
        raise ValueError('Final build manifest does not identify the newly built .ko')
    if info.get('apk', {}).get('sha256') != digest(apk.read_bytes()):
        raise ValueError('Final APK bytes differ from build manifest')
    with zipfile.ZipFile(apk) as z:
        native = z.read('lib/arm64-v8a/libc3uksu.so')
        if native.count(content) != 1:
            raise ValueError('APK does not contain EXACTLY ONE byte-identical rebuilt .ko in libc3uksu.so')
        # Ensure normal first-stage loader and the independent root-shell client
        # are still present (the original helper hash is checked by build script).
        for name in ('lib/arm64-v8a/libbootstrap.so', 'lib/arm64-v8a/libdfroot.so',
                     'lib/arm64-v8a/libdfrootsu.so'):
            if name not in z.namelist():
                raise ValueError(f'Missing original legacy native library: {name}')
        if b'/data/user_de/0/df.root/ksud' not in native:
            raise ValueError('Manager-provided ksud path is absent from the packaged loader')
        if b'c3u-autobuilt.ko' not in native:
            raise ValueError('Compiled-mode native payload filename is absent')
    return sha


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', required=True, type=Path)
    parser.add_argument('--ko', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    args = parser.parse_args()
    try:
        sha = verify(args.apk, args.ko, args.manifest)
    except (ValueError, KeyError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as e:
        parser.exit(1, f'FAIL: {e}\n')
    print(f'PASS: rebuilt KernelSU .ko SHA-256 {sha}')
    print('PASS: compiled module embedded byte-for-byte in APK; no known-good substitution')
    if sha == KNOWN_GOOD_SHA:
        print('PASS: compiled module is byte-identical to the device-tested original')
    else:
        print('WARNING: compiled .ko differs from original, and requires device validation')


if __name__ == '__main__':
    main()
