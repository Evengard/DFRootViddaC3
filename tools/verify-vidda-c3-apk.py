#!/usr/bin/env python3
"""Verify the Vidda C3 APK embeds only the freshly compiled KernelSU module."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

KNOWN_GOOD_SHA = '7b5374327b316ccb4e0c4271b938b664f193b7aeb3dd25bd9428976a6c08a38b'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify(apk: Path, ko: Path, manifest: Path) -> str:
    if not all(p.is_file() for p in (apk, ko, manifest)):
        raise ValueError('APK, just-built .ko, and build-manifest.json are all required')
    info = json.loads(manifest.read_text())
    module = info.get('kernelsu', {})
    if module.get('selection') != 'ci-compiled-unverified':
        raise ValueError('APK was NOT built in freshly compiled module mode')
    version_file = manifest.parent.parent / 'vidda-c3-kernelsu/source-version.json'
    if not version_file.is_file():
        raise ValueError('Missing selected KernelSU source/version attestation')
    source = json.loads(version_file.read_text())
    if (module.get('source_revision') != source.get('source_revision')
            or module.get('version_tag') != source.get('version_tag')
            or module.get('version_code') != source.get('version_code')):
        raise ValueError('APK manifest does not match selected upstream version')
    content = ko.read_bytes()
    sha = digest(content)
    if module.get('sha256') != sha or module.get('bytes') != len(content):
        raise ValueError('Final build manifest does not identify the newly built .ko')
    if info.get('apk', {}).get('sha256') != digest(apk.read_bytes()):
        raise ValueError('Final APK bytes differ from build manifest')
    with zipfile.ZipFile(apk) as z:
        native = z.read('lib/arm64-v8a/libc3uksu.so')
        if source['version_tag'].encode('ascii') not in content:
            raise ValueError('Fresh module does not advertise selected KernelSU version tag')
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
