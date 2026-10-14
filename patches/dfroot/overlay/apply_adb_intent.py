#!/usr/bin/env python3
"""Add ADB-protected C3U root launcher and Android-14 foreground process holder.

This keeps the unmodified DFRoot Root button handler running in MainActivity;
it does not port DirtyFrag itself to a background service. Running the APK's
root operation in a service worker would require additional DFRoot refactoring.

    python3 patches/dfroot/overlay/apply_adb_intent.py /path/to/DFRoot
"""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import xml.etree.ElementTree as ET

TAG = 'C3UAdbRootAction.consumeAndRun(this);'
MANIFEST_ACTIVITY = 'df.root.C3UAdbRootActivity'
MANIFEST_SERVICE = 'df.root.C3URootForegroundService'
NS = '{http://schemas.android.com/apk/res/android}'


def method_end(java: str, brace: int) -> int:
    depth = 0
    i = brace
    state = 'code'
    while i < len(java):
        c = java[i]
        n = java[i + 1] if i + 1 < len(java) else ''
        if state == 'code':
            if c == '"': state = 'str'
            elif c == "'": state = 'chr'
            elif c == '/' and n == '/': state = 'line'; i += 1
            elif c == '/' and n == '*': state = 'block'; i += 1
            elif c == '{': depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0: return i
        elif state in ('str', 'chr'):
            if c == '\\': i += 1
            elif c == ('"' if state == 'str' else "'"): state = 'code'
        elif state == 'line':
            if c == '\n': state = 'code'
        elif state == 'block':
            if c == '*' and n == '/': state = 'code'; i += 1
        i += 1
    raise ValueError('Could not parse onCreate method boundaries')


