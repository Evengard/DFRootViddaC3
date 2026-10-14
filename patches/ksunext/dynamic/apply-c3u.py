#!/usr/bin/env python3
"""Patch a chosen KernelSU Next Git revision for the Vidda C3U.

Fail closed if the SELinux late-load guard or Kbuild version rules change.
Use host-derived, full-history Git version values: DDK images may not have git.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

IMAGE = 'ghcr.io/ylarod/ddk-min:android14-5.15-20260828'
BEFORE = '''\t\tif (!getenforce()) {
\t\t\tpr_info("Permissive SELinux, enforcing\\n");
\t\t\tsetenforce(true);
\t\t}
'''
AFTER = '''\t\tif (!getenforce()) {
\t\t\tpr_info("Permissive SELinux, keeping\\n");
\t\t\t//setenforce(true); // Vidda C3U: never force Enforcing on this vendor kernel
\t\t}
'''
VERSION_START = '# Check if this is a git repository'
VERSION_END = '# Calculate version if git version is available'


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def replace_unique(text: str, before: str, after: str, label: str) -> str:
    if text.count(before) != 1:
        raise ValueError(f'Upstream {label} changed; found {text.count(before)} matches, refusing unsafe patch')
    return text.replace(before, after, 1)


def patched_sources(init: str, kbuild: str, commit_count: int, tag: str) -> tuple[str, str]:
    if commit_count < 1000 or not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+(?:[-.][A-Za-z0-9._-]+)?', tag):
        raise ValueError('Unrecognized upstream git version or tag')
    new_init = replace_unique(init, BEFORE, AFTER, 'Permissive SELinux late-load block')
    if VERSION_START not in kbuild or VERSION_END not in kbuild or kbuild.count(VERSION_START) != 1 or kbuild.count(VERSION_END) != 1:
        raise ValueError('KernelSU Kbuild version logic changed; refusing unsafe patch')
    start, end = kbuild.index(VERSION_START), kbuild.index(VERSION_END)
    if end <= start or ('KSU_GIT_VERSION' not in kbuild[start:end]):
        raise ValueError('Unrecognized Kbuild version block')
    # Force verified full-history values rather than relying on git in the DDK container.
    # Kbuild's existing version calculation and ccflags-y emission are retained.
    custom = ('# Vidda C3U: host-resolved real upstream Git history and suffix.\n'
              'KSU_GIT_VERSION_VALID := 1\n'
              f'KSU_GIT_VERSION := {commit_count}\n'
              f'KSU_GIT_TAG := {tag}-viddaC3\n\n')
    new_kbuild = kbuild[:start] + custom + kbuild[end:]
    for marker in ('ccflags-y += -DKSU_VERSION=$(KSU_VERSION)',
                   'ccflags-y += -DKSU_VERSION_TAG=\\"$(KSU_VERSION_TAG)\\"'):
        if marker not in new_kbuild:
            raise ValueError(f'KernelSU Kbuild no longer uses expected version macro: {marker}')
    return new_init, new_kbuild


def apply(repo: Path, output: Path, requested_ref: str) -> dict:
    repo = repo.resolve()
    if git(repo, 'status', '--porcelain'):
        raise ValueError('Expected clean source checkout before applying C3U patch')
    head = git(repo, 'rev-parse', 'HEAD')
    if not re.fullmatch('[0-9a-f]{40}', head):
        raise ValueError('Cannot determine selected KernelSU commit')
    count = int(git(repo, 'rev-list', '--count', 'HEAD'))
    tag = git(repo, 'describe', '--tags', '--abbrev=0', 'HEAD')
    version_code = 30000 + count
    new_init, new_kbuild = patched_sources(
        (repo / 'kernel/core/init.c').read_text(),
        (repo / 'kernel/Kbuild').read_text(), count, tag,
    )
    (repo / 'kernel/core/init.c').write_text(new_init)
    (repo / 'kernel/Kbuild').write_text(new_kbuild)
    changed = set(git(repo, 'diff', '--name-only').splitlines())
    if changed != {'kernel/core/init.c', 'kernel/Kbuild'}:
        raise ValueError(f'Unexpected source changes after C3U patch: {sorted(changed)}')
    info = {
        'source_ref': requested_ref,
        'source_revision': head,
        'upstream_version_tag': tag,
        'version_tag': tag + '-viddaC3',
        'git_commit_count': count,
        'version_code': version_code,
        'ddk_image': IMAGE,
        'selinux_mode': 'preserve-permissive',
        'module_status': 'CI-rebuilt; requires on-device verification',
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / 'source-version.json').write_text(json.dumps(info, indent=2) + '\n')
    (output / 'source-commit.txt').write_text(head + '\n')
    print(f'C3U KernelSU: {tag}-viddaC3 ({version_code}), ref={requested_ref!r}, commit={head}')
    return info


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('checkout', type=Path)
    ap.add_argument('output', type=Path)
    ap.add_argument('--ref', default='master')
    args = ap.parse_args()
    try:
        apply(args.checkout, args.output, args.ref)
    except (OSError, ValueError, subprocess.CalledProcessError) as e:
        ap.exit(1, f'REFUSED to patch KernelSU: {e}\n')


if __name__ == '__main__':
    main()
