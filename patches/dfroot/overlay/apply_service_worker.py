#!/usr/bin/env python3
"""Upgrade DFRoot v3.1 ADB launcher from UI clicking to a service-owned worker.

Requires apply_adb_intent.py to have run first. Checks the exact reviewed
upstream ExploitRunner.java supplied by the GitHub Actions source artifact.
Does not modify upstream exploit sequencing or native C/JNI.
"""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

UPSTREAM_RUNNER_SHA256 = 'f34c93dddca5eeaf1eb01c44db2cdd031640f57e9ea07781d66b1a5f361992ae'
UI_HOOK = 'C3UAdbRootAction.consumeAndRun(this);'
OWNER_MARKER = '// C3U_SERVICE_OWNS_ROOT: one-shot exploit runs on service worker'
NS = '{http://schemas.android.com/apk/res/android}'


def patch(repo: Path, patchdir: Path) -> None:
    java = repo / 'app/src/main/java/df/root'
    main = java / 'MainActivity.java'
    runner = java / 'ExploitRunner.java'
    manifest = repo / 'app/src/main/AndroidManifest.xml'
    target_activity = java / 'C3UAdbRootActivity.java'
    target_service = java / 'C3URootForegroundService.java'
    legacy_action = java / 'C3UAdbRootAction.java'
    for p in (main, runner, manifest, target_activity, target_service):
        if not p.is_file():
            raise ValueError(f'Missing expected DFRoot v3.1 source or stage-04 patch: {p}')
    actual = hashlib.sha256(runner.read_bytes()).hexdigest()
    if actual != UPSTREAM_RUNNER_SHA256:
        raise ValueError('ExploitRunner.java differs from reviewed upstream v3.1: ' + actual)
    src = runner.read_text()
    required = ('public static int run(Context ctx, IReporter reporter)',
                'IpSecManager', 'IpSecTransform', 'return runBinary(bin, reporter,',
                'transform.close();', 'spiObj.close();', 'encapSock.close();')
    if any(s not in src for s in required):
        raise ValueError('ExploitRunner API or resource lifetime differs from reviewed source')
    root = ET.parse(manifest).getroot()
    app = root.find('application')
    if app is None:
        raise ValueError('Missing manifest application')
    act = [a for a in app.findall('activity')
           if a.get(NS+'name') == 'df.root.C3UAdbRootActivity']
    svc = [s for s in app.findall('service')
           if s.get(NS+'name') == 'df.root.C3URootForegroundService']
    if len(act) != 1 or len(svc) != 1 or (act[0].get(NS+'exported') != 'true'
            or act[0].get(NS+'permission') != 'android.permission.DUMP'
            or svc[0].get(NS+'exported') != 'false'
            or svc[0].get(NS+'foregroundServiceType') != 'specialUse'):
        raise ValueError('ADB Activity / FGS manifest protection is unexpected')
    text = main.read_text()
    if UI_HOOK in text:
        if text.count(UI_HOOK) != 1:
            raise ValueError('Expected a single legacy UI dispatch hook')
        text = text.replace(UI_HOOK, OWNER_MARKER, 1)
    elif OWNER_MARKER not in text:
        raise ValueError('Neither legacy UI hook nor new service marker was found')
    if UI_HOOK in text:
        raise ValueError('MainActivity still auto-clicks Root')

    if legacy_action.exists() and 'public final class C3UAdbRootAction' not in legacy_action.read_text():
        raise ValueError('Refusing to remove unexpected UI action source')

    # All validations succeeded; mutate only the patch-generated files.
    for name in ('C3UAdbRootActivity.java', 'C3URootForegroundService.java'):
        content = (patchdir/name).read_text()
        if 'package df.root;' not in content or 'C3U' not in content:
            raise ValueError(f'Bundled Java source looks incorrect: {name}')
    main.write_text(text)
    for name in ('C3UAdbRootActivity.java', 'C3URootForegroundService.java'):
        (java/name).write_bytes((patchdir/name).read_bytes())
    # Previous source was used solely to synthesize an Activity UI click.
    if legacy_action.exists():
        legacy_action.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dfroot', type=Path)
    args = parser.parse_args()
    try:
        patch(args.dfroot.resolve(), Path(__file__).resolve().parent.parent / 'service_worker')
    except (OSError, ValueError, ET.ParseError) as e:
        parser.exit(1, f'C3U service-worker migration refused: {e}\n')
    print('PASS: C3U ADB Activity starts FGS; FGS owns ExploitRunner.run() directly')
    print('No UI Root-click hook remains; upstream IPsec and native process lifecycle is unchanged')


if __name__ == '__main__':
    main()
