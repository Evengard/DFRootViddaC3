#!/usr/bin/env python3
"""Write a machine-readable provenance manifest for a CI-only build."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(p):
    p = Path(p)
    return {'name': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes': p.stat().st_size}


def main():
    a = argparse.ArgumentParser()
    for arg in ('config', 'out', 'kernel', 'apk', 'ksu-ref', 'ksu-commit', 'dfroot-ref', 'dfroot-commit', 'selection'):
        a.add_argument('--' + arg, required=True)
    args = a.parse_args()
    config = json.loads(Path(args.config).read_text())
    manifest = {
        'status': 'candidate_not_device_tested',
        'module_selection': args.selection,
        'kernelsu_next': {'repository': config['kernelsu_next']['repository'], 'requested_ref': args.ksu_ref, 'resolved_commit': args.ksu_commit or None},
        'dfroot': {'repository': config['dfroot']['repository'], 'requested_ref': args.dfroot_ref, 'resolved_commit': args.dfroot_commit},
        'target_kernel': config['target_kernel'],
        'target_fingerprint': config['target_fingerprint'],
        'build_kmi': config['kmi'],
        'ddk_image': config['ddk_image'],
        'module': digest(args.kernel),
        'apk': digest(args.apk),
        'automatic_device_deployment': False,
        'requires_existing_ksud': True,
        'runtime_validation': 'not performed; a CI pass is not proof of compatibility',
    }
    Path(args.out).write_text(json.dumps(manifest, indent=2) + '\n')
    print('Wrote ' + args.out)


if __name__ == '__main__':
    main()
