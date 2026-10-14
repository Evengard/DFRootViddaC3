#!/usr/bin/env python3
"""Create/reuse a LOCAL signing key and register it as GitHub Actions secrets.

Requires `keytool` from a JDK and authenticated `gh` CLI. The key is generated
only on your own machine, never in GitHub CI, and is NOT added to the repo.

Example: python3 tools/configure-ci-signing.py --generate --repo Evengard/DFRootViddaC3
Existing key: python3 tools/configure-ci-signing.py --keystore /path/to/original.jks --alias old_alias
"""
from __future__ import annotations

import argparse
import base64
import getpass
import os
from pathlib import Path
import shutil
import subprocess
import sys


def run_checked(argv, *, env=None, data=None):
    subprocess.run(argv, check=True, env=env, input=data, text=data is not None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keystore', type=Path,
                        default=Path.home() / '.config/dfroot-c3u/release.jks')
    parser.add_argument('--alias', default='dfroot-c3u')
    parser.add_argument('--repo', help='GitHub repository (e.g. Evengard/DFRootViddaC3)')
    parser.add_argument('--generate', action='store_true',
                        help='Generate a new key if the specified keystore does not exist')
    args = parser.parse_args()
    if shutil.which('keytool') is None or shutil.which('gh') is None:
        parser.error('Install a JDK (keytool) and GitHub CLI (gh), then run gh auth login')
    keystore = args.keystore.expanduser().resolve()
    if not keystore.is_file() and not args.generate:
        parser.error('Keystore not found. Use --generate for a NEW signing identity; '
                     'use the ORIGINAL keystore to preserve an existing installed app identity.')
    if not args.alias or '\n' in args.alias:
        parser.error('Invalid signing key alias')
    existing = keystore.is_file()
    password = getpass.getpass('Keystore password (not displayed): ')
    if not password:
        parser.error('Password must not be empty')
    key_password = (getpass.getpass('Private-key password (Enter if same): ') or password) if existing else password
    if not existing:
        confirm = getpass.getpass('Confirm new keystore/key password: ')
        if confirm != password:
            parser.error('Passwords did not match; nothing generated')
        keystore.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(keystore.parent, 0o700)
        env = dict(os.environ, C3U_KEYTOOL_PASS=password)
        run_checked(['keytool', '-genkeypair', '-keystore', str(keystore),
                     '-storetype', 'JKS', '-alias', args.alias,
                     '-keyalg', 'RSA', '-keysize', '3072', '-validity', '10000',
                     '-dname', 'CN=DFRoot Vidda C3U',
                     '-storepass:env', 'C3U_KEYTOOL_PASS',
                     '-keypass:env', 'C3U_KEYTOOL_PASS', '-noprompt'], env=env)
        os.chmod(keystore, 0o600)
        print('Created persistent signing key outside the Git checkout.')
    # Fail before storing secrets if alias/password are invalid.
    env = dict(os.environ, C3U_KEYTOOL_PASS=password)
    run_checked(['keytool', '-list', '-keystore', str(keystore),
                 '-alias', args.alias, '-storepass:env', 'C3U_KEYTOOL_PASS'], env=env)
    key = keystore.read_bytes()
    if len(key) < 100:
        parser.error('Signing key file unexpectedly small')
    base = ['gh', 'secret', 'set']
    if args.repo:
        base += ['--repo', args.repo]
    secrets = (
        ('C3U_SIGNING_KEYSTORE_B64', base64.b64encode(key).decode('ascii')),
        ('C3U_SIGNING_KEYSTORE_PASSWORD', password),
        ('C3U_SIGNING_KEY_ALIAS', args.alias),
        ('C3U_SIGNING_KEY_PASSWORD', key_password),
    )
    for name, val in secrets:
        run_checked(base[:3] + [name] + base[3:], data=val)
        print('Configured GitHub Actions secret: ' + name)
    print('DONE. Save an OFFLINE BACKUP of: ' + str(keystore))
    print('CI will refuse to sign if these secrets are missing; never commit the keystore.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f'ERROR: local keytool / GitHub CLI exited with code {exc.returncode}', file=sys.stderr)
        raise SystemExit(1)