def patch(repo: Path, sources: Path) -> Path:
    java_root = repo / 'app/src/main/java'
    manifest = repo / 'app/src/main/AndroidManifest.xml'
    if not java_root.is_dir() or not manifest.is_file():
        raise ValueError('Missing app/src/main Java sources or AndroidManifest.xml')
    candidates = [p for p in java_root.rglob('MainActivity.java')
                  if re.search(r'\bclass\s+MainActivity\b', p.read_text())]
    if len(candidates) != 1:
        raise ValueError(f'Expected exactly one Java MainActivity, found {len(candidates)}; refusing to guess')
    main = candidates[0]
    text = main.read_text()
    pkg = re.search(r'^\s*package\s+([\w.]+)\s*;', text, re.M)
    if not pkg or pkg.group(1) != 'df.root':
        raise ValueError('Expected DFRoot Java package df.root; unsupported upstream ref')
    match = re.search(r'\bvoid\s+onCreate\s*\(\s*(?:@\w+\s+)*'
                      r'(?:android\.os\.)?Bundle\s+\w+\s*\)\s*\{', text)
    if not match:
        raise ValueError('MainActivity.onCreate(Bundle) not found')
    end = method_end(text, match.end() - 1)
    method = text[match.end():end]
    if not re.search(r'\bsetContentView\s*\(', method):
        raise ValueError('MainActivity.onCreate does not setContentView; cannot reuse Root UI safely')
    if TAG in text:
        if text.count(TAG) != 1: raise ValueError('Duplicate C3U ADB hook found')
    else:
        text = text[:end] + '\n        // C3U_ADB_ROOT: one-time, permission-gated ADB launcher\n        ' + TAG + '\n    ' + text[end:]

    xml = manifest.read_text()
    parsed = ET.fromstring(xml)
    app_nodes = parsed.findall('application')
    if len(app_nodes) != 1:
        raise ValueError('Expected exactly one application element')

    activities = [n for n in app_nodes[0].findall('activity')
                  if n.get(NS + 'name') == MANIFEST_ACTIVITY]
    if len(activities) > 1:
        raise ValueError('Duplicate C3U launcher Activity')
    if activities:
        a = activities[0]
        if (a.get(NS + 'permission') != 'android.permission.DUMP'
                or a.get(NS + 'exported') != 'true'):
            raise ValueError('Manifest contains an unprotected C3U launcher')
        if a.get(NS + 'theme') != '@android:style/Theme.Translucent.NoTitleBar':
            # Upgrade v2's Theme.NoDisplay, which cannot reliably start an FGS
            # as a visible Activity on Android 14.
            if a.get(NS + 'theme') != '@android:style/Theme.NoDisplay':
                raise ValueError('Unexpected launcher theme; not upgrading blindly')
            xml = xml.replace('@android:style/Theme.NoDisplay',
                              '@android:style/Theme.Translucent.NoTitleBar', 1)
    else:
        if xml.count('</application>') != 1:
            raise ValueError('Manifest missing unique closing </application>')
        entry = (f'        <!-- C3U_ADB_ROOT: shell-only, permission-gated visible launcher -->\n'
                 f'        <activity android:name="{MANIFEST_ACTIVITY}"\n'
                 f'                  android:exported="true"\n'
                 f'                  android:permission="android.permission.DUMP"\n'
                 f'                  android:theme="@android:style/Theme.Translucent.NoTitleBar"\n'
                 f'                  android:noHistory="true"\n'
                 f'                  android:excludeFromRecents="true"/>\n')
        xml = xml.replace('</application>', entry + '    </application>', 1)

    parsed = ET.fromstring(xml)
    services = [n for n in parsed.find('application').findall('service')
                if n.get(NS + 'name') == MANIFEST_SERVICE]
    if len(services) > 1:
        raise ValueError('Duplicate C3U foreground service')
    if services:
        svc = services[0]
        if (svc.get(NS + 'exported') != 'false' or
                svc.get(NS + 'foregroundServiceType') != 'specialUse'):
            raise ValueError('Existing C3U service is exported or has wrong FGS type')
    else:
        service_entry = (f'        <!-- C3U_ROOT_FGS: non-exported foreground process holder -->\n'
                         f'        <service android:name="{MANIFEST_SERVICE}"\n'
                         f'                 android:exported="false"\n'
                         f'                 android:stopWithTask="false"\n'
                         f'                 android:foregroundServiceType="specialUse">\n'
                         f'            <property android:name="android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE"\n'
                         f'                      android:value="one_shot_adb_requested_root_operation"/>\n'
                         f'        </service>\n')
        if xml.count('</application>') != 1:
            raise ValueError('Manifest missing unique closing </application>')
        xml = xml.replace('</application>', service_entry + '    </application>', 1)

    for permission in ('android.permission.FOREGROUND_SERVICE',
                       'android.permission.FOREGROUND_SERVICE_SPECIAL_USE'):
        parsed = ET.fromstring(xml)
        hits = [n for n in parsed.findall('uses-permission') if n.get(NS + 'name') == permission]
        if len(hits) > 1:
            raise ValueError(f'Duplicate permission: {permission}')
        if not hits:
            if xml.count('<application') != 1:
                raise ValueError('Manifest missing unique opening application')
            xml = xml.replace('<application',
                              f'<uses-permission android:name="{permission}" />\n    <application', 1)

    parsed = ET.fromstring(xml)
    permissions = {n.get(NS + 'name') for n in parsed.findall('uses-permission')}
    if not {'android.permission.FOREGROUND_SERVICE',
            'android.permission.FOREGROUND_SERVICE_SPECIAL_USE'} <= permissions:
        raise ValueError('Foreground service permissions not installed')

    bridge_path = main.with_name('C3UAdbRootActivity.java')
    action_path = main.with_name('C3UAdbRootAction.java')
    service_path = main.with_name('C3URootForegroundService.java')
    for dest in (bridge_path, action_path, service_path):
        if dest.exists() and 'C3U' not in dest.read_text():
            raise ValueError(f'Refusing to overwrite unrelated file {dest}')
        if not (sources / dest.name).is_file():
            raise ValueError(f'Missing bundled source {dest.name}')

    # All structural checks passed: apply atomically enough for a fresh checkout.
    main.write_text(text)
    manifest.write_text(xml)
    bridge_path.write_bytes((sources / bridge_path.name).read_bytes())
    action_path.write_bytes((sources / action_path.name).read_bytes())
    service_path.write_bytes((sources / service_path.name).read_bytes())
    return main


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dfroot', type=Path)
    args = parser.parse_args()
    try:
        path = patch(args.dfroot.resolve(), Path(__file__).resolve().parent)
    except (OSError, ValueError, ET.ParseError) as exc:
        parser.exit(1, f'ADB intent + FGS patch refused: {exc}\n')
    print(f'C3U protected ADB launcher + foreground process holder installed: {path}')
    print('Trigger: adb shell am start -n df.root/.C3UAdbRootActivity')
    print('Monitor: adb logcat -s C3UAdbRoot:I C3URootService:I')
    print('Verify separately: adb shell su -c id')


if __name__ == '__main__':
    main()
