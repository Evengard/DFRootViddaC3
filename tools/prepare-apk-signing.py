#!/usr/bin/env python3
"""Stage a persistent, secret-backed DFRoot Android release signing key.

CI secrets (all required, no ephemeral fallback):
  C3U_SIGNING_KEYSTORE_B64, C3U_SIGNING_KEYSTORE_PASSWORD,
  C3U_SIGNING_KEY_ALIAS, C3U_SIGNING_KEY_PASSWORD

This utility writes credentials ONLY into the disposable, checked-out DFRoot
working directory. The caller must remove these files on process exit.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import os
from pathlib import Path
import re
import tempfile

NAMES = (
    'C3U_SIGNING_KEYSTORE_B64',
    'C3U_SIGNING_KEYSTORE_PASSWORD',
    'C3U_SIGNING_KEY_ALIAS',
    'C3U_SIGNING_KEY_PASSWORD',
)
MAX_CODE = 2_100_000_000


def credentials(env=None):
    env = os.environ if env is None else env
    missing = [key for key in NAMES if not env.get(key)]
    if missing:
        raise ValueError('Persistent APK signing secrets are missing: ' + ', '.join(missing)
                         + '. Set all four GitHub Actions repository secrets; '
                         'no temporary key will be created.')
    encoded = ''.join(env[NAMES[0]].split())
    try:
        key = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError('C3U_SIGNING_KEYSTORE_B64 is not valid Base64') from exc
    if len(key) < 100:
        raise ValueError('Decoded signing keystore is suspiciously short')
    for name in NAMES[1:]:
        if '\n' in env[name] or '\r' in env[name] or '\x00' in env[name]:
            raise ValueError(f'{name} contains an unsupported newline or null')
    return key, env[NAMES[1]], env[NAMES[2]], env[NAMES[3]]


def version_code(env=None):
    env = os.environ if env is None else env
    raw = env.get('C3U_APK_VERSION_CODE')
    if raw is None and env.get('GITHUB_RUN_NUMBER') is not None:
        raw = str(100000 + int(env['GITHUB_RUN_NUMBER']))
    if raw is None:
        return 401  # local-only fallback; CI always supplies GITHUB_RUN_NUMBER
    try:
        code = int(raw)
    except ValueError as exc:
        raise ValueError('APK versionCode must be an integer') from exc
    if not (401 <= code <= MAX_CODE):
        raise ValueError('APK versionCode must be between 401 and 2100000000')
    return code


def java_properties_escape(value):
    result = []
    for i, ch in enumerate(value):
        if ch == '\\':
            result.append('\\\\')
        elif ch in '\n\r\x00':
            raise ValueError('Unexpected newline or null in signing properties')
        elif ch in ':=#!' or (ch == ' ' and i == 0):
            result.append('\\' + ch)
        elif ch == '\t':
            result.append('\\t')
        elif ord(ch) > 126:
            b = ch.encode('utf-16-be')
            result.extend('\\u' + b[j:j + 2].hex() for j in range(0, len(b), 2))
        else:
            result.append(ch)
    return ''.join(result)


def atomic_private_write(target: Path, contents: bytes):
    old_umask = os.umask(0o077)
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.c3u-key-', delete=False) as out:
            staged = Path(out.name)
            out.write(contents)
        try:
            os.chmod(staged, 0o600)
            os.replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)
    finally:
        os.umask(old_umask)


def prepare(destination: Path, env=None):
    key, storepass, alias, keypass = credentials(env)
    destination = destination.resolve()
    gradle_file = destination / 'app/build.gradle.kts'
    if not gradle_file.is_file():
        raise ValueError(f'Missing DFRoot Gradle file at {gradle_file}')
    old = gradle_file.read_text()
    if not re.search(r'(?m)^\s*versionCode\s*=\s*401\s*$', old):
        raise ValueError('Unexpected upstream DFRoot versionCode; refusing to modify Gradle')
    code = version_code(env)
    new = re.sub(r'(?m)^(\s*versionCode\s*=\s*)401(\s*)$',
                 lambda m: m.group(1) + str(code) + m.group(2), old, count=1)
    # Stage the keystore and its properties, then modify the disposable checkout.
    atomic_private_write(destination / 'keystore.jks', key)
    props = ('KEYSTORE_FILE=../keystore.jks\n'
             'KEYSTORE_PASSWORD=' + java_properties_escape(storepass) + '\n'
             'KEY_ALIAS=' + java_properties_escape(alias) + '\n'
             'KEY_PASSWORD=' + java_properties_escape(keypass) + '\n')
    atomic_private_write(destination / 'signing.properties', props.encode('ascii'))
    gradle_file.write_text(new)
    print(f'PASS: Persistent signing identity staged (APK versionCode={code}); private key not printed')
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate required secrets without writing files')
    parser.add_argument('workdir', nargs='?', type=Path, help='Disposable upstream DFRoot source checkout')
    args = parser.parse_args()
    try:
        if args.check:
            credentials()
            code = version_code()
            print(f'PASS: All four persistent APK signing secrets are configured (versionCode={code})')
            return 0
        if args.workdir is None:
            parser.error('Provide a destination DFRoot working directory')
        prepare(args.workdir)
        return 0
    except ValueError as exc:
        parser.exit(2, 'ERROR: ' + str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
