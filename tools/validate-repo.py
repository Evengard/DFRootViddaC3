#!/usr/bin/env python3
"""Small fail-closed validation of the C3U release configuration."""
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_KERNEL = "5.15.148-android14-11-g7b7674251b5d-dirty"
EXPECTED_FP = "Hisense/VIDAA_TV/MT9655:14/UQ1A.240105.004.A1/07.02.70.202512281739:user/release-keys"


def validate(config):
    assert config['kernelsu_next']['repository'] == 'KernelSU-Next/KernelSU-Next'
    assert config['dfroot']['repository'] == 'diabl0w/DFRoot'
    assert config['kmi'] == 'android14-5.15'
    assert config['target_kernel'] == EXPECTED_KERNEL
    assert config['target_fingerprint'] == EXPECTED_FP
    assert config['ddk_image'] == 'ghcr.io/ylarod/ddk-min:android14-5.15-20260828'
    for section in ('dfroot', 'kernelsu_next'):
        ref = config[section]['ref']
        assert re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}', ref) and '..' not in ref
    loader = (ROOT / 'patches/dfroot/overlay/c3u_ksu_preload.c').read_text()
    assert EXPECTED_KERNEL in loader and EXPECTED_FP in loader
    for name in ('build-and-bundle.sh', 'build-in-docker.sh'):
        assert (ROOT / 'patches/dfroot' / name).is_file()
    assert (ROOT / 'patches/ksunext/patch-selinux.py').is_file()
    for name in ('apply_adb_intent.py', 'C3UAdbRootActivity.java', 'C3UAdbRootAction.java', 'apply_service_worker.py'):
        assert (ROOT / 'patches/dfroot/overlay' / name).is_file()
    for name in ('C3UAdbRootActivity.java','C3URootForegroundService.java'):
        assert (ROOT/'patches/dfroot/service_worker'/name).is_file()
    return True


def main():
    config = json.loads((ROOT / 'config/upstreams.json').read_text())
    validate(config)
    print('PASS: C3U-only firmware lock, KMI, DDK version and essential build files')


if __name__ == '__main__':
    try:
        main()
    except (AssertionError, ValueError, KeyError) as e:
        sys.exit(f'FAIL: invalid config or missing build components: {e}')
