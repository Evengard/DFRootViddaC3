#!/usr/bin/env python3
"""Check latest stable KernelSU Next release and optionally update the pinned tag.

This script never downloads/executes upstream code. It only edits
config/upstreams.json; GitHub Actions builds and validates the candidate.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

API = 'https://api.github.com/repos/KernelSU-Next/KernelSU-Next/releases/latest'


def version(tag):
    m = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', tag or '')
    return tuple(map(int, m.groups())) if m else None


def candidate(current, release):
    if release.get('draft') or release.get('prerelease'):
        return None
    tag = release.get('tag_name', '')
    new_v = version(tag)
    old_v = version(current)
    if not new_v or not old_v:
        raise ValueError(f'Cannot compare non-stable tags: current={current!r}, latest={tag!r}')
    return tag if new_v > old_v else None


def get_release(fixture=None):
    if fixture is not None:
        return json.loads(Path(fixture).read_text())
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'c3u-kernelsu-update-checker', 'X-GitHub-Api-Version': '2022-11-28'}
    token = os.getenv('GITHUB_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    with urlopen(Request(API, headers=headers), timeout=30) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=Path(__file__).resolve().parents[1] / 'config/upstreams.json')
    parser.add_argument('--fixture', type=Path, help='Local release JSON for offline testing')
    parser.add_argument('--apply', action='store_true', help='Update the config file only when a newer stable tag exists')
    parser.add_argument('--github-output', type=Path, default=os.getenv('GITHUB_OUTPUT'))
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text())
    current = cfg['kernelsu_next']['ref']
    release = get_release(args.fixture)
    newer = candidate(current, release)
    new = newer or current
    if newer and args.apply:
        cfg['kernelsu_next']['ref'] = newer
        args.config.write_text(json.dumps(cfg, indent=2) + '\n')
    outputs = {'changed': 'true' if newer else 'false', 'previous_tag': current, 'new_tag': new, 'release_url': release.get('html_url', '')}
    for k, v in outputs.items():
        print(f'{k}={v}')
    if args.github_output:
        with open(args.github_output, 'a', encoding='utf-8') as f:
            for k,v in outputs.items():
                f.write(f'{k}={v}\n')
    if not newer:
        print('No newer stable KernelSU Next release; pinned ref unchanged.')
    else:
        print(f'New stable release: {current} -> {new}. CI build and manual device testing required.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        sys.exit(f'KernelSU upstream update check failed: {exc}')
